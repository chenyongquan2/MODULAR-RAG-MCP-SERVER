# Tasks: 带权重的结果融合

**Input**: Design documents from `specs/005-weighted-fusion/`
**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/)

**Tests**: 本 feature **必须**配套单元测试 —— 宪法原则七（测试支撑变更）是 NON-NEGOTIABLE，不允许例外登记。

**Organization**: 按 user story 分组，每个 story 可独立实现、独立验收、独立交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story（US1 / US2 / US3）
- 每条含确切文件路径

> ⚠️ **所有命令与测试必须用 `.venv/Scripts/python.exe`**。全局 Python 的 protobuf 是 5.29.3，`import chromadb` 会失败。

---

## Phase 1: Setup（配置字段）

**Purpose**: 让权重与平滑参数可配置，这是后续一切的前提

- [x] T001 在 `src/core/settings.py` 的 `RetrievalSettings` 增加 `rrf_k: int = 60` 与 `fusion_weights: Dict[str, float] = field(default_factory=lambda: {"dense": 1.0, "sparse": 1.0})`，附中文注释说明「只有相对比例有意义」（[data-model.md § 2](./data-model.md)）
- [x] T002 在 `src/core/settings.py` 的 `validate_settings()` 增加校验（宪法原则三，启动期硬失败）：`rrf_k` 必须为正整数（含挡掉 `bool`）；每个权重必须是非负数值；**权重不得全部为 0**（否则所有得分归零、排序退化为字典序，且不会有任何报错）
- [x] T003 [P] 在 `config/settings.yaml` 的 `retrieval` 段增加 `rrf_k: 60` 与 `fusion_weights: {dense: 1.0, sparse: 1.0}`，注释说明默认值刻意保持当前硬编码值以确保升级后行为不变
- [x] T004 [P] 新建 `tests/unit/test_settings_retrieval.py`：新字段默认值、非法值逐类被拒（负数 / 全零 / 非数值 / `rrf_k<=0` / `rrf_k=True`）、**向后兼容回归**（`settings.yaml` 不含新字段时仍能加载并通过校验）

**Checkpoint**: 配置可读、非法值在启动期即被拒绝

---

## Phase 2: Foundational（融合契约落地）

**Purpose**: 融合本身的能力与三条不变量。所有 user story 都依赖它

**⚠️ CRITICAL**: 本阶段完成前，任何 user story 不能开工

- [x] T005 按 [contracts/fusion.contract.md](./contracts/fusion.contract.md) 改造 `src/core/query_engine/fusion.py`：`__init__` 接受 `k: int = 60` 与 `weights: Optional[Mapping[str, float]] = None`；`fuse()` 入参从 `List[List[RetrievalResult]]` 改为 `Mapping[str, Sequence[RetrievalResult]]`；得分公式改为 `weight[r] / (k + rank)`；权重按**键**查找，缺失的键缺省 `1.0`
- [x] T006 删除 `src/core/query_engine/fusion.py:87` 那条**把两路顺序写反**的注释（它写 `[sparse_result, dense_result]`，而 `hybrid_search.py:204` 传的是相反顺序）。改接口后该注释既过时又有害 —— 它正是「按顺序对应会出错」的现成例证，理由留在 contract 与 data-model 里，代码里不留错误注释
- [x] T007 更新 `tests/unit/test_fusion_rrf.py` 的 9 个既有用例适配新入参形态。**每一处断言改动都必须在用例 docstring 里写明理由** —— 沿用 Feature-003 T017 与 Feature-004 T028 的纪律，防止靠改断言蒙过
- [x] T008 在 `tests/unit/test_fusion_rrf.py` 增加**顺序无关守卫**（SC-012 / FR-002）：`fuse({"dense": D, "sparse": S})` 与 `fuse({"sparse": S, "dense": D})` 输出逐条相等。这是本 feature 最危险失败模式的唯一闸门 —— 权重与路径错配**不报错**，只是效果悄悄变差
- [x] T009 在 `tests/unit/test_fusion_rrf.py` 增加**空路无副作用守卫**（SC-013 / FR-004）：`fuse({"dense": D, "sparse": []})` 的排序与 `fuse({"dense": D})` 一致。同时守住 [research.md](./research.md) Decision 4 的「刻意不做动态归一化」不被后人当作优化加回来
- [x] T010 在 `tests/unit/test_fusion_rrf.py` 增加**等权兼容守卫**（SC-006 / FR-003）：权重全相等时输出排序与本 feature 之前逐条一致（等权时新公式是旧公式的常数倍，排序不变）
- [x] T011 [P] 在 `tests/unit/test_fusion_rrf.py` 增加权重语义用例：某路权重为 0 时该路不影响任何结果（SC-005）；权重比例相同的两组配置（如 `1:0.5` 与 `2:1`）输出完全相同（[data-model.md § 2](./data-model.md) 的「只有相对比例有意义」）

