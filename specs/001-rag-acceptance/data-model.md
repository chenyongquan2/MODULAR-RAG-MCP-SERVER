# Data Model: RAG 质量验收(中英双语基线)

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 1 complete

本文件定义本 feature 涉及的所有实体、字段约束、关系与状态转换。所有跨模块共享类型集中定义在 [src/core/types.py](../../src/core/types.py)(宪法 § VI 类型安全)。

---

## 1. Configuration Entities(配置实体,定义在 `src/core/settings.py`)

### 1.1 `EvaluationSettings`(扩展)

| Field | Type | Default | Constraint | Source |
|---|---|---|---|---|
| `_schema_version` | `int` | `1` | `>= 1` | research.md § Decision 7 |
| `backends` | `list[str]` | `["custom"]`(扩到 `["custom", "ragas"]`) | 元素 ∈ `{"custom", "ragas"}` | spec § FR-001 |
| `golden_test_set` | `str` | `"./tests/fixtures/golden_test_set.json"` | 文件可读 | 既有 |
| `golden_test_sets_by_lang` | `dict[str, str]` | `{}` | key ∈ `{"zh", "en"}`,value 必须可读 | spec § FR-006 |
| `judge_llm` | `JudgeLLMSettings` | 见 1.2 | 仅当 `"ragas" in backends` 时必须填 | spec § FR-016 |
| `embedding` | `EvaluationEmbeddingSettings` | 见 1.3 | 必须填 | spec § FR-017 |
| `acceptance_thresholds` | `AcceptanceThresholds` | 见 1.4 | 见 1.4 约束 | spec § FR-013 |
| `by_tag_dimensions` | `list[str]` | `["content_type", "difficulty"]` | 必须 ⊆ `{"content_type", "difficulty"}` | spec § FR-015 |
| `report_archive_dir` | `str` | `"./logs/evaluation_reports"` | 父目录可写 | research.md § Decision 3 |
| `baseline_store_path` | `str` | `"./logs/baselines.json"` | 父目录可写 | research.md § Decision 3 |
| `tag_slice_min_samples` | `int` | `5` | `>= 1` | spec § FR-015 |
| `chunk_id_validation` | `bool` | `True` | — | spec § FR-007 |

**Validation**(`load_settings()` 启动期完成):
- 若 `"ragas" in backends`:`judge_llm` 必须非空
- `acceptance_thresholds` 每个值 ∈ `[0, 1]`
- `judge_llm.provider` ∈ LLMFactory 注册列表
- `embedding.provider` ∈ EmbeddingFactory 注册列表
- `report_archive_dir` / `baseline_store_path` 父目录必须可写

### 1.2 `JudgeLLMSettings`

| Field | Type | Default | Constraint |
|---|---|---|---|
| `provider` | `str` | `"glm"` | ∈ `{"glm", "azure", "openai", "ollama", "deepseek"}` |
| `model` | `str` | `"glm-4"` | 非空 |
| `api_key` | `str` | `""`(env 注入) | — |
| `base_url` | `Optional[str]` | `None` | — |
| `temperature` | `float` | `0.0` | ∈ `[0, 2]` |
| `request_timeout_sec` | `int` | `60` | `> 0` |

### 1.3 `EvaluationEmbeddingSettings`

| Field | Type | Default | Constraint |
|---|---|---|---|
| `provider` | `str` | `""`(空 = 复用 `settings.embedding.provider`) | 空 或 ∈ EmbeddingFactory 注册列表 |
| `model` | `str` | `""`(空 = 复用 `settings.embedding.model`) | — |
| `api_key` | `str` | `""`(env 注入) | — |
| `base_url` | `Optional[str]` | `None` | — |

**默认行为**:全空时直接复用 production query 的 embedding(FR-017 默认要求)。

### 1.4 `AcceptanceThresholds`

| Field | Type | Default | Constraint |
|---|---|---|---|
| `ragas__context_recall` | `float` | `0.70` | ∈ `[0, 1]` |
| `ragas__context_precision` | `float` | `0.65` | ∈ `[0, 1]` |
| `ragas__faithfulness` | `float` | `0.85` | ∈ `[0, 1]` |
| `ragas__answer_relevancy` | `float` | `0.75` | ∈ `[0, 1]` |
| `custom__hit_rate` | `float` | `0.60` | ∈ `[0, 1]`(K 由 `query.top_k_final`,默认 5/10) |
| `custom__mrr` | `float` | `0.55` | ∈ `[0, 1]` |
| `custom__recall` | `float` | `0.70` | ∈ `[0, 1]` |
| `custom__ndcg` | `float` | `0.55` | ∈ `[0, 1]` |

