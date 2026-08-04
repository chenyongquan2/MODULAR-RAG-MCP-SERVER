---

description: "Task list for Feature-003 金标精修自动化"
---

# Tasks: 金标精修自动化(异源预筛 + borderline 路由)

**Input**: Design documents from `specs/003-testset-refine-automation/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: 本 feature 的测试任务**不是可选项**。宪法 [§ VII 测试支撑变更](../../.specify/memory/constitution.md) 为 NON-NEGOTIABLE,要求每个实现任务配套 unit test,提交前 `pytest tests/unit -v` 通过。

**Organization**: 按 user story 分组,每组可独立实现与验收。

> **修订记录(2026-08-04,speckit-analyze 后)**:原 29 任务版本存在 1 个 CRITICAL(FR-010/FR-011 有实现无测试,违反宪法 § VII)与 1 个 HIGH(SC-006 在原设计下不可计算)。本版新增 T016 / T018 / T027 三个任务并调整 T023–T026,任务数 29 → 32,ID 已重编号。

## Format

`- [ ] TID [P?] [Story?] 描述(含文件路径)`

- **[P]**:可并行(不同文件、无未完成依赖)
- **[Story]**:所属 user story(US1/US2/US3)

## Path Conventions

单体项目:仓库根下 `src/`、`scripts/`、`tests/`、`config/`(见 [plan.md § Project Structure](plan.md))。

---

## Phase 1: Setup(共享基础设施)

**Purpose**:配置与提示词就位,不含代码逻辑

> **实施期修正(2026-08-04)**:T001 被标为 Phase 1 独立任务是**错的**。实测 YAML 加了 `screening_llm` 节后,`load_settings()` 立刻抛
> `TypeError: EvaluationSettings.__init__() got an unexpected keyword argument 'screening_llm'` —— 因为装配代码会把未知子节当顶层 kwarg 透传。
> **T001 硬依赖 T003**(dataclass + 装配),两者必须同批落地,否则仓库处于 `load_settings()` 全线失败的坏状态。已按此顺序实施。

- [x] T001 [P] 在 [config/settings.yaml](../../config/settings.yaml) 的 `evaluation` 段下新增 `screening_llm` 节,字段与默认值照 [contracts/settings.screening.schema.md § 1](contracts/settings.screening.schema.md);`provider`/`model` 留空(默认交互模式不需要),阈值取默认 `keep_threshold: 0.80` / `drop_threshold: 0.80` / `borderline_ratio_warn: 0.40` / `sample_ratio: 0.10` / `compliance_gate: 0.90`
- [x] T002 [P] 新建 [config/prompts/testset_screening.txt](../../config/prompts/testset_screening.txt) 预筛提示词:输入单条用例的 query / ground_truth / expected_chunk_ids / 合成期 contexts,要求返回含「三态结论 + 置信度 + 理由」的 JSON;判定标准对齐 SC-002 三项(question 通顺 / ground_truth 可在语料中验证 / expected_chunk_ids 指向真实 chunk)(refs [research § Decision 4](research.md))

---

## Phase 2: Foundational(blocking prerequisites)

**Purpose**:配置装配与异源 LLM 构造能力。**所有 user story 都依赖本阶段**

**⚠️ CRITICAL**:T003-T005 完成前不能开始任何 user story

- [x] T003 在 [src/core/settings.py](../../src/core/settings.py) 新增 `ScreeningLLMSettings` dataclass(11 个字段见 [data-model.md § 4](data-model.md)),经既有 `_build_sub_settings` 装配进 `EvaluationSettings`,并在 `_validate_evaluation_settings` 中加数值区间校验(阈值均 `0.0 < x ≤ 1.0`,`temperature ∈ [0,2]`,`request_timeout_sec > 0`),非法立即抛 `ValueError`;**不在加载期强制 `provider`/`model` 非空**——否则未配置该节的既有用法全部启动失败,违反 FR-004(理由见 [contracts/settings.screening.schema.md § 3](contracts/settings.screening.schema.md);参照既有 `judge_llm` 在 settings.py:715 的同样处理)
- [x] T004 在 [src/observability/evaluation/_ragas_wrappers.py](../../src/observability/evaluation/_ragas_wrappers.py) 把「子配置节 → `BaseLLM`」的 settings 投影逻辑(现内联于 `build_ragas_judge` 第 78-92 行)抽成共享函数,并改造 `build_ragas_judge` 调用它。**这是对 Feature-001 生产路径的重构**,须单独提交且跑通既有 ragas 相关单测(refs [research § Decision 1](research.md))
- [x] T005 在 [src/observability/evaluation/_ragas_wrappers.py](../../src/observability/evaluation/_ragas_wrappers.py) 新增 `get_screening_identifier(settings) -> str`,返回 `f"{provider}:{model}"`,与既有 `get_judge_identifier`(第 317 行)对称(依赖 T004 同文件改动完成;refs [contracts/settings.screening.schema.md § 4](contracts/settings.screening.schema.md))

### Tests for Foundational(宪法 § VII NON-NEGOTIABLE)

- [x] T006 [P] 新建 [tests/unit/test_settings_screening.py](../../tests/unit/test_settings_screening.py):覆盖 `ScreeningLLMSettings` 默认值、`${VAR}` 注入、各阈值越界抛 `ValueError`、以及**未配置 `screening_llm` 时 `load_settings()` 仍正常返回**(FR-004 关键回归点)
- [x] T007 运行既有 ragas / 评估相关单测,确认 T004 重构零回归:`pytest tests/unit -k "ragas or evaluation or settings" -v`

**Checkpoint**:异源 LLM 可经配置构造,标识可比较 —— user story 可以开工

---

## Phase 3: User Story 1 - 预筛后只人工处理疑难用例(Priority: P1)🎯 MVP

**Goal**:auto 模式下高置信 keep/drop 自动决策,只有 borderline 停下来问人。单独交付即可把人工耗时从 30-60 分钟压到十几分钟。

**Independent Test**:准备含明显优质 / 明显劣质 / 模糊用例的 candidate,以 `--auto-mode` 运行,验证仅模糊用例触发人工提示,产出金标含预期保留用例。

### Tests for User Story 1(宪法 § VII NON-NEGOTIABLE)

> 先写测试并确认失败,再实现

- [x] T008 [P] [US1] 新建 [tests/unit/test_testset_screener.py](../../tests/unit/test_testset_screener.py):mock 预筛 LLM,覆盖三态路由(`keep` 且置信度 ≥ 阈值 → 自动保留 / `drop` 且 ≥ 阈值 → 自动丢弃 / 其余 → borderline)与**全部降级路径**(LLM 抛异常、返回非 JSON、JSON 缺字段、置信度越界 → 一律 borderline)。断言不变式:**任何异常路径都不得流向自动保留或自动丢弃**(refs FR-001/FR-008, [data-model.md § 2](data-model.md))
- [x] T009 [P] [US1] 在 [tests/unit/test_testset_screener.py](../../tests/unit/test_testset_screener.py) 追加同源检测用例:标识串完全相等 → 判定同源;**provider 相同但 model 不同 → 判定异源**(用真实值 `glm:minimax/minimax-m2.7` vs `glm:glm-4.6`);`_synthesis_metadata` 缺失或 `judge_llm_identifier` 为空 → 判定「无法确认」(refs FR-002, [research § Decision 2](research.md);依赖 T008 建文件)

### Implementation for User Story 1

- [x] T010 [US1] 新建 [src/observability/evaluation/testset_screener.py](../../src/observability/evaluation/testset_screener.py):定义 `ScreeningVerdict` dataclass(`decision` / `confidence` / `reason` / `case_index`)与三态枚举,实现单条用例判定 `screen_case()` —— 加载 T002 提示词、经 T004 helper 构造的 `BaseLLM` 调用、解析 JSON、按阈值路由、异常一律降级 borderline。**零 `print()`**,日志走 `observability.logger`(宪法 § V NON-NEGOTIABLE;refs [research § Decision 5](research.md))
- [x] T011 [US1] 在 [src/observability/evaluation/testset_screener.py](../../src/observability/evaluation/testset_screener.py) 实现 `check_source_divergence(settings, candidate)`,比较 `get_screening_identifier()` 与 `candidate["_synthesis_metadata"]["judge_llm_identifier"]`,返回三态结果(异源 / 同源 / 无法确认);**比完整标识串,不比 provider**(refs FR-002;依赖 T005, T010)
- [x] T012 [US1] 在 [src/observability/evaluation/testset_screener.py](../../src/observability/evaluation/testset_screener.py) 实现批量预筛 `screen_all()`:逐条调用 `screen_case()`,汇总 verdict 列表(按 `case_index` 索引,供后续决策来源反查)并计算 borderline 占比;**全部调用均失败时抛可区分的异常**供 CLI 映射为退出码 3;**空输入(0 条用例)时不发起任何 LLM 调用,直接返回空结果**(refs spec Edge Cases「评审模型整体不可用」「空输入」;依赖 T010)
- [ ] T013 [US1] 在 [scripts/refine_testset.py](../../scripts/refine_testset.py) 的 `parse_args()` 新增 `--auto-mode` 与 `--allow-same-source` 参数,并在 `main()` 增加 auto 模式入口校验:`screening_llm.provider/model` 为空 → 退出码 2;同源 → 退出码 2;无法确认异源且无 `--allow-same-source` → 退出码 2 并提示该参数(refs [contracts/cli_contract.md § 1-2](contracts/cli_contract.md);依赖 T011)
- [ ] T014 [US1] 在 [scripts/refine_testset.py](../../scripts/refine_testset.py) 新增 `auto_refine()` 流程:调 `screen_all()`,自动保留/丢弃直接计入,borderline 复用既有 `_format_case_for_review()` + y/e/d/s/q 交互;**维护 `case_index → 决策来源` 内存映射**(auto-kept / human-kept,供 US3 的 SC-006 拆分使用,不写入 case 内部);borderline 占比超 `borderline_ratio_warn` 时告警(FR-011);预筛整体失败 → 退出码 3;中断保留已完成决策并标 `v0.9-partial`(FR-010)。**不改动既有 `interactive_refine()`**,默认路径零变化(依赖 T012, T013;refs [data-model.md § 3 决策来源追踪](data-model.md))
- [ ] T015 [P] [US1] 新建 [tests/unit/test_refine_testset_auto.py](../../tests/unit/test_refine_testset_auto.py) CLI 契约测试:同源 → 退出码 2 且不写文件;缺标识无豁免 → 退出码 2;全部预筛失败 → 退出码 3;**不带 `--auto-mode` 时零 LLM 调用且输出无 `_review_metadata`**(依赖 T014;refs [contracts/cli_contract.md § 5](contracts/cli_contract.md))
- [ ] T016 [US1] 在 [tests/unit/test_refine_testset_auto.py](../../tests/unit/test_refine_testset_auto.py) 补 **FR-010 与 FR-011 的测试**(analyze 发现的宪法 § VII 缺口):① auto 模式下于 borderline 处置期中断 → 已完成的自动决策与人工决策全部保留、`version == "v0.9-partial"`、退出码 130;② borderline 占比超 `borderline_ratio_warn` → 产生对应 warning 且不影响退出码(依赖 T015 同文件)
- [ ] T017 [US1] FR-004 回归验证:`pytest tests/unit/test_refine_testset.py -v` 全过且**未修改任何断言**(`git diff` 该文件应为空);再跑 `pytest tests/unit -v` 全量确认无连带回归
- [ ] T018 [US1] **SC-001 实测**(analyze 发现的覆盖缺口):用真实 candidate(如 `tests/fixtures/candidates/zh_smoke_v2.json`)配好异源预筛后实跑 `--auto-mode`,**记录人工实际耗时**并与 30-60 分钟基线对比,结论写入本 feature 的验收记录。未达 ≤ 15 分钟则回查阈值配置(而非直接判定实现失败,见 T030)

### US1 验收

T018 的耗时实测通过即视为 MVP 达标 —— 本 feature 的核心价值(SC-001/SC-002)已交付。

**Checkpoint**:US1 独立可用

---

## Phase 4: User Story 2 - 金标自带可追溯的审计记录(Priority: P2)

**Goal**:金标文件自身即可回答「多少条机器决定、用哪个模型、阈值多少」,无需翻日志。

**Independent Test**:跑完 auto 模式后检查金标的 `_review_metadata`,各计数与实际运行一致、含模型标识与阈值快照。

### Tests for User Story 2(宪法 § VII NON-NEGOTIABLE)

- [ ] T019 [P] [US2] 新建 [tests/unit/test_review_metadata.py](../../tests/unit/test_review_metadata.py):断言 `ReviewMetadata` 各字段齐全([data-model.md § 3](data-model.md) 的 10 个字段)、不变式 `auto_decided + human_reviewed == 输入用例总数`(非 partial 时)、`partial=True` 时 `version` 为 `v0.9-partial`;并**断言 `_refine_summary` 的 4 个键与 `_schema_version == 1` 未被改动**(FR-004 硬约束;refs [research § Decision 3](research.md))

### Implementation for User Story 2

- [ ] T020 [US2] 在 [src/observability/evaluation/testset_screener.py](../../src/observability/evaluation/testset_screener.py) 实现 `build_review_metadata()`,由 verdict 列表 + 人工决策计数 + settings 构造审计 dict,含 `screening_llm_identifier` / `synthesis_llm_identifier` / `thresholds_snapshot` / `borderline_ratio` / `warnings` / `partial`(依赖 T012;refs FR-005)
- [ ] T021 [US2] 修改 [scripts/refine_testset.py](../../scripts/refine_testset.py) 的 `_build_final()`,支持注入可选 `_review_metadata` 字段。**必须保持 `_refine_summary` 键名语义与 `_schema_version: 1` 不变**,且默认交互模式下不写出该字段(refs [research § Decision 3](research.md);依赖 T020)
- [ ] T022 [US2] FR-004 回归复验:`pytest tests/unit/test_refine_testset.py -v` 仍全过(T021 直接改了被断言的 `_build_final`,这一步不可跳过)

### US2 验收

打开产出金标,`_review_metadata` 能回答 SC-005 的四个问题。

**Checkpoint**:US1 + US2 均独立可用

---

## Phase 5: User Story 3 - 抽样合规自检作为质量门控(Priority: P3)

**Goal**:收尾时按 SC-002 抽 10% 保留用例人工确认,当场算合规率并记入审计,不达标告警。

**Independent Test**:跑一份含 20 条保留用例的 candidate,验证抽 2 条、合规率计算正确、不达标时告警。

### Tests for User Story 3(宪法 § VII NON-NEGOTIABLE)

- [ ] T023 [P] [US3] 新建 [tests/unit/test_compliance_sample.py](../../tests/unit/test_compliance_sample.py):① 抽样数 `max(1, ceil(n × sample_ratio))` —— 20 条 → 2、10 条 → 1、**3 条 → 1(不跳过自检)**、**0 条 → 不抽样且 `compliance_rate` 为 `None`**(analyze 发现的空输入缺口);② 合规率计算;③ `compliance_rate < compliance_gate` 时 `gate_passed=False` 且产生 warning,**告警不改变退出码**;④ **SC-006 拆分**:抽中用例含 auto-kept 与 human-kept 混合时,`auto_kept_sampled` / `auto_kept_compliant` / `auto_kept_noncompliance_rate` 只统计 auto-kept 子集,子集为空时该率为 `null`(refs FR-006/FR-007/SC-006, [data-model.md § 3](data-model.md))

### Implementation for User Story 3

- [ ] T024 [US3] 在 [src/observability/evaluation/testset_screener.py](../../src/observability/evaluation/testset_screener.py) 实现 `pick_compliance_sample()` 与 `summarize_compliance()`:随机抽样(不固定 seed)、返回 `sampled_case_indices` / `sample_size` / `compliant` / `compliance_rate` / `gate_passed`,**并按 T014 提供的决策来源映射拆出 `auto_kept_sampled` / `auto_kept_compliant` / `auto_kept_noncompliance_rate`**(SC-006 的唯一计算来源;refs [research § Decision 7](research.md), [data-model.md § 3](data-model.md))
- [ ] T025 [US3] 在 [scripts/refine_testset.py](../../scripts/refine_testset.py) 的 auto 流程收尾接入自检:逐条展示抽中用例并请人确认合规性,新增 `--skip-compliance-sample` 参数(跳过时 `compliance` 为 `null` 并记 warning);合规率不达标时**明确告警但仍写出文件、退出码保持 0**(refs FR-007, [contracts/cli_contract.md § 2](contracts/cli_contract.md);依赖 T024)
- [ ] T026 [US3] 把自检结果(含 3 个 auto-kept 拆分字段)填入 `ReviewMetadata.compliance`,并把告警追加到 `warnings`;确认 SC-006 可仅凭金标文件计算(依赖 T020, T024)
- [ ] T027 [US3] 明确**重复运行**行为(analyze 发现的 edge case 缺口):对同一 candidate 二次运行 `--auto-mode` 时,输出路径已存在金标的处置方式须与现状一致或更保守(不因随机抽样的偶然性静默覆盖成更差版本);在 [tests/unit/test_refine_testset_auto.py](../../tests/unit/test_refine_testset_auto.py) 补对应断言(refs spec Edge Cases「重复运行」)

### US3 验收

抽样自检可跑通,合规率与门控告警符合 SC-003;SC-006 可由 `_review_metadata.compliance` 直接算出。

**Checkpoint**:三个 story 全部独立可用

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T028 按 [quickstart.md](quickstart.md) 全流程实跑一遍(配置 → auto 模式 → 看审计记录 → 阈值校准),修正文档与实现的偏差
- [ ] T029 [P] 更新 [CLAUDE.md](../../CLAUDE.md) § Evaluation System 的「关键 CLI」表格,补 `refine_testset.py --auto-mode` 用法与 `evaluation.screening_llm` 配置指引
- [ ] T030 用真实 candidate 跑一轮并记录 `borderline_ratio`,据实际分布校准 `keep_threshold` / `drop_threshold` 默认值(spec Assumptions 明确该阈值是初始猜测,需首轮后校准)
- [ ] T031 FR / SC 覆盖度自查:逐条核对 FR-001..FR-011 与 SC-001..SC-006 均有对应实现与测试,缺口补齐(重点复核 analyze 曾标出的 FR-010 / FR-011 / SC-001 / SC-006 四项)
- [ ] T032 全量 `pytest tests/unit -v` 通过;确认 `src/` 内新增代码零 `print()`(宪法 § V):`git grep -n "print(" -- src/observability/evaluation/testset_screener.py` 应为空

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1 Setup**(T001-T002):无依赖,可立即开始
- **Phase 2 Foundational**(T003-T007):依赖 Phase 1 —— **阻塞所有 user story**
- **Phase 3-5 User Stories**:均依赖 Phase 2 完成
- **Phase 6 Polish**:依赖所需 story 全部完成

### User Story 依赖

- **US1(P1)**:Phase 2 后即可开始,不依赖其他 story
- **US2(P2)**:T020 依赖 US1 的 T012(verdict 列表);实践上跟在 US1 之后
- **US3(P3)**:T024 依赖 US1 的 T014(决策来源映射)与 T012;T026 依赖 US2 的 T020

> 三个 story 并非完全解耦 —— 审计记录建立在预筛结果之上,抽样自检的 SC-006 拆分又依赖 auto 流程记录的决策来源。但每个 story 都有独立的验收标准与可交付价值,可在任一 checkpoint 停下。

### 关键串行约束(同文件)

| 文件 | 串行任务 |
|---|---|
| `src/core/settings.py` | T003 |
| `_ragas_wrappers.py` | T004 → T005 |
| `testset_screener.py` | T010 → T011 → T012 → T020 → T024 |
| `scripts/refine_testset.py` | T013 → T014 → T021 → T025 |
| `tests/unit/test_testset_screener.py` | T008 → T009 |
| `tests/unit/test_refine_testset_auto.py` | T015 → T016 → T027 |

### 并行机会

- T001 ‖ T002(配置与提示词,不同文件)
- T008、T015、T019、T023 分属不同测试文件,彼此可并行
- T029 与 T030/T031 可并行

---

## Parallel Example: Phase 1

```bash
# Phase 1 两个任务完全独立
Task: "T001 config/settings.yaml 新增 screening_llm 节"
Task: "T002 新建 config/prompts/testset_screening.txt"
```

---

## Implementation Strategy

### MVP First(仅 US1)

1. Phase 1 Setup(T001-T002)
2. Phase 2 Foundational(T003-T007)—— **阻塞点,必须先完成**
3. Phase 3 US1(T008-T018)
4. **停下验收**:T018 实测人工耗时,确认 SC-001 达标
5. 此时已交付本 feature 的核心价值

### 增量交付

1. Setup + Foundational → 异源 LLM 能力就位
2. \+ US1 → 效率收益到手(MVP,SC-001/SC-002)
3. \+ US2 → 审计可追溯(SC-005)
4. \+ US3 → 质量门控闭环(SC-003/SC-006)
5. Polish → 阈值校准 + 文档对齐

### 风险提示

- **T004 是唯一触及 Feature-001 生产路径的任务**(重构 `build_ragas_judge`)。单独提交、单独验证,不要与新功能混在一个 commit 里
- **T017 / T022 是 FR-004 的两道闸门**。T021 直接修改了被既有测试断言的 `_build_final()`,T022 不可跳过;T017 要求 `git diff test_refine_testset.py` 为空,防止靠改断言蒙过
- **T014 的决策来源映射是 SC-006 的前提**。若 T014 漏了这个映射,T024 的 auto-kept 拆分无从计算 —— 这是 analyze 发现的原设计缺口,别再漏掉
- 阈值默认值(T001)是猜测值,T030 才是真正的校准步骤;T018 若耗时未达标,**先怀疑阈值而非实现**

---

## Notes

- `[P]` = 不同文件、无未完成依赖
- 提交信息按宪法 § X 引用 task ID(`refs T-0XX`)
- 每个任务或逻辑组完成后即提交
- 任一 checkpoint 均可停下独立验收