**Checkpoint**: 融合支持权重，三条不变量由测试固定

---

## Phase 3: User Story 1 - 融合权重可配置且真实生效 (Priority: P1) 🎯 MVP

**Goal**: 让运维者能通过配置调节两路配比，并能在追踪记录里看到本次生效的权重。

**Independent Test**: 修改权重配置并重启，同一查询的融合排序发生可观测变化；关键词路径权重设为 0 时结果与纯语义检索一致。**本阶段完成即可独立交付** —— 运维者获得调节手段，默认仍是等权（行为不变）。

- [x] T012 [US1] 修改 `src/core/query_engine/hybrid_search.py:91`：`Fusion` 改为从 `settings` 构造（传 `settings.retrieval.rrf_k` 与 `settings.retrieval.fusion_weights`），不再无参构造。这同时修掉一处既有的配置驱动违规（`DEFAULT_K = 60` 硬编码、构造时不读任何配置）
- [x] T013 [US1] 修改 `src/core/query_engine/hybrid_search.py:204`：改为按命名映射调用 `fuse({"dense": dense_results, "sparse": sparse_results}, top_k=...)`
- [x] T014 [US1] 在 `src/core/query_engine/hybrid_search.py` 的 `finish_stage("fusion", ...)` payload 中加入本次生效的权重（FR-008 / SC-008），与既有的 `input_dense` / `input_sparse` / `output_count` 并列
- [x] T015 [P] [US1] 新建 `tests/unit/test_hybrid_search_fusion_wiring.py`：验证 `Fusion` 由 settings 构造（改配置 `rrf_k` / 权重能传达到融合器）、`fuse` 收到的是命名映射而非位置列表、fusion 打点 payload 含生效权重
- [x] T016 [US1] 端到端手工核验：`--collection default_text-embedding-v4` 下对同一查询分别跑 `sparse: 1.0` 与 `sparse: 0`，确认前者结果含仅被关键词路径命中的内容、后者与纯语义检索一致（SC-004 / SC-005）

**Checkpoint**: 权重可配置、可观测、可验证。默认等权，行为与之前一致。

---

## Phase 4: User Story 2 - 权重经金标校准并给出推荐值 (Priority: P2)

**Goal**: 用「一次检索、多次离线重放」在英文金标上扫出推荐权重，中文金标用作不倒退验证。

**Independent Test**: 查看校准记录能看到候选范围、判据、各候选得分；第三方按记录重跑得到相同结论。

