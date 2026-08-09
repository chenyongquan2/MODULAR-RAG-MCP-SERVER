# Implementation Plan: 检索基础设施修正

**Branch**: `dev-from-clean-start`（不单开分支，用 `SPECIFY_FEATURE=004-retrieval-infra-fix` 调用 speckit 脚本） | **Date**: 2026-08-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/004-retrieval-infra-fix/spec.md`

## Summary

修复三个已实测确诊的缺陷：关键词索引与向量库的 chunk_id 体系不相交（导致结果融合从未生效、混合检索实际是纯向量检索）、两路检索的集合隔离口径不一致、CJK 字符在整条关键词链路上被丢弃。

技术路径由数据现状锁死：原始文档已删除且向量生成走 API，因此**只能从向量库反向重建关键词索引**。所幸向量库自身持有全部正文（20 MB / 52,919 条）与正确标识，反向重建在数据上完全可行且零 embedding 成本。

一次重建同时消解三个缺陷：重建时用向量库的标识 → 解决 D1；按 `metadata.collection` 分组 → 配合向量侧迁移解决 D2；用新的共享切分逻辑 → 解决 D3。

关键设计决策见 [research.md](./research.md)，其中 **Decision 2（chunk_id 字典化）是中文支持在体积上可行的前提** —— 不做它，索引会从 38 MB 涨到 156 MB。

## Technical Context

**Language/Version**: Python 3.12（`.venv`，protobuf 3.20.3 —— 全局 Python 的 protobuf 5.29.3 会导致 `import chromadb` 失败，所有脚本与测试必须在 `.venv` 下运行）
**Primary Dependencies**: chromadb 1.4.1（向量存储）、既有 `SparseEncoder` / `BM25Indexer`（关键词索引）、ragas 0.1.21（评估，版本为 Feature-001 基线锚定点，禁止升级）
**Storage**: ChromaDB 持久化于 `data/db/chroma`（626 MB）；关键词索引为 `data/db/bm25/<collection>.json`
**Testing**: pytest（`pytest tests/unit -v`），受影响的既有测试见下方 Project Structure
**Target Platform**: Windows 11 本机开发；MCP server 支持 stdio 与 SSE 两种 transport
**Project Type**: 单体 Python 项目（RAG 服务 + CLI 脚本 + Streamlit dashboard）
**Performance Goals**: 重建后索引加载耗时不超过修复前的 2 倍（当前 38 MB / 1.81 s / 67 MB 常驻）；重建过程零新增 embedding 调用
**Constraints**: 不可重新 ingest（原始文档已删除）；迁移必须可回滚（复制而非移动）；查询端与索引端切分口径必须严格一致
**Scale/Scope**: 52,919 条 chunk / 4 个逻辑集合；倒排项 205,469 → 约 1,207,000

## Constitution Check

*GATE: 逐条标记，NON-NEGOTIABLE 条款不允许 Complexity Tracking 豁免。*

### 架构原则

- [x] **一、Provider 无关性** — **PASS**。迁移与重建脚本**不 import chromadb**，全程经 `VectorStoreFactory` + `BaseVectorStore` 抽象操作（详见下方「关键合规设计」）。tokenizer 是共享工具模块而非新的可插拔组件层级，理由见 research.md Decision 4。
- [x] **二、配置驱动** — **PASS**。新增的索引格式版本号有 `settings.yaml` 字段 + `src/core/settings.py` dataclass；集合切换沿用既有的 `vector_store.collection_name`，不新增机制。切分策略为唯一实现，无需配置项（research.md Decision 4）。
- [x] **三、快速失败校验** — **PASS**。索引格式版本不匹配时立即抛 `ValueError` 而非静默降级 —— 这一条至关重要：旧格式索引与新格式共存时若静默回退，会重演「静默失效」这一本 feature 正在修复的失败模式。
- [x] **四、追踪显式化** — **N/A**。本 feature 不新增 pipeline 函数。重建与迁移是离线脚本，不参与查询链路。`query_processor` 的既有签名不变。
- [x] **五、结构化日志(NON-NEGOTIABLE)** — **PASS**。`src/` 内零 `print()`；两个新脚本位于 `scripts/`，按宪法「CLI 工具的人类可读输出应写在 `scripts/`」输出人类可读进度与统计报告。
- [x] **六、类型安全** — **PASS**。新增模块全部 public 函数带完整类型注解；不引入新的跨模块领域类型（复用既有 `Chunk` / `ChunkRecord`）。
- [x] **七、测试支撑变更(NON-NEGOTIABLE)** — **PASS**。每个实现任务配套 `tests/unit/` 测试，清单见下方 Project Structure。切分口径一致性有专门的往返测试（索引端切出的词条必须能被查询端切分命中）。

### SDD 纪律

- [x] **八、Spec 先行(NON-NEGOTIABLE)** — **PASS**。`specs/004-retrieval-infra-fix/spec.md` 已存在并通过 16 项质量校验。
- [x] **九、Plan 先于 Tasks(NON-NEGOTIABLE)** — **PASS**。`tasks.md` 将由本 plan 推导。
- [x] **十、可追溯性(NON-NEGOTIABLE)** — **PASS**。实施期 commit 引用 `refs T-XXX`。

### 关键合规设计：迁移脚本如何不违反原则一

宪法原则一明确把 `scripts/` 列为业务代码，禁止 import 具体 provider 实现。但迁移需要**读出向量**，而现有 `BaseVectorStore` 抽象只有 `upsert` / `query` / `get_by_ids`，`get_by_ids` 不返回向量。

**解法**：向 `BaseVectorStore` 增加一个 provider 无关的抽象方法：

```python
def iter_records(self, include_vectors: bool = False,
                 batch_size: int = 1000) -> Iterator[Dict[str, Any]]
