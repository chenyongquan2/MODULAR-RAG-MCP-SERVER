# RAG 质量验收方案（RAGAS + 自合成数据集）

> **文档性质**：RAG 系统质量验收的可执行方案，2026-04-22 创建。
> **适用对象**：执行本方案的开发者或 AI 助手。新的对话/Session 可以从此文档开始，无需依赖历史上下文。
> **配套文档**：[docs/ragas-guide.md](ragas-guide.md) 提供了 RAGAS 指标的理论与 FAQ，本文档专注"如何做一次完整验收"。

---

## Context（为什么做这件事）

**项目现状**（截至 2026-04-22）：
- RAG 评估代码已完整实现（4 个 RAGAS 指标 + Hit/MRR/Recall/NDCG 检索指标），最近两个提交 `a999a20` 和 `7a87eec` 把框架打磨得较成熟。
- 当前 [tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json) 仅有 **4 条样例用例**，且 `expected_chunk_ids` 是 `chunk_azure_001` 这类占位符 ID，**与实际摄入的 MT5 文档的真实 chunk ID 不匹配**，跑出来的 Hit/MRR 一定是 0。
- [config/settings.yaml](../config/settings.yaml) 只启用了 `custom` backend，`ragas` 被注释掉。
- ChromaDB 已摄入 313MB 数据（MT5 中英文手册），存储在 `data/db/chroma/`。

**目标**：对现有 MT5 中英文 RAG 系统做一次完整的质量验收，产出可量化、可复用、可回归的评估基线。

**验收配置**（已与 owner 确认）：
- **语料范围**：中英双语都评估（MT5 中英文手册各一个 collection）。
- **数据集策略**：RAGAS TestsetGenerator 自动合成 + 人工精修（业内最佳实践，贴合自有语料）。
- **评估规模**：中等规模，中英各 40-50 条，合计 80-100 条。
- **评估维度**：4 个 RAGAS 指标全开 + 保留 custom 检索指标，**GLM-4 作为 Judge LLM**。

**关于"没有专业数据集"这个顾虑**：业内没有能直接套用的"第三方专业 RAG 测试集"能覆盖 MT5 这种垂直领域。公开数据集（RGB/CRUD-RAG/MS MARCO/DuReader 等）的语料与你的文档不匹配——即使引入，也要先把它们的语料摄入进来才有意义，那本质上就是"换一个领域重跑一遍"。**RAG 验收的核心是"在自己的语料上评"，而自己的语料上的评估集只能自己造**。业内标准做法是 RAGAS TestsetGenerator 自动合成 + 人工精修关键条目。

---

## 方案总览

```
[Step 0] 准备：开启 RAGAS backend、配置 GLM-4 judge、确认数据已摄入
   ↓
[Step 1] 合成测试集：RAGAS TestsetGenerator 分别从中/英集合各生成 80-100 条 (question + ground_truth)
   ↓
[Step 2] 人工精修：抽样 20-30 条校对、修正明显错误的 ground_truth、删除坏样本
   ↓
[Step 3] 写回 golden_test_set.json：填充真实的 expected_chunk_ids（从 ChromaDB 反查）
   ↓
[Step 4] 执行评估：custom + ragas 全开，GLM-4 judge，跑一遍基线
   ↓
[Step 5] 解读报告 + 标记基线：通过 Dashboard 固定基线，后续每次改进对比 delta
   ↓
[Step 6]（可选）横向对照：在 RGB 中文小样本上跑一次，观察系统在不同语料上的能力差
```

---

## 评估架构：双层视角（重要的心智模型）

