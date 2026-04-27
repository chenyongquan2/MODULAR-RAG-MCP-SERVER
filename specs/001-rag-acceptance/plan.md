# Implementation Plan: RAG 质量验收(中英双语基线)

**Branch**: `001-rag-acceptance` | **Date**: 2026-04-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-rag-acceptance/spec.md`

## Summary

为 MT5 中英双语 RAG 系统建立**可量化、可回归、provider-agnostic 的质量验收基线**。依托项目既有的 `EvalRunner` / `CompositeEvaluator` / `RagasEvaluator` 框架(详见 [src/observability/evaluation/eval_runner.py](../../src/observability/evaluation/eval_runner.py)),本 feature 做 4 件事:

1. **配置启用 + Judge / Embedding 接入** — 启用 RAGAS backend,Judge 与 embedding 经 `LLMFactory` / `EmbeddingFactory` 注入(默认 GLM-4 + production 同款 embedding,符合 FR-016 / FR-017)。
2. **测试集到位** — US1 修复占位 ID 让管线跑通;US2 用 RAGAS TestsetGenerator 自动合成 + 人工精修,产出中英各 ≥ 40 条金标集合(每条带 `tags` 字段)。
3. **报告字段加固** — `EvalReport` 扩展 `acceptance_thresholds_snapshot` / `judge_llm_identifier` / `embedding_identifier` / `acceptance_status` / `degraded_case_count` / `aggregate_metrics_by_tag`;FR-007 强制 `expected_chunk_ids` 存在性校验。
4. **基线 + 回归** — 新增 `BaselineManager` 支撑标记 / 当前基线 / delta 计算;Streamlit 评估面板加视觉区分 pass/fail 基线 + 趋势折线。

**MVP 不重写既有评估器**,只做"启用 + 接入 + 字段扩展 + 工具补齐"。

## Technical Context

**Language/Version**: Python 3.11+(项目既定)

**Primary Dependencies**:
- `ragas` — 新依赖,需固定单一已验证版本(见 [research.md § Decision 1](research.md))
- `langchain-openai` — 用于把项目 LLMFactory 实例包装成 RAGAS 期待的 LangChain BaseLLM 接口(详见 [research.md § Decision 2](research.md))
- `chromadb` — 已有,作为 MVP vector store 实际后端(spec 层不绑定)
- `Streamlit` — 已有,dashboard

**Storage**:
- 项目 vector store(MVP 实际后端 ChromaDB)— 通过既有 `vector_store.backend` 配置
- 文件系统 — 金标测试集 `tests/fixtures/golden_test_set_<lang>.json`、评估报告归档 `logs/evaluation_reports/<run_id>.json`、基线标记 `logs/baselines.json`(具体方案见 [research.md § Decision 3](research.md))

**Testing**: `pytest`(项目既有);新增单元测试位于 `tests/unit/test_evaluation_*.py`、`tests/unit/test_baseline_*.py`、`tests/unit/test_threshold_*.py`

**Target Platform**: 跨平台(Windows / macOS / Linux);Python CLI(`scripts/evaluate.py` 等)+ Streamlit dashboard(本地浏览器)

**Project Type**: Single project — Python lib + CLI tools + MCP server + Streamlit dashboard 单仓内

**Performance Goals**:
- SC-003 — 单语种完整评估(80-100 case + 答案生成 + 全 8 项指标)≤ 30 分钟,合计中英 ≤ 60 分钟(基于默认 Judge=GLM-4 假设)
- SC-004 — Dashboard 呈现 delta 视图 ≤ 1 分钟

**Constraints**:
- **provider-agnostic**:Judge / embedding 完全经 factory 接入(FR-016 / FR-017);spec 层不引用具体 provider 名
- **配置驱动**:pass/fail 阈值、by-tag 切片维度、报告归档目录全部 settings.yaml 可控
- **embedding 一致性**:评估流程的 RAGAS 内部相似度、ground_truth-chunk 语义匹配等所有 embedding 环节 MUST 用同一配置(FR-017),不允许各组件分别选 embedding
- **报告自携阈值快照**:`acceptance_thresholds_snapshot` 字段固化每次评估生效的阈值,跨评估对比时阈值是否变过可查
- **RAGAS 库版本固定**:本 feature 锁定单一已验证版本,plan 期不允许升级(避免 API 漂移污染基线)

**Scale/Scope**:
- 80-100 测试用例 × 2 collection(中 / 英)
- 单次评估生成 1 份 EvaluationReport(JSON,含 per_case_metrics 数组 + 8 项 aggregate + by-tag 切片);累计 ≥ 3 次评估即触发趋势折线
- 1 份当前基线 / collection;历史基线无上限(MVP 不做归档清理,避免引入额外存储设计)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

逐条标记 **PASS / VIOLATION / N/A** 并附一行说明。**NON-NEGOTIABLE** 条款不允许通过 Complexity Tracking 豁免。

### 架构原则

- [x] **一、Provider 无关性** — **PASS**:FR-016 / FR-017 强制 Judge / Embedding 经 `LLMFactory` / `EmbeddingFactory` 接入;新代码 `from .*_llm import` / `from .*_embedding import` 应仅出现在 factory 内部
- [x] **二、配置驱动** — **PASS**:Judge、embedding、阈值、by-tag 切片维度全部由 `settings.yaml evaluation.*` 控制,`EvaluationSettings` dataclass 大幅扩展(见 [data-model.md § EvaluationSettings](data-model.md))
- [x] **三、快速失败校验** — **PASS**:`expected_chunk_ids` 存在性校验(FR-007)在 `EvalRunner.run()` 入口完成、Judge / embedding 配置错误最早阶段抛 `ValueError`(US1 AS2)、阈值清单非法(取值不在 [0, 1])在 `load_settings()` 拒绝
- [x] **四、追踪显式化** — **PASS**(不冲突):评估流程**不写入** `traces.jsonl`(那是 production query 用),所以 `EvalRunner` 不构造 `TraceContext`;评估期间调用 `retriever.search()` / `response_builder.build()` 时显式传 `trace=None`(符合"显式参数"原则,而非依赖 thread-local)
- [x] **五、结构化日志(NON-NEGOTIABLE)** — **PASS**:新代码用 `from observability.logger import get_logger; logger = get_logger(__name__)`;`src/` 下零 `print()`(`scripts/` 例外,允许 stdout 输出 JSON 报告)
- [x] **六、类型安全** — **PASS**:新增 `EvaluationSettings` 子 dataclass 全部 `@dataclass` + 完整类型注解;TestCase / GoldenTestSet / EvaluationReport / Baseline / DeltaReport 集中定义在 `src/core/types.py`(实体见 [data-model.md](data-model.md))
- [x] **七、测试支撑变更(NON-NEGOTIABLE)** — **PASS**:Phase 2(speckit-tasks)生成的 tasks.md 中,每个 src/ 实施任务必须对应一个 `tests/unit/` 任务;提交前 `pytest tests/unit -v` 通过

### SDD 纪律

- [x] **八、Spec 先行(NON-NEGOTIABLE)** — **PASS**:[spec.md](spec.md) 已 ratify(specify + 7-clarify 完成,0 个 `NEEDS CLARIFICATION` marker,commit `3a076d7`)
- [x] **九、Plan 先于 Tasks(NON-NEGOTIABLE)** — **PASS**:本文件即 Plan;`tasks.md` 将由 `speckit-tasks` 由本 plan 推导,不脱钩生成
- [x] **十、可追溯性(NON-NEGOTIABLE)** — **PASS**:实施期 commit message 必须引用 task ID(`refs T-XXX`),由 `tasks.md` 中分配的 ID 锚定

**Constitution Check 总结**:全部 PASS,无 violation,无需 Complexity Tracking 区段登记理由。

> 完整原则定义见 [.specify/memory/constitution.md](../../.specify/memory/constitution.md)。

## Project Structure

### Documentation (this feature)

```text
specs/001-rag-acceptance/
├── plan.md                 # 本文件
├── research.md             # Phase 0:技术调研与决策记录(7 个核心决策)
├── data-model.md           # Phase 1:实体定义、字段约束、状态转换
├── quickstart.md           # Phase 1:开发者从零跑通本 feature 的指南
├── contracts/
│   ├── settings.evaluation.schema.md   # settings.yaml evaluation 段最终 schema
│   ├── evaluation_report.schema.md     # EvaluationReport JSON 输出结构
│   ├── golden_test_set.schema.md       # 金标测试集 JSON 结构(含 tags)
│   └── cli_contracts.md                # 4 个 scripts/ 入口的 CLI 契约
├── checklists/requirements.md          # 已存在(specify 阶段产出)
├── spec.md                 # 已存在
└── tasks.md                # 由 speckit-tasks 后续生成
```

### Source Code (repository root)

```text
src/
├── core/
│   ├── settings.py                     # EXTEND: EvaluationSettings 大幅扩展(见 data-model.md)
│   └── types.py                        # EXTEND: 新增 TestCase / GoldenTestSet / EvaluationReport / Baseline / DeltaReport / AcceptanceStatus 类型
├── libs/evaluator/                     # KEEP(全部 5 个文件不动:base/custom/ragas-shim/factory/__init__)
└── observability/evaluation/
    ├── eval_runner.py                  # MODIFY: expected_chunk_ids 存在性校验 + acceptance_thresholds 快照 + by-tag 聚合 + judge/embedding identifier 记录 + acceptance_status 计算 + degraded_case_count 统计;EvalCase 加 tags 字段
    ├── ragas_evaluator.py              # MODIFY: Judge / embedding 改为从 settings 经 LLMFactory / EmbeddingFactory 注入
    ├── composite_evaluator.py          # KEEP(若已支持 ragas + custom 组合)/ MODIFY(若需扩展)
    ├── threshold_evaluator.py          # NEW: 读 acceptance_thresholds + 给 8 项主聚合打 pass/fail + 生成 acceptance_status
    ├── baseline_manager.py             # NEW: 基线标记 / 查询当前基线 / 计算 DeltaReport
    └── testset_synthesizer.py          # NEW: 包装 RAGAS TestsetGenerator,产出含 tags 的候选 JSON

