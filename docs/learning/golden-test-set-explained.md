# 金标是什么：从词源到本项目的两代标注方式

> **专题定位**：[RAG 评估系统学习](rag-evaluation/README.md) **第 04 层（测试集）的深入阅读**。本文讨论的 `expected_chunk_ids` 正是 [02 章](rag-evaluation/02-retrieval-metrics.md) 所有指标的输入。第一次接触请先读专题的 [04 章](rag-evaluation/04-golden-set.md)（入口版，25 分钟，含金标文件清点与「拿到一份陌生金标怎么判断能不能用」），再回来看这里的完整流水线与两代逐词拆解。
> **记录日期**：2026-08-15
> **关联代码**：[`scripts/backfill_chunk_ids.py`](../../scripts/backfill_chunk_ids.py)、[`scripts/label_golden_chunks.py`](../../scripts/label_golden_chunks.py)、[`src/observability/evaluation/eval_runner.py`](../../src/observability/evaluation/eval_runner.py)、`tests/fixtures/golden_test_set_*.json`
> **关联变更**：`openspec/changes/archive/2026-08-14-retriever-agnostic-golden-labels/`（两代划分的定义处）
> **起因**：「金标」「v1/v2」「dense-top-k」「pooled-llm-judged」这几个词在项目文档里被大量使用却从未定义过。它们是理解本项目所有评估结论的前提——包括「重排指标为什么会跌」「HyDE 分数为什么会虚高」这两个最反直觉的发现

## 置信度标注约定

「置信度」= **这句话有多可信、凭什么可信**。本文每条结论都在句尾挂一个方括号标签，说明它的**来源**——因为一篇笔记里混着「源码里写着的事实」和「我个人的推测」，读者若分不清，就会把后者当前者去做决策。

沿用 [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) 的约定，四档**从硬到软**：

| 标注 | 含义 | 可信度 | 引用时 |
|---|---|---|---|
| **【代码】** | 从本仓库源码直接读出，附文件行号 | 最硬——可当场翻代码复核 | 直接用 |
| **【实测】** | 在本机实际运行验证过，2026-08-15 | 硬，但**只在当时那套环境/模型/语料下成立** | 换环境需重测 |
| **【文献】** | 来自论文/公开资料 | 高，但可能过时 | 以最新版为准 |
| **【推断】** | 本文作者的综合判断 | 最软，**不是共识** | **引用前请自行核验** |

> 💡 这个约定本身就是本项目的一条硬规矩（CLAUDE.md § 学习笔记）：**没跑过不许标【实测】**。§9「HyDE 分数会虚高」标的是【推断】而不是【实测】，正是因为本项目**还没真跑过 HyDE 的 A/B**——那是逻辑推出来的，不是量出来的。

> ⚠️ **本文里「置信度」有两个不相干的含义，别混**：这里说的是**给读者看的来源标签**（人工标的、四档离散值）；§6.5 ②「精修」里 `keep_threshold: 0.90` 那个置信度是**预筛模型自己吐出来的一个 0~1 数字**，用来决定该 case 自动处理还是转人工，与本节无关。

---

## 目录

