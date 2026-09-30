"""配置与 API Key 装载。

Key 的优先级（从高到低）：
    1. 环境变量 TYPESAFE_API_KEY
    2. 本目录下 .env 文件里的 TYPESAFE_API_KEY
    3. config.json 里的 api_key 字段

你只需要挑一个地方填。推荐填 .env（已在 .gitignore 里）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
CONFIG_PATH = os.path.join(ROOT, "config.json")

PLACEHOLDER_MARKERS = (
    "",
    "在这里填入",
    "YOUR_API_KEY",
    "your_api_key",
    "sk-xxx",
    "REPLACE_ME",
    "<your-key>",
)

DEFAULTS: Dict[str, Any] = {
    "base_url": "https://api.typesafe.ai",
    "model": "jev-latest",
    "timeout_seconds": 60,
    "max_retries": 4,
    "concurrency": 8,
    "output_dir": "report",
    # 置信度门控阈值（官方建议：先保守，再按你自己的数据调）
    "confidence_act": 0.90,
    "confidence_confirm": 0.60,
    # noul 判定为“成立”的阈值
    "noul_threshold": 0.50,
    # 噪音套件里注入的无关文本规模（按重复次数）
    "noise_repeat_mid": 60,
    "noise_repeat_large": 260,
    # 性能套件并发档位
    "concurrency_levels": [1, 4, 16],
    "perf_repeats": 3,
}


def _load_env_file(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                out[key] = value
    return out


def _looks_like_placeholder(value: Optional[str]) -> bool:
    if value is None:
        return True
    v = value.strip()
    if v in PLACEHOLDER_MARKERS:
        return True
    lowered = v.lower()
    return any(m.lower() in lowered for m in ("填入", "your_api_key", "replace_me", "sk-xxx"))


class Config:
    def __init__(self, data: Dict[str, Any], api_key: Optional[str], key_source: str):
        self.data = data
        self.api_key = api_key
        self.key_source = key_source

    def __getattr__(self, item: str) -> Any:
        try:
            return self.data[item]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(item) from exc

    @property
    def has_key(self) -> bool:
        return bool(self.api_key) and not _looks_like_placeholder(self.api_key)

    def output_path(self, filename: str) -> str:
        out_dir = self.data.get("output_dir", "report")
        if not os.path.isabs(out_dir):
            out_dir = os.path.join(ROOT, out_dir)
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, filename)


def load_config(cli_overrides: Optional[Dict[str, Any]] = None) -> Config:
    data = dict(DEFAULTS)

    # config.json（可选，用于覆盖 tunable）
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_data = json.load(f)
            if isinstance(file_data, dict):
                data.update({k: v for k, v in file_data.items() if k != "api_key"})
        except (ValueError, OSError) as exc:
            raise SystemExit("config.json 解析失败：%s" % exc)

    # API Key 三级查找
    api_key: Optional[str] = None
    key_source = "未找到"

    env_file = _load_env_file(ENV_PATH)
    json_key = None
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                json_key = (json.load(f) or {}).get("api_key")
        except (ValueError, OSError):
            json_key = None

    candidates = [
        ("环境变量 TYPESAFE_API_KEY", os.environ.get("TYPESAFE_API_KEY")),
        (".env 文件", env_file.get("TYPESAFE_API_KEY")),
        ("config.json", json_key),
    ]
    for source, value in candidates:
        if value and not _looks_like_placeholder(value):
            api_key, key_source = value.strip(), source
            break
    else:
        # 全都缺失或是占位符，记录一下第一个非空的来源便于报错提示
        for source, value in candidates:
            if value:
                api_key, key_source = value.strip(), source + "（疑似占位符）"
                break

    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                data[k] = v

    return Config(data, api_key, key_source)
