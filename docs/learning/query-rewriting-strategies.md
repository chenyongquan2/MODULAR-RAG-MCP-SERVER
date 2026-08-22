# 查询改写策略对照：同义词扩展 / Multi-Query / HyDE / Step-back

> **专题定位**：本文涉及评估的部分（HyDE 分数虚高）属于 [RAG 评估系统学习](rag-evaluation/README.md) **第 05-06 层的深入阅读** —— 该机制在专题 [05 章 § 2.3](rag-evaluation/05-meta-evaluation.md) 有对称论证（金标结构性**奖励** HyDE，与它惩罚重排同源）。策略对照部分不需要评估背景，可直接读。
> **记录日期**：2026-08-15
> **关联代码**：[`src/core/query_engine/query_processor.py`](../../src/core/query_engine/query_processor.py)、[`src/core/query_engine/fusion.py`](../../src/core/query_engine/fusion.py)、[`src/core/text/tokenizer.py`](../../src/core/text/tokenizer.py)
> **关联规格**：`specs/004-retrieval-infra-fix/spec.md:174`、`specs/005-weighted-fusion/spec.md:160`（两者都把「查询改写」列为后续 feature）
> **起因**：Feature-005 后的诊断结论指向「下一步在关键词路径的质量本身（查询改写）」，但「查询改写」是一族策略而非一个动作，需要先厘清各自帮的是哪条检索路径，再决定做哪个

## 置信度标注约定

沿用 [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) 的约定：

| 标注 | 含义 |
|---|---|
| **【代码】** | 从本仓库源码直接读出，附文件行号 |
| **【实测】** | 在本机实际运行验证过，2026-08-15 |
| **【文献】** | 来自论文/官方文档，高置信但请以最新版为准 |
| **【推断】** | 本文作者的综合判断，**不是共识，引用前请自行核验** |

---

## 目录

