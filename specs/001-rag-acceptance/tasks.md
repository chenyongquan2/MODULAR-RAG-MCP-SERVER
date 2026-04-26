---
description: "Task list for Feature-001: RAG 质量验收(中英双语基线)"
---

# Tasks: RAG 质量验收(中英双语基线)

**Input**: Design documents from `specs/001-rag-acceptance/`
**Prerequisites**: [plan.md](plan.md) + [spec.md](spec.md) + [research.md](research.md) + [data-model.md](data-model.md) + [contracts/](contracts/) + [quickstart.md](quickstart.md)

**Tests**:**强制包含**(宪法 § VII NON-NEGOTIABLE — 每个实现任务必须配套 unit test)。

**Organization**: 任务按 user story(US1/US2/US3)组织,确保每个 story 可独立实施、独立测试、独立交付增量。

## Format

`[ID] [P?] [Story?] Description with file path (refs <spec/data-model/research/contract>)`

- **[P]**:可并行(不同文件,无对未完成任务的依赖)
- **[Story]**:US1 / US2 / US3,Setup / Foundational / Polish 阶段无 Story label
- **refs**:可追溯性锚点(宪法 § X NON-NEGOTIABLE)。实施期 commit message **必须** 引用本任务 ID(`refs T-XXX` 或 `closes T-XXX`)。

---

## Phase 1: Setup(共享基础设施)

**Purpose**:固定关键依赖版本,确保 Feature-001 全周期使用同一 RAGAS 版本,保证基线可比性(research.md § Decision 1)。

- [x] T001 在 [pyproject.toml](../../pyproject.toml) 的 dependencies 中固定 `ragas==0.1.21`(或最终选定的精确版本)与 `langchain-openai`(可能还需 `langchain-community` 视 RAGAS 版本要求)+ 在 README 该段加注释"RAGAS 版本是 Feature-001 基线锚定点,擅自升级会破坏 SC-005/SC-008 可比性",运行 `pip install -e ".[dev]"` 同步本地环境(refs research § Decision 1)

---

## Phase 2: Foundational(blocking prerequisites)

**Purpose**:所有 user story 共同依赖的基础类型与配置。**所有 user story 在本阶段完成前不能开始**。

**⚠️ CRITICAL**: 完成 Phase 2 前禁止进入 Phase 3+。

