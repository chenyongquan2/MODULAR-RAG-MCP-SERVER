# Phase 0 Research: 检索基础设施修正

**Feature**: 004-retrieval-infra-fix
**Date**: 2026-08-09
**Input**: [spec.md](./spec.md)

本文记录 plan 阶段的技术选型与实测依据。所有数字均为本机实测（2026-08-09，`.venv` Python 3.12 + chromadb 1.4.1）。

---

## Decision 1：从向量库反向重建关键词索引（不重新 ingest）

**Decision**：重建的数据源是 Chroma 自身持有的 `embedding_id` + `chroma:document` + `metadata.collection`，不读原始文档、不产生 embedding 调用。

**Rationale**：这不是权衡后的偏好，而是被数据现状锁死的唯一可行路径：

- `ingest_source/` 目录已不存在 —— 金标引用的 `MetaTrader5SDK_English.chm` 等原始文档已被删除，无法重新 ingest
- `embedding.provider: openai`（经 Qwen 端点），重新生成 52,919 条向量有真实 API 成本
- Chroma 中同时持有正文与标识，反向重建在数据上完全可行

**可行性实测**：

| 指标 | 实测值 |
|---|---|
| 正文总量 | **20 MB** / 52,919 条 |
| 单 chunk 平均 | 395 字符（最大 499） |
| 内存可行性 | 全量装内存无压力 |

**复用既有组件**，不重复造轮子：

```
Chroma → Chunk(id, text, metadata)
       → SparseEncoder.encode()   → ChunkRecord(sparse_vector)
       → 按 metadata['collection'] 分组
       → BM25Indexer.build(records, collection) → save()
```

`BM25Indexer.build()` 现有签名 `(records: List[ChunkRecord], collection: str)` 无需改动即可复用；它内部已实现两遍扫描（先统计 df 算 idf，再建倒排）。

**Alternatives considered**：

- *重新 ingest*：原始文档已不存在，直接不可行
- *只修改现有索引的 chunk_id 映射*：两套 ID 之间不存在可推导的映射关系（一个是文件路径 hash，一个是文件绝对路径），无法转换
- *手写重建逻辑*：会与 `SparseEncoder` / `BM25Indexer` 产生第二份切分与打分实现，正是本 feature 要消灭的问题

---

## Decision 2：索引存储改为 chunk_id 字典化编码

**Decision**：索引文件结构改为「chunk_id 表 + 倒排项存整数下标」，倒排项从 `{"chunk_id": "...", "tf": 5.0, "doc_length": 301}` 变为 `[id_index, tf]`。

**Rationale**：这是让中文支持在体积上可行的**前提条件**，不是锦上添花。

新的 chunk_id 是**路径式**的，比旧的长 2.4 倍：

| | 平均长度 |
|---|---|
| 旧 `doc_ef2c08f714519e8e_0000_ec888c20` | 38 字符 |
| 新 `C:\workspace\...\MetaTrader5SDK_English.chm_1925_a0973c74` | **91 字符**（最长 109） |

叠加中文 bigram 带来的倒排项增长（205,469 → 约 1,207,000，见 Decision 3），若沿用现格式，索引会失控：

| 方案 | 每倒排项 | 1.2M 项总计 |
|---|---|---|
| A 现格式 + 新长 ID | 136 B | **156 MB** |
| B 去掉冗余的 `doc_length` | 116 B | 133 MB |
| C 紧凑数组 `["...", 5]` | 97 B | 111 MB |
| **D chunk_id 字典化 `[12345, 5]`** | **10 B** | **12 MB** + ID 表 4.8 MB |

**选 D**。瘦身后总计约 17 MB —— 尽管倒排项增长约 6 倍，索引反而比现在磁盘上的 38 MB **更小**。这是 SC-011（启动耗时不超过修复前 2 倍）能达成的原因。

两项附带的冗余消除：

- `doc_length` 在每个倒排项里重复存储，而顶层 `doc_lengths` 已有一份完整映射 —— 删除倒排项内的副本
- 磁盘上现有索引带 `indent=4`（旧版代码产物），而当前 `bm25_indexer.save()` 写的是无缩进 JSON —— 重建后自动消除，约占现有体积的一半

**Alternatives considered**：

- *保持现格式*：156 MB 索引，加载耗时和内存都不可接受（当前 38 MB 已需 1.81 s / 67 MB 常驻）
- *改用二进制格式（pickle / msgpack）*：体积更优，但牺牲可读性与可诊断性；本次问题的发现过程高度依赖「直接打开 JSON 看内容」，保留这个能力有实际价值
- *引入专用检索引擎*：属于框架级依赖更换，按宪法《架构稳定性》需 MAJOR 修宪，远超本 feature 范围

