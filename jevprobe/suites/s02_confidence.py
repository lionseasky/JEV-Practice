"""S02 置信度机制。

目标：搞清 confidence 到底是什么形状的数、能不能当门控阈值用，
以及"模型不确定"时它是否真的会告诉你。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import choice, noul
from .base import Ctx, V_DEFECT, V_INFO, V_OK, V_WARN, check, mean, result

SUITE = "S02"
TITLE = "置信度机制与门控可用性"
HYPOTHESIS = (
    "choice 的 confidence 可由 (n*p-1)/(n-1) 复算；输入越模糊/越无关，confidence 越低；"
    "criteria 互相重叠会把 confidence 拉低。"
)
OFFICIAL = (
    "confidence 是概率分布的统计量，取值 0~1，只有 choice/score 有。"
    "choice 的算法为 (n*p - 1) / (n - 1)：完全平均时为 0，某项为 1 时为 1。"
    "官方推荐三档用法：高置信自动执行 / 中置信先确认 / 低置信转人工。"
    "noul 不携带 confidence，0.5 表示是与否等概率。"
)

INTENTS = {
    "billing": "Payment, invoice or subscription issues",
    "technical": "Bugs, login or integration problems",
    "sales": "Pricing or account questions",
}
Q_INTENT = choice("Which team should handle this", INTENTS)


def _recompute_confidence(probabilities: Dict[str, float]) -> Any:
    probs = list((probabilities or {}).values())
    n = len(probs)
    if n < 2:
        return None
    p = max(probs)
    return round((n * p - 1) / (n - 1), 4)


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    # ---- 1. 复算官方公式
    resp = ctx.ask(
        SUITE,
        "s02_formula",
        "My invoice shows a $49 charge for a subscription I cancelled in January.",
        {"intent": dict(Q_INTENT)},
        note="用返回的 probabilities 反算 confidence，对照官方公式",
    )
    if resp:
        ans = resp.answers["intent"]
        recomputed = _recompute_confidence(ans.probabilities)
        returned = ans.confidence
        match = (
            recomputed is not None
            and returned is not None
            and abs(recomputed - returned) <= 0.005
        )
        checks.append(
            check(
                "confidence 可由 (n*p-1)/(n-1) 复算",
                V_OK if match else V_DEFECT,
                {"returned": returned, "recomputed": recomputed},
                "不吻合说明官方算法有变，或 probabilities 与 confidence 不同源",
            )
        )

    # ---- 2. 清晰 / 模糊 / 无关：confidence 是否单调下降
    clear_state = (
        "My invoice shows a $49 charge on March 3 for a subscription I cancelled in "
        "January. I want to know why I was charged."
    )
    ambiguous_state = "I can't get in and my card was declined. Please sort it out."
    irrelevant_state = "Purple elephants are dancing in a thunderstorm over the harbor."

    r_clear = ctx.ask(SUITE, "s02_clear", clear_state, {"intent": dict(Q_INTENT)}, note="意图非常清晰")
    r_ambig = ctx.ask(SUITE, "s02_ambiguous", ambiguous_state, {"intent": dict(Q_INTENT)}, note="两条线交织，含糊")
    r_irrel = ctx.ask(SUITE, "s02_irrelevant", irrelevant_state, {"intent": dict(Q_INTENT)}, note="与选项完全无关")

    confs = {}
    if r_clear and r_ambig and r_irrel:
        confs = {
            "清晰": r_clear.answers["intent"].confidence,
            "模糊": r_ambig.answers["intent"].confidence,
            "无关": r_irrel.answers["intent"].confidence,
        }
        ordered = (
            confs["清晰"] is not None
            and confs["模糊"] is not None
            and confs["无关"] is not None
            and confs["清晰"] >= confs["模糊"] >= confs["无关"]
        )
        checks.append(
            check(
                "confidence 随输入质量单调下降（清晰 ≥ 模糊 ≥ 无关）",
                V_OK if ordered else V_WARN,
                confs,
                "这是 confidence 能当门控用的前提；不单调则阈值策略要重新设计",
            )
        )

        chosen = {
            "清晰": r_clear.answers["intent"].choice,
            "模糊": r_ambig.answers["intent"].choice,
            "无关": r_irrel.answers["intent"].choice,
        }
        checks.append(
            check("三档输入各自选了哪个选项", V_INFO, chosen,
                  "关注'无关'输入是否仍硬选一个选项——低 confidence 是唯一的安全网"),
        )

    # ---- 3. criteria 互相重叠（官方失效场景 #7）
    overlap_q = choice(
        "Which team should handle this",
        {
            "billing": "Anything related to money, including payment failures",
            "technical": "Anything related to the product, including payment failures",
            "sales": "Anything else, including money and product topics",
        },
    )
    r_overlap = ctx.ask(
        SUITE,
        "s02_overlapping_criteria",
        clear_state,
        {"intent": overlap_q},
        note="故意让三个选项互相重叠",
    )
    if r_overlap and confs:
        overlap_conf = r_overlap.answers["intent"].confidence
        drop = (
            round(confs["清晰"] - overlap_conf, 4)
            if overlap_conf is not None and confs.get("清晰") is not None
            else None
        )
        checks.append(
            check(
                "criteria 重叠会把 confidence 拉低",
                V_OK if (drop is not None and drop > 0.05) else V_INFO,
                {"清晰输入+清晰criteria": confs.get("清晰"), "清晰输入+重叠criteria": overlap_conf,
                 "下降": drop},
                "confidence 对 criteria 质量敏感 → 它是你评测 criteria 写得好不好的免费信号",
            )
        )

    # ---- 4. 一批混合输入的 confidence 分布，给出阈值区间建议
    batch = [
        ("b1", "Where is my refund? It has been two weeks.", "高"),
        ("b2", "I was double charged on the 3rd and again on the 5th.", "高"),
        ("b3", "The app crashes when I upload a PDF.", "高"),
        ("b4", "It does not work.", "中"),
        ("b5", "Something is off with my account, not sure what.", "中"),
        ("b6", "ok", "低"),
        ("b7", "hello?", "低"),
        ("b8", "asdfasdf", "低"),
    ]
    dist: Dict[str, List[float]] = {"高": [], "中": [], "低": []}
    for case_id, state, difficulty in batch:
        r = ctx.ask(SUITE, "s02_batch_" + case_id, state, {"intent": dict(Q_INTENT)},
                    note="难度标注：%s" % difficulty)
        if r:
            c = r.answers["intent"].confidence
            if c is not None:
                dist[difficulty].append(c)

    if any(dist.values()):
        checks.append(
            check(
                "confidence 分布（按输入信息量分档）",
                V_INFO,
                {k: {"均值": mean(v), "样本": v} for k, v in dist.items()},
                "用实测分布来定阈值，而不是照抄官方的 0.5/0.9",
            )
        )
        highs, lows = dist["高"], dist["低"]
        if highs and lows:
            separable = mean(highs) > mean(lows)
            checks.append(
                check(
                    "高信息量输入与垃圾输入的 confidence 是否可分",
                    V_OK if separable else V_WARN,
                    {"高信息量均值": mean(highs), "垃圾输入均值": mean(lows),
                     "差值": round((mean(highs) or 0) - (mean(lows) or 0), 4)},
                    "可分 → 可以用单一阈值做路由；不可分 → 需要按意图分别标定阈值",
                )
            )

    # ---- 5. noul 的 0.5 语义确认
    r_tie = ctx.ask(
        SUITE,
        "s02_noul_tie",
        "The user said: 'maybe, we will see'.",
        {"is_committed": noul("Does the user commit to a decision?")},
        note="noul 在真正含糊时应落在 0.5 附近",
    )
    if r_tie:
        v = r_tie.answers["is_committed"].noul
        checks.append(
            check(
                "noul 在含糊输入上是否落在 0.5 附近",
                V_OK if (v is not None and 0.3 <= v <= 0.7) else V_INFO,
                {"noul": v},
                "noul 的 0.5 表示是与否等概率，不表示'中等程度'——别拿它当打分用",
            )
        )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary="confidence 的唯一正确用法是做门控，不是当准确率看。先实测分布，再定阈值。",
    )
