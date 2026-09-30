"""探测套件注册表。新增套件只要在这里挂一行。"""

from __future__ import annotations

from typing import Dict, List

from . import (
    s01_primitives,
    s02_confidence,
    s03_literalism,
    s04_counting,
    s05_dates,
    s06_noise,
    s07_indirection,
    s08_language,
    s09_perf,
)

# 顺序即执行顺序：先确认契约，再逐条验证官方公布的失效边界，最后算账。
SUITES: List = [
    s01_primitives,
    s02_confidence,
    s03_literalism,
    s04_counting,
    s05_dates,
    s06_noise,
    s07_indirection,
    s08_language,
    s09_perf,
]

BY_ID: Dict[str, object] = {m.SUITE.lower(): m for m in SUITES}
# 也允许用两位序号简写，如 s1 / 1
for _m in SUITES:
    BY_ID[_m.SUITE[1:].lstrip("0")] = _m


def resolve(names: List[str]) -> List:
    """把 ['all'] / ['s04','s05'] / ['s4'] 解析成套件列表。"""
    if not names or "all" in [n.lower() for n in names]:
        return list(SUITES)
    picked = []
    unknown = []
    for name in names:
        key = name.strip().lower()
        module = BY_ID.get(key) or BY_ID.get(key.lstrip("s").lstrip("0") or key)
        if module is None:
            unknown.append(name)
        elif module not in picked:
            picked.append(module)
    if unknown:
        raise SystemExit("未知套件：%s（可用：%s）" % (", ".join(unknown),
                                                  ", ".join(m.SUITE for m in SUITES)))
    return picked
