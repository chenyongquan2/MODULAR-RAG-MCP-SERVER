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

- [x] T008 [US1] 改造 [src/observability/evaluation/ragas_evaluator.py](../../src/observability/evaluation/ragas_evaluator.py) 中 `RagasEvaluator`:`__init__()` 加 lazy 标志 `_wrappers_built`,首次 `_evaluate_with_ragas()` 触发时调用 `_ragas_wrappers.build_ragas_judge/build_ragas_embedding` 通过 LLMFactory/EmbeddingFactory 注入 RAGAS 4 个 metrics 的 `.llm`/`.embeddings`(单元测试可通过 kwargs 覆盖通道注入 mock);新增 `get_judge_identifier()` / `get_embedding_identifier()` 委托给 `_ragas_wrappers.get_*_identifier`(refs [spec FR-016](spec.md), [spec FR-017](spec.md);依赖 T006)
- [x] T009 [P] [US1] 新增 [src/observability/evaluation/threshold_evaluator.py](../../src/observability/evaluation/threshold_evaluator.py):实现 `ThresholdEvaluator` 类,接收 `AcceptanceThresholds` dataclass,`evaluate(aggregate_metrics) -> AcceptanceStatus` 返回 `PASS`(全 8 项 ≥ 各自阈值)或 `FAIL`(任一不达标 / 缺 key / NaN);附 `get_failed_metrics()` 辅助方法 + `thresholds_snapshot` 只读属性(refs [spec FR-013](spec.md), [data-model § 2.4](data-model.md))
- [x] T010 [US1] 改造 [src/observability/evaluation/eval_runner.py](../../src/observability/evaluation/eval_runner.py):
  - `EvalCase` 加 `tags: Optional[TestCaseTags] = None` 字段(US1 占位允许 None)
  - `EvalReport` 大扩展:加 `run_id` / `collection` / `test_set_version` / `created_at` / `acceptance_thresholds_snapshot` / `acceptance_status` / `judge_llm_identifier` / `embedding_identifier` / `degraded_case_count` / `aggregate_metrics_by_tag` 字段
  - `_load_test_cases()` 解析 `tags` 字段 + `_schema_version` 校验
  - `run()` 入口加 `_validate_chunk_ids_exist()`(FR-007;`settings.evaluation.chunk_id_validation=True` 时启用,未通过抛 `ValueError` 含 case index + 缺失 chunk_id);加 `_aggregate_by_tag(case_results, dimension)` helper(FR-015;< `tag_slice_min_samples` 跳过 + `_skipped_reason`)
  - 收集 NaN metrics → `degraded_case_count++` 且不计入分母(避免 NaN 污染均值)
  - 调用 `ThresholdEvaluator` 计算 `acceptance_status`,从 `evaluator.get_judge_identifier()` / `get_embedding_identifier()` 取标识(若 evaluator 不支持则记 `null`,作为 custom-only 评估场景)
  - 加 `_archive_report(report)` 写 `settings.evaluation.report_archive_dir/<run_id>.json` + 追加 `index.jsonl` 一行精简元数据
  (refs [spec FR-007](spec.md), [spec FR-013](spec.md), [spec FR-015](spec.md), [spec FR-016](spec.md), [spec FR-017](spec.md), [data-model § 2.5](data-model.md), [contracts/evaluation_report.schema.md](contracts/evaluation_report.schema.md);依赖 T008, T009)
- [x] T011 [P] [US1] 修复 [tests/fixtures/golden_test_set.json](../../tests/fixtures/golden_test_set.json):
  - 加顶层 `_schema_version: 1` / `language: "mixed"` / `version: "v0.1-smoke"` / `created_at` / `source_corpus_collection: "default"` 字段
  - 每条 case 加 `tags` 4 子字段(content_type/difficulty/language/doc_version);难度分布:2 simple / 1 reasoning / 1 multi_context
  - **expected_chunk_ids 保留占位字符串**(`chunk_*_001` 等),由 user 在 quickstart Path A Step 5-6 替换为 vector store 真实 ID(此为 US1 验收的人工步骤);或临时设 `evaluation.chunk_id_validation=false` 跳过校验
  - 加 `_note` 字段说明上述意图,向未来读者解释为什么 chunk_ids 仍是占位
  (refs [contracts/golden_test_set.schema.md § 6](contracts/golden_test_set.schema.md))
