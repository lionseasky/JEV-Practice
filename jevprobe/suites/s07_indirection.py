"""S07 多层间接与结构不变量。

目标：确认官方失效场景 #4（多层间接）与 #8（常识性结构不变量）的边界在哪，
找到"最多问到第几跳"的可操作红线。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import choice, noul
from .base import Ctx, V_CLEAN, V_DEFECT, V_INFO, V_OK, V_WARN, check, pct, result

SUITE = "S07"
TITLE = "多层间接与结构不变量"
HYPOTHESIS = (
    "零跳（字段直读）稳定，一跳（一次映射）基本可用，两跳开始掉准确率；"
    "把同一个判断正反各问一次，答案应当自洽。"
)
OFFICIAL = (
    "jev-1.13 在需要额外层级间接的任务上会变吃力，它相当字面。"
    "官方建议减少跳数、把问题直接指向相关的 state 字段。"
    "失效场景 #8：同一件事要用同一种方式问，一致性约束留给代码强制。"
)

STATE = {
    "account": {
        "name": "Acme Robotics",
        "plan_code": "ent-2026",
        "seats": 240,
        "region": "cn-north",
    },
    "catalog": {
        "plan_codes": {
            "ent-2026": {"tier": "enterprise", "sla_hours": 4, "support": "dedicated"},
            "pro-2026": {"tier": "business", "sla_hours": 24, "support": "email"},
            "free": {"tier": "starter", "sla_hours": 72, "support": "community"},
        }
    },
    "sla_policy": {
        "enterprise": {"first_response_hours": 4, "escalation": "pagerduty"},
        "business": {"first_response_hours": 24, "escalation": "email"},
        "starter": {"first_response_hours": 72, "escalation": "none"},
    },
    "ticket": {"opened_hours_ago": 6, "severity": "high"},
}


def run(ctx: Ctx) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    hop_rows: List[Dict[str, Any]] = []

    # ---------------- 跳数阶梯：同一个真值，三种问法 ----------------
    # 真值链路：acct.plan_code=ent-2026 → tier=enterprise → first_response_hours=4
    # 当前工单已开 6 小时 > 4 小时 → 已超出首次响应承诺
    hop0 = ctx.ask(
        SUITE,
        "s07_hop0",
        STATE,
        {"q": noul("`account.plan_code` 是否等于 'ent-2026'？")},
        note="0 跳：直接读字段",
    )
    if hop0:
        v = hop0.answers["q"].noul
        ok = v is not None and v >= 0.5
        hop_rows.append({"跳数": 0, "问题": "plan_code 是否等于 ent-2026", "noul": v, "正确": ok})
        checks.append(check("0 跳（字段直读）", V_OK if ok else V_DEFECT, {"noul": v}, "基线能力"))

    hop1 = ctx.ask(
        SUITE,
        "s07_hop1",
        STATE,
        {"q": noul("`account` 所属的方案等级（tier）是不是 enterprise？")},
        note="1 跳：plan_code → catalog.plan_codes → tier",
    )
    if hop1:
        v = hop1.answers["q"].noul
        ok = v is not None and v >= 0.5
        hop_rows.append({"跳数": 1, "问题": "tier 是否 enterprise", "noul": v, "正确": ok})
        checks.append(check("1 跳（一次映射）", V_OK if ok else V_DEFECT, {"noul": v}, ""))

    hop2 = ctx.ask(
        SUITE,
        "s07_hop2",
        STATE,
        {"q": noul(
            "该工单是否已经超出了这个账户的首次响应时间承诺？"
            "（请依次使用 `catalog.plan_codes` 与 `sla_policy` 中的信息判断）"
        )},
        note="2 跳：plan_code → tier → first_response_hours，再与 opened_hours_ago 比较",
    )
    if hop2:
        v = hop2.answers["q"].noul
        ok = v is not None and v >= 0.5  # 真值：6h > 4h，已超时
        hop_rows.append({"跳数": 2, "问题": "是否超出首次响应承诺", "noul": v, "正确": ok})
        checks.append(
            check(
                "2 跳（含数值比较）",
                V_OK if ok else V_DEFECT,
                {"noul": v, "真值": "已超出（6h > 4h）"},
                "两跳 + 一次数值比较，是官方警告的典型形态",
            )
        )

    hop3 = ctx.ask(
        SUITE,
        "s07_hop3",
        STATE,
        {"q": noul(
            "如果该账户的工单在本小时内仍未被首次响应，是否会触发 pagerduty 升级？"
        )},
        note="3 跳 + 反事实推理（未显式给出映射链路）",
    )
    if hop3:
        v = hop3.answers["q"].noul
        hop_rows.append({"跳数": 3, "问题": "未显式指路时的反事实推理", "noul": v, "正确": None})
        checks.append(
            check(
                "3 跳（未显式指路，反事实）",
                V_INFO,
                {"noul": v},
                "这一问刻意不指出数据在哪，用来观察'不指路'时的表现退化",
            )
        )

    if hop_rows:
        scored = [r for r in hop_rows if r["正确"] is not None]
        checks.append(
            check(
                "跳数 — 准确率曲线",
                V_INFO,
                [{"跳数": r["跳数"], "noul": r["noul"], "正确": r["正确"]} for r in scored],
                "实操红线：能压到 1 跳就不要 2 跳；把映射表预先算进 state 是最有效的改法",
            )
        )

    # ---------------- 修复版：把映射预先算好，降回 0 跳 ----------------
    flat_state = dict(STATE)
    flat_state["derived"] = {
        "tier": "enterprise",
        "first_response_hours": 4,
        "sla_breached": True,
        "escalation": "pagerduty",
    }
    r_flat = ctx.ask(
        SUITE,
        "s07_hop2_flat",
        flat_state,
        {"q": noul("`derived.sla_breached` 是否为真？")},
        note="同一个真值，但把派生字段预先算进 state，降回 0 跳",
    )
    if r_flat and hop2:
        v_flat = r_flat.answers["q"].noul
        checks.append(
            check(
                "把派生数据预先算进 state 后的表现",
                V_OK if (v_flat is not None and v_flat >= 0.5) else V_WARN,
                {"2跳版": hop2.answers["q"].noul, "0跳版": v_flat},
                "这是「减少跳数」最工程化的做法：让上游代码多做一步，模型少想一层",
            )
        )

    # ---------------- 结构不变量：正反各问一次 ----------------
    inv_state = {"a": "Changsha", "b": "Harbin", "month": "January",
                 "note": "一月的平均气温：长沙约 5°C，哈尔滨约 -18°C。"}
    r_fwd = ctx.ask(
        SUITE,
        "s07_invariant_fwd",
        inv_state,
        {"colder": choice("哪个城市一月更冷？", {"a": "a 更冷", "b": "b 更冷"})},
        note="正向问法",
    )
    r_rev = ctx.ask(
        SUITE,
        "s07_invariant_rev",
        inv_state,
        {"colder": choice("哪个城市一月更冷？", {"b": "b 更冷", "a": "a 更冷"})},
        note="反向问法（选项顺序颠倒）",
    )
    if r_fwd and r_rev:
        f = r_fwd.answers["colder"].choice
        rv = r_rev.answers["colder"].choice
        consistent = f == rv
        checks.append(
            check(
                "选项顺序颠倒后的答案是否自洽",
                V_OK if consistent else V_DEFECT,
                {"正向": f, "反向": rv,
                 "正向confidence": r_fwd.answers["colder"].confidence,
                 "反向confidence": r_rev.answers["colder"].confidence},
                "不一致即复现失效场景 #8：位置偏好会让同一判断给出两个答案",
            )
        )
        if f and rv:
            checks.append(
                check(
                    "正确答案（哈尔滨更冷）",
                    V_OK if (f == "b" and rv == "b") else V_DEFECT,
                    {"正向": f, "反向": rv},
                    "对照项：看它是真的会判断，还是只在赌选项位置",
                )
            )

    # ---------------- 确定性：同一请求发两次 ----------------
    q_same = {"q": noul("`account.seats` 是否大于 200？")}
    d1 = ctx.ask(SUITE, "s07_determinism_1", STATE, dict(q_same), note="确定性检查 第 1 次")
    d2 = ctx.ask(SUITE, "s07_determinism_2", STATE, dict(q_same), note="确定性检查 第 2 次")
    if d1 and d2:
        v1, v2 = d1.answers["q"].noul, d2.answers["q"].noul
        same = v1 == v2
        checks.append(
            check(
                "同一请求重复两次是否完全一致",
                V_OK if same else V_WARN,
                {"第1次": v1, "第2次": v2, "差值": (round(abs(v1 - v2), 4) if None not in (v1, v2) else None)},
                "若不一致，你就不能对 noul 用严格 == 阈值做边界判断，需要留缓冲带",
            )
        )

    return result(
        SUITE,
        TITLE,
        HYPOTHESIS,
        OFFICIAL,
        checks,
        summary=(
            "把「跳数」当成一个要主动管理的成本项：每多一跳，准确率和可解释性都在掉。"
            "最有效的手段是上游预计算，把 2 跳压成 0 跳。"
        ),
    )
