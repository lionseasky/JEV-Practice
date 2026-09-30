"""S06 大而杂的 state 会稀释准确率。

目标：量化「不要图省事把整个上下文塞进去」这条官方建议。
副作用很重要：Jev 按输入 token 计费，塞噪音既伤准确率又多花钱。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import choice, noul, score
from .base import Ctx, V_DEFECT, V_INFO, V_OK, V_WARN, check, mean, result

SUITE = "S06"
TITLE = "噪音稀释：state 规模对准确率与成本的双重影响"
HYPOTHESIS = (
    "同一组问题，在干净 state 与掺入大量无关文本的 state 上，答案会漂移、confidence 会下降，"
    "同时输入 token 与成本成倍上涨。"
)
OFFICIAL = (
    "大而杂的 state 会拉低准确率。官方建议先过滤，只发问题真正需要的那部分内容。"
    "同时 Jev 按输入 token 计费（$42/Btok，输出免费），所以噪音是「准确性 + 成本」的双重损失。"
)

TICKET = (
    "Customer message: I was charged twice for the same order this month, "
    "and support has not replied in 5 days. I want this fixed today or I am "
    "disputing the charge with my bank."
)

QUESTIONS = {
    "intent": choice(
        "Which team should handle this",
        {
            "billing": "Payment, invoice or charge issues",
            "technical": "Bugs, login or integration problems",
            "sales": "Pricing or account questions",
        },
    ),
    "frustration": score(
        "How frustrated does the customer appear",
        ["Calm", "Mildly annoyed", "Frustrated", "Very angry, threatening action"],
    ),
    "urgent": noul("Does the customer demand action within a specific short deadline?"),
}

# 一段与工单无关的运营日志噪音（约 40 tokens）
NOISE_UNIT = (
    "2026-09-28 03:14:22 INFO  scheduler: nightly compaction finished in 812ms, "
    "rows_merged=41902, segments=17, disk_free=64%, region=cn-north-1, "
    "checkpoint_ok=true, next_run=2026-09-29T03:00:00Z, trace_id=ab9f21c7. "
)


def _build_noisy_state(repeat: int) -> str:
    if repeat <= 0:
        return TICKET
    return "=== 无关系统日志（与工单无关） ===\n" + (NOISE_UNIT * repeat) + "\n=== 工单正文 ===\n" + TICKET


def _snapshot(resp) -> Dict[str, Any]:
    if not resp:
        return {}
    return {
        "intent": resp.answers["intent"].choice,
        "intent_confidence": resp.answers["intent"].confidence,
        "frustration": resp.answers["frustration"].score,
        "frustration_confidence": resp.answers["frustration"].confidence,
        "urgent": resp.answers["urgent"].noul,
        "input_tokens": resp.input_tokens,
    }


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    repeat_mid = int(ctx.config.data.get("noise_repeat_mid", 60))
    repeat_large = int(ctx.config.data.get("noise_repeat_large", 260))

    r_clean = ctx.ask(SUITE, "s06_clean", TICKET, dict(QUESTIONS), note="干净 state（基线）")
    r_mid = ctx.ask(SUITE, "s06_noise_mid", _build_noisy_state(repeat_mid), dict(QUESTIONS),
                    note="注入 %d 段无关日志" % repeat_mid)
    r_large = ctx.ask(SUITE, "s06_noise_large", _build_noisy_state(repeat_large), dict(QUESTIONS),
                      note="注入 %d 段无关日志" % repeat_large)

    snaps = {
        "干净": _snapshot(r_clean),
        "中等噪音(%d段)" % repeat_mid: _snapshot(r_mid),
        "大量噪音(%d段)" % repeat_large: _snapshot(r_large),
    }
    checks.append(check("三种 state 下的答案快照", V_INFO, snaps,
                        "关注 intent 是否翻转、confidence 是否下降、token 是否暴涨"))

    if r_clean:
        base_intent = snaps["干净"].get("intent")
        base_conf = snaps["干净"].get("intent_confidence")

        flips = []
        for label in list(snaps.keys())[1:]:
            s = snaps[label]
            if not s:
                continue
            if s.get("intent") != base_intent:
                flips.append({"场景": label, "从": base_intent, "变为": s.get("intent")})
        checks.append(
            check(
                "intent 答案是否被噪音改变",
                V_OK if not flips else V_DEFECT,
                {"翻转次数": len(flips), "明细": flips},
                "翻转即复现官方缺陷 #5；未翻转只能说这段噪音还不够干扰，不能反证",
            )
        )

        conf_deltas = {}
        for label in list(snaps.keys())[1:]:
            s = snaps[label]
            if s.get("intent_confidence") is not None and base_conf is not None:
                conf_deltas[label] = round(s["intent_confidence"] - base_conf, 4)
        checks.append(
            check(
                "intent confidence 随噪音的变化",
                V_INFO if conf_deltas else V_WARN,
                {"基线": base_conf, "变化": conf_deltas},
                "即使答案不翻转，confidence 下滑也是有用的预警信号",
            )
        )

        tok_clean = snaps["干净"].get("input_tokens") or 0
        cost_rows = []
        for label in snaps:
            tok = snaps[label].get("input_tokens") or 0
            cost_rows.append(
                {
                    "场景": label,
                    "input_tokens": tok,
                    "相对基线倍数": round(tok / tok_clean, 2) if tok_clean else None,
                    "单次成本_usd": round(tok * 0.042 / 1e6, 8),
                    "每万次成本_usd": round(tok * 0.042 / 1e6 * 10000, 4),
                }
            )
        checks.append(
            check(
                "噪音的 token 与成本代价",
                V_INFO,
                cost_rows,
                "把这张表贴在代码评审里，比讲道理更能说服人先做 state 过滤",
            )
        )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "结论应当是一条硬规矩：state 只发问题需要的那部分。"
            "过滤在前，判断在后；省下的是准确率和真金白银两样东西。"
        ),
    )