---

## Decision 3：中文切分采用字符 bigram（不引入词典分词）

**Decision**：CJK 字符段按相邻两字滑窗切分；ASCII 段沿用现有整词逻辑；两者在同一份实现中并存。

**Rationale**：

- **语料特性决定**：目标是 MT5 技术文档，现有索引中有 7,165 个纯 ASCII 词条（函数名、错误码、参数名），说明中文文档里混杂大量专有名词。词典分词对未登录词切分效果差，需要长期维护自定义词典
- **零依赖**：不引入新的第三方包
- **与现有约束兼容**：现有 `min_term_length = 2` 恰好放行二字组合；词典分词切出的单字词反而会被这个过滤器吃掉
- **业界验证**：Elasticsearch 的 CJK analyzer 默认即为 bigram 策略
- **噪音可自愈**：跨词边界的 bigram（如「理这」「果仅」）会出现在大量文档中 → 文档频率高 → IDF 低 → BM25 自动给它们极低权重

**实测规模**（3,000 chunk 采样，外推至全量 20,798 条中文 chunk）：

| 指标 | 实测/外推值 |
|---|---|
| 采样汉字总数 | 224,176 |
| distinct bigram | 10,101（采样内） |
| 每 chunk 平均 distinct bigram | 48 |
| 全量新增倒排项 | 约 1,001,562 |
| 倒排项总量 | 205,469 → 约 1,207,000（约 5.9×） |

**切分规则细节**：

1. 先按字符类别把文本切成 CJK 段与非 CJK 段
2. CJK 段长度 ≥ 2：滑窗取全部相邻二字组合
3. **CJK 段长度 = 1：该单字直接作为词条收录** —— 否则「钱」「房」这类单字查询在关键词路径上永远无结果（对应 spec 的 Edge Case）
4. 非 CJK 段：沿用现有 `\b[a-z0-9]+\b` + 停用词过滤 + 长度约束
5. **长度约束只作用于 ASCII 词条**，CJK 词条豁免（否则规则 3 产出的单字词条会被立即过滤掉，自相矛盾）

**Alternatives considered**：

- *词典分词（jieba 一类）*：语义更准、索引小 2-3 倍，但引入约 20 MB 词典依赖、对 MT5 术语切碎、单字词被现有长度约束吃掉。用户在设计盘问中明确选择 bigram
- *trigram 或混合 n-gram*：召回更高但索引再涨数倍，且 bigram 对中文已是业界默认平衡点
- *把 tokenizer 做成可插拔组件（base + factory）*：用户在设计盘问中明确未选此项，理由见 Decision 4

---

## Decision 4：Tokenizer 作为共享工具模块，不建立新的可插拔组件层级

**Decision**：新建 `src/core/text/tokenizer.py`，作为查询端与索引端共同 import 的**普通共享模块**，不设 base 抽象类、不设 factory。

**Rationale**：

- **宪法《架构稳定性》**规定新增组件层级需在 plan 中「明确证明现有抽象层无法满足」并遵循 base + factory 模式。本次不新增组件层级，因此不触发该流程
- 宪法原则一列举的可替换组件是「LLM、Embedding、Splitter、向量库、Reranker、Evaluator」，tokenizer 不在其中，且本 feature 不引入 provider 选择的需求（只有一种切分策略）
- 用户在设计盘问中明确在「bigram + 索引瘦身」与「bigram + tokenizer 做成可插拔」之间选择了前者 —— **不预先建设未被需要的可替换性**
- 若将来确实需要词典分词作为备选，届时按《架构稳定性》流程升级为组件层级，成本可控

**放置位置**：`src/core/text/` 而非 `src/libs/`。理由：`src/libs/<component>/` 是 provider 实现的位置（base + factory 模式），把非可插拔的工具模块放进去会造成误导。它被 `src/ingestion/embedding/sparse_encoder.py` 与 `src/core/query_engine/query_processor.py` 跨包共用，放在 `src/core/` 下符合既有的共享代码惯例（对比 `src/core/types.py`）。

**这是本 feature 最重要的结构性约束（FR-009）**：查询端与索引端必须 import 同一个函数。两端各留一份副本正是 D3 的成因 —— 一旦口径漂移，查询切出的词条永远匹配不上索引里的词条，而且**这种失败是静默的**（不报错，只是永远召回为空）。

---

## Decision 5：collection 统一到物理隔离，复制式迁移

**Decision**：向量侧按 `metadata.collection` 拆分到独立的物理 collection，与关键词侧现有的分文件存储对齐。迁移采用复制方式，原 `default` collection 保持完整。

**Rationale**：

不一致的根因【代码】：

