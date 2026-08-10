# Implementation Plan: 带权重的结果融合

**Branch**: `dev-from-clean-start`（不单开分支，用 `SPECIFY_FEATURE=005-weighted-fusion` 调用 speckit 脚本） | **Date**: 2026-08-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/005-weighted-fusion/spec.md`

## Summary

消除 Feature-004 实测到的倒退：混合检索在英文金标上 recall 42.4% 低于纯语义的 45.7%、hit_rate 61.9% 低于 69.0%。根因是 RRF 公式 `1/(k+rank)` 无权重项，两路一视同仁，关键词路径的噪音命中挤掉了语义路径的正确结果。

技术路径三步：给 RRF 加权重项（`weight/(k+rank)`）→ 把权重与平滑参数纳入配置（顺带修掉 `Fusion()` 不读配置、`k=60` 硬编码这处既有的配置驱动违规）→ 用「一次检索、多次离线融合」在英文金标上校准出推荐权重。

关键设计决策见 [research.md](./research.md)，其中两条值得在此点明：

- **Decision 2（接口改命名映射）**有一个现成的反面例证：`fusion.py:87` 的注释把两路顺序写反了，而 `hybrid_search.py:204` 传的是相反顺序。等权时无害所以一直没被发现；加权重后同样的混淆就是真 bug，且不报错。
- **Decision 5（缓存重放）**把校准的 API 调用从 384 次降到 48 次。权重只影响融合、不影响检索，因此两路排名列表可缓存后离线重放 —— Feature-004 期间反复遭遇网关 503 与超时，长批量任务必须避免。

## Technical Context

**Language/Version**: Python 3.12（`.venv`，protobuf 3.20.3 —— 全局 Python 的 5.29.3 会让 `import chromadb` 失败）
**Primary Dependencies**: 无新增依赖。改动集中在既有的 `Fusion` / `HybridSearch` / `settings`
**Storage**: 校准缓存为 JSON 文件（两路排名列表），不入向量库
**Testing**: pytest（`.venv/Scripts/python.exe -m pytest tests/unit -v`）
**Target Platform**: Windows 11 本机开发
**Project Type**: 单体 Python 项目
**Performance Goals**: 融合是纯内存计算，权重不引入额外 I/O；校准全程 ≤ 48 次 embedding 调用
**Constraints**: 未配置权重时行为必须逐条不变（FR-003）；权重与路径的对应不得依赖参数顺序（FR-002）
**Scale/Scope**: 2 条检索路径、48 条金标（英 42 / 中 6）、8 组候选权重

## Constitution Check

*GATE: 逐条标记，NON-NEGOTIABLE 条款不允许 Complexity Tracking 豁免。*

### 架构原则

- [x] **一、Provider 无关性** — **PASS**。不新增 provider、不新增组件层级。`Fusion` 是既有的算法实现，本 feature 只扩展其参数；不引入 provider 选择需求（融合算法族由 `fusion_algorithm` 字段保留，但本次仅一种实现）。
- [x] **二、配置驱动** — **PASS，且修复一处既有违规**。新增 `retrieval.rrf_k` 与 `retrieval.fusion_weights` 字段 + `src/core/settings.py` dataclass。此前 `Fusion()` 在 `hybrid_search.py:91` 不带参数构造、`DEFAULT_K = 60` 硬编码、配置段无对应字段 —— 本 feature 一并补正。
- [x] **三、快速失败校验** — **PASS**。负权重 / 全零权重 / 非数值 / `rrf_k ≤ 0` 一律在 `load_settings()` 抛 `SettingsError`，不静默回退（清单见 research.md Decision 3）。
- [x] **四、追踪显式化** — **PASS**。`fuse()` 不新增 trace 参数（它本就不接 trace；打点在 `hybrid_search` 的 `finish_stage("fusion", ...)` 中完成）。FR-008 要求的生效权重写入该处既有的 payload，不引入隐式 trace 状态。
- [x] **五、结构化日志(NON-NEGOTIABLE)** — **PASS**。`src/` 内零 `print()`；校准脚本位于 `scripts/`，人类可读输出符合宪法对 CLI 的许可。
- [x] **六、类型安全** — **PASS**。`fuse()` 入参形态变更后类型注解同步更新；不新增跨模块共享类型（权重是 `Dict[str, float]`，属配置而非领域对象，无需进 `core/types.py`）。
- [x] **七、测试支撑变更(NON-NEGOTIABLE)** — **PASS**。每个实现任务配套 unit test；两条关键守卫测试（顺序无关 SC-012、空路不影响他路 SC-013）单列，清单见 Project Structure。

### SDD 纪律

- [x] **八、Spec 先行(NON-NEGOTIABLE)** — **PASS**。`specs/005-weighted-fusion/spec.md` 已存在并通过 16 项质量校验。
- [x] **九、Plan 先于 Tasks(NON-NEGOTIABLE)** — **PASS**。`tasks.md` 将由本 plan 推导。
- [x] **十、可追溯性(NON-NEGOTIABLE)** — **PASS**。实施期 commit 引用 `refs T-XXX`。

### 一处需要说明的设计张力

**`fuse()` 改变入参形态属于破坏性接口变更**，宪法《架构稳定性》要求新增组件层级须论证，但未直接约束既有方法的签名演进。

影响面已核实：生产调用点仅 `hybrid_search.py:204` 一处，加 `tests/unit/test_fusion_rrf.py` 9 个用例与一处 docstring 示例。`Fusion` 不属于 `src/libs/<component>/` 的 provider 体系，无第三方实现需要同步。

**因此这不构成宪法偏离，无 Complexity Tracking 登记项。** 保留旧位置列表形态作为兼容层反而更糟 —— 它会让「按下标对应权重」这条错误路径继续存在，直接违背 FR-002 的立法意图。

## Project Structure

### Documentation (this feature)

```text
specs/005-weighted-fusion/
├── spec.md              # ✅ 已完成（11 FR / 13 SC）
├── plan.md              # ✅ 本文件
├── research.md          # ✅ 已完成（6 项决策）
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/
│   └── fusion.contract.md     # fuse() 的入出参与权重语义契约
├── checklists/
│   └── requirements.md  # ✅ 16 项全通过
└── tasks.md             # Phase 2 输出（由 /speckit.tasks 生成）
```

### Source Code (repository root)

```text
src/
├── core/
│   ├── query_engine/
│   │   ├── fusion.py            # 【改】加权重项；入参改命名映射；k 由构造参数注入
│   │   └── hybrid_search.py     # 【改】:91 从 settings 构造 Fusion；:204 改传映射；
│   │                            #       fusion 打点 payload 加生效权重
│   └── settings.py              # 【改】RetrievalSettings 加 rrf_k / fusion_weights + 校验
└── (其余不动)

