# 04 · 测试集：标准答案是谁造的

> **专题**：[RAG 评估系统学习](README.md) 第 04 章
> **前置**：[02 章](02-retrieval-metrics.md)（指标怎么用标注）、[03 章](03-generation-metrics.md)（RAGAS 读哪些字段）、[00 章 § 3](00-prerequisites.md#3-金标文件的字段解剖)（金标字段解剖）
> **本章目标**：知道一份金标是怎么造出来的、每一步引入了什么立场；看到一份陌生金标能判断它能不能用来比较。
> **预计**：25 分钟
> 📖 **遇到不认识的词** → [术语速查表](glossary.md)（查表用，不用顺读）

> ### 用人话说，这章解决什么
>
> 前面两章都在算分，而算分要有**参考答案**。到现在为止我们一直默默假设：**参考答案是对的。**
>
> **这一章拆掉这个假设。**
>
> 真相是：这份「卷子」（题目 + 参考答案 + 该翻哪几页）**也是 AI 造出来的** —— 人工出 100 道题要好几天，换一批资料还得重来，没人做得起。
>
> 于是问题变成：**AI 出的卷子，偏心谁？**
>
> 本章会给你一个具体到能动手查的答案。这是整个专题的**地基** —— 这层塌了，前面算的分全部作废。

---

## 1. 这是地基层

02 章开头有一句被刻意搁置的话：

> ⚠️ 「本章暂时假设标注是对的 —— 这是一个教学用的简化，不是事实。」

**本章拆掉这个假设。**

为什么它是地基：前两章所有指标的输入都是「哪些 chunk 是相关的」和「参考答案是什么」。这两样东西**不是从天上掉下来的**，它们是某个流程的产物。流程有什么倾向，指标就有什么倾向 —— 而指标不会告诉你这件事。

---

## 2. 鸡生蛋问题

要评估就得有标准答案。人工写 100 条高质量金标（问题 + 参考答案 + 逐条标出哪些片段相关）是**几天的工作量**，而且换一批语料就得重来。

于是几乎所有 RAG 项目都走同一条捷径：**让 LLM 造金标。**

```
语料 ──[LLM 合成]──> 候选问答对 ──[精修]──> 保留的 case ──[标注]──> expected_chunk_ids
                                                                        ↑
                                                          这一步决定了检索指标的立场
```

三步各有各的坑，本章按顺序过一遍。

---

## 3. 第一步：合成候选

### 3.1 做法

RAGAS 除了评估，还有第二个身份：**`TestsetGenerator` —— 从语料自动合成测试集**【文献】。

机制大致是：从语料抽取节点 → 让 LLM 基于节点生成问题和参考答案 → 按难度做「进化」（简单 / 多跳 / 推理型等）。

本项目对应 `scripts/synthesize_testset.py`。

### 3.2 坑：合成端产出的语言可能不是你要的

[03 章 § 5.3](03-generation-metrics.md#53-中文-ragas-有一个额外的坑) 讲过这个实测事故：`adapt(language=chinese)` 静默返回未翻译的英文提示词，导致 47 条中文候选里 33 条（70%）其实是英文问题。

**为什么它属于本章**：合成阶段的缺陷会一路传染 —— 语言错乱的 case 即使侥幸留下来，也会在 judge 阶段变成降级（03 章 § 5.2 的病因）。**金标的问题不会停在金标里。**

---

## 4. 第二步：精修

### 4.1 为什么必须有这一步

LLM 合成的候选质量参差：问题里泄露答案、参考答案在语料里根本找不到依据、语种混杂……**直接拿去评估等于用坏尺子量。**

本项目对应 `scripts/refine_testset.py`，默认是逐条人工 y/e/d/s/q 确认。

### 4.2 自动化，以及它的代价

逐条人工确认单语种要 30-60 分钟。本项目做了 `--auto-mode`：**LLM 预筛 → 只对存疑的点人 → 收尾抽样自检**。

三条路径：

```
预筛给出 keep + 置信度 ≥ 0.90  →  自动保留
预筛给出 drop + 置信度 ≥ 0.80  →  自动丢弃
其余                            →  borderline，交人工
```

【代码】阈值在 [config/settings.yaml:209](../../../config/settings.yaml#L209) 的 `screening_llm`。

⚠️ **阈值必须校准，且不可跨模型移植**。本项目实测【实测】（`z-ai/glm-5.2-free`，47 条扫描，2026-08-08）：

| `keep_threshold` | borderline 占比 |
|---|---|
| 0.80 | 4.3%（太松，几乎全自动 —— 等于没做人工把关） |
| **0.90** | **10.6%** ← 落进预期 10-20% 区间，取此值 |
| 0.95 | 29.8%（偏严，接近 40% 告警线） |

**换预筛模型后必须重新扫描** —— 不同模型的置信度标度不可互换。这与「换 judge 后阈值失效」是同一回事，本项目里这类「阈值不可跨模型移植」的情形一共出现了四处（05 章会汇总）。

### 4.3 这里出现了本专题第一条硬约束：异源

> **预筛模型必须与合成模型异源。**

理由很直接：**候选是 judge_llm 合成的，再用同一个模型判断「这条 case 好不好」，等于自己批自己的作业。** 同一个模型的盲点会原封不动地保留下来。

【代码】判据是**完整标识串** `<provider>:<model>` 不相等，**不是 provider 不相等**（[config/settings.yaml:197-208](../../../config/settings.yaml#L197)）：

```
judge_llm      : glm:minimax/minimax-m2.7      ← provider 名义是 glm，实际路由到 minimax
screening_llm  : glm:z-ai/glm-5.2-free         ← 标识串不同 → 异源 ✅
```

**只比 provider 会把真正异源的两个模型误判为同源。** 这条在本项目里被写成了启动期硬校验：同源直接退出码 2，且**不可用 `--allow-same-source` 豁免**（该参数只豁免「无法确认」）。

---

## 5. 第三步：标注期望片段 —— 两代分岔点

到这一步为止我们有了 `query` 和 `ground_truth`。还缺 `expected_chunk_ids` —— **「哪些片段算正确答案」**。

**本项目有两代做法，这是整个评估体系里最关键的一处分歧。**

### 5.1 第一代：`dense-top-k`

```
拿 ground_truth 去做 dense 检索  →  top-5  →  就是 expected_chunk_ids
```

【代码】`scripts/backfill_chunk_ids.py`：把参考答案编码成向量，查 `vector_store.query()`，取前 5。**纯 dense 检索，无 BM25、无融合、无重排。**

机械特征很好认【实测】：

| 文件 | 每条 case 的 `expected_chunk_ids` 平均条数 |
|---|---|
| `golden_test_set_en.json`（v1） | **5.0** ← 恒等于 5，就是 top-5 |
| `golden_test_set_zh.json`（v1） | **5.0** |

**致命弱点** —— 一句话：

> **标准答案就是「embedding 认为最像参考答案的那 5 条」。**

于是所有召回类指标都**锚定在 dense 一路上**。后果在 05 章展开，这里先记住这个形状。

### 5.2 第二代：`pooled-llm-judged`

```
用 query（不是答案）从 dense / sparse / rerank 三路各取 top-N
   ↓
取并集去重（池化，pooling）→ 每条 case 约 25-40 个候选
   ↓
让 LLM 逐条判 0-3 分级相关度
   ↓
≥ relevance_threshold(=2) 的进 expected_chunk_ids
```

【代码】`scripts/label_golden_chunks.py`，配置在 [config/settings.yaml:245](../../../config/settings.yaml#L245)。

两个关键改动：

1. **用 query 而不是 ground_truth 去召回** —— 不再是「找像答案的片段」，而是「找回答问题需要的片段」
2. **多路并集** —— 没有任何一路能垄断标准答案

> 💡 `pooled` 这个词有来头。它是信息检索评测（TREC）几十年的标准做法【文献】：语料太大无法穷举标注，就把**多个参赛系统**的 top-N 结果并起来只标这个池子。本项目把「多个参赛系统」换成了「自己的三条检索路径」。

机械特征同样好认【实测】：

| 文件 | 平均条数 |
|---|---|
| `golden_test_set_en_v2.json` | **15.4** |
| `golden_test_set_zh_v2.json` | **12.0** |

**从 5 条涨到 12-15 条，这不是「标松了」** —— 是原来那 5 条之外确实还有相关片段，只是第一代看不见。

### 5.3 换代到底换出了什么：一个数字

【实测】中文 6 条实测（记在 `_labeling_metadata` 里）：

```
mean_dense_jaccard : 0.328
accepted_count     : 72
```

Jaccard 0.328 意味着：**新旧两套标准答案的重合度只有约三分之一。** 被接受的 72 条里，**22 条（31%）是纯 dense 结构上根本看不到的**。

> ⚠️ **直接推论**：v1 和 v2 金标上的分数**不可比较**。分数变化里混着「标注口径变了」和「检索质量变了」两件事。本项目在报告里用 `delta_comparable: false` 显式标注跨代比较【代码】—— 但**工具只能标注，判读还是你的事**。

### 5.4 第二代也有立场，只是换了一个

新方法去掉了检索器锚定，**代价是引入了判定模型自身的偏好**。

三条必须知道的限制：

| 限制 | 实情 |
|---|---|
| 判定模型也要异源 | `labeling_llm` 必须 ≠ `judge_llm`（`ground_truth` 就是 judge 写的，同源等于自我确认） |
| **两代金标都没有机器可读的合成端标识** | 建于 2026-04-28，早于该字段。所以异源检测返回 `UNVERIFIABLE`，**当前只能靠 `--allow-same-source` 显式承担风险**【实测】 |
| **校准是「跨模型」而非「人工」** | 见下 |

关于最后一条【实测】（2026-08-14）：24 条三元组由 `anthropic:claude-opus-5` 盲评，与原判定模型 `glm:z-ai/glm-5.2-free` 一致率 **95.8%（23/24）**，唯一分歧那条复盘为原判定更正确。

**但元数据里记的是 `cross_judge_agreement_rate`，`human_agreement_rate` 是 `null`。**

> ⚠️ **两个判定方都是 LLM，可能共享人类会发现的盲点。** 95.8% 的一致率证明的是「两个模型看法一致」，不是「判定正确」。若将来任何依赖 v2 金标的结论被质疑，**第一件该做的事就是补真人抽检** —— 审阅表已经在 `tests/fixtures/labeling_review_zh.md`，可直接对照两方分歧。

---

## 6. 拿到一份陌生金标，怎么判断能不能用

按顺序问四个问题：

| # | 问题 | 去看哪个字段 |
|---|---|---|
| 1 | `expected_chunk_ids` 怎么挑的？ | `_labeling_method`（**不是 `version`**） |
| 2 | 在哪个集合上标的？现在评的是同一个吗？ | `source_corpus_collection` |
| 3 | 标注模型是谁？与合成端异源吗？ | `_labeling_metadata.labeling_llm_identifier` |
| 4 | 有多少条？一条 case 值多少分？ | `len(test_cases)`（回到 [00 章 § 6](00-prerequisites.md#6-小样本一条-case-值多少分)） |

> ⚠️ **第 1 条最容易搞错**：`version`、`_schema_version`、`_labeling_method` 是三个不联动的字段。本项目就有 `version: v1.0` 但内容已换代的实例（[术语速查表 § 4](glossary.md)）。**判断可比性只看 `_labeling_method`。**

---

## 7. 在本项目里：金标文件清点

【实测】（2026-08-17 逐个读取 `tests/fixtures/`）：

| 文件 | version | 条数 | `_labeling_method` | 平均期望片段数 | 状态 |
|---|---|---|---|---|---|
| `golden_test_set.json` | v0.1-smoke | 4 | — | 1.5 | 冒烟占位，不用于验收 |
| `golden_test_set_en.json` | v1.0 | **42** | `dense-top-k` | 5.0 | **当前英文主力** |
| `golden_test_set_en_v2.json` | v2.0 | 41 | `pooled-llm-judged` | 15.4 | 第二代，未设为默认 |
| `golden_test_set_zh.json` | v0.1-partial | **6** | `dense-top-k` | 5.0 | **当前中文主力**（条数严重不足） |
| `golden_test_set_zh_v2.json` | v2.0 | 6 | `pooled-llm-judged` | 12.0 | 第二代 |
| `golden_test_set_zh_v3.json` | v1.0 | 29 | — | **0.0** | 已精修，**期望片段尚未标注** |

三处值得注意：

1. **`settings.yaml` 默认指向的仍是第一代**【代码】（[config/settings.yaml:175-177](../../../config/settings.yaml#L175)）。也就是说本项目**日常跑的报告全部是 dense-anchored 的**。
2. **中文只有 6 条**，一条 case 值 16.7% —— 中文侧的任何结论都应视为轶事而非证据。
3. **`zh_v3` 有 29 条但期望片段是空的**，跑检索指标会直接失败。它是「已完成精修、卡在标注」的半成品。

### 7.1 还有一个必须记住的坑

> **金标必须在含全部语料的集合上评估**（当前是 `default_text-embedding-v4`），**不要指向 `mt5_docs_chinese` / `mt5_docs_english`。**

【实测】原因：中英文语料是同一份 MT5 文档的两个语言版本，回填时匹配**跨了语言** —— en 集 42 条里 18 条跨语料、210 个 chunk_id 里 20 个指向中文。分语言集合只能解析 190/210，评估会直接触发 `chunk_id_validation` 失败。

这是 [00 章 § 1.2](00-prerequisites.md#12-一个真实的-chunk_id-长什么样) 那条「金标绑定在一次具体入库结果上」的直接后果。

---

## 8. 自测

<details><summary><b>Q1.</b> 第一代 <code>dense-top-k</code> 一句话是什么做法？它的致命弱点是什么？</summary>

拿 `ground_truth` 做 dense 检索，top-5 就是标准答案。弱点：**标准答案就是 embedding 认为最像答案的那几条**，于是所有召回类指标都锚定在 dense 一路上。（§ 5.1）
</details>

<details><summary><b>Q2.</b> 第二代改了哪两件事？</summary>

① 用 **query** 而不是 ground_truth 去召回（找「回答问题需要的」而非「像答案的」）；② **多路池化**（dense/sparse/rerank 取并集），没有任何一路垄断标准答案。（§ 5.2）
</details>

<details><summary><b>Q3.</b> 你看到两份报告分数差 0.1，怎么判断能不能比？</summary>

先看 `_labeling_method` 是否相同。跨代的话，实测新旧标准答案 Jaccard 只有 0.328 —— 分数变化里混着「口径变了」。**不要看 `version` 字段**，它与标注方法不联动。（§ 5.3、§ 6）
</details>

<details><summary><b>Q4.</b> 为什么预筛/标注模型必须与合成模型「异源」？判据是什么？</summary>

候选和参考答案都是 judge_llm 造的，同一个模型来筛/标等于自己批自己的作业，盲点会原样保留。判据是**完整标识串 `<provider>:<model>` 不相等**，不是 provider 不相等 —— 本项目的 `glm:minimax/...` 名义 provider 是 glm 但实际路由到 minimax。（§ 4.3）
</details>

<details><summary><b>Q5.</b> v2 金标的 <code>cross_judge_agreement_rate = 95.8%</code>，能说明标注是可靠的吗？</summary>

不能完全说明。两个判定方**都是 LLM**，一致只证明看法相同，可能共享人类会发现的盲点。`human_agreement_rate` 至今是 `null`。（§ 5.4）
</details>

<details><summary><b>Q6.</b> 本项目日常跑出来的报告，用的是第几代金标？</summary>

**第一代**（`settings.yaml` 默认指向 `golden_test_set_{zh,en}.json`）。所以现有报告全部是 dense-anchored 的 —— 这一点在读任何历史结论时都要记着。（§ 7）
</details>

---

## 本章小结

| 问题 | 答案 |
|---|---|
| 金标怎么来的 | 合成 → 精修 → 标注期望片段，三步都由 LLM 参与 |
| 两代的分歧点 | 第三步：`dense-top-k`（答案去 dense 查 top-5）vs `pooled-llm-judged`（query 多路池化 + LLM 分级判定） |
| 换代换出多大差异 | 新旧标准答案 Jaccard **0.328**；31% 的接受项纯 dense 看不见 |
| 贯穿全程的硬约束 | **异源** —— 判据是完整标识串，不是 provider |
| 判断可比性看哪个字段 | `_labeling_method`，**不是 `version`** |
| 第二代的残留风险 | 校准是跨模型的，`human_agreement_rate` 仍为 `null` |

## 深入阅读

| 想深入 | 去哪 |
|---|---|
| 金标的完整流水线、词源、两代逐词拆解、退出码约定 | [golden-test-set-explained.md](../golden-test-set-explained.md)（本项目最完整的一篇，本章基本是它的入口版） |
| 精修自动化的三条路径与审计元数据 | [specs/003-testset-refine-automation/quickstart.md](../../../specs/003-testset-refine-automation/quickstart.md) |
| 合成端的语言校验 | [ragas-basics.md § 8.4](../ragas-basics.md) |

**下一章** → [05 · 元评估：这些分数凭什么信](05-meta-evaluation.md) ← **本专题的分水岭**
