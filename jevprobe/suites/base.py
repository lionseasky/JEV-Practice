"""探测套件共用的基础设施：度量工具、用例记录、结果结构。"""

from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List, Optional

from ..client import JevError

# 判读词汇表 —— 刻意区分"复现了官方缺陷"和"调用失败"，
# 因为对能力摸底来说，复现缺陷是有价值的结论，不是 bug。
V_OK = "符合预期"
V_DEFECT = "缺陷复现"
V_CLEAN = "未见缺陷"
V_INFO = "已测量"
V_WARN = "需注意"
V_ERROR = "调用失败"


# ------------------------------------------------------------------ 度量工具


def preview(value: Any, limit: int = 360) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " …"


def pct(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


def mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 4) if vals else None


def percentile(values: List[Optional[float]], p: float) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 1)
    rank = (len(vals) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(vals) - 1)
    frac = rank - lo
    return round(vals[lo] * (1 - frac) + vals[hi] * frac, 1)


def check(name: str, verdict: str, value: Any = None, note: str = "") -> Dict[str, Any]:
    return {"name": name, "verdict": verdict, "value": value, "note": note}


# ------------------------------------------------------------------ 执行上下文


class Ctx:
    """承载客户端、配置与用例日志，让套件专注于"问什么"。"""

    def __init__(self, client, config, log):
        self.client = client
        self.config = config
        self._log = log
        self.cases: List[Dict[str, Any]] = []

    def ask(
        self,
        suite: str,
        case_id: str,
        state: Any,
        questions: Dict[str, Dict[str, Any]],
        note: str = "",
        model: Optional[str] = None,
    ):
        """发一次请求并把用例登记进日志。失败返回 None，不中断整个套件。"""
        try:
            resp = self.client.system_one(state, questions, model=model)
            record = {
                "suite": suite,
                "case_id": case_id,
                "note": note,
                "ok": True,
                "state_preview": preview(state, 600),
                "questions": questions,
                "answers": {k: v.data for k, v in resp.answers.items()},
                "response_model": resp.model,
                "usage": resp.usage,
                "latency_ms": round(resp.latency_ms, 1),
                "error": None,
            }
            self.cases.append(record)
            return resp
        except JevError as exc:
            self.cases.append(
                {
                    "suite": suite,
                    "case_id": case_id,
                    "note": note,
                    "ok": False,
                    "state_preview": preview(state, 600),
                    "questions": questions,
                    "answers": {},
                    "response_model": None,
                    "usage": {},
                    "latency_ms": None,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                }
            )
            self._log("  [失败] %s → %s" % (case_id, exc))
            return None

    def cases_for(self, suite: str) -> List[Dict[str, Any]]:
        return [c for c in self.cases if c["suite"] == suite]


def result(
    suite_id: str,
    title: str,
    hypothesis: str,
    official_baseline: str,
    checks: List[Dict[str, Any]],
    summary: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": suite_id,
        "title": title,
        "hypothesis": hypothesis,
        "official_baseline": official_baseline,
        "checks": checks,
        "summary": summary,
        "extra": extra or {},
    }