config/
└── settings.yaml               # 【改】retrieval 段加 rrf_k 与 fusion_weights

scripts/
└── calibrate_fusion_weights.py # 【新增】一次检索缓存 + 离线权重扫描 + 三方对比

tests/unit/
├── test_fusion_rrf.py           # 【改】适配新入参形态；新增权重语义、顺序无关、空路用例
├── test_settings_retrieval.py   # 【新增】rrf_k / fusion_weights 的校验与向后兼容
├── test_hybrid_search_fusion_wiring.py  # 【新增】Fusion 由 settings 构造；打点含权重
└── test_calibrate_fusion_weights.py     # 【新增】缓存重放的确定性与判据逻辑
```

**Structure Decision**: 单体项目结构，无新增目录。改动集中在融合环节的三个既有文件 + 一个校准脚本。校准脚本放 `scripts/`（非 `scripts/dev/`）—— 它产出的是验收证据，需要可复现、可被他人重跑，不是一次性探索。

## 实施顺序与依赖

```
① 配置字段 + 校验（settings）
        ↓  Fusion 需要从配置拿 k 与权重
② Fusion 加权重 + 入参改命名映射 + 两条守卫测试
        ↓  HybridSearch 需要按新形态调用
③ HybridSearch 接线（从 settings 构造 + 传映射 + 打点加权重）
        ↓  校准需要可运行的带权融合
④ 校准脚本：一次检索缓存 → 离线扫权重 → 选推荐值
        ↓
⑤ 推荐权重写入默认配置 + 三方对比留档 + 验收
```

**User Story 映射**：① + ② + ③ 交付 US1（P1，权重可配置且生效）；④ 交付 US2（P2，校准出推荐值）；⑤ 交付 US3（P3，三方对比证据）。

**MVP 边界**：① + ② + ③ 完成后，运维者已获得调节两路配比的手段，可独立交付。此时默认仍是等权（行为不变），推荐值待 ④ 给出。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| **权重与路径错配**（本 feature 最危险，且不报错） | 入参改命名映射（Decision 2）+ SC-012 守卫测试：交换传入顺序，输出必须逐条不变 |
| 改接口打断既有测试 | 影响面已核实仅 9 个用例 + 1 处 docstring；`test_fusion_rrf.py` 的改动须逐条说明理由，不得靠改断言蒙过 |
| 未配置权重时行为漂移 | SC-006 要求逐条完全一致。等权时新公式 `1.0/(k+rank)` 与旧式数学等价，有测试固定 |
| 校准被网关抖动打断 | Decision 5 的缓存重放把 API 调用降到 48 次且只在第一步；后续扫描纯离线，可反复重跑 |
| 校准结果过拟合 42 条金标 | 步长不细于 0.25（research Decision 6）；中文金标用作不倒退验证而非调优目标；结论明确标注绑定当前语料 |
| 有人日后把「动态归一化」优化进来 | Decision 4 说明了为何刻意不做；SC-013 测试守住 |
| 最优权重可能就是 sparse 极低 | spec Assumptions 与 research 均已预先承认。届时 SC-001/002 成立、SC-011 可能不成立，校准记录须直说 |

## Complexity Tracking

> 本 feature 的 Constitution Check 全部 PASS，**无违规需要登记**。

唯一有张力的点（`fuse()` 破坏性接口变更）已在 Constitution Check 末节说明：影响面仅 1 处生产调用，且保留兼容层会让 FR-002 要消除的错误路径继续存在，因此变更比兼容更正确。
