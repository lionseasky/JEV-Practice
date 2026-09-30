"""Jev / TypeSafe System One HTTP 客户端（纯标准库，零依赖）。

设计要点：
  * 完整实现官方错误码语义：401 鉴权、422 校验、429 限速、529 过载。
  * 对 429 / 529 / 5xx / 网络错误做指数退避 + 抖动重试，并遵守 retry-after 头。
  * 记录每次调用的延迟、token 用量、原始请求与响应，供报告与成本核算使用。
  * 内置 mock 模式，让整条报告管线在无 Key、无网络时也能跑通自检。
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- 异常体系


class JevError(Exception):
    """所有 Jev 调用异常的基类。"""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class AuthError(JevError):
    """401：Key 缺失或无效。"""


class ValidationError(JevError):
    """422：请求体校验失败（字段名会出现在 body 里）。"""


class RateLimitError(JevError):
    """429：超出限速。"""


class OverloadedError(JevError):
    """529：服务过载。"""


class TransportError(JevError):
    """网络层错误。"""


# ---------------------------------------------------------------- 问题构造器


def noul(instructions: Any, criteria: Any = None) -> Dict[str, Any]:
    """是/否判断，返回 0~1 的概率。criteria 可选，用于说明 yes/no 的含义。"""
    q: Dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria is not None:
        q["criteria"] = criteria
    return q


def choice(instructions: Any, criteria: Dict[str, Any]) -> Dict[str, Any]:
    """从给定选项里选一个。criteria 是 {选项名: 说明}，最多 255 个。"""
    if not isinstance(criteria, dict) or not criteria:
        raise ValueError("choice 的 criteria 必须是非空 dict")
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: Any, criteria: List[str]) -> Dict[str, Any]:
    """按有序档位打分。criteria 是数组，2~10 档，按顺序描述每一档。"""
    if not isinstance(criteria, list) or not (2 <= len(criteria) <= 10):
        raise ValueError("score 的 criteria 必须是 2~10 个元素的数组")
    return {"type": "score", "instructions": instructions, "criteria": criteria}


# ---------------------------------------------------------------- 答案包装


class Answer:
    """一条类型化答案的只读包装，方便断言。"""

    def __init__(self, question_id: str, data: Dict[str, Any]):
        self.id = question_id
        self.data = data or {}

    @property
    def type(self) -> Optional[str]:
        return self.data.get("type")

    @property
    def noul(self) -> Optional[float]:
        return self.data.get("noul")

    @property
    def choice(self) -> Optional[str]:
        return self.data.get("choice")

    @property
    def score(self) -> Optional[float]:
        return self.data.get("score")

    @property
    def confidence(self) -> Optional[float]:
        """只有 choice / score 才有 confidence，noul 没有。"""
        return self.data.get("confidence")

    @property
    def probabilities(self) -> Optional[Dict[str, float]]:
        return self.data.get("probabilities")

    @property
    def legend(self) -> Optional[Dict[str, str]]:
        return self.data.get("legend")

    @property
    def top_probability(self) -> Optional[float]:
        probs = self.probabilities
        if not probs:
            return None
        return max(probs.values())

    def probability_of(self, key: str) -> Optional[float]:
        probs = self.probabilities or {}
        return probs.get(key)

    def __repr__(self) -> str:  # pragma: no cover
        return "Answer(%s, %s)" % (self.id, self.data)


class JevResponse:
    def __init__(
        self,
        model: Optional[str],
        answers: Dict[str, Answer],
        usage: Dict[str, Any],
        latency_ms: float,
        request_payload: Dict[str, Any],
        raw: Dict[str, Any],
        status: int = 200,
        attempts: int = 1,
    ):
        self.model = model
        self.answers = answers
        self.usage = usage or {}
        self.latency_ms = latency_ms
        self.request_payload = request_payload
        self.raw = raw
        self.status = status
        self.attempts = attempts

    # 便捷访问
    def noul(self, key: str) -> Optional[float]:
        return self.answers[key].noul if key in self.answers else None

    def choice(self, key: str) -> Optional[str]:
        return self.answers[key].choice if key in self.answers else None

    def score(self, key: str) -> Optional[float]:
        return self.answers[key].score if key in self.answers else None

    def confidence(self, key: str) -> Optional[float]:
        return self.answers[key].confidence if key in self.answers else None

    @property
    def input_tokens(self) -> int:
        try:
            return int(self.usage.get("input_tokens") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def output_tokens(self) -> int:
        try:
            return int(self.usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            return 0


def parse_model_list(data: Any) -> List[Dict[str, str]]:
    """把 GET /v1/models 的返回归一化成 [{"name","description","release_date"}]。

    实测（2026-09）真实结构是 `{"models":[{"name":...,"description":...,"release_date":...}]}`，
    而文档/其他网关出现过 `{"data":[{"id":...}]}` 的形态，所以两种都兼容。
    """
    if not isinstance(data, dict):
        return []
    for key in ("models", "data"):
        items = data.get(key)
        if isinstance(items, list):
            out: List[Dict[str, str]] = []
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("id")
                    if not name:
                        continue
                    out.append(
                        {
                            "name": str(name),
                            "description": str(item.get("description") or ""),
                            "release_date": str(item.get("release_date") or ""),
                        }
                    )
                elif isinstance(item, str):
                    out.append({"name": item, "description": "", "release_date": ""})
            if out:
                return out
    return []


# ---------------------------------------------------------------- 重试判定

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 529}


class JevClient:
    """真实 HTTP 客户端。"""

    is_mock = False

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.typesafe.ai",
        model: str = "jev-latest",
        timeout: float = 60.0,
        max_retries: int = 4,
        verbose: bool = False,
        log=None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.verbose = verbose
        self._log = log or (lambda msg: None)
        # 统计
        self.stats = {
            "requests": 0,
            "retries": 0,
            "errors": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "status_counts": {},
        }

    # -------------------------------------------------- 底层 HTTP

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Accept": "application/json",
            "User-Agent": "jev-probe/1.0 (+capability-audit)",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    status = resp.status
                    retry_after = resp.headers.get("retry-after")
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                parsed = json.loads(body) if body.strip() else {}
                self.stats["status_counts"][status] = self.stats["status_counts"].get(status, 0) + 1
                parsed["__latency_ms"] = elapsed_ms
                parsed["__attempts"] = attempt + 1
                parsed["__retry_after"] = retry_after
                return parsed

            except urllib.error.HTTPError as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                status = exc.code
                raw_body = exc.read().decode("utf-8", "replace")
                try:
                    parsed_body = json.loads(raw_body) if raw_body.strip() else {}
                except ValueError:
                    parsed_body = {"raw": raw_body}
                retry_after = exc.headers.get("retry-after") if exc.headers else None
                self.stats["status_counts"][status] = self.stats["status_counts"].get(status, 0) + 1

                message = _extract_error_message(parsed_body) or ("HTTP %s" % status)

                if status in RETRYABLE_STATUS and attempt < self.max_retries:
                    self.stats["retries"] += 1
                    delay = _backoff_seconds(attempt, retry_after)
                    self._log(
                        "  [retry] HTTP %s：%s；%.1fs 后第 %d 次重试"
                        % (status, message, delay, attempt + 2)
                    )
                    time.sleep(delay)
                    last_error = _status_to_error(status, message, parsed_body)
                    continue

                raise _status_to_error(status, message, parsed_body)

            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    self.stats["retries"] += 1
                    delay = _backoff_seconds(attempt, None)
                    self._log("  [retry] 网络错误：%s；%.1fs 后重试" % (exc, delay))
                    time.sleep(delay)
                    last_error = TransportError(str(exc))
                    continue
                raise TransportError("网络错误：%s" % exc)

        raise last_error or TransportError("请求失败且无更多信息")

    # -------------------------------------------------- 公开 API

    def list_models(self) -> Dict[str, Any]:
        """GET /v1/models —— 不消耗判断额度，用于验证 Key。"""
        return self._request("GET", "/v1/models")

    def system_one(
        self,
        state: Any,
        questions: Dict[str, Dict[str, Any]],
        model: Optional[str] = None,
    ) -> JevResponse:
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": questions,
        }
        self.stats["requests"] += 1
        raw = self._request("POST", "/v1/systemone", payload)

        latency_ms = float(raw.get("__latency_ms") or 0.0)
        attempts = int(raw.get("__attempts") or 1)
        usage = raw.get("usage") or {}
        self.stats["input_tokens"] += int(usage.get("input_tokens") or 0)
        self.stats["output_tokens"] += int(usage.get("output_tokens") or 0)

        answers = {
            key: Answer(key, value)
            for key, value in (raw.get("answers") or {}).items()
        }
        return JevResponse(
            model=raw.get("model"),
            answers=answers,
            usage=usage,
            latency_ms=latency_ms,
            request_payload=payload,
            raw={k: v for k, v in raw.items() if not k.startswith("__")},
            attempts=attempts,
        )


# ---------------------------------------------------------------- 错误处理辅助


def _backoff_seconds(attempt: int, retry_after: Optional[str]) -> float:
    """指数退避 + 抖动；优先遵守 retry-after 头。"""
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except (TypeError, ValueError):
            pass
    base = 0.8 * (2 ** attempt)
    return min(base + random.uniform(0, 0.4 * base), 30.0)


def _extract_error_message(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message") or err.get("type") or json.dumps(err, ensure_ascii=False)
        if isinstance(err, str):
            return err
        if "message" in body:
            return str(body["message"])
        if "detail" in body:
            return json.dumps(body["detail"], ensure_ascii=False)
    return None


def _status_to_error(status: int, message: str, body: Any) -> JevError:
    if status == 401:
        return AuthError("鉴权失败（401）：%s" % message, status, body)
    if status == 422:
        return ValidationError("请求校验失败（422）：%s" % message, status, body)
    if status == 429:
        return RateLimitError("超出限速（429）：%s" % message, status, body)
    if status == 529:
        return OverloadedError("服务过载（529）：%s" % message, status, body)
    return JevError("HTTP %s：%s" % (status, message), status, body)


# ---------------------------------------------------------------- Mock 客户端


class MockJevClient(JevClient):
    """离线自检用的假客户端。

    注意：它产出的数字是**伪造**的，只用来验证报告管线，绝不可当作 Jev 的能力测量。
    """

    is_mock = True

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("api_key", "mock-key")
        super().__init__(*args, **kwargs)

    def list_models(self) -> Dict[str, Any]:
        return {
            "data": [
                {"id": "jev-latest", "object": "model", "description": "[MOCK] 最新稳定版"},
                {"id": "jev-preview", "object": "model", "description": "[MOCK] 预览版"},
            ],
            "__latency_ms": 12.0,
            "__attempts": 1,
        }

    def system_one(self, state, questions, model=None) -> JevResponse:
        self.stats["requests"] += 1
        time.sleep(random.uniform(0.05, 0.18))

        text = json.dumps(state, ensure_ascii=False)
        answers: Dict[str, Answer] = {}
        # 用内容哈希制造确定性但“看起来有起伏”的假答案
        seed = abs(hash(text)) % (2 ** 31)

        for idx, (key, q) in enumerate(questions.items()):
            rnd = random.Random(seed + idx * 7919)
            qtype = q.get("type")
            if qtype == "noul":
                value = round(rnd.uniform(0.05, 0.97), 4)
                answers[key] = Answer(key, {"type": "noul", "noul": value})
            elif qtype == "choice":
                crit = list((q.get("criteria") or {}).keys())
                if not crit:
                    crit = ["unknown"]
                winner = crit[rnd.randrange(len(crit))]
                n = len(crit)
                rest = max(0.0, 0.9 - 0.0)
                probs = {c: round(rnd.uniform(0.0, 0.12), 4) for c in crit}
                probs[winner] = round(max(0.35, 0.92 - 0.05 * n), 4)
                total = sum(probs.values()) or 1.0
                probs = {c: round(v / total, 4) for c, v in probs.items()}
                p = max(probs.values())
                conf = round((n * p - 1) / (n - 1), 4) if n > 1 else 1.0
                answers[key] = Answer(
                    key,
                    {
                        "type": "choice",
                        "choice": winner,
                        "confidence": conf,
                        "probabilities": probs,
                    },
                )
            elif qtype == "score":
                levels = q.get("criteria") or ["low", "high"]
                n = len(levels)
                pos = rnd.randrange(n)
                probs = {str(i): round(rnd.uniform(0.01, 0.2), 4) for i in range(n)}
                probs[str(pos)] = 0.75
                total = sum(probs.values()) or 1.0
                probs = {k: round(v / total, 4) for k, v in probs.items()}
                value = sum(float(k) * v for k, v in probs.items())
                p = max(probs.values())
                conf = round((n * p - 1) / (n - 1), 4) if n > 1 else 1.0
                answers[key] = Answer(
                    key,
                    {
                        "type": "score",
                        "score": round(value, 4),
                        "confidence": conf,
                        "legend": {str(i): lv for i, lv in enumerate(levels)},
                        "probabilities": probs,
                    },
                )

        payload = {"state": state, "model": model or self.model, "questions": questions}
        input_tokens = max(1, len(json.dumps(payload, ensure_ascii=False)) // 4)
        self.stats["input_tokens"] += input_tokens
        raw = {
            "model": "[MOCK] jev-1.13.0",
            "answers": {k: v.data for k, v in answers.items()},
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        }
        return JevResponse(
            model=raw["model"],
            answers=answers,
            usage=raw["usage"],
            latency_ms=random.uniform(180.0, 620.0),
            request_payload=payload,
            raw=raw,
            attempts=1,
        )


def build_client(config, mock: bool = False, log=None) -> JevClient:
    if mock:
        return MockJevClient(
            base_url=config.base_url,
            model=config.model,
            timeout=config.timeout_seconds,
            max_retries=1,
            log=log,
        )
    if not config.has_key:
        raise AuthError(
            "没有找到可用的 TYPESAFE_API_KEY（来源：%s）。\n"
            "请在 .env 文件里填入你的 Key，例如：\n"
            "    TYPESAFE_API_KEY=你的密钥\n"
            "领取地址：https://console.typesafe.ai/keys" % config.key_source
        )
    return JevClient(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
        log=log,
    )