scripts/
├── evaluate.py                         # MODIFY: 集成 acceptance_status 输出 + 自动 delta(若有当前基线);保留向后兼容的纯 retrieval 评估行为
├── synthesize_testset.py               # NEW: 调用 testset_synthesizer 合成中 / 英候选集,落到 tests/fixtures/candidates/<lang>.json
├── refine_testset.py                   # NEW: 提供 keep / edit / drop 最小工具(CLI;Streamlit 嵌入页可选)产出 golden_test_set_<lang>.json
└── backfill_chunk_ids.py               # NEW: 用项目 EmbeddingFactory 把 ground_truth 与 vector store 真实 chunk 做语义匹配回填 expected_chunk_ids

src/observability/dashboard/            # 沿用项目既有路径(由 scripts/start_dashboard.py 启动)
└── pages/evaluation_panel.py           # MODIFY: 加"标记基线"按钮、当前/历史基线展示、delta 视图、趋势折线、视觉区分 pass/fail

tests/
├── fixtures/
│   ├── golden_test_set.json            # KEEP(MVP 占位集合,US1 修复 expected_chunk_ids;加 tags schema)
│   ├── golden_test_set_zh.json         # NEW(US2 产出)
│   ├── golden_test_set_en.json         # NEW(US2 产出)
│   └── candidates/                     # NEW(US2 中间产物;按需加 .gitignore)
└── unit/
    ├── test_evaluation_settings.py     # NEW
    ├── test_eval_runner_validation.py  # NEW(覆盖 FR-007 chunk_id 校验)
    ├── test_eval_runner_by_tag.py      # NEW(覆盖 FR-015 by-tag 聚合)
    ├── test_threshold_evaluator.py     # NEW(覆盖 FR-013 pass/fail)
    ├── test_baseline_manager.py        # NEW(覆盖 FR-008 / FR-009)
    ├── test_ragas_evaluator_factory.py # NEW(覆盖 FR-016 Judge / FR-017 Embedding 接入)
    └── test_testset_synthesizer.py     # NEW(轻量;真合成跑 integration)

