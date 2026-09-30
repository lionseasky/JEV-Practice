"""Playground 预设场景。

每个预设都是一份**可以直接发出去的完整请求**，配一句"该看什么"。
它们大多来自 `jevprobe/suites/` 里的探测用例，所以在界面上手动跑一遍，
结果可以和实验台报告里的实测数据对照着看。
"""

from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------- 客服工单基线

TICKET = (
    "Hi, I've been trying to connect my Stripe account for 3 days and the "
    "integration keeps failing. I'm losing sales. Please help ASAP."
)

REFUND_SCOPE_STATE = (
    "Customer message: I see in your policy that refunds are available within 30 days. "
    "Just wanted to say the new dashboard looks nice. Keep up the good work!"
)

DOUBLE_NEG_STATE = "The customer did not fail to provide the receipt."

# ---------------------------------------------------------------- 计数语料
#
# 预设 ④（直接问）和 ⑤（逐项加总）刻意使用**同一份语料**，真值都是 5，
# 这样两次调用的结果可以直接对比。
#
# 语料和真值都由代码生成 + 校验，避免手写列表和文案里的数字悄悄漂移
# （第一版就踩过：文案写"真值 5"，实际语料只有 4 句含「退款」）。

COUNTING_TRUTH = 5

_COUNTING_FILLER = [
    "配送记录显示包裹已经离开分拣中心。",
    "客户在应用内提交了地址变更。",
    "系统在凌晨完成了一次例行备份。",
    "客服在昨天下午回复了第一条消息。",
    "订单包含两件商品，包装完好。",
    "客户更新了自己的手机号码。",
    "系统向客户发送了一条发货通知。",
    "该账号在两周前完成实名认证。",
    "配送员已经完成签到。",
    "仓库完成了本周的库存盘点。",
]
_COUNTING_TARGET = "客户明确提出了退款申请，编号 R%d。"


def _build_counting_sentences(total: int = 10, truth: int = COUNTING_TRUTH, seed: int = 20260929):
    import random

    items = [_COUNTING_TARGET % (i + 1) for i in range(truth)]
    items += random.Random(seed).sample(_COUNTING_FILLER, max(0, total - truth))
    random.Random(seed).shuffle(items)
    return items


COUNTING_SENTENCES = _build_counting_sentences()
COUNTING_PARAGRAPH = "".join(COUNTING_SENTENCES)
_COUNTING_TRUTH_ACTUAL = sum(1 for s in COUNTING_SENTENCES if "退款" in s)

MULTI_HOP_STATE = {
    "account": {"name": "Acme Robotics", "plan_code": "ent-2026", "seats": 240},
    "catalog": {
        "plan_codes": {
            "ent-2026": {"tier": "enterprise", "sla_hours": 4},
            "pro-2026": {"tier": "business", "sla_hours": 24},
        }
    },
    "sla_policy": {
        "enterprise": {"first_response_hours": 4, "escalation": "pagerduty"},
        "business": {"first_response_hours": 24, "escalation": "email"},
    },
    "ticket": {"opened_hours_ago": 6, "severity": "high"},
}


