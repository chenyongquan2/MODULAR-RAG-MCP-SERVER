# Tasks: 检索基础设施修正

**Input**: Design documents from `specs/004-retrieval-infra-fix/`
**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/)

**Tests**: 本 feature **必须**配套单元测试 —— 宪法原则七（测试支撑变更）是 NON-NEGOTIABLE，不允许例外登记。

**Organization**: 按 user story 分组，每个 story 可独立实现、独立验收、独立交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story（US1 / US2 / US3）
- 每条含确切文件路径

> ⚠️ **所有命令与测试必须用 `.venv/Scripts/python.exe`**。全局 Python 的 protobuf 是 5.29.3，`import chromadb` 会失败。

---

## Phase 1: Setup

**Purpose**: 建立配置与目录骨架

- [x] T001 在 `src/core/settings.py` 的 `VectorStoreSettings` 增加 `bm25_index_format_version: int = 2` 字段，并在 `load_settings()` 的校验路径中确保其为正整数（宪法原则二、三）
- [x] T002 [P] 在 `config/settings.yaml` 的 `vector_store` 段增加 `bm25_index_format_version: 2`，附中文注释说明「不匹配时硬失败、不静默降级」的理由
- [x] T003 [P] 创建 `src/core/text/__init__.py` 与空的 `src/core/text/tokenizer.py` 骨架（模块级 docstring 说明：本模块是查询端与索引端**唯一**的切分实现，禁止在别处复制）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有 user story 都依赖的底层能力

**⚠️ CRITICAL**: 本阶段完成前，任何 user story 不能开工

- [x] T004 在 `src/libs/vector_store/base_vector_store.py` 增加抽象方法 `iter_records(include_vectors: bool = False, batch_size: int = 1000) -> Iterator[Dict[str, Any]]`，含完整 Google 风格 docstring 与类型注解（见 [data-model.md § 6](./data-model.md)）
- [x] T005 在 `src/libs/vector_store/chroma_store.py` 实现 `iter_records`，按 `batch_size` 分批拉取避免一次性物化全部向量；`include_vectors=False` 时不请求 embeddings
- [x] T006 在 `tests/unit/test_vector_store_contract.py` 增加 `iter_records` 的契约测试：分批边界、`include_vectors` 两种取值的返回字段、空集合行为
- [x] T007 在 `tests/unit/test_vector_store_contract.py` 增加断言：`scripts/` 下不得出现 `import chromadb`（宪法原则一的可执行守卫，防止后续 task 图省事直接调 chromadb）

**Checkpoint**: 向量库抽象具备全量枚举能力，迁移与重建脚本可以在不碰 chromadb 的前提下开工

---

## Phase 3: User Story 1 - 混合检索真正生效 (Priority: P1) 🎯 MVP

**Goal**: 修复 D1（标识体系不一致）与 D2（集合隔离口径不一致），让两路检索作用于同一批 chunk、标识一致、结果融合真正发生。

**Independent Test**: 对英文语料发起查询，关键词路径返回非空结果且其标识能在向量库中取回；两路结果的标识交集 > 0（当前恒为 0）。**本阶段完成即可独立交付价值** —— 英文语料（31,387 条）的混合检索从「名义存在」变为「真实生效」，中文暂不受益。

### 集合迁移

- [x] T008 [US1] 新建 `scripts/migrate_collections.py`：经 `VectorStoreFactory` 构造源/目标两个 store 实例（靠不同的 `collection_name`），用 `iter_records(include_vectors=True)` 读、`upsert` 写；支持 `--dry-run`；**复制语义，不删源数据**（FR-006）
- [x] T009 [US1] 在 `scripts/migrate_collections.py` 中实现可疑数据识别并单独列出，**不自动删除**（FR-007）。判据修正：实测表明 10 条 temp 残留**并非** `metadata.collection` 缺失（它们都标着 `default`），因此判据应为「源路径指向临时目录」。同时报告 `metadata.collection` 缺失/为空的记录（当前为 0，但作为防御性检查保留）
- [x] T010 [P] [US1] 新建 `tests/unit/test_migrate_collections.py`：验证迁移幂等（重复执行不产生重复记录）、源集合保持完整、向量随行未重新生成、无归属记录被正确隔离
- [x] T011 [US1] 执行迁移：`.venv/Scripts/python.exe scripts/migrate_collections.py --dry-run` 核对计划，确认后实跑。**实测的源集合 `default` 内含标记分布**：`mt5_docs_english` 31,387 / `mt5_docs_chinese` 21,193 / `finpoints_handbook` 162（同名物理集合已存在同样 162 条，迁移应幂等无副作用）/ `default` 15（含 10 条 temp 残留，留在原地不迁走）

### `--collection` 语义修正