> **2026-04-25 增补**：本节解释为什么本方案的"自合成 + 人工精修"测试集是必然选择、为什么 Step 6 公开 benchmark 是"可选但有价值"、以及为什么 [Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 的 FR-014/FR-015 要求测试集打 `tags`。如果你只是要执行一次验收，可以跳过本节直接看"详细步骤"；如果你想理解"评估架构在系统生命周期中如何演进"，本节是核心。
>
> **前置概念**：本节假设你已理解"语料 vs Golden Test Set"的区别 + RAGAS 输入数据流。若不熟悉，先读 [docs/ragas-guide.md § 1.4 RAG 语料 vs Golden Test Set](ragas-guide.md) 与 [§ 1.5 RAGAS 的输入与评估对象](ragas-guide.md)。

### 1. 为什么不存在"通用万能 RAG 测试集"

RAG 系统的实际效果是 `f(语料, 查询类型, 下游使用场景)` 三个变量的乘积。公开数据集（MS MARCO / HotpotQA / 等）只能模拟"通用语料 × 通用查询"，跟你的真实业务场景永远错位。

举个例子：你想测"我的 MT5 RAG 好不好用"，但 MS MARCO 的题目基于 Bing 搜索 + Web 文档，跟 MT5 手册没有任何关系——拿 MS MARCO 的题目问你的 RAG，几乎必然 100% 答错（因为你的语料里压根没那些内容）。反过来，把 MS MARCO 的语料**额外摄入**到你的系统再评估，本质等于"换一个领域重跑一遍"，对你的 MT5 业务效果一无所知。

**结论**：追求"一份通用集量我所有 RAG 项目"在逻辑上不成立。

### 2. 工业界的解法：双层评估架构

把"评估"拆成两个独立的层，分别承担不同职责：

```
┌──────────────────────────────────────────────────────────┐
│  Layer A: 业务回归层（演进的）                              │
│  ──────────────────────────────────                       │
│  目的：评估"我当前业务上系统好不好"                          │
│  数据：业务专属 golden set（自合成 + 人工精修）              │
│  生命周期：跟文档一起演进 v1 → v2 → v3                      │
│  本项目：本方案 Step 0~5 + Feature-001 全部围绕这层          │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Layer B: 能力诊断层（基本不变的）                           │
│  ──────────────────────────────────                       │
│  目的：评估"我系统的零部件能力在标准基准下处于什么水平"        │
│  数据：公开 benchmark（按能力维度选）                        │
│  生命周期：文档怎么变这层都不变（除非升级 retriever 算法本身）│
│  本项目：本方案 Step 6（可选）+ 未来独立 feature             │
└──────────────────────────────────────────────────────────┘
```

**Layer A 与 Layer B 不互相替代，是互补关系**：

| 你想知道的问题 | Layer A | Layer B |
|------|---------|---------|
| 我的 MT5 业务 RAG 效果怎样 | ✅ 唯一权威 | ❌ 不能告诉你 |
| 我的检索器多跳推理能力如何 | ❌ 看不出 | ✅ HotpotQA 能告诉你 |
| 我的系统对表格 QA 鲁棒吗 | ❌（除非业务集恰好有表格题） | ✅ TabFact 能告诉你 |
| 文档变了之后老能力有没有退化 | ✅ 重跑 v1 子集 | ❌ |
| 我跟业内 SOTA 差多少 | ❌ | ✅ |

### 3. Layer B 的能力维度数据集清单（按需选用）

只要你想测某种"组件能力"，几乎都有对应的公开 benchmark：

| 想测的能力 | 推荐 benchmark | 备注 |
|------------|----------------|------|
| 表格 QA | WikiTableQuestions / TabFact / FinQA | 加表格内容前先跑一次拿基线 |
| 代码 QA / 检索 | CodeSearchNet / CoSQA / HumanEval-Pack | 加代码内容时用 |
| 多跳推理 | HotpotQA / 2WikiMultihopQA | 测复杂 query |
| 长文档 | NarrativeQA / QuALITY / LongBench | 测 chunk 跨段拼接 |
| 抗噪声 / 反事实 / 拒答 | RGB（同济，中英双语，4 档难度） | 测系统鲁棒性 |
| 中文 RAG 综合 | DuReader / CRUD-RAG / CMRC2018 | 中文场景 |
| 检索器纯能力 | MS MARCO / BEIR（18 个子集） | 不含 generator |

**Layer B 跑法**：把 benchmark 的语料**临时摄入到独立 collection**（例如 `benchmark_rgb`），跑同样的评估管线，得分作为系统的"能力指纹"。文档形态变化前后这层指标**不应该明显变动**——因为它测的不是业务，是组件能力。

### 4. Layer A 的核心难题：测试集如何"演进"

业务文档不会一成不变。MT5 文档今天可能是纯文本（A 状态），明年可能扩展到含代码段、含表格（B 状态）。如果每次文档变了就**全部废弃旧测试集重新合成**，会同时丢两样东西：
- **历史回归能力**：没法判断"老题指标退步"是因为新文档加进来污染了，还是 retriever 本身退化
- **沉没的人工精修成本**：每条用例的人工 review 成本很高，重做一遍亏本

**正确做法（业界标准）**：增量演进 + 维度切片。

#### 4.1 测试集 schema 加 tags

每条用例打**多维标签**（[Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 的 FR-014）：

```json
{
  "query": "如何在 MT5 中执行限价单？",
  "ground_truth": "...",
  "expected_chunk_ids": ["..."],
  "tags": {
    "content_type": "text",          // text | code | table | mixed
    "difficulty": "simple",          // simple | reasoning | multi_context
    "language": "zh",
    "doc_version": "v1"              // 关键：标注题目所属的文档版本
  }
}
```

#### 4.2 文档扩展时的增量做法

文档从 A → B 时，**v1 全部保留**，**只增量补 v2**：

```
v1.json  (40 条 text 题)               ← 保留不动
v2.json  (10 条 code 题 + 8 条 table 题)  ← 新增

最终金标 = v1 ∪ v2 = 58 条
```

#### 4.3 评估时按 tag 切片看分数（[Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 的 FR-015）

不要只看总分，要按 tag 维度切片定位短板：

```
ragas__faithfulness:
  全集     = 0.82
  ├─ content_type=text   = 0.85   ← 跟 v1 历史比，没退化
  ├─ content_type=code   = 0.71   ← 新能力，刚达标
  └─ content_type=table  = 0.65   ← ⚠️ 新能力，待优化
```

#### 4.4 双重红线：历史回归 + 新能力达标

文档每次扩展时跑两次评估，对应两条独立验收红线：

| 红线 | 测什么 | 跑哪份测试集 | 评估规则 |
|------|--------|--------------|----------|
| **历史回归** | 老能力别退化 | `tags.doc_version=v1` 子集 | 与 v1 时代基线对比，每个指标 delta ≥ -0.02 |
| **新能力达标** | 新内容能 hold | `tags.doc_version=v2` 增量子集 | 每个指标 ≥ Layer B 对应能力的"合格"水位 |

这就是 [Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) **SC-008** 要求的"v1 子集重跑 delta ≥ -0.02"的来源。

### 5. 一句话总结

| 你以为你在找 | 你真正需要的 |
|---|---|
| 一份通用数据集量我所有 RAG 项目 | 一套**评估架构**，让业务集能演进、能力集能补充 |
| 文档变了测试集就失效 | 让测试集**增量演进 + 维度切片**，老题留下做回归，新题专测新能力 |
| 用 RAGAS 跑一次给我个全局分数 | 用 RAGAS 跑**按 tag 切片**的分数矩阵，定位能力短板 |

> **金句**：测试集的"通用性"不在题目本身能跨业务，而在**评估架构能跨版本**。

### 6. 与本方案 Step 0~6 的对应关系

- **Step 0~5（本方案核心）= Layer A 第一次落地**：用 MT5 v1 文档建业务测试集 v1。本节"4.1 tags schema"在合成阶段就要落到 `golden_test_set_zh.json` / `golden_test_set_en.json`，本节"4.3 切片聚合"在 [src/observability/evaluation/eval_runner.py](../src/observability/evaluation/eval_runner.py) 的报告聚合阶段落地。
- **Step 6（可选）= Layer B 第一次启动**：选 RGB 中文小样本做"能力指纹"对照。建议作为独立 feature 启动，不在本方案 MVP 强求。
- **未来 v2 文档扩展**：按本节 4.2~4.4 的增量做法操作，v1 题留下做历史回归，新增 v2 题专测新内容类型。

---

## 详细步骤

### Step 0：环境与配置准备

**0.1 安装 RAGAS 依赖**

`pyproject.toml` 中已有可选依赖组，确认 ragas/datasets 已装：
```bash
pip install "ragas>=0.2" datasets langchain-openai
```

**0.2 修改 [config/settings.yaml](../config/settings.yaml)（evaluation 章节），开启 ragas backend**：
```yaml
evaluation:
  backends:
    - custom
    - ragas          # 解除注释
  golden_test_set: ./tests/fixtures/golden_test_set.json
```

**0.3 GLM-4 作为 RAGAS Judge**

RAGAS 内部依赖 `langchain` 的 LLM/Embeddings 对象。GLM 提供 OpenAI 兼容端点，可通过 `langchain_openai.ChatOpenAI` 包一层接入：

需要在 [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py) 中确认/补充一个 `_build_judge_llm()` 方法，从 `settings.llm` 读 GLM 配置并构造 `ChatOpenAI(base_url=..., api_key=..., model="glm-4")`，传给 `ragas.evaluate(llm=..., embeddings=...)`。

**关键文件**：
- [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py)（主要改动点，第 57-120 行 `evaluate()` 逻辑内配置 judge）
- [src/core/settings.py](../src/core/settings.py)（如需新增 `evaluation.judge_provider` 配置项则同步 dataclass，约第 168 行 `EvaluationSettings`）

**0.4 确认两个集合已摄入**

假设 MT5 中英文分别摄入到不同 collection：
```bash
python scripts/ingest.py --path ./tests/fixtures/chm/MetaTrader5SDK_Chinese.chm --collection mt5_zh
python scripts/ingest.py --path ./tests/fixtures/chm/MetaTrader5SDK_English.chm --collection mt5_en
```
（若已摄入到 `default` 则跳过，但强烈建议分 collection，便于独立评估中英。）

**0.5 烟雾测试**：先把现有 [tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json) 里的 `expected_chunk_ids` 改为 ChromaDB 中的真实 chunk UUID（任选几个），跑一次 `python scripts/evaluate.py --generate-answers --pretty`，确认 8 个指标都有数值、无 ValueError。这一步是验证 GLM-4 judge 接入是否正确，失败代价低。

---

### Step 1：合成测试集（主要工作量）

**1.1 新建脚本 `scripts/generate_testset.py`**

用 RAGAS TestsetGenerator 从已摄入的原始文档（不是 chunks，是源 Markdown/PDF 文本）生成 Q/GT 对。核心流程：

```python
from ragas.testset import TestsetGenerator
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.document_loaders import DirectoryLoader

# 复用项目 loader 拿到已摄入的源文档
docs = load_ingested_source_docs(collection="mt5_zh")

generator_llm = ChatOpenAI(base_url=GLM_BASE, api_key=GLM_KEY, model="glm-4-plus")
embeddings = existing_embedding_wrapper()  # 复用项目 embedding

generator = TestsetGenerator.from_langchain(generator_llm, embeddings=embeddings)
testset = generator.generate_with_langchain_docs(
    docs,
    testset_size=100,
    distributions={
        "simple": 0.5,          # 单点事实
        "reasoning": 0.3,       # 多跳推理
        "multi_context": 0.2,   # 需跨多段
    },
)
testset.to_pandas().to_json("tests/fixtures/raw_testset_zh.json", ...)
```

**中英各生成 100 条（目标精修后保留 80-100 条）**，产物是 `raw_testset_zh.json` 和 `raw_testset_en.json`。

**1.2 关键注意事项**：
- TestsetGenerator 会自己调 LLM，预估 100 条约 300-500 次 LLM 调用，GLM-4-plus 成本可控。
- 生成的 `ground_truth` 是 LLM 自产的，**会有幻觉和错误，必须人工过一遍**——这是"人工精修"不可省略的原因。
- RAGAS 0.2+ 的 TestsetGenerator API 若与示例不符，以 [RAGAS 官方文档](https://docs.ragas.io/) 为准，逻辑框架不变。

---

### Step 2：人工精修（1-2 小时）

**2.1 编写辅助脚本 `scripts/review_testset.py`**

CLI 交互式地逐条展示 `question` / `contexts`（生成时的原始片段）/ `ground_truth`，让你打标：`k`(keep) / `e`(edit ground_truth) / `d`(drop)。输出到 `reviewed_testset_{lang}.json`。

**2.2 精修原则**：
- 中英各保留 40-50 条，**总计 80-100 条**。
- 保留难度分布：简单事实题 50%、推理题 30%、跨段综合题 20%。
- 删除问题：问题歧义、ground_truth 明显错误、contexts 本身不包含答案。

---

### Step 3：回填 expected_chunk_ids

**3.1 问题**：RAGAS 指标只需 `ground_truth`，但项目的 custom 检索指标（Hit/MRR/Recall/NDCG）需要 `expected_chunk_ids`。

**3.2 做法**：新建 `scripts/backfill_chunk_ids.py`，对每条精修后的 `question`，执行一次稠密检索，把 Top-3 中**文本与 ground_truth 语义匹配**的 chunk_id 记为 expected。可以用 embedding 相似度 + ground_truth 做自动匹配，再人工校验。

**3.3 合并输出**：生成最终的 `tests/fixtures/golden_test_set_zh.json` 和 `golden_test_set_en.json`，schema 与现有格式一致：
```json
{
  "test_cases": [
    {
      "query": "...",
      "expected_chunk_ids": ["<real_chunk_uuid>"],
      "expected_sources": ["mt5_sdk_zh.md"],
      "ground_truth": "..."
    }
  ]
}
```

---

### Step 4：执行评估

**4.1 中文集合评估**
```bash
python scripts/evaluate.py \
  --test-set ./tests/fixtures/golden_test_set_zh.json \
  --collection mt5_zh \
  --generate-answers \
  --pretty > logs/eval_zh_baseline.json
```

**4.2 英文集合评估**
```bash
python scripts/evaluate.py \
  --test-set ./tests/fixtures/golden_test_set_en.json \
  --collection mt5_en \
  --generate-answers \
  --pretty > logs/eval_en_baseline.json
```

`--generate-answers` 会让 [scripts/evaluate.py](../scripts/evaluate.py) 自动调 `ResponseBuilder` 生成 answer，RAGAS 的 faithfulness/answer_relevancy 才有值。

**4.3 预期输出字段**（出自 [src/observability/evaluation/eval_runner.py](../src/observability/evaluation/eval_runner.py) 约第 187 行）：
```
aggregate_metrics:
  custom__hit_rate / custom__mrr / custom__recall / custom__ndcg
  ragas__faithfulness / ragas__answer_relevancy
  ragas__context_precision / ragas__context_recall
```

---

### Step 5：解读与基线标记

**5.1 启动 Dashboard** 查看可视化报告：
```bash
python scripts/start_dashboard.py
```
进入"评估面板"页 → 选中刚刚跑出的两份报告 → 点"Mark as Baseline"（走 [src/observability/dashboard/services/evaluation_service.py](../src/observability/dashboard/services/evaluation_service.py) 的 `mark_as_baseline`）。

**5.2 验收门槛参考**（行业经验值，按项目调整）：

| 指标 | 差 | 合格 | 良好 | 优秀 |
|---|---|---|---|---|
| custom__hit_rate | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| custom__mrr | <0.3 | 0.3-0.5 | 0.5-0.7 | >0.7 |
| ragas__context_precision | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| ragas__context_recall | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| ragas__faithfulness | <0.6 | 0.6-0.75 | 0.75-0.9 | >0.9 |
| ragas__answer_relevancy | <0.7 | 0.7-0.8 | 0.8-0.9 | >0.9 |

**5.3 诊断思路**（指标 → 问题定位）：
- `context_recall` 低 → 检索漏召回 → 调 top_k / 开启混合检索 / 检查 splitter
- `context_precision` 低 → 检索噪声大 → 开启 reranker / 调 RRF 权重
- `faithfulness` 低（但 context_recall 高）→ 生成器幻觉 → 改 prompt，强制引用
- `answer_relevancy` 低 → 生成答非所问 → prompt 里加入"直接回答问题"约束

---

### Step 6（可选）：横向对照

若想看你的系统在"外部难度基准"上的表现，**选一个小型公开中文 RAG 集**即可（**不用全跑**）：
- **RGB (同济大学)** — 专为 RAG 设计，中英双语，难度分 4 档。选它的"噪声鲁棒性"子集 50 条跑一次。
- **CRUD-RAG** — 涵盖增删改查四种 RAG 场景。
- **DuReader-retrieval** — 中文检索基准。

做法：把数据集的语料摄入到独立 collection（如 `benchmark_rgb`），按同样流程跑评估。**目的不是拿这个分数做验收**，而是看你的系统在标准难度下能到什么水平，反过来判断自合成集的难度是否合理。

---

## 关键文件一览

| 文件 | 动作 |
|---|---|
| [config/settings.yaml](../config/settings.yaml) | 开启 `ragas` backend |
| [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py) | 接入 GLM-4 judge（LangChain wrapper） |
| [src/core/settings.py](../src/core/settings.py) | 如需新配置项则扩展 `EvaluationSettings` |
| `scripts/generate_testset.py` | **新建**：RAGAS TestsetGenerator 合成脚本 |
| `scripts/review_testset.py` | **新建**：CLI 交互精修工具 |
| `scripts/backfill_chunk_ids.py` | **新建**：回填 expected_chunk_ids |
| `tests/fixtures/golden_test_set_zh.json` | **新建**：中文验收集（约 40-50 条） |
| `tests/fixtures/golden_test_set_en.json` | **新建**：英文验收集（约 40-50 条） |
| [scripts/evaluate.py](../scripts/evaluate.py) | 复用，无需改动 |
| [src/observability/evaluation/eval_runner.py](../src/observability/evaluation/eval_runner.py) | 复用，无需改动 |

---

## 验证方法（方案执行后如何确认成功）

1. **烟雾测试**：先用现有 4 条 `golden_test_set.json`（把 expected_chunk_ids 改成真实 ID）跑一次 `--generate-answers`，确认 8 个指标都有数值、无 ValueError。
2. **数据集完整性**：中英 golden set 各至少 40 条，人工抽检 10% 条目确认 question/ground_truth 通顺合理。
3. **RAGAS 正确性**：`aggregate_metrics` 含全部 4 个 `ragas__*` key；单条结果里 `contexts` 是真实文本（可读）而非 chunk ID——这是 [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py) 约第 132 行已经强制校验的。
4. **基线持久化**：Dashboard 评估面板中能看到两份基线记录，下次改动 retriever 后重跑能看到 `delta_aggregate_metrics`。
5. **单元测试**：`pytest tests/unit -v` 仍全部通过（改动都在 scripts/ 和 evaluator 配置层）。

---

## 时间与成本预估

| 阶段 | 工时 | LLM 调用 |
|---|---|---|
| Step 0 配置与 judge 接入 | 1-2 h | - |
| Step 1 合成（中英各 100 条） | 脚本运行 30-60 min | ~600-1000 次 GLM-4 |
| Step 2 人工精修 | 1-2 h | - |
| Step 3 回填 chunk_ids | 脚本 10 min + 抽检 30 min | - |
| Step 4 正式评估（中英各跑一次） | 30-60 min | ~100 条 × 4 指标 × 2-4 次 = 800-1600 次 |
| Step 5 解读与基线 | 30 min | - |
| **总计** | **1 个工作日** | **GLM-4 调用约 1500-2500 次** |

---

## 执行进度追踪

新的 AI 会话或开发者在按此方案推进时，请在下方记录进度（或在 DEV_SPEC.md 中新增对应任务）：

- [ ] Step 0：RAGAS backend 开启 + GLM judge 接入 + 烟雾测试通过
- [ ] Step 1：合成 raw_testset_zh.json / raw_testset_en.json
- [ ] Step 2：人工精修产出 reviewed_testset_*.json
- [ ] Step 3：回填 chunk_ids 产出 golden_test_set_{zh,en}.json
- [ ] Step 4：生成 logs/eval_zh_baseline.json、logs/eval_en_baseline.json
- [ ] Step 5：Dashboard 标记基线
- [ ] Step 6（可选）：RGB 小样本对照

---

## 新会话快速启动指引

若你是一个全新的 AI 会话，要接手这份工作：

1. 先读本文档了解整体方案（你正在读）。
2. 再读 [docs/ragas-guide.md](ragas-guide.md) 了解 RAGAS 指标的深度解读。
3. 读 [CLAUDE.md](../CLAUDE.md) 了解项目架构与代码约定。
4. 检查上方"执行进度追踪"清单，从**第一个未打钩**的步骤开始。
5. 执行前运行 `git status` 和 `ls logs/ tests/fixtures/` 确认当前文件状态。
6. 每完成一个步骤，把对应 checkbox 改为 `[x]` 并提交一次 commit。