config/
└── settings.yaml                       # MODIFY: evaluation 段大幅扩展(见 contracts/settings.evaluation.schema.md)
```

**Structure Decision**:沿用项目既有 `src/observability/evaluation/` 单文件夹放评估实现的格局(`EvalRunner` / `RagasEvaluator` / `CompositeEvaluator` 都已在那)。本 feature 在该文件夹新增 3 个文件(`threshold_evaluator.py` / `baseline_manager.py` / `testset_synthesizer.py`),**不新建子目录、不新增 component 层级**(详见 [research.md § Decision 4](research.md))。Streamlit dashboard 的"评估面板"沿用项目既有页面布局,只在该面板内追加 UI 控件。

## Phase 0 / Phase 1 Outputs

| Phase | 文件 | 内容 |
|---|---|---|
| Phase 0 | [research.md](research.md) | 7 个核心技术决策(RAGAS 版本固定 / Judge LangChain 包装 / 报告归档存储 / 文件夹结构 / by-tag 聚合 schema / RAGAS embedding 复用 / settings 校验时机) |
| Phase 1 | [data-model.md](data-model.md) | 8 个实体的字段定义、约束、状态转换 |
| Phase 1 | [contracts/](contracts/) | 4 份契约文档(settings 段 / report JSON / 金标 JSON / CLI) |
| Phase 1 | [quickstart.md](quickstart.md) | 开发者从零跑 US1 的 10 步指南 |

## Complexity Tracking

> **Constitution Check 全部 PASS,无 violation 需要登记。**
