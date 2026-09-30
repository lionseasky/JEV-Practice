"""报告生成：Markdown（给人看）+ JSON（给机器/回归用）。"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime
from typing import Any, Dict, List

from . import OFFICIAL, __version__
from .suites.base import V_DEFECT, V_ERROR, V_INFO, V_WARN

VERDICT_BADGE = {
    "符合预期": "✅",
    "缺陷复现": "🔴",
    "未见缺陷": "🟢",
    "已测量": "📊",
    "需注意": "⚠️",
    "调用失败": "❌",
}


def _badge(verdict: str) -> str:
    return VERDICT_BADGE.get(verdict, "•")


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _count_verdicts(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for res in results:
        for c in res["checks"]:
            counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    return counts


def build_markdown(
    meta: Dict[str, Any],
    results: List[Dict[str, Any]],
    cases: List[Dict[str, Any]],
    max_cases_per_suite: int = 4,
) -> str:
    lines: List[str] = []
    mock_banner = ""
    if meta.get("mock"):
        mock_banner = (
            "\n> ⚠️ **本次为 MOCK 离线模式，所有数字都是伪造的**，仅用于验证报告管线是否正常。\n"
            "> 请填好 API Key 后重新运行 `python3 run.py` 获取真实测量。\n"
        )

    lines.append("# Jev（TypeSafe System One）能力摸底报告")
    lines.append("")
    lines.append("> 由 `jev-probe` v%s 自动生成 · %s" % (__version__, meta["generated_at"]))
    lines.append(mock_banner)

    # ---------------- 元信息
    lines.append("## 0. 运行信息")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 运行模式 | %s |" % ("MOCK 离线自检（数据伪造）" if meta.get("mock") else "真实调用"))
    lines.append("| 请求的模型别名 | `%s` |" % meta.get("model_alias"))
    lines.append("| 响应中实际出现的模型 ID | `%s` |" % ", ".join(meta.get("observed_models") or []) or "—")
    lines.append("| 接口地址 | `%s` |" % meta.get("base_url"))
    lines.append("| Key 来源 | %s |" % meta.get("key_source"))
    lines.append("| 执行套件 | %s |" % ", ".join(r["id"] for r in results))
    lines.append("| 总请求数 | %s |" % meta["stats"].get("requests"))
    lines.append("| 重试次数 | %s |" % meta["stats"].get("retries"))
    lines.append("| HTTP 状态分布 | `%s` |" % json.dumps(meta["stats"].get("status_counts", {}), ensure_ascii=False))
    lines.append("| 累计输入 token | %s |" % meta["stats"].get("input_tokens"))
    lines.append("| 累计输出 token | %s |" % meta["stats"].get("output_tokens"))
    lines.append("| 累计成本（仅输入计费） | $%.6f |" % meta["cost_usd"])
    lines.append("| Python | %s |" % meta.get("python"))
    lines.append("| 平台 | %s |" % meta.get("platform"))
    lines.append("")

    # ---------------- 判读摘要
    counts = _count_verdicts(results)
    lines.append("## 1. 判读摘要")
    lines.append("")
    order = ["符合预期", "缺陷复现", "未见缺陷", "已测量", "需注意", "调用失败"]
    lines.append("| 判读 | 条数 | 含义 |")
    lines.append("| --- | --- | --- |")
    meaning = {
        "符合预期": "行为与官方文档/预期一致",
        "缺陷复现": "复现了官方公布的失效场景（对摸底而言是有价值的结论）",
        "未见缺陷": "本套件未能复现预期中的缺陷",
        "已测量": "信息性数据，无对错",
        "需注意": "偏离预期或需要人工介入判断",
        "调用失败": "请求本身失败（鉴权/校验/限速/网络）",
    }
    for key in order:
        if counts.get(key):
            lines.append("| %s %s | %d | %s |" % (_badge(key), key, counts[key], meaning[key]))
    lines.append("")

    # 自动列出需要注意 / 复现缺陷的条目
    highlights: List[str] = []
    for res in results:
        for c in res["checks"]:
            if c["verdict"] in (V_DEFECT, V_WARN, V_ERROR):
                highlights.append("- **%s %s · %s** → `%s`" % (
                    _badge(c["verdict"]), res["id"], c["name"], _fmt(c["value"])))
    if highlights:
        lines.append("### 需要你重点关注的条目")
        lines.append("")
        lines.extend(highlights)
        lines.append("")
    else:
        lines.append("### 需要你重点关注的条目")
        lines.append("")
        lines.append("- 无。所有条目均为「符合预期」或信息性数据。")
        lines.append("")

    # ---------------- 逐套件
    lines.append("## 2. 逐套件明细")
    lines.append("")
    for res in results:
        lines.append("### %s %s" % (res["id"], res["title"]))
        lines.append("")
        lines.append("- **假设**：%s" % res["hypothesis"])
        lines.append("- **官方基线**：%s" % res["official_baseline"])
        lines.append("")
        for c in res["checks"]:
            lines.append("**%s %s · %s**" % (_badge(c["verdict"]), c["verdict"], c["name"]))
            lines.append("")
            lines.append("- 数值：`%s`" % _fmt(c["value"]))
            if c.get("note"):
                lines.append("- 说明：%s" % c["note"])
            lines.append("")
        if res.get("summary"):
            lines.append("> %s" % res["summary"])
            lines.append("")

        suite_cases = [c for c in cases if c["suite"] == res["id"]]
        if suite_cases:
            lines.append("<details><summary>代表用例样本（共 %d 次调用，展示前 %d 条）</summary>"
                         % (len(suite_cases), min(len(suite_cases), max_cases_per_suite)))
            lines.append("")
            for case in suite_cases[:max_cases_per_suite]:
                lines.append("- `%s`%s" % (case["case_id"], ("（%s）" % case["note"]) if case.get("note") else ""))
                lines.append("  - state：`%s`" % case["state_preview"][:200])
                lines.append("  - 问题：`%s`" % _fmt(list(case["questions"].keys())))
                if case["ok"]:
                    lines.append("  - 答案：`%s`" % _fmt(case["answers"]))
                    lines.append("  - 延迟：%s ms ｜ input_tokens：%s"
                                 % (case["latency_ms"], (case["usage"] or {}).get("input_tokens")))
                else:
                    lines.append("  - ❌ 失败：%s" % case["error"])
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # ---------------- 附录
    lines.append("## 3. 附录：官方参数基线（用于对照）")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 模型 ID | `%s` |" % OFFICIAL["model_id"])
    lines.append("| 别名 | `jev-latest` / `jev-preview` → `%s` |" % OFFICIAL["model_id"])
    lines.append("| 计费 | 仅输入 token，$%s/Btok（约 $%s/Mtok），输出免费 |"
                 % (OFFICIAL["price_usd_per_btok_input"], OFFICIAL["price_usd_per_mtok_input"]))
    lines.append("| 限速 | %s token/s，%s 请求/分钟（官方声明会动态调整） |"
                 % ("{:,}".format(OFFICIAL["rate_limit_tokens_per_second"]),
                    "{:,}".format(OFFICIAL["rate_limit_requests_per_minute"])))
    lines.append("| 上下文 | 单请求 %s token；state + 最长单问题 %s token |"
                 % ("{:,}".format(OFFICIAL["context_tokens_total"]),
                    "{:,}".format(OFFICIAL["context_tokens_state_plus_longest_question"])))
    lines.append("| 输入形态 | 仅文本（字符串 / JSON 对象 / 文本数组），不支持图像音频视频 |")
    lines.append("")
    lines.append("### 官方公布的九类失效场景")
    lines.append("")
    lines.append("| # | 失效场景 |")
    lines.append("| --- | --- |")
    for num, desc in sorted(OFFICIAL["failure_modes"].items()):
        lines.append("| %d | %s |" % (num, desc))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> 本报告中「缺陷复现」指实测行为与官方 *Jev 1.13 jaggedness* 页面公布的失效场景一致，"
                 "是能力边界证据，不是产品缺陷报告。")
    lines.append("> 官方文档：https://docs.typesafe.ai/ ｜ 失效场景：https://docs.typesafe.ai/model-jaggedness/jev-1.13")

    return "\n".join(lines)


def build_json(meta: Dict[str, Any], results: List[Dict[str, Any]], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "probe_version": __version__,
        "meta": meta,
        "official_baseline": OFFICIAL,
        "results": results,
        "cases": cases,
        "verdict_counts": _count_verdicts(results),
    }