- `vector_upserter.py:102` 的 `upsert()` **从不传 collection** → 向量全部写入 `settings.vector_store.collection_name` 指向的那一个物理 collection
- `pipeline.py:650` 的 `bm25_indexer.build(records, collection=self._collection)` → 关键词侧**按 collection 分文件**

所以 `--collection` 参数在两侧语义完全不同：关键词侧是物理隔离，向量侧只是给 chunk 打了个元数据标签。

**为什么选物理隔离而非逻辑隔离**：

- 逻辑隔离要求关键词侧也建单一大索引 + 检索时过滤，会让 BM25 的 IDF 被跨语料污染（中英文混算逆文档频率，破坏打分基准）
- 元数据过滤发生在结果融合**之后**（`hybrid_search.py:220`），top_k 会被削减得七零八落
- Chroma 原生支持多 collection，物理隔离在检索阶段就缩小范围，性能更好

**为什么复制而非移动**：磁盘可用 63 GB，Chroma 全部数据仅 626 MB，复制成本可忽略；不做不可逆删除。原数据在人工确认前保持完整可回滚（FR-006 / SC-007）。

**当前布局实测**：

| Chroma 物理 collection | 向量数 | | `metadata.collection` 取值 | 条数 |
|---|---|---|---|---|
| `default` | 52,757 | | `mt5_docs_chinese` | 21,193 |
| `finpoints_handbook` | 162 | | `mt5_docs_english` | 31,387 |
| `mt5_docs_chinese` | **0（空壳）** | | `finpoints_handbook` | 324 |
| | | | `default` | 15 |

`finpoints_handbook` 已是正确布局（应是配置对齐时 ingest 的），迁移只需处理 `default` 内的 52,757 条。

**Alternatives considered**：

- *统一到逻辑隔离*：IDF 污染 + 融合后过滤削 top_k，见上
- *合并成单一 collection*：中英文金标分两套，混在一起会有语言干扰（英文查询召回中文 chunk），且切分策略被迫共用一套
- *移动式迁移*：省 626 MB 空间，但引入不可逆风险，收益与风险不成比例

---

## Decision 6：`--collection` 改为覆盖配置真源，而非注入过滤器

**Decision**：CLI 的 `--collection` 参数改为覆盖 `settings.vector_store.collection_name`（在构造检索器之前），而不是构造 `filters={"collection": ...}`。

**Rationale**：`collection_name` 已经是两侧共同的真源 —— `sparse_retriever.py:67` 用它决定加载哪个索引文件，`DenseRetriever` 经 `VectorStoreFactory.create(settings)` 用它决定打开哪个物理 collection。迁移完成后（Decision 5），覆盖这一个值就能让两路同时正确换范围。

现有做法把它塞进 `filters` 走 `_apply_metadata_filters`，是**融合后过滤**，且关键词侧根本不看这个参数 —— 这正是 D2 在使用侧的表现。

**改动点**：

| 文件 | 现状 | 目标 |
|---|---|---|
| `scripts/evaluate.py:180` | `filters = {"collection": args.collection}` | 覆盖 settings 后再构造检索器 |
| `scripts/query.py:76-78` | 同上 | 同上 |

元数据过滤能力本身保留 —— 它回归真正的用途（按 `doc_type`、`tags` 等维度过滤），只是不再承担集合切换的职责。

---

## Decision 7：既有基线保留并追加检索模式标注

**Decision**：在 `logs/baselines.json` 的基线记录中追加检索模式与语料有效性标注；既有记录标为**「语料不匹配，不可用作参照」**（而非最初设想的「纯向量参照」）。原始指标数字不做任何修改。

> **本决策在 Phase 0 期间经实测推翻过一次原始设想，修正如下。**

**实测发现**：`logs/evaluation_reports/` 下 152 份归档中，**145 份是 pytest 临时产物**（`test_set_path` 指向 pytest tmp 目录），真实评估仅 7 份。其中在完整金标上跑过的只有两份：

| 报告 | 金标 | 条数 | 时间 | 结果 |
|---|---|---|---|---|
| `866eb7e3` | `golden_test_set_en.json` | 42 | 2026-04-28 | 全部指标 0 |
| — | `golden_test_set_zh.json` | 6 | 2026-04-28 | fail |

英文那份**全 42 条 hit_rate / recall / MRR 均为 0，包括 22 条 simple**。逐条检查其 `retrieved_chunk_ids` 发现真相：

```
expected : ...\ingest_source\MetaTrader5SDK_English.chm_7444_9692ddea
retrieved: C:\workspace\mt-tools\docs\company_policy.md_1_f855fd86
           C:\Users\cyq\AppData\Local\Temp\tmpg0csbti9.md_1_f855fd86
```

