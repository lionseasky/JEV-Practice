"""S01 原语形态与返回契约。

目标：在写任何业务代码之前，先确认 Jev 的三种答案形态与官方文档一致，
并搞清"一个请求可以并行问多个问题"这件事的真实代价。
"""

from __future__ import annotations

from typing import Any, Dict

from ..client import choice, noul, score
from .base import Ctx, V_DEFECT, V_INFO, V_OK, V_WARN, check, mean, result

SUITE = "S01"
TITLE = "原语形态与返回契约"
HYPOTHESIS = "choice/score/noul 各自返回文档承诺的字段；question key 不参与推理；多问题扇出几乎不增加延迟。"
OFFICIAL = (
    "noul 只返回 noul（0~1，无 confidence）；choice 返回 choice/probabilities/confidence；"
    "score 返回 score/legend/probabilities/confidence。key 不发送给模型、不参与推理。"
    "Jev 读入 state 一次后并行评估所有问题。"
)

TICKET = (
    "Hi, I've been trying to connect my Stripe account for 3 days and the "
    "integration keeps failing. I'm losing sales. Please help ASAP."
)


def run(ctx: Ctx) -> Dict[str, Any]:
    checks = []

    # ---- 1. 一次请求同时问三种类型，看返回契约
    resp = ctx.ask(
        SUITE,
        "s01_three_types",
        TICKET,
        {
            "department": choice(
                "Which team should handle this",
                {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            ),
            "frustration": score(
                "How frustrated the customer appears",
                ["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
            ),
            "is_urgent": noul("The message conveys urgency or time-sensitivity"),
        },
        note="官方示例原样复刻：三种类型一次问完",
    )

    if resp:
        dep, fru, urg = resp.answers.get("department"), resp.answers.get("frustration"), resp.answers.get("is_urgent")

        # choice 契约
        ok_choice = bool(
            dep
            and dep.type == "choice"
            and dep.choice
            and dep.probabilities
            and dep.confidence is not None
        )
        prob_sum = round(sum((dep.probabilities or {}).values()), 3) if dep else None
        checks.append(
            check(
                "choice 返回 choice + probabilities + confidence",
                V_OK if ok_choice else V_WARN,
                {"choice": dep.choice if dep else None, "confidence": dep.confidence if dep else None},
                "概率和 = %s（应≈1.0）" % prob_sum,
            )
        )
        checks.append(
            check(
                "choice 概率是否归一化",
                V_OK if prob_sum and abs(prob_sum - 1.0) < 0.02 else V_WARN,
                prob_sum,
                "明显偏离 1.0 说明返回的 probabilities 不是标准分布",
            )
        )

        # score 契约
        legend = fru.legend if fru else None
        ok_score = bool(
            fru and fru.type == "score" and fru.score is not None and legend and fru.confidence is not None
        )
        checks.append(
            check(
                "score 返回 score + legend + probabilities + confidence",
                V_OK if ok_score else V_WARN,
                {
                    "score": fru.score if fru else None,
                    "legend_levels": len(legend) if legend else None,
                    "confidence": fru.confidence if fru else None,
                },
                "legend 档位数应等于 criteria 档位数：%s" % (len(legend) == 3 if legend else "n/a"),
            )
        )

        # noul 契约：确认它确实没有 confidence
        noul_has_conf = bool(urg and "confidence" in (urg.data or {}))
        checks.append(
            check(
                "noul 只返回 noul、不含 confidence",
                V_OK if (urg is not None and urg.noul is not None and not noul_has_conf) else V_DEFECT,
                {"noul": urg.noul if urg else None, "含confidence": noul_has_conf},
                "官方明确 noul 不携带 confidence；若出现则文档有变",
            )
        )

        # 计费口径：output_tokens 是否为 0
        checks.append(
            check(
                "output_tokens 是否为 0（输出免费）",
                V_OK if resp.output_tokens == 0 else V_WARN,
                {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens},
                "官方按输入 token 计费、输出免费",
            )
        )
        checks.append(
            check("响应里的 model 字段（版本钉死用）", V_INFO, resp.model, "别名会漂移，日志里应记录这个值")
        )

    # ---- 2. key 不参与推理：同问题换 key 应得到完全相同的答案
    q = choice(
        "Which team should handle this",
        {
            "billing": "Payment or subscription issues",
            "technical": "Bugs or integration problems",
            "sales": "Pricing or account questions",
        },
    )
    r_a = ctx.ask(SUITE, "s01_key_a", TICKET, {"q_alpha": dict(q)}, note="同问题，key=q_alpha")
    r_b = ctx.ask(SUITE, "s01_key_b", TICKET, {"q_beta": dict(q)}, note="同问题，key=q_beta")
    if r_a and r_b:
        a, b = r_a.answers["q_alpha"], r_b.answers["q_beta"]
        same = (a.choice == b.choice) and (a.confidence == b.confidence)
        checks.append(
            check(
                "question key 不参与推理（换 key 答案不变）",
                V_OK if same else V_WARN,
                {"alpha": [a.choice, a.confidence], "beta": [b.choice, b.confidence]},
                "若不同，说明 key 或请求顺序影响了结果（也可能是非确定性），都值得注意",
            )
        )

    # ---- 3. score 的档位边界：2 档与 10 档
    r_min = ctx.ask(
        SUITE,
        "s01_score_min",
        TICKET,
        {"s2": score("How severe is this issue", ["Not severe", "Severe"])},
        note="score 下限 2 档",
    )
    r_max = ctx.ask(
        SUITE,
        "s01_score_max",
        TICKET,
        {"s10": score("How severe is this issue", ["Level %d" % i for i in range(10)])},
        note="score 上限 10 档",
    )
    if r_min and r_max:
        a2, a10 = r_min.answers["s2"], r_max.answers["s10"]
        checks.append(
            check(
                "score 档位边界（2 档 / 10 档）均可接受",
                V_OK if a2.score is not None and a10.score is not None else V_DEFECT,
                {"2档": {"score": a2.score, "confidence": a2.confidence},
                 "10档": {"score": a10.score, "confidence": a10.confidence}},
                "档位越多置信度通常越低——这是选档位数的实操依据",
            )
        )

    # ---- 4. choice 的兜底选项
    r_other = ctx.ask(
        SUITE,
        "s01_choice_other",
        "The customer attached a 4K video of a dancing cat and said nothing else.",
        {
            "intent": choice(
                "What does the customer want",
                {
                    "refund": "Wants money back",
                    "technical": "Reports a bug",
                    "billing": "Asks about charges",
                    "other": "None of the above",
                },
            )
        },
        note="喂一条不属于任何类别的输入，看是否落到 other",
    )
    if r_other:
        ans = r_other.answers["intent"]
        checks.append(
            check(
                "choice 兜底选项（None of the above）行为",
                V_INFO,
                {"choice": ans.choice, "confidence": ans.confidence,
                 "other_probability": ans.probability_of("other")},
                "低置信度是否配合兜底项，是设计路由分支的关键",
            )
        )

    # ---- 5. 扇出代价：1 个问题 vs 16 个问题，同一 state
    r1 = ctx.ask(SUITE, "s01_fanout_1", TICKET, {"q0": noul("Is this urgent?")}, note="1 个问题")
    many = {
        "q%d" % i: noul("Does the message mention topic number %d?" % i) for i in range(16)
    }
    r16 = ctx.ask(SUITE, "s01_fanout_16", TICKET, many, note="16 个问题，同一 state")
    if r1 and r16:
        delta = round(r16.latency_ms - r1.latency_ms, 1)
        ratio = round(r16.latency_ms / r1.latency_ms, 2) if r1.latency_ms else None
        checks.append(
            check(
                "问题扇出 1 → 16 的延迟代价",
                V_OK if delta < 800 else V_WARN,
                {"1问_ms": r1.latency_ms, "16问_ms": r16.latency_ms, "增量_ms": delta, "倍数": ratio},
                "官方称 state 只读入一次、问题并行评估；若增量很小，说明可放心把多个判断打包进一次请求",
            )
        )
        checks.append(
            check(
                "扇出的 token 代价（按输入计费，问题文本也收费）",
                V_INFO,
                {"1问_input": r1.input_tokens, "16问_input": r16.input_tokens,
                 "16问成本_usd": round(r16.input_tokens * 0.042 / 1e6, 8)},
                "每个问题的 instructions 都算输入 token",
            )
        )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary="先确认返回契约，再谈业务。契约不符时后续所有套件的判读都要打折扣。",
    )