- [x] T012 [US1] 修改 `scripts/evaluate.py:180`：`--collection` 从构造 `filters={"collection": ...}` 改为在构造检索器**之前**覆盖 `settings.vector_store.collection_name`（[research.md](./research.md) Decision 6）
- [x] T013 [P] [US1] 修改 `scripts/query.py:76-78`：同 T012
- [x] T014 [P] [US1] 在 `tests/unit/` 增加测试：指定 `--collection` 后两路检索的范围都随之切换，且返回结果 100% 属于该集合（SC-004）

### 索引重建（沿用现有 ASCII 切分）

- [x] T015 [US1] 按 [contracts/bm25_index.schema.md](./contracts/bm25_index.schema.md) 改造 `src/ingestion/storage/bm25_indexer.py` 的 `save()` / `load()`：标识字典化（`chunk_ids` 表 + 倒排项存 `[下标, tf]`）、去掉倒排项内冗余的 `doc_length`、`tf` 存整数、写入走临时文件 + `os.replace` 原子替换（FR-003 / FR-014）
- [x] T016 [US1] 在 `bm25_indexer.load()` 增加 `_format_version` 严格校验：缺失或不等于 2 时抛 `ValueError` 并提示运行重建脚本。**禁止静默降级或自动重建**（宪法原则三；理由见契约文件）
- [x] T017 [P] [US1] 更新 `tests/unit/test_bm25_indexer_roundtrip.py`：适配新格式的往返断言，并新增版本不匹配必须抛 `ValueError` 的用例
- [x] T018 [US1] 新建 `scripts/rebuild_bm25_index.py`：经 `iter_records(include_vectors=False)` 读取 → 构造 `Chunk` → 复用 `SparseEncoder.encode()` → 按 `metadata.collection` 分组 → `BM25Indexer.build()` + `save()`。支持 `--collection` 与 `--inspect-only`（[research.md](./research.md) Decision 1）
- [x] T019 [US1] 在 `scripts/rebuild_bm25_index.py` 输出统计报告（FR-013）：每集合的词条数、覆盖 chunk 数、含中文词条占比、跳过条目数、**标识回查向量库的命中率**（后者是 FR-001 的可执行判据）
- [x] T020 [P] [US1] 新建 `tests/unit/test_rebuild_bm25_index.py`：验证重建后索引中的标识与向量库完全一致、正文为空的记录被跳过并计入报告、中断不破坏既有索引
- [x] T021 [US1] 执行重建（两个集合），核对报告中标识命中率为 **100%**（当前 0/200）

**Checkpoint**: 英文语料混合检索真实生效。此时中文仍失效（切分未改），这是预期的。

---

## Phase 4: User Story 2 - 中文内容能被关键词检索命中 (Priority: P2)

**Goal**: 修复 D3 —— CJK 字符能进入索引并被中文查询命中，且查询端与索引端切分口径严格一致。

**Independent Test**: 中文语料索引中含汉字词条占比 > 50%（当前 0%）；用某段正文中真实出现的中文短语作查询，能命中该正文所在 chunk。

### 共享切分实现

- [x] T022 [US2] 在 `src/core/text/tokenizer.py` 实现切分函数：按字符类别切分 CJK 段与非 CJK 段；CJK 段长度 ≥ 2 取相邻二字滑窗，长度 = 1 时该单字直接成词；非 CJK 段沿用 `\b[a-z0-9]+\b` + 小写化 + 停用词过滤（[data-model.md § 1](./data-model.md)）
- [x] T023 [US2] 在 `src/core/text/tokenizer.py` 落实约束差异：长度约束与停用词过滤**只作用于非 CJK 词条**，CJK 词条豁免（否则 T022 产出的单字词条会被立即过滤，规则自相矛盾）
- [x] T024 [P] [US2] 新建 `tests/unit/test_tokenizer.py`：中文纯文本、中英混排、单字段落、标点分隔、空串等切分用例
- [x] T025 [US2] 在 `tests/unit/test_tokenizer.py` 增加**两端口径一致性往返测试**：取一段正文，分别走索引端与查询端路径，断言产出的词条序列逐元素相等。这是本 feature 的核心不变量 —— 违反它的失败是静默的（不报错，只是永远召回为空）

### 两端接入

- [x] T026 [US2] 修改 `src/ingestion/embedding/sparse_encoder.py:128`：删除本地 ASCII-only 正则，改调 `src/core/text/tokenizer.py`
- [x] T027 [US2] 修改 `src/core/query_engine/query_processor.py:145`：删除本地 ASCII-only 正则，改调同一份 tokenizer
- [x] T028 [P] [US2] 更新 `tests/unit/test_sparse_encoder.py` 与 `tests/unit/test_query_processor.py`：适配新切分行为；确认既有 ASCII 术语匹配能力未被削弱（FR-010 / US2 验收场景 4）
- [x] T029 [US2] 再次执行重建（两个集合），核对中文集合的含汉字词条占比 **> 50%**（SC-003）、索引体积在 **约 17 MB 量级**（若接近 156 MB 说明 T015 的标识字典化未生效）、启动耗时不超过修复前的 2 倍（SC-011）

