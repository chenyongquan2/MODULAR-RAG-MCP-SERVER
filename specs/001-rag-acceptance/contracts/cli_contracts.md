# Contract: CLI 入口契约

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 1

定义本 feature 的 4 个 `scripts/` 入口的命令行契约:输入参数、退出码、stdout/stderr 行为。

---

## 1. `scripts/evaluate.py`(MODIFY)

**Purpose**:运行评估并产出 EvaluationReport;若已有当前基线,自动附 delta。

### Synopsis

```bash
python scripts/evaluate.py \
  [--test-set <path>] \
  [--top-k <int>] \
  [--collection <name>] \
  [--lang <zh|en>] \
  [--generate-answers | --no-generate-answers] \
  [--archive | --no-archive] \
  [--pretty] \
  [--exit-on-fail]
```

### Arguments

| Flag | Type | Default | Behavior |
|---|---|---|---|
| `--test-set` | str | `settings.evaluation.golden_test_set` | 金标 JSON 路径(优先级高于 `--lang`) |
| `--top-k` | int | `settings.retrieval.top_k_final` | 每条 query 召回数量 |
| `--collection` | str | `settings.vector_store.collection_name` | 评估 collection |
| `--lang` | enum | None | `zh` / `en`;有则从 `settings.evaluation.golden_test_sets_by_lang[<lang>]` 取 path,与 `--test-set` 互斥 |
| `--generate-answers` / `--no-generate-answers` | bool | auto-on if `"ragas" in backends` | 是否走 ResponseBuilder 生成 answer(RAGAS faithfulness 等需要) |
| `--archive` / `--no-archive` | bool | True | 是否归档到 `logs/evaluation_reports/` |
| `--pretty` | flag | false | stdout JSON 缩进 |
| `--exit-on-fail` | flag | false | `acceptance_status="fail"` 时退出码 1(用于 CI) |

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | 评估成功(且若启用 `--exit-on-fail`,acceptance_status=pass) |
| 1 | 校验错误(ValueError;含 FR-007 chunk_id 不存在) |
| 2 | 运行时错误(RuntimeError;含 Judge LLM 不可达) |
| 3 | `--exit-on-fail` 启用 + acceptance_status=fail |

### Output

- **stdout**:完整 EvaluationReport JSON([见 schema](evaluation_report.schema.md))。
- **stderr**:结构化日志(`get_logger()` 默认走 stderr),含进度提示如 `Evaluating case 12/80...`、`Validation failed: ...`、`Acceptance status: pass`。
- **filesystem**(若 `--archive`):
  - `logs/evaluation_reports/<run_id>.json`(完整报告)
  - `logs/evaluation_reports/index.jsonl`(追加一行精简索引)

### 错误信息样本

```
Error: golden_test_set chunk_id missing: case[3] '如何配置 vector_store...'
       references chunk_id 'chunk_placeholder_xxx' not in collection 'mt5_docs_chinese'
       (set evaluation.chunk_id_validation=false to skip this check)
```

---

## 2. `scripts/synthesize_testset.py`(NEW)

**Purpose**:从已摄入的真实 MT5 语料用 RAGAS TestsetGenerator 自动合成 (question, ground_truth, source_contexts) 候选用例(US2 step 1)。

### Synopsis

```bash
python scripts/synthesize_testset.py \
  --collection <name> \
  --lang <zh|en> \
  [--target-count <int>] \
  [--output <path>] \
  [--distribution <simple>:<reasoning>:<multi_context>]
```

### Arguments

| Flag | Type | Default | Behavior |
|---|---|---|---|
| `--collection` | str | **必填** | ChromaDB collection 名(中/英) |
| `--lang` | enum | **必填** | `zh` / `en` |
| `--target-count` | int | 100 | 合成候选数(精修后会缩到 ≥ 40) |
| `--output` | str | `tests/fixtures/candidates/<lang>.json` | 候选输出路径 |
| `--distribution` | str | `0.5:0.3:0.2` | 难度分布(simple:reasoning:multi_context),逗号或冒号分隔 |

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | 合成成功 |
| 1 | 配置错误(collection 不存在 / Judge 不可达 / `target-count <= 0`) |
| 2 | RAGAS 合成内部错误 |

### Output