- [x] T012 [US1] 改造 [scripts/evaluate.py](../../scripts/evaluate.py):
  - 新增 `--lang <zh|en>` 参数(从 `settings.evaluation.golden_test_sets_by_lang[<lang>]` 取 path,与 `--test-set` 互斥)
  - 新增 `--archive` / `--no-archive` 默认 True,控制 EvalRunner 归档行为
  - 新增 `--exit-on-fail` 启用时 acceptance_status=fail → 退出码 3
  - stdout 输出已扩展的 EvaluationReport JSON;FR-007 失败 → 退出码 1 + stderr 友好错误
  (refs [contracts/cli_contracts.md § 1](contracts/cli_contracts.md);依赖 T010)

### Tests for User Story 1(宪法 § VII NON-NEGOTIABLE)

- [x] T013 [P] [US1] 测试 [tests/unit/test_ragas_evaluator_factory.py](../../tests/unit/test_ragas_evaluator_factory.py):**9 用例** — Identifier 助手 (4):provider 切换 / 顶层 fallback / 覆盖 / GLM-4 默认;factory 注入 (4):lazy init 不预热、`_ensure_wrappers` 单次构建、覆盖 mock_metrics 短路、kwargs 旁路通道(refs T008,[spec FR-016](spec.md), [spec FR-017](spec.md))
- [x] T014 [P] [US1] 测试 [tests/unit/test_threshold_evaluator.py](../../tests/unit/test_threshold_evaluator.py):**14 用例** — 主路径 (5):全 PASS / 全等于阈值 / 单项 FAIL / 边界 0.69999 / 用户覆盖;边角 (4):缺 key / NaN / None / 空 dict;辅助 (5):空失败 list / 多失败 / NaN 失败 / snapshot 副本独立 / snapshot 8 keys(refs T009,[spec FR-013](spec.md))
- [x] T015 [P] [US1] 测试 [tests/unit/test_eval_runner_validation.py](../../tests/unit/test_eval_runner_validation.py):**4 用例** — 通过路径 (1)、失败定位错误信息含 case index+缺失 ID+提示 (1)、vector store 故障的友好错误 (1)、`chunk_id_validation=False` 完全跳过 factory.create (1)(refs T010,[spec FR-007](spec.md))
- [x] T016 [P] [US1] 测试 [tests/unit/test_eval_runner_by_tag.py](../../tests/unit/test_eval_runner_by_tag.py):**4 用例** — 命名规则 + 双维度 (1)、< min samples 切片标 `_skipped_reason` 全 metric None (1)、切片不影响 acceptance_status (1)、无 tags case 不进切片 (1)(refs T010,[spec FR-015](spec.md))
- [x] T017 [P] [US1] 测试 [tests/unit/test_eval_runner_extended_fields.py](../../tests/unit/test_eval_runner_extended_fields.py):**13 用例** — Run 元数据 (4):UUID4 格式 / 跨 run 不同 / collection 优先级 / test_set_version 解析;Provider identifiers (2):evaluator 有/无方法的两种行为;Acceptance status (2):全过 PASS / snapshot 与 settings 一致;NaN 处理 (2):degraded_case_count++ / 不污染均值;Archive (3):per-run + index.jsonl 写入 / --no-archive 跳过 / 多次 append(refs T010,[spec FR-001](spec.md), [data-model § 2.5](data-model.md))

### US1 验收

