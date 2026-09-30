#!/usr/bin/env python3
"""Jev 能力摸底实验台 —— 入口脚本。

用法：
    python3 run.py --ui            打开图形界面（Playground，推荐）
    python3 run.py --ui --mock     无 Key 时预览界面
    python3 run.py --list          看套件清单
    python3 run.py --check-key     验证 Key
    python3 run.py --mock          离线自检（数据伪造）
    python3 run.py                 真实运行全部套件

零第三方依赖，Python 3.9+ 即可（推荐 3.11+）。
需要更高版本或其他依赖时也可以：
    uv run --python 3.12 python run.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jevprobe.runner import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
