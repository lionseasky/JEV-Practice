"""S08 中文 vs 英文。

目标：官方明说英文是主要训练语言、CJK 支持但表现不同等。
对中文工作流来说，这是**上生产前必须自己实测**的一项。
同时测一种常用的兜底写法：英文 instructions + 中文 state。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import noul, score
from .base import Ctx, V_INFO, V_OK, V_WARN, check, mean, pct, result

SUITE = "S08"
TITLE = "中文 / 英文 / 混合模式的表现差异"
HYPOTHESIS = "英文准确率与置信度高于中文；用英文写 instructions 配中文 state 可能把中文表现拉回来。"
OFFICIAL = (
    "English 是主要训练语言，也是当前准确率最好的语言。其他语言（包括中日韩文字）被支持但表现不同等，"
    "官方建议在自己的内容上测过再依赖，非英文路由时要格外关注 confidence。"
)

# (英文, 中文, 真值：是否需要客服采取行动)
PAIRS = [
    ("The package arrived three days late and the box was crushed.",
     "包裹晚了三天才送到，箱子还被压扁了。", True),
    ("Thanks, everything works perfectly now.",
     "谢谢，现在一切正常了。", False),
    ("I'd like to cancel my subscription before the next billing date.",
     "我想在下次扣费之前取消订阅。", True),
    ("The invoice shows a charge I don't recognize.",
     "账单上有一笔我不认识的扣费。", True),
    ("No need to reply, just logging this for the record.",
     "不用回复，我只是留个记录。", False),
    ("Can you tell me whether the warranty covers water damage?",
     "能告诉我保修是否覆盖进水损坏吗？", True),
    ("I already fixed it myself, you can close the ticket.",
     "我自己已经修好了，你们可以关掉工单。", False),
    ("This is the third time I've written about the same bug.",
     "同一个问题我已经第三次写信了。", True),
]

EN_Q = "Does `items[%d]` require the support team to take an action or reply?"
ZH_Q = "`items[%d]` 是否需要客服团队采取行动或回复？"
ACTION_LEVELS_EN = ["No action needed", "Needs an answer", "Needs immediate action"]
ACTION_LEVELS_ZH = ["无需动作", "需要回复", "需要立即处理"]


def _build_questions(template: str, levels: List[str]) -> Dict[str, Dict[str, Any]]:
    questions: Dict[str, Dict[str, Any]] = {}
    for i in range(len(PAIRS)):
        questions["act_%d" % i] = noul(template % i)
        questions["load_%d" % i] = score("How much action does `items[%d]` require?" % i, levels)
    return questions


def _evaluate(resp, label: str) -> Dict[str, Any]:
    hits = 0
    total = 0
    confs: List[float] = []
    wrong: List[Dict[str, Any]] = []
    for i, (_, _, truth) in enumerate(PAIRS):
        ans = resp.answers.get("act_%d" % i)
        if ans is None or ans.noul is None:
            continue
        total += 1
        got = ans.noul >= 0.5
        if got == truth:
            hits += 1
        else:
            wrong.append({"item": i, "noul": round(ans.noul, 3), "真值": truth})
        load = resp.answers.get("load_%d" % i)
        if load is not None and load.confidence is not None:
            confs.append(load.confidence)
    return {
        "语言模式": label,
        "准确率%": pct(hits, total),
        "命中": hits,
        "样本": total,
        "平均confidence": mean(confs),
        "错误项": wrong,
    }


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    en_items = [p[0] for p in PAIRS]
    zh_items = [p[1] for p in PAIRS]

    r_en = ctx.ask(
        SUITE, "s08_english",
        {"items": en_items},
        _build_questions(EN_Q, ACTION_LEVELS_EN),
        note="英文 state + 英文 instructions（对照组）",
    )
    r_zh = ctx.ask(
        SUITE, "s08_chinese",
        {"items": zh_items},
        _build_questions(ZH_Q, ACTION_LEVELS_ZH),
        note="中文 state + 中文 instructions",
    )
    r_mix = ctx.ask(
        SUITE, "s08_mixed",
        {"items": zh_items},
        _build_questions(EN_Q, ACTION_LEVELS_EN),
        note="中文 state + 英文 instructions（常用兜底写法）",
    )

    rows = []
    if r_en:
        rows.append(_evaluate(r_en, "英文 state + 英文指令"))
    if r_zh:
        rows.append(_evaluate(r_zh, "中文 state + 中文指令"))
    if r_mix:
        rows.append(_evaluate(r_mix, "中文 state + 英文指令"))

    if rows:
        checks.append(check("三语言模式的准确率与置信度对照", V_INFO, rows,
                            "样本只有 8 条，看趋势不看小数点；要下生产结论请把样本扩到几百条"))

    by_label = {r["语言模式"]: r for r in rows}
    en = by_label.get("英文 state + 英文指令")
    zh = by_label.get("中文 state + 中文指令")
    mix = by_label.get("中文 state + 英文指令")

    if en and zh:
        acc_gap = (en["准确率%"] or 0) - (zh["准确率%"] or 0)
        conf_gap = None
        if en["平均confidence"] is not None and zh["平均confidence"] is not None:
            conf_gap = round(en["平均confidence"] - zh["平均confidence"], 4)
        checks.append(
            check(
                "英文 vs 中文的准确率差",
                V_OK if acc_gap >= 0 else V_WARN,
                {"英文%": en["准确率%"], "中文%": zh["准确率%"], "差值": round(acc_gap, 1)},
                "中文更低是符合官方说明的预期；差多少决定你要不要加人工复核环节",
            )
        )
        checks.append(
            check(
                "英文 vs 中文的平均 confidence 差",
                V_INFO,
                {"英文": en["平均confidence"], "中文": zh["平均confidence"], "差值": conf_gap},
                "中文 confidence 系统性偏低 → 中文路由阈值应当单独标定，不能照抄英文的",
            )
        )

    if zh and mix:
        checks.append(
            check(
                "英文 instructions 能否救回中文 state 的表现",
                V_INFO,
                {
                    "中文state+中文指令": {"准确率%": zh["准确率%"], "平均confidence": zh["平均confidence"]},
                    "中文state+英文指令": {"准确率%": mix["准确率%"], "平均confidence": mix["平均confidence"]},
                },
                "若有效，这是一个几乎零成本的兜底手段；若无效，说明瓶颈在 state 而不在指令语言",
            )
        )

    checks.append(
        check(
            "中文工作流的实操建议",
            V_INFO,
            {
                "结论": "别假设中文表现等同英文，必须用你自己的真实语料标定",
                "推荐做法": [
                    "中文路由阈值单独标定，不要复用英文阈值",
                    "关键路径上用 confidence 门控 + 人工复核兜底",
                    "上线前把本套件扩到 200~500 条真实样本，做成回归集",
                ],
            },
            "这条建议的成本很低，但能挡住最容易踩的坑",
        )
    )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "对中文团队来说这是最关键的一个套件：它决定了你的阈值、你的复核比例、"
            "以及是否需要英文指令兜底。本套件的 8 条样本只是引子，真正有价值的是把它换成你的业务语料。"
        ),
    )