默认值即 spec § FR-013 锁定的"业界参考值";用户在 settings.yaml 中可覆盖任一字段。

---

## 2. Domain Entities(领域实体,定义在 `src/core/types.py`)

### 2.1 `TestCaseTags`

| Field | Type | Allowed Values | Source |
|---|---|---|---|
| `content_type` | `Literal["text", "code", "table", "mixed"]` | 4 选 1 | spec § FR-014 |
| `difficulty` | `Literal["simple", "reasoning", "multi_context"]` | 3 选 1 | spec § FR-014 |
| `language` | `Literal["zh", "en"]` | 2 选 1 | spec § FR-014 |
| `doc_version` | `str` | 默认 `"v1"`,字符串如 `"v1"` / `"v2"` | spec § FR-014 |

### 2.2 `TestCase`

| Field | Type | Constraint | Source |
|---|---|---|---|
| `query` | `str` | 非空,strip 后非空 | spec § FR-006 |
| `expected_chunk_ids` | `list[str]` | 非空,所有 ID 必须在 vector store 存在(若 `chunk_id_validation=True`) | spec § FR-007 |
| `expected_sources` | `list[str]` | 可空 | spec § FR-006 |
| `ground_truth` | `str` | 非空(US2 后强制),US1 占位阶段允许空 | spec § FR-006 |
| `tags` | `TestCaseTags` | 必填,所有子字段必填 | spec § FR-014 |

### 2.3 `GoldenTestSet`

| Field | Type | Constraint | Source |
|---|---|---|---|
| `language` | `Literal["zh", "en"]` | 必填 | spec § Key Entities |
| `version` | `str` | 形如 `"v1.0"` | spec § Key Entities |
| `cases` | `list[TestCase]` | 长度 ∈ `[40, 100]`(US2 完成后) | spec § FR-006 |
| `created_at` | `str` | ISO-8601 | spec § Key Entities |
| `source_corpus_collection` | `str` | 非空 | spec § Key Entities |

**Invariants**:
- 同一 `language` 在仓库内只有一份"当前在用"(其他版本归 `tests/fixtures/archive/`,MVP 不实现归档自动化)
- 难度分布:每类 ≥ 10%(spec US2 Independent Test)

### 2.4 `AcceptanceStatus`

```python
from enum import Enum

class AcceptanceStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
```

### 2.5 `EvaluationReport`(扩展;现有 `EvalReport` 升级)

| Field | Type | New / Existing | Source |
|---|---|---|---|
| `run_id` | `str (UUID4)` | NEW | research.md § Decision 3 |
| `collection` | `str` | NEW(从 `filters` 提升) | spec § Key Entities |
| `test_set_version` | `str` | NEW | spec § Key Entities |
| `total_cases` | `int` | EXISTING | — |
| `aggregate_metrics` | `dict[str, float]` | EXISTING(扩到 8 项) | spec § FR-001 |
| `aggregate_metrics_by_tag` | `dict[str, dict[str, dict[str, float \| None]]]` | NEW | spec § FR-015 |
| `case_results` | `list[EvalCaseResult]` | EXISTING | — |
| `judge_llm_identifier` | `str` | NEW(形如 `"glm:GLM-4"`) | spec § FR-016 |
| `embedding_identifier` | `str` | NEW(形如 `"openai:text-embedding-3-small"`) | spec § FR-017 |
| `acceptance_thresholds_snapshot` | `dict[str, float]` | NEW | spec § FR-013 |
| `acceptance_status` | `AcceptanceStatus` | NEW | spec § FR-013 |
| `degraded_case_count` | `int` | NEW | spec § Edge Cases / SC-006 |
| `created_at` | `str (ISO-8601)` | NEW | — |
| `baseline_id` | `Optional[str]` | EXISTING | spec § FR-009 |
| `delta_aggregate_metrics` | `Optional[dict[str, float]]` | EXISTING | spec § FR-009 |
| `per_tag_delta` | `Optional[dict[str, dict[str, dict[str, float]]]]` | NEW | spec § Key Entities |
| `hit_rate` / `mrr` / `source_hit_rate` | `float` | EXISTING(顶层方便字段) | 既有 |

**Invariants**:
- `acceptance_status == PASS` ⟺ 8 个主聚合指标全部 ≥ 各自 `acceptance_thresholds_snapshot` 中对应阈值
- `aggregate_metrics_by_tag` 不参与 `acceptance_status` 判定(spec Clarifications Q2)
- 切片样本量 < `tag_slice_min_samples` 时,该 entry 值为 `null` 且 entry 内含 `_skipped_reason: "n_samples=<n><N>"`(research.md § Decision 5)

### 2.6 `Baseline`

