"""Jev Playground —— 本地 Web 界面（纯标准库 http.server，零第三方依赖）。

设计原则：
  * **只绑定 127.0.0.1**，不对外暴露。
  * **API Key 只存在于 Python 进程内**，浏览器永远拿不到它。页面通过 `/api/eval` 由服务端代理调用。
  * 静态文件直接读 `webui/` 目录，改动后刷新即生效（`Cache-Control: no-store`）。
  * 服务端不做任何判断逻辑，只是「表单 → 官方 API → 带类型的答案」的搬运工，
    顺便把延迟、token 与成本算给前端看。

启动：`python3 run.py --ui`
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import OFFICIAL, __version__
from .client import (
    AuthError,
    JevError,
    OverloadedError,
    RateLimitError,
    TransportError,
    ValidationError,
    build_client,
    parse_model_list,
)
from .presets import PRESETS, validate_presets

WEBUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
MAX_BODY_BYTES = 4 * 1024 * 1024
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

# 拿不到 /v1/models 时的兜底清单（官方别名 + 当前版本 ID）
FALLBACK_MODELS = ["jev-latest", "jev-preview", OFFICIAL["model_id"]]

MODEL_NOTES = {
    "jev-latest": "最新稳定版别名。会随新版发布漂移 —— 生产环境别用它。",
    "jev-preview": "最新发布版别名，可能比 latest 更超前。",
    OFFICIAL["model_id"]: "当前版本 ID。已经调过阈值就钉死它，自己决定何时升级。",
}


def _error_info(exc: Exception) -> Tuple[str, str]:
    """把异常翻译成（类型, 处置建议）。"""
    if isinstance(exc, AuthError):
        return "鉴权失败 401", "检查 .env 里的 TYPESAFE_API_KEY：是否填了、有没有多余空格、是否已失效。"
    if isinstance(exc, ValidationError):
        return "请求校验失败 422", "看返回体里指出的字段名，多半是 choice 缺 criteria 或 score 档位数不在 2~10。"
    if isinstance(exc, RateLimitError):
        return "超出限速 429", "客户端已自动退避重试。持续出现就降低并发；官方限速会动态调整。"
    if isinstance(exc, OverloadedError):
        return "服务过载 529", "这是官方侧的问题，稍后重试即可。"
    if isinstance(exc, TransportError):
        return "网络错误", "检查本机网络或代理设置。"
    if isinstance(exc, JevError):
        return "调用失败", str(exc)
    return type(exc).__name__, str(exc)


class PlaygroundServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, config, client, models: List[str],
                 model_notes: Dict[str, str], mock: bool):
        super().__init__(addr, handler)
        self.config = config
        self.client = client
        self.models = models
        self.model_notes = model_notes
        self.mock = mock
        self.calls = 0
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "JevPlayground/" + __version__
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ 输出辅助

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            BaseHTTPRequestHandler.log_message(self, fmt, *args)
        else:
            print("  · %s" % (fmt % args), flush=True)

    # ------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in STATIC_FILES:
                filename, ctype = STATIC_FILES[path]
                self._serve_static(filename, ctype)
            elif path == "/api/config":
                self._json(200, self._config_payload())
            elif path == "/api/health":
                self._json(200, {"ok": True, "version": __version__})
            else:
                self._json(404, {"ok": False, "error": "未知路径 %s" % path})
        except BrokenPipeError:
            pass
        except Exception as exc:  # 服务端自身异常也要给出可读响应
            self._safe_error(exc)

    def _serve_static(self, filename: str, ctype: str) -> None:
        full = os.path.join(WEBUI_DIR, filename)
        if not os.path.isfile(full):
            self._json(500, {"ok": False, "error": "缺少静态文件 %s" % filename})
            return
        with open(full, "rb") as f:
            body = f.read()
        self._send(200, body, ctype)

    def _config_payload(self) -> Dict[str, Any]:
        srv: PlaygroundServer = self.server  # type: ignore[assignment]
        cfg = srv.config
        return {
            "ok": True,
            "version": __version__,
            "configured": bool(cfg.has_key) or srv.mock,
            "mock": srv.mock,
            "key_source": ("MOCK 模式（数据伪造）" if srv.mock else cfg.key_source),
            "base_url": cfg.base_url,
            "model_alias": cfg.model,
            "models": srv.models,
            "model_notes": srv.model_notes,
            "confidence_act": cfg.data.get("confidence_act", 0.9),
            "confidence_confirm": cfg.data.get("confidence_confirm", 0.6),
            "noul_threshold": cfg.data.get("noul_threshold", 0.5),
            "official": {
                "model_id": OFFICIAL["model_id"],
                "price_usd_per_mtok_input": OFFICIAL["price_usd_per_mtok_input"],
                "choice_max_options": OFFICIAL["choice_max_options"],
                "score_min_levels": OFFICIAL["score_min_levels"],
                "score_max_levels": OFFICIAL["score_max_levels"],
                "context_tokens_total": OFFICIAL["context_tokens_total"],
            },
            "presets": PRESETS,
            "stats": srv.client.stats if srv.client else {},
        }

    # ------------------------------------------------------------ POST

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/eval":
                self._handle_eval()
            else:
                self._json(404, {"ok": False, "error": "未知路径 %s" % path})
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._safe_error(exc)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大（上限 4MB）")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("请求体不是合法 JSON：%s" % exc)
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _handle_eval(self) -> None:
        srv: PlaygroundServer = self.server  # type: ignore[assignment]

        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._json(400, {"ok": False, "kind": "请求格式错误", "error": str(exc)})
            return

        model = body.get("model")
        state = body.get("state")
        questions = body.get("questions")

        # ---- 服务端二次校验：前端校验可以被绕过，这里兜底
        if not isinstance(model, str) or not model.strip():
            self._json(400, {"ok": False, "kind": "参数错误", "error": "model 必须是非空字符串"})
            return
        if state is None or (isinstance(state, str) and not state.strip()):
            self._json(400, {"ok": False, "kind": "参数错误", "error": "state 不能为空"})
            return
        if not isinstance(state, (str, dict, list)):
            self._json(400, {"ok": False, "kind": "参数错误",
                             "error": "state 必须是字符串、JSON 对象或数组"})
            return
        if not isinstance(questions, dict) or not questions:
            self._json(400, {"ok": False, "kind": "参数错误", "error": "questions 必须是非空对象"})
            return
        for qid, q in questions.items():
            if not isinstance(q, dict) or q.get("type") not in ("choice", "score", "noul"):
                self._json(400, {"ok": False, "kind": "参数错误",
                                 "error": "问题 %s 的 type 必须是 choice/score/noul" % qid})
                return
            if q.get("instructions") in (None, "", [], {}):
                self._json(400, {"ok": False, "kind": "参数错误",
                                 "error": "问题 %s 缺少 instructions" % qid})
                return

        if srv.client is None:
            self._json(200, {"ok": False, "kind": "未配置",
                             "error": "服务端没有可用的 API Key",
                             "hint": "在 .env 里填入 TYPESAFE_API_KEY 后重启界面"})
            return

        with srv.lock:
            srv.calls += 1

        try:
            resp = srv.client.system_one(state, questions, model=model)
        except JevError as exc:
            kind, hint = _error_info(exc)
            self._json(200, {
                "ok": False,
                "kind": kind,
                "error": str(exc),
                "hint": hint,
                "status": getattr(exc, "status", None),
                "body": getattr(exc, "body", None),
            })
            return
        except Exception as exc:
            kind, hint = _error_info(exc)
            self._json(200, {"ok": False, "kind": kind, "error": str(exc), "hint": hint})
            return

        cost = resp.input_tokens * OFFICIAL["price_usd_per_mtok_input"] / 1e6
        self._json(200, {
            "ok": True,
            "alias": model,
            "model": resp.model,
            "answers": {k: v.data for k, v in resp.answers.items()},
            "usage": resp.usage,
            "latency_ms": round(resp.latency_ms, 1),
            "attempts": resp.attempts,
            "cost_usd": round(cost, 8),
        })

    # ------------------------------------------------------------ 兜底

    def _safe_error(self, exc: Exception) -> None:
        try:
            self._json(500, {"ok": False, "kind": type(exc).__name__, "error": str(exc)})
        except Exception:
            pass


# ---------------------------------------------------------------- 模型清单


def resolve_models(client) -> Tuple[List[str], Dict[str, str], Optional[str]]:
    """返回（模型名清单, 模型说明, 警告信息）。

    实测真实结构是 {"models":[{"name","description","release_date"}]}，
    解析交给 client.parse_model_list 归一化；失败则回退到内置清单。
    """
    if client is None:
        return list(FALLBACK_MODELS), {}, None
    try:
        data = client.list_models()
    except JevError as exc:
        return list(FALLBACK_MODELS), {}, "无法获取模型列表（%s），已回退到内置清单" % exc

    parsed = parse_model_list(data)
    if not parsed:
        return list(FALLBACK_MODELS), {}, "模型列表返回结构无法识别，已回退到内置清单"

    names: List[str] = []
    notes: Dict[str, str] = {}
    for item in parsed:
        name = item["name"]
        names.append(name)
        bits = []
        if item.get("description"):
            bits.append(item["description"])
        if item.get("release_date"):
            bits.append("发布于 " + item["release_date"][:10])
        if name in MODEL_NOTES:
            bits.append(MODEL_NOTES[name])
        notes[name] = " ｜ ".join(bits) or name

    # 版本 ID 通常不在列表里，但 model 字段接受它 —— 补一个方便钉版本
    if OFFICIAL["model_id"] not in names:
        names.append(OFFICIAL["model_id"])
        notes[OFFICIAL["model_id"]] = MODEL_NOTES[OFFICIAL["model_id"]]
    return names, notes, None


# ---------------------------------------------------------------- 启动


def serve(config, mock: bool = False, port: int = 8765, open_browser: bool = True,
          verbose: bool = False) -> int:
    print("=" * 68)
    print("  Jev Playground v%s" % __version__)
    print("=" * 68)

    # 预设自检：拦截「集合型 state + 模糊指代」这类会让答案全部相同的写法
    preset_problems = validate_presets()
    if preset_problems:
        print("  ⚠️ 预设自检发现 %d 个问题：" % len(preset_problems))
        for problem in preset_problems:
            print("     - %s" % problem)
        print()

    client = None
    if mock:
        client = build_client(config, mock=True)
        print("  模式      : MOCK 离线自检（所有数字伪造，仅用于验证界面）")
    elif config.has_key:
        client = build_client(config, mock=False)
        print("  模式      : 真实调用")
        print("  Key 来源  : %s" % config.key_source)
    else:
        print("  模式      : 未配置 Key（界面可打开，但无法提交）")
        print("  提示      : 在 .env 第 8 行填入 TYPESAFE_API_KEY，或先用 --mock 预览界面")

    print("  接口      : %s" % config.base_url)

    models, model_notes, warning = resolve_models(client)
    if warning:
        print("  注意      : %s" % warning)
    print("  可用模型  : %s" % ", ".join(models))

    httpd = None
    chosen = None
    for candidate in range(port, port + 12):
        try:
            httpd = PlaygroundServer(
                ("127.0.0.1", candidate), Handler, config, client, models, model_notes, mock
            )
            chosen = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print("\n❌ 端口 %d~%d 都被占用了，换一个：python3 run.py --ui --ui-port 9000" % (port, port + 11))
        return 2

    httpd.verbose = verbose  # type: ignore[attr-defined]
    url = "http://127.0.0.1:%d/" % chosen
    print("  界面地址  : %s" % url)
    print("=" * 68)
    print("  按 Ctrl+C 停止\n")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
        if client is not None:
            stats = client.stats
            total = stats.get("input_tokens", 0) * OFFICIAL["price_usd_per_mtok_input"] / 1e6
            print("本次会话：%d 次调用 · %s 输入 token · 约 $%.6f"
                  % (stats.get("requests", 0), stats.get("input_tokens", 0), total))
    return 0
