# Contract: `settings.yaml` `evaluation` 段最终 schema

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 1

定义本 feature 完成后,`config/settings.yaml` `evaluation` 段的完整 schema。所有字段在 [data-model.md § 1](../data-model.md) 有 Python 端 dataclass 定义;本文件给出 YAML 端的对应形式 + 校验规则 + 示例。

---

## Full Example

```yaml
# 评估配置(本 feature 后的最终形态)
evaluation:
  _schema_version: 1

  # 启用的评估后端(顺序无关;custom 永久启用,ragas 视场景启用)
  backends:
    - custom
    - ragas

  # 占位金标(US1 阶段使用;US2 完成后由 golden_test_sets_by_lang 主导)
  golden_test_set: ./tests/fixtures/golden_test_set.json

  # 中英分语种金标(US2 完成后填充)
  golden_test_sets_by_lang:
    zh: ./tests/fixtures/golden_test_set_zh.json
    en: ./tests/fixtures/golden_test_set_en.json

  # Judge LLM(仅 ragas backend 启用时必须填)
  # 复用 LLMFactory 的 5 个 provider:glm / azure / openai / ollama / deepseek
  judge_llm:
    provider: glm
    model: glm-4
    api_key: ${GLM_API_KEY}
    base_url: ${GLM_BASE_URL}
    temperature: 0.0
    request_timeout_sec: 60

  # 评估流程使用的 embedding(默认空 = 复用 production query 的 embedding)
  # 如需为评估专门换 embedding,在此填写;建议保持空以避免 train-eval skew(FR-017)
  embedding:
    provider: ""        # 空 = 复用 settings.embedding.provider
    model: ""           # 空 = 复用 settings.embedding.model
    api_key: ""
    base_url: null

  # 8 个聚合指标的 pass/fail 阈值(默认值即 spec § FR-013 业界参考值)
  acceptance_thresholds:
    ragas__context_recall: 0.70
    ragas__context_precision: 0.65
    ragas__faithfulness: 0.85
    ragas__answer_relevancy: 0.75
    custom__hit_rate: 0.60
    custom__mrr: 0.55
    custom__recall: 0.70
    custom__ndcg: 0.55

  # by-tag 切片维度(MVP 白名单;只允许 content_type / difficulty)
  by_tag_dimensions:
    - content_type
    - difficulty

  # 切片样本量下限(< 此值的切片在报告中标 null + _skipped_reason)
  tag_slice_min_samples: 5

  # 评估报告归档目录(每次评估产出 <run_id>.json + 累积 index.jsonl)
  report_archive_dir: ./logs/evaluation_reports

  # 基线标记单文件(原子写)
  baseline_store_path: ./logs/baselines.json

  # FR-007:expected_chunk_ids 存在性校验(通常应 true;调试时可 false 跳过)
  chunk_id_validation: true
```

---

## Field Validation Rules

`load_settings()` 启动期完成,**任一规则失败立即抛 `ValueError`**(宪法 § III)。

| Field | Rule | Error Example |
|---|---|---|
| `_schema_version` | 必须 `>= 1` | `"evaluation._schema_version=0 invalid (>= 1 required)"` |
| `backends` | 元素 ∈ `{"custom", "ragas"}`;`"custom"` 必须存在 | `"evaluation.backends contains unknown backend: 'deepeval'"` |
| `golden_test_set` | 文件存在且可读(US1 阶段必填) | `"evaluation.golden_test_set not readable: <path>"` |
| `golden_test_sets_by_lang` | 若提供,key ⊆ `{"zh", "en"}`,value 必须可读 | `"evaluation.golden_test_sets_by_lang['zh'] not readable: <path>"` |
| `judge_llm.provider` | `"ragas" in backends` 时必须填,且 ∈ LLMFactory 注册列表 | `"evaluation.judge_llm.provider='claude' not in LLMFactory registry"` |
| `judge_llm.model` | 非空 | `"evaluation.judge_llm.model cannot be empty"` |
| `judge_llm.temperature` | ∈ `[0, 2]` | `"evaluation.judge_llm.temperature=3.0 out of range [0, 2]"` |
| `judge_llm.request_timeout_sec` | `> 0` | `"evaluation.judge_llm.request_timeout_sec=-1 must be > 0"` |
| `embedding.provider` | 空 或 ∈ EmbeddingFactory 注册列表 | `"evaluation.embedding.provider='cohere' not in EmbeddingFactory registry"` |
| `acceptance_thresholds.<metric>` | 每个值 ∈ `[0, 1]` | `"evaluation.acceptance_thresholds.faithfulness=1.5 out of range [0, 1]"` |
| `acceptance_thresholds` | 必须包含全部 8 个指标 key(default 自动填) | `"evaluation.acceptance_thresholds missing keys: ['custom__ndcg']"` |
| `by_tag_dimensions` | 必须 ⊆ `{"content_type", "difficulty"}` | `"evaluation.by_tag_dimensions contains unknown dimension: 'language'"` |
| `tag_slice_min_samples` | `>= 1` | `"evaluation.tag_slice_min_samples=0 must be >= 1"` |
| `report_archive_dir` | 父目录可写 | `"evaluation.report_archive_dir parent not writable: <path>"` |
| `baseline_store_path` | 父目录可写 | `"evaluation.baseline_store_path parent not writable: <path>"` |
| `chunk_id_validation` | bool | TypeError if not bool |

---

## Backward Compatibility(本 feature 实施前 vs 后)

**Before**(当前 settings.yaml):
```yaml
evaluation:
  backends:
    - custom
  golden_test_set: ./tests/fixtures/golden_test_set.json
```

**After**(本 feature 实施后):见上方 Full Example。

**Migration**:
- 既有 2 字段 (`backends` / `golden_test_set`) 字段名不变,语义不变 → **零中断**
- 新字段全有合理 default → 老配置加载不报错;但若用户启用了 `"ragas" in backends`,会因 `judge_llm.provider` 缺失而启动期报错(快速失败,符合 § III)
- `_schema_version` 缺失时默认按 `1` 处理(向后兼容)

---

## 与项目其他 settings 段的关系

- `evaluation.embedding` 留空 → 自动 fallback 到顶层 `embedding`(production query 用的同一份)
- `evaluation.judge_llm` 与顶层 `llm`(production answer generation)**完全独立**,可以异同;典型场景:production 用 GLM-4 生成答案,judge 也用 GLM-4(但用更低 temperature 0.0 提高判分稳定性)
- `evaluation.report_archive_dir` 与 `observability.log_file` 是兄弟目录(都在 `logs/` 下)

---

## Schema 演进策略

未来若 `acceptance_thresholds` 需要从 `dict[metric, float]` 升级为 `dict[metric, {value, severity}]`,流程:
1. 新 feature 在 spec 中说明诉求
2. plan 阶段把 `_schema_version` 升到 `2`
3. `load_settings()` 见 `_schema_version=2` 时按新结构解析;见 `_schema_version=1` 时报错并提示"请运行 migration 工具"(由该 feature 的 tasks 提供)

本 feature 不实现 migration 工具,只埋下钩子。