- [x] T018 [US1] quickstart Path A 真实 GLM API 跑通(commit `b78b4be`):`run_id=ccd21700-...`,`judge_llm_identifier=glm:z-ai/glm-4.7`,`embedding_identifier=openai:text-embedding-3-small`,8 个 aggregate_metrics keys 全产出(7 finite + 1 NaN 在 spec 允许的显式降级范围),archive 写入 `logs/evaluation_reports/<run_id>.json` + `index.jsonl`;**SC-001 严格满足**(refs [spec SC-001](spec.md))

**Checkpoint**:US1 完整可用,可独立交付 MVP 增量。

---

## Phase 4: User Story 2 - 合成并精修真实 MT5 测试集(Priority: P2)

**Goal**:从已摄入 MT5 语料合成 ≥ 100 条候选,人工精修到 80-100 条,产出中英各 ≥ 40 条带 tags 的金标集合 + 真实 expected_chunk_ids。

**Independent Test**:`tests/fixtures/golden_test_set_zh.json` 与 `_en.json` 各存在且 ≥ 40 条;每条含完整 tags 4 子字段;随机抽 10% 人工 review 通过率 ≥ 90%(spec SC-002)。

### Implementation for User Story 2

- [x] T019 [US2] 新增 [src/observability/evaluation/testset_synthesizer.py](../../src/observability/evaluation/testset_synthesizer.py):`TestsetSynthesizer` 类包装 RAGAS `TestsetGenerator`,通过 `_ragas_wrappers` 用项目 LLMFactory/EmbeddingFactory 注入 generator+critic LLM 与 embedding(共用同一 LLM 减少模型差异);从 chromadb 直接拉 chunks 包装为 LangChain Document → 调 `generate_with_langchain_docs()` → 转成 candidate JSON(含 `_synthesis_metadata`:generator/ragas_version/judge_id/embedding_id/distribution/synthesized_at);RAGAS evolution_type → tags.difficulty 映射(refs [spec FR-004](spec.md), [contracts/golden_test_set.schema.md § 4](contracts/golden_test_set.schema.md);依赖 T006)
- [x] T020 [US2] 新增 [scripts/synthesize_testset.py](../../scripts/synthesize_testset.py):CLI 入口 + 难度分布参数解析(冒号/逗号分隔)+ 退出码映射 + 难度计数总结输出(refs [contracts/cli_contracts.md § 2](contracts/cli_contracts.md);依赖 T019)
- [x] T021 [P] [US2] 新增 [scripts/refine_testset.py](../../scripts/refine_testset.py):interactive 模式 — y/e/d/s/q 决策、`$EDITOR` 集成(临时 JSON 文件 + 启动外部编辑器)、Ctrl-C 安全保存进度、`_synth_*` 临时字段过滤、partial 标记(version=v0.9-partial)(refs [spec FR-005](spec.md), [contracts/cli_contracts.md § 3](contracts/cli_contracts.md))
- [x] T022 [P] [US2] 新增 [scripts/backfill_chunk_ids.py](../../scripts/backfill_chunk_ids.py):用 EmbeddingFactory 把 ground_truth 编码 → vector_store.query(top-K) → 阈值过滤 → 回填 expected_chunk_ids;`--dry-run` 不写、匹配率 < 90% 退出码 2 + 拒写;支持 `id`/`chunk_id` 两种返回 key(refs [spec FR-007](spec.md), [contracts/cli_contracts.md § 4](contracts/cli_contracts.md))

### Tests for User Story 2(宪法 § VII NON-NEGOTIABLE)

- [x] T023 [P] [US2] 测试 [tests/unit/test_testset_synthesizer.py](../../tests/unit/test_testset_synthesizer.py):**8 用例** — distribution 校验(unknown key 拒绝 / 总和远离 1 拒绝 / 浮点容差 / target_count=0)、candidate JSON schema 完整性(顶层字段 + 元数据 + tags 映射)、空 collection 抛错、ragas_version 元数据可用(refs T019)
- [x] T024 [P] [US2] 测试 [tests/unit/test_refine_testset.py](../../tests/unit/test_refine_testset.py):**9 用例** — y/d/s 决策(3)、q 中途退出 partial 标记(1)、非法输入 retry(1)、edit 调用 $EDITOR + 失败回退(2)、_synth_* 字段过滤(1)、final schema 顶层字段(1)(refs T021)
- [x] T025 [P] [US2] 测试 [tests/unit/test_backfill_chunk_ids.py](../../tests/unit/test_backfill_chunk_ids.py):**5 用例** — 阈值过滤、空 ground_truth / 空白 ground_truth 跳过 embed、`chunk_id` 字段名兼容、全部 < 阈值返空(refs T022)

