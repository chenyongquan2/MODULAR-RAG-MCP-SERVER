# 04 · 选型与取舍

> **前置**：[03 · 约束解码原理](03-principles.md)
> **本章目标**：知道约束解码的代价（它不是免费的）、四种方法为什么会共存、以及怎么给一个具体端点选方案。
> **预计**：20 min

---

## 1. 约束解码的代价

上一章讲完原理，很容易得出「那当然用最强的那个」。**但它不是免费午餐。**

### 1.1 推理空间的损失（影响最大）

约束解码强迫模型**第一个 token 就是 `{`**。模型因此**失去了「先想一想再回答」的空间**。

而 LLM 的推理能力高度依赖于把思考过程写出来——这正是 CoT（Chain-of-Thought）有效的原因。不让它写，它就得凭直觉一步到位给出 `decision`。

**对 judge / 评分类任务，这个损失是实打实的**：判定相关度本来就需要先分析再打分。

### 1.2 解法：把 reasoning 放进 schema，且放在最前

```python
class ScreeningVerdict(BaseModel):
    reason: str                                        # ← 必须在最前
    decision: Literal["keep", "drop", "borderline"]    # ← 写它时 reason 已在上下文里
    confidence: float
```

回忆 §00 §2 推论 A（自回归、严格从左到右）：

| 顺序 | 效果 |
|---|---|
| `reason` 在**前** | 模型在 JSON 内部完成了一次 CoT，`decision` 基于分析得出 |
| `reason` 在**后** | `decision` 已经拍板，`reason` 只是**事后编的理由**（post-hoc rationalization） |

**字段完全一样，判断质量可能差很多。这不是风格问题，是能力问题。**

### 1.3 ⚠️ 但这个技巧不保证被遵守【实测】

本项目探针里 schema 声明的顺序是 `reason` → `decision` → `confidence`，实际返回：

| 模型 | 实际字段顺序 | 遵守声明顺序？ |
|---|---|---|
| `z-ai/glm-5.2` | `reason` 在前 | ✅ |
| `minimax/minimax-m2.7` | **`confidence` → `decision` → `reason`** | ❌ 完全颠倒 |

minimax 把 `reason` 甩到最后，**退化成了事后编理由**——而它正是本项目的 judge。

> **结论：这个技巧值得做（零成本），但必须验证它真被遵守。** 验证方法很简单：看实际返回的键序。

### 1.4 其他代价

| 代价 | 说明 |
|---|---|
| **占用 tools 通道** | 用假函数方案时，若场景本身要用真工具，两者会打架（§02 §3.2） |
| **schema 表达力受限** | 严格模式常要求全部字段 `required`、禁 `additionalProperties`、限嵌套深度【文献，以最新文档为准】 |
| **首次调用编译开销** | schema 要编译成状态机 |
| **流式输出变复杂** | 拿到的是不完整 JSON，需要增量解析 |
| **格式熟悉度** | §03 §3.2 第 3 条：把模型逼进陌生格式会伤内容质量 |

---

## 2. 为什么会有四种方法共存

三个原因，都很现实。

### 2.1 历史层积，不是设计出来的【文献】

```
2022       提示词 hack 是唯一选择
2023-06    OpenAI 推出 function calling  ← 为工具调用设计，被挪用来拿 JSON
2023-11    推出 JSON mode               ← 官方承认「原来大家只是想要 JSON」
2024-08    推出 Structured Outputs       ← 用约束解码彻底解决
```

每一代出来时上一代已有海量代码在跑，**不能删**。兼容层只能全都留着。

### 2.2 供给侧是碎片的

| provider 类型 | 可用的路 |
|---|---|
| OpenAI 较新模型 | 四种全有 |
| Anthropic | tool use（≈假函数），传统上是官方推荐路径 |
| 老模型 / 小模型 | 只有提示词 |
| **兼容端点 / 网关** | **未知，必须实测**（§00 §7.2） |

### 2.3 真有取舍

见 §1。不是纯粹的「新的更好」。

**特别地：假函数不会消失。** 有一类场景它是正解而非包袱——**agent loop 里的终止信号**：

```python
tools=[search, run_sql,
       final_answer]      # ← 假函数，但不是包袱
# 不设 tool_choice，让模型自己决定什么时候交卷
```

`json_schema` 在这里用不了——它会强制**每一次**响应都符合 schema，模型就没法调真工具了。

> **假函数作为「拿数据的 workaround」正在退役；作为「agent 表达终止意图的手段」是长期设计。同一个技术，两种命运。**

