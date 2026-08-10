# Specification Quality Checklist: 带权重的结果融合

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## 校验记录

**第 1 轮**（2026-08-10）发现 3 项问题，已修正：

| 项 | 问题 | 修正 |
|---|---|---|
| All FR have clear acceptance criteria | **FR-002（权重与路径不得按顺序对应）无任何 SC 覆盖** —— 而这正是 spec 自己在 Edge Cases 里标注的「最危险失败模式」：错配后不报错、只是效果悄悄变差 | 新增 SC-012：改变传入顺序，融合输出必须逐条完全不变 |
| All FR have clear acceptance criteria | FR-004（某路返回空时不得影响另一路相对排序）无 SC 覆盖 | 新增 SC-013 |
| Requirements are testable and unambiguous | US2 验收场景 1 有笔误「评估judgement判据」 | 改为「选择判据」 |

**第 2 轮**（2026-08-10）16 项全部通过。

## FR → SC 覆盖映射

复核用，确保无遗漏：

| FR | 覆盖它的 SC |
|---|---|
| FR-001 权重机制 | SC-004 |
| FR-002 不按顺序对应 | **SC-012**（第 1 轮补） |
| FR-003 未配置时等权 | SC-006 |
| FR-004 空路不影响他路 | **SC-013**（第 1 轮补） |
| FR-005 权重配置化 | SC-004 / SC-007 |
| FR-006 平滑参数配置化 | SC-007（非法值拒绝路径同源） |
| FR-007 非法权重启动期拒绝 | SC-007 |
| FR-008 追踪含生效权重 | SC-008 |
| FR-009 / FR-010 校准有据可复现 | SC-010 |
| FR-011 三方对比 | SC-009 / SC-001 / SC-002 / SC-003 |

## 术语口径说明

本 spec 刻意使用领域中性词以满足「技术无关」要求，与实现术语的对应关系如下，供 plan 阶段衔接：

| spec 用词 | 实现对应 |
|---|---|
| 语义匹配路径 | dense / `DenseRetriever` |
| 关键词匹配路径 | sparse / `SparseRetriever`（BM25） |
| 基于排名的倒数融合 | RRF |
| 融合平滑参数 | RRF 的 `k`（当前硬编码 60） |
| 检索路径（Route） | 传入 `Fusion.fuse()` 的一个结果列表 |

## Notes

- 本 feature 是**缺陷修复 + 能力补全**：既消除 Feature-004 实测到的召回倒退，也修掉一处既有的配置驱动违规（融合器构造时不读任何配置，平滑参数硬编码）。
- 倒退的实测证据见 [Feature-004 验收记录 § 四](../../004-retrieval-infra-fix/acceptance.md)。
- Assumptions 中已预先承认一种可能结果：**最优权重可能就是「关键词路径权重极低」**，使带权混合收敛到接近纯语义检索。届时 SC-011（严格优于任一单路）可能无法达成，但 SC-001/002（消除倒退）仍然成立 —— 这不是验收放水，而是对结果不确定性的诚实预设。