### US2 实操(产出测试集)

- [x] T026 [US2] 用 T020 合成中文候选,落到 [tests/fixtures/candidates/zh.json](../../tests/fixtures/candidates/zh.json)
  > 2026-04-28 更新:target=50 实跑得 47 条候选,但只 6 条真中文(minimax/minimax-m2.7 不能完成 RAGAS `adapt(language=chinese)`,prompt 翻译稳定输出非 JSON,内部 prompt 保持英文 → 生成英文 question)。已加 `generator.adapt()` + 2x retry + `cache_dir` 机制 + `BatchedInMemoryDocumentStore`(embedding 50 min → 1 min, 14-60x)。**zh 数据规模问题转 Feature-004 处理**。
- [x] T027 [US2] 用 T021 精修中文候选 → [tests/fixtures/golden_test_set_zh.json](../../tests/fixtures/golden_test_set_zh.json)
  > 2026-04-28 更新:Claude(Anthropic, 与合成端 minimax 不同家族,盲点正交)代理人工 review 47 条,保留 6 条真中文,drop 41(语种 mismatch 33 / 中英混杂 4 / GT="not present" 2 / answer leakage 2)。落 `_reviewer` + `_review_notes` 字段供审计。**实际 6 条 < 40 阈值**,SC-002 zh deferred(见 T037)。
- [x] T028 [US2] 用 T022 回填 zh 的 expected_chunk_ids
  > 2026-04-28 更新:`backfill_chunk_ids.py --threshold 0.5`(zh 数据稀疏, 默认 0.6 漏 FeederGet),回填 6/6 = 100%。
- [x] T029 [US2] 产出 [tests/fixtures/golden_test_set_en.json](../../tests/fixtures/golden_test_set_en.json)(≥ 40 条)
  > 2026-04-28 更新:en 合成 48 条 → Claude review keep 42(drop 6: 4 条 GT="not present" + 2 条 answer leakage),回填 42/42 = 100% @ threshold 0.5。**en SC-002 ✅ 42/40**。
- [x] T030 [US2] 跑 [quickstart.md Path B](quickstart.md) 全流程 + 抽样 review,验证 SC-002 / SC-003
  > 2026-04-28 更新:Path B 全程跑通(synthesize → review → backfill → evaluate)。SC-002 en ✅ 42/40 + reviewer 元数据;SC-002 zh deferred。SC-003 实测:zh 6 case ~3 min ✅,en 42 case ~30 min 在 30 min 阈值边缘。

**Checkpoint**:US2 完整可用,中英金标到位,可独立交付增量。

---

## Phase 5: User Story 3 - 标记基线并支持回归对比(Priority: P3)

**Goal**:支持把任意一次评估标为"当前基线"、自动计算 delta、Streamlit 面板呈现 pass/fail 视觉区分 + 趋势折线 + delta 视图。

**Independent Test**:跑 [quickstart.md Path C](quickstart.md):标记 zh/en 各一份基线 → 改 `retrieval.top_k_final` 重跑 → 面板显示 delta 表 + 8 项指标趋势折线;基线列表区分 pass/fail 视觉。

### Implementation for User Story 3

