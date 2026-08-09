# Phase 1 Data Model: 检索基础设施修正

**Feature**: 004-retrieval-infra-fix
**Date**: 2026-08-09
**Input**: [spec.md](./spec.md) · [research.md](./research.md)

本文定义本 feature 涉及的数据实体、状态迁移与校验规则。索引文件的完整格式契约另见 [contracts/bm25_index.schema.md](./contracts/bm25_index.schema.md)。

---

## 1. 词条（Token）

切分的产物，是关键词索引的基本单元。**本 feature 不为它引入新的 Python 类型** —— 它在代码中就是 `str`，此处定义的是它的**生成规则**，因为规则的一致性正是 FR-009 的全部内容。

### 生成规则

输入文本先按字符类别切成交替的 CJK 段与非 CJK 段，两类分别处理：

| 段类型 | 条件 | 产出 |
|---|---|---|
| CJK 段 | 长度 ≥ 2 | 全部相邻二字组合（滑窗），如「预约技师」→ `预约`、`约技`、`技师` |
| CJK 段 | 长度 = 1 | 该单字本身作为一个词条 |
| 非 CJK 段 | — | 沿用既有 `\b[a-z0-9]+\b` 提取 + 小写化 + 停用词过滤 |

### 校验规则

| 规则 | 说明 |
|---|---|
| 长度约束只作用于非 CJK 词条 | 既有 `min_term_length = 2` 会吃掉 CJK 单字词条，与「单字段落成词」规则自相矛盾，故 CJK 词条豁免长度检查 |
| 停用词只作用于非 CJK 词条 | 既有停用词表是英文表，对 CJK 词条不适用 |
| 大小写归一只作用于非 CJK 词条 | CJK 无大小写概念 |
| **两端必须产出完全相同的词条序列** | 同一段文本经查询端与索引端切分，结果必须逐元素相等 —— 这是索引可被命中的充要条件 |

> **最后一条是本 feature 的核心不变量。** 它之所以需要被显式写成校验规则，是因为违反它的失败是**静默的**：不报错、不抛异常，只是永远召回为空。D3 正是这样潜伏至今的。

### 反例（当前实现，两端各一份且都丢弃 CJK）

```python
# src/core/query_engine/query_processor.py:145
normalized = re.sub(r"[^a-z0-9\s-]", " ", normalized)

# src/ingestion/embedding/sparse_encoder.py:128
tokens = re.findall(r'\b[a-z0-9]+\b', text)
```

---

## 2. 关键词索引（BM25 Index）

### 结构变更概览

| | 当前 | 目标 |
|---|---|---|
| chunk 引用方式 | 每个倒排项内嵌完整 chunk_id 字符串（平均 91 字符） | 整数下标，指向顶层 chunk_id 表 |
| `doc_length` | 每个倒排项重复存一份 | 仅顶层 `doc_lengths` 保留 |
| 倒排项形态 | `{"chunk_id": str, "tf": float, "doc_length": int}` | `[chunk_index: int, tf: int]` |
| 格式版本号 | 无 | 有，加载时严格校验 |
| 单项体积 | 136 B | 10 B |

### 关键字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `_format_version` | int | 索引格式版本。加载时不匹配立即抛 `ValueError`，**禁止静默降级** |
| `chunk_ids` | `list[str]` | chunk 标识表，下标即倒排项中引用的整数。**顺序即身份，不可重排** |
| `doc_lengths` | `list[int]` | 与 `chunk_ids` 同下标对齐的文档长度 |
| `index` | `dict[str, {idf, postings}]` | 词条 → 该词的 IDF 与倒排列表 |
| `index[term].postings` | `list[[int, int]]` | `[chunk_ids 下标, 词频]` |
| `total_documents` / `avg_doc_length` / `k1` / `b` | — | BM25 打分参数，语义不变 |

### 不变量

- `len(chunk_ids) == len(doc_lengths) == total_documents`
- 所有 `postings` 中的下标必须落在 `[0, len(chunk_ids))`
- `chunk_ids` 内元素唯一
- **`chunk_ids` 中的每个标识都必须能在对应集合的向量库中取回** —— 这是 D1 的直接反制，也是 FR-001 的可执行判据

### 状态迁移

```
旧格式索引（chunk_id 内嵌、无版本号、与向量库标识不相交）
        │
        │  scripts/rebuild_bm25_index.py
        │  数据源：向量库的 iter_records(include_vectors=False)
        ↓
临时文件（写入中，尚未生效）
        │  os.replace 原子替换
        ↓
新格式索引（ID 字典化、带版本号、标识与向量库一致）
```

