# Coverage Audit: FR / SC → 实现与测试

**Feature**: 003-testset-refine-automation
**Created**: 2026-08-04(T031)
**Purpose**: 逐条核对每项需求都有对应实现**与**测试,缺口当场补齐

宪法 [§ VII](../../../.specify/memory/constitution.md) 为 NON-NEGOTIABLE:每个实现任务必须配套 unit test。本表是该条款的验收依据。

## Functional Requirements

| FR | 实现 | 测试 | 状态 |
|---|---|---|---|
| FR-001 三态判定 + 置信度 | `testset_screener.screen_case()` | `TestThreeWayRouting`(7) | ✅ |
| FR-002 异源强制,同源拒绝 | `check_source_divergence()` + `check_auto_preconditions()` | `TestSourceDivergence`(8)、`TestAutoPreconditions`(6) | ✅ |
| FR-003 仅 borderline 走人工 | `auto_refine()` | `test_only_borderline_prompts_human` | ✅ |
| FR-004 默认行为零变化 | `--auto-mode` 分支隔离;`_build_final(review_metadata=None)` 不写字段 | `TestDefaultPathUnchanged`(2) + **`git diff` 闸门** | ✅ |
| FR-005 审计记录落盘 | `build_review_metadata()` | `TestReviewMetadataFields`(9) | ✅ |
| FR-006 抽样 10%,不足 1 条取 1 | `compute_sample_size()` / `pick_compliance_sample()` | `TestSampleSize`(9)、`TestPickSample`(5) | ✅ |
| FR-007 合规率不达标告警 | `summarize_compliance()` + `run_compliance_sample()` | `TestSummarizeCompliance`(6) + **`TestComplianceGateIsAdvisory`** | ✅ |
| FR-008 失败一律降级 borderline | `screen_case()` 全异常捕获 | `TestDegradationPaths`(12 parametrize + 5) | ✅ |
| FR-009 配置驱动,不硬编码 | `ScreeningLLMSettings` + `LLMFactory` | `test_settings_screening`(18) | ✅ |
| FR-010 中断保住进度 | `auto_refine()` 的 `KeyboardInterrupt` 分支 | `TestInterruptPreservesProgress`(3) | ✅ |
| FR-011 borderline 超限告警 | `auto_refine()` 比对 `borderline_ratio_warn` | `TestBorderlineRatioWarning`(3) | ✅ |

## Success Criteria

| SC | 手段 | 状态 |
|---|---|---|
| SC-001 人工耗时 ≤ 15 min | T018 真实实测 | ⏳ **待实测**(需真实 API + 人工计时) |
| SC-002 人工处置占比 ≤ 25% | `_review_metadata` 可算出 `(human_reviewed + compliance.sample_size) / 总数` | ⏳ 随 T018 一并测量 |
| SC-003 抽样合规率 ≥ 90% | `compliance.gate_passed` | ✅ 机制就绪,实际值待 T018 |
| SC-004 默认模式零变化 | FR-004 三道闸门 | ✅ |
| SC-005 金标自解释 | `_review_metadata` 10 字段 | ✅ `test_auto_mode_output_carries_review_metadata` |
| SC-006 自动保留准确性 ≤ 10% 不合规 | `compliance.auto_kept_noncompliance_rate` | ✅ `test_compliance_split_reaches_metadata`、`test_sc006_threshold_is_computable` |

## 本次自查发现并补齐的缺口

**FR-007 缺端到端验证**:此前只在单元层断言 `gate_passed=False`,**没有验证「告警但退出码仍为 0、文件仍写出」**这条契约。FR-007 的要害恰恰是「告警是提示性的」—— 若实现成硬失败,使用者会以为金标没产出。

已补 `TestComplianceGateIsAdvisory::test_failed_gate_still_exits_0_and_writes_file`:构造合规率 0% 的运行,断言退出码 0、文件存在、`gate_passed=False`、告警同时进 stderr 与审计记录。

## 测试规模

| 文件 | 用例数 |
|---|---|
| `test_settings_screening.py` | 18 |
| `test_testset_screener.py` | 28 |
| `test_refine_testset_auto.py` | 25 |
| `test_review_metadata.py` | 19 |
| `test_compliance_sample.py` | 21 |
| **合计** | **111** |

## 遗留

SC-001 / SC-002 的实际数值只能由 T018 真实运行产出,无法用 mock 替代。届时需:配好异源 `screening_llm` → 用真实 candidate 跑 `--auto-mode` → 记录人工耗时与 `borderline_ratio` → 据实际分布执行 T030 的阈值校准。
