"""S05 日期与时间比较。

目标：确认官方失效场景 #3 —— Jev 把日期当文本读，不做有序量比较；
并验证官方推荐的「抽取交给模型、比较留在代码」这条拆分路线。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from ..client import choice, noul
from .base import Ctx, V_CLEAN, V_DEFECT, V_INFO, V_OK, check, pct, result

SUITE = "S05"
TITLE = "日期时间比较"
HYPOTHESIS = (
    "直接让 Jev 比较两个日期不可靠；把年/月/日拆成 choice 抽取、再在代码里比较，能拿回准确性。"
)
OFFICIAL = (
    "jev-1.13 把日期当文本读，不当有序量。问两个日期谁在前、相差多久、是否落在某个窗口内都不可靠，"
    "混合格式、相对表述和季度/结算窗口这类领域边界会让情况更糟。"
    "官方建议拆开：抽取是判断，交给模型；算术不是判断，留在代码。"
)

MONTHS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
DAYS = ["%02d" % i for i in range(1, 32)]

BOOL_PAIR = {"yes": "是", "no": "否"}


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    direct_hits = 0
    direct_total = 0

    # ---------------- 用例 1：谁更早 ----------------
    d_a = date(2026, 3, 4)
    d_b = date(2026, 2, 27)
    truth_earlier = "A" if d_a < d_b else "B"

    r1 = ctx.ask(
        SUITE,
        "s05_order",
        {"date_A": d_a.isoformat(), "date_B": d_b.isoformat()},
        {
            "earlier": choice(
                "`date_A` 和 `date_B` 哪个日期更早？",
                {"A": "date_A 更早", "B": "date_B 更早"},
            ),
            "a_before_b": noul("`date_A` 早于 `date_B`"),
        },
        note="标准 ISO 格式的先后比较",
    )
    if r1:
        picked = r1.answers["earlier"].choice
        direct_total += 1
        if picked == truth_earlier:
            direct_hits += 1
        checks.append(
            check(
                "两个 ISO 日期谁更早",
                V_OK if picked == truth_earlier else V_DEFECT,
                {"真值": truth_earlier, "Jev答": picked,
                 "confidence": r1.answers["earlier"].confidence},
                "同格式、同一年的简单比较，如果也错，说明日期能力非常弱",
            )
        )
        nv = r1.answers["a_before_b"].noul
        direct_total += 1
        expect_high = (d_a < d_b)
        if nv is not None and ((nv >= 0.5) == expect_high):
            direct_hits += 1
        checks.append(
            check(
                "noul 形式的先后判断",
                V_OK if (nv is not None and ((nv >= 0.5) == expect_high)) else V_DEFECT,
                {"真值": expect_high, "noul": nv},
                "choice 与 noul 两种问法可以互为交叉验证",
            )
        )

    # ---------------- 用例 2：相差几天 ----------------
    start = date(2026, 1, 30)
    end = date(2026, 2, 13)
    truth_days = (end - start).days  # 14
    r2 = ctx.ask(
        SUITE,
        "s05_interval",
        {"start": start.isoformat(), "end": end.isoformat()},
        {
            "days": choice(
                "`start` 到 `end` 相差多少天？",
                {str(i): "%d 天" % i for i in range(0, 41)},
            )
        },
        note="跨月的天数差（官方明说不可靠）",
    )
    if r2:
        picked = r2.answers["days"].choice
        direct_total += 1
        if picked == str(truth_days):
            direct_hits += 1
        checks.append(
            check(
                "跨月天数差",
                V_OK if picked == str(truth_days) else V_DEFECT,
                {"真值": truth_days, "Jev答": picked,
                 "confidence": r2.answers["days"].confidence},
                "跨月是多位数字运算的典型场景；这里出错完全在预期之内",
            )
        )

    # ---------------- 用例 3：是否落在窗口内 ----------------
    inside = date(2026, 3, 15)
    outside = date(2026, 4, 1)
    r3 = ctx.ask(
        SUITE,
        "s05_window",
        {
            "window_start": "2026-03-01",
            "window_end": "2026-03-31",
            "candidate_inside": inside.isoformat(),
            "candidate_outside": outside.isoformat(),
        },
        {
            "inside_in": noul("`candidate_inside` 是否落在 `window_start` 到 `window_end` 之间（含端点）？"),
            "outside_in": noul("`candidate_outside` 是否落在 `window_start` 到 `window_end` 之间（含端点）？"),
        },
        note="窗口包含性：一个明显在内，一个明显在外",
    )
    if r3:
        v_in = r3.answers["inside_in"].noul
        v_out = r3.answers["outside_in"].noul
        direct_total += 2
        if v_in is not None and v_in >= 0.5:
            direct_hits += 1
        if v_out is not None and v_out < 0.5:
            direct_hits += 1
        checks.append(
            check(
                "窗口包含性（内/外两个对照）",
                V_OK if (v_in is not None and v_in >= 0.5 and v_out is not None and v_out < 0.5) else V_DEFECT,
                {"窗内应为高": v_in, "窗外应为低": v_out},
                "窗口判断是结算/账期类需求的核心动作",
            )
        )

    # ---------------- 用例 4：混合格式 ----------------
    r4 = ctx.ask(
        SUITE,
        "s05_mixed_format",
        {"date_X": "27 Feb 2026", "date_Y": "2026-03-04"},
        {"x_earlier": noul("`date_X` 早于 `date_Y`")},
        note="两种日期书写格式混用",
    )
    if r4:
        v = r4.answers["x_earlier"].noul
        direct_total += 1
        if v is not None and v >= 0.5:
            direct_hits += 1
        checks.append(
            check(
                "混合日期格式的先后比较",
                V_OK if (v is not None and v >= 0.5) else V_DEFECT,
                {"真值": "date_X 更早", "noul": v},
                "官方特别提示混合格式会让情况变糟",
            )
        )

    # ---------------- 用例 5：相对表述 ----------------
    anchor = date(2026, 9, 28)
    last_wed = anchor - timedelta(days=anchor.weekday()) - timedelta(days=7) + timedelta(days=2)
    r5 = ctx.ask(
        SUITE,
        "s05_relative",
        {"today": anchor.isoformat(), "note": "会议安排在上周三。"},
        {
            "is_last_wed": noul("会议日期是 `%s` 吗？" % last_wed.isoformat()),
            "extract_weekday_ok": noul(
                "这段话里的「上周三」指的是 `%s`（相对 `today` 而言）吗？" % last_wed.isoformat()
            ),
        },
        note="相对时间表述（today=%s，上周三=%s）" % (anchor.isoformat(), last_wed.isoformat()),
    )
    if r5:
        v = r5.answers["is_last_wed"].noul
        direct_total += 1
        if v is not None and v >= 0.5:
            direct_hits += 1
        checks.append(
            check(
                "相对时间表述（上周三）是否解析正确",
                V_OK if (v is not None and v >= 0.5) else V_DEFECT,
                {"锚点": anchor.isoformat(), "真值": last_wed.isoformat(), "noul": v},
                "相对表述连人都容易歧义，模型错也不意外——真正的解法是把锚点显式写进 state",
            )
        )

    # ---------------- 用例 6：官方推荐的拆分法 ----------------
    r6 = ctx.ask(
        SUITE,
        "s05_decompose",
        {"date_A": d_a.isoformat(), "date_B": d_b.isoformat()},
        {
            "a_year": choice("`date_A` 的年份是哪一年？", {"2025": "2025", "2026": "2026", "2027": "2027"}),
            "a_month": choice("`date_A` 的月份是哪个月？", {m: m for m in MONTHS}),
            "a_day": choice("`date_A` 的日是哪一天？", {d: d for d in DAYS}),
            "b_year": choice("`date_B` 的年份是哪一年？", {"2025": "2025", "2026": "2026", "2027": "2027"}),
            "b_month": choice("`date_B` 的月份是哪个月？", {m: m for m in MONTHS}),
            "b_day": choice("`date_B` 的日是哪一天？", {d: d for d in DAYS}),
        },
        note="官方推荐的拆分：年/月/日各自抽取，比较留给代码",
    )
    if r6:
        def _assemble(prefix: str):
            try:
                y = r6.answers[prefix + "_year"].choice
                m = r6.answers[prefix + "_month"].choice
                d = r6.answers[prefix + "_day"].choice
                if y is None or m is None or d is None:
                    return None
                return date(int(y), int(m), int(d))
            except (ValueError, KeyError, TypeError):
                return None

        got_a, got_b = _assemble("a"), _assemble("b")
        extracted_ok = (got_a == d_a and got_b == d_b)
        code_verdict_ok = extracted_ok and (("A" if got_a < got_b else "B") == truth_earlier)
        checks.append(
            check(
                "拆分法：年/月/日抽取准确率",
                V_OK if extracted_ok else V_DEFECT,
                {"真值A": d_a.isoformat(), "抽取A": got_a.isoformat() if got_a else None,
                 "真值B": d_b.isoformat(), "抽取B": got_b.isoformat() if got_b else None},
                "抽取是「判断」→ 模型擅长；这一步命中，整条路线就成立",
            )
        )
        checks.append(
            check(
                "拆分法：代码比较后的最终结论",
                V_OK if code_verdict_ok else V_DEFECT,
                {"真值": truth_earlier, "拆分法结论": ("A" if (got_a and got_b and got_a < got_b) else "B") if extracted_ok else None},
                "这一项应当稳定为真；它是「日期问题该怎么写」的标准答案",
            )
        )

    # ---------------- 汇总 ----------------
    checks.append(
        check(
            "直接问日期的综合命中率",
            V_INFO,
            {"命中": direct_hits, "总数": direct_total, "命中率%": pct(direct_hits, direct_total)},
            "命中率明显低于 100% 即复现官方缺陷 #3；数值本身受样本量限制，看趋势即可",
        )
    )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "日期是「抽取 vs 算术」这条分界线的教科书场景。跑完这个套件，你应该能对团队说清："
            "模型只负责把 27 Feb 2026 变成 (2026,2,27)，差值一律 code 算。"
        ),
    )