- **stdout**:总结摘要(`Synthesized 100 candidates -> tests/fixtures/candidates/zh.json (simple=52, reasoning=29, multi_context=19)`)
- **stderr**:进度日志
- **filesystem**:`tests/fixtures/candidates/<lang>.json`([candidate schema](golden_test_set.schema.md#4-候选测试集-schemaus2-中间产物candidatesljsonjson))

---

## 3. `scripts/refine_testset.py`(NEW)

**Purpose**:对候选用例做 keep / edit / drop 最小工具操作,产出 final 金标(US2 step 2)。MVP 提供 CLI 模式;若时间允许,可附加 Streamlit 嵌入页(non-blocking,UI 不实现也不阻塞 US2 完成)。

### Synopsis

```bash
python scripts/refine_testset.py \
  --input <path> \
  [--output <path>] \
  [--mode <interactive|batch>]
```

### Arguments

| Flag | Type | Default | Behavior |
|---|---|---|---|
| `--input` | str | **必填** | 候选测试集路径 |
| `--output` | str | `tests/fixtures/golden_test_set_<lang>.json` | 精修后金标输出 |
| `--mode` | enum | `interactive` | `interactive`:逐条 prompt y(keep) / e(edit) / d(drop) / s(skip);`batch`:从 `--actions-file` 读批处理脚本(MVP 不实现) |

### Interactive 流程

每条 case 显示:`query` + `ground_truth` + `expected_chunk_ids[].text 前 100 字`,prompt 选择:
- `y` / `enter` → keep(进 final)
- `e` → 启动 `$EDITOR` 编辑当前 case JSON,保存后 keep
- `d` → drop
- `s` → 跳过(本轮不动,留待下一轮 refine)
- `q` → 退出并保存当前进度到 output

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | 精修完成,final 金标已写出 |
| 1 | 输入文件不存在或非法 |
| 130 | 用户 Ctrl-C(进度部分保存) |

### Output

- **stdout**:简短总结(`Refined: 80 kept, 15 edited, 5 dropped -> tests/fixtures/golden_test_set_zh.json`)
- **filesystem**:`tests/fixtures/golden_test_set_<lang>.json`(final 金标)

---

## 4. `scripts/backfill_chunk_ids.py`(NEW)

**Purpose**:对精修后还没有 expected_chunk_ids(或 expected_chunk_ids 为占位)的金标用例,通过 `EmbeddingFactory` + vector store 语义匹配回填 expected_chunk_ids(US2 step 3,FR-007)。

### Synopsis

```bash
python scripts/backfill_chunk_ids.py \
  --input <path> \
  --collection <name> \
  [--top-k <int>] \
  [--threshold <float>] \
  [--dry-run]
```

### Arguments

| Flag | Type | Default | Behavior |
|---|---|---|---|
| `--input` | str | **必填** | 金标文件(in-place 更新) |
| `--collection` | str | **必填** | 用于匹配的 ChromaDB collection |
| `--top-k` | int | 5 | 每条 ground_truth 取 top-K 候选 chunk_ids |
| `--threshold` | float | 0.6 | 余弦相似度下限,< 阈值的 chunk 不入 expected_chunk_ids |
| `--dry-run` | flag | false | 只打印将要回填的内容,不修改文件 |

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | 回填成功 |
| 1 | 输入错误(文件 / collection 不存在) |
| 2 | 匹配率过低警告(< 90% 的 case 都没匹配到符合阈值的 chunk;退出但不写) |

### Output

- **stdout**:总结(`Backfilled 78/80 cases (97.5%); 2 cases below similarity threshold 0.6 (need manual review)`)
- **stderr**:逐条 verbose 日志(可控)
- **filesystem**:in-place 修改 `--input`(`--dry-run` 时不修改)

---

## 5. 通用约定

### 退出码语义

所有 4 个脚本统一:
- `0` = success
- `1` = 用户输入 / 配置 / 文件 / schema 错误(ValueError)
- `2` = 内部运行时错误(RuntimeError;包括 LLM API 失败、文件 I/O 失败)
- `3` = 业务结果 fail(仅 `evaluate.py --exit-on-fail` 使用)
- `130` = 用户中断(SIGINT,Ctrl-C)

### 日志惯例

- 所有脚本入口顶部:`logger = get_logger(__name__)`
- 不用 `print()` 输出诊断信息;**唯有 stdout JSON 报告(evaluate.py)和 stdout 总结摘要(其他 3 个)允许直接 print**——这符合宪法 § V("`src/` 下零 print";`scripts/` 例外允许人类可读输出)
- 所有 ERROR 级别消息附完整 traceback(`logger.error(..., exc_info=True)`)
- INFO 级别记录关键路径决策(`logger.info("Acceptance status: %s", status)`)

### Settings 加载

所有脚本第一行实操:
```python
from src.core.settings import load_settings
settings = load_settings()  # 启动期校验在此完成,失败抛 ValueError → 进 except 块 → 退出码 1
```

### 与现有 evaluator/factory 的接口契约

`evaluate.py` 沿用现有调用链:
```python
hybrid_search = HybridSearch(settings)
evaluator = EvaluatorFactory.create(settings)
runner = EvalRunner(settings, hybrid_search, evaluator, response_builder)
report = runner.run(test_set_path, top_k, filters)
```

本 feature 不改 `EvaluatorFactory.create()` 的签名,但改其内部行为(让它根据 `settings.evaluation.backends` 返回 CompositeEvaluator / RagasEvaluator / CustomEvaluator,并在 RagasEvaluator 内注入 Judge / embedding)。

### CLI 与 dashboard 的边界

- CLI 侧重**自动化与 CI 友好**(可控的退出码、JSON 出 stdout)
- Dashboard 侧重**人类可视化**(读 `logs/evaluation_reports/`)
- 不允许 CLI 命令直接调 Streamlit 或 dashboard 做"标记基线"等动作;dashboard 内的标记基线最终也是写到同一份 `baselines.json`(由 `BaselineManager` 抽象层封装)