| Field | Type | Constraint | Source |
|---|---|---|---|
| `report_id` | `str (UUID4)` | 必须指向已归档的 EvaluationReport | spec § FR-008 |
| `collection` | `str` | 必填 | spec § FR-008 |
| `marked_at` | `str (ISO-8601)` | 必填 | — |
| `marked_by` | `str` | 默认 `"manual"`,MVP 不做权限 | — |
| `acceptance_status` | `AcceptanceStatus` | 复制自 EvaluationReport(便于面板查询不必再读 report) | spec § Clarifications Q3 |

**Invariants**:
- 同一 `collection` 在 `BaselineStore.current[<collection>]` 只能有一个 Baseline
- `acceptance_status == FAIL` 的 Baseline 仍可被标记(spec § Clarifications Q3),但面板必须视觉区分

### 2.7 `BaselineStore`(整体存储模型,落到 `logs/baselines.json`)

```json
{
  "_schema_version": 1,
  "current": {
    "<collection_name>": {
      "report_id": "<uuid>",
      "marked_at": "<iso8601>",
      "marked_by": "manual",
      "acceptance_status": "pass"
    }
  },
  "history": {
    "<collection_name>": [
      {"report_id": "<uuid_old>", "marked_at": "<iso8601>", "demoted_at": "<iso8601>"}
    ]
  }
}
```

### 2.8 `DeltaReport`(自动产生;不归档独立文件,作为 EvaluationReport 的子结构)

| Field | Type | Source |
|---|---|---|
| `current_report_id` | `str` | spec § Key Entities |
| `baseline_report_id` | `str` | spec § Key Entities |
| `per_metric_delta` | `dict[str, float]` | spec § FR-009 |
| `per_tag_delta` | `dict[str, dict[str, dict[str, float]]]` | spec § Key Entities |

**Calculation**:`delta = current_value - baseline_value`(简单相减,正数表示提升,负数表示退化)。

---

## 3. Lifecycle / State Transitions

### 3.1 EvaluationReport 生命周期

```
[start]
  │
  ▼
generated (EvalRunner.run() 完成)
  │     ├─ acceptance_status: pass | fail (FR-013 自动判定)
  │     └─ (可选) 自动写入 logs/evaluation_reports/<run_id>.json
  │
  ▼
archived (持久化到文件系统;index.jsonl 追加一行)
  │
  ├──► (用户操作) marked_as_baseline
  │       └─ 在 baselines.json 的 current[<collection>] 写入,旧 baseline 移到 history[<collection>]
  │
  └──► (自动) 若该 collection 已有 baseline,生成 DeltaReport 嵌入 EvaluationReport 输出
```

### 3.2 Baseline 生命周期

```
no_baseline_for_collection
  │
  ▼ (用户标记)
current_baseline_v1
  │
  ▼ (用户标记新基线)
current_baseline_v2  (v1 移到 history)
```

**注意**:当前基线被替换时不删除报告文件,只在 BaselineStore.history 追加;EvaluationReport 文件长期保留。

---

## 4. Relationships

```
GoldenTestSet --owns 40~100--> TestCase
TestCase --has 1--> TestCaseTags
EvaluationReport --produced from 1--> GoldenTestSet
EvaluationReport --references 0..1--> Baseline (via baseline_id)
EvaluationReport --contains 1..N--> EvalCaseResult --references 1--> TestCase
BaselineStore --tracks N--> Baseline (1 current + 多个 history per collection)
DeltaReport --references 2--> EvaluationReport (current + baseline)
```

---

## 5. Persistence Contracts(对应文件路径)

| Entity | Path | Format |
|---|---|---|
| GoldenTestSet (zh) | `tests/fixtures/golden_test_set_zh.json` | JSON |
| GoldenTestSet (en) | `tests/fixtures/golden_test_set_en.json` | JSON |
| GoldenTestSet (legacy 占位) | `tests/fixtures/golden_test_set.json` | JSON,US1 修复 |
| EvaluationReport(单份) | `logs/evaluation_reports/<run_id>.json` | JSON |
| EvaluationReport(索引) | `logs/evaluation_reports/index.jsonl` | JSONL,append-only |
| BaselineStore | `logs/baselines.json` | JSON,原子写 |
| 候选测试集(US2 中间产物) | `tests/fixtures/candidates/<lang>.json` | JSON |

具体 schema 见 `contracts/` 目录:
- [contracts/golden_test_set.schema.md](contracts/golden_test_set.schema.md)
- [contracts/evaluation_report.schema.md](contracts/evaluation_report.schema.md)
- [contracts/settings.evaluation.schema.md](contracts/settings.evaluation.schema.md)