```

「枚举一个集合中的全部记录」是任何向量库都具备的通用能力，不是 Chroma 特有的，因此属于**扩展既有抽象**而非新增组件层级 —— 按宪法《架构稳定性》不触发 MAJOR 修宪。

它同时服务两个脚本：迁移需要 `include_vectors=True`，重建只需 `include_vectors=False`。

集合定位则通过既有机制完成：`ChromaStore` 在 `__init__`（`chroma_store.py:79`）绑定 `settings.vector_store.collection_name`，因此迁移脚本构造**两个 store 实例**（源集合、目标集合各一）即可，无需为 `upsert` 增加 collection 参数。

**结论**：两个脚本全程只依赖 `VectorStoreFactory.create()` 与 `BaseVectorStore` 接口，`grep "import chromadb" scripts/` 应为零。**无 Complexity Tracking 登记项。**

## Project Structure

### Documentation (this feature)

```text
specs/004-retrieval-infra-fix/
├── spec.md              # ✅ 已完成
├── plan.md              # ✅ 本文件
├── research.md          # ✅ 已完成（8 项决策，含 2 处经实测推翻的修正）
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/
│   └── bm25_index.schema.md   # 索引文件格式契约
├── checklists/
│   └── requirements.md  # ✅ 16 项全通过
└── tasks.md             # Phase 2 输出（由 /speckit.tasks 生成，非本命令）
```

### Source Code (repository root)

```text
src/
├── core/
│   ├── text/                        # 【新增目录】
│   │   ├── __init__.py
│   │   └── tokenizer.py             # 【新增】两端共享的切分实现（FR-009 的载体）
│   ├── query_engine/
│   │   └── query_processor.py       # 【改】:145 的 ASCII-only 正则 → 改调共享 tokenizer
│   └── settings.py                  # 【改】索引格式版本字段；默认集合改为英文语料
├── ingestion/
│   ├── embedding/
│   │   └── sparse_encoder.py        # 【改】:128 的 ASCII-only 正则 → 改调共享 tokenizer
│   └── storage/
│       └── bm25_indexer.py          # 【改】索引格式改 ID 字典化 + 版本校验（Decision 2）
├── libs/vector_store/
│   ├── base_vector_store.py         # 【改】新增 iter_records 抽象方法
│   └── chroma_store.py              # 【改】实现 iter_records
└── observability/evaluation/
    └── baseline_manager.py          # 【改】基线追加检索模式/语料有效性标注（Decision 7）

scripts/
├── migrate_collections.py           # 【新增】复制式集合迁移（Decision 5）
├── rebuild_bm25_index.py            # 【新增】从向量库反向重建（Decision 1）
├── evaluate.py                      # 【改】:180 --collection 改为覆盖配置真源（Decision 6）
└── query.py                         # 【改】:76-78 同上

