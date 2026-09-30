# Jev 能力摸底实验台

针对 **Jev（TypeSafe System One）** 的通用能力探测工具。零第三方依赖，一条命令跑完，
输出一份带实测数据和判读结论的 Markdown + JSON 报告。

> Jev 不是一个会写文章的模型。它接收一段 `state` 和若干**带类型的问题**，
> 返回代码可以直接比较的数字与选项 —— 是「判断层」的替代品，不是「生成层」的替代品。

---

## 图形界面（Jev Playground）

不想写代码、想直接手工试参数的话，用这个：

```bash
python3 run.py --ui                # 打开界面并自动开浏览器
python3 run.py --ui --no-browser   # 只起服务，自己访问 http://127.0.0.1:8765/
python3 run.py --ui --ui-port 9000 # 换端口
python3 run.py --ui --mock         # 还没填 Key 时预览界面（数据伪造）
```

界面里能做的事：

| 区域 | 说明 |
| --- | --- |
| **模型** | 枚举 → **多选框**。勾选多个会并排跑同一个请求，并给出逐题对比表（标黄表示各模型答案不一致） |
| **State** | 形态单选（字符串 / JSON 对象 / JSON 数组）+ 编辑器，带 JSON 实时校验 |
| **问题类型** | 枚举 → **多选框**。勾 `choice`/`score`/`noul` 即生成对应的问题卡片，可复制出同类多张 |
| **预设场景** | 10 个预设一键载入，覆盖官方九类失效场景里最典型的几个，每个都写了「看什么」 |
| **结果区** | 按答案类型分别可视化：`noul` 概率条、`choice` 概率分布、`score` 档位梯；附延迟 / token / 成本 |
| **多模型对比** | 同一请求发给多个模型，逐题列出答案差异 |

两个设计上的安全点：

- 服务端**只绑定 `127.0.0.1`**，不对外暴露。
- **API Key 永远不进浏览器** —— 页面通过 `/api/eval` 由本地服务端代理调用，前端拿不到密钥。

提交按钮旁会实时预估本次调用的成本；右上角状态点显示当前 Key 来源。

---

## 30 秒上手（命令行方式）

```bash
# 1) 先把 Key 填进 .env（本文件已 gitignore，不会误提交）
#    打开 .env，在 TYPESAFE_API_KEY= 后面粘贴你的密钥

# 2) 验证 Key 是否可用（调 /v1/models，不消耗判断额度）
python3 run.py --check-key

# 3) 先离线跑一遍，确认报告管线正常（数据是伪造的）
python3 run.py --mock

# 4) 正式摸底
python3 run.py
```

跑完在 `report/` 下得到两份东西：

| 文件 | 用途 |
| --- | --- |
| `report/latest.md` | 给人看的完整报告（判读摘要 + 逐套件明细 + 官方基线对照） |
| `report/latest.json` | 给机器用（可入库、可做回归对比） |
| `report/jev-probe-<时间戳>.md/.json` | 每次运行的存档，方便前后对比 |

预估成本：约 60~80 次请求、4 万~8 万输入 token，**约 $0.002~$0.004**（不到三分钱）。

---

## 常用命令

```bash
python3 run.py --list              # 列出 9 个探测套件及各自假设
python3 run.py -s s04,s05          # 只跑计数与日期两个套件
python3 run.py -s 4 -s 5 --yes     # 序号简写，并跳过成本确认
python3 run.py --model jev-1.13.0  # 钉死版本号（而不是用会漂移的别名）
python3 run.py --mock --tag demo   # 给报告文件名加标签
```

Key 的读取优先级：环境变量 `TYPESAFE_API_KEY` → `.env` → `config.json` 的 `api_key`。
三处任选一处填即可。领取地址：<https://console.typesafe.ai/keys>

---

## 九个探测套件

设计思路：**先用 S01 确认返回契约，再逐条去撞官方公布的能力边界，最后算账。**
每个套件都写明了「假设」和「官方基线」，报告里会自动列出需要你重点关注的条目。

| 套件 | 主题 | 对应的官方失效场景 | 你要拿到的结论 |
| --- | --- | --- | --- |
| **S01** | 原语形态与返回契约 | — | 三种答案的字段形状、`key` 是否参与推理、多问题扇出的延迟代价 |
| **S02** | 置信度机制与门控可用性 | #7 | `confidence` 能否复算、输入变糊时是否真会下降、阈值该定在哪 |
| **S03** | 字面理解 | #1 | 「写下的问题 ≠ 想问的问题」到底有多严重 |
| **S04** | 计数与数字精度 | #2 | 直接问数字会不会错；「逐项判断 + 代码加总」是否可行 |
| **S05** | 日期时间比较 | #3 | 日期比较的可靠性，以及「抽取交给模型、算术留给代码」是否成立 |
| **S06** | 噪音稀释 | #5 | 掺无关文本后答案漂移多少、成本涨多少 |
| **S07** | 多层间接与结构不变量 | #4、#8 | 第几跳开始掉准确率；正反各问一次是否自洽 |
| **S08** | 中文 / 英文 / 混合模式 | 语言支持 | 中文准确率与置信度相比英文差多少；英文指令能否兜底 |
| **S09** | 性能、并发、版本与成本 | — | 延迟分位、并发吞吐、版本漂移、按你的量算月成本 |

