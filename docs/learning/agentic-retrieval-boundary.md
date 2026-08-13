# Agentic Retrieval 的能力边界：改写、规划、迭代该放在哪一侧

> **记录日期**：2026-08-08
> **关联代码**：`src/core/query_engine/`、`src/core/trace/`、`src/mcp_server/`
> **关联外部项目**：`C:\workspace\smart-appointment-ai-agent`（本项目的第二个调用方）
> **起因**：评估简历两条待写内容（Query Rewrite 策略路由、ReAct Agentic RAG）是否与本项目现状相符，进而厘清「这些能力该由 RAG 服务提供方做，还是由调用方做」

## 置信度标注约定

沿用 [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) 的约定：

| 标注 | 含义 |
|---|---|
| **【代码】** | 从两个仓库源码直接读出，附文件行号 |
| **【实测】** | 在本机实际运行命令验证过，2026-08-08 |
| **【文献】** | 来自官方文档/论文，高置信但请以最新版为准 |
| **【推断】** | 本文作者的综合判断，**不是共识，引用前请自行核验** |

---

## 目录

1. [先分清四个概念的层级](#1-先分清四个概念的层级)
2. [核心心智模型：检索链路的三个位置](#2-核心心智模型检索链路的三个位置)
3. [归属判定：一个口诀，三个裁决](#3-归属判定一个口诀三个裁决)
4. [三条红线](#4-三条红线)
5. [业界实践扫描](#5-业界实践扫描)
6. [本项目现状核验](#6-本项目现状核验)
7. [两个调用方带来的硬约束](#7-两个调用方带来的硬约束)
8. [落地路径与阻塞项](#8-落地路径与阻塞项)
9. [对简历口径的影响](#9-对简历口径的影响)
10. [附录：术语表](#附录术语表)

---

## 1. 先分清四个概念的层级

最初的混乱来自把四个不在同一维度的词混着用。它们的关系是：

| 名词 | 是什么 | 类比 |
|---|---|---|
| **Agentic Retrieval** | 一个**统称/时代标签**，指「检索不再是一次性的，而是带规划和自查的」 | 「自动驾驶」 |
| **Query Rewriting** | 一个**具体技术动作**：把用户的话改写成更适合检索的话 | 「车道保持」 |
| **Query Planning** | 一个**具体技术动作**：把一个问题拆成多个子检索并编排 | 「路径规划」 |
| **ReAct** | 一种**循环控制范式**（Reason→Act→Observe 反复） | 「控制算法」 |

所以「agentic retrieval 和 query rewriting 是什么关系」≈「自动驾驶和车道保持是什么关系」——**后者是前者的一个组成动作，不是同层的替代品**。

而 ReAct 更特殊：它是**实现手段**，不是能力本身。可以用 ReAct 实现 query planning，也可以用固定流程实现。**「我实现了 ReAct」说的是手段，「我实现了 agentic retrieval」说的是能力**——面试时把这两个混着说会显得没想清楚。

**一句话关系**：

> Agentic Retrieval = Query Rewriting + Query Planning + 证据自查迭代，
> 其中迭代部分**可以**用 ReAct 范式实现。

---

## 2. 核心心智模型：检索链路的三个位置

这是本文最该记住的一张图。整条链路上只有**三个位置**可能放「智能」：

```
用户原话
   │
   ├─ ① 搜之前：改写      Query Rewriting
   │      把用户的话翻译成文档的话
   │      （HyDE / Multi-Query / 同义词扩展）
   │
   ├─ ② 搜之前：拆分      Query Planning
   │      把一个问题拆成多个子检索并编排
   │      （子问题分解 / 元数据过滤路由）
   │
   ├─ ─────── 检索执行（hybrid + RRF + rerank）───────
   │
   └─ ③ 搜之后：迭代      证据自查
          看结果够不够，不够回到 ① 或 ②
```

**为什么这个拆分有用**：之前反复纠结「agentic 该放哪」得不出结论，是因为在问一个复合问题。拆成三个位置后，每个位置的答案是清晰的，而且**三个答案的理由各不相同**。

另外注意：①和②有重叠。Multi-Query 展开（改写出多个变体）和子问题分解（拆成多个子查询）**在实现上都是「一个 query 变多个 query」**，区别只在语义——前者是同一个意思的多种说法，后者是不同意思的多个部分。做工程设计时要划清，否则会重复实现。

---

## 3. 归属判定：一个口诀，三个裁决

### 口诀

拿不准某个决定该归谁时，问一句：

> **做这个决定，需要知道什么？**

- 需要知道**语料和索引长什么样** → 检索服务提供方（本项目）
- 需要知道**用户在干什么任务** → 调用方
- 两个都需要 → 说明这一步该拆成两半，各做一半

这是「能力应该放在拥有必要信息的那一侧」的口语版，是分工的第一性原理，其他都是推论。

### 裁决

| 位置 | 归属 | 理由 |
|---|---|---|
| ① 改写 | **提供方** | 改写的目的是把用户的话翻译成**文档的话**。要做这个翻译必须知道文档用什么词、chunk 切多长、什么文体。调用方不掌握这些 |
| ② 拆分 | **提供方**（有例外） | 同样依赖语料知识：知道哪类内容分散在多处、`category` 有哪些取值 |
| ③ 迭代 | **两边都要** | 两边问的是不同的问题，互相替代不了 |

### ② 的例外：语料结构 vs 业务流程

拆分依据是哪一种，决定归谁：

- 「精油推拿和泰式按摩差在哪、价格差多少」→ 拆成三个检索 → 因为**语料**把这三块分开存了 → **提供方**
- 「先查服务介绍 → 再匹配技师 → 再查可用时间」→ 这是**业务流程**，且后两步不走 RAG（查数据库）→ **调用方**

**判据**：这个拆分换一个知识库还成立吗？不成立 → 语料结构，归提供方。照样成立 → 业务流程，归调用方。

### ③ 为什么两边都要

这一条最容易被误解成二选一。实际上两边的回路问的是不同问题：

| | 提供方的回路 | 调用方的回路 |
|---|---|---|
| 它问什么 | **「证据找全了吗？」** | **「这个方向对吗？」** |
| 具体判断 | 子查询有空手而归的吗？命中段落被 chunk 边界切断了吗？ | 用户其实问的是另一回事？知识库确实没有，该转人工/问用户/改查数据库？ |
| 眼里只有 | 证据 | 任务 |
| 产出 | 一组**证据** | 一个**决定** |

**互相替代不了**：提供方不知道任务是什么；调用方不知道语料长什么样，而且（见 §7）接口只给它一次调用。

---

## 4. 三条红线

提供方侧越过这三条，就从「检索服务」变成「躲在 API 后面的 agent」，调用方将无法编排、无法信任、无法为其成本负责。

**一、「要不要检索」不是提供方的决定。**
被调用了就说明调用方已经决定要检索了。

**二、返回证据，不返回答案。**
一旦开始生成最终回复，就担起了对话责任，而对话上下文并不在提供方手里。

**三、指代消解做不了——这是硬约束，不是选择。**
调用方接口只传单个 query，没有对话历史（见 §7）。用户说「上次那个技师擅长的项目多少钱」，提供方收到的就是这句话本身，无从知道「上次那个」是谁。

> 对比【文献】：Azure AI Search 的 agentic retrieval 接的是**整段对话**而非单个 query——正是为了能做这件事。

两个解法：

- **（推荐）调用方在传入前把指代解掉** —— 它有对话历史，成本低，且符合 §3 的口诀
- **扩展接口允许传对话上下文** —— 像 Azure 那样，但要改对方接口，需协商

---

## 5. 业界实践扫描

### 5.1 提供方侧在做的

**最典型：Azure AI Search 的 agentic retrieval / knowledge agent**（2025 年推出）【文献】。形态几乎就是标准答案：

- 调用方发送**对话上下文**（不只是一个 query）
- **服务内部**做 query planning：拆子查询、并行执行、语义排序、合并去重
- 返回统一结果集 + references + **一份 activity/plan 记录**（走了哪几步、拆成了什么子查询）

最后一条值得注意：**它把内部规划过程报出来了**。这印证了「藏在一次调用背后的循环必须可观测」不是凭空要求。

其他（细节各家不同，置信度中等）【文献】：Vertex AI Search 的服务端 query 理解与扩展、OpenAI `file_search` 的内置 query rewriting、LlamaCloud 的 composite retrieval 多索引路由、Vectara / Contextual AI 等托管 RAG 的 query understanding。

**共同形态：进一个问题，出一组证据。内部多步，外部单次。**

### 5.2 调用方侧在做的

这边体量更大，而且是学术谱系的正统。

**LangGraph 是事实标准**【文献】。其官方参考实现里有一整套 agentic RAG 范式：

| 范式 | 做什么 |
|---|---|
| **Self-RAG** | 生成后自我批判，判断有无幻觉、证据够不够，不够就重检索 |
| **CRAG**（Corrective RAG） | 给检索结果打分，质量差就降级到网络搜索 |
| **Adaptive RAG** | 按问题复杂度路由：简单的直答、中等的单次检索、复杂的多步 |

这些循环**全在应用层**，底下的向量库就是个哑 API。

学术源头也在这边【文献】：**ReAct、IRCoT、FLARE、Self-RAG、CRAG** 的实现都是「模型/应用持有循环，retrieval 是被调用的函数」。**DSPy** 更是直接把多跳检索编译成应用层程序。

MCP 生态天然属于这边：host 拥有模型和循环，server 提供能力。

### 5.3 关键：两者是**叠**的，不是竞争的

```
用户
 ↓
LangGraph / Claude Code / 预约 agent        ← 任务级循环（调用方）
 ↓  一次调用
Azure agentic retrieval / 本项目的规划器     ← 检索级循环（提供方）
 ↓
向量库 / BM25 / rerank
```

真实生产系统通常两层都有。问「业界选哪个」是假二选一。

分工线：

| 决策 | 归属 |
|---|---|
| 要不要拆子查询？拆成什么？ | 提供方 |
| 命中段落被切断了，要不要补上下文？ | 提供方 |
| 稀疏/稠密权重？要不要过滤元数据？ | 提供方 |
| **要不要检索**（还是直接答/问用户/查数据库）？ | 调用方 |
| 检索完下一步干什么？ | 调用方 |
| 答案不满意，要不要换思路整体重来？ | 调用方 |

一句话：**提供方决定「怎么找」，调用方决定「找不找、找完干嘛」。**

### 5.4 趋势：提供方侧在往上吃【推断】

```
2023  纯向量 API                     ← 提供方什么都不做
2024  + hybrid + rerank + query rewriting
2025  + query planning / agentic retrieval
```

边界一直在往上移，但**在一个明确的地方停住了**：

> **提供方返回证据，永远不返回决定。**

### 5.5 MCP 场景尚未收敛【推断】

- 协议设计意图明显偏调用方——`sampling` 原语的存在就是为了让 server 不必自带 LLM
- 但 `sampling` 客户端支持率一直很差，导致需要推理的 server 普遍自带 LLM
- 现存 MCP RAG server 绝大多数是**单次哑检索**，少数开始做内部改写
- 没有哪家发布过「MCP agentic retrieval server」的标准范式

**本项目在这个方向上偏早**。既是优势（有得讲）也是风险（没有现成范式可抄，也没人背书）。

---

## 6. 本项目现状核验

> ⚠️ **本节的缺陷清单已于 2026-08-10 由 Feature-004 全部修复**。修复后的实测数字见
> [specs/004-retrieval-infra-fix/acceptance.md](../../specs/004-retrieval-infra-fix/acceptance.md)。
> 摘要：标识回查命中率 0/200 → **200/200**；中文词条占比 0% → **78.9%**；
> 两路检索结果重合从恒为 0 → 8 个查询中 7 个有重合。
>
> 本节保留原始诊断内容，因为**发现过程**比结论更有价值 —— 这三个缺陷的共同点是
> 「静默失效」，不报错、不告警，只是结果悄悄变空。

### 6.1 三个位置都是空的

| 位置 | 现状 |
|---|---|
| ① 改写 | **无**。`query_processor.py` 全程不调 LLM，只做正则分词 + 停用词过滤 + filters 透传【代码】 |
| ② 拆分 | **无**。`hybrid_search.py:162` 只喂 dense + sparse 两路【代码】 |
| ③ 迭代 | **无**。`grep -iE "react\|agentic\|agent"` 在 `src/` 下 116 个 py 文件中零命中【实测】 |

### 6.2 已有的可复用基建

- **多路融合能力已就位**：`fusion.py` 的 `fuse()` 签名是 `List[List[RetrievalResult]]`，天然支持 N 路。**改写出的多个 query 各自检索后直接喂进去即可**【代码】（注意：代码能力就位，但因 §6.3 缺陷零，它至今没真正融合过任何东西）
- **元数据过滤已有**：`hybrid_search.py:231` `_apply_metadata_filters`【代码】
- **分阶段耗时已记录**：`trace_context.py:27` `duration_ms`、`:119` `total_duration_ms`【代码】
- **评估体系完整**：Feature-001 的 8 项指标 + baseline/delta + archive，是做消融实验的现成度量底座
- **SSE transport 已完整实现**：`server.py:190` `run_sse()`（Starlette + uvicorn），`settings.py:380` `VALID_TRANSPORTS = {"stdio","sse"}`，`settings.yaml` 的 `mcp_server.transport` 即开关【代码】。starlette/uvicorn 由 `mcp` 传递依赖带入。**§7.4 曾把传输方式列为阻塞项，那是照 CLAUDE.md 旧描述写的，实际代码已超前**

### 6.3 四个已知缺陷/缺口

> **✅ 状态更新（2026-08-10）**：下述四个缺陷**已全部修复** —— 缺陷零、二、三由 [Feature-004](../../specs/004-retrieval-infra-fix/spec.md)，缺陷一（RRF 无权重）由 [Feature-005](../../specs/005-weighted-fusion/spec.md)。原先判断「缺陷一留待 Query Rewrite feature」的说法已作废：它单独成了一个 feature，而且校准过程还反过来发现了金标 recall 偏向 dense 这个更根本的问题（见缺陷一条目）。修复后实测：
>
> | 指标 | 修复前 | 修复后 |
> |---|---|---|
> | 索引标识回查 Chroma 命中率 | **0 / 200** | **200 / 200** |
> | 中文语料索引含汉字词条占比 | **0 %**（7,165 词条零汉字） | **78.9 %**（30,246 / 38,347） |
> | sparse 路径返回内容 | 恒为空 | 带正文，中文查询 top1 精准命中 |
> | `mt5_docs_chinese` 索引体积 | 37.4 MB | **17.7 MB** |
> | 该索引加载耗时 | 1.81 s | **1.29 s** |
> | 向量侧 collection 隔离 | 全在 `default`，靠元数据区分 | 物理隔离，两侧口径一致 |
>
> 词条数涨了 5 倍而体积和加载时间反而下降，是因为索引格式改成了 chunk 标识字典化（倒排项存整数下标而非 91 字符的路径式标识）。详见 [contracts/bm25_index.schema.md](../../specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md)。

**零、chunk_id 体系不一致 —— 混合检索从未真正生效（最严重）**【实测】【已修复】

BM25 索引与 Chroma 数据来自**不同批次的 ingest、不同版本的代码**，chunk_id 完全不相交：

```
BM25 索引 : doc_17e0642333a24b6e_0000_d0fc09b9
Chroma    : C:\workspace\...\ingest_source\MetaTrader5SDK_English.chm_1925_a0973c74
```

抽 200 个 BM25 chunk_id 查 Chroma，**命中 0 / 200**。

旁证：磁盘上的 BM25 文件带 `indent=4`，而当前 `bm25_indexer.save()` 写的是无缩进 JSON —— 索引确实是旧版代码留下的产物。

**后果链**：

1. `fusion.py` 按 `chunk_id` 合并 → 两边 ID 不相交 → **没有任何 chunk 会被识别为「两路都命中」**，RRF 退化成两个列表拼接
2. `sparse_retriever.py:134` 拿 BM25 返回的 ID 去 `get_by_ids()` 查 Chroma → 查不到 → **sparse 那路返回空**
3. **「混合检索」实际一直是纯 dense。Feature-001 归档的所有评估数字，都是纯 dense 的数字**

**语料本身是干净的**【实测】：52,580 条（99.4%）是金标引用的 `ingest_source` 路径式 ID，329 条 finpoints，仅 10 条 temp 临时文件残留。问题**只**在索引侧。

**修复路径被数据现状锁死**：`ingest_source/` 目录已不存在（原始文档没了），且 embedding 走 API（重新 embedding 52,919 条有真实成本）。因此唯一可行路径是**从 Chroma 反向重建 BM25**——读 `embedding_id` + `chroma:document` + `metadata.collection`，按 collection 分组重建。ID 天然对齐，零 embedding 成本。

> **这一次重建同时解决下面全部四件事**：ID 对齐、CJK 切分、collection 物理隔离、索引格式瘦身。

**一、RRF 无权重**【代码】【✅ 已由 [Feature-005](../../specs/005-weighted-fusion/spec.md) 修复】
原先 `fusion.py` 是 `rrf_score = 1.0 / (self._k + rank)`，没有权重项。现在是 `weight[r] / (k + rank)`，权重与平滑参数 `k` 均由 `settings.yaml` 的 `retrieval.fusion_weights` / `retrieval.rrf_k` 控制。

**修复后实测（英文金标 42 条，`dense` 固定 1.0）**：

| dense : sparse | hit_rate | recall | MRR | nDCG |
|---|---|---|---|---|
| 1 : 0（纯语义） | 69.0% | 45.7% | 0.4365 | 0.3889 |
| **1 : 0.1**（采用值） | 66.7% | **45.7%** | 0.4693 | 0.4106 |
| 1 : 0.75 | 66.7% | 44.3% | **0.5395** | **0.4237** |
| 1 : 1（改造前的等权） | 64.3% | 42.4% | 0.5115 | 0.3995 |

**消除了 recall 倒退**（等权 42.4% → 45.7%，与纯语义持平），两个语种的 MRR / nDCG 都优于纯语义。

**但校准中发现一件比权重更重要的事**：金标的 `expected_chunk_ids` 是 `backfill_chunk_ids.py:85` 直接调 `vector_store.query()` 回填的 —— **纯 dense 检索，无 BM25、无融合**。所以 `recall` / `hit_rate` 这把尺子是用 dense 自己的布裁的，任何 sparse 贡献挤掉一条 dense 命中就只能拉低它们。比较混合与单路时 `MRR` / `nDCG` 更可信。

这个发现指向一个结论：**提升混合检索的下一步不在融合权重，而在关键词路径的质量本身（查询改写）或金标的构造方式（人工标注答案边界）。** 完整曲线与取舍见 [Feature-005 验收记录](../../specs/005-weighted-fusion/acceptance.md)。

> **2026-08-13 补充**：上面这两个方向里，**「金标的构造方式」已被第二次、且更强地验证为瓶颈**。重排（cross-encoder）落地后的 A/B 显示英文金标 MRR 0.4914 → 0.3668，而同一个模型在集成测试里每次都能把故意放在末位的相关段落提到首位。原因是 `expected_chunk_ids` 由纯 dense top-5 回填，标准答案本身就是「embedding 认为最相关的那几条」，而重排的全部工作就是不同意第一阶段的排序 —— 于是**四项 custom 指标对重排全都是 dense-anchored 的**，连 `MRR`/`nDCG` 也不中立（本文其他地方说 MRR/nDCG 更可信，那只适用于 dense-vs-sparse 的路径比较）。详见 [重排验收记录](../../openspec/changes/archive/2026-08-13-activate-cross-encoder-rerank/acceptance.md) § 五。

**二、CJK 在整条 sparse 链路上被丢弃（查询端 + 索引端都是）**【代码】【已修复】

查询端 `query_processor.py:145`：

```python
normalized = re.sub(r"[^a-z0-9\s-]", " ", normalized)
```

索引端 `sparse_encoder.py:128`：

```python
tokens = re.findall(r'\b[a-z0-9]+\b', text)
```

两处字符类都只保留 ASCII 字母数字，**汉字全部被丢弃**。

这不是「查询端一行 bug」，而是**端到端的 ASCII-only 设计**，三个后果依次递进：

1. 纯中文查询提取出的 keywords 为空
2. **BM25 索引里本身就没有任何中文词条** —— 即便查询端修好了也检索不到，因为索引是空的
3. 因此中文语料上的「混合检索」**实际一直是纯 dense**

**连带影响**：`golden_test_set_zh.json` 6 条全是中文查询【实测】，所以 Feature-001 已归档的中文基线数字，本质是**纯 dense 的分数**，不是混合检索的分数。

**修复范围**（远超「< 10 行 bug 修复」，因此不适用宪法例外，需走 SDD）：
- 两处 tokenizer 都要改，且**必须保证查询端与索引端切分口径一致**（否则查询切出的词永远匹配不上索引里的词）
- 需要选定中文切分方案（jieba 分词 / 字符 bigram / 其他），可能引入新依赖
- **改完必须全量重建 BM25 索引**（re-ingest），旧索引里没有中文词条
- 重跑 Feature-001 评估并重标基线

**三、无 P95 统计**【实测】【未修复 —— 不在 Feature-004 范围】
`grep -iE "p95|percentile|latency"` 在 `src/` 下零命中。原始耗时数据在 `logs/traces.jsonl`，但没有任何聚合成分位数的代码。要给出延迟指标需先写统计脚本。

**四、dense / sparse 的 collection 隔离口径不一致**【实测】

`vector_upserter.py:102` 的 `upsert()` **从不传 collection**，向量全进 `settings.vector_store.collection_name` 指的那个物理 collection；而 `pipeline.py:650` 的 BM25 是**按 collection 分文件存**的。所以 `--collection` 参数**在 sparse 侧是物理隔离，在 dense 侧只是打了个 metadata 标签**。

实际布局：

| Chroma 物理 collection | 向量数 | | `metadata.collection` 取值 | 条数 |
|---|---|---|---|---|
| `default` | 52,757 | | `mt5_docs_chinese` | 21,193 |
| `finpoints_handbook` | 162 | | `mt5_docs_english` | 31,387 |
| `mt5_docs_chinese` | **0（空壳）** | | `finpoints_handbook` | 324 |
| | | | `default` | 15 |

后果：`collection_name: default` 时 dense 搜全部 52,757 条，sparse 只加载 `default.json`（5 篇 / 53 词条）——**两路语料范围差 4 个数量级**。加 `--collection` 也无用：它是融合后过滤，且 sparse 从 settings 读 collection、不看 CLI 参数。

**决策**：统一到物理隔离 + 复制式迁移脚本（磁盘 63GB 空闲，Chroma 仅 626MB，复制成本可忽略；不做不可逆删除）。同时把 `--collection` 改成真正切换检索范围。

### 6.4 金标集对「多跳」的覆盖【实测】

| 文件 | 条数 | simple | multi_context | reasoning |
|---|---|---|---|---|
| `golden_test_set_zh.json` | 6 | **6** | 0 | 0 |
| `golden_test_set_en.json` | 42 | 22 | 9 | 11 |

**中文集全是 simple，一条多跳都没有。** 英文集 20 条（48%）非 simple，是目前唯一能验证「多跳到底难不难」的样本。

> **可信度折扣**【实测】：两个集里**每条的 `expected_chunk_ids` 都恰好 5 个**，是 `backfill_chunk_ids.py` 按固定 top-5 回填的，不是人工标注的真实答案边界。这会削弱它对多跳问题的判别力，看结果时要心里有数。

**待做的实证检查**（成本近零，评估基建现成）：跑一次评估，看英文集 20 条 multi_context+reasoning 的 `ragas__context_recall` 比 22 条 simple 低多少。

- 差距大 → 缺口真实，做规划器有的放矢
- 差距小 → 语料撑不起这个特性

**建议在开 spec 前先跑这一次。**

---

## 7. 两个调用方带来的硬约束

本项目不只被 Claude Code 调用，还要被 `smart-appointment-ai-agent` 当工具调用。这个事实**改变了结论**，因为它带来三个硬约束。

### 7.1 接口形状已被定死【代码】

`services/knowledge_search.py` 的 `KnowledgeSearchPort`：

```python
async def search(self, query: str, top_k: int = 3,
                 category: Optional[str] = None) -> list[dict[str, Any]]
```

**单次调用、无状态、进 query 出文档。**

三个推论：

- 位置 ①② 只能在这次调用**内部**发生——调用方没有插入点
- 位置 ③ 的「证据自查」也必须在内部，否则没人做
- `category` 参数 = **元数据过滤已是硬需求**，不是推测

对方文档明确写着「接入独立 RAG 项目 = 实现一个端口 client 并注入」——**这个 port 的形状恰好就是 §5.1 里业界提供方侧的标准形状**。规划器塞进去，对方一行代码不用改。

### 7.2 调用方侧的循环已经饱和【代码】

`harness/runtime/agent_loop.py`：

| 机制 | 位置 |
|---|---|
| `max_steps: int = 8` | `:95`、`:109`，注释写「用 range 而非 while True——天然带硬上限」 |
| `BUDGET_EXCEEDED` token 预算 | `:63` |
| `MAX_STEPS` 跑满兜底 | `:64`、`:277` |
| `SpinDetector` 打转检测 | `:183`，「连续相同工具调用达上限即终止，是早于 max_steps 的逃生口」 |
| 主循环 | `:202` `for _step in range(self.max_steps)` |

**结论：两个调用方都自带完整 ReAct 循环**（Claude Code 本身就是；预约 agent 见上表）。

**在本项目再写一个通用 ReAct 循环 = 造第三个轮子。**

### 7.3 但那两个循环都不会用来做检索规划

- **Claude Code** 能做，但只能靠自己瞎试着换措辞重调，没有语料知识、没有策略
- **预约 agent 做不了**：port 是单次的；即便能多调，那 8 步预算是留给「识别意图 → 匹配技师 → 查可用时间 → 下单」的，system prompt 是关于预约业务而非检索策略的

**所以真实空缺是：没有任何一层在负责「把证据找全」。** 这就是本项目该补的位置。

### 7.4 传输方式缺口

本项目 MCP server 只有 stdio transport。预约项目是 FastAPI 常驻服务，**每请求 spawn 一个 stdio 子进程不可行**。接入前必须先定：HTTP/SSE transport、还是绕过 MCP 直接在进程内实现那个 port。

---

## 8. 落地路径与阻塞项

### 8.1 该做成什么形状

不是「第三个 ReAct 循环」，而是**藏在单次调用背后的受约束检索规划器**（本文自造的中文说法，非业界术语；英文用 bounded retrieval planner 或直接描述行为更稳妥）。

四道约束是它区别于通用 agent 的本质——**机制上可以就是一个 ReAct 循环**，区别只在约束：

| 约束维度 | 检索规划器 | 通用 ReAct Agent |
|---|---|---|
| 工具集 | 封闭，且**全是只读检索工具** | 开放，可含有副作用的工具 |
| 终止判据 | 固定：证据充分性 | 由 LLM 判断「任务完成」 |
| 预算 | 硬编码且小（3~5 步） | 8~50 步 |
| 状态 | **无状态**，不看对话历史，一次调用自包含 | 有状态，跨轮次持有会话 |

**第四条最关键**：无状态 = 可缓存、可测试、可并行、可重放。同一 query 进去结果确定（除 LLM 采样），因此能拿金标集跑 pytest、做消融、算 context_recall。**这也正是「循环放调用方就测不出数字」的技术原因。**

伪代码形状：

```python
async def search(query, top_k=3, category=None) -> list[dict]:
    plan = llm.plan(query)                  # 结构化输出，不是自由选工具
    evidence = await gather(*[hybrid_search(q) for q in plan.subqueries])

    for _ in range(MAX_REFINE):             # 2~3 步，不是 8
        gap = llm.check_sufficiency(query, evidence)   # 只问：还缺什么
        if gap.sufficient or over_budget():
            break
        evidence += await fill(gap)         # 只能调检索类工具

    return dedupe(evidence)[:top_k]         # 出去的是证据，不是答案
```

两个细节：`plan` 是**结构化输出**（规定只能输出子查询列表，它就跑不偏）；返回的是**文档而非答案**（守住红线二）。

### 8.2 优先级

经 2026-08-09 的设计盘问后确定。**目标语料锁定为现有的 mt5 语料**，门店知识库接入往后放。

**Feature-004「检索基础设施修正」**（一个 feature，内部 4 个独立 task，各自 commit；共享一次索引重建 + 一次基线重标）：

| Task | 事项 | 为什么 |
|---|---|---|
| **T1** | collection 物理隔离 + 复制式迁移脚本；`--collection` 改为真正切换检索范围；修正金标 `source_corpus_collection` 字段 | **解锁测量能力**。英文金标 42 条（含 20 条多跳）不受 CJK 影响，只被隔离问题卡着 |
| **T2** | 跑 Step 0：英文金标 simple(22) vs multi_context+reasoning(20) 的 `context_recall` 对比 | 这是 gate —— 决定后面的检索规划器到底做不做 |
| **T3** | CJK 字符 bigram 切分，tokenizer 抽成**两端共享的单一模块** | 两端口径漂移就是 bug 温床：查询切出的词永远匹配不上索引 |
| **T4** | 从 Chroma 反向重建 BM25 + 索引格式瘦身 + 重标基线 | 一次重建同时解决缺陷零/二/四 |

> **优先级修正**：早先把 CJK 排在第 0 位是错的。英文金标不受 CJK 影响，中文金标 6 条全 simple 也测不出多跳 —— **解锁 Step 0 只依赖 collection 隔离**。

**后续 feature（T2 结果决定）**：

| 顺序 | 事项 | 为什么 |
|---|---|---|
| **1** | 位置 ①：Query Rewriting（含带权重 RRF 前置改造） | port 单次调用下，提供方是唯一能改善查询的地方 |
| **2** | 位置 ②③：检索规划器（**条件性**，取决于 T2） | 内部编排细粒度检索工具，贴合 port 形状 |

> **细粒度工具的定位修正**：`search_by_keyword` / `expand_neighbors` 等仍要做，但**定位是规划器的内部工具，不是优先暴露的 MCP 工具**。原因：预约 agent 用不了（port 单次），只有 Claude Code 能用。

**已定的验收与处置口径**：

- **CJK 用二元验收**（中文金标仅 6 条且全 simple，样本量不支持量化提升幅度）：① 重建后 `mt5_docs_chinese.json` 含汉字词条从 0 变成数万；② 6 条中文查询的 sparse 返回从 ASCII 噪音变成相关 chunk；③ 中文集 8 项指标无倒退
- **旧基线保留并重标为「纯 dense 参照」**，不删除。旧数字不是错的，只是标签错了 —— 保留后「纯 dense vs 真混合」就是一组现成的消融数据
- **10 条 temp 临时文件残留 chunk**：单列出来，删除前需确认

### 8.3 两个独立测量面

- **本项目**：金标 + `ragas__context_recall`（检索质量）
- **预约项目**：`evals/metrics.py:446` `task_success_rate` + `tool_failure` 信号（端到端任务成功率）【代码】

端到端效果可做**三点对比**：未接入（`NotConfiguredKnowledgeSearch` 抛异常）vs 接入哑检索 vs 接入带规划器的版本。比只在本项目内部测有说服力得多。

---

## 9. 对简历口径的影响

三处需要修正：

**一、「指代」这个词要删。**
原文「针对短查询、指代和多跳问题选择 Multi-Query、HyDE 或问题分解」——**指代消解在当前 port 形状下做不到**（红线三）。面试问「你没有对话历史怎么消解指代」会答不上来。改成「短查询、模糊表述和多跳问题」即诚实。

**二、ReAct / max_steps / Token 预算这套已经在预约项目实现了。**【代码】
`agent_loop.py` 全都有，且 `简历.md:44` 已经写过一遍（在预约项目段落）。若把同一套再写在本项目名下，面试官对比两段会发现是同一件事写两遍。

**三、两条改成不重叠，并讲出边界。**

- 预约项目 → 通用 tool-calling 循环运行时（TAO/ReAct、护栏、打转检测）
- 本项目 → 受约束检索规划器（查询改写路由 + 证据充分性驱动的多步检索，藏在单次 port 调用后）

这样就能讲出**「为什么循环要分两层、边界为什么划在 `KnowledgeSearchPort`」**——比「我也实现了 ReAct」深得多，而且是真的。

另外，`[实测百分点]` / `[实测值]` 这类占位符要能填上，前提是 §6.3 缺陷三（无 P95 统计）和 §6.4 的实证检查都做掉。

---

## 附录：术语表

| 术语 | 含义 |
|---|---|
| **Agentic Retrieval** | 统称：检索带规划与自查，而非一次性执行 |
| **Query Rewriting** | 把用户的话改写成更适合检索的话（位置①） |
| **HyDE** | Hypothetical Document Embeddings：先让 LLM 编一段「假想答案」，拿它去做向量检索。前提是要知道语料的 chunk 长度与文体 |
| **Multi-Query** | 把一个 query 改写成多个语义等价变体，各自检索后融合 |
| **Query Planning** | 把一个问题拆成多个**语义不同**的子检索并编排（位置②） |
| **ReAct / TAO** | Reason→Act→Observe 循环范式。是**实现手段**，不是能力本身 |
| **Self-RAG** | 生成后自我批判，证据不足则重检索（调用方侧范式） |
| **CRAG** | Corrective RAG：检索结果打分，质量差则降级到其他来源 |
| **Adaptive RAG** | 按问题复杂度路由到不同检索深度 |
| **受约束检索规划器** | 本文自造说法（非业界术语）：工具封闭、判据固定、预算小、**无状态**的检索侧循环 |
| **RRF** | Reciprocal Rank Fusion。Feature-005 起为 `weight[r]/(k+rank)` 求和，权重与 `k` 均可配置（`retrieval.fusion_weights` / `retrieval.rrf_k`） |
| **KnowledgeSearchPort** | 预约项目定义的检索端口，`search(query, top_k, category) -> list[dict]`，单次无状态 |
| **sampling** | MCP 原语：server 反向请求 client 的 LLM 做推理。设计意图是让 server 不必自带 LLM，但客户端支持率低 |

---

## 待办清单

> **2026-08-13 状态更新**：本清单写于 Feature-004 规划期，多数项已完成。下面按现状重标。

**Feature-004（已完成并冻结于 [specs/004-retrieval-infra-fix/](../../specs/004-retrieval-infra-fix/)）**

- [x] T1 collection 物理隔离 + 迁移脚本 + `--collection` 语义修正 + 金标 `source_corpus_collection` 修正
- [x] T2 跑 Step 0，拿多跳缺口数据（gate：决定规划器做不做）
- [x] T3 CJK bigram，tokenizer 抽两端共享模块 —— 落地为 `src/core/text/tokenizer.py`，由 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 守住两端一致
- [x] T4 从 Chroma 反向重建 BM25 + 格式瘦身 + 重标基线 —— `scripts/rebuild_bm25_index.py`，索引格式 v2
- [x] 10 条 temp 残留 chunk 清理 —— 2026-08-10 用户确认后删除，向量库与索引均 10 → 0

**后续**

- [x] 扩展 `fusion.py` 支持带权重 RRF（§6.3 缺陷一）—— Feature-005 完成，`retrieval.fusion_weights` + `retrieval.rrf_k` 均为配置项，校准脚本 `scripts/calibrate_fusion_weights.py`
- [ ] 写 P95 延迟统计脚本（§6.3 缺陷三）**—— 仍未做**。而且比原以为的更麻烦：**`scripts/evaluate.py` 与 `scripts/query.py` 都不写 query trace**，只有 MCP server 路径写 `logs/traces.jsonl`。想统计延迟分布，得先给这两个脚本接上 trace，或者写独立基准脚本（2026-08-13 量重排延迟时就是被这一点逼着写了临时脚本）
- [ ] 划清 Query Rewriting 与 Query Planning 的实现边界（§2 末）**—— 仍未决策**
- [x] Step 0 的判据 —— 数据已到手，Feature-004 据此决定了 scope
- [ ] 修正简历三处口径（§9）；另需重新审视「混合检索」相关表述（§6.3 缺陷零）**—— 仍未做**
- [x] Feature-003 遗留 T018（人工耗时实测）—— 已按现状收尾，见 [specs/003-testset-refine-automation/acceptance-record.md](../../specs/003-testset-refine-automation/acceptance-record.md)
- [x] ~~修正 CLAUDE.md 的「The MCP server runs on stdio transport」~~ —— 已改，现明确写出 stdio + SSE 双 transport 由 `mcp_server.transport` 切换

**新增（2026-08-13，重排落地后）**

- [~] **金标 `expected_chunk_ids` 的构造方式已换代**（2026-08-13，change `retriever-agnostic-golden-labels`）—— 不是改成人工标注，而是**多路池化 + LLM 分级判定**：候选来自 dense / sparse / rerank 各自 top-N 的并集，再让异源 LLM 判 0-3 级相关度。中文 6 条实测与纯 dense top-K 的 Jaccard 仅 0.328、31% 的标签纯 dense 看不到。**仍未完成的是人工抽检** —— 它去掉了检索器锚定，但引入了判定模型自身的偏好，抽检是唯一校准手段。原表述「人工标注答案边界」 —— §319 已把它列为两个方向之一，重排的 A/B 是对它的**第二次、且更强的一次撞击**：`expected_chunk_ids` 是纯 dense top-5 回填的，所以四项 custom 指标对重排**全都**是 dense-anchored，`MRR`/`nDCG` 也不中立。集成测试证明模型在做正确的事（把末位的相关段落提到首位），指标却在跌。**不解决它，任何「敢改变名次」的改进都无法被离线评估**
- [ ] **中文金标从 6 条扩到 ≥ 40 条** —— 现在任何中文侧结论都不成立
- [ ] 跨语言压分的缓解 —— 实测中文 query 对中文答案得 0.9998、对语义等价的英文答案只得 0.2973。本项目语料是同一份 MT5 文档的中英双版本，这个偏差是真实存在的