- [ ] T017 [US2] 新建 `scripts/calibrate_fusion_weights.py` 的 `--build-cache` 路径：对指定金标每条查询执行**一次**两路检索，把两路的**有序**标识列表 + `expected_chunk_ids` + `difficulty` 写入缓存 JSON。缓存须记录 `collection`，重放前校验一致，不匹配即报错（[data-model.md § 5](./data-model.md)）
- [ ] T018 [US2] 实现 `--sweep` 路径：从缓存离线重放融合，固定 `dense=1.0` 扫 `sparse ∈ {0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0}`，对每个候选算 `hit_rate` / `recall` / `MRR` / `nDCG`。**零 API 调用**，可反复重跑（[research.md](./research.md) Decision 5）
- [ ] T019 [US2] 实现选择判据（[research.md](./research.md) Decision 6）：硬约束 `recall ≥ 45.7%`（纯语义水平）→ 满足者中取 `MRR` 最大 → 若无人满足则取 `recall` 最大并标注未达成。判据须在输出中显式打印，不做隐式选择
- [ ] T020 [P] [US2] 新建 `tests/unit/test_calibrate_fusion_weights.py`：缓存重放的确定性（同缓存同权重必得同结果）、判据逻辑的三个分支、缓存 `collection` 不匹配时报错、`sparse=0` 候选等价于纯语义
- [ ] T021 [US2] 执行英文校准：`--build-cache --lang en` 后 `--sweep --lang en`，记录完整扫描曲线与选定值
- [ ] T022 [US2] 执行中文验证：`--build-cache --lang zh` 后 `--sweep --lang zh`。**中文仅 6 条、单条 case 即 16.7% 摆动，不作为调优目标**，只确认选定权重在中文上不倒退（spec Assumptions）
- [ ] T023 [US2] 把推荐权重写入 `config/settings.yaml` 的默认值，并在注释中标注：该值由英文金标校准得出、绑定当前 MT5 语料、换语料需重新校准

**Checkpoint**: 有推荐默认值，且其依据可复现。

---

## Phase 5: User Story 3 - 三方对比证据留档 (Priority: P3)

**Goal**: 产出「纯语义 / 等权混合 / 带权混合」逐指标对比，证明倒退已消除。

**Independent Test**: 存在覆盖中英文、四项指标、三种配置的对比表，且带权混合的 recall 与 hit_rate 不低于纯语义。

- [ ] T024 [US3] 实现 `scripts/calibrate_fusion_weights.py --compare`：从**同一份缓存**重放三种配置（`sparse=0` / `sparse=1.0` / 推荐值），输出四项指标的对比表。同源缓存意味着三者差异纯粹来自权重，不含检索层面的随机波动
- [ ] T025 [US3] 产出英文与中文两份三方对比，写入 `specs/005-weighted-fusion/acceptance.md`（SC-009）
- [ ] T026 [US3] 核验核心目标：带权混合的 `recall` ≥ 45.7%、`hit_rate` ≥ 69.0%（SC-001 / SC-002），`MRR` 不低于等权的 0.502（SC-003）
- [ ] T027 [US3] 核验 SC-011（至少一个语种上带权混合在召回与排序两项同时严格优于任一单路）。**若未达成**，在 acceptance.md 中直说并给出曲线依据 —— spec Assumptions 已预先承认「最优权重可能就是关键词路径权重极低」这一结果，届时 SC-001/002 成立而 SC-011 不成立是可接受的诚实结论，不得粉饰
- [ ] T028 [US3] 把校准记录（候选范围、判据、完整扫描曲线）写入 `acceptance.md`（SC-010），确保第三方按记录可复现

**Checkpoint**: 证据完备，可判定 feature 是否达成目的。

---

## Phase 6: Polish & Cross-Cutting

- [ ] T029 [P] 全量跑 `.venv/Scripts/python.exe -m pytest tests/unit -v`，确认无回归（基线：Feature-004 收尾时 1412 passed / 2 skipped）
- [ ] T030 [P] 更新 `CLAUDE.md`：`retrieval` 段新增配置项说明；补一条「权重是语料相关的，换语料需重新校准」的提示（与既有的「换 Judge 需重新校准阈值」并列）
- [ ] T031 [P] 更新 `docs/learning/agentic-retrieval-boundary.md`：把 § 6.3 中「RRF 无权重」标记为已修复，补修复后的实测数字
- [ ] T032 复核 SC-001～SC-013 逐条达成情况，未达成项写明原因，结论记入 `acceptance.md`

