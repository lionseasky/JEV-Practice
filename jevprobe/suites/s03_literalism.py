"""S03 字面理解。

目标：验证官方失效场景 #1 —— 它回答你**写下的**问题，不是你想问的问题。
这是上手 Jev 最容易翻车的地方，也是最重要的一个认知。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import noul
from .base import Ctx, V_CLEAN, V_DEFECT, V_INFO, V_OK, check, pct, result

SUITE = "S03"
TITLE = "字面理解（写下的问题 ≠ 想问的问题）"
HYPOTHESIS = (
    "把 '提到' 误当 '要求'、忽略否定、省略隐含条件时，Jev 会按字面给出严格答案；"
    "把条件写全会显著改变答案与置信度。"
)
OFFICIAL = (
    "jev-1.13 回答你写的问题，不是你想问的问题。作用域词、否定、隐含条件都按字面读。"
    "官方建议：把确切条件写进 instructions，把边界情况写进 criteria；"
    "当你看着一个错答案、开始对自己解释'我其实是想问'的时候，那句解释就是漏写的另一半指令。"
)


def _truth_check(name: str, value: Any, expected_low: bool, note: str) -> Dict[str, Any]:
    """expected_low=True 表示期望 noul 偏低。"""
    if value is None:
        return check(name, V_INFO, None, "无返回")
    passed = (value < 0.5) if expected_low else (value >= 0.5)
    return check(name, V_OK if passed else V_DEFECT, round(value, 4), note)


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    literal_hits = 0
    literal_total = 0

    # ---- 1. 「提到」vs「要求」：作用域 + 意图的经典陷阱
    scope_state = (
        "Customer message: I see in your policy that refunds are available within 30 days. "
        "Just wanted to say the new dashboard looks nice. Keep up the good work!"
    )
    r1 = ctx.ask(
        SUITE,
        "s03_mention_vs_request",
        scope_state,
        {
            "requests_refund": noul("Does the customer request a refund?"),
            "mentions_refund": noul("Does the message mention refunds?"),
        },
        note="消息里出现'退款'字样，但客户并没有要求退款",
    )
    if r1:
        req = r1.answers["requests_refund"].noul
        men = r1.answers["mentions_refund"].noul
        literal_total += 1
        if req is not None and req < 0.5:
            literal_hits += 1
        checks.append(
            _truth_check(
                "「客户是否要求退款？」→ 期望低（只是提到政策）",
                req,
                expected_low=True,
                note="选低分说明它没有被'退款'这个词带偏，语义区分能力在线",
            )
        )
        checks.append(
            _truth_check(
                "「消息是否提到退款？」→ 期望高",
                men,
                expected_low=False,
                note="同一 state 下两个相近问题的分离度，是判断 instructions 精度的标尺",
            )
        )
        checks.append(
            check(
                "同一 state 下相近问题的分离度",
                V_OK
                if (req is not None and men is not None and abs(men - req) > 0.3)
                else V_INFO,
                {"请求退款": req, "提到退款": men},
                "分离度大 → instructions 的措辞真的在起作用",
            )
        )

    # ---- 2. 否定与双重否定
    r2 = ctx.ask(
        SUITE,
        "s03_negation",
        "The customer did not fail to provide the receipt.",
        {
            "provided": noul("Did the customer provide the receipt?"),
            "not_provided": noul("Did the customer fail to provide the receipt?"),
        },
        note="双重否定：'没有未能提供' = 提供了",
    )
    if r2:
        provided = r2.answers["provided"].noul
        not_provided = r2.answers["not_provided"].noul
        literal_total += 2
        if provided is not None and provided >= 0.5:
            literal_hits += 1
        if not_provided is not None and not_provided < 0.5:
            literal_hits += 1
        checks.append(
            _truth_check("双重否定 →「提供了收据」期望高", provided, False,
                         "官方把'多层间接'列为独立失效场景，双重否定是最小复现")
        )
        checks.append(
            _truth_check("反向问法 →「未提供收据」期望低", not_provided, True,
                         "两个问法自相矛盾时，说明模型没有稳定解析否定")
        )

    # ---- 3. 隐含条件：条件不写全会怎样
    order_state = (
        "Order #88213. Customer: 72 years old, first-time user. Amount: 480 CNY. "
        "Payment: completed. Escort assigned: none yet. Appointment: tomorrow 09:00. "
        "Customer left a note: 'I may need help finding the cardiology department.'"
    )
    r_naive = ctx.ask(
        SUITE,
        "s03_implicit_naive",
        order_state,
        {"needs_review": noul("Does this order need manual review?")},
        note="没给复核标准，全靠模型猜'你想问的'",
    )
    r_explicit = ctx.ask(
        SUITE,
        "s03_implicit_explicit",
        order_state,
        {
            "needs_review": noul(
                "Does this order need manual review? Manual review is required if and only if "
                "at least one of these is true: (a) no escort has been assigned, and the "
                "appointment is within 24 hours; (b) the customer is 70 years or older AND "
                "is a first-time user. Answer based only on these conditions."
            )
        },
        note="把复核标准写进 instructions（官方推荐的写法）",
    )
    if r_naive and r_explicit:
        nv = r_naive.answers["needs_review"]
        ev = r_explicit.answers["needs_review"]
        # 真值：条件 (a) 成立（未派单 + 24 小时内）→ 应为 yes
        checks.append(
            check(
                "把判定条件写进 instructions 前后的差异",
                V_OK if (ev.noul is not None and ev.noul >= 0.5) else V_INFO,
                {"naive_noul": nv.noul, "explicit_noul": ev.noul},
                "真值：条件(a)成立（未派单且就诊在 24h 内）→ 期望 yes。"
                "naive 版若给 no，正是「你没写标准，它就自己猜」的典型表现",
            )
        )

    # ---- 4. 作用域词："除了…之外"
    r4 = ctx.ask(
        SUITE,
        "s03_scope_word",
        "除了北京的订单，其他城市的订单都已经发货了。",
        {
            "beijing_shipped": noul("北京的订单发货了吗？"),
            "others_shipped": noul("除北京外其他城市的订单发货了吗？"),
        },
        note="中文作用域词测试",
    )
    if r4:
        bj = r4.answers["beijing_shipped"].noul
        others = r4.answers["others_shipped"].noul
        literal_total += 2
        if bj is not None and bj < 0.5:
            literal_hits += 1
        if others is not None and others >= 0.5:
            literal_hits += 1
        checks.append(_truth_check("北京订单发货了吗 → 期望低", bj, True,
                                   "作用域词在中文里同样按字面读"))
        checks.append(_truth_check("其他城市订单发货了吗 → 期望高", others, False,
                                   "中文作用域识别的能力下限"))

    # ---- 汇总
    checks.append(
        check(
            "字面回答命中率（有明确真值的子项）",
            V_INFO,
            {"命中": literal_hits, "总数": literal_total, "命中率%": pct(literal_hits, literal_total)},
            "命中率高 → 它在'认真读你写的字'，所以写错指令的锅在人不在模型",
        )
    )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "这个套件的价值不在分数，而在建立肌肉记忆：写 instructions 时把'我其实是想问…'"
            "那句话也写进去。写全之后答案变化越大，说明你的原型指令越依赖模型猜。"
        ),
    )