> **「workaround」= 变通绕道**：用一个**本不为此设计**的机制去达成目的。function calling 的本职是「让模型调用真实工具」，而只想拿 JSON 的人声明一个永远不会真执行的假函数，只为让模型按 schema 把参数填出来——目的达到了，但走的是侧门。侧门的命运取决于正门开没开：`json_schema`（约束解码）就是拿数据的正门，开通后侧门自然退役；而 `final_answer` 表达的确实是「模型要执行一个动作」，它走的本来就是 tools 通道的正门，所以不算 workaround，也就不会退。

---

## 3. LangChain 的 `with_structured_output` 在哪一层

```python
structured_llm = llm.with_structured_output(ScreeningVerdict)
result = structured_llm.invoke("...")
result.decision     # 已校验的枚举值
```

**关键认识：它是一个接口，不是一种实现。** 底层就是 §02 那四条路，靠 `method` 参数选：

| `method` | 对应 |
|---|---|
| `"function_calling"` | §02 §3（多数 provider 的默认） |
| `"json_mode"` | §02 §2 |
| `"json_schema"` | §02 §4 |
| （不支持时回落到 OutputParser） | §02 §1 |

**它的价值是抹平 provider 差异**，代价是抽象层厚、版本耦合紧。

一个实用参数【文献】：

```python
llm.with_structured_output(ScreeningVerdict, include_raw=True)
# 返回 {"raw": ..., "parsed": 对象或 None, "parsing_error": 异常或 None}
# 解析失败时不抛异常 —— 生产环境做降级时用这个
```

> **要不要为它引入整个 LangChain？** 对 provider 无关的项目（比如本项目），更贴合的做法是在自家 `BaseLLM` 上加一个 `generate_structured(schema)` 抽象方法，各 provider 实现里各走各的原生通道。

---

## 4. 决策树

```
你的端点支持 json_schema 严格模式？
  ├─ 是 → 用它。记得 reason 字段放最前面（§1.2），并验证它被遵守（§1.3）
  └─ 否 → 支持 function calling / tool use？
           ├─ 是 → 用假函数
           └─ 否 → 支持 json_mode？
                    ├─ 是 → json_mode + 提示词写 schema + pydantic 事后校验
                    └─ 否 → 提示词 + 容错解析
                            ├─ 优先 XML 标签而非 JSON（§03 §4）
                            └─ 必须准备「解析失败」的降级路径
```

> ⚠️ **这棵树给的是理论优先级，不是你端点上的实际优先级。**
>
> 【实测】本项目网关上 `tools` 反而比 `json_schema` 更可靠（3/3 vs 2/3），还快 5 倍省 87%（§05 章）。
>
> **树只用来决定「先测哪个」，不能决定「用哪个」。顺序由实测定。**

---

## 5. 生产纪律（与通道无关）

选对通道只是一半。下面八条**不管你用哪种方法都要做**，而且这一半更常被跳过。

| # | 纪律 | 为什么 |
|---|---|---|
| 1 | **永远做 pydantic 二次校验** | ② 层保证不一定有，③ 层从来没有 |
| 2 | **单条失败不炸整批** | 用 `include_raw=True` 或等价机制，记录 + 降级 |
| 3 | **失败必须可归因** | 记 `finish_reason` / `usage`，分开「截断 / 格式非法 / 语义判不出」 |
| 4 | **`max_tokens` 按推理段估** | 推理段占 85–90%，安全值 = 预期输出 × 5–10（§00 §4） |
| 5 | **检查 `tool_calls` 是否为空** | `tool_choice` 是请求不是保证，会被静默吃掉 |
| 6 | **能力探测纳入回归** | 实测到**间歇性**静默失效，测一次通过会漏 |
| 7 | **`reason` 放最前，且验证真被遵守** | §1.3 |
| 8 | **拿不准时降级，不要猜** | 猜出来的值会静默污染下游 |

**第 3 条最容易跳过、代价最大**——不做它，后面所有优化都无法判断有没有效（§01 §3.3）。

---

## 6. 本章小结

| 问题 | 答案 |
|---|---|
| 约束解码最大的代价 | **剥夺了模型「先想再答」的空间** |
| 怎么补救 | reason 字段放进 schema 且放最前 —— **但要验证被遵守** |
| 为什么四种方法共存 | 历史层积 + provider 碎片 + 真有取舍 |
| 假函数会消失吗 | 作为拿数据的 workaround 会；作为 agent 终止信号不会 |
| 决策树能直接用吗 | **不能。它只决定「先测哪个」** |
| 比选通道更重要的是 | 那八条生产纪律，尤其第 3 条 |

---

## 深入阅读

| 想深入 | 去哪 |
|---|---|
| 取舍的完整论证 | 深文 [§6](../structured-output-explained.md) |
| LangChain 各 provider 的 `method` 默认值 | LangChain `with_structured_output` API 文档 |
| 生产纪律的逐条展开 | 深文 [§10.1](../structured-output-explained.md) |

**下一章** → [05 · 本项目现状](05-this-project.md)