1. [「金标」这个词是什么意思](#1-金标这个词是什么意思)
2. [一条 case 里有两种「答案」](#2-一条-case-里有两种答案)
3. [两种答案喂给两组不同的指标](#3-两种答案喂给两组不同的指标)
4. [最脆弱的一环：期望片段谁来定](#4-最脆弱的一环期望片段谁来定)
5. [第一代：`dense-top-k`](#5-第一代dense-top-k)
6. [第二代：`pooled-llm-judged`](#6-第二代pooled-llm-judged)
   - 6.5 [**金标是怎么造出来的：完整流水线**](#65-金标是怎么造出来的完整流水线)
7. [两代对照](#7-两代对照)
8. [三个长得像版本号的东西](#8-三个长得像版本号的东西)
9. [两代的偏向：一把有立场的尺子](#9-两代的偏向一把有立场的尺子)
10. [本项目金标文件清点](#10-本项目金标文件清点)
11. [已知局限与待办](#11-已知局限与待办)
12. [附录：术语表](#附录术语表)

---

## 1. 「金标」这个词是什么意思

**金标 = golden test set / gold standard**，也译作「黄金标准」。

**【文献】** 「gold standard」原本是**医学与计量学**的词：指某领域里公认最可靠的那个参照物，别的方法都拿它对标（更早可追溯到金本位时代——货币以黄金为准）。在检索与机器学习里，它指**一份「已知正确答案」的题库**。

> **打个比方**：要评价学生答得好不好，得先有一份**标准答案册**。
> **金标就是那份答案册，你的 RAG 系统是那个学生。**

### 为什么 RAG 非要它不可

RAG 系统的输出是「一段自然语言回答 + 一堆检索到的文档片段」。这种输出**没法像图片分类那样直接算对错**——分类任务里「这张图是猫」一目了然，而「这段回答好不好」需要一个参照。

所以只能**事先备好题目和答案，再拿系统实际输出去比对**。这份预备好的题目集，就是金标。

---

## 2. 一条 case 里有两种「答案」

**【代码】** 本项目一条 case 的结构（`tests/fixtures/golden_test_set_*.json` 的 `test_cases[]`）：

```json
{
  "query": "怎么设置止损？",
  "ground_truth": "在订单窗口的 Stop Loss 字段填入价格...",   // ← 答案 ①
  "expected_chunk_ids": ["chunk_A", "chunk_B", ...],         // ← 答案 ②
  "expected_sources": [...],
  "tags": [...]
}
```

**这两个都叫「答案」，但完全是两回事**：

| | 是什么 | 回答的问题 | 答案册比方 |
|---|---|---|---|
| **① `ground_truth`** | 答案**文本** | 「这题该怎么答」 | 答案册上写的答案 |
| **② `expected_chunk_ids`** | 应被检索到的**片段编号** | 「答这题该翻到哪几页」 | 旁注「依据见课本第 37、82、105 页」 |

> ⚠️ **本文（以及本项目其他文档）说「标准答案」时，绝大多数指的是 ②**。这是个历史遗留的含混用词——严格说应该叫**「期望片段」**。看到「标准答案是 dense 检索挑的」这类句子，指的一定是 ②，**不是** ①。

---

## 3. 两种答案喂给两组不同的指标

这解释了本项目 8 项指标为什么天然分成两组：

| 指标组 | 消费什么 | 量的是什么 |
|---|---|---|
| `custom__hit_rate` / `mrr` / `recall` / `ndcg` | **② `expected_chunk_ids`** | **检索**准不准——翻到的页码对不对 |
| `ragas__context_recall` / `context_precision` / `faithfulness` / `answer_relevancy` | **① `ground_truth`** + 实际检索到的上下文 + 系统生成的回答 | **生成**好不好——答得对不对、有没有编 |

> 💡 这直接解释了 CLAUDE.md 里那条反复被提起的记录：**`custom__recall` 与 `ragas__context_recall` 量的不是一回事**（实测同一批结果 **0.30 vs 0.83**）。
>
> 前者比对**片段编号的重合率**，后者判**上下文对答案的支撑度**——一个查 ②，一个查 ①，**本来就不该相等**。把它们的差值当成异常去排查，是白费功夫。

---

## 4. 最脆弱的一环：期望片段谁来定

① `ground_truth` 由 RAGAS 的 `TestsetGenerator` 合成、再经 `refine_testset.py` 人工/半自动精修——**两代之间从没变过**。

争议全在 **② `expected_chunk_ids`**。

理想做法是**人工逐条标注**：每道题请人通读候选片段，判断哪些真的相关。但本项目语料有 **5 万多条 chunk**，这个成本不现实。

所以只能**机器生成**。

> ⚠️ **这是整个评估体系里最脆弱的一环**：**编答案册的方式，会偷偷决定谁得高分。**
>
> 本项目所有「指标在撒谎」的发现——重排明明做对了指标却跌、HyDE 分数会结构性虚高——**根源全在这里**（见 §9）。

「怎么机器生成」的两种不同答案，就是本项目的**两代标注方式**。

> **注意「代」的含义**：不是「文件改了第二版、订正了错字」，而是**换了一整套编答案册的方法**。同一批题目（`query` 与 `ground_truth` 基本没动），只是 ② 被重新定过了。

---

## 5. 第一代：`dense-top-k`

**【代码】** 名字来自常量 [`eval_runner.py:88`](../../src/observability/evaluation/eval_runner.py)：

```python
LABELING_METHOD_DENSE_TOP_K = "dense-top-k"
"""第一代金标的标注方式:``backfill_chunk_ids.py`` 用纯 dense top-K 回填。

第一代金标文件里**没有** ``_labeling_method`` 字段,所以缺失即视为这一代。
"""
```

### 逐词拆解

| 词 | 含义 |
|---|---|
| **dense** | **稠密向量检索**——把文本转成一串数字（向量），比较向量的接近程度。本项目走 ChromaDB |
| **top-k** | **取最相似的前 k 个**。本项目 k = 5（`backfill_chunk_ids.py` 的 `--top-k` 默认值） |

> 对照：`dense` 的反面是 `sparse`（稀疏检索），即 BM25 那种数关键词出现次数的老办法。本项目两路都有，融合权重 `dense=1.0 / sparse=0.1`。

**连起来读：「用稠密向量检索，取前 5 个」。**

### 做法

**【代码】** [`backfill_chunk_ids.py`](../../scripts/backfill_chunk_ids.py) 的 `_backfill_one`，docstring 写得很直白：`Embed ground_truth + query vector store`。

```
ground_truth（真答案）→ 编码成向量 → dense 检索 top-5 → 这 5 条即期望片段
```

（另有 `--threshold` 默认 0.6 的余弦相似度下限，低于则丢弃。）

### 它的致命弱点

简单、便宜、可复现。**但隐含一个假设：「embedding 认为最像答案的 5 条」= 「正确答案」。**

这叫**检索器锚定（retriever-anchored）**——**期望片段本身就是某一个检索器的输出**，等于让运动员自己当裁判。后果见 §9。

---

## 6. 第二代：`pooled-llm-judged`

**【代码】** 名字来自 [`label_golden_chunks.py:69`](../../scripts/label_golden_chunks.py)：`LABELING_METHOD = "pooled-llm-judged"`

### 逐词拆解

| 词 | 含义 |
|---|---|
| **pooled** | **池化**——让多个检索方法各交一份候选名单，取**并集**成一个「候选池」 |
| **llm-judged** | **由 LLM 判定**——逐条读、逐条打分，而不是靠排名截断 |

### `pooled` 这个词有来头 **【文献】**

**pooling 是信息检索领域几十年的标准做法**，出自 **TREC**（Text REtrieval Conference，美国 NIST 主办的检索评测会议，1992 年至今）。

TREC 的原始流程：

```
参赛的 N 个检索系统 → 各交前 100 个结果 → 取并集成「池」
                    → 只对池里的文档请人工评审员判定相关性
```

**为什么要池化**：语料有几百万篇，不可能全部人工判。但如果只用**一个**系统的结果去判，标准答案就被那个系统绑架了——**它没召回的东西，永远不会被标成「相关」**。多路取并集能大幅降低这种偏差。

**本项目第二代做的就是 TREC pooling**，只是换了两个零件：

| | TREC 原版 | 本项目 |
|---|---|---|
| 池子来自 | N 个参赛系统 | dense / sparse / rerank **三路** |
| 谁来判 | **人工**评审员 | **LLM**（打 0-3 分） |

> 💡 **`llm-judged` 这半截，正是它相对 TREC 打的折扣**——省了人力，但引入了判定模型自己的偏好。这就是 §11 那条局限的由来。

### 做法

```
query（不是答案！）→ dense / sparse / rerank 三路各取 top-N
                  → 取并集（池化）
                  → LLM 逐条判 0-3 分相关度
                  → 达标的入选
```

> **「用 query 而不是 ground_truth」是与第一代的关键差异**。归档变更的 `design.md` 说得很清楚：
>
> > "旧脚本用 `ground_truth`（答案）去检索，那是「找像答案的段落」；评估时系统面对的是 query。用 query 池化才能覆盖「真实检索会看到的候选空间」。"
>
> `ground_truth` 仍然用——**作为判定时给 LLM 的参考答案**，而不是检索输入。

### 多出来的 `_chunk_labels` **【实测】**

第二代金标每条 case 会多一个 `_chunk_labels` 数组，逐条记录判定过程：

```json
{
  "chunk_id": "...MetaTrader5SDK_English.chm_5353_...",
  "grade": 3,
  "reason": "The passage directly states that...",
  "contributed_by": ["sparse"],     // ← 这条是 sparse 捞出来的
  "judge_failed": false
}
```

注意 `contributed_by: ["sparse"]`——**这条 grade 3（最相关）的片段，纯 dense 根本看不到。**

**【实测】** 中文实测两代标签 Jaccard 仅 **0.328**，被接受的 72 条里 **22 条（31%）是纯 dense 结构上看不到的**。

> `judge_failed` 单独存在，是因为本项目坚持**「解析失败」必须与「判定为否」严格区分**——兜底成 0/false 会让解析 bug 伪装成「语料里没有相关内容」，产出一份看起来正常、实际全空的金标。首轮标注 234 次判定几乎全失败，正是靠这个设计一眼看出来的。

文件层面还会写一个 `_labeling_metadata`，含 `route_contributions` / `pool_size_mean` / `accepted_count` / `judge_failed_count` / `labeling_llm_identifier` / `synthesis_llm_identifier` / `mean_dense_jaccard` / `warnings` 等审计字段【实测】。

---

## 6.5 金标是怎么造出来的：完整流水线

前面讲的是「两代的差别」，这一节讲**整条生产线**——从零到一份可用金标，要跑几个脚本、每步产出什么。

### 全景

```
语料（已摄入 ChromaDB + BM25）
   │
   ├─ ① synthesize_testset.py ──→ candidates/<lang>.json
   │     RAGAS 合成 (question, ground_truth)         【出题】
   │
   ├─ ② refine_testset.py ──────→ golden_test_set_<lang>.json
   │     逐条精修，淘汰坏题                          【审题】
   │     ⚠️ 此时还没有 expected_chunk_ids
   │
   ├─ ③ 标注期望片段（二选一）
   │     ├─ backfill_chunk_ids.py   → 第一代 dense-top-k
   │     └─ label_golden_chunks.py  → 第二代 pooled-llm-judged
   │
   ├─ ④ 人工抽检（仅第二代）
   │     --export-sample → 人工填 → --import-sample
   │
   └─ ⑤ evaluate.py  用它评估检索系统
```

**要点：题目（①②）和期望片段（③）是两个独立阶段。** 两代之争只发生在 ③——①② 的产物两代共用。

---

### ① 合成候选 —— `synthesize_testset.py`

**【代码】** 用 RAGAS 的 `TestsetGenerator` 从已摄入语料反向生成题目：

```bash
python -u scripts/synthesize_testset.py --collection default_text-embedding-v4 --lang en
```

| 参数 | 默认 | 作用 |
|---|---|---|
| `--target-count` | 100 | 生成多少条候选 |
| `--distribution` | `0.5:0.3:0.2` | 难度分布 |
| `--chunk-sample-size` | — | 从语料抽多少 chunk 当素材 |
| `--source-filter` | — | 限定来源文档 |

难度分布对应 RAGAS 的三种「进化」类型【代码】：

| 类型 | 占比 | 含义 |
|---|---|---|
| `simple` | 0.5 | 单跳，答案在一个 chunk 里 |
| `reasoning` | 0.3 | 需要推理 |
| `multi_context` | 0.2 | 需综合多个 chunk |

**产出**：`tests/fixtures/candidates/<lang>.json`，含 `question` + `ground_truth`。

> ⚠️ **中文在这一步有个大坑**。RAGAS 内部 prompt 全是英文，生成中文测试集必须先调 `generator.adapt(language=chinese)` 把 prompt 模板翻译过去。而本项目 2026-08-14 实测发现：**adapt 不抛异常地「成功」了，产出的五个「中文」prompt 文件里一个中文字符都没有**，还被永久固化进了磁盘缓存（`logs/ragas_adapt_cache/`）。于是后续任何合成都读到英文 prompt，47 条候选里 33 条因语言不匹配被丢。
>
> 这是本项目反复撞见的同一类病：**看起来生效、实际没生效、而且不报错**。在途变更 `expand-chinese-golden-set` 正在修。

---

### ② 精修 —— `refine_testset.py`

合成出来的题目质量参差：有的答案在语料里根本找不到依据，有的问题本身有歧义。这一步淘汰坏题。

**两种模式**：

**默认（交互式）** —— 逐条 prompt `y/e/d/s/q`（保留 / 编辑 / 丢弃 / 跳过 / 退出）。单语种人工耗时 30-60 分钟。

**`--auto-mode`（Feature-003）** —— LLM 预筛 + borderline 路由，目标 ≤ 15 分钟：

```
每条候选 → screening_llm 判 keep/drop + 置信度
   ├─ keep 且置信度 ≥ 0.90  → 自动保留
   ├─ drop 且置信度 ≥ 0.80  → 自动丢弃
   └─ 其余                  → borderline，交人工
最后再抽 10% 自检，合规率需 ≥ 0.90
```

**【代码】** 阈值全在 `config/settings.yaml` 的 `evaluation.screening_llm`：`keep_threshold: 0.90` / `drop_threshold: 0.80` / `sample_ratio: 0.10` / `compliance_gate: 0.90`。

#### 这里的「置信度」是什么

**【代码】** 它是**预筛模型自己在 JSON 里报的一个 0~1 数字**——[`testset_screener.py:61`](../../src/observability/evaluation/testset_screener.py) 直接要求模型按这个格式输出：

```json
{"decision": "keep|drop|borderline", "confidence": 0.0, "reason": "one sentence"}
```

读作**「模型对自己这个判断有多大把握」**：0.95 ≈「这题明显该留」，0.6 ≈「我也拿不准」。程序拿它当**闸门**——够高就自动执行，不够高就转人工（`testset_screener.py:599`）。范围不在 [0,1] 或解析不出，整条降级为 borderline，**不兜底成 0**（同 §6 `judge_failed` 的思路）。

> ⚠️ **它不是概率，也没有绝对刻度**。没人验证过「标 0.9 的判断是否真有 90% 正确」——那只是模型生成的一个数，A 模型的 0.9 可能相当于 B 模型的 0.75。**【推断】**
>
> **这正是下面那条「阈值需要校准」的根本原因**：阈值不是绑在任务上，而是绑在**那一个具体模型**上。本项目里同类情形一共四处（换 `judge_llm` 的验收阈值、换 `screening_llm` 的 `keep_threshold`、换 `labeling_llm` 的 `relevance_threshold`、换 embedding 的相似度门限），根因都是同一个。

> ⚠️ **阈值需要校准**。默认值是初始猜测，不同模型的置信度标度不可互换。校准办法：跑一轮看 `_review_metadata.borderline_ratio`——远高于 20% 说明阈值太严，接近 0% 说明太松。

**产出**：`tests/fixtures/golden_test_set_<lang>.json`，`version` 写死 `v1.0`（中断则 `v0.9-partial`）【代码 `refine_testset.py:269`】。

> **此时 `expected_chunk_ids` 还是空的**——只有题目和答案，没有「该翻到哪几页」。

---

### ③ 标注期望片段 —— 两代分岔点

#### ③a 第一代：`backfill_chunk_ids.py`

```bash
python -u scripts/backfill_chunk_ids.py --input <golden> --collection <c>
```

| 参数 | 默认 | 作用 |
|---|---|---|
| `--top-k` | **5** | 取 dense 前几名 |
| `--threshold` | **0.6** | 余弦相似度下限，低于则丢弃 |
| `--dry-run` | — | 只打印不写文件 |

机制见 §5。**该脚本刻意保留**——它是第一代金标的可复现来源，删了就无法重现历史基线是怎么来的。但 docstring 顶部已标注警告：**新标注请用 `label_golden_chunks.py`**。

#### ③b 第二代：`label_golden_chunks.py`

```bash
python -u scripts/label_golden_chunks.py \
    --input  tests/fixtures/golden_test_set_en.json \
    --output tests/fixtures/golden_test_set_en_v2.json \
    --collection default_text-embedding-v4
```

**【代码】** 池化与判定参数在 `config/settings.yaml` 的 `evaluation.labeling`：

| 配置 | 当前值 | 说明 |
|---|---|---|
| `pool_top_n_dense` | 20 | dense 路取多少进池 |
| `pool_top_n_sparse` | 20 | sparse 路取多少进池 |
| `pool_top_n_rerank` | **0** | 0 = 不启用（重排依赖是 optional extra，默认置 0 保证核心安装即可标注） |
| `relevance_threshold` | **2** | ≥ 此值纳入。分级：**0 无关 / 1 沾边 / 2 部分支撑 / 3 直接回答** |
| `max_judgements` | 2000 | 调用上限，达到即停并记录被跳过数（**不静默截断**） |

**三路并集去重后每条 case 约 25-40 个候选**；中英 48 条 case 约需 **1200-1900 次** LLM 判定调用。

> ⚠️ **至少两路必须 > 0**，启动期强制校验。只配一路会让那条路径「永远全对」，等于把第二代方法**静默退化成第一代**。

**三条内建告警**【代码】——它们守的是「新方法到底有没有起作用」：

| 告警 | 阈值 | 触发含义 |
|---|---|---|
| `judge_failure_warn_ratio` | 0.10 | 判定解析失败率过高 |
| `dense_overlap_warn` | 0.90 | **与纯 dense top-5 的 Jaccard 太高 → 池化或判定疑似没生效** |
| `human_agreement_warn` | 0.80 | 人工抽检一致率过低 |

**`--dry-run`** 只池化不判定（零成本），可用来先看候选池规模。

---

### ④ 人工抽检（仅第二代）

**这是判定可信度的闸门**，不是可选步骤：

```bash
# 导出 20 条待检
python -u scripts/label_golden_chunks.py --input <v2> --export-sample 20 --sample-out sample.json
# 人工在 sample.json 里填 human_label，然后导回
python -u scripts/label_golden_chunks.py --input <v2> --import-sample sample.json
```

> ⚠️ **本项目至今没跑过真人抽检**——做的是跨模型盲评（见 §11）。`human_agreement_rate` 仍是 `null`。

---

### 贯穿全程的异源约束

**【代码】** 三个 LLM 角色，配置在 `config/settings.yaml` 的 `evaluation.*`：

| 角色 | 干什么 | 当前模型 | 异源要求 |
|---|---|---|---|
| `judge_llm` | ① 合成端 + RAGAS 评估裁判 | `glm:minimax/minimax-m2.7` | — |
| `screening_llm` | ② 预筛 | `glm:z-ai/glm-5.2-free` | **必须 ≠ judge** |
| `labeling_llm` | ③b 标注 | `glm:z-ai/glm-5.2-free` | **必须 ≠ judge** |

**为什么**：题目是 `judge_llm` 出的，再让它自己判「这题好不好」「这个片段相不相关」，就是自己批自己的作业。

**判据是完整标识串 `<provider>:<model>` 相等**，不是 provider 相等——实测 judge 标识为 `glm:minimax/minimax-m2.7`，provider 名义是 glm 但模型经 OpenAI 兼容端点路由到 minimax。只比 provider 会把真正异源的误判成同源。

> 注意 `screening_llm` 与 `labeling_llm` **用的是同一个模型但拆成两份配置**——因为「这条 case 该不该留」与「这个 chunk 相关到什么程度」是两个不同的判定任务，共用一份配置会让两处的阈值校准互相干扰。
>
> 选 `glm-5.2-free` 的理由也很实际：**异源成立 + 走免费额度**。标注要发上千次调用，**成本是这个环节最大的实际约束**。

### 退出码约定（③b 与 ②`--auto-mode` 共用）

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 输入错误（文件 / JSON / collection） |
| 2 | 前置条件不满足（LLM 未配置 / 与合成端同源 / 无法确认异源） |
| 3 | 判定模型**整体不可用**（凭据、网络、模型下架） |
| 130 | 中断。**文件仍会写出**并标 partial，已完成的判定不丢 |

> **码 3 与「模型通但输出不合格」严格区分**：后者会全部降级 borderline 交人工，不是失败。

> ⚠️ **所有脚本务必加 `-u`**。stdout 在管道下是全缓冲的，不加会看到空输出并误判成「进程卡死」——本项目为此误杀过两个正常运行的评估进程。

---

## 7. 两代对照

| | **第一代** | **第二代** |
|---|---|---|
| **`_labeling_method`** | **`dense-top-k`**（字段缺失即视为此代） | **`pooled-llm-judged`** |
| 生成脚本 | `backfill_chunk_ids.py` | `label_golden_chunks.py` |
| 伴随的 `version` 值 | `v1.0` | `v2.0` |
| **拿什么去搜** | `ground_truth`（**答案**） | `query`（**问题**） |
| **候选来自** | 只有 dense 一路 | dense ∪ sparse ∪ rerank |
| **谁决定入选** | 排名前 5 就入选 | LLM 读完打 0-3 分 |
| **每条数量** | 恰好 5（en：42 条 × 5 = 210） | 不固定（英文那份首条 **19** 条） |
| 额外字段 | 无 | `_chunk_labels` + `_labeling_metadata` |
| **致命弱点** | 期望片段 = dense 的输出（检索器锚定） | LLM 的偏好未经真人校准 |

### 为什么分数不可跨代比较

因为**「期望片段」的定义变了**。同一套检索代码在第一代金标上得 0.49、在第二代上得 0.61，**不代表检索变好了，只代表尺子换了**。

所以评估报告会标 `delta_comparable: false`。**换代后必须重标基线。**

---

## 8. 三个长得像版本号的东西

**【代码】** 这是实践中最容易搞混的地方——项目里有三样都像版本号，**只有第三样是判据**：

| # | 东西 | 例子 | 谁写的 | 是代次判据吗 |
|---|---|---|---|:---:|
| 1 | **文件名后缀** | `golden_test_set_zh_v3.json` | 人手起的 | ❌ 表示「第几个**文件**」 |
| 2 | **JSON 的 `version`** | `"version": "v1.0"` | 脚本**硬编码** | ❌ 仅供人读 |
| 3 | **`_labeling_method`** | `"pooled-llm-judged"` | `label_golden_chunks.py` | ✅ **唯一判据** |

第 2 项是死值【代码】：
- `refine_testset.py:269` → `"version": "v1.0" if not partial else "v0.9-partial"`
- `label_golden_chunks.py:620-625` → 写 `"v2.0"` + `_labeling_method`

第 3 项才是代码读的东西（`eval_runner.py:88-94`，见 §5）。

### 一个能说明问题的实例 **【实测】**

`golden_test_set_zh_v3.json`：

| | 值 | 含义 |
|---|---|---|
| 文件名 | `_v3` | 第 **3 个**中文金标**文件** |
| `version` | `v1.0` | `refine_testset.py` 的硬编码默认值 |
| `_labeling_method` | **缺失** | → 代码判定为**第一代标注** |

**看起来自相矛盾，实际完全正确**：它是刚 refine 完、还没跑第二代标注的中间产物。

> 💡 **所以本项目文档一律用标注方式名（`dense-top-k` / `pooled-llm-judged`）指代两代，不用「v1/v2」。**
> 说「v2 金标」时，读者无法判断你指的是文件名、`version` 字段、还是标注方式——而这三者会打架。
> 而看到 `dense-top-k`，你立刻知道「期望片段是 dense 检索挑的」——**名字自己会说话**。

### 两代划分定义在哪

**【代码】** 归档变更 `openspec/changes/archive/2026-08-14-retriever-agnostic-golden-labels/design.md` 的 **D9**：

> "两代金标的区分靠 `version` + 新增 `_labeling_method` 字段：现有金标 `version: "v1.0"`，新产出用 `v2.0` 并带 `_labeling_method: "pooled-llm-judged"`；第一代回填标 `"dense-top-k"`。报告侧读这两个字段判定可比性。"

**这是项目自己的定义，不是行业术语。** 别的 RAG 项目不会有「两代金标」这个说法。

---

## 9. 两代的偏向：一把有立场的尺子

**这是本文最重要的一节**，也是 §4 那句「编答案册的方式会偷偷决定谁得高分」的具体展开。

### 情形一：`dense-top-k` 结构性**惩罚**重排 **【实测】**

- 期望片段 = 「embedding 认为最像答案的那几条」
- 而重排的全部工作 = **不同意 dense 的排序**

于是四项 custom 指标**结构上不可能给重排打出正分**：

| | 结果 |
|---|---|
| 英文 42 条 MRR | 0.4914 → **0.3668** |
| 中文 6 条 MRR | 0.5833 → **0.4167** |
| 集成测试 | 同一模型**每次都能**把故意放在末位的相关段落提到首位 |

**模型在做正确的事，指标却在跌。**

> ⚠️ 这也推翻了另一条常见经验法则：CLAUDE.md 里「比较混合与单路时 MRR/nDCG 比 recall/hit_rate 可信」**只适用于 dense-vs-sparse 的路径比较**。对重排而言四项全是 dense-anchored 的，MRR/nDCG **并不更中立**。

### 插曲：`oracle` 是什么意思 **【文献】**

下面两小节反复出现这个词，先定义。

**oracle =「神谕 / 先知」，指在实验或标注环节拿得到、但真实查询时拿不到的正确信息。**

词源是计算理论里的 **oracle machine**（图灵 1939）：一台图灵机可以免费向一个「神谕」问某个子问题的答案，用来分析「假如这一步免费且必定正确，整体最好能做到什么程度」。到了检索与机器学习领域，它固化成一个修饰词：

| 说法 | 含义 |
|---|---|
| **oracle answer** | 真正的标准答案（本文的 `ground_truth`） |
| **oracle ranking** | 完美排序，指标的理论上限 |
| **oracle experiment** | 故意「开外挂」跑一遍，量这条路径的天花板 |

它**不含贬义**，是一个中性的**实验条件标记**，提醒读者：这个数字是在「手里已经有答案」的前提下拿到的，**线上没有这个前提**。

> **打个比方**（接 §1 的答案册）：出题老师手里有答案册，考生没有。**oracle 答案就是老师手里那一份。**

### 情形二：`dense-top-k` 结构性**奖励** HyDE **【推断】**

HyDE（Hypothetical Document Embeddings）的机制是：**让 LLM 编一段假想答案，拿它的向量去 dense 检索**。

对照第一代标注：**拿真答案的向量去 dense 检索**。

两条通路并排看，差别只在最左边那一格：

| | 向量从哪来 | 拿它做什么 |
|---|---|---|
| **第一代标注**（出题老师） | `ground_truth`——**oracle 答案**，标注时手里真有 | dense top-5 → `expected_chunk_ids` |
| **HyDE**（考生） | LLM 编的假想答案——没有 oracle，只能猜一个去逼近 | dense top-k → 检索结果 |

> **这两件事是同一个机制**，区别只是 oracle 答案 vs 猜测答案。
> **第一代金标的期望片段，恰好就是「答案向量的 dense 邻居」；而 HyDE 的全部工作就是逼近答案向量。**

**结论：用 `dense-top-k` 金标评 HyDE，分数会虚高**——不是检索真的变好，而是 HyDE 越成功就越接近金标的构造方式本身。

### 普适结论

| 改动 | `dense-top-k` 的偏向 | 后果 |
|---|---|---|
| **Cross-encoder 重排** | 结构性**惩罚** | 指标跌，但模型是对的 |
| **HyDE** | 结构性**奖励** | 指标涨，但涨的可能是假的 |

> 💡 **`dense-top-k` 金标不是中立裁判，它是「dense 检索 + oracle 答案」这一特定机制的化身。**
> **任何靠近该机制的改动都会被奖励，任何偏离的都会被惩罚。**
>
> 实践守则：**在换掉金标构造方式之前，不要用它去判断任何「敢改变名次」的改进。**

---

## 10. 本项目金标文件清点

**【实测】** 2026-08-15 清点 `tests/fixtures/`。「标注方式」一列才是判据，`version` 只是伴随值：

| 文件 | `version` | **标注方式** | 条数 | `_chunk_labels` | 状态 |
|---|---|---|---:|:---:|---|
| `golden_test_set.json` | — | — | — | ✗ | US1 占位 |
| `golden_test_set_en.json` | v1.0 | `dense-top-k` | 42 | ✗ | dense-anchored |
| `golden_test_set_zh.json` | v0.1-partial | `dense-top-k` | 6 | ✗ | 中断产物 |
| **`golden_test_set_en_v2.json`** | v2.0 | **`pooled-llm-judged`** | **41** | ✓ | ✅ **已就位**（> SC-002 的 ≥40） |
| `golden_test_set_zh_v2.json` | v2.0 | `pooled-llm-judged` | 6 | ✓ | ❌ 样本量不足 |
| `golden_test_set_zh_v3.json` | v1.0 | `dense-top-k` | 29 | ✗ | 🚧 在途，尚未二代标注 |

**要点**：
- **英文侧的第二代金标已达标**（41 条），任何需要中立裁判的 A/B **英文侧今天就能做**
- **中文侧被阻塞**，在途变更 `openspec/changes/expand-chinese-golden-set/` 正在扩充
- 末行正是 §8 的实例：文件名 `_v3` 但标注方式仍是第一代

> ⚠️ 另一条硬约束（CLAUDE.md）：**金标必须在含全部语料的集合上评估**（当前 `default_text-embedding-v4`），不要指向 `mt5_docs_{zh,en}` 分语言集合——中英金标存在跨语言匹配，分语言集合只能解析 190/210 个 chunk_id，会直接触发 `chunk_id_validation` 失败。

---

## 11. 已知局限与待办

| 局限 | 现状 | 影响 |
|---|---|---|
| **第二代的校准是「跨模型」而非「人工」** | 24 条三元组由 `claude-opus-5` 盲评，与 `glm:z-ai/glm-5.2-free` 一致率 **95.8%**（23/24）。元数据记 `cross_judge_agreement_rate`，**`human_agreement_rate` 仍是 `null`** | 两个判定方都是 LLM，**可能共享人类会发现的盲点**。重排 A/B 的翻转结论依赖这个前提 |
| **两代都没有机器可读的合成端标识** | 建于 2026-04-28，早于 Feature-003 的 `_review_metadata` | 异源检测返回 `UNVERIFIABLE`，只能靠 `--allow-same-source` 显式承担风险 |
| **中文样本量不足** | 6 条，SC-002 要求 ≥40 | 中文侧任何检索结论都只能当噪声看 |

**若第二代金标的任何结论被质疑，第一件该做的事是补真人抽检**——审阅表在 `tests/fixtures/labeling_review_zh.md`，可直接对照两方分歧。**别先去改检索代码。**

> **做交叉判定时务必盲评**（先藏掉原判定与理由），否则第二个判定方会倾向附和，算出的一致率没有校准价值。

---

## 附录：术语表

| 术语 | 含义 |
|---|---|
| **金标 / golden test set / gold standard** | 评估用的标准答案集。词源见 §1 |
| **`ground_truth`** | 答案**文本**（本文的「答案 ①」）。喂给 RAGAS 四项指标 |
| **`expected_chunk_ids`** | **期望片段**编号（本文的「答案 ②」）。喂给 custom 四项指标。**两代之争只关于它** |
| **dense** | 稠密向量检索（embedding 相似度）。本项目走 ChromaDB |
| **sparse** | 稀疏检索（BM25 关键词计数） |
| **top-k** | 取最相似的前 k 个。第一代 k=5 |
| **`dense-top-k`** | 第一代标注方式：拿 `ground_truth` 做 dense 检索取 top-5 |
| **pooling / 池化** | TREC 的经典做法：多路结果取并集成候选池，只判池内文档 |
| **`pooled-llm-judged`** | 第二代标注方式：多路池化 + LLM 打 0-3 分 |
| **oracle（神谕 / 先知）** | 标注或实验时拿得到、真实查询时拿不到的正确信息。**oracle 答案 = 真答案**（本项目即 `ground_truth`）。中性词，只是一个「这数字有外挂」的实验条件标记。详见 §9 插曲 |
| **HyDE（Hypothetical Document Embeddings）** | 查询改写策略：让 LLM 编一段**假想答案**，拿它的向量去 dense 检索。可视为「没有 oracle 时对 oracle 答案的逼近」 |
| **检索器锚定 / retriever-anchored** | 期望片段本身是某个检索器的输出，导致评估偏向该检索器 |
| **`_labeling_method`** | 金标 JSON 的字段，**代次的唯一判据**。缺失即视为 `dense-top-k` |
| **`delta_comparable`** | 评估报告字段。跨代比较时为 `false` |
| **`_chunk_labels`** | 第二代金标的逐条判定记录（`grade` / `reason` / `contributed_by` / `judge_failed`） |
| **TREC** | Text REtrieval Conference，NIST 主办的检索评测会议，1992 年至今 |
| **`judge_llm`** | 合成端 + RAGAS 评估裁判。当前 `glm:minimax/minimax-m2.7` |
| **`screening_llm`** | 精修阶段的预筛模型，**必须与 judge 异源** |
| **`labeling_llm`** | 第二代标注的判定模型，**必须与 judge 异源** |
| **置信度（本文顶部的标注约定）** | 挂在每条结论后的**来源标签**：【代码】/【实测】/【文献】/【推断】，从硬到软。人工标注，四档离散。见 [§置信度标注约定](#置信度标注约定) |
| **置信度（`confidence` 字段）** | 预筛/标注模型**自报**的 0~1 把握程度，程序拿它当自动化闸门。**不是概率、无绝对刻度、不可跨模型移植**。见 §6.5 ② |
| **borderline** | 预筛置信度不足、需转人工的候选。占比是阈值校准的观测指标 |
| **evolution / distribution** | RAGAS 合成的难度分布：simple / reasoning / multi_context |

---

## 相关文档

- [ragas-basics.md](ragas-basics.md) —— RAGAS 四项指标怎么算，以及它作为「金标合成器」的第二身份
- [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) —— §9 情形一的完整记录
- [query-rewriting-strategies.md](query-rewriting-strategies.md) —— §9 情形二的完整记录，以及查询改写的评估约束
- [tech-selection-llamaindex.md](tech-selection-llamaindex.md) —— 为什么这套评估体系是不迁移到框架的主要理由
- `openspec/config.yaml` § 已知陷阱 —— 项目硬约束的权威来源
- `openspec/changes/archive/2026-08-14-retriever-agnostic-golden-labels/` —— 两代划分的定义处
