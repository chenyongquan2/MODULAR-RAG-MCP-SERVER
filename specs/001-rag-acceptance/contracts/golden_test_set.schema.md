# Contract: 金标测试集 JSON Schema

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 1

定义本 feature 用到的 3 类金标测试集文件结构。所有文件位于 `tests/fixtures/` 下。

---

## File Layout

| File | Purpose | Lifecycle |
|---|---|---|
| `tests/fixtures/golden_test_set.json` | US1 占位(MVP 烟雾测试) | KEEP,US1 修复 expected_chunk_ids + 加 tags |
| `tests/fixtures/golden_test_set_zh.json` | 中文金标(US2 产出) | NEW |
| `tests/fixtures/golden_test_set_en.json` | 英文金标(US2 产出) | NEW |
| `tests/fixtures/candidates/<lang>.json` | 合成候选(US2 中间产物) | NEW,精修后可清理(.gitignore 视情况添加) |

---

## 1. Final 金标 schema(zh / en / 占位 三类同 schema)

```jsonc
{
  "_schema_version": 1,
  "language": "zh",                            // "zh" | "en";占位文件可标 "mixed"
  "version": "v1.0",                           // 语义化版本;每次 refine 后递增
  "created_at": "2026-04-25T16:00:00+08:00",
  "source_corpus_collection": "mt5_docs_chinese",  // 该金标对应的 ChromaDB collection
  "test_cases": [
    {
      "query": "如何配置 Azure OpenAI?",
      "expected_chunk_ids": [
        "1a2b3c4d-uuid-real-1",                // 必须是 vector store 中真实存在的 ID
        "5e6f7g8h-uuid-real-2"
      ],
      "expected_sources": ["config_guide.pdf"],
      "ground_truth": "在 config/settings.yaml 的 llm 节点下,将 provider 设为 azure...",
      "tags": {                                // FR-014:必填,4 子字段必填
        "content_type": "text",                // "text" | "code" | "table" | "mixed"
        "difficulty": "simple",                // "simple" | "reasoning" | "multi_context"
        "language": "zh",                      // "zh" | "en"
        "doc_version": "v1"                    // 字符串;首版 "v1"
      }
    }
    // ... 39+ more cases for zh/en file (≥ 40 per language;FR-006)
  ]
}
```

---

## 2. 字段约束

| Field | Type | Constraint | Source |
|---|---|---|---|
| `_schema_version` | `int` | `>= 1` | — |
| `language` | `"zh"\|"en"\|"mixed"` | `mixed` 仅占位文件可用 | spec § FR-014 |
| `version` | `str` | 形如 `"v1.0"` / `"v1.1"` | data-model § 2.3 |
| `source_corpus_collection` | `str` | 非空 | data-model § 2.3 |
| `test_cases` | `list[TestCase]` | `len ∈ [40, 100]`(占位文件不限) | spec § FR-006 |
| `test_cases[].query` | `str` | strip 后非空 | spec § FR-006 |
| `test_cases[].expected_chunk_ids` | `list[str]` | 非空,所有 ID 必须在 `source_corpus_collection` 中存在(FR-007) | spec § FR-007 |
| `test_cases[].expected_sources` | `list[str]` | 可空 | spec § FR-006 |
| `test_cases[].ground_truth` | `str` | 非空(US2 后强制),US1 占位允许空 | spec § FR-006 |
| `test_cases[].tags` | `TestCaseTags` | 必填,4 子字段必填 | spec § FR-014 |
| `tags.content_type` | enum | ∈ `{"text", "code", "table", "mixed"}` | spec § FR-014 |
| `tags.difficulty` | enum | ∈ `{"simple", "reasoning", "multi_context"}` | spec § FR-014 |
| `tags.language` | enum | ∈ `{"zh", "en"}`,且必须等于父级 `language` 字段(占位文件除外) | spec § FR-014 |
| `tags.doc_version` | `str` | MVP 阶段固定 `"v1"`,未来 `"v2"` 等 | spec § FR-014 |

---

## 3. 难度分布约束(US2 验收 + Independent Test)

