# 附录：Jev（TypeSafe System One）请求参数速查

> 来源：官方 API 参考 <https://docs.typesafe.ai/api>、原语页 <https://docs.typesafe.ai/primitives>、
> State 页 <https://docs.typesafe.ai/concepts/state>（核准日期见文末）
>
> 端点：`POST https://api.typesafe.ai/v1/systemone`

---

## 一、请求头

```
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

---

## 二、顶层字段：只有三个，全部必填

```json
{
  "state": "要评估的内容",
  "model": "jev-latest",
  "questions": { "你起的名字": { "type": "...", "instructions": "...", "criteria": ... } }
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `state` | string \| object \| array | ✅ | 被评估的材料。**一次请求只能有一个 state**，所有问题都看同一份 |
| `model` | string | ✅ | `jev-latest` / `jev-preview` / `jev-1.13.0`（生产环境建议钉版本号） |
| `questions` | map<string, Question> | ✅ | 问题映射。**键名由你决定，不发送给模型、不参与推理**，答案按同名键返回 |

### `state` 的三种形态

| 形态 | 适合 | 例子 |
| --- | --- | --- |
| 字符串 | 一条消息、一段文章 | `"My card was charged twice."` |
| 对象 | **推荐**。多个命名字段/关联记录/应用状态 | `{"message": "...", "order_id": "A-104"}` |
| 数组 | 一串消息或记录 | `["Hi", "My customer number is TS1337.", "I was charged twice."]` |

> 官方建议：**大多数请求用对象**，让 state 的每一部分都有描述性的名字、关系清晰。
> 把 state 想成"你在请一组专家做判断前，会摆到他们面前的资料"。
>
> ⚠️ **仅文本**。图像、音频、视频不支持（需要时自己先转成文本或结构化字段）。

---

## 三、`questions` 里每个问题对象的字段

三个字段，其中 `criteria` 的形状**取决于 `type`**：

| 字段 | choice | score | noul |
| --- | --- | --- | --- |
| `type` | `"choice"` | `"score"` | `"noul"` |
| `instructions` | 问题本身 | 要评分的问题 | 是/否问题或待判断陈述 |
| `criteria` | **必填**：`{选项名: 说明}` 映射 | **必填**：有序数组 | **可选**：`{"true": ..., "false": ...}` |

### 逐类型详解

#### 1. `choice` —— 从固定选项里选一个

```json
{
  "type": "choice",
  "instructions": "Which team should handle this?",
  "criteria": {
    "returns": "Exchanges, wrong or damaged items",
    "shipping": "Delivery status, delays, lost packages",
    "billing": "Charges, invoices, payment problems"
  }
}
```

- `criteria` 是**映射**：键是选项名（会原样出现在答案的 `choice` 和 `probabilities` 里），值是给模型看的说明。
- **选项名和说明都会被发送给模型**，所以说明要写成能互相区分的样子。
- 上限 **255 个选项**。答案里 `choice` 只会是你给的某个键。
- 建议在选项可能覆盖不全时，加一个 `"other"` / `"none of the above"` 兜底项。

#### 2. `score` —— 沿有序档位打分

```json
{
  "type": "score",
  "instructions": "How severe is the reported issue?",
  "criteria": [
    "Cosmetic; no impact to functionality",
    "Broken or degraded feature, but workaround exists",
    "Blocking issue; no workaround exists"
  ]
}
```

- `criteria` 是**数组**，从低到高排列。**顺序即编号**：第 0、1、2 档。
- **至少 2 档，最多 10 档。**
- 返回的 `score` 是沿档位的一个位置，**可以落在两档之间**（比如 1.4）。
  ⚠️ 官方明确说档位在数值标定上很弱，**不要用它在两档之间插值反推精确数值**，只用来判断是否越过某个阈值。

#### 3. `noul` —— 是/否判断

```json
{
  "type": "noul",
  "instructions": "Is the customer asking for a human agent?",
  "criteria": {
    "true": "Mentions a prior attempt, ticket, or that they have asked before",
    "false": "No sign of any previous contact"
  }
}
```

- 返回 `noul`：**答案为"是"的概率**，0 = 否，1 = 是。
- `criteria` 是**可选的**，只包含 `true` / `false` 两个键，用来把"什么算 yes、什么算 no"写清楚。
  只有 `instructions` 也能用，但当判断标准有歧义时加上它更稳。
- ⚠️ `noul` 的 0.5 表示**是与否等概率**，不表示"中等程度"。要程度就用 `score`。

### `instructions` 的三种形态

三者都可以是 **字符串 / 对象 / 数组**。先用字符串；需要把数据拼进问题时用对象。

```json
{
  "q0": {
    "type": "noul",
    "instructions": {
      "question": "Is `items[0]` the name of a fruit?",
      "context": "Only botanical fruits count."
    }
  }
}
```

配合 `state` 是数组/对象时，可以在 `instructions` 里**用反引号引用 state 的字段**，
例如 `account.plan_code`、`items[3]`、`ticket.messages`。这是官方推荐的"批量提问"写法。

---

## 四、响应里的字段

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "department":  { "type": "choice", "choice": "billing", "confidence": 0.78,
                     "probabilities": { "billing": 0.85, "technical": 0.15 } },
    "frustration": { "type": "score", "score": 1.0, "confidence": 1.0,
                     "legend": { "0": "Calm", "1": "Frustrated" },
                     "probabilities": { "0": 0.0, "1": 1.0 } },
    "is_urgent":   { "type": "noul", "noul": 1.0 }
  },
  "usage": { "input_tokens": 392, "output_tokens": 65 }
}
```

| 类型 | 独有字段 | 有 `confidence` 吗 |
| --- | --- | --- |
| `choice` | `choice`、`probabilities` | ✅ |
| `score` | `score`、`legend`、`probabilities` | ✅ |
| `noul` | `noul` | ❌ **没有** |

- `confidence`（0~1）由概率分布推导。choice 的算法：`(n * p - 1) / (n - 1)`（n=选项数，p=最高概率）。
- `legend` 告诉你 `score` 的每一档对应什么（以字符串数字为键）。
- `model` 报告**实际应答的版本 ID** —— 建议记日志，这是发现别名漂移的唯一手段。

---

## 五、没有的参数（从别的 API 迁移过来最容易误会的地方）

| 你可能会找 | Jev 有吗 | 说明 |
| --- | --- | --- |
| `temperature` / `top_p` / `seed` | ❌ | 没有采样参数 |
| `max_tokens` | ❌ | 输出不是文本，无需控制长度 |
| `system` / `messages` 角色 | ❌ | 只有单个 `state` + `questions`，没有对话结构 |
| 流式输出（`stream`） | ❌ | 返回结构化 JSON |
| 批量的 `items` 字段 | ⚠️ | **官方 HTTP API 只列出 `state`/`model`/`questions`**。社区 MCP 项目提到过 `items`，与官方文档不一致 —— 批量场景请以官方 API 参考为准并实测确认 |
| 微调 / LoRA | ❌ | 所有账号共享同一份权重 |
| 图像 / 音频 / 视频输入 | ❌ | 仅文本 |

---

## 六、硬约束速查

| 约束 | 值 |
| --- | --- |
| 单请求上下文 | 64,000 token（`state` + 所有 `questions` 之和） |
| `state` + 最长单个问题 | 32,000 token |
| `choice` 选项数 | ≤ 255 |
| `score` 档位数 | 2 ~ 10 |
| 输入形态 | 仅文本：字符串 / JSON 对象 / 文本数组 |
| 计费 | 仅输入 token，$42/Btok（约 $0.042/Mtok），**输出免费** |
| 限速 | 250,000 token/秒 与 1,200 请求/分钟（官方声明会动态调整） |
| 超限错误码 | 429（限速）、529（过载）、401（鉴权）、422（校验） |

---

## 七、对应到本实验台的代码

`jevprobe/client.py` 里有三个构造器，把上面的 JSON 形状包成了 Python 函数：

| 官方字段 | 实验台里的写法 |
| --- | --- |
| `{"type":"noul","instructions":...,"criteria":{"true":...,"false":...}}` | `noul(instructions, criteria=None)` |
| `{"type":"choice","instructions":...,"criteria":{...}}` | `choice(instructions, criteria={...})` |
| `{"type":"score","instructions":...,"criteria":[...]}` | `score(instructions, criteria=[...])` |

调用方式：

```python
from jevprobe.client import choice, noul, score