- [x] T002 [P] 扩展 [src/core/types.py](../../src/core/types.py):新增 `TestCaseTags` / `TestCase` / `GoldenTestSet` / `Baseline` / `BaselineStore` / `DeltaReport` 数据类与 `AcceptanceStatus` 枚举(refs [data-model.md § 2](data-model.md))
- [x] T003 [P] 扩展 [src/core/settings.py](../../src/core/settings.py):新增 `JudgeLLMSettings` / `EvaluationEmbeddingSettings` / `AcceptanceThresholds` 子 dataclass,扩展 `EvaluationSettings` 加 `_schema_version` / `golden_test_sets_by_lang` / `judge_llm` / `embedding` / `acceptance_thresholds` / `by_tag_dimensions` / `tag_slice_min_samples` / `report_archive_dir` / `baseline_store_path` / `chunk_id_validation` 字段(refs [data-model.md § 1](data-model.md))
- [x] T004 在 [src/core/settings.py](../../src/core/settings.py) 实现 `_validate_evaluation_settings(settings)` 启动期校验函数并接入 `load_settings()`,覆盖 16 条 [校验规则](contracts/settings.evaluation.schema.md#field-validation-rules);非法值立即抛 `ValueError`(refs [research § Decision 7](research.md), [contracts/settings.evaluation.schema.md](contracts/settings.evaluation.schema.md);依赖 T003)
- [x] T005 [P] 扩展 [config/settings.yaml](../../config/settings.yaml) 的 `evaluation` 段,从当前 2 字段扩到完整 schema(参照 [contracts/settings.evaluation.schema.md § Full Example](contracts/settings.evaluation.schema.md))(refs [contracts/settings.evaluation.schema.md](contracts/settings.evaluation.schema.md))
- [x] T006 [P] 在 [src/observability/evaluation/_ragas_wrappers.py](../../src/observability/evaluation/_ragas_wrappers.py) 新增 `build_ragas_judge(settings)` 与 `build_ragas_embedding(settings)` 包装层函数(实施时改为单独 helper 模块,而非塞进 ragas_evaluator.py;延迟 import ragas 让 custom-only 评估场景不必装 ragas):把 `LLMFactory.create()` / `EmbeddingFactory.create()` 实例适配为 LangChain `BaseLLM` / `Embeddings` 接口,再用 RAGAS `LangchainLLMWrapper` / `LangchainEmbeddingsWrapper` 包一层供 metric 注入(refs [research § Decision 2](research.md), [research § Decision 6](research.md))
- [x] T007 [P] 测试 [tests/unit/test_evaluation_settings.py](../../tests/unit/test_evaluation_settings.py):22 用例覆盖 — 默认值正确性(8 个 acceptance_thresholds 业界参考值 + Judge GLM-4 默认 + chunk_id_validation 等)+ 12 个 negative cases(provider/temperature/timeout/by_tag_dimensions/thresholds 越界/min_samples 等违规 + ragas backend 未配 judge + 父目录不可写)+ load_settings 端到端 + AcceptanceThresholds.to_dict;**全部 22 用例通过**(refs T003, T004,宪法 § VII)

**Checkpoint**:Foundation 就绪,US1/US2/US3 可启动。

---

## Phase 3: User Story 1 - 端到端跑通评估管线(Priority: P1)🎯 MVP

**Goal**:在不合成新测试集的前提下,启用 RAGAS backend、修复占位测试集、跑通 8 项指标全管线、产出含 acceptance_status 的 EvaluationReport。

**Independent Test**:跑 [quickstart.md Path A](quickstart.md) 10 步,stdout JSON 含全 8 项指标(0~1 数字)+ `acceptance_status` + `judge_llm_identifier` + `embedding_identifier` + `acceptance_thresholds_snapshot` 字段;`logs/evaluation_reports/` 写入 `<run_id>.json` + `index.jsonl`。

### Implementation for User Story 1

- [ ] T008 [US1] 改造 [src/observability/evaluation/ragas_evaluator.py](../../src/observability/evaluation/ragas_evaluator.py) 中 `RagasEvaluator`:`__init__()` 调用 T006 的 `_build_ragas_judge(settings)` + `_build_ragas_embedding(settings)`,把 4 个 RAGAS metrics(Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall)的 `.llm` 与 `.embeddings` 全部注入同一对实例;新增 `get_judge_identifier()` 返回 `"<provider>:<model>"` 字符串、`get_embedding_identifier()` 同理;移除任何环境变量直读或 hardcoded provider 行为(refs [spec FR-016](spec.md), [spec FR-017](spec.md);依赖 T006)
- [ ] T009 [P] [US1] 新增 [src/observability/evaluation/threshold_evaluator.py](../../src/observability/evaluation/threshold_evaluator.py):实现 `ThresholdEvaluator` 类,接收 `acceptance_thresholds: dict[str, float]` + `aggregate_metrics: dict[str, float]`,`evaluate(metrics) -> AcceptanceStatus` 返回 `PASS`(全 8 项 ≥ 各自阈值)或 `FAIL`;附 `get_failed_metrics(metrics) -> list[str]` 辅助方法供面板展示(refs [spec FR-013](spec.md), [data-model § 2.4](data-model.md))
- [ ] T010 [US1] 改造 [src/observability/evaluation/eval_runner.py](../../src/observability/evaluation/eval_runner.py):
  - `EvalCase` 加 `tags: Optional[TestCaseTags] = None` 字段(US1 占位允许 None)
  - `EvalReport` 大扩展:加 `run_id` / `collection` / `test_set_version` / `created_at` / `acceptance_thresholds_snapshot` / `acceptance_status` / `judge_llm_identifier` / `embedding_identifier` / `degraded_case_count` / `aggregate_metrics_by_tag` 字段
  - `_load_test_cases()` 解析 `tags` 字段 + `_schema_version` 校验
  - `run()` 入口加 `_validate_chunk_ids_exist()`(FR-007;`settings.evaluation.chunk_id_validation=True` 时启用,未通过抛 `ValueError` 含 case index + 缺失 chunk_id);加 `_aggregate_by_tag(case_results, dimension)` helper(FR-015;< `tag_slice_min_samples` 跳过 + `_skipped_reason`)
  - 收集 NaN metrics → `degraded_case_count++` 且不计入分母(避免 NaN 污染均值)
  - 调用 `ThresholdEvaluator` 计算 `acceptance_status`,从 `evaluator.get_judge_identifier()` / `get_embedding_identifier()` 取标识(若 evaluator 不支持则记 `null`,作为 custom-only 评估场景)
  - 加 `_archive_report(report)` 写 `settings.evaluation.report_archive_dir/<run_id>.json` + 追加 `index.jsonl` 一行精简元数据
  (refs [spec FR-007](spec.md), [spec FR-013](spec.md), [spec FR-015](spec.md), [spec FR-016](spec.md), [spec FR-017](spec.md), [data-model § 2.5](data-model.md), [contracts/evaluation_report.schema.md](contracts/evaluation_report.schema.md);依赖 T008, T009)
- [ ] T011 [P] [US1] 修复 [tests/fixtures/golden_test_set.json](../../tests/fixtures/golden_test_set.json):
  - 加顶层 `_schema_version: 1` / `language: "mixed"` / `version: "v0.1-smoke"` / `created_at` / `source_corpus_collection: "default"` 字段
  - 替换 4 条 case 的 `expected_chunk_ids` 占位字符串为 vector store 真实 ID(可用 `python -c "..."` 通过 chromadb 客户端 `peek()` 获取)
  - 每条 case 加 `tags` 4 子字段(content_type=text / difficulty=simple / language=zh|en / doc_version=v1)
  (refs [contracts/golden_test_set.schema.md § 6](contracts/golden_test_set.schema.md))
- [ ] T012 [US1] 改造 [scripts/evaluate.py](../../scripts/evaluate.py):
  - 新增 `--lang <zh|en>` 参数(从 `settings.evaluation.golden_test_sets_by_lang[<lang>]` 取 path,与 `--test-set` 互斥)
  - 新增 `--archive` / `--no-archive` 默认 True,控制 EvalRunner 归档行为
  - 新增 `--exit-on-fail` 启用时 acceptance_status=fail → 退出码 3
  - stdout 输出已扩展的 EvaluationReport JSON;FR-007 失败 → 退出码 1 + stderr 友好错误
  (refs [contracts/cli_contracts.md § 1](contracts/cli_contracts.md);依赖 T010)

### Tests for User Story 1(宪法 § VII NON-NEGOTIABLE)

- [ ] T013 [P] [US1] 测试 [tests/unit/test_ragas_evaluator_factory.py](../../tests/unit/test_ragas_evaluator_factory.py):mock `LLMFactory.create()` 与 `EmbeddingFactory.create()`,验证 `RagasEvaluator.__init__()` 通过 factory 路径取 Judge / embedding(无任何 `from .*_llm import` 或环境变量直读);`get_judge_identifier()` / `get_embedding_identifier()` 返回 `"<provider>:<model>"` 格式正确(refs T008,[spec FR-016](spec.md), [spec FR-017](spec.md))
- [ ] T014 [P] [US1] 测试 [tests/unit/test_threshold_evaluator.py](../../tests/unit/test_threshold_evaluator.py):覆盖 — 8 项全过 → PASS;任一不过 → FAIL;阈值边界(等于 0.70 与略低于 0.70);缺指标 key 抛错;`get_failed_metrics()` 返回正确 list(refs T009,[spec FR-013](spec.md))
- [ ] T015 [P] [US1] 测试 [tests/unit/test_eval_runner_validation.py](../../tests/unit/test_eval_runner_validation.py):mock vector store 客户端 — 全部 chunk_id 存在 → 通过;任一缺失 → 抛 `ValueError` 含 case index + 缺失 ID;`chunk_id_validation=False` 时跳过校验(refs T010,[spec FR-007](spec.md))
- [ ] T016 [P] [US1] 测试 [tests/unit/test_eval_runner_by_tag.py](../../tests/unit/test_eval_runner_by_tag.py):覆盖 `_aggregate_by_tag` — 命名规则 `aggregate_metrics_by_<dim>.<value>.<metric>` 正确;< 5 样本切片返 `null` 且 entry 含 `_skipped_reason: "n_samples=<n><5"`;不参与 `acceptance_status` 计算(spec Clarifications Q2)(refs T010,[spec FR-015](spec.md))
- [ ] T017 [P] [US1] 测试 [tests/unit/test_eval_runner_extended_fields.py](../../tests/unit/test_eval_runner_extended_fields.py):覆盖 EvalReport 新字段 — `run_id` 是 UUID4 格式;`acceptance_thresholds_snapshot` 与 settings 一致;`judge_llm_identifier` / `embedding_identifier` 来自 evaluator;NaN metric → `degraded_case_count++` + 不污染均值;`_archive_report()` 写 `<run_id>.json` + 追加 `index.jsonl`(refs T010,[spec FR-001](spec.md), [data-model § 2.5](data-model.md))

### US1 验收

- [ ] T018 [US1] 跑 [quickstart.md Path A](quickstart.md) 10 步端到端验证:确认 stdout JSON 含 8 个 aggregate_metrics 键 + `acceptance_status` + 4 个 identifier/snapshot/case 相关字段;`logs/evaluation_reports/<run_id>.json` 与 `index.jsonl` 落盘正确(refs [spec SC-001](spec.md))

**Checkpoint**:US1 完整可用,可独立交付 MVP 增量。

---

## Phase 4: User Story 2 - 合成并精修真实 MT5 测试集(Priority: P2)

**Goal**:从已摄入 MT5 语料合成 ≥ 100 条候选,人工精修到 80-100 条,产出中英各 ≥ 40 条带 tags 的金标集合 + 真实 expected_chunk_ids。

**Independent Test**:`tests/fixtures/golden_test_set_zh.json` 与 `_en.json` 各存在且 ≥ 40 条;每条含完整 tags 4 子字段;随机抽 10% 人工 review 通过率 ≥ 90%(spec SC-002)。

### Implementation for User Story 2

- [ ] T019 [US2] 新增 [src/observability/evaluation/testset_synthesizer.py](../../src/observability/evaluation/testset_synthesizer.py):`TestsetSynthesizer` 类包装 RAGAS `TestsetGenerator`,接收 `collection: str` / `lang: Literal["zh","en"]` / `target_count: int` / `distribution: dict[str, float]`,返回含 `_synthesis_metadata` 与 candidate cases 的 dict;Judge / embedding 复用 T006 的包装层(refs [spec FR-004](spec.md), [contracts/golden_test_set.schema.md § 4](contracts/golden_test_set.schema.md);依赖 T006)
- [ ] T020 [US2] 新增 [scripts/synthesize_testset.py](../../scripts/synthesize_testset.py):CLI 入口,argparse 解析 `--collection` / `--lang` / `--target-count` / `--output` / `--distribution`,调用 `TestsetSynthesizer`,JSON 落盘到 `tests/fixtures/candidates/<lang>.json`;退出码符合 [contracts/cli_contracts.md § 2](contracts/cli_contracts.md)(refs [contracts/cli_contracts.md § 2](contracts/cli_contracts.md);依赖 T019)
- [ ] T021 [P] [US2] 新增 [scripts/refine_testset.py](../../scripts/refine_testset.py):CLI 实现 interactive 模式 — 逐条 case prompt(y/e/d/s/q),`e` 启动 `$EDITOR` 编辑当前 JSON,`q` 保存进度并退出;退出码符合 [contracts/cli_contracts.md § 3](contracts/cli_contracts.md);使用 `get_logger()` 输出 stderr 进度(refs [spec FR-005](spec.md), [contracts/cli_contracts.md § 3](contracts/cli_contracts.md))
- [ ] T022 [P] [US2] 新增 [scripts/backfill_chunk_ids.py](../../scripts/backfill_chunk_ids.py):CLI 实现 — 用 `EmbeddingFactory.create(settings)` 把每条 case 的 `ground_truth` 编码为向量,在指定 collection 中查 top-K 最相似 chunk,过 `--threshold` 后回填 `expected_chunk_ids`;`--dry-run` 不写文件;匹配率 < 90% 时退出码 2 + 警告 stderr(refs [spec FR-007](spec.md), [contracts/cli_contracts.md § 4](contracts/cli_contracts.md))

### Tests for User Story 2(宪法 § VII NON-NEGOTIABLE)

- [ ] T023 [P] [US2] 测试 [tests/unit/test_testset_synthesizer.py](../../tests/unit/test_testset_synthesizer.py):mock RAGAS `TestsetGenerator.generate()` 返回固定 candidates;验证 `_synthesis_metadata` 字段填写完整(generator 名 / ragas_version / judge_llm_identifier / embedding_identifier / distribution / synthesized_at);distribution 总和 ≠ 1.0 时抛错(refs T019)
- [ ] T024 [P] [US2] 测试 [tests/unit/test_refine_testset.py](../../tests/unit/test_refine_testset.py):mock stdin 输入序列;覆盖 keep / drop / skip 决策正确性,output JSON 结构合规;Ctrl-C 后保存进度(refs T021)
- [ ] T025 [P] [US2] 测试 [tests/unit/test_backfill_chunk_ids.py](../../tests/unit/test_backfill_chunk_ids.py):mock EmbeddingFactory + ChromaDB 查询;覆盖 — 阈值过滤生效;`--dry-run` 不修改输入文件;匹配率 < 90% 触发警告退出码(refs T022)

### US2 实操(产出测试集)

- [ ] T026 [US2] 用 T020 合成 100 条中文候选,落到 [tests/fixtures/candidates/zh.json](../../tests/fixtures/candidates/zh.json)
- [ ] T027 [US2] 用 T021 精修中文候选 → [tests/fixtures/golden_test_set_zh.json](../../tests/fixtures/golden_test_set_zh.json)(≥ 40 条)
- [ ] T028 [US2] 用 T022 回填 [tests/fixtures/golden_test_set_zh.json](../../tests/fixtures/golden_test_set_zh.json) 的 expected_chunk_ids;dry-run 抽 5 条人工 review 后正式写入
- [ ] T029 [US2] 重复 T026-T028 流程产出 [tests/fixtures/golden_test_set_en.json](../../tests/fixtures/golden_test_set_en.json)(≥ 40 条)
- [ ] T030 [US2] 跑 [quickstart.md Path B](quickstart.md) 全流程 + 抽样 10% 人工 review,验证 [spec SC-002](spec.md)(结构合规率 ≥ 90%)、[spec SC-003](spec.md)(单语种 ≤ 30 分钟)

**Checkpoint**:US2 完整可用,中英金标到位,可独立交付增量。

---

## Phase 5: User Story 3 - 标记基线并支持回归对比(Priority: P3)

**Goal**:支持把任意一次评估标为"当前基线"、自动计算 delta、Streamlit 面板呈现 pass/fail 视觉区分 + 趋势折线 + delta 视图。

**Independent Test**:跑 [quickstart.md Path C](quickstart.md):标记 zh/en 各一份基线 → 改 `retrieval.top_k_final` 重跑 → 面板显示 delta 表 + 8 项指标趋势折线;基线列表区分 pass/fail 视觉。

### Implementation for User Story 3

- [ ] T031 [US3] 新增 [src/observability/evaluation/baseline_manager.py](../../src/observability/evaluation/baseline_manager.py):`BaselineManager` 类
  - `mark_as_baseline(report_id, collection)`:把当前 baseline 移到 history,新 baseline 写入 current(原子写:写临时文件 + os.replace 重命名)
  - `get_current_baseline(collection)` → `Optional[Baseline]`
  - `get_history(collection)` → `list[Baseline]`
  - `compute_delta(current_report: EvaluationReport, baseline_report: EvaluationReport)` → `DeltaReport`(简单相减)
  - `_load_report(report_id)` 从 `report_archive_dir` 读完整报告 JSON
  - 文件:`settings.evaluation.baseline_store_path`(默认 `logs/baselines.json`),schema 见 [data-model § 2.7](data-model.md)
  (refs [spec FR-008](spec.md), [spec FR-009](spec.md), [research § Decision 3](research.md), [data-model § 2.6](data-model.md), [data-model § 2.7](data-model.md))
- [ ] T032 [US3] 在 [src/observability/evaluation/eval_runner.py](../../src/observability/evaluation/eval_runner.py) 的 `run()` 尾部接入 `BaselineManager`:若 `get_current_baseline(collection)` 非空,则 `compute_delta(current, baseline_report)` 并把结果嵌入 EvalReport 的 `baseline_id` / `delta_aggregate_metrics` / `per_tag_delta` / `delta_hit_rate` / `delta_mrr` 字段(refs [spec FR-009](spec.md);依赖 T031,改 T010 已扩展的 EvalRunner)
- [ ] T033 [US3] 改造 Streamlit 评估面板(具体路径以现有 dashboard 代码为准,典型位置 `src/observability/dashboard/pages/evaluation_panel.py` 或类似):
  - 列出 `index.jsonl` 中每次评估,绿色徽标 = pass、红色徽标 = fail
  - 评估详情视图加"标记为基线"按钮 → 调用 `BaselineManager.mark_as_baseline()`
  - 当前 vs 基线 delta 表格(8 项主聚合指标 + 顶层 hit_rate / mrr 的 delta 含正负方向)
  - 历史趋势:每个 collection × 每个 metric 的时序折线(扫 `index.jsonl` 中 `created_at` + 单文件读 `aggregate_metrics`,N ≤ 几十次)
  - fail 基线列表项加灰色背景(spec § Clarifications Q3)
  (refs [spec FR-008](spec.md), [spec FR-009](spec.md), [spec FR-010](spec.md), [spec US3 AS1-AS4](spec.md), [contracts/evaluation_report.schema.md § 5](contracts/evaluation_report.schema.md))

### Tests for User Story 3(宪法 § VII NON-NEGOTIABLE)

- [ ] T034 [P] [US3] 测试 [tests/unit/test_baseline_manager.py](../../tests/unit/test_baseline_manager.py):用 tmp_path fixture 构造临时 baselines.json
  - 标记新基线后旧基线移到 history,current 仅 1 个 / collection
  - `compute_delta()` 简单相减正确(`current - baseline`,含正负)
  - 原子写:模拟写中断(临时文件留存),不破坏原 baselines.json
  - schema_version 不匹配时拒绝读取
  (refs T031,[spec FR-008](spec.md), [spec FR-009](spec.md))
- [ ] T035 [P] [US3] 测试 [tests/unit/test_eval_runner_baseline_integration.py](../../tests/unit/test_eval_runner_baseline_integration.py):mock BaselineManager — 有当前基线时 EvalReport 含 delta 字段;无当前基线时 delta 字段为 None;baseline_report 缺失某指标时该 delta 项为 None(refs T032)

### US3 验收

- [ ] T036 [US3] 跑 [quickstart.md Path C](quickstart.md):中文标基线 → 改 `retrieval.top_k_final` → 重跑 → stdout JSON 含 baseline_id + delta_aggregate_metrics;面板显示 delta 视图 + 趋势折线;视觉区分 pass/fail;验证 [spec SC-004](spec.md)(delta ≤ 1 分钟)+ [spec SC-005](spec.md)(已识别一次真实 delta)

**Checkpoint**:US3 完整可用,基线回归机制就绪,所有 user stories 独立交付完成。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**:文档同步 + 全套验收 + 跨 story 整合验证。

- [ ] T037 [P] 跑 [quickstart.md](quickstart.md) 全流程(Path A → B → C)端到端,逐条 verify [spec SC-001](spec.md) ~ [spec SC-008](spec.md):SC-001/003/004/005/006 自动验证、SC-002 抽样人工 review、SC-007 = acceptance_status 字段产出、SC-008 = `tags.doc_version` 字段就位(refs [spec § Success Criteria](spec.md))
- [ ] T038 [P] 更新 [docs/rag-acceptance-plan.md](../../docs/rag-acceptance-plan.md) 的"执行进度追踪"章节,标记 Step 0 ~ Step 5 完成状态(refs spec § Assumptions)
- [ ] T039 [P] 微调 [CLAUDE.md](../../CLAUDE.md) "Evaluation System" 章节:加"Judge LLM / embedding 切换时阈值需重新校准"提示(链接到 [spec § Assumptions § Judge 切换与阈值校准](spec.md))(refs [spec § Assumptions](spec.md))
- [ ] T040 跑 `pytest tests/unit -v` 全部绿(宪法 § VII NON-NEGOTIABLE 验收门槛);若任一失败禁止 commit
- [ ] T041 [P] (可选,SC-003 性能验证)写一个 `scripts/dev/benchmark_evaluation.py` 跑 80 用例 @ GLM-4 默认 Judge 测时长;若 > 30 分钟需在 plan.md 记录 Complexity Tracking 条目说明(refs [spec SC-003](spec.md))

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**:无依赖,立即开始
- **Phase 2 (Foundational)**:依赖 Phase 1 完成 — **BLOCKS US1/US2/US3**
- **Phase 3 (US1)**:依赖 Phase 2;实施完成后即可独立交付 MVP
- **Phase 4 (US2)**:依赖 Phase 2;**不依赖 US1 的修复 fixture(T011)**,可与 US1 并行(若多人协作)
- **Phase 5 (US3)**:依赖 Phase 2 + US2 产出的金标(否则基线无统计意义,spec § US3 Why)
- **Phase 6 (Polish)**:依赖所有 US 完成

### User Story Dependencies

- **US1 (P1)**:Phase 2 完成后即可启动 — 不依赖 US2/US3
- **US2 (P2)**:Phase 2 完成后即可启动 — 不依赖 US1(US2 不修改 EvalRunner,与 US1 改动文件不冲突;US2 跑评估时使用 US1 改造后的 EvalRunner,因此 **US2 实操 task T026-T030 依赖 US1 完成**)
- **US3 (P3)**:依赖 US2 产出的金标(spec § US3 Why);代码 task(T031-T035)可在 US2 实操 task 之前完成,**实操 task T036 依赖 US2 实操 T030**

### Within Each User Story

- 测试任务可在实施任务之前/之后/之间编写(本项目宪法不强制 TDD,但宪法 § VII 要求 commit 前 unit test 全绿)
- Models / 类型 → services / 编排 → endpoints / CLI
- 同一 story 内不同文件的实施任务标 [P] 可并行

### Parallel Opportunities Map

| Phase | 可并行任务组 |
|---|---|
| Phase 1 (Setup) | T001 单 task,无并行 |
| Phase 2 (Foundational) | T002 / T003 / T005 / T006 / T007 全部 [P] 可并行(改不同文件);**T004 串行**(同 settings.py,依赖 T003) |
| Phase 3 (US1) 实施 | T008 + T009 + T011 + T012 中 [P] 标的可并行;T010 串行(汇总核心改动,依赖 T008 + T009) |
| Phase 3 (US1) 测试 | T013-T017 全部 [P] 可并行(各自独立测试文件) |
| Phase 4 (US2) 实施 | T019(必先) → T020 / T021 / T022 [P] 可并行 |
| Phase 4 (US2) 测试 | T023 / T024 / T025 全部 [P] 可并行 |
| Phase 4 (US2) 实操 | T026 → T027 → T028 串行(中文流水);T029 中文完成后再做(也可与英文流水并行) |
| Phase 5 (US3) 实施 | T031(必先) → T032 / T033 [P] 可并行(改不同文件) |
| Phase 5 (US3) 测试 | T034 / T035 [P] 可并行 |
| Phase 6 (Polish) | T037 / T038 / T039 / T041 [P] 可并行;T040 最后跑 |

---

## Parallel Example: User Story 1 测试任务组

```bash
# Phase 3 测试任务可同时启动(都改不同的 tests/unit/test_*.py 文件):
Task T013: tests/unit/test_ragas_evaluator_factory.py     # FR-016 / FR-017
Task T014: tests/unit/test_threshold_evaluator.py         # FR-013
Task T015: tests/unit/test_eval_runner_validation.py      # FR-007
Task T016: tests/unit/test_eval_runner_by_tag.py          # FR-015
Task T017: tests/unit/test_eval_runner_extended_fields.py # 新字段 + NaN
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1 → **STOP & VALIDATE T018**
2. 已可验收 [spec SC-001](spec.md);可作为独立交付增量 commit + push

### Incremental Delivery

1. Setup + Foundational(`d0420f1` 后第一个 commit;预计 T001-T007)
2. + US1 → 验收 SC-001 → 增量 commit
3. + US2 → 验收 SC-002 / SC-003 → 增量 commit
4. + US3 → 验收 SC-004 / SC-005 → 增量 commit
5. + Polish → 验收 SC-006 / SC-007 / SC-008(skeleton) + pytest 全绿 → 增量 commit
6. Feature-001 收尾 commit,可关闭分支

### Per-Task Commit 风格(宪法 § X NON-NEGOTIABLE)

每个 src/ 改动 commit 必须引用 task ID。建议风格:

```
feat(spec-001): <scope> <imperative summary> (refs T-XXX)

<optional body>
```

或合理分组(同类的 [P] 测试任务可一起 commit):

```
test(spec-001): add unit tests for US1 RAGAS factory & threshold (refs T-013, T-014)
```

---

## Notes

- [P] 任务 = 不同文件 + 无对未完成任务的依赖
- [Story] 标签 = 用户故事追溯锚点(US1/US2/US3)
- 每个 user story 必须可独立完成、独立测试、独立交付
- 实施期 commit 必须引用 task ID(宪法 § X)
- US1 完成即可作为 MVP 增量交付,不必等 US2/US3
- 同一文件的多个任务避免标 [P](会相互冲突);同 story 内若两 task 都改 `eval_runner.py`,必须串行
- 任一 unit test 失败禁止 commit(宪法 § VII)
