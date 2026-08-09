# Contract: 关键词索引文件格式 v2

**Feature**: 004-retrieval-infra-fix
**File**: `data/db/bm25/<collection>.json`
**Format version**: `2`
**Date**: 2026-08-09

本契约定义关键词索引文件的磁盘格式。写入方为 `BM25Indexer.save()`，读取方为 `BM25Indexer.load()`。格式变更**必须**同步 bump `_format_version` 并更新本文件。

---

## 为什么要改格式

v1 把完整的 chunk 标识字符串内嵌在每一个倒排项里。当标识从 38 字符的 `doc_<hash>_<idx>_<hash>` 变成 91 字符的绝对路径式，再叠加中文 bigram 带来的约 6 倍倒排项增长，索引体积会失控：

| 方案 | 每倒排项 | 1.2M 项总计 |
|---|---|---|
| v1 格式 + 新长标识 | 136 B | **156 MB** |
| **v2（标识字典化）** | **10 B** | **12 MB** + 标识表 4.8 MB |

v2 让索引在倒排项增长 6 倍的情况下反而比现状（38 MB）更小，是 SC-011 得以达成的原因。

---

## Schema

```jsonc
{
  "_format_version": 2,

  // 标识表：下标即倒排项中引用的整数。顺序即身份，不可重排。
  "chunk_ids": [
    "C:\\workspace\\...\\MetaTrader5SDK_English.chm_1925_a0973c74",
    "C:\\workspace\\...\\MetaTrader5SDK_English.chm_1926_b1084d85"
  ],

  // 与 chunk_ids 同下标对齐的文档长度（词条数）
  "doc_lengths": [301, 288],

  // 倒排索引：词条 → {idf, postings}
  "index": {
    "metatrader": {
      "idf": 3.3551298086596004,
      // 每项为 [chunk_ids 下标, 该 chunk 内的词频]
      "postings": [[0, 5], [1, 1]]
    },
    "预约": {
      "idf": 5.201,
      "postings": [[1, 3]]
    }
  },

  // BM25 打分参数（语义与 v1 相同）
  "total_documents": 2,
  "avg_doc_length": 294.5,
  "k1": 1.5,
  "b": 0.75
}
```

### 字段约束

| 字段 | 类型 | 约束 |
|---|---|---|
| `_format_version` | `int` | 必须为 `2`。**不匹配时立即抛 `ValueError`** |
| `chunk_ids` | `list[str]` | 元素唯一；长度 == `len(doc_lengths)` == `total_documents` |
| `doc_lengths` | `list[int]` | 每项 ≥ 0；与 `chunk_ids` 下标一一对齐 |
| `index` | `dict[str, object]` | 键为词条 |
| `index[t].idf` | `float` | 预计算的逆文档频率 |
| `index[t].postings` | `list[[int, int]]` | 每项 `[chunk_index, tf]`；`chunk_index ∈ [0, len(chunk_ids))`；`tf ≥ 1` |
| `total_documents` | `int` | 参与建索引的文档数 |
| `avg_doc_length` | `float` | `sum(doc_lengths) / total_documents`，`total_documents == 0` 时为 `0.0` |
| `k1` / `b` | `float` | BM25 参数，默认 1.5 / 0.75 |

### 序列化约定

- **UTF-8，`ensure_ascii=False`** —— 中文词条以原字符存储，便于直接打开诊断
- **不使用缩进** —— 缩进约占体积一半（磁盘上现存 v1 文件带 `indent=4`，是旧版代码遗留；当前 `save()` 已无缩进）
- **`tf` 存整数** —— v1 存的是 `5.0` 这样的浮点，纯属浪费

---

## 加载行为契约

| 场景 | 行为 |
|---|---|
| `_format_version == 2` | 正常加载 |
| `_format_version` 缺失（v1 文件） | **抛 `ValueError`**，提示需运行重建脚本 |
| `_format_version > 2` | **抛 `ValueError`**，提示代码版本过旧 |
| 文件不存在 | 返回 `False`（沿用 v1 既有行为，非错误） |
| JSON 损坏 | 返回 `False`（沿用 v1 既有行为） |

> **为什么版本不匹配必须抛异常而不是静默重建或降级**：本 feature 修复的三个缺陷全部属于「静默失效」—— 不报错、不告警，只是结果悄悄变空。若这里再留一条静默降级路径，等于在刚修好的地方重新埋雷。这也是宪法原则三（快速失败校验，禁止静默回退默认值）的直接要求。

---

## 写入行为契约

| 要求 | 说明 |
|---|---|
| 原子替换 | 先写同目录临时文件，完整后 `os.replace`。中途失败不得破坏现有可用索引（FR-003） |
| 临时文件清理 | 失败路径必须删除临时文件 |
| 目录自动创建 | 沿用 v1 行为 |

---

## 跨契约不变量（与向量库的关系）

**`chunk_ids` 中的每个标识都必须能在同名集合的向量库中取回。**

这条不是索引文件的内部约束，而是它与向量库之间的契约 —— 也正是 D1 违反的那一条：v1 索引里的标识在向量库中命中 **0/200**，导致关键词检索路径取不到正文、返回空，结果融合因此从未真正发生。

验证方式：抽样 `chunk_ids` 调用向量库的 `get_by_ids()`，命中率必须为 100%。这是 FR-001 的可执行判据，应在重建脚本的统计报告中输出（FR-013）。

---

## 兼容性与迁移

v1 → v2 **无就地升级路径**。v1 索引的标识体系与向量库不相交，即使转换格式也仍然是错的 —— 必须通过 `scripts/rebuild_bm25_index.py` 从向量库反向重建。

磁盘上现存的 v1 文件（`default.json` / `finpoints_handbook.json` / `mt5_docs_chinese.json` / `mt5_docs_english.json`）在重建后被整体替换。