resp = client.system_one(
    state={"ticket": {"subject": "Duplicate charge", "body": "..."}, "order_id": "A-104"},
    questions={
        "department": choice("Which team should handle this?", {"billing": "...", "technical": "..."}),
        "frustration": score("How frustrated?", ["Calm", "Annoyed", "Angry"]),
        "is_urgent": noul("Does the customer demand action within a deadline?"),
    },
)

resp.choice("department")        # -> "billing"
resp.confidence("department")    # -> 0.78
resp.score("frustration")        # -> 1.0
resp.noul("is_urgent")           # -> 0.95
resp.model                       # -> "jev-1.13.0"   ← 记进日志
```

---

## 参考

- API 参考：<https://docs.typesafe.ai/api>
- 原语总览：<https://docs.typesafe.ai/primitives>
- Choice：<https://docs.typesafe.ai/primitives/choice>
- Score：<https://docs.typesafe.ai/primitives/score>
- Noul：<https://docs.typesafe.ai/primitives/noul>
- State：<https://docs.typesafe.ai/concepts/state>
- 结构化 instructions：<https://docs.typesafe.ai/primitives/advanced>
- 模型与限速：<https://docs.typesafe.ai/models>
- 失效场景清单：<https://docs.typesafe.ai/model-jaggedness/jev-1.13>
