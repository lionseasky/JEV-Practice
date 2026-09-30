"""实验台入口：CLI 解析、执行编排、报告落盘。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

from . import OFFICIAL, __version__
from .client import AuthError, JevError, build_client, parse_model_list
from .config import ROOT, load_config
from .report import build_json, build_markdown
from .suites import SUITES, resolve
from .suites.base import Ctx

BANNER = r"""
   __  _____   __     ___  ____   ___  ____  ____
   | |/ / __ \  \ \   / / |/ /\ \ / / |  _ \| __ )| ____|
   |   <  __/   \ \ / /| ' /  \ V /  | |_) |  _ \|  _|
   |_|\_\___|    \_/   |_|\_\   |_|   |____/|____/|_____|

   Jev / TypeSafe System One 能力摸底实验台 v%s
""" % __version__

ESTIMATE_NOTE = (
    "预估：约 60~80 次请求、4 万~8 万输入 token，"
    "按 $0.042/Mtok 计约 $0.002~$0.004（不到三分钱）。"
)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Jev（TypeSafe System One）能力摸底实验台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 run.py --ui                   打开图形界面（推荐从这里开始）\n"
            "  python3 run.py --ui --mock            无 Key 时预览界面\n"
            "  python3 run.py --list                 列出所有探测套件\n"
            "  python3 run.py --mock                 离线跑通全流程（数据伪造，仅验证管线）\n"
            "  python3 run.py --check-key            只验证 API Key 是否可用\n"
            "  python3 run.py                        跑全部套件（真实调用）\n"
            "  python3 run.py -s s04,s05             只跑计数与日期两个套件\n"
            "  python3 run.py -s 4 -s 5 --yes        用序号简写、跳过确认\n"
        ),
    )
    parser.add_argument("--ui", action="store_true", help="启动本地图形界面（Playground）")
    parser.add_argument("--ui-port", type=int, default=8765, help="界面端口，默认 8765")
    parser.add_argument("--no-browser", action="store_true", help="启动界面时不自动打开浏览器")
    parser.add_argument("-s", "--suite", action="append", default=[],
                        help="要运行的套件，可重复或用逗号分隔；默认全部")
    parser.add_argument("--list", action="store_true", help="列出套件后退出")
    parser.add_argument("--mock", action="store_true", help="离线自检模式（数据伪造）")
    parser.add_argument("--check-key", action="store_true", help="只调用 /v1/models 验证 Key")
    parser.add_argument("-y", "--yes", action="store_true", help="跳过成本确认")
    parser.add_argument("--model", default=None, help="覆盖模型别名，如 jev-1.13.0（建议生产环境钉版本）")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印重试等细节")
    parser.add_argument("--tag", default="", help="给报告文件名加一个后缀标签")
    return parser.parse_args(argv)


def print_suite_list() -> None:
    print("\n可用的探测套件：\n")
    for module in SUITES:
        print("  %-4s %s" % (module.SUITE, module.TITLE))
        print("       假设：%s" % module.HYPOTHESIS)
        print()


def log(message: str = "") -> None:
    print(message, flush=True)


def confirm(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return True
    try:
        answer = input("继续吗？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


def check_key(client) -> int:
    log("正在验证 API Key（GET /v1/models，不消耗判断额度）…")
    try:
        data = client.list_models()
    except JevError as exc:
        log("❌ Key 验证失败：%s" % exc)
        return 2

    models = parse_model_list(data)
    if models:
        log("✅ Key 可用。账号可见的模型：")
        for item in models:
            line = "   - %s" % item["name"]
            if item.get("description"):
                line += "\n       %s" % item["description"]
            if item.get("release_date"):
                line += "\n       发布于 %s" % item["release_date"]
            log(line)
    else:
        log("✅ 请求成功，但模型列表结构无法识别：")
        log(json.dumps(data, ensure_ascii=False, indent=2)[:1200])
    return 0


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.list:
        print(BANNER)
        print_suite_list()
        return 0

    log(BANNER)

    config = load_config({"model": args.model} if args.model else None)

    # ---------------- 图形界面模式：无需 Key 也能打开（只是提交时会被拦）
    if args.ui:
        from . import ui as ui_module

        return ui_module.serve(
            config,
            mock=args.mock,
            port=args.ui_port,
            open_browser=not args.no_browser,
            verbose=args.verbose,
        )

    if not config.has_key and not args.mock:
        log("❌ 没有找到可用的 TYPESAFE_API_KEY（来源：%s）" % config.key_source)
        log("")
        log("请任选一个位置填入你的 Key：")
        log("  1) 编辑本目录下的 .env       →  TYPESAFE_API_KEY=你的密钥   （推荐）")
        log("  2) 编辑本目录下的 config.json →  \"api_key\": \"你的密钥\"")
        log("  3) 导出环境变量               →  export TYPESAFE_API_KEY=你的密钥")
        log("")
        log("Key 领取地址：https://console.typesafe.ai/keys")
        log("若只想验证报告管线是否正常，可运行：python3 run.py --mock")
        return 2

    try:
        client = build_client(config, mock=args.mock, log=log if args.verbose else (lambda m: None))
    except AuthError as exc:
        log("❌ %s" % exc)
        return 2

    if args.check_key:
        return check_key(client)

    selected = resolve(args.suite)
    suite_names = ", ".join(m.SUITE for m in selected)

    log("模式：%s" % ("MOCK 离线自检（数字伪造）" if args.mock else "真实调用"))
    log("模型：%s" % config.model)
    log("接口：%s" % config.base_url)
    log("Key 来源：%s" % config.key_source)
    log("套件：%s" % suite_names)
    log("")
    log(ESTIMATE_NOTE)
    log("")

    if not confirm(args.yes):
        log("已取消。")
        return 0

    ctx = Ctx(client, config, log)
    results: List[Dict[str, Any]] = []
    started = time.time()

    for module in selected:
        log("─" * 68)
        log("▶ %s %s" % (module.SUITE, module.TITLE))
        try:
            res = module.run(ctx)
        except KeyboardInterrupt:
            log("\n已中断。已完成的部分会照常写进报告。")
            break
        except Exception as exc:  # 套件内部异常不应终止整轮摸底
            log("  ❌ 套件异常：%s: %s" % (type(exc).__name__, exc))
            res = {
                "id": module.SUITE,
                "title": module.TITLE,
                "hypothesis": module.HYPOTHESIS,
                "official_baseline": module.OFFICIAL,
                "checks": [{
                    "name": "套件执行异常",
                    "verdict": "调用失败",
                    "value": "%s: %s" % (type(exc).__name__, exc),
                    "note": "这是实验台自身的问题，请把这条报给开发者",
                }],
                "summary": "",
                "extra": {},
            }
        results.append(res)
        bad = [c for c in res["checks"] if c["verdict"] in ("缺陷复现", "需注意", "调用失败")]
        log("  ✓ 完成：%d 条判读，其中需关注 %d 条" % (len(res["checks"]), len(bad)))

    elapsed = round(time.time() - started, 1)

    # ---------------- 汇总并落盘
    stats = client.stats
    observed: List[str] = []
    for case in ctx.cases:
        if case.get("response_model") and case["response_model"] not in observed:
            observed.append(case["response_model"])

    cost_usd = stats.get("input_tokens", 0) * OFFICIAL["price_usd_per_mtok_input"] / 1e6
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mock": bool(args.mock),
        "probe_version": __version__,
        "model_alias": config.model,
        "observed_models": observed,
        "base_url": config.base_url,
        "key_source": config.key_source,
        "python": "%s (%s)" % (sys.version.split()[0], sys.executable),
        "platform": platform.platform(),
        "elapsed_seconds": elapsed,
        "stats": stats,
        "cost_usd": round(cost_usd, 8),
        "suite_order": [r["id"] for r in results],
        "config": {k: v for k, v in config.data.items()},
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = ("-" + args.tag) if args.tag else ""
    mock_tag = "-MOCK" if args.mock else ""
    base_name = "jev-probe-%s%s%s" % (timestamp, tag, mock_tag)

    md_path = config.output_path(base_name + ".md")
    json_path = config.output_path(base_name + ".json")
    latest_md = config.output_path("latest.md")
    latest_json = config.output_path("latest.json")

    markdown = build_markdown(meta, results, ctx.cases)
    payload = build_json(meta, results, ctx.cases)

    for path, content in ((md_path, markdown), (latest_md, markdown)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    for path in (json_path, latest_json):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---------------- 收尾输出
    log("")
    log("═" * 68)
    log("完成：%d 个套件，%d 次调用，耗时 %ss" % (len(results), stats.get("requests", 0), elapsed))
    log("输入 token：%s ｜ 输出 token：%s" % (stats.get("input_tokens"), stats.get("output_tokens")))
    log("成本：$%.6f" % cost_usd)
    if observed:
        log("响应模型：%s" % ", ".join(observed))

    counts: Dict[str, int] = {}
    for res in results:
        for c in res["checks"]:
            counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    if counts:
        log("判读：%s" % "，".join("%s %d" % (k, v) for k, v in counts.items()))

    log("")
    log("报告（Markdown）：%s" % md_path)
    log("报告（JSON）    ：%s" % json_path)
    log("最新副本        ：%s" % latest_md)

    if args.mock:
        log("")
        log("⚠️  这是 MOCK 模式，数字全部伪造。填好 Key 后重跑以获取真实测量。")

    return 0
