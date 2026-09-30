"""S04 计数。

目标：确认官方失效场景 #2 —— Jev 不会数数，但"逐个判断 + 代码加总"这条路是通的。
这个套件同时给出可复用的替代写法，因为它是最高频的踩坑点。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from ..client import choice, noul
from .base import Ctx, V_CLEAN, V_DEFECT, V_INFO, V_OK, check, pct, result

SUITE = "S04"
TITLE = "计数与数字精度"
HYPOTHESIS = (
    "直接让 Jev 数个数会错、且误差随规模增大；改用「每项一个 noul + 代码求和」能拿到真值。"
)
OFFICIAL = (
    "jev-1.13 不能可靠计数，覆盖字符数、词频、长列表项数。模型识别的是答案的形状而不是逐项清点，"
    "误差随被数对象的规模增大。官方建议：在代码里循环，对每个候选问一个问题，然后自己加总。"
)

FILLER = [
    "配送记录显示包裹已经离开分拣中心。",
    "客户在应用内提交了地址变更。",
    "系统在凌晨完成了一次例行备份。",
    "客服在昨天下午回复了第一条消息。",
    "订单包含两件商品，包装完好。",
    "配送员已经完成签到。",
    "仓库完成了本周的库存盘点。",
    "客户更新了自己的手机号码。",
    "系统向客户发送了一条发货通知。",
    "该账号在两周前完成实名认证。",
]
TARGET_SENTENCE = "客户明确提出了退款申请，编号 R%d。"

FRUITS = ["apple", "banana", "orange", "grape", "peach", "pear", "mango", "cherry"]
NON_FRUITS = ["desk", "hammer", "window", "bicycle", "cable", "lamp", "notebook",
              "brick", "towel", "bottle", "spanner", "curtain"]


def _build_paragraph(total_sentences: int, target_count: int, seed: int):
    rnd = random.Random(seed)
    sentences: List[str] = []
    for i in range(target_count):
        sentences.append(TARGET_SENTENCE % (i + 1))
    filler_needed = max(0, total_sentences - target_count)
    for i in range(filler_needed):
        sentences.append(FILLER[i % len(FILLER)])
    rnd.shuffle(sentences)
    return "".join(sentences)


def _build_items(total: int, fruit_count: int, seed: int) -> List[str]:
    rnd = random.Random(seed)
    items = [rnd.choice(NON_FRUITS) for _ in range(total)]
    for idx in rnd.sample(range(total), fruit_count):
        items[idx] = rnd.choice(FRUITS)
    return items


def _fruit_truth(items: List[str]) -> int:
    return sum(1 for it in items if it in FRUITS)


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    # ================= 任务 A：文本中关键词出现次数 =================
    truth_a = 5
    paragraph = _build_paragraph(total_sentences=12, target_count=truth_a, seed=4211)
    sentences = [s for s in paragraph.replace("。", "。\n").split("\n") if s.strip()]
    real_count = paragraph.count("退款")

    # A1 直接问（错误示范）
    direct_options = {str(i): "出现 %d 次" % i for i in range(0, 13)}
    r_direct = ctx.ask(
        SUITE,
        "s04_direct_count",
        paragraph,
        {
            "count": choice(
                "「退款」这个词在这段文字里出现了几次？",
                direct_options,
            )
        },
        note="直接问次数（官方明确说这条路不可靠）",
    )
    if r_direct:
        picked = r_direct.answers["count"].choice
        ok = picked == str(real_count)
        checks.append(
            check(
                "直接问「出现几次」是否命中",
                V_OK if ok else V_DEFECT,
                {"真值": real_count, "Jev答": picked, "confidence": r_direct.answers["count"].confidence},
                "答错即复现官方缺陷 #2；注意它答错时 confidence 未必低，这是危险点",
            )
        )

    # A2 官方推荐写法（正确示范）
    #
    # ⚠️ 这里有个必须遵守的硬要求：每个问题的 instructions 都要用反引号**显式指向**那一项
    # （`sentences[0]`、`sentences[1]`…）。如果只写「这句话」，Jev 会把整个集合当成判断对象，
    # 10 个问题会全部返回接近 1 的 yes —— 实测正是如此（全部 ~0.80），于是加总得到 10 而非真值。
    # 这不是模型能力问题，是指令没写清（官方失效场景 #1：它回答你写下的问题）。
    per_sentence_q = {
        "s%d" % i: noul("`sentences[%d]` 是否包含「退款」这个词？" % i)
        for i in range(len(sentences))
    }
    r_iter = ctx.ask(
        SUITE,
        "s04_iterate_sum",
        {"sentences": sentences},
        per_sentence_q,
        note="对每句问一个 noul（每题显式指向 sentences[i]），然后在代码里加总",
    )
    if r_iter:
        votes = []
        for i in range(len(sentences)):
            v = r_iter.answers.get("s%d" % i)
            votes.append(v.noul if v else None)
        counted = sum(1 for v in votes if v is not None and v >= 0.5)
        ok = counted == real_count
        checks.append(
            check(
                "逐个 noul 提问 + 代码加总是否命中",
                V_OK if ok else V_DEFECT,
                {"真值": real_count, "加总结果": counted, "句子数": len(sentences),
                 "逐句noul": [round(v, 3) if v is not None else None for v in votes]},
                "官方推荐的替代路径。前提是每个问题都用反引号指向具体项（`sentences[i]`）—— "
                "少了这一步，整条路线会失效并全部返回 yes",
            )
        )
        checks.append(
            check(
                "两种写法的准确率对比",
                V_INFO,
                {"直接问": "命中" if (r_direct and r_direct.answers["count"].choice == str(real_count)) else "未命中",
                 "拆分加总": "命中" if ok else "未命中"},
                "结论应当写进团队的编码规范：凡是需要精确数字，一律代码算",
            )
        )

    # ================= 任务 B：字符计数 =================
    word = "strawberry"
    truth_b = word.count("r")
    r_char = ctx.ask(
        SUITE,
        "s04_char_count",
        {"word": word},
        {"r_count": choice("`word` 这个单词里有几个字母 r？", {str(i): "%d 个" % i for i in range(0, 6)})},
        note="字符级计数（典型翻车点）",
    )
    if r_char:
        picked = r_char.answers["r_count"].choice
        checks.append(
            check(
                "单词字母计数是否命中",
                V_OK if picked == str(truth_b) else V_DEFECT,
                {"单词": word, "真值": truth_b, "Jev答": picked},
                "经典案例；答错意味着任何「数长度/数字符」的需求都必须走代码",
            )
        )

    # ================= 任务 C：误差是否随规模增大 =================
    scale_rows = []
    for total, fruit_count, seed, label in ((5, 3, 991, "小规模5项"), (40, 23, 992, "大规模40项")):
        items = _build_items(total, fruit_count, seed)
        truth = _fruit_truth(items)
        options = {str(i): "%d 个" % i for i in range(0, total + 1)}
        r = ctx.ask(
            SUITE,
            "s04_scale_direct_%d" % total,
            {"items": items},
            {"count": choice("`items` 里有几个是水果？", options)},
            note="%s：直接问总数" % label,
        )
        picked = r.answers["count"].choice if r else None
        r2 = ctx.ask(
            SUITE,
            "s04_scale_iter_%d" % total,
            {"items": items},
            {"i%d" % i: noul("`items[%d]` 是水果的名字吗？" % i) for i in range(total)},
            note="%s：逐项判断后加总" % label,
        )
        counted = None
        if r2:
            counted = sum(
                1
                for i in range(total)
                if r2.answers.get("i%d" % i) is not None
                and r2.answers["i%d" % i].noul is not None
                and r2.answers["i%d" % i].noul >= 0.5
            )
        scale_rows.append(
            {
                "规模": label,
                "真值": truth,
                "直接问": picked,
                "直接问误差": (abs(int(picked) - truth) if picked is not None and picked.isdigit() else None),
                "拆分加总": counted,
                "拆分加总误差": (abs(counted - truth) if counted is not None else None),
            }
        )

    if scale_rows:
        checks.append(
            check(
                "计数误差是否随规模增大",
                V_INFO,
                scale_rows,
                "官方称误差随之增大；若实测确如此，就给'状态先过滤/先分片'提供了量化理由",
            )
        )
        improved = all(
            (row["拆分加总误差"] is not None)
            and (row["直接问误差"] is None or row["拆分加总误差"] <= row["直接问误差"])
            for row in scale_rows
        )
        checks.append(
            check(
                "拆分加总是否不劣于直接问",
                V_OK if improved else V_DEFECT,
                {"逐行": [{"规模": r["规模"], "直接问误差": r["直接问误差"],
                           "拆分误差": r["拆分加总误差"]} for r in scale_rows]},
                "这是「该怎么写」的正面证据，可以直接抄进项目里的工具函数",
            )
        )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "把这条结论固化下来：Jev 负责判断，代码负责算术。凡是需要精确数字的地方，"
            "都改成「模型逐项判断 + 代码聚合」。"
        ),
    )
