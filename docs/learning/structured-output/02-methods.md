# 02 · 四种实现方法

> **前置**：[01 · 概念](01-concepts.md)
> **本章目标**：认得出四种写法，理解它们的强制力从「零」到「物理不可能违反」是怎么递进的。
> **预计**：25 min

四种方法，按强制力从弱到强。**注意看每一种「靠什么起作用」**——这一栏才是它们的本质区别。

| # | 方法 | 靠什么起作用 |
|---|---|---|
| 1 | 提示词 + 解析 | **请求**模型配合 |
| 2 | JSON Mode | 服务端保证是合法 JSON |
| 3 | Function Calling（假函数） | 借用被专门训练过的通道 + 强制 |
| 4 | 约束解码 | **物理上不可能违反** |

---

## 1. 提示词 + 解析

### 怎么写

```python
prompt = """判定这条金标用例，只输出 JSON，不要有其他文字：
{"decision": "keep|drop|borderline", "confidence": <0-1的小数>, "reason": "<理由>"}"""
raw = llm.generate(prompt)
data = json.loads(raw)   # 🙏
```

### 本质：纯粹的请求，零强制力

模型完全可以回你：

````text
好的，这是判定结果：

```json
{"decision": "keep", ...}
```

希望对你有帮助！
````

**它没做错任何事。** 你只是「请求」了它，没有任何机制阻止它说人话。承受后果的是你的解析器。

### 典型失效

| 失效 | 原因 | 属于（§01 §3） |
|---|---|---|
| markdown 代码围栏包裹 | 模型觉得这样更好读 | ① |
| 前后夹带解释文字 | 对话本能 | ① |
| 字符串内引号/换行未转义 | **生成内容与转义是两个任务，它经常只顾得上一个** | ① |
| 输出被 `max_tokens` 截断 | JSON 写一半 = 语法非法（§00 §2 推论 B） | ① |
| 字段名用了中文或同义词 | 提示词只是建议 | ② |

### 实测【实测】

本项目三个模型 × 两种提示词 = 6 次调用，**产出纯 JSON 的次数：0**。全部带围栏或夹带文字。

> **它唯一的优点是普适**——任何模型、任何端点都能用。所以它永远是最后的兜底方案，但**不该是默认方案**。

---

## 2. JSON Mode

### 怎么写

```python
resp = client.chat.completions.create(
    model="...", messages=[...],
    response_format={"type": "json_object"},   # ← 就这一行
)
json.loads(resp.choices[0].message.content)    # 这行不会炸了
```

### 它保证什么、不保证什么

**保证**：返回的是合法 JSON（① 层）。

**不保证**：符合你的 schema。它可能给你：

```json
{"结果": "相关", "备注": "这段讲的是配置"}
```

合法 JSON，你要的字段一个都没有。

> **JSON Mode 解决了 ①，完全没碰 ②。** schema 依然只能写在提示词里，模型看不看是它的事。

【实测】本项目 `z-ai/glm-5.2-free` 在 JSON Mode 下返回过一个**顶层是 list** 的结果——连「是个对象」都没保证。

### 一个实践约束【文献】

多数实现要求**提示词里必须出现 "JSON" 字样**，否则 API 直接报错。这是为了防止模型陷入无限空白生成。

---

## 3. Function Calling（假函数）

这一节是本章的重头，也是最容易困惑的地方。

### 3.1 怎么写

```python
resp = client.chat.completions.create(
    model="...", messages=[...],
    tools=[{
        "type": "function",
        "function": {
            "name": "ScreeningVerdict",                         # ← 假函数，永不执行
            "parameters": ScreeningVerdict.model_json_schema(),  # ← schema 走正式通道
        }
    }],
    tool_choice={"type": "function",
                 "function": {"name": "ScreeningVerdict"}},      # ← 强制
)
args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
verdict = ScreeningVerdict(**args)   # §00 §6：字典解包 + pydantic 校验
```