**Checkpoint**: 中英文语料的混合检索均真实生效。

---

## Phase 5: User Story 3 - 评估结论可信且可追溯 (Priority: P3)

**Goal**: 让历史与当前的评估数字都能被正确解读，并产出修复前后的对比证据。

**Independent Test**: 任一历史基线都能看出其真实检索模式与语料有效性；能生成「纯向量 vs 混合」的逐指标对比。

> ✅ **T030 的时序枷锁已解除**（2026-08-09 实施期修正）。原判断是「修复前状态一旦被重建覆盖就永久不可复现」，这个前提**是错的** —— 那个状态就是 `data/db/bm25/*.json` 四个文件，复制一份即可永久保留。已备份至 `data/db/bm25_v1_prefix_backup/`（md5 逐一校验一致），随时可还原重跑基准。
>
> 因此 T030 可以在任何时候补跑，不再阻塞 T021。

- [x] T030 [US3] **已完成（改用另一条路径达成）**。原计划是「重建前留存 v1 索引状态下的纯向量参照」，但 `text-embedding-3-small` 永久下架、全量重嵌后旧 1536 维向量不可再查，那条路径已失效。改为**在新向量空间内直接做 dense-only vs hybrid 对照**：把 BM25 索引临时移开让 sparse 空载，跑一轮；恢复索引再跑一轮。两轮语料、向量空间、金标完全相同，对照更干净。结果见 [acceptance.md § 四](./acceptance.md)。v1 索引备份仍保留在 `data/db/bm25_v1_prefix_backup/`（已无对应向量，仅作归档）
- [x] T031 [P] [US3] 修正两套金标的 `source_corpus_collection` 字段：`tests/fixtures/golden_test_set_zh.json` 与 `golden_test_set_en.json` 现均写 `default`，与实际引用内容不符（FR-012）
- [x] T032 [US3] 在 `src/observability/evaluation/baseline_manager.py` 的基线记录增加 `retrieval_mode`（`dense_only` / `hybrid`）与 `corpus_validity`（`valid` / `mismatched`）两个可选字段；写入沿用既有 `_write_store_atomic()`；**不修改任何既有指标数字**（FR-011）
- [x] T033 [P] [US3] 更新 `tests/unit/test_baseline_manager.py`：新字段的读写、旧记录缺失该字段时视为「未标注」的向后兼容行为
- [x] T034 [US3] 把 `logs/baselines.json` 中 2026-04-28 的既有记录标注为 `corpus_validity: mismatched` —— 实测表明当时 MT5 语料尚未 ingest，该次评估检索回的是 `company_policy.md` 与临时文件，**不是**「纯向量参照」（[research.md](./research.md) Decision 7）
- [x] T035 [US3] **已完成（中英文两套金标 8 项指标全部产出）**。中文 `run_id=0798cc98`（6/8 过阈值）、英文 `run_id=80a82405`（5/8 过阈值，42 条）。**两个语种独立复现同一分裂：RAGAS 4 项全过，custom 召回类全不过** —— `custom__recall` 0.30/0.42 vs `ragas__context_recall` 0.83/0.83，说明前者量的是「有没有复现回填脚本的 top-5 选择」而非「够不够回答问题」。详见 [acceptance.md § 三](./acceptance.md)
- [x] T036 [US3] **已完成**（混合口径，见 [acceptance.md § 五](./acceptance.md)）：simple hit 63.6%/recall 40.0%、multi_context 77.8%/68.9%、reasoning 45.5%/25.5%。**结论与设计假设相反：难的是 reasoning 而非多跳** —— multi_context 的召回反而显著高于 simple（68.9% vs 40.0%）。对「要不要做检索规划器」的启示是目标该对准推理类，而非笼统的多跳
- [x] T037 [US3] **已完成**。旧基线 `collection=default` 标注为 `dense_only` / `mismatched`（T034）。当前基线改为英文那份（`run_id=80a82405`，42 条）—— 基线按 collection 键存，两套金标跑在同一 collection 上，槽位只能容纳一份；选样本量大的更利于回归检测（中文集单条 case 即 16.7% 摆动）。中文那份（`0798cc98`）已降级到 `history`，未丢失

**Checkpoint**: 评估数字可解读、可对比、可追溯。

---

## Phase 6: Polish & Cross-Cutting