> 官方失效场景编号来自 <https://docs.typesafe.ai/model-jaggedness/jev-1.13>（最后审阅 2026-09-17）。

---

## 报告怎么读：判读词汇表

实验台刻意区分「复现了官方缺陷」和「调用失败」——对能力摸底来说，**复现缺陷是有价值的结论，不是 bug**。

| 标记 | 判读 | 含义 |
| --- | --- | --- |
| ✅ | 符合预期 | 行为与官方文档/预期一致 |
| 🔴 | 缺陷复现 | 撞上了官方公布的失效边界 → 这是你要写进编码规范的约束 |
| 🟢 | 未见缺陷 | 本套件没能复现预期中的缺陷 |
| 📊 | 已测量 | 信息性数据，无对错（延迟、成本、分布等） |
| ⚠️ | 需注意 | 偏离预期，需要你人工判断 |
| ❌ | 调用失败 | 请求本身失败（鉴权/校验/限速/网络） |

**重要**：S04~S08 里有相当比例的 🔴 是正常的。官方自己就把这些列成了已知缺陷。
如果某个套件一条 🔴 都没有，先怀疑样本太简单，而不是模型变强了。

---

## 目录结构

```
JEV test/
├── run.py                       入口脚本
├── .env                         ← 把你的 Key 填在这里
├── .env.example                 模板
├── config.json                  可调参数（阈值、并发档位、噪音规模等）
├── jevprobe/
│   ├── client.py                零依赖 HTTP 客户端（重试/退避/错误码/mock）
│   ├── config.py                配置与 Key 装载
│   ├── report.py                Markdown + JSON 报告生成
│   ├── runner.py                CLI 与执行编排
│   ├── ui.py                    图形界面的本地服务端（仅绑 127.0.0.1）
│   ├── presets.py               界面里的 10 个预设场景
│   ├── webui/                   界面静态文件（index.html / app.js，无框架无构建）
│   └── suites/
│       ├── base.py              度量工具与用例记录
│       ├── s01_primitives.py    … 到 s09_perf.py
└── report/                      运行产物
```

### 加一个自己的套件

写一个模块暴露 `SUITE / TITLE / HYPOTHESIS / OFFICIAL / run(ctx)` 五个符号，
然后在 `jevprobe/suites/__init__.py` 的 `SUITES` 里挂一行即可。
`ctx.ask(...)` 会自动记录请求、响应、延迟与 token，报告里就多了这一节。

```python
from ..client import choice, noul
from .base import Ctx, V_DEFECT, V_INFO, V_OK, check, result

SUITE, TITLE = "S10", "我的业务场景"
HYPOTHESIS = "……"
OFFICIAL = "……"

def run(ctx: Ctx):
    resp = ctx.ask(SUITE, "case_1", state="……", questions={"q": noul("……")})
    checks = []
    if resp:
        checks.append(check("判定项", V_OK, {"noul": resp.noul("q")}, "备注"))
    return result(SUITE, TITLE, HYPOTHESIS, OFFICIAL, checks)
```

**这是这个实验台最有价值的用法**：把 S08 里的 8 条合成样本，
换成你业务里 200~500 条**带真值**的真实样本，它就变成了你的上线前回归集。

---

## 报错对照

| 状态码 | 含义 | 处理 |
| --- | --- | --- |
| 401 | Key 缺失或无效 | `python3 run.py --check-key` 定位；检查 `.env` 有没有留空格 |
| 422 | 请求校验失败 | 响应体会指出具体字段；多半是 `choice` 缺 `criteria` 或 `score` 档位数不在 2~10 |
| 429 | 超出限速 | 客户端已自动指数退避；持续出现就降低 `config.json` 里的并发档位 |
| 529 | 服务过载 | 同上，稍后重试 |

---

## 注意事项

- **`--mock` 模式下所有数字都是伪造的**，只用于验证报告管线，不代表 Jev 的任何真实表现。
  报告顶部会打明显的 MOCK 水印。
- 报告里的百分比受样本量限制（S08 只有 8 条）。**看趋势，别抠小数点**；
  要下生产结论，请把样本扩到几百条。
- 官方限速和别名会动态调整，别把当前数值写死进你的重试逻辑。
  生产环境请把模型版本号钉死（如 `jev-1.13.0`），并记录响应里的 `model` 字段。

## 参考

- 官方文档：<https://docs.typesafe.ai/>
- 快速上手：<https://docs.typesafe.ai/introduction/quickstart>
- HTTP API：<https://docs.typesafe.ai/api>
- 模型与限速：<https://docs.typesafe.ai/models>
- 失效场景清单：<https://docs.typesafe.ai/model-jaggedness/jev-1.13>
- 置信度机制：<https://docs.typesafe.ai/confidence>
- 控制台 Key：<https://console.typesafe.ai/keys>