def _noul(instructions: str, criteria: Any = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    return q


def _choice(instructions: str, criteria: Dict[str, str]) -> Dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def _score(instructions: str, criteria: List[str]) -> Dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": criteria}


PRESETS: List[Dict[str, Any]] = [
    {
        "id": "triage",
        "title": "① 工单三类型｜一次请求问三种判断（官方示例）",
        "note": "看什么：同一次请求里 choice/score/noul 并行返回三种形状的答案。"
        "注意 noul 没有 confidence，而 choice 有 —— 这是两者最本质的差别。",
        "state_mode": "string",
        "state": TICKET,
        "questions": {
            "department": _choice(
                "Which team should handle this",
                {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            ),
            "frustration": _score(
                "How frustrated the customer appears",
                ["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
            ),
            "is_urgent": _noul("The message conveys urgency or time-sensitivity"),
        },
    },
    {
        "id": "scope",
        "title": "② 字面理解｜「提到」不等于「要求」",
        "note": "看什么：state 里出现了「退款」字样，但客户并没有要求退款。"
        "两个相近问题应当给出明显不同的分数 —— 这是 instructions 精度的试金石。",
        "state_mode": "string",
        "state": REFUND_SCOPE_STATE,
        "questions": {
            "requests_refund": _noul("Does the customer request a refund?"),
            "mentions_refund": _noul("Does the message mention refunds?"),
        },
    },
    {
        "id": "negation",
        "title": "③ 双重否定｜官方列出的第 4 类失效场景",
        "note": "看什么：「没有未能提供收据」= 提供了。两个反向问法如果自相矛盾，"
        "说明否定解析不稳定 —— 这是写 instructions 时要主动规避的形态。",
        "state_mode": "string",
        "state": DOUBLE_NEG_STATE,
        "questions": {
            "provided": _noul("Did the customer provide the receipt?"),
            "not_provided": _noul("Did the customer fail to provide the receipt?"),
        },
    },
    {
        "id": "count_naive",
        "title": "④ 计数·错误示范｜直接问「出现了几次」",
        "note": "看什么：真值是 %d 次（这段文字与预设 ⑤ 内容完全相同）。"
        "官方明确说这条路不可靠（误差随规模增大），注意它答错时 confidence 未必低 —— 这才是危险的地方。"
        % _COUNTING_TRUTH_ACTUAL,
        "state_mode": "string",
        "state": COUNTING_PARAGRAPH,
        "questions": {
            "count": _choice(
                "「退款」这个词在这段文字里出现了几次？",
                {str(i): "出现 %d 次" % i for i in range(0, len(COUNTING_SENTENCES) + 1)},
            )
        },
    },
    {
        "id": "count_iterate",
        "title": "⑤ 计数·正确写法｜逐句判断 + 代码加总",
        "note": "看什么：这是官方推荐的替代路径 —— 对每句问一个 noul，然后你在代码里加总。"
        "真值同样是 %d（与预设 ④ 是同一份语料，可以直接对比）。"
        "⚠️ 关键前提：每个问题都必须用反引号指向具体那一项（`sentences[0]`、`sentences[1]`…）。"
        "如果只写「这句话」，Jev 会把整个集合当成判断对象 —— 实测会让所有问题都返回接近 1 的 yes，"
        "加总得到 10 而不是 %d。这不是模型不行，是指令没写清（官方失效场景 #1）。"
        % (_COUNTING_TRUTH_ACTUAL, _COUNTING_TRUTH_ACTUAL),
        "state_mode": "object",
        "state": {"sentences": COUNTING_SENTENCES},
        "questions": {
            "s%d" % i: _noul("`sentences[%d]` 是否包含「退款」这个词？" % i)
            for i in range(len(COUNTING_SENTENCES))
        },
    },
    {
        "id": "date_direct",
        "title": "⑥ 日期·直接比较｜官方第 3 类失效场景",
        "note": "看什么：2026-02-27 更早。它把日期当文本读，不当有序量。"
        "同时看 choice 和 noul 两种问法是否一致。",
        "state_mode": "object",
        "state": {"date_A": "2026-03-04", "date_B": "2026-02-27"},
        "questions": {
            "earlier": _choice(
                "`date_A` 和 `date_B` 哪个日期更早？",
                {"A": "date_A 更早", "B": "date_B 更早"},
            ),
            "a_before_b": _noul("`date_A` 早于 `date_B`"),
        },
    },
    {
        "id": "date_decompose",
        "title": "⑦ 日期·正确写法｜抽取交给模型，算术留给代码",
        "note": "看什么：把年/月/日各自抽成一个 choice，比较在代码里做。"
        "抽取是「判断」所以模型擅长，算术不是 —— 这条分界线是 Jev 工程化的核心。",
        "state_mode": "object",
        "state": {"date_A": "2026-03-04", "date_B": "2026-02-27"},
        "questions": {
            "a_year": _choice("`date_A` 的年份是哪一年？", {"2025": "2025", "2026": "2026", "2027": "2027"}),
            "a_month": _choice("`date_A` 的月份是哪个月？", {"%02d" % m: "%02d" % m for m in range(1, 13)}),
            "a_day": _choice("`date_A` 的日是哪一天？", {"%02d" % d: "%02d" % d for d in range(1, 32)}),
            "b_year": _choice("`date_B` 的年份是哪一年？", {"2025": "2025", "2026": "2026", "2027": "2027"}),
            "b_month": _choice("`date_B` 的月份是哪个月？", {"%02d" % m: "%02d" % m for m in range(1, 13)}),
            "b_day": _choice("`date_B` 的日是哪一天？", {"%02d" % d: "%02d" % d for d in range(1, 32)}),
        },
    },
    {
        "id": "confidence",
        "title": "⑧ 置信度门控｜清晰 vs 无关，看 confidence 掉不掉",
        "note": "看什么：两个 state 分开跑（先跑这个，再把 state 换成"
        "「Purple elephants are dancing in a thunderstorm.」重跑一次）。"
        "如果 confidence 会随输入变糊而下降，它就能当门控阈值用。",
        "state_mode": "string",
        "state": "My invoice shows a $49 charge on March 3 for a subscription I cancelled in January.",
        "questions": {
            "intent": _choice(
                "Which team should handle this",
                {
                    "billing": "Payment, invoice or subscription issues",
                    "technical": "Bugs, login or integration problems",
                    "sales": "Pricing or account questions",
                },
            )
        },
    },
    {
        "id": "zh_en",
        "title": "⑨ 中文 vs 英文｜同一批语义，两种语言各跑一次",
        "note": "看什么：先跑英文，再把 state.items 换成中文那组重跑（或者勾选两个模型对比）。"
        "官方明说英文准确率最好、CJK 支持但表现不同等 —— 这是中文工作流最该自测的一项。",
        "state_mode": "object",
        "state": {
            "items": [
                "The package arrived three days late and the box was crushed.",
                "Thanks, everything works perfectly now.",
                "I'd like to cancel my subscription before the next billing date.",
                "No need to reply, just logging this for the record.",
            ]
        },
        "questions": {
            "act_0": _noul("Does `items[0]` require the support team to take an action or reply?"),
            "act_1": _noul("Does `items[1]` require the support team to take an action or reply?"),
            "act_2": _noul("Does `items[2]` require the support team to take an action or reply?"),
            "act_3": _noul("Does `items[3]` require the support team to take an action or reply?"),
            "load_0": _score(
                "How much action does `items[0]` require?",
                ["No action needed", "Needs an answer", "Needs immediate action"],
            ),
        },
    },
    {
        "id": "multi_hop",
        "title": "⑩ 多层间接｜同一真值，三种跳数",
        "note": "看什么：plan_code → tier → first_response_hours → 与 opened_hours_ago 比较。"
        "第 0 跳是字段直读（稳），第 2 跳叠了数值比较。把派生字段预先算进 state 是最有效的改法。",
        "state_mode": "object",
        "state": MULTI_HOP_STATE,
        "questions": {
            "hop0": _noul("`account.plan_code` 是否等于 'ent-2026'？"),
            "hop1": _noul("`account` 所属的方案等级（tier）是不是 enterprise？"),
            "hop2": _noul(
                "该工单是否已经超出了这个账户的首次响应时间承诺？"
                "（请依次使用 `catalog.plan_codes` 与 `sla_policy` 中的信息判断）"
            ),
        },
    },
]


def by_id(preset_id: str):
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    return None


# ---------------------------------------------------------------- 自检
#
# 存在的理由：这个 bug 真实发生过两次（预设 ⑤ 和 suites/s04）。
# 当 state 是一个集合、而你要对每一项问同一个问题时，instructions 必须用反引号
# **显式指向那一项**（`sentences[0]`）。只写「这句话」的话，Jev 会把整个集合当成
# 判断对象，于是每个问题都返回几乎相同的答案 —— 表面上看是模型不行，
# 实际是指令没写清。这类错误不看结果很难发现，所以在这里做静态拦截。

VAGUE_DEIXIS = (
    "这句话",
    "这一条",
    "该条目",
    "该句",
    "这条消息是否",
    "this sentence",
    "this item",
    "this message",
)


def _collection_in(state: Any):
    """如果 state 里有一个多元素列表字段，返回 (字段名, 列表)。"""
    if isinstance(state, dict):
        for key, value in state.items():
            if isinstance(value, list) and len(value) > 1:
                return key, value
    return None, None


def validate_presets() -> List[str]:
    """静态自检。返回问题清单，空列表 = 全部通过。"""
    problems: List[str] = []

    for preset in PRESETS:
        key, items = _collection_in(preset.get("state"))
        if key is None:
            continue
        for qid, q in preset["questions"].items():
            instr = q.get("instructions")
            text = instr if isinstance(instr, str) else json.dumps(instr, ensure_ascii=False)
            for vague in VAGUE_DEIXIS:
                if vague in text:
                    problems.append(
                        "%s / %s：instructions 出现「%s」这种模糊指代，但 state 是 %d 个元素的集合。"
                        "Jev 会把整个集合当成判断对象，导致所有问题返回几乎相同的答案。"
                        "请改成反引号指向具体项，例如 `%s[0]`。"
                        % (preset["id"], qid, vague, len(items), key)
                    )
                    break

    if _COUNTING_TRUTH_ACTUAL != COUNTING_TRUTH:
        problems.append(
            "计数语料真值漂移：期望 %d，实际 %d（检查 _build_counting_sentences）"
            % (COUNTING_TRUTH, _COUNTING_TRUTH_ACTUAL)
        )

    if COUNTING_PARAGRAPH.count("退款") != _COUNTING_TRUTH_ACTUAL:
        problems.append("段落版语料与句子版语料的真值不一致，预设 ④ 与 ⑤ 无法直接对比")

    return problems