- [x] T038 [P] 全量跑 `.venv/Scripts/python.exe -m pytest tests/unit -v`，确认 80 个测试文件全通过（宪法原则七）
- [x] T039 [P] 更新 `docs/learning/agentic-retrieval-boundary.md` 的 § 6.3：把四个缺陷标记为已修复，补上修复后的实测数字
- [x] T040 [P] 更新 `CLAUDE.md` 中与索引格式、`--collection` 语义相关的描述
- [x] T041 处置 10 条无归属的 temp 残留 chunk：清单已列出并交用户确认。2026-08-09 用户先决定保留；**2026-08-10 用户改为删除，已执行**。删除前核对无金标引用（三份金标引用数均为 0），删除后**重建了两个集合的 BM25 索引** —— 否则索引会引用向量库里已不存在的 chunk，等于重新制造 D1 那类不一致。核验：向量库 52,757 → 52,747，两侧 temp 残留均为 0，标识回查保持 200/200。FR-007 的「人工确认」环节闭环
- [x] T042 复核 SC-001～SC-011 逐条达成情况，未达成项写明原因，结论记入本 feature 的验收记录

---

## Dependencies

```
Phase 1 (T001-T003)  Setup
        ↓
Phase 2 (T004-T007)  Foundational —— 阻塞点，必须先完成
        ↓
Phase 3 (T008-T021)  US1 混合检索真正生效  🎯 MVP
        │  ⚠ T030 必须插在 T014 之后、T021 之前
        ↓
Phase 4 (T022-T029)  US2 中文可被关键词命中
        ↓
Phase 5 (T031-T037)  US3 评估可信（T030 除外，见上）
        ↓
Phase 6 (T038-T042)  Polish
```

**Story 间依赖**：US2 依赖 US1 的索引格式改造（T015-T017）与重建脚本（T018）；US3 的 T030 反向嵌入 US1 中间。三者不是完全独立 —— 这是缺陷修复类 feature 的固有性质（共享同一套索引与重建路径），已在各 Checkpoint 标明可独立验收的边界。

---

## Parallel Opportunities

| 组 | 可并行任务 | 前提 |
|---|---|---|
| Setup | T002 ‖ T003 | T001 完成 |
| US1 测试 | T010 ‖ T014 ‖ T017 ‖ T020 | 各自对应的实现任务完成 |
| US1 CLI | T012 ‖ T013 | 无 |
| US2 测试 | T024 ‖ T028 | T022-T023 完成 |
| US3 | T031 ‖ T033 | 无 |
| Polish | T038 ‖ T039 ‖ T040 | Phase 5 完成 |

---

## Implementation Strategy

### MVP 范围

**Phase 1 + 2 + 3（T001-T021）即为 MVP** —— 交付后英文语料（31,387 条、42 条金标）的混合检索真实生效，D1 与 D2 消解。中文暂不受益，但这是可独立交付、可独立验收的完整增量。

### 增量交付

1. Setup + Foundational → 向量库具备全量枚举能力
2. \+ US1 → **混合检索从名义存在变为真实生效**（MVP，SC-001/SC-002/SC-004）
3. \+ US2 → 中文语料纳入关键词检索（SC-003/SC-011）
4. \+ US3 → 评估可信、对比数据到手（SC-006/SC-008/SC-009）
5. Polish → 文档对齐 + 残留数据处置

### 风险提示

- ~~**T030 是全局唯一的时序卡点**~~ **已解除**。原判断认为「T021 一旦执行，纯向量参照永久不可复现」，但那个状态就是四个 JSON 文件 —— 已备份至 `data/db/bm25_v1_prefix_backup/`（md5 校验一致）。**教训：在给某个任务加时序枷锁之前，先问一句「这个状态到底能不能被复制」** —— 本例中一条 `cp` 就解决了，而枷锁会逼着人在外部服务不可用时硬跑
- **T025 是 FR-009 的唯一闸门**。查询端与索引端切分口径漂移的失败是静默的：不报错、不告警，只是永远召回为空。D3 正是这样潜伏至今
- **T016 不允许打折**。版本不匹配必须硬失败 —— 若在这里留静默降级路径，等于在刚修好的地方重新埋雷
- **T015 是 T029 体积达标的前提**。标识字典化没做对，中文 bigram 会把索引撑到 156 MB，SC-011 直接失败
- **T011 与 T041 涉及数据操作**。迁移为复制式不删源数据；10 条残留的删除必须人工确认，不得自动执行

---

## Notes

- `[P]` = 不同文件、无未完成依赖
- 提交信息按宪法 § X 引用 task ID（`refs T-0XX`）
- 每个任务或逻辑组完成后即提交；**触及 Feature-001 生产路径的改动单独提交、单独验证**（沿用 Feature-003 的 T004 纪律）
- 任一 Checkpoint 均可停下独立验收
- 所有命令与测试用 `.venv/Scripts/python.exe`
