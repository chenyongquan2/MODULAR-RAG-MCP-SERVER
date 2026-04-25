# Contract: `EvaluationReport` JSON Schema

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 1

定义本 feature 输出的评估报告 JSON 结构。两个落盘位置:
- 单份完整报告:`logs/evaluation_reports/<run_id>.json`(归档)
- 累积索引:`logs/evaluation_reports/index.jsonl`(JSONL,每行一条精简元数据,供 dashboard 趋势页扫描)

`scripts/evaluate.py` 同时把完整报告打印到 stdout(向后兼容既有用法)。

---

## 1. 完整报告 schema(`<run_id>.json`)

```jsonc
{
  "_schema_version": 1,

  // ── 元数据 ──
  "run_id": "550e8400-e29b-41d4-a716-446655440000",       // UUID4,主键
  "collection": "mt5_docs_chinese",                        // 评估的 collection
  "test_set_path": "./tests/fixtures/golden_test_set_zh.json",
  "test_set_version": "v1.0",                              // 来自 GoldenTestSet.version
  "created_at": "2026-04-25T16:30:00+08:00",               // ISO-8601

  // ── Provider identifiers(FR-016 / FR-017) ──
  "judge_llm_identifier": "glm:glm-4",                     // <provider>:<model>;custom-only 评估时为 null
  "embedding_identifier": "openai:text-embedding-3-small", // 总是非空(评估流程必有 embedding)

  // ── 阈值快照(FR-013) ──
  "acceptance_thresholds_snapshot": {
    "ragas__context_recall": 0.70,
    "ragas__context_precision": 0.65,
    "ragas__faithfulness": 0.85,
    "ragas__answer_relevancy": 0.75,
    "custom__hit_rate": 0.60,
    "custom__mrr": 0.55,
    "custom__recall": 0.70,
    "custom__ndcg": 0.55
  },

  // ── 验收结论(FR-013) ──
  "acceptance_status": "pass",  // "pass" | "fail"

  // ── 总体规模 ──
  "total_cases": 80,
  "degraded_case_count": 2,     // FR-001 NaN 用例数;SC-006 要求 ≤ 5%

  // ── 主聚合指标(8 项;参与 acceptance_status) ──
  "aggregate_metrics": {
    "ragas__context_recall": 0.74,
    "ragas__context_precision": 0.68,
    "ragas__faithfulness": 0.88,
    "ragas__answer_relevancy": 0.79,
    "custom__hit_rate": 0.62,
    "custom__mrr": 0.58,
    "custom__recall": 0.72,
    "custom__ndcg": 0.57
  },

  // ── by-tag 切片子聚合(FR-015;不参与 pass/fail) ──
  "aggregate_metrics_by_tag": {
    "content_type": {
      "text": {
        "ragas__context_recall": 0.76,
        "ragas__faithfulness": 0.89,
        "custom__hit_rate": 0.64
        // ... 其余 5 项
      },
      "code": {
        // 样本量 < tag_slice_min_samples 时:
        "_skipped_reason": "n_samples=3<5",
        "ragas__context_recall": null,
        "ragas__faithfulness": null,
        "custom__hit_rate": null
        // 全部指标 = null
      }
    },
    "difficulty": {
      "simple": { /* ... 8 项 ... */ },
      "reasoning": { /* ... 8 项 ... */ },
      "multi_context": { "_skipped_reason": "n_samples=4<5", /* 全 null */ }
    }
  },

  // ── 顶层方便字段(向后兼容既有 EvalReport) ──
  "hit_rate": 0.62,
  "mrr": 0.58,
  "source_hit_rate": 0.85,

  // ── 单条用例结果 ──
  "case_results": [
    {
      "query": "如何配置 Azure OpenAI?",
      "tags": {
        "content_type": "text",
        "difficulty": "simple",
        "language": "zh",
        "doc_version": "v1"
      },
      "expected_chunk_ids": ["uuid-real-1", "uuid-real-2"],
      "expected_sources": ["config_guide.pdf"],
      "retrieved_chunk_ids": ["uuid-real-1", "uuid-real-7"],
      "retrieved_sources": ["config_guide.pdf"],
      "hit": true,
      "reciprocal_rank": 1.0,
      "source_hit": true,
      "answer": "在 config/settings.yaml 的 llm 节点下...",
      "contexts": ["text-1...", "text-7..."],
      "ground_truth": "在 config/settings.yaml 的 llm 节点下...",
      "metrics": {
        "ragas__context_recall": 0.95,
        "ragas__context_precision": 0.80,
        "ragas__faithfulness": 0.92,
        "ragas__answer_relevancy": 0.86,
        "custom__hit_rate": 1.0,
        "custom__mrr": 1.0,
        "custom__recall": 0.5,
        "custom__ndcg": 1.0
      }
    }
    // ... 其余 79 条
  ],

  // ── Baseline & Delta(若该 collection 已有当前基线;否则下面四个字段 = null) ──
  "baseline_id": "uuid-of-baseline-report",
  "delta_aggregate_metrics": {
    "ragas__context_recall": +0.04,    // 当前 - baseline,正数 = 提升
    "ragas__faithfulness": -0.02,
    // ... 其余 6 项
  },
  "per_tag_delta": {
    "content_type": {
      "text": {
        "ragas__context_recall": +0.05
        // ... 8 项
      },
      "code": null  // baseline 当时也 skipped 或当前 skipped → 整 entry 为 null
    },
    "difficulty": { /* ... */ }
  },
  "delta_hit_rate": +0.04,
  "delta_mrr": +0.02
}
```