> **关于 `ScreeningVerdict`**：它是本项目真实存在的类（[`testset_screener.py:115`](../../../src/observability/evaluation/testset_screener.py#L115)），本专题示例做了简化。
>
> 但要分清：**发给 API 的那个 `"name": "ScreeningVerdict"` 只是个字符串标签**，跟你本地这个类没有绑定关系，改成 `"abc123"` 照样能跑（见 §3.3 第 3 条）。**类是真的，标签是任意的。**

### 3.2 `tools` 与 `tool_choice`：清单与策略

两个正交的维度，**缺一不可**：

```python
tools=[...]        # 「你有哪些表格可以填」 —— 供给（清单）
tool_choice=...    # 「这次你必须填哪张」   —— 策略
```

**`tools` 只是告知，不构成任何要求。** 只传 `tools` 不传 `tool_choice`，模型完全可以看一眼说「我不用，我直接说」。这对 agent 是**正确行为**，对结构化输出是灾难。

类比：`tools` 是**菜单**，`tool_choice` 是**今天怎么点**。菜单不决定你吃什么。

`tool_choice` 的四档【文献】：

| 取值 | 含义 | 典型场景 |
|---|---|---|
| `"auto"` | 模型自己决定调不调、调哪个（**有 tools 时的默认值**） | **agent loop** |
| `"none"` | 不许调，正常说话 | 临时禁用但不想改 `tools` |
| `"required"` | 必须调一个，哪个由模型选 | 「要么给答案，要么给澄清问题」 |
| `{"type":"function","function":{"name":"X"}}` | 必须调 **X** | **结构化输出** ← 本章用的 |

**为什么不合并成一个字段**：① 主要用途本来就是「模型自己选」（agent），合并了这个核心场景就没了；② `tools` 是静态的（每轮原样重发）、`tool_choice` 是每轮可变的；③ `"none"` 无处安放（传空 `tools` 会让模型**看不到定义**，不是一回事）。

### 3.3 「假函数」到底假在哪

先纠正一个几乎人人都有的误解：

> **模型从来没有执行过任何函数**，即使在真正的工具调用场景里也一样。

你发给 API 的从来不是代码，只是一段**描述**（name + JSON Schema）。模型看不到你的代码，也没有运行时。它做的唯一一件事是生成一段文本，表示「我想调用 X，参数是 Y」。

**真函数和假函数的差别，只在你收到响应之后**：

```
                    真工具调用                          结构化输出
                    ─────────                          ─────────
  你的代码里     def get_weather(city):              class ScreeningVerdict(BaseModel):
                     return requests.get(...)             decision: str
                 ↑ 真实存在、能跑                     ↑ 只是数据定义，不可执行

  发给 API       {"name": "get_weather",             {"name": "ScreeningVerdict",
                  "parameters": {...}}                "parameters": {...}}
                 ↑ ────────── 这两行完全同构 ──────────↑

  模型返回       tool_calls[0].arguments             tool_calls[0].arguments
                 = {"city": "北京"}                   = {"decision": "keep", ...}
                 ↑ ────────── 这两行也完全同构 ────────↑

  你接下来做     result = get_weather("北京")        ScreeningVerdict(**args)
                 ↓ 结果塞回消息，再请求一次           ↓ 结束。就这样。
                 → 第二轮调用模型（agent loop）      没有第二轮
                 ↑ ═══════ 差别只在这里 ═══════↑
```

「假」具体假在：

1. **全项目搜不到 `def ScreeningVerdict(...)`** —— 项目里那个是 `@dataclass class`，**不是函数，不可调用**
2. 传进去的甚至是个 **pydantic class**（§00 §5.3），不是函数
3. **`name` 完全是个标签**，叫什么都行
4. `tool_choice` 强制后模型只有这一条路，**这才是可靠的来源**

> ⚠️ 注意 `ScreeningVerdict` 在代码里出现了**两次，是两个不同的东西**：一次是发给 API 的**字符串标签**，一次是你本地的 **Python 类**。它们只是碰巧同名（LangChain 自动拿类名当 tool name，所以看起来像一个东西）。

### 3.4 「它什么都不干，那要它干嘛」

这是最常见的卡点。**对，它确实什么都不干。它的作用不是「做事」，是「规定答案长什么样」。**

想象你要考 100 个学生同一道题：

- **方式 A（问答题）**：「请判断这条用例该保留还是丢弃，说明理由。」
  学生答：*「我认为应该保留。理由是问题清晰、上下文支持……希望对您有帮助！」*
- **方式 B（答题卡）**：递一张表格必须填：
  `【判定】□keep □drop □borderline  【置信度】___  【理由】___`

三个问题：答题卡本身「干」了什么事吗？**没有，它只是张纸。** 学生的思考变了吗？**没有。** 那意义在哪？**你能用机器批卷了。**

**假函数就是那张答题卡**：`tools` = 递表格，`tool_choice` 强制 = 「必须填表，不许口头作答」。

**同一个模型、同一个问题、同一个判断，只差递没递表格**【实测】：

| | 不用假函数 | 用假函数 |
|---|---|---|
| 返回长什么样 | ` ```json...``` ` 裹着客套话 | `{"confidence":0.95,"decision":"keep",...}` |
| 6 次调用产出**纯 JSON** | **0 次** | **6 次** |
| minimax 耗时 | 14.9 秒 | **3.0 秒** |
| minimax 输出 token | 579 | **76** |

快 5 倍省 87% 的原因：不给表格时模型先写一堆推理散文再挤出 JSON；给了表格它直接填格子（`finish_reason=tool_calls`，几乎不走推理段）。

#### 拿到之后干什么 —— 看本项目的真实代码

上面说「能用机器批卷」还是抽象的。**批卷的代码长这样**【代码】：

```python
# testset_screener.py:593  —— 卡阈值
threshold = (self._screening.keep_threshold
             if decision is ScreeningDecision.KEEP
             else self._screening.drop_threshold)
if confidence < threshold:
    return self._borderline(case_index, ...)      # 未达阈值 → 降级交人工
```

```python
# testset_screener.py:141  —— 批量分流
result.auto_keep_indices    # 高置信保留 —— 无需人工介入
result.auto_drop_indices    # 高置信丢弃 —— 无需人工介入
result.borderline_indices   # 存疑 —— 必须交人工处置
result.borderline_ratio     # 存疑占比，超上限告警
```

**这几行就是结构化输出的全部回报。** Feature-003 的目标（CLAUDE.md）是把逐条 100% 人工确认改成「机器预筛 → 只看存疑」，单语种人工耗时 **30-60 min → ≤ 15 min**——省下的时间全部来自这里。

**现在把结构化输出拿掉。** 模型返回一段人话：

> 我认为这条应该保留，因为问题清晰、上下文也支持，置信度大概八成吧。

`if confidence < threshold` 这行**写不出来**——「大概八成」不是 `float`。`auto_keep_indices` 那个列表推导也写不出来——「应该保留」不是 `ScreeningDecision.KEEP`。

> **模型的判断力在两种情况下完全一样。差别只是：一种能被代码消费，一种不能。**
>
> 所以结构化输出的产品**不是那段 JSON**，是「自动分流 1000 条候选」这件事。JSON 只是中间物。

#### schema 是下游需求的镜像

「为什么一定要这个格式」——因为字段不是拍脑袋定的，**每一个都对应一段下游代码**：

| 下游要做什么 | 所以 schema 里必须有 |
|---|---|
| 三路分流 | `decision` 是**三选一枚举**，不能是自由字符串 |
| 跟 `keep_threshold` 比大小 | `confidence` 必须是**数**，不能是「八成」 |
| 人工处置 borderline 时看依据 | `reason` 是字符串 |

**反过来用**：设计 schema 时先问「拿到之后要写什么代码」，字段就自己浮现了。写不出下游代码的字段，就是多余字段。

#### 在 agent 里同理

结构化输出撑起的永远是「**代码要基于模型的判断做决定**」这件事：

| 用途 | 例子 |
|---|---|
| 分支路由 | 本项目的三路分流 |
| 阈值判断 | `confidence < threshold` |
| 聚合统计 | `borderline_ratio` 超限告警 |
| 落盘审计 | `_review_metadata` 记各路径计数 |
| **循环终止** | agent 里模型调 `final_answer` 表示「我判断够了」（§04 §2.3） |

没有这个需求（输出直接给人看）就不需要结构化输出——这就是 [§01 §1.1](01-concepts.md) 那条边界。

### 3.5 那为什么非得长成「函数」的样子

**因为你只有这一种信封。**

你真正想寄的是那份 JSON Schema，但 API 参数里能装它的槽位只有 `tools`——它当初是为工具调用设计的，所以长成函数的样子。

> **你要送的是信，但邮局只卖一种信封。** 对方拆开只看信、扔掉信封。

### 3.6 外部工具与假函数：同一条通道，方向相反

它们不是并列的两个东西，是**同一个 `tools` 通道的两种用法**：

| | 外部工具 | 假函数 |
|---|---|---|
| 模型缺什么 | 缺**信息/能力**（不知道天气） | **什么都不缺**，它已经知道答案 |
| 缺的是谁的 | 模型的 | **你的**——你缺一个可消费的格式 |
| 数据方向 | 外部 **→** 模型 | 模型 **→** 你的代码 |
| 要不要回到模型 | **必须** | **不用**，参数就是终点 |
| 调用轮数 | ≥ 2 轮 | 1 轮 |

> **外部工具解决「模型不知道」，假函数解决「模型知道，但说出来的形式我没法用」。** 前者是能力问题，后者是格式问题。**互相替代不了。**

---

## 4. 约束解码 / Structured Outputs（严格模式）

### 怎么写

```python
resp = client.chat.completions.create(
    model="...", messages=[...],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "screening_verdict",
            "schema": ScreeningVerdict.model_json_schema(),
            "strict": True,          # ← 关键。不加就退化成普通 json_mode
        },
    },
)
```

这是唯一**从数学上**保证 ① 和 ② 的方案。**原理见下一章**——那是本专题的分水岭。

它也不用假装寄一个函数，走的是独立的 `response_format` 通道（跟 `tools` 不冲突，可同时用）。

**代价不是零**，见 §04 章。

---

## 5. 四种方法对照

| 方法 | ① 语法 | ② 结构 | 依赖 | 普适性 |
|---|---|---|---|---|
| 提示词 + 解析 | ❌ | ❌ | 无 | **任何模型** |
| JSON Mode | ✅ | ❌ | API 支持 | 中 |
| Function Calling | 🔶 极大概率 | 🔶 极大概率 | 模型支持 tools | 中 |
| 约束解码严格模式 | ✅ **数学保证** | ✅ **数学保证** | 模型 + API 都支持 | 低 |

> ⚠️ **这张表是理论排序。** 你端点上的实际排序**必须实测**——本项目实测就把它推翻了（§05 章）。

---

## 6. 本章小结

| 问题 | 答案 |
|---|---|
| 四种方法的本质区别 | **强制力**：请求 → 服务端保证 → 借道 + 强制 → 物理不可能 |
| `tools` 和 `tool_choice` 为什么是两个 | 清单 vs 策略。只给清单，模型有权不用 |
| 假函数为什么叫「假」 | 你的代码里不存在这个函数，它永不执行 |
| 假函数有什么用 | **不是做事，是规定答案的形状**（答题卡） |
| 假函数 vs 外部工具 | 同一通道，数据方向相反 |

---

## 深入阅读

| 想深入 | 去哪 |
|---|---|
| 每种方法的完整失效模式 | 深文 [§3](../structured-output-explained.md) |
| `tool_choice` 被静默忽略的实测案例 | 深文 [§3.3.1](../structured-output-explained.md) |
| agent loop 里 `final_answer` 假函数模式 | 深文 [§3.3.3](../structured-output-explained.md) |

**下一章** → [03 · 约束解码原理](03-principles.md)