检索回的是**完全无关的文档**（公司政策、临时文件）。结论：**2026-04-28 时 MT5 语料尚未 ingest 进 `default`**，该次评估跑在一个不含目标内容的集合上。

**因此旧基线不是「纯向量参照」，而是「跑在错误语料上的无效记录」** —— 它无法作为任何对比的基准。原始设想（保留旧基线即可白捡一组消融数据）不成立。

**Rationale（修正后）**：仍然保留、不删除 —— 但标注口径从「纯向量参照」改为「语料不匹配」。保留的价值从「可用作对比」降级为「记录这段历史，避免后人再次误用」。同时这解释了为何 `acceptance_status` 一直是 `fail`：不是检索质量差，是语料压根不在库里。

**兼容性**：`baseline_manager.py:293` 读取时校验 `_schema_version`，只拒绝**高于**当前版本的 schema。追加可选字段属向后兼容的加法，旧记录缺失该字段即视为「未标注」。写入沿用既有的 `_write_store_atomic()` 原子写路径。

**兼容性**：`baseline_manager.py:293` 在读取时校验 `_schema_version`，但只拒绝**高于**当前版本的 schema。追加一个可选字段属于向后兼容的加法，读取旧记录时该字段缺失即视为「未标注」。写入采用既有的 `_write_store_atomic()` 原子写路径（临时文件 + `os.replace`），不新增写入机制。

**Alternatives considered**：

- *删除旧基线*：丢失历史趋势与对比数据，且掩盖了这个缺陷曾经存在的事实，不利于可追溯性
- *就地修正旧数字*：无法修正 —— 那需要用修复后的系统重跑当时的数据，而当时的系统状态已不可复现

---

## Decision 8：验收执行顺序 —— 缺口分析在修复之后

**Decision**：必须在索引重建**之前**，先在**当前语料**上补跑一次中英文评估，作为真正的「纯向量参照」；SC-009 的缺口分析则在重建**之后**执行。

**Rationale**：这一项经 Decision 7 的实测发现后作了两次修正。

*第一次修正*（设计盘问 → Phase 0 初稿）：盘问时把「跑数」排在重建之前，理由是英文金标不受中文切分影响、可早拿决策数据。但那样测的是**仍然坏着的系统**（关键词路径返回空），得出的「多跳更难」结论未必在修复后成立 —— 修好关键词路径后，多跳问题可能恰好因为关键词锚点而变简单。故 SC-009 应在修复后测。

*第二次修正*（Decision 7 实测后）：原以为「纯向量参照」可直接引用既有归档，**该前提已被证伪** —— 既有归档跑在错误语料上（见 Decision 7）。因此若要达成 SC-008（纯向量 vs 混合的逐指标对比），**必须在重建前补跑一次基准评估**。

**执行顺序因此确定为**：

```
① 补跑基准评估（当前语料 + 当前失效的关键词路径 = 真正的纯向量参照）
        ↓  必须在此之前完成，一旦重建就再也测不到「修复前」
② 迁移 + 重建 + 中文切分
        ↓
③ 重跑评估（真混合）→ 与 ① 对比得 SC-008
        ↓
④ 按难度分组统计 → SC-009
```

**代价与约束**：

- ① 有真实 API 成本：42 + 6 条金标 × (embedding + RAGAS judge LLM 调用)。这是 SC-008 无法回避的代价 —— **修复前的状态一旦被重建覆盖就永久不可复现**
- ① 必须在**迁移完成后、重建之前**执行，否则集合范围不可比：迁移改变的是数据布局而非检索逻辑，不影响「纯向量」这一性质
- 逐条结果（`case_results`）含 `query` 字段，可与金标按 query 关联取得 `tags.difficulty`，分组统计无需额外改造评估器

**附带发现（超出本 feature 范围）**：`logs/evaluation_reports/` 被 145 份 pytest 临时产物污染 —— 测试直接写入了 `settings.evaluation.report_archive_dir` 指向的生产归档目录，而非临时目录。这会让归档难以浏览、基线容易误选。已单列为独立问题，不在本 feature 处理。

---

## 无 NEEDS CLARIFICATION 项

spec 阶段的主要决策已在设计盘问中逐一定案（目标语料范围、隔离口径、切分方案、feature 切分粒度、中文验收口径、基线处置），本阶段的技术选型均可由实测数据与既有约束推导，无遗留待澄清项。

## 实测环境说明

- 所有 Python 实测均使用 `.venv/Scripts/python.exe`（protobuf 3.20.3，满足 `pyproject.toml` 的 `<4` 约束）
- 全局 Python 的 protobuf 为 5.29.3，`import chromadb` 会失败 —— 本 feature 的所有脚本与测试必须在 `.venv` 下运行