---

## 2. 索引文件 schema(`index.jsonl`,每行一条)

```jsonc
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "collection": "mt5_docs_chinese",
  "created_at": "2026-04-25T16:30:00+08:00",
  "acceptance_status": "pass",
  "judge_llm_identifier": "glm:glm-4",
  "embedding_identifier": "openai:text-embedding-3-small",
  "total_cases": 80,
  "is_baseline": true,                 // 当前是否被标为基线(可能随后续标记/取消而变化;dashboard 读时以 baselines.json 为准,index 仅供快速过滤)
  "report_path": "logs/evaluation_reports/550e8400-e29b-41d4-a716-446655440000.json"
}
```

**演进**:`index.jsonl` 是 **append-only** + **never-mutated**;`is_baseline` 字段在 dashboard 渲染时与 `baselines.json` 的 current 比对取最新值,而非依赖 index 自己的状态。

---

## 3. 字段约束总览

| 字段 | Type | Constraint | Source |
|---|---|---|---|
| `_schema_version` | `int` | `>= 1` | research.md § Decision 7 |
| `run_id` | `str (UUID4)` | 唯一 | research.md § Decision 3 |
| `collection` | `str` | 非空 | spec § FR-002 |
| `acceptance_status` | `"pass"\|"fail"` | 当且仅当 8 项主聚合全部 ≥ 阈值 → "pass" | spec § FR-013 |
| `acceptance_thresholds_snapshot` | `dict[str, float]` | 必含全部 8 个 metric key | spec § FR-013 |
| `aggregate_metrics` | `dict[str, float]` | 8 个 key,值 ∈ `[0, 1]` 或 NaN(NaN 转 null) | spec § FR-001 |
| `aggregate_metrics_by_tag.<dim>.<value>` | `dict[str, float\|null]` | 样本 < N 时所有 metric = null,且 entry 含 `_skipped_reason` | spec § FR-015 |
| `degraded_case_count` | `int` | `>= 0`,占比 ≤ 5%(SC-006) | spec § Edge Cases |
| `case_results[].metrics` | `dict[str, float]` | 8 个 key | spec § FR-001 |
| `case_results[].tags` | `TestCaseTags` | 4 子字段必填 | spec § FR-014 |
| `delta_aggregate_metrics` | `Optional[dict]` | 仅当 baseline 存在 | spec § FR-009 |

---

## 4. NaN / null 编码规则

- 单条用例 metric NaN(显式降级,FR-001):JSON 输出 `null`(JSON 不支持 NaN,统一用 null)
- 聚合时遇到 NaN:跳过该用例**不计入分母**(`degraded_case_count++`),不让 NaN 污染均值
- 切片样本不足:见 § 1 的 `_skipped_reason` 模式

---

## 5. 与 dashboard 的契约

Dashboard 读 `index.jsonl` 做**列表/趋势/筛选**,读 `<run_id>.json` 做**详情/case-level drill-down**;不直接读 `baselines.json`(由 BaselineManager 抽象层封装查询)。

dashboard 视觉规则(spec § Clarifications Q3):
- `acceptance_status="pass"` → 绿色徽标
- `acceptance_status="fail"` → 红色徽标 + 提示 hover "未达 FR-013 阈值"
- 若 baseline 自己是 fail → 列表项加灰色背景(早期参考点)

---

## 6. 与 spec 字段映射

| spec 字段 | report 字段 |
|---|---|
| FR-001 8 项指标 | `aggregate_metrics.*` |
| FR-007 校验(没字段;失败时 EvalRunner 抛错,不出 report) | — |
| FR-013 阈值清单 + pass/fail | `acceptance_thresholds_snapshot` + `acceptance_status` |
| FR-015 切片 | `aggregate_metrics_by_tag.<dim>.<value>.*` |
| FR-016 Judge | `judge_llm_identifier` |
| FR-017 Embedding | `embedding_identifier` |
| Key Entities § Baseline | 见 contracts/(本文件)的 Baseline & Delta 区段 |