中途失败时临时文件被清理，原索引不受影响（FR-003）。

---

## 3. 集合布局（Collection Layout）

### 迁移前（实测）

| Chroma 物理集合 | 向量数 | 内含的 `metadata.collection` 取值 |
|---|---|---|
| `default` | 52,757 | `mt5_docs_chinese` 21,193 / `mt5_docs_english` 31,387 / `default` 15 / 临时残留 10 |
| `finpoints_handbook` | 162 | `finpoints_handbook`（已正确） |
| `mt5_docs_chinese` | 0 | 空壳 |

关键词侧则已按集合分成独立文件 —— **两侧口径不一致即 D2**。

### 迁移后（目标）

| Chroma 物理集合 | 来源 | 关键词索引文件 |
|---|---|---|
| `mt5_docs_chinese` | 从 `default` 复制 `metadata.collection == "mt5_docs_chinese"` 的 21,193 条 | `mt5_docs_chinese.json` |
| `mt5_docs_english` | 同上，31,387 条 | `mt5_docs_english.json` |
| `finpoints_handbook` | 已正确，不动 | `finpoints_handbook.json` |
| `default` | **保持原样不删**（可回滚） | `default.json` |

### 校验规则

| 规则 | 说明 |
|---|---|
| 迁移为复制语义 | 源集合在人工确认前保持完整（FR-006 / SC-007） |
| 迁移幂等 | 重复执行不产生重复记录（按 chunk 标识 upsert） |
| 向量必须随行 | 迁移携带 embedding，不重新生成（SC-005） |
| 无归属数据单独列出 | 10 条临时文件残留不归入任何目标集合，输出清单待人工确认（FR-007） |
| 两侧集合名一一对应 | 每个物理集合都有同名索引文件，反之亦然（FR-004） |

---

## 4. 基线标注（Baseline Annotation）

在 `logs/baselines.json` 的基线记录上追加标注字段，**不修改任何既有指标数字**。

| 字段 | 取值 | 含义 |
|---|---|---|
| `retrieval_mode` | `dense_only` / `hybrid` | 该次评估实际生效的检索模式 |
| `corpus_validity` | `valid` / `mismatched` | 语料是否与金标匹配 |

### 既有记录的回填结论

research.md Decision 7 的实测表明：2026-04-28 的两份完整评估**检索回的是无关文档**（公司政策、临时文件），说明当时 MT5 语料尚未 ingest。

因此既有记录回填为 `corpus_validity: mismatched` —— **不是**最初设想的「纯向量参照」。它无法作为任何对比基准，保留的意义是记录这段历史、避免后人误用。

### 兼容性

`baseline_manager.py:293` 读取时只拒绝**高于**当前值的 `_schema_version`，因此追加可选字段属向后兼容加法。旧记录缺失该字段时视为「未标注」。写入沿用既有 `_write_store_atomic()` 原子写路径。

---

## 5. 复用而不改动的既有类型

| 类型 | 位置 | 本 feature 中的角色 |
|---|---|---|
| `Chunk` | `src/core/types.py` | 重建时由向量库记录构造，喂给 `SparseEncoder.encode()` |
| `ChunkRecord` | `src/core/types.py:172` | `SparseEncoder` 的产物，带 `sparse_vector`，喂给 `BM25Indexer.build()` |
| `RetrievalResult` | `src/core/types.py` | 检索返回类型，不变 |

**本 feature 不新增任何跨模块共享类型**，因此 `src/core/types.py` 不需要改动（宪法原则六只要求共享类型集中定义，未新增即无需改）。

---

## 6. 新增抽象方法：`BaseVectorStore.iter_records`

```python
def iter_records(self, include_vectors: bool = False,
                 batch_size: int = 1000) -> Iterator[Dict[str, Any]]
```

| 返回字段 | 类型 | 条件 |
|---|---|---|
| `id` | `str` | 总是 |
| `text` | `str` | 总是 |
| `metadata` | `dict` | 总是 |
| `vector` | `list[float]` | 仅 `include_vectors=True` |

**为什么需要它**：既有 `get_by_ids` 不返回向量，且需先知道 ID 列表；`query` 是相似度检索而非全量枚举。「枚举集合内全部记录」是任何向量库都具备的通用能力，属扩展既有抽象而非新增组件层级。

**两个消费方**：迁移用 `include_vectors=True`，重建用 `include_vectors=False`（省内存 —— 52,919 条向量远大于 20 MB 正文）。

**分批**：`batch_size` 控制单次从底层拉取的记录数，避免一次性物化全部向量。