1. [现状核查：本项目实现了哪些](#1-现状核查本项目实现了哪些)
2. [先划清边界：改写 ≠ 规划](#2-先划清边界改写--规划)
3. [四种策略逐个拆](#3-四种策略逐个拆)
4. [核心决策表：哪条策略帮哪条路径](#4-核心决策表哪条策略帮哪条路径)
5. [本项目的瓶颈诊断与策略匹配](#5-本项目的瓶颈诊断与策略匹配)
6. [落地设计草案](#6-落地设计草案)
7. [评估约束：金标的两代与它们的偏向](#7-评估约束金标的两代与它们的偏向)
   - 7.0 [前置概念：金标与两代标注方式](#70-前置概念金标与两代标注方式) → 完整解释见 [golden-test-set-explained.md](golden-test-set-explained.md)
8. [推荐落地顺序](#8-推荐落地顺序)
9. [面试口径](#9-面试口径)
10. [附录：待验证事项](#附录待验证事项)

---

## 1. 现状核查：本项目实现了哪些

**【实测】** 全仓 grep `hyde|hypothetical|query_rewrit|query_expan|查询改写|查询扩展`：

| 位置 | 命中数 |
|---|---:|
| `src/` | **0** |
| `scripts/` | **0** |
| `docs/` + `specs/` | 10 |

**结论：一个都没实现。**

**【代码】** [query_processor.py:68-98](../../src/core/query_engine/query_processor.py) 的 `process()` 目前只做两件事：

1. `_extract_keywords()` —— 走共享 tokenizer + 停用词过滤 + 去重截断
2. `_parse_filters()` —— 过滤条件透传

**纯规则，零 LLM 调用。** 输出的 `ProcessedQuery` 只有 `original_query` / `keywords` / `filters` 三个字段。

但这不是遗漏，是**明确排期后推迟的**：

> `specs/004:174` —— "本 feature 的产出是后续「**查询改写**」与「检索规划」两个 feature 的**前提**——在混合检索真正生效前，任何检索改进的消融实验都不可信"
> `specs/005:160` —— "不引入查询改写、子查询分解、检索规划 —— **那些属于后续 feature**"

**前置条件（混合检索生效 + 带权融合）已在 004/005 完成。** 阻塞项转移到了评估侧，见 §7。

---

## 2. 先划清边界：改写 ≠ 规划

[agentic-retrieval-boundary.md](agentic-retrieval-boundary.md) 已经把四个概念的层级理清了。本文**只讨论查询改写（Query Rewriting）**，即：

> **输入一个 query，输出一个或多个「更适合检索」的 query（或向量），然后走一次检索。**

以下**不在本文范围**，它们属于查询规划（Query Planning），见 agentic 那篇：

- 子问题分解（把一个问题拆成多个**语义不同**的子检索）
- 多跳检索（用第一次的结果决定第二次查什么）
- 证据充分性驱动的迭代

**一句话区分**：改写产出的多个 query **问的是同一件事**；规划产出的多个 query **问的是不同的事**。

---

## 3. 四种策略逐个拆

### 3.1 同义词 / 术语扩展（Synonym & Term Expansion）

**做法**：把 query 里的词按一张词表展开成同义词、缩写、别名。

```
"怎么设置止损"  →  keywords: [设置, 止损, SL, stop_loss, stoploss]
```

**特点**：**唯一一个不需要 LLM 的策略**。词表可以是人工维护的，也可以从语料里挖（共现统计、embedding 近邻聚类）。

| 维度 | 评价 |
|---|---|
| LLM 调用 | **0** |
| 延迟 | ~0（查表） |
| Token 成本 | **0** |
| 主要受益路径 | **sparse / BM25** |
| 维护成本 | 词表要人维护，**语料相关** |

**【推断】** 为什么它主要帮 sparse：BM25 是**字面匹配**，query 写 `SL` 而文档写 `止损` 时命中为零。而 dense 的 embedding 本身就对同义词鲁棒——`止损` 和 `stop loss` 的向量本来就近。**所以扩展同义词对 dense 几乎无增益，对 sparse 是刚需。**

> ⚠️ 本项目实施时的硬约束：扩展必须发生在 **`_extract_keywords()` 之后**，且扩展出的词**也要过同一个 tokenizer**。否则又是一次两端切分口径漂移——那类失败是静默的（召回恒为空、不报错），由 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 守着。

---

### 3.2 Multi-Query（多查询改写 / RAG-Fusion）

**做法**：让 LLM 把原 query 改写成 N 个语义等价但措辞不同的版本，每个都跑一次检索，最后融合。

```
"怎么设置止损"
  ↓ LLM 改写 ×3
  ├─ "如何配置止损参数"
  ├─ "stop loss 的设置方法"
  └─ "在哪里修改止损点位"
  ↓ 各自跑 dense + sparse
  ↓ RRF 融合所有结果列表
```

**「RAG-Fusion」这个名字**指的就是 Multi-Query + RRF 这个组合。

| 维度 | 评价 |
|---|---|
| LLM 调用 | **1**（一次生成 N 个改写） |
| 延迟 | +1-2 秒 |
| Token 成本 | 中（输出 N 个短句） |
| 主要受益路径 | **两路都受益，sparse 尤其明显** |
| 实现复杂度 | **本项目最低**，见 §6.2 |

**【推断】** 为什么它对 sparse 增益大：BM25 命中与否取决于**词表面**，多改写几次等于**多几组词面去撞**，命中率显著上升。对 dense 也有增益但边际较小——因为不同措辞的向量本来就聚在一起，取并集收益有限。

> 💡 它和同义词扩展的关系：**Multi-Query 是「用 LLM 现场生成同义词表」**。优点是零维护、随语料自适应；缺点是有延迟和 token 成本。

---

### 3.3 HyDE（Hypothetical Document Embeddings）

**【文献】** 出自 2022 年论文 *Precise Zero-Shot Dense Retrieval without Relevance Labels*。

**先拆名字**：`Hypothetical` = **假设的、虚构的**。这个词修饰的是 `Document`——指这份文档是 LLM **凭空编出来的**，它不来自知识库、也不保证正确。名字里就已经声明了「我知道它是假的」，这不是缺陷描述，是设计意图。

**做法**：**不拿 query 去检索，先让 LLM 编一段「假想答案」，拿这段编出来的假答案的向量去检索。**

```
query → LLM 生成假想答案 → 编码假想答案 → 向量检索 → 真实 chunk
```

**它解决的是「非对称检索」**：query 是短的疑问句，document 是长的陈述句，二者形态差异大，而 embedding 模型对形态相似比对问答匹配更敏感。HyDE 把「疑问句 vs 陈述句」掰成「陈述句 vs 陈述句」。

**最反直觉的一点**：**假想文档不需要正确，可以是幻觉。** 因为 embedding 编码器本身是有损压缩器——它保留主题、领域、术语分布、文体，丢掉具体数值细节。幻觉部分在编码时就被过滤了。

> 记忆锚点：**HyDE 生成的不是答案，是「答案应该长什么样」的一个向量方向。**

| 维度 | 评价 |
|---|---|
| LLM 调用 | **1** |
| 延迟 | +1-3 秒（生成整段文字，比 Multi-Query 长） |
| Token 成本 | 高（输出是一整段） |
| 主要受益路径 | **仅 dense** |
| 对 sparse | **有害** —— 假想文档的词不在语料里，稀释真关键词 |

**常见变体**：生成 N 段取平均向量（抵消单次幻觉偏移）；把原 query 向量加权拼回（防跑偏）。

> ⚠️ 前置条件常被忽略：**假想文档的长度和文体要与真实 chunk 对齐**，否则向量落不到同一邻域。已记在 [agentic-retrieval-boundary.md:546](agentic-retrieval-boundary.md) 的术语表里。

**【推断】 混合检索下的规避方式：分路投喂。** 上表「对 sparse 有害」不等于「HyDE 与混合检索不兼容」——标准做法是**只把假想文档喂给 dense 路，sparse 路仍用原始 query**：

```
              ┌─ 假想文档 → embedding → dense 检索 ─┐
query → LLM ──┤                                      ├─→ RRF 融合
              └─ 原始 query → tokenizer → BM25 ─────┘
```

这样 HyDE 的收益只加在它擅长的那一路，散文里那些语料中不存在的词也就进不了词面匹配。**代价是改写从「query 层的预处理」下沉成了「路径层的差异化输入」**——`ProcessedQuery` 不再是两路共享的单一真源，`query_processing` 阶段要能表达「每路各拿什么」。这与 §6.1 那个 `strategy` 单开关的形态不完全兼容，真做 HyDE 时（§8 第 4 步）需要重新设计这层接口，**不能照搬 synonym / multi_query 的落地路径**。

---

### 3.4 Step-back Prompting（抽象化提问）

**做法**：让 LLM 把具体问题**退一步**问成更一般的问题，两个都检索。

```
"MT5 里 EURUSD 的点差为什么突然变成 30？"
  ↓ step-back
"MT5 的点差是如何计算和浮动的？"
```

**适用于**：具体细节问题，但语料里只有原理性描述时。检索原理段落比检索具体数值更容易命中。

| 维度 | 评价 |
|---|---|
| LLM 调用 | 1 |
| 延迟 | +1-2 秒 |
| 主要受益路径 | 两路，偏 dense |
| 适用面 | **窄**，只对「具体→原理」这一类 query 有效 |

**【推断】** 在本项目优先级最低——适用面窄，且需要判断哪些 query 属于这一类（等于又要一层路由）。

---

## 4. 核心决策表：哪条策略帮哪条路径

**【推断】** 这是本文最该记住的一张表：

| 策略 | dense 增益 | sparse 增益 | LLM 调用 | 延迟 | Token |
|---|:---:|:---:|:---:|:---:|:---:|
| **同义词/术语扩展** | ~无 | **强** | 0 | ~0 | 0 |
| **Multi-Query** | 中 | **强** | 1 | +1-2s | 中 |
| **HyDE** | **强** | **负** | 1 | +1-3s | 高 |
| **Step-back** | 中 | 中 | 1 | +1-2s | 中 |

**两条推论**：

1. **dense 已经对措辞鲁棒**（embedding 天然吸收同义），所以「换个说法」类策略对它边际递减；真正能提升 dense 的是**改变查询的形态**（HyDE 那种把疑问句变陈述句）。
2. **sparse 是字面匹配，对措辞极度敏感**，所以「多给几组词面」类策略对它增益最大；而 HyDE 那种生成散文的做法会**引入语料里不存在的词**，反而添噪。

> 💡 **策略选择的第一问不是「哪个更先进」，而是「我的哪条路径弱」。**

---

## 5. 本项目的瓶颈诊断与策略匹配

### 5.1 瓶颈在 sparse **【代码】**

Feature-005 校准出的生效权重是 `sparse=0.1`，dense=1.0。[fusion.py](../../src/core/query_engine/fusion.py) 开头的注释记录了原因：

> "等权融合在英文金标上 recall 42.4% **低于**纯语义检索的 45.7%…… 根因就是两路一视同仁 —— **关键词路径的噪音命中挤掉了语义路径的正确结果**"

而 Feature-005 后写下的诊断结论是：

> "提升混合检索的下一步**不在融合权重，而在关键词路径的质量本身（查询改写）** 或金标的构造方式" ——[agentic-retrieval-boundary.md:319](agentic-retrieval-boundary.md)

**权重压到 0.1 是止血，不是治疗。** BM25 那一路的信噪比低，才是根因。

### 5.2 匹配结论 **【推断】**

| 策略 | 是否对症 | 判断 |
|---|:---:|---|
| 同义词/术语扩展 | ✅ **高度对症** | 直击 BM25 字面匹配缺陷，零 LLM、零延迟、零成本 |
| Multi-Query | ✅ **对症** | 同样主要提升 sparse，且基础设施复用度最高（§6.2） |
| HyDE | ❌ **不对症** | 只帮 dense（你已调得不错的那一路），且**对 sparse 有害**——正好打在你的弱项上 |
| Step-back | ⚠️ 适用面窄 | 暂不考虑 |

> **反直觉但重要**：HyDE 是这四个里名气最大、最像「高级技术」的一个，**却是对本项目最不对症的一个**。选型看的是路径匹配，不是知名度。

### 5.3 其他约束

**延迟预算已经紧张**【实测】：cross-encoder 重排 40 候选实测 **5.2 秒**（每候选 121-147 ms）。任何 LLM 类改写叠加上去接近 8 秒，且改写在**链路最前端**——它慢，后面全部阻塞。

**成本形态与既有选型不一致**：重排是本地推理、**零 token**；LLM 类改写是**每次查询都烧 token**。项目此前把重排做成默认关闭的 optional extra，体现的是成本谨慎。

**领域风险（仅对 HyDE）**：语料是 MT4/MT5 文档。MetaTrader 是公开产品，LLM 大概率知道「止损」「EA」「点差」等基本概念，但具体配置项名、报表字段名它不知道。属于「部分知道」，**需实测而非先验判断**。

---

## 6. 落地设计草案

### 6.1 配置驱动的形态 **【推断】**

沿用本项目的七条原则（provider 无关、配置驱动、快速失败）：

```yaml
query_rewrite:
  strategy: none          # none（默认）| synonym | multi_query
  # --- synonym ---
  synonym_dict: config/synonyms_zh.yaml
  # --- multi_query ---
  llm:                    # 复用 LLMFactory，不新建 provider 体系
    provider: glm
    model: ...
  num_queries: 3          # multi_query
  timeout_sec: 5
```

**默认 `none`**，与 `rerank.backend: none` 同构——一个默认不启用的能力不该向所有调用方收税。

**快速失败**：`strategy != none` 且必填项缺失时，`load_settings()` 直接抛 `SettingsError`。参照重排那条教训——**刻意不留隐式默认值**（此前重排的兜底是纯英文 `ms-marco`，对中文语料无效且不报错）。

> ### ⚠️ `hyde` 刻意不在这个 enum 里
>
> **【推断】** 上面的 `strategy` 只列了 `synonym` / `multi_query`——**HyDE 不是这个开关的第四个取值**，因为它和另外几个不在同一层：
>
> | | 改写对象 | 两路输入 | 能否套用本节草案 |
> |---|---|:---:|:---:|
> | synonym / multi_query / step-back | **query 本身** | 相同 | ✅ |
> | **HyDE** | **dense 路的输入向量** | **不同** | ❌ |
>
> 前三者改完 `ProcessedQuery` 仍是 dense 与 sparse 的**共享单一真源**；而 HyDE 按 §3.3 的分路投喂实现后，dense 拿假想文档、sparse 拿原始 query，**`ProcessedQuery` 不再能表达完整的检索意图**。
>
> 落地时 `query_processing` 阶段要升到「每路各拿什么」的结构（大致是 `ProcessedQuery` 增加一个 `per_route_input: Mapping[str, str]` 之类的字段，缺省时全路径回落到 `original_query`）。**这是接口变更，不是加一个 enum 值**，改造量与另外两个策略不在一个量级。
>
> 这也回过头解释了 §8 为什么把 HyDE 排在第 4 步而非「反正都是改写、顺手一起做」——它排最后不只因为不对症，**也因为它是四个里唯一需要动检索层接口的**。

### 6.2 Multi-Query 可以零改动复用 fusion ⭐ **【代码】**

这是个值得单独指出的发现。[fusion.py:103-107](../../src/core/query_engine/fusion.py) 的签名是：

```python
def fuse(
    self,
    routes: Mapping[str, Sequence[RetrievalResult]],
    top_k: Optional[int] = None,
) -> List[RetrievalResult]:
```

**`routes` 是「路径名 → 有序结果」的任意映射，不是固定的两路。** Feature-005 特意把入参从位置列表改成命名映射（原因见该文件 docstring：位置列表曾把两路顺序写反且完全不报错）。

这意味着 Multi-Query 的 N 个改写 query × 2 路 = 2N 个结果列表，**可以直接塞进现有的 `fuse()`**：

```python
routes = {
    "dense_q0": ..., "sparse_q0": ...,
    "dense_q1": ..., "sparse_q1": ...,
    "dense_q2": ..., "sparse_q2": ...,
}
```

**Multi-Query 是四个策略里基础设施复用度最高的**——融合层不用动。

> ### ⚠️ 但这里埋着一个静默陷阱
>
> **【代码】** [fusion.py:99-101](../../src/core/query_engine/fusion.py)：
>
> ```python
> def weight_for(self, route: str) -> float:
>     """取某路径的生效权重；未配置的路径返回缺省值。"""
>     return float(self._weights.get(route, DEFAULT_ROUTE_WEIGHT))
> ```
>
> 缺省值是 **1.0**。而配置里校准出的是 `{dense: 1.0, sparse: 0.1}`——**键名是 `sparse`**。
>
> 一旦把路径命名成 `sparse_q0`，`weight_for` 查不到，**返回 1.0 而不是 0.1**。于是 Feature-005 辛苦校准的权重被**悄悄作废**，sparse 回到等权，而系统照常运行、不报错、只是效果变差。
>
> **这正是本项目反复撞见的那一类病**：看起来生效、实际没生效、而且不报错（同 `top_m` 死配置、`--collection` 死参数、`max_tokens=200` 饿死判定）。
>
> **解法**：权重查找按**路径族**而非完整路径名——从 `sparse_q0` 剥出 `sparse` 再查表。这条必须写进 fusion 的契约并配单测，否则一定会被再犯一次。

### 6.3 追踪 **【推断】**

`logs/traces.jsonl` 的 query trace 现有阶段是 `query_processing → dense → sparse → fusion → rerank`。改写应作为 **`query_processing` 阶段内的一个子记录**（记 `strategy`、原 query、改写后的 query 列表、耗时），而不是新开顶层阶段——保持 dashboard 的动态渲染不需要改代码。

---

## 7. 评估约束：金标的两代与它们的偏向

**【推断】** 本节是全文的另一半重点。查询改写做不做得成，卡点不在实现，在**能不能量出来**。

### 7.0 前置概念：金标与两代标注方式

> 📖 **完整解释已独立成篇：[golden-test-set-explained.md](golden-test-set-explained.md)**
> ——「金标」的词源、一条 case 里的两种答案、`dense-top-k` / `pooled-llm-judged` 的逐词拆解、TREC pooling 的来历、三个长得像版本号的东西。**本节只保留读懂 §7.1-§7.3 所需的最小集，不重复。**

**金标（golden test set）** = 评估用的标准答案集。每条 case 里有**两种**「答案」：

| | 是什么 | 喂给哪组指标 |
|---|---|---|
| `ground_truth` | 答案**文本** | RAGAS 四项 |
| **`expected_chunk_ids`** | **期望片段**编号（「答这题该翻到哪几页」） | **custom 四项** |

**下文说「标准答案」时一律指后者。** 人工标注 5 万条 chunk 不现实，只能机器生成——**而「怎么机器生成」的两种答案，就是本项目的两代标注方式**（不是「文件改了第二版」，是换了一整套编答案册的方法）：

| `_labeling_method` | 拿什么去搜 | 候选来自 | 谁决定入选 |
|---|---|---|---|
| **`dense-top-k`**（第一代） | `ground_truth`（**答案**） | 只有 dense 一路 | 排名前 5 |
| **`pooled-llm-judged`**（第二代） | `query`（**问题**） | dense ∪ sparse ∪ rerank | LLM 打 0-3 分 |

**第一代的致命弱点：期望片段本身就是 dense 检索的输出**（检索器锚定）——这正是 §7.1 的全部内容。

> ⚠️ **术语口径**：本文一律用标注方式名，不用「v1/v2」。项目里文件名后缀、`version` 字段、`_labeling_method` 三者会打架，**只有第三个是代码的判据**（`eval_runner.py:88`）。详见独立篇 §8。

### 7.1 `dense-top-k` 金标结构性偏袒 HyDE

**【代码】** [`scripts/backfill_chunk_ids.py`](../../scripts/backfill_chunk_ids.py) 的 `_backfill_one` docstring：

> `Embed ground_truth + query vector store`

也就是说 **`dense-top-k` 金标的 `expected_chunk_ids` = 把「真答案」编码后取 dense top-5**。

对照 HyDE 的机制：**把「假答案」编码后取 dense top-k**。

> 📖 **`oracle`（神谕 / 先知）= 标注时拿得到、真实查询时拿不到的正确信息**——这里指 `ground_truth` 那份真答案。中性词，只是标记「这个数字是在有外挂的前提下拿到的」。词源（图灵的 oracle machine）与完整用法见 [golden-test-set-explained.md § 9 插曲](golden-test-set-explained.md#插曲oracle-是什么意思-文献)。
>
> **一句话对位**：第一代标注是**出题老师**，手里有 oracle 答案；HyDE 是**考生**，没有答案只能编一个去逼近它。两者跑的是同一条通路。

> **这两件事是同一个机制**，区别只是一个用 oracle 答案、一个用 LLM 猜的答案。
> **`dense-top-k` 金标的标准答案，恰好就是「答案向量的 dense 邻居」；而 HyDE 的全部工作就是逼近答案向量。**

**结论：用 `dense-top-k` 金标评 HyDE，分数会虚高**——不是检索真的变好，而是 HyDE 越成功就越接近金标的构造方式本身。

这与重排踩的坑是**同一根因的镜像**：

| 改动 | `dense-top-k` 金标的偏向 | 后果 |
|---|---|---|
| **Cross-encoder 重排** | 结构性**惩罚** | MRR 0.4914 → 0.3668，模型做对了事指标却跌 |
| **HyDE** | 结构性**奖励** | 分数会涨，但涨的可能全是假的 |

> 💡 更普适的一条：**`dense-top-k` 金标不是中立裁判，它是「dense 检索 + oracle 答案」这一特定机制的化身。任何靠近该机制的改动都会被奖励，任何偏离的都会被惩罚。**

### 7.2 `pooled-llm-judged` 金标：英文已就位，中文不足

`pooled-llm-judged` 用 **query** 而非答案池化，不再 dense-anchored，**是评查询改写的正确工具**。

**【实测】** 2026-08-15 清点 `tests/fixtures/`。注意「标注方式」一列才是判据，`version` 只是伴随值：

| 文件 | `version` | **标注方式** | 条数 | `_chunk_labels` | 可用性 |
|---|---|---|---:|:---:|---|
| `golden_test_set_en.json` | v1.0 | `dense-top-k` | 42 | ✗ | dense-anchored |
| `golden_test_set_zh.json` | v0.1-partial | `dense-top-k` | 6 | ✗ | 中断产物 |
| **`golden_test_set_en_v2.json`** | v2.0 | **`pooled-llm-judged`** | **41** | ✓ | ✅ **已就位，> SC-002 的 ≥40** |
| `golden_test_set_zh_v2.json` | v2.0 | `pooled-llm-judged` | 6 | ✓ | ❌ 样本量不足 |
| `golden_test_set_zh_v3.json` | v1.0 | `dense-top-k` | 29 | ✗ | 🚧 在途，尚未二代标注 |

**结论修正：英文侧的查询改写 A/B 今天就能做**（41 条 `pooled-llm-judged` 金标已达标）。**只有中文侧被阻塞。**

> 📖 **A/B = A/B 测试（对照实验）**，不是 RAG 专有名词，就是最普通的受控对比：
> **A（对照组）** 不开查询改写，原样查询走现有管线；**B（实验组）** 开改写后走**同一条**管线。
> 除「有没有改写」这一个变量外，金标、collection、`fusion_weights`、rerank 配置全部保持不变——这样两组指标的差值才能归因到改写本身。

> 末行正是 §7.0 那个实例：文件名带 `_v3`，但 `version` 是 `v1.0`、标注方式仍是 `dense-top-k`——**文件序号与标注代次是两回事**。

`golden_test_set_zh_v3.json` 是在途变更 `openspec/changes/expand-chinese-golden-set/` 的中间产物——29 条，还没跑二代标注（无 `_chunk_labels`）。该变更还发现了一处更严重的静默失效：RAGAS `adapt(language=chinese)` 产出的五个「中文」prompt 文件里**一个中文字符都没有**，且被永久固化进磁盘缓存（2026-04-28），导致后续任何合成都读到英文 prompt。

**所以前置条件应拆成两条**：英文侧无阻塞，可先行；中文侧等 `expand-chinese-golden-set` 完成。

### 7.3 还需要额外的评估口径

**【推断】** 即使 `pooled-llm-judged` 金标就位，评查询改写还缺一样东西：**分路径的指标**。

现有 8 项指标量的都是**融合后**的最终结果。但同义词扩展和 Multi-Query 的作用点在 **sparse 单路**——如果只看融合后指标，sparse 的改善会被 `weight=0.1` 稀释到几乎看不见。

**需要在 A/B（见 §7.2 的 📖 注）时单独量 sparse 路的 recall/MRR**，否则会得出「改写没用」的错误结论——改善真的发生了，只是被融合口径这把尺子量丢了。

---

## 8. 推荐落地顺序

**【推断】**

| 阶段 | 做什么 | 理由 |
|---|---|---|
| **0（前置）** | 补分路径评估口径 | 否则 sparse 的改善被 `weight=0.1` 稀释到看不见。**这是唯一的硬前置** |
| **0.5（并行）** | 完成 `expand-chinese-golden-set` | 只阻塞中文侧；**英文侧用 `golden_test_set_en_v2.json`（41 条 `pooled-llm-judged`）可先行** |
| **1** | **同义词/术语扩展** | 零 LLM、零延迟、零 token、高度对症。**性价比最高，先做这个** |
| **2** | **Multi-Query** | 对症、基础设施复用度最高（fusion 零改动）。注意 §6.2 的权重陷阱 |
| **3** | 重新校准 `fusion_weights` | sparse 质量提升后，`0.1` 这个值必然过时——它是**语料相关且路径质量相关**的 |
| **4** | HyDE（可选） | 只在 dense 侧还有明显提升空间时才做。届时 `pooled-llm-judged` 金标已就位，可公正评判 |
| **—** | Step-back / 策略路由 | 适用面窄 + 需额外一层分类，暂不排期 |

> **第 3 步容易被漏掉**：改写提升了 sparse 的信噪比之后，压到 0.1 的权重就成了新的瓶颈。**改写与权重必须联合校准**，`python scripts/calibrate_fusion_weights.py --sweep` 要重跑。

---

## 9. 面试口径

**【推断】** 被问「你做了查询改写吗 / 为什么不做 HyDE」时：

> "**没做，但不是没想过——是判断它不对症。**
>
> 我的诊断是瓶颈在 sparse 那一路：Feature-005 校准出的 BM25 权重只有 0.1，等权融合时它的噪音命中会把 dense 的正确结果挤掉，recall 反而低于纯 dense。**权重压到 0.1 是止血，不是治疗。**
>
> 而 HyDE 帮的是 dense——我已经调得不错的那一路——**而且它生成的散文喂给 BM25 是有害的，正好打在我的弱项上**。它是这几个策略里名气最大的，但**选型看的是路径匹配，不是知名度**。
>
> 真要做，我的顺序是先做同义词扩展（零 LLM、零延迟、零 token，直击 BM25 的字面匹配缺陷），再做 Multi-Query。
>
> 不过现在真正的阻塞不在实现，在**评估**：我的第一代金标（`dense-top-k`）是拿真答案做 dense 检索回填的，而 HyDE 就是拿假答案做 dense 检索——**两者是同一个机制，用它评 HyDE 分数会结构性虚高**。这和我之前在重排上踩的坑是同一根因的镜像：那次它结构性惩罚重排，这次会结构性奖励 HyDE。所以我先去扩中文的第二代金标了。"

**这段的杀伤力在最后一句**——它展示的不是「会不会用某个技术」，而是**知道自己的指标什么时候在撒谎**。

---

## 附录：待验证事项

| 事项 | 状态 | 验证方式 |
|---|---|---|
| 同义词扩展对 sparse 的实际增益 | 未做 | 需分路径指标（§7.3） |
| LLM 对 MT4/MT5 专有术语的覆盖度 | **【推断】** | 抽 20 条真实 query 让 LLM 生成假想答案，人工看术语是否对得上语料 |
| §6.2 的权重陷阱是否真会触发 | **【推断】**，基于 `weight_for` 的缺省值逻辑 | 实现时写一条单测直接验证 |
| 改写后 `fusion_weights` 的新最优值 | 未知 | `calibrate_fusion_weights.py --sweep` 重跑 |
| HyDE 假想文档的最佳长度/文体 | **【文献】** 只给了原则 | 需按本项目 chunk 中位长度（428 字符）调 prompt |
| **HyDE 分路投喂的接口改造范围** | **【推断】**，见 §6.1 的 ⚠️ 块 | 排到 §8 第 4 步时先做一次接口调研：`ProcessedQuery` 加 `per_route_input` 会波及哪些调用方、trace 的 `query_processing` 阶段字段要不要跟着改 |
| HyDE 分路投喂后 sparse 是否真无污染 | **【推断】**，基于「sparse 拿原 query 即回到 baseline」 | 分路径指标（§7.3）下对比 sparse 单路 recall，应与不开改写时**完全一致**；不一致说明串了 |

---

## 相关文档

- [agentic-retrieval-boundary.md](agentic-retrieval-boundary.md) —— 改写 / 规划 / ReAct 的层级划分与归属红线
- [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) —— 重排能力与 `dense-top-k` 金标评估局限的完整记录
- [tech-selection-llamaindex.md](tech-selection-llamaindex.md) —— LlamaIndex 提供的现成实现与选型判断
- `openspec/changes/expand-chinese-golden-set/` —— 本 feature 的前置变更
- `openspec/config.yaml` § 已知陷阱 —— 项目硬约束的权威来源
