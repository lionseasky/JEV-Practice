"""S09 性能、并发、版本与成本。

目标：拿到真实数字来算账 —— 延迟能不能接进你的链路、并发能扛多少、
以及在你的调用量下一个月要花多少钱。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from ..client import noul
from .base import Ctx, V_INFO, V_OK, V_WARN, check, mean, percentile, result

SUITE = "S09"
TITLE = "性能、并发、版本与成本"
HYPOTHESIS = "延迟通常在亚秒级；问题扇出几乎不增加延迟；成本只与输入 token 相关且非常低。"
OFFICIAL = (
    "典型延迟通常在半秒以内。限速 250,000 token/秒 与 1,200 请求/分钟，超限返回 429（可能随时调整）。"
    "计费仅按输入 token，$42/Btok（约 $0.042/Mtok），输出 token 免费。"
)

SMALL_STATE = "Ticket: customer cannot log in since the update."
MEDIUM_STATE = SMALL_STATE + (" Additional context: " + "user reported the same issue last week. " * 40)
LARGE_STATE = SMALL_STATE + (" Additional context: " + "user reported the same issue last week. " * 400)


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    # ---------------- 1. 扇出对延迟的影响 ----------------
    lat_by_count: Dict[str, Any] = {}
    for count in (1, 8, 16):
        q = {"q%d" % i: noul("Does the message mention topic %d?" % i) for i in range(count)}
        t0 = time.perf_counter()
        r = ctx.ask(SUITE, "s09_fanout_%d" % count, MEDIUM_STATE, q,
                    note="同一 state 下问 %d 个问题" % count)
        wall = (time.perf_counter() - t0) * 1000.0
        if r:
            lat_by_count["%d问" % count] = {
                "服务端延迟_ms": r.latency_ms,
                "端到端_ms": round(wall, 1),
                "input_tokens": r.input_tokens,
            }
    if lat_by_count:
        checks.append(check("问题数量 vs 延迟（state 固定）", V_INFO, lat_by_count,
                            "官方称 state 只读入一次、问题并行评估；曲线越平越好"))

    # ---------------- 2. state 规模对延迟与成本的影响 ----------------
    size_rows = []
    for label, state in (("小(~15 tokens)", SMALL_STATE),
                         ("中(~450 tokens)", MEDIUM_STATE),
                         ("大(~4400 tokens)", LARGE_STATE)):
        r = ctx.ask(SUITE, "s09_size_%s" % label.split("(")[0], state,
                    {"q": noul("Is the customer unable to log in?")},
                    note="state 规模：%s" % label)
        if r:
            size_rows.append({
                "state规模": label,
                "服务端延迟_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "单次成本_usd": round(r.input_tokens * 0.042 / 1e6, 8),
                "每百万次调用_usd": round(r.input_tokens * 0.042 / 1e6 * 1_000_000, 2),
            })
    if size_rows:
        checks.append(check("state 规模 vs 延迟与成本", V_INFO, size_rows,
                            "成本随输入线性增长；延迟通常远不如成本敏感"))

    # ---------------- 3. 并发吞吐 ----------------
    conc_rows = []
    for level in ctx.config.data.get("concurrency_levels", [1, 4, 16]):
        n = max(level * 2, 4)
        questions = {"q": noul("Does the message mention logging in?")}

        def _one(idx: int):
            return ctx.ask(SUITE, "s09_conc_%d_%d" % (level, idx), MEDIUM_STATE, dict(questions),
                           note="并发档位 %d 的第 %d 个请求" % (level, idx))

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=level) as pool:
            list(pool.map(_one, range(n)))
        wall = time.perf_counter() - t0
        conc_rows.append({
            "并发度": level,
            "请求数": n,
            "总耗时_s": round(wall, 2),
            "吞吐_req/s": round(n / wall, 2) if wall else None,
        })
    if conc_rows:
        checks.append(check("并发度 vs 吞吐", V_INFO, conc_rows,
                            "关注是否出现 429；官方限速为 1200 请求/分钟，动态可调，别写死进重试逻辑"))

    # ---------------- 4. 延迟分布 ----------------
    repeats = int(ctx.config.data.get("perf_repeats", 3))
    latencies: List[float] = []
    for i in range(repeats):
        r = ctx.ask(SUITE, "s09_latency_%d" % i, SMALL_STATE,
                    {"q": noul("Does the customer cannot log in?")},
                    note="延迟采样 %d" % (i + 1))
        if r:
            latencies.append(r.latency_ms)
    if latencies:
        checks.append(
            check(
                "冷启动/延迟分位（样本少，仅供参考）",
                V_INFO,
                {"样本": [round(v, 1) for v in latencies],
                 "min_ms": round(min(latencies), 1),
                 "p50_ms": percentile(latencies, 0.5),
                 "max_ms": round(max(latencies), 1),
                 "注意": "样本量仅 %d，要下生产结论请加大采样" % len(latencies)},
                "第一次调用的延迟明显偏高是正常的（连接建立 + 冷启动）",
            )
        )

    # ---------------- 5. 版本与别名 ----------------
    versions = set()
    for case in ctx.cases:
        if case["suite"] == SUITE and case["response_model"]:
            versions.add(case["response_model"])
    checks.append(
        check(
            "本次实测响应里出现过的 model 版本",
            V_OK if versions else V_WARN,
            sorted(versions),
            "官方声明别名会随新版发布漂移。生产环境请把版本号写死，并把这个字段记进日志",
        )
    )

    # ---------------- 6. 成本总账 ----------------
    stats = ctx.client.stats
    total_input = stats.get("input_tokens", 0)
    total_output = stats.get("output_tokens", 0)
    cost = total_input * 0.042 / 1e6
    checks.append(
        check(
            "整轮摸底的总 token 与总成本",
            V_INFO,
            {
                "请求数": stats.get("requests", 0),
                "重试次数": stats.get("retries", 0),
                "错误数": stats.get("errors", 0),
                "HTTP 状态分布": stats.get("status_counts", {}),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "总成本_usd": round(cost, 6),
                "总成本_人民币约": round(cost * 7.2, 4),
            },
            "这是「先花钱摸清能力再谈投入」的实价；对照一下：整轮摸底通常不到一杯咖啡",
        )
    )
    if ctx.client.is_mock:
        checks.append(check("注意", V_WARN, "本次为 MOCK 模式，以上数字全部是伪造的",
                            "加 --mock 只用于验证报告管线，不代表 Jev 的任何真实表现"))

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "把这里的数字代进你自己的调用量，就能算出每月的固定成本。"
            "延迟和成本都很低，真正的风险在准确率和中文表现，不在性能。"
        ),
    )