每份金标(zh / en):
- `simple` 占比 ≥ 10%
- `reasoning` 占比 ≥ 10%
- `multi_context` 占比 ≥ 10%

合成阶段建议分布(spec § Assumptions § 难度分布):simple 50% / reasoning 30% / multi_context 20%。

---

## 4. 候选测试集 schema(US2 中间产物,`candidates/<lang>.json`)

合成阶段产出,精修后丢弃。Schema 与 final 金标基本相同,但:
- `tags` 字段允许部分缺失(精修阶段补齐)
- `expected_chunk_ids` 可以是合成器返回的 retrieved IDs(精修阶段会经 backfill_chunk_ids.py 重新匹配)
- 多一个 `_synthesis_metadata` 字段记录合成工具与参数:

```jsonc
{
  "_schema_version": 1,
  "language": "zh",
  "_synthesis_metadata": {
    "generator": "ragas.testset.TestsetGenerator",
    "ragas_version": "0.1.21",
    "judge_llm_identifier": "glm:glm-4",
    "embedding_identifier": "openai:text-embedding-3-small",
    "distribution": {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.2},
    "synthesized_at": "2026-04-25T15:00:00+08:00"
  },
  "test_cases": [
    /* 同 final schema,但 tags 部分字段可缺失 */
  ]
}
```

---

## 5. expected_chunk_ids 校验流程(FR-007)

`EvalRunner._load_test_cases()` 加载金标后,**在跑评估之前**:

1. 从 vector store(`HybridSearch._chroma_client` 或类似)获取 `source_corpus_collection` 的全部 chunk ID 集合
2. 对每条 case 检查 `expected_chunk_ids` ⊆ 该集合
3. 任一 ID 缺失 → 立刻抛 `ValueError`,错误信息格式:
   ```
   golden_test_set chunk_id missing: case[<idx>] '<query[:50]>...' references chunk_id '<id>' not in collection '<col>'
   ```
4. 所有 ID 通过 → 继续评估
5. **配置 `chunk_id_validation: false` 时跳过此校验**(用于调试)

---

## 6. 示例:US1 阶段占位文件的修复(以现有 golden_test_set.json 为基础)

**Before**(L1 中 4 条占位):
```json
{
  "test_cases": [
    {
      "query": "如何配置 Azure OpenAI?",
      "expected_chunk_ids": ["chunk_azure_001", "chunk_azure_002"],   // 占位 ID
      "expected_sources": ["config_guide.pdf"],
      "ground_truth": "在 config/settings.yaml 的 llm 节点下..."
    }
  ]
}
```

**After**(US1 修复;只动 4 条,加 `_schema_version` / `language` / `version` / `tags`,把 `expected_chunk_ids` 替换为 ChromaDB 中真实 ID):

```json
{
  "_schema_version": 1,
  "language": "mixed",
  "version": "v0.1-smoke",
  "created_at": "2026-04-25T16:00:00+08:00",
  "source_corpus_collection": "default",
  "test_cases": [
    {
      "query": "如何配置 Azure OpenAI?",
      "expected_chunk_ids": ["1a2b3c4d-real-uuid-1", "5e6f7g8h-real-uuid-2"],
      "expected_sources": ["config_guide.pdf"],
      "ground_truth": "在 config/settings.yaml 的 llm 节点下,将 provider 设为 azure...",
      "tags": {
        "content_type": "text",
        "difficulty": "simple",
        "language": "zh",
        "doc_version": "v1"
      }
    }
    /* ... 其余 3 条同样升级 ... */
  ]
}
```

---

## 7. 与既有 EvalCase 的兼容性

`src/observability/evaluation/eval_runner.py:EvalCase` 当前字段:

```python
@dataclass
class EvalCase:
    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str] = field(default_factory=list)
    ground_truth: str = ""
```

本 feature 后扩展为:

```python
@dataclass
class EvalCase:
    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str] = field(default_factory=list)
    ground_truth: str = ""
    tags: Optional[TestCaseTags] = None  # NEW;US1 占位允许 None,US2 后必填
```

`tags=None` 时 by-tag 聚合自动跳过该用例(不影响主聚合)。
