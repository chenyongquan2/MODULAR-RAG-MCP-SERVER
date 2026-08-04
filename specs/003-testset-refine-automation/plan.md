# Implementation Plan: 金标精修自动化(异源预筛 + borderline 路由)

**Branch**: `dev-from-clean-start`(不单开 feature 分支;speckit 脚本经 `SPECIFY_FEATURE=003-testset-refine-automation` 旁路分支名校验) | **Date**: 2026-08-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-testset-refine-automation/spec.md`

## Summary

把 `scripts/refine_testset.py` 从「逐条 100% 人工确认」改造为「异源 LLM 预筛 → 仅 borderline 走人工 → 抽样合规自检 → 审计记录落盘」,使单语种金标精修的人工耗时从 30-60 分钟降到 ≤ 15 分钟,同时满足 Feature-001 SC-002 的「抽样 10% + 合规率 ≥ 90%」门控。

技术路径:新增 `evaluation.screening_llm` 配置节,复用 `_ragas_wrappers` 已验证的「settings 投影 + LLMFactory」模式创建异源模型实例;判定逻辑落在 `src/observability/evaluation/testset_screener.py`(可单测、无 print),CLI 交互留在 `scripts/`;审计记录以**新增字段** `_review_metadata` 落盘,`_refine_summary` 与 `_schema_version` 保持原样以满足 FR-004。

## Technical Context

**Language/Version**: Python 3.12(实测运行环境;`pyproject.toml` 声明 `>=3.10`)
**Primary Dependencies**: 项目内既有 `LLMFactory` / `Settings`;无新增第三方依赖
**Storage**: 文件(candidate JSON 输入 → golden_test_set JSON 输出),无数据库
**Testing**: pytest(`testpaths = ["tests"]`,marker `unit`),mock 预筛 LLM
**Target Platform**: 本地开发机 CLI(主环境 Windows;stdout 已强制 UTF-8)
**Project Type**: 单体项目内的离线 CLI 工具 + `src/` 内可复用模块
**Performance Goals**: 人工耗时 ≤ 15 分钟/语种(SC-001);预筛机器耗时不设硬指标(约 50 次 LLM 调用)
**Constraints**: FR-004 —— `tests/unit/test_refine_testset.py` 现有断言不得修改;输出 `_schema_version` 必须保持 `1`
**Scale/Scope**: 单次处理约 40-50 条用例;改动 1 个脚本 + 新增 1 个 `src/` 模块 + 1 个配置节

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 架构原则

- [x] **一、Provider 无关性** — **PASS**:预筛模型经 `LLMFactory` + `evaluation.screening_llm` 配置接入,业务代码零具体 provider import(research § D1)
- [x] **二、配置驱动** — **PASS**:新增 `evaluation.screening_llm.*` 配置节 + `ScreeningLLMSettings` dataclass;置信度阈值、borderline 比例上限、合规率阈值均配置化,不写死
- [x] **三、快速失败校验** — **PASS**:同源检测与配置完整性校验在 CLI 入口完成,违反前置条件立即失败并说明原因(FR-002)
- [x] **四、追踪显式化** — **N/A**:本 feature 是离线金标制作 CLI,不属 query / ingestion pipeline,无 trace 语义;审计需求由 `_review_metadata` 落盘满足(research § D6)
- [x] **五、结构化日志(NON-NEGOTIABLE)** — **PASS**:新增 `src/` 模块内零 `print()`,日志走 `observability.logger`;交互式打印保留在 `scripts/`(该条仅约束 `src/`)(research § D5)
- [x] **六、类型安全** — **PASS**:新模块所有 public 函数完整类型注解;判定结果等共享结构以 dataclass 定义
- [x] **七、测试支撑变更(NON-NEGOTIABLE)** — **PASS**:每个实现任务配套 unit test(mock 预筛 LLM);提交前 `pytest tests/unit -v` 全绿

### SDD 纪律

- [x] **八、Spec 先行(NON-NEGOTIABLE)** — **PASS**:`spec.md` 已于 `3243bb4` 提交,本 plan 完全由其推导
- [x] **九、Plan 先于 Tasks(NON-NEGOTIABLE)** — **PASS**:`tasks.md` 将由本 plan 推导,不脱钩生成
- [x] **十、可追溯性(NON-NEGOTIABLE)** — **PASS**:实施期 commit message 引用 task ID(`refs T-XXX`)

> 完整原则定义见 [.specify/memory/constitution.md](../../.specify/memory/constitution.md)。

**Post-Design 复检(Phase 1 完成后)**:设计未引入新 provider 耦合、未新增第三方依赖、未在 `src/` 引入 print、未改动既有测试断言。上述判定全部维持,**无违反项**,故 Complexity Tracking 区段留空。

## Project Structure

### Documentation (this feature)

```text
specs/003-testset-refine-automation/
├── spec.md                      # 需求(已完成)
├── plan.md                      # 本文件
├── research.md                  # Phase 0 产出(已完成,7 项决策)
├── data-model.md                # Phase 1 产出
├── quickstart.md                # Phase 1 产出
├── contracts/
│   ├── cli_contract.md          # CLI 参数与退出码契约
│   └── settings.screening.schema.md   # 配置节 schema
├── checklists/
│   └── requirements.md          # spec 质量清单(已完成,16/16)
└── tasks.md                     # Phase 2 产出(由 /speckit-tasks 生成,本命令不创建)
```

### Source Code (repository root)

```text
config/
├── settings.yaml                        # [改] 新增 evaluation.screening_llm 节
└── prompts/
    └── testset_screening.txt            # [新] 预筛提示词(与代码分离,沿用既有约定)

src/
├── core/
│   └── settings.py                      # [改] 新增 ScreeningLLMSettings dataclass + 装配 + 校验
└── observability/
    └── evaluation/
        ├── _ragas_wrappers.py           # [改] 抽出「子配置节 → BaseLLM」共享 helper
        │                                #      + 新增 get_screening_identifier()
        └── testset_screener.py          # [新] 预筛判定、三态路由、抽样与合规率计算(零 print)

scripts/
└── refine_testset.py                    # [改] 新增 --auto-mode;接预筛;borderline 走既有交互
                                         #      默认路径行为零变化(FR-004)

tests/unit/
├── test_refine_testset.py               # [不改断言] FR-004 回归保护
└── test_testset_screener.py             # [新] mock 预筛 LLM,覆盖三态路由/降级/抽样/审计
```

**Structure Decision**: 沿用项目既有的单体 `src/` + `scripts/` 分层,不引入新顶层目录。分层依据见 research § D5 —— 判定逻辑入 `src/`(受宪法 Rule V 约束、需可单测),交互层留 `scripts/`(print 为正当 CLI 输出)。评估相关模块统一归入既有的 `src/observability/evaluation/`,与 `testset_synthesizer.py` 同级,保持「合成 → 精修」两端对称。

## Complexity Tracking

> Constitution Check 无违反项,本区段留空。