tests/unit/
├── test_tokenizer.py                # 【新增】切分规则 + 两端口径一致性往返测试
├── test_migrate_collections.py      # 【新增】迁移幂等性 + 复制不删原数据
├── test_rebuild_bm25_index.py       # 【新增】重建后 ID 与向量库一致 + 统计报告正确
├── test_bm25_indexer_roundtrip.py   # 【改】索引格式变更影响既有断言
├── test_query_processor.py          # 【改】切分逻辑变更
├── test_sparse_encoder.py           # 【改】切分逻辑变更
├── test_vector_store_contract.py    # 【改】新增抽象方法进入契约测试
└── test_baseline_manager.py         # 【改】新增标注字段
```

**Structure Decision**: 单体项目结构，沿用既有布局。唯一的新增目录是 `src/core/text/` —— 放在 `src/core/` 而非 `src/libs/` 是刻意的：`src/libs/<component>/` 是 provider 实现的位置（base + factory 模式），把非可插拔的工具模块放进去会误导后来者以为它是可替换组件（research.md Decision 4）。

## 实施顺序与依赖

顺序由 research.md Decision 8 确定，其中**第 ① 步不可后移** —— 修复前的系统状态一旦被重建覆盖就永久不可复现：

```
① 集合迁移（复制式）+ --collection 语义修正
        ↓
② 补跑基准评估（当前语料 + 当前失效的关键词路径 = 真正的「纯向量参照」）
   ⚠ 有 API 成本；这是最后一次能测到「修复前」的机会
        ↓
③ 反向重建索引（沿用现有 ASCII 切分）→ 标识对齐，英文语料混合检索生效
        ↓
④ 共享 tokenizer + 索引格式改造 → 再次重建 → 中文生效
        ↓
⑤ 重跑评估 → 与 ② 对比得 SC-008 → 按难度分组得 SC-009
        ↓
⑥ 基线标注 + 旧基线标记为「语料不匹配」
```

**为什么迁移必须在基准评估之前**：要在 `mt5_docs_english` 上跑评估，该物理集合必须先存在，且 `--collection` 的语义修正必须已生效 —— 否则命令根本跑不通。迁移改变的是数据布局而非检索逻辑，不影响「纯向量」这一性质，因此不破坏参照的有效性。

**为什么重建做两次**：③ 用现有 ASCII 切分重建，单独验证「标识对齐 → 结果融合生效」；④ 换上新切分再重建，单独验证「中文进索引」。两次分开做才能把效果归因到正确的原因上；若一次做完，无法分辨是哪个改动带来的变化。重建无 embedding 成本（仅读取 20 MB 正文 + 切分 + 建索引），多做一次代价可忽略。

**User Story 映射**：① + ③ 交付 US1（P1，混合检索真正生效）；④ 交付 US2（P2，中文可被关键词命中）；② + ⑤ + ⑥ 交付 US3（P3，评估可信）。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 重建中断留下半成品索引，覆盖掉当前可用索引 | 先写临时文件，完整后 `os.replace` 原子替换（沿用 `baseline_manager._write_store_atomic` 的既有模式）（FR-003） |
| 两端切分口径再次漂移 | 单一实现 + 往返测试：取一段正文中真实出现的短语作查询，必须能命中该正文所在 chunk |
| 旧格式索引被静默加载 | 索引带格式版本号，不匹配立即抛 `ValueError`（宪法原则三）。**绝不静默降级** —— 静默失效正是本 feature 在修的病 |
| 迁移误删数据 | 复制式，原 `default` 集合保持完整；10 条无归属的临时文件残留单独列出，删除前需人工确认（FR-007） |
| 索引体积失控 | Decision 2 的 ID 字典化把 156 MB 压到约 17 MB；SC-011 用启动耗时守住这条线 |
| 改动触及 Feature-001 生产路径 | 沿用 Feature-003 的 T004 纪律：触及既有生产路径的改动**单独提交、单独验证**，不与新功能混在一个 commit |

## Complexity Tracking

> 本 feature 的 Constitution Check 全部 PASS，**无违规需要登记**。

唯一曾有张力的点（迁移脚本是否必须 import chromadb）已通过扩展 `BaseVectorStore` 的 `iter_records` 抽象方法消解，见上方「关键合规设计」。