---

## Dependencies

```
Phase 1 (T001-T004)  Setup 配置字段
        ↓  Fusion 需要从配置拿 k 与权重
Phase 2 (T005-T011)  Foundational 融合契约 + 三条不变量守卫
        ↓  HybridSearch 需要按新形态调用
Phase 3 (T012-T016)  US1 权重可配置且生效  🎯 MVP
        ↓  校准需要可运行的带权融合
Phase 4 (T017-T023)  US2 校准出推荐值
        ↓  对比需要推荐值
Phase 5 (T024-T028)  US3 三方对比证据
        ↓
Phase 6 (T029-T032)  Polish
```

**Story 间依赖**：US2 依赖 US1（校准需要带权融合能跑）；US3 依赖 US2（对比需要推荐值）。三者呈链式而非并行 —— 这是「改造→校准→验证」类 feature 的固有形态，已在各 Checkpoint 标明可独立验收的边界。

---

## Parallel Opportunities

| 组 | 可并行任务 | 前提 |
|---|---|---|
| Setup | T003 ‖ T004 | T001–T002 完成 |
| Foundational | T011 与 T008–T010 可并行编写 | T005–T007 完成 |
| US1 | T015 与 T012–T014 可并行编写 | T005 完成 |
| US2 | T020 与 T017–T019 可并行编写 | T005 完成 |
| Polish | T029 ‖ T030 ‖ T031 | Phase 5 完成 |

---

## Implementation Strategy

### MVP 范围

**Phase 1 + 2 + 3（T001–T016）即为 MVP** —— 交付后运维者获得调节两路配比的手段，融合的三条不变量由测试固定，且默认等权保证行为不变。推荐值待 US2 给出，但能力本身已可用、可交付。

### 增量交付

1. Setup + Foundational → 融合支持权重，不变量有守卫
2. \+ US1 → **权重可配置、可观测**（MVP，SC-004/005/006/008/012/013）
3. \+ US2 → 有依据的推荐默认值（SC-010）
4. \+ US3 → 倒退消除的证据（SC-001/002/003/009/011）
5. Polish → 文档对齐 + 逐条复核

### 风险提示

- **T008 是本 feature 最重要的一条测试**。权重与路径错配**不报错**，只是效果悄悄变差；而代码里已经存在一处顺序写反的注释（`fusion.py:87`），证明这种混淆是真实发生过的。这条守卫不可省
- **T009 守的是一条「刻意不做」**。动态归一化不改变任何可观测排序，却让绝对得分随「另一路是否恰好为空」跳变。没有测试的话，后人很容易把它当作优化加回来
- **T007 触及既有测试的断言**。沿用 Feature-003 T017 / Feature-004 T028 的纪律：每处改动必须在 docstring 写明理由，不得靠改断言蒙过
- **T017 是唯一有 API 成本的任务**。之后的扫描与对比全部离线重放。Feature-004 期间反复遭遇网关 503 与超时 —— 把 API 调用集中在一处且只做一遍，是校准能跑完的前提
- **T027 允许「未达成」**。spec 已预先承认最优权重可能就是关键词路径权重极低。届时诚实记录比凑一个好看的结论有价值 —— 「关键词路径在当前语料上贡献有限」本身会直接影响后续是否值得投入查询改写

---

## Notes

- `[P]` = 不同文件、无未完成依赖
- 提交信息按宪法 § X 引用 task ID（`refs T-0XX`）
- 每个任务或逻辑组完成后即提交；**触及既有测试断言的改动单独提交、单独验证**
- 任一 Checkpoint 均可停下独立验收
- 所有命令与测试用 `.venv/Scripts/python.exe`