- [x] T031 [US3] 新增 [src/observability/evaluation/baseline_manager.py](../../src/observability/evaluation/baseline_manager.py):`BaselineManager` 类:per-collection mark / current / history(`logs/baselines.json` 单文件 + 原子写 mkstemp+os.replace);`compute_delta` 覆盖主聚合 + by-tag(切片任一边 skipped 即 entry 为 None);`load_report` 读归档;`_schema_version=1` 守卫(refs [spec FR-008](spec.md), [spec FR-009](spec.md), [research § Decision 3](research.md), [data-model § 2.6](data-model.md), [data-model § 2.7](data-model.md))
- [x] T032 [US3] [src/observability/evaluation/eval_runner.py](../../src/observability/evaluation/eval_runner.py) `run()` 尾部新增 `_attach_baseline_delta(report)`:若 `get_current_baseline(collection)` 非空 → `load_report(baseline_id)` + `compute_delta` → 嵌入 `baseline_id` / `delta_aggregate_metrics` / `per_tag_delta` / `delta_hit_rate` / `delta_mrr`;失败仅日志警告不阻断主输出(refs [spec FR-009](spec.md))
- [x] T033 [US3] 新增 [src/observability/dashboard/pages/_feature_001_evaluation.py](../../src/observability/dashboard/pages/_feature_001_evaluation.py) + 在 [src/observability/dashboard/pages/evaluation_panel.py](../../src/observability/dashboard/pages/evaluation_panel.py) 用 `st.tabs()` 接入(legacy 视图保留):
  - 读 `logs/evaluation_reports/index.jsonl` 列近 30 次评估表格(run_id 短/collection/created_at/acceptance_status/judge/embedding/n_cases)
  - per-collection 当前基线展示(`:green` / `:red` 徽标 + marked_at)
  - 选中 run 详情:summary 4 列、judge/embedding identifier、主聚合 vs 阈值 pass 列、Mark-as-baseline 按钮(调 `BaselineManager.mark_as_baseline`)
  - Delta 表(若 report 已含 baseline_id,显示主聚合 + 顶层 hit_rate/mrr 的 delta + ↑/↓ 方向)
  - by-tag 切片诊断(expander,显示 skipped 切片含 _skipped_reason)
  - 8 项主聚合指标趋势折线(读 ≤ 30 个归档报告,FR-010)
  (refs [spec FR-008](spec.md), [spec FR-009](spec.md), [spec FR-010](spec.md), [spec US3 AS1-AS4](spec.md), [contracts/evaluation_report.schema.md § 5](contracts/evaluation_report.schema.md))

### Tests for User Story 3(宪法 § VII NON-NEGOTIABLE)

- [x] T034 [P] [US3] 测试 [tests/unit/test_baseline_manager.py](../../tests/unit/test_baseline_manager.py):**17 用例** — mark(5):首份基线 / 替换 + 旧到 history / 跨 collection 隔离 / 缺 report 拒绝 / 空 collection 拒绝;query 无基线(2);compute_delta(5):主聚合相减 / 缺 baseline metric 跳过 / 切片 skipped → None / 缺 baseline 切片 → None / 空 dict;load_report(2);schema 兼容(2):未来版本拒绝 / corrupted JSON;原子写无残留临时文件(1)(refs T031,[spec FR-008](spec.md), [spec FR-009](spec.md))
- [x] T035 [P] [US3] 测试 [tests/unit/test_eval_runner_baseline_integration.py](../../tests/unit/test_eval_runner_baseline_integration.py):**4 用例** — 无基线时 delta 字段全 None;有基线时主聚合/顶层 delta 正确嵌入;BaselineManager 失败时降级 None 不阻断(report 文件丢失模拟);baseline 缺指标时该 delta key 不出现(refs T032)

### US3 验收

