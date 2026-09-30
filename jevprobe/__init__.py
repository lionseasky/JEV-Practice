"""Jev (TypeSafe System One) 能力摸底实验台。

零第三方依赖，纯 Python 标准库实现，兼容 Python 3.9+。

快速开始：
    python3 run.py --list          # 看有哪些探测套件
    python3 run.py --mock          # 离线跑通全流程，验证报告管线
    python3 run.py                 # 填好 Key 后真实探测
"""

__version__ = "1.0.0"

# Jev 官方公布的关键常量（来源：docs.typesafe.ai，2026-09 核准）
OFFICIAL = {
    "endpoint": "https://api.typesafe.ai/v1/systemone",
    "models_endpoint": "https://api.typesafe.ai/v1/models",
    "model_id": "jev-1.13.0",
    "aliases": {"jev-latest": "jev-1.13.0", "jev-preview": "jev-1.13.0"},
    # 计费：只按输入 token 计费，输出免费
    "price_usd_per_mtok_input": 0.042,
    "price_usd_per_btok_input": 42.0,
    # 限速（官方声明会动态调整，不要写死进重试逻辑）
    "rate_limit_tokens_per_second": 250_000,
    "rate_limit_requests_per_minute": 1_200,
    # 上下文
    "context_tokens_total": 64_000,
    "context_tokens_state_plus_longest_question": 32_000,
    # 原语约束
    "choice_max_options": 255,
    "score_min_levels": 2,
    "score_max_levels": 10,
    # 失效场景编号（docs.typesafe.ai/model-jaggedness/jev-1.13）
    "failure_modes": {
        1: "字面理解（回答你写的问题，不是你想问的问题）",
        2: "数学与数字（不会算、不会数）",
        3: "日期时间比较（把日期当文本读）",
        4: "多层间接（需要多跳推理）",
        5: "大而杂的 state 稀释准确率",
        6: "对抗性内容",
        7: "instructions 与 criteria 互相矛盾",
        8: "常识性结构不变量（同一件事问两遍答案不一致）",
        9: "生成（它根本不生成文本）",
    },
}
