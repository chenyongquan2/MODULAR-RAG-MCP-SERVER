# RAGAS 评估指南

> 面向项目内 RAG 开发的 RAGAS 使用手册。本文档假设你对 RAG 有基本了解，但对 RAGAS（RAG 评估框架）不熟悉。

---

## 目录

1. [RAGAS 是什么，为什么需要它](#1-ragas-是什么为什么需要它)
2. [本项目的评估架构](#2-本项目的评估架构)
3. [四大核心指标详解](#3-四大核心指标详解)
4. [Golden Test Set 构建](#4-golden-test-set-构建)
5. [操作手册](#5-操作手册)
6. [指标解读与问题排查](#6-指标解读与问题排查)
7. [常见问题 FAQ](#7-常见问题-faq)
8. [扩展阅读](#8-扩展阅读)

---

## 1. RAGAS 是什么，为什么需要它

### 1.1 一句话定义

**RAGAS（Retrieval-Augmented Generation Assessment）** 是一个用 LLM 给 RAG 系统打分的评估框架——用一个强模型（如 GPT-4）当裁判，判断你的 RAG 系统"检索得准不准"、"回答得对不对"。

### 1.2 为什么 RAG 需要专门的评估

传统 NLP 评估（BLEU、ROUGE）对 RAG 不适用：
- RAG 的答案是"基于上下文生成"的，不是固定的标准答案
- RAG 有两个阶段（检索 + 生成），需要分别评估
- 幻觉（hallucination）是 RAG 的头号敌人，需要专门的指标

RAGAS 的核心思想：**用 LLM 做 Judge**（LLM-as-judge），让一个强模型判断"这个答案有没有忠实于检索到的上下文"。

### 1.3 与检索类指标的关系

本项目评估体系分两层：

| 层次 | 评估器 | 指标 | 输入 | 成本 |
|---|---|---|---|---|
| **检索评估** | `CustomEvaluator` | Hit Rate / MRR | chunk ID | 零（纯计算）|
| **生成评估** | `RagasEvaluator` | Faithfulness / Relevancy / Precision / Recall | 文本 + LLM judge | 每条 case 2 次 LLM 调用 |

**两者互补，缺一不可。** 检索不准，生成再好也没用；检索准了，生成不忠实（幻觉）也是灾难。

> 注：这里的"两层"指**评估器维度**（检索器 vs 生成器）。还有另一个正交的"两层"——**业务回归层（Layer A）vs 能力诊断层（Layer B）**——指的是**测试集来源维度**（业务自合成 vs 公开 benchmark），详见 [docs/rag-acceptance-plan.md § 评估架构：双层视角](rag-acceptance-plan.md)。两个"两层"是不同坐标轴，互相独立。

### 1.4 RAG 语料 vs Golden Test Set：必须区分的两个概念

> **2026-04-25 增补**：本节是 RAG 学习者最容易混淆的概念之一，先讲清楚再往下看 RAGAS 数据流。

刚接触 RAG 评估时，很多人会把"语料"和"测试集"混作一谈，问出"有没有通用 RAG 数据集供我评估系统？"。两者完全是不同性质的资源：

| 概念 | 指什么 | 在管线里的角色 | 例子（本项目） |
|------|--------|--------------|------------|
| **语料**（corpus） | 被检索的知识库本体 | 摄取阶段灌进 ChromaDB 的内容 | MT5 中英文手册（PDF / Markdown） |
| **基线数据 / Golden Test Set** | 用来评估系统好坏的 (question, ground_truth, expected_chunks) 三元组 | 评估阶段输入到 evaluator 的"答案册" | [tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json) |

#### 为什么两者都不存在"通用"版本

**语料层面**：RAG 的价值就在"用你自己的私有/垂直/最新知识增强 LLM"。如果用通用语料（如英文 Wikipedia），LLM 本身预训练时已经看过——RAG 反而成为多余环节。所以你的**业务语料就是你的语料**（MT5 手册无可替代），不该追求"通用"。

**测试集层面**：公开 RAG 测试集（MS MARCO / HotpotQA / RGB / DuReader 等）的题目都是基于自己的语料编的，跟你的业务语料错位——直接拿来用，要么把它的语料也摄入进系统（本质等于"换一个领域重跑一遍"，跟你业务无关），要么期望你的 RAG 能答出语料里没有的内容（必然 100% 答错）。

**结论**：业务效果验收**只能**用业务自合成 + 人工精修的 Golden Set。这是为什么 [Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 走"自合成 + 人工精修中英各 40-50 条"路径。

#### 公开测试集的合理用法（Layer B 能力诊断）

公开数据集**不能做主验收**，但可以做**能力指纹**——告诉你系统的零部件能力（多跳推理 / 表格 QA / 抗噪声 / 长上下文）在业内标准基准下是什么水平。这是另一个独立维度，详见 [rag-acceptance-plan.md § 评估架构：双层视角](rag-acceptance-plan.md) 的完整说明。

### 1.5 RAGAS 的输入与评估对象

> **2026-04-25 增补**：理解 RAGAS"吃什么、评什么"是用好它的第一步。

#### 1.5.1 RAGAS 评估的对象：是"运行时产物"，不是"静态资源"

```
                  RAG 系统（你的整套 pipeline）
                        ↓
        ┌──────────────┴──────────────┐
        ↓                              ↓
   检索阶段产出                    生成阶段产出
   contexts（命中的             answer（LLM 基
   知识片段文本）                于 contexts 写
                                 出的回答）
        └──────────────┬──────────────┘
                        ↓
                    RAGAS 在这里
                    打分（用 Judge LLM）
```

**关键洞察**：RAGAS **不直接看语料库、不直接看测试集**——它看的是"测试集里的题目喂给你的 RAG 系统后，系统跑出来的答卷"。

#### 1.5.2 RAGAS 输入的四元组

每条评估用例必须凑齐 4 个字段：

| 字段 | 含义 | 来源 | 谁负责提供 |
|------|------|------|-----------|
| **question** | 用户的提问 | golden set | 测试集 |
| **contexts** | RAG 系统检索到的知识片段（**真实文本**，非 chunk ID） | 运行时 | 你的检索器 |
| **answer** | RAG 系统给出的回答 | 运行时 | 你的生成器（ResponseBuilder） |
| **ground_truth** | 题目的"标准答案" | golden set | 测试集 |

**关键约束**：`contexts` 必须是**可读知识片段文本**（[Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 的 FR-003 与 [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py) 约 L132 都强制校验这一点）——RAGAS 内部要让 Judge LLM 阅读这段文本做语义对比，给 chunk ID 它读不懂。

#### 1.5.3 4 个 RAGAS 指标各自需要哪些字段

不同指标对四元组的依赖不同：

| 指标 | question | contexts | answer | ground_truth | 评估什么 |
|------|:---:|:---:|:---:|:---:|---------|
| **faithfulness** | ✓ | ✓ | ✓ | ✗ | answer 是不是只基于 contexts，没有幻觉 |
| **answer_relevancy** | ✓ | ✗ | ✓ | ✗ | answer 是不是真的回答了 question |
| **context_precision** | ✓ | ✓ | ✗ | ✓ | 检索到的 contexts 中"有用片段"的占比（去噪能力） |
| **context_recall** | ✗ | ✓ | ✗ | ✓ | ground_truth 中的事实是否被 contexts 覆盖（召回能力） |

**重要推论**：
- `faithfulness` 与 `answer_relevancy` **不需要 ground_truth** → 理论上可以"无标准答案"评估（线上流量采样可用）
- `context_precision` 与 `context_recall` **必须有 ground_truth** → 这是为什么测试集的 `ground_truth` 字段不能省略

#### 1.5.4 必须有 Judge LLM 的原因

RAGAS 指标的本质是**语义判断**，不是字符串匹配：

| 任务 | 字符串匹配能否做？ | 需要 LLM 吗 |
|------|---------|-------|
| answer "MT5 用 MQL5 写策略" 与 ground_truth "MetaTrader 5 通过 MQL5 编程实现" 是否一致 | ❌ 字符不重合 | ✅ |
| contexts 中哪些段落跟 question 真正相关 | ❌ | ✅ |
| answer 里每句话能不能在 contexts 里找到依据 | ❌ | ✅ |

所以 RAGAS 必须有 Judge LLM 当"裁判"——本项目硬约束 = GLM-4，通过 LangChain 的 `ChatOpenAI` 包一层 GLM 兼容端点接入。

**注意区分两种 LLM 角色**：
- **生成器 LLM**（[src/libs/llm/](../src/libs/llm/)）：你 RAG 系统里负责拼 answer 的模型，可配 GLM / Azure / Ollama 等
- **Judge LLM**：RAGAS 评估时单独配置（本项目固定 = GLM-4），跟生成器 LLM 可以是同一个也可以不同

#### 1.5.5 RAGAS vs custom 检索指标的输入差异

本项目同时跑 RAGAS（4 个指标）+ custom（4 个检索指标），输入要求不同：

| 维度 | RAGAS 指标 | custom 检索指标（Hit/MRR/Recall/NDCG） |
|------|------------|-----------------------------------------|
| 输入 | (question, contexts 文本, answer, ground_truth) | (检索返回的 chunk_id 列表, expected_chunk_ids 列表) |
| 评估对象 | 语义层（基于内容） | ID 匹配层（基于元数据） |
| 需要 Judge LLM | ✅ | ❌（纯 ID 集合运算） |
| 需要 ground_truth 文本 | 部分指标需要 | ❌ |
| 需要 expected_chunk_ids | ❌ | ✅ |

这就是为什么 [Feature-001 spec.md](../specs/001-rag-acceptance/spec.md) 的 `TestCase` 实体同时包含 `ground_truth`（喂 RAGAS）和 `expected_chunk_ids`（喂 custom 指标）——**一份测试集同时服务两组指标**。

---

## 2. 本项目的评估架构

### 2.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     完整评估链路                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Golden Test Set                                                  │
│  {query, expected_chunk_ids, ground_truth}                        │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────┐                                                  │
│  │  EvalRunner  │                                                  │
│  └──────┬───────┘                                                  │
│         │                                                          │
│         ├──▶ HybridSearch.search(query)                            │
│         │        └─▶ RetrievalResult[{chunk_id, text, score}]      │
│         │                                                          │
│         ├──▶ ResponseBuilder.build(query, results)    [可选]       │
│         │        └─▶ StructuredContent(markdown=answer)            │
│         │                                                          │
│         └──▶ Evaluator.evaluate(                                   │
│                  query, retrieved_ids, golden_ids,                 │
│                  answer,          ◀── LLM 生成的答案                │
│                  contexts,        ◀── 真实的文本片段（不是 ID！）   │
│                  ground_truth     ◀── 参考答案                      │
│              )                                                     │
│                   │                                                │
│                   ├─▶ CustomEvaluator    → hit_rate, mrr           │
│                   └─▶ RagasEvaluator     → 4 个 RAGAS 指标         │
│                            (内部调 LLM 打分)                        │
│                                                                    │
│         ▼                                                          │
│      EvalReport                                                    │
│      (聚合指标 + 每条 case 详情)                                    │
│                                                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 关键文件定位

| 角色 | 文件 |
|---|---|
| 抽象接口 | [src/libs/evaluator/base_evaluator.py](../src/libs/evaluator/base_evaluator.py) |
| 工厂（自动注册 backend） | [src/libs/evaluator/evaluator_factory.py](../src/libs/evaluator/evaluator_factory.py) |
| 检索评估实现 | [src/libs/evaluator/custom_evaluator.py](../src/libs/evaluator/custom_evaluator.py) |
| RAGAS 评估实现 | [src/observability/evaluation/ragas_evaluator.py](../src/observability/evaluation/ragas_evaluator.py) |
| 组合评估（并行多 backend） | [src/observability/evaluation/composite_evaluator.py](../src/observability/evaluation/composite_evaluator.py) |
| 评估编排器 | [src/observability/evaluation/eval_runner.py](../src/observability/evaluation/eval_runner.py) |
| Dashboard 服务层 | [src/observability/dashboard/services/evaluation_service.py](../src/observability/dashboard/services/evaluation_service.py) |
| CLI 入口 | [scripts/evaluate.py](../scripts/evaluate.py) |
| Golden Test Set | [tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json) |

### 2.3 插件化工厂机制

配置驱动，修改 `config/settings.yaml` 即可切换：

```yaml
evaluation:
  backends:
    - custom      # 必选：检索类指标
    - ragas       # 可选：生成类指标（需安装 ragas 依赖）
  golden_test_set: ./tests/fixtures/golden_test_set.json
```

当配置多个 backend 时，工厂返回 `CompositeEvaluator`，并行运行所有 evaluator 并用命名空间合并指标（如 `custom__hit_rate`、`ragas__faithfulness`）。

---

## 3. 四大核心指标详解

### 3.1 Faithfulness（忠实度）— 防幻觉

**问的是**：生成的 answer 里每句话，能不能在 contexts 里找到依据？

```
score = 被 contexts 支持的 claim 数 / answer 中总 claim 数
```

**示例**：
- contexts = `["RAG 由检索和生成两部分组成"]`
- answer = `"RAG 由检索、生成和嵌入三部分组成"`
- faithfulness ≈ 0.66（"检索和生成"能找到依据，"嵌入"是编造的）

**需要**：`answer` + `contexts`
**看这个指标**：判断 LLM 有没有胡编

---

### 3.2 Answer Relevancy（答案相关性）— 防答非所问

**问的是**：answer 是否真的回答了 question？

RAGAS 会让 LLM 从 answer 反推出多个可能的 question，再计算反推 question 与原 question 的相似度。

**示例**：
- question = `"如何配置 Azure OpenAI？"`
- answer = `"Azure OpenAI 是微软的云服务"`  → relevancy 低（没答怎么配置）
- answer = `"在 settings.yaml 设置 provider: azure 并填写 api_key"` → relevancy 高

**需要**：`question` + `answer` + `contexts`
**看这个指标**：判断 LLM 有没有答到点上

---

### 3.3 Context Precision（上下文精确率）— 检索是否精准

**问的是**：检索到的 contexts 中，与回答相关的片段是否排在前面？

```
像一个考虑排序的 Precision@K：相关片段越靠前，分越高
```

**示例**：
- top-3 contexts 中第 1、2 条相关 → precision 高
- top-3 contexts 中只有第 3 条相关 → precision 低

**需要**：`question` + `contexts` + `ground_truth`
**看这个指标**：判断 reranker / fusion 的排序质量

---

### 3.4 Context Recall（上下文召回率）— 检索是否完整

**问的是**：ground_truth 里涉及的每个知识点，contexts 都覆盖到了吗？

```
score = ground_truth 中能在 contexts 找到依据的 claim 数 / 总 claim 数
```

**示例**：
- ground_truth 提到 A、B、C 三个点
- contexts 只覆盖了 A 和 B → recall ≈ 0.66

**需要**：`contexts` + `ground_truth`
**看这个指标**：判断检索有没有漏关键信息

---

### 3.5 四指标组合看板

| 场景 | 症状 | 看哪个指标 |
|---|---|---|
| LLM 爱编造 | `faithfulness ↓` | |
| 答非所问 | `answer_relevancy ↓` | |
| 检索排序烂 | `context_precision ↓` | |
| 检索有遗漏 | `context_recall ↓` | |

---

## 4. Golden Test Set 构建

### 4.1 标准格式

[tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json)

```json
{
  "test_cases": [
    {
      "query": "如何配置 Azure OpenAI？",
      "expected_chunk_ids": ["chunk_azure_001", "chunk_azure_002"],
      "expected_sources": ["config_guide.pdf"],
      "ground_truth": "在 config/settings.yaml 的 llm 节点下，将 provider 设为 azure..."
    }
  ]
}
```

### 4.2 字段语义

| 字段 | 必填 | 用途 | 谁在用 |
|---|---|---|---|
| `query` | ✓ | 测试查询 | 所有 evaluator |
| `expected_chunk_ids` | ✓ | 参考检索 ID | `CustomEvaluator`（Hit/MRR）|
| `expected_sources` | ✗ | 参考来源文档 | Source 级 hit 指标 |
| `ground_truth` | ✗（但 RAGAS 必需）| 参考答案文本 | `RagasEvaluator`（Precision/Recall）|

**注意**：虽然 `ground_truth` 在 schema 层面可选，但启用 RAGAS 时**必须填写**，否则会报 `ValueError`。

### 4.3 规模建议

| 阶段 | 推荐条数 | 说明 |
|---|---|---|
| 冷启动 | 10~20 | 验证流程跑通，覆盖核心场景 |
| 开发期 | 50~100 | 足以发现大部分回归 |
| 生产级 | 100~500 | 按业务分类均衡覆盖 |

### 4.4 构建方法（按性价比排序）

**方法 1：生产流量回放（推荐）**

```
生产日志采样 → 筛选有价值 query → 人工补 ground_truth
```

最真实，但需要生产数据。建议在 logs/traces.jsonl 中采样。

**方法 2：LLM 合成 + 人工审核**

用强模型（GPT-4/Claude）读你的文档自动生成 QA 对，再人工筛选。

```python
# 伪代码示例
prompt = f"基于以下文档，生成 5 个用户可能会问的问题和标准答案：\n{doc}"
qa_pairs = llm.generate(prompt)
# 人工挑选保留质量高的
```

**方法 3：RAGAS TestsetGenerator**

安装 ragas 后可用：

```python
from ragas.testset import TestsetGenerator
# 自动合成测试集，支持 simple/reasoning/multi_context 三种难度
```

**方法 4：人工标注（最慢但质量最高）**

由领域专家直接写 query + ground_truth。适合核心业务场景。

### 4.5 测试集质量检查表

- [ ] 覆盖不同难度（简单事实 / 多跳推理 / 边界情况）
- [ ] 覆盖不同业务域（配置类 / 使用类 / 原理类）
- [ ] 包含负例（知识库里没有答案的问题）
- [ ] `ground_truth` 简洁但包含所有关键点（50~200 字为宜）
- [ ] `expected_chunk_ids` 必须真实存在于当前索引中

---

## 5. 操作手册

### 5.1 前置准备

#### Step 1：安装依赖

```bash
# 激活虚拟环境
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 安装 RAGAS
pip install ragas datasets
```

#### Step 2：配置 judge LLM

RAGAS 默认读 `OPENAI_API_KEY`。推荐复用已有 LLM（省钱 + 数据不出境）：

```bash
# .env（复用 GLM）
OPENAI_API_KEY=your-glm-key
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
```

#### Step 3：启用 RAGAS backend

[config/settings.yaml](../config/settings.yaml)

```yaml
evaluation:
  backends:
    - custom
    - ragas       # ← 新增这一行
  golden_test_set: ./tests/fixtures/golden_test_set.json
```

---

### 5.2 场景 A：纯检索评估（日常高频）

**特点**：秒级完成、零 LLM 成本、不需要 `ground_truth`。

```bash
python scripts/evaluate.py --no-generate-answers --pretty
```

**输出示例**：

```json
{
  "total_cases": 4,
  "hit_rate": 0.75,
  "mrr": 0.58,
  "source_hit_rate": 1.0,
  "aggregate_metrics": {
    "hit_rate": 0.75,
    "mrr": 0.58
  }
}
```

**适用场景**：改了 embedding、splitter、top_k、reranker 后快速验证。

---

### 5.3 场景 B：完整 RAGAS 评估（发版前）

**特点**：走完整 RAG 链路，产出 4 个 RAGAS 指标。

```bash
# 方式 1：显式启用
python scripts/evaluate.py --generate-answers --pretty

# 方式 2：配置含 ragas 时自动启用（推荐）
python scripts/evaluate.py --pretty
```

**执行时间参考**：4 条 case × 2 次 LLM 调用/case ≈ 10~30 秒（受 LLM 延迟影响）

**输出示例**：

```json
{
  "total_cases": 4,
  "hit_rate": 0.75,
  "mrr": 0.58,
  "aggregate_metrics": {
    "custom__hit_rate": 0.75,
    "custom__mrr": 0.58,
    "ragas__faithfulness": 0.87,
    "ragas__answer_relevancy": 0.91,
    "ragas__context_precision": 0.82,
    "ragas__context_recall": 0.78
  }
}
```

**保存结果**：

```bash
python scripts/evaluate.py --generate-answers --pretty > logs/eval_$(date +%Y%m%d_%H%M).json
```

---

### 5.4 场景 C：Dashboard 可视化运行

```bash
python scripts/start_dashboard.py
```

浏览器打开后进入"评估面板"页面：

```
┌─────────────────────────────────────────┐
│  Mode: ○ custom  ○ ragas  ● all          │
│  Test Set: golden_test_set.json  ▼       │
│  Top-K: [10]                             │
│  Collection: [default]                   │
│  [ ▶ 运行评估 ]                           │
└─────────────────────────────────────────┘
```

**页面功能**：
- 单次运行：实时看本次指标
- 历史趋势：多次评估的折线图
- 基线对比：与打了 baseline 标记的历史记录对比，产出 delta

**历史文件位置**：`logs/evaluations.jsonl`

---

### 5.5 CLI 参数速查

```bash
python scripts/evaluate.py --help
```

| 参数 | 说明 |
|---|---|
| `--test-set PATH` | 测试集路径（默认 `tests/fixtures/golden_test_set.json`）|
| `--top-k N` | 每条 query 的召回数（默认读配置 `retrieval.top_k_final`）|
| `--collection NAME` | 集合过滤 |
| `--pretty` | JSON 缩进输出 |
| `--generate-answers` | 强制启用 LLM answer 生成 |
| `--no-generate-answers` | 强制关闭 answer 生成（即使配置了 ragas）|

---

## 6. 指标解读与问题排查

### 6.1 指标基准值参考

| 指标 | 差 | 一般 | 好 | 优秀 |
|---|---|---|---|---|
| `hit_rate` | < 0.5 | 0.5~0.7 | 0.7~0.85 | > 0.85 |
| `mrr` | < 0.3 | 0.3~0.5 | 0.5~0.7 | > 0.7 |
| `faithfulness` | < 0.6 | 0.6~0.75 | 0.75~0.9 | > 0.9 |
| `answer_relevancy` | < 0.7 | 0.7~0.8 | 0.8~0.9 | > 0.9 |
| `context_precision` | < 0.5 | 0.5~0.7 | 0.7~0.85 | > 0.85 |
| `context_recall` | < 0.5 | 0.5~0.7 | 0.7~0.85 | > 0.85 |

> 数值仅供参考，不同领域差异大，重点关注**趋势**和**相对值**。

### 6.2 常见问题诊断树

```
指标下降？
│
├─ hit_rate 掉？
│  ├─ embedding 模型换了？  → 重新 ingest
│  ├─ splitter 策略变了？   → chunk 不匹配，重新 ingest
│  ├─ top_k 变小了？        → 召回范围不够
│  └─ filter 太严？         → 放宽 collection/filter
│
├─ hit_rate 高但 mrr 低？
│  └─ 相关 chunk 排在后面   → 检查 reranker 和 fusion 权重
│
├─ faithfulness 低？
│  ├─ LLM 爱发挥？          → 换更严谨的模型
│  ├─ prompt 不够约束？     → 加"严格基于上下文回答，无依据时说不知道"
│  └─ contexts 质量差？     → 先看 context_precision
│
├─ answer_relevancy 低？
│  ├─ query 被曲解？        → 检查 QueryProcessor
│  ├─ answer 跑题？         → 检查 prompt 模板
│  └─ contexts 不相关？     → 先看 context_precision
│
├─ context_precision 低？
│  ├─ chunk 太大？          → 调小 chunk_size
│  ├─ top_k 太大？          → 引入无关内容
│  └─ reranker 没启用？     → 配置 rerank.backend
│
└─ context_recall 低？
   ├─ top_k 太小？          → 漏了关键 chunk
   ├─ chunk 切分不合理？   → 关键信息被切碎
   └─ embedding 召回差？   → 考虑 hybrid（dense + sparse）
```

### 6.3 典型异常场景

**场景 1：`hit_rate = 1.0` 但 `faithfulness = 0.3`**

→ 检索到了正确 chunk，但 LLM 没用好 → 查 prompt 和生成模型

**场景 2：`faithfulness = 0.95` 但 `answer_relevancy = 0.4`**

→ LLM 说的都对但没答到问题点 → query 理解有问题

**场景 3：`context_recall` 稳定但 `context_precision` 波动大**

→ 召回够但排序不稳定 → reranker 或 fusion 权重需要调优

---

## 7. 常见问题 FAQ

### Q1：每次评估都要花钱吗？

**A**：`--no-generate-answers` 模式完全免费（纯计算）。完整 RAGAS 每条 case 约 2 次 LLM 调用，按 GLM/DeepSeek 定价约 ¥0.01~0.05/case，100 条全跑约 ¥1~5。

### Q2：RAGAS 的 judge LLM 可以用本地模型吗？

**A**：可以，但效果可能下降。RAGAS 官方推荐 GPT-4 级别的模型做 judge。如果用本地模型（如 Qwen-72B），建议保留一个小规模的"人工标注对照集"校验 judge 的准确性。

### Q3：`ground_truth` 写多长合适？

**A**：50~200 字，覆盖所有关键知识点。太短会导致 `context_recall` 虚高（没啥可召回的），太长会导致每个 claim 粒度太细。

### Q4：我修改了 splitter，之前的 `expected_chunk_ids` 还有效吗？

**A**：无效。chunk_id 通常是基于内容+位置生成的，splitter 变了 ID 就变了。需要重新 ingest 后更新测试集的 `expected_chunk_ids`，或者只依赖 `expected_sources`（文档级）+ `ground_truth`（语义级）。

### Q5：RAGAS 的数值稳定吗？每次跑分数会变？

**A**：会轻微波动（LLM 有温度）。建议：
- 把 RAGAS judge LLM 的 `temperature` 设为 0
- 用 3 次运行的平均值作为稳定估计
- 关注**趋势**而非**绝对值**

### Q6：CI/CD 里怎么用？

**A**：设门禁阈值，指标低于阈值时 exit 1：

```bash
python scripts/evaluate.py --pretty > /tmp/report.json
python -c "
import json, sys
r = json.load(open('/tmp/report.json'))
m = r['aggregate_metrics']
assert m.get('custom__hit_rate', 0) >= 0.8, 'hit_rate regression'
assert m.get('ragas__faithfulness', 0) >= 0.7, 'faithfulness regression'
"
```

### Q7：为什么我传了 chunk ID 列表当 contexts，RAGAS 会报错？

**A**：这是**刻意的设计**。之前的旧代码会悄悄把 chunk ID 当文本喂给 LLM judge，产出毫无意义的分数。现在会显式报 `ValueError`，迫使你传真实文本。这是从"静默产出错数据"改为"主动报错"的最佳实践。

### Q8：没有 `ResponseBuilder` 可以跑 RAGAS 吗？

**A**：可以跑，但 `faithfulness` 和 `answer_relevancy` 会因 `answer` 为空而得 0。`context_precision` 和 `context_recall` 不依赖 answer，仍然有效。

---

## 8. 扩展阅读

### 8.1 项目内相关文档

- [DEV_SPEC.md](../DEV_SPEC.md) §3.8：评估系统技术设计
- [CLAUDE.md](../CLAUDE.md)：项目整体说明
- [docs/rag-acceptance-plan.md](rag-acceptance-plan.md)：RAG 质量验收方案 + § 评估架构：双层视角（业务回归层 vs 能力诊断层、tags schema、文档形态扩展时的双红线评估）—— 与本文 § 1.4/1.5 互补阅读
- [specs/001-rag-acceptance/spec.md](../specs/001-rag-acceptance/spec.md)：RAG 验收 Feature-001 spec（FR-014/FR-015/SC-008 是双层评估架构在本项目的 schema 落地）
- 本文档：`docs/ragas-guide.md`

### 8.2 RAGAS 官方资源

- 官网：https://ragas.io
- 指标原理：https://docs.ragas.io/en/stable/concepts/metrics/
- TestsetGenerator：https://docs.ragas.io/en/stable/concepts/testset_generation.html

### 8.3 其他评估方案对比

| 框架 | 定位 | 是否推荐用于本项目 |
|---|---|---|
| Ragas | RAG 专用评估 | ✅ 已集成 |
| DeepEval | pytest 风格 LLM 评估 | 备选 |
| TruLens | 可观测性 + 评估 | 备选 |
| LangSmith | 商业平台 | ❌ 不推荐（无 LangChain 依赖）|

### 8.4 最佳实践参考

- 企业 RAG 评估案例：用生产流量采样 + 专家标注做 golden set
- A/B 测试：将 RAGAS 与用户反馈（👍/👎）做相关性分析，校准 judge 的有效性
- 持续评估：每次索引/模型/prompt 变更都打 baseline，形成可追溯的指标基线

---

## 附：快速 SOP

```bash
# 日常开发循环（秒级）
python scripts/evaluate.py --no-generate-answers

# 发版前（完整评估）
python scripts/evaluate.py --generate-answers --pretty > logs/eval_$(date +%F).json

# 对比基线（Dashboard）
python scripts/start_dashboard.py  # 在评估面板打 baseline 标记
```

**黄金法则**：
1. `hit_rate` 是基础，低于 0.7 先修检索，别急着调 prompt
2. `faithfulness` 低先检查 prompt，再换模型
3. Golden Set 持续扩充，评估才有说服力
4. 关注趋势，不要纠结单次绝对值