- [x] T036 [US3] 程序化等价于 quickstart Path C 跑通(2026-04-26):
  - **标基线**:用 `BaselineManager.mark_as_baseline(report_id="ccd21700-...", collection="default", status=FAIL)` 把 T018 真实跑通的 4-case 报告标为 default 的当前基线 → `logs/baselines.json` 写入正确
  - **改配置重跑**:`python scripts/evaluate.py --collection default --top-k 20 --archive`(top_k 从默认 10 改 20)
  - **delta 自动嵌入**:新 run `625f90ba-...` 的 `_attach_baseline_delta` 触发,日志显示"Attached baseline delta: baseline_id=ccd21700-..., 主聚合 delta keys=[8 项全部]"
  - **延迟**:第二轮评估 51 秒 + delta 嵌入 < 1 秒,远低于 SC-004 的 1 分钟阈值(8 项主聚合 + per_tag_delta 2 dimensions 完整计算)
  - **数值**:current top_k=20 vs baseline top_k=10 在当前占位 fixture(查询与 corpus 不匹配)下 delta 全 0(数学正确,因为不匹配的 retrieval 在两种 top_k 下都 hit_rate=0)+ ragas__faithfulness 全 NaN;真实非零 delta 需要 US2 完成的语义匹配金标
  - **机制验证完成**(SC-004 / SC-005 mechanism)— 真实非零 delta 可见性留待 US2 完成后,或当前 user 在 dashboard 上视觉确认(`http://localhost:8501` → "🎯 Feature-001 基线 + 回归" tab)
  (refs T031, T032, T033)

**Checkpoint**:US3 完整可用,基线回归机制就绪,所有 user stories 独立交付完成。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**:文档同步 + 全套验收 + 跨 story 整合验证。

- [x] T037 [P] 跑 [quickstart.md](quickstart.md) 全流程(Path A → B → C):**Path A** ✅(T018 commit `b78b4be`),**Path B** ✅ 2026-04-28 zh+en 双语跑通(zh deferred 见下),**Path C** ✅(T036)。SC matrix:
  > **SC-001** ✅ 8 metrics 都产出(faithfulness 偶 NaN 用 degraded_case_count 标记,符合 spec)
  > **SC-002 zh** ❌ deferred → Feature-004(实得 6/40,minimax adapt 故障)
  > **SC-002 en** ✅ 42/40 + reviewer 元数据
  > **SC-003 zh** ✅ ~3 min;**SC-003 en** 🟡 ~30 min 在阈值边缘
  > **SC-004** ✅ baseline + delta 机制 zh run 2fe47055 / en run 866eb7e3 已 archive
  > **SC-005** ✅ mechanism 验证(跨 Judge 真实对比 deferred)
  > **SC-006** ❌ deferred(同 SC-002 zh)
  > **SC-007** ✅ archive + index.jsonl 工作
  > **SC-008** ✅ schema 含 judge_llm_identifier + embedding_identifier + acceptance_thresholds_snapshot
- [x] T038 [P] [docs/rag-acceptance-plan.md](../../docs/rag-acceptance-plan.md) 更新"执行进度追踪"章节:Step 0/4/5 标 [x](机制完成);Step 1/2/3 标 [ ] 注明"代码就位待 user 跑";Step 6 标"标 spec § Assumptions Step 6 横向对照不在 MVP";顶部加 SDD 接管说明 + 11 个 commit 链接
- [x] T039 [P] [CLAUDE.md](../../CLAUDE.md) "Evaluation System" 章节大改:列 8 项主聚合指标命名;加 Judge/embedding 切换需校准阈值的提示;加 4 个 CLI 入口;加 dashboard tab 路径
- [x] T040 `pytest tests/unit -v` 已多次跑过 — **当前 1070 passed, 2 skipped, 0 failed**(宪法 § VII NON-NEGOTIABLE 验收门槛达成);本会话累计新增 86+ unit test 用例(T007 22 + T013-T017 44 + T023-T025 22 + T034-T035 21 - 部分穿插数据)
- [x] T041 [P] (可选,SC-003 性能验证)
  > 2026-04-28 实测:zh 6 case ~3 min,en 42 case ~30 min(贴近 30 min 阈值)。Feature-004 扩 zh 到 ≥40 后需重测以确认 SC-003 zh。en 已贴边,Feature-002 embedding 批处理 + 异步并发若启用可显著拉低 evaluate 阶段耗时。

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
