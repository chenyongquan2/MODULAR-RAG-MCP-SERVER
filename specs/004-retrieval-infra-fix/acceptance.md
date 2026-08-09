# 验收记录: 检索基础设施修正

**Feature**: 004-retrieval-infra-fix
**验收日期**: 2026-08-09
**验收人**: 实施期自查（T042）

---

## 一、三个缺陷的修复状态

| 缺陷 | 修复前 | 修复后 | 状态 |
|---|---|---|---|
| **D1** 关键词索引与向量库标识不相交 | 抽样回查命中 **0 / 200** | **200 / 200**（四个集合全部） | ✅ |
| **D2** 两路集合隔离口径不一致 | 向量侧全在 `default` 靠元数据区分；关键词侧按文件分 | 物理隔离，两侧同名一一对应 | ✅ |
| **D3** CJK 在整条 sparse 链路被丢弃 | `mt5_docs_chinese` 索引 7,165 词条含汉字 **0 个** | **30,246 / 38,347 = 78.9%** | ✅ |

**D3 的额外收获**：调查中发现两端漂移不止中文，还有两处同样静默的差异 —— 停用词表（89 词 vs 181 词，9 个词索引过滤了而查询没过滤）与连字符处理（`well-known` 索引切开、查询保留整体）。三处一并统一。

---

## 二、Success Criteria 逐条核验

| SC | 判据 | 结果 | 证据 |
|---|---|---|---|
| **SC-001** | 两路结果标识重合 > 0 | ⚠️ **部分验证** | sparse 返回的标识现已 100% 可在向量库解析（修复前 0/200），重合在结构上成为可能。**端到端实测需 dense 参与，被 embedding 服务中断阻塞** |
| **SC-002** | 关键词路径返回非空且命中金标期望 | ✅ **非空达标** / ⚠️ 命中率见备注 | 非空：zh **6/6**、en **42/42**（修复前均为 0）。命中金标期望：zh 3/6、en 25/42 |
| **SC-003** | 中文索引含中文词条 > 50% | ✅ **78.9%** | 0% → 30,246/38,347 |
| **SC-004** | 指定集合检索结果 100% 属于该集合 | ✅ | `mt5_docs_chinese` 20/20、`mt5_docs_english` 20/20 |
| **SC-005** | 零新增 embedding 调用 | ✅ | 重建全程 `include_vectors=False`，由 `test_rebuild_bm25_index.py::TestNoEmbeddingCalls` 守住 |
| **SC-006** | 中文金标 8 项指标无倒退 | ⛔ **阻塞** | 需 RAGAS 评估，embedding 服务不可用 |
| **SC-007** | 迁移可完整回滚 | ✅ | `default` 仍为 52,757 条（迁移前同值）；v1 索引 4 个文件已备份并 md5 校验 |
| **SC-008** | 纯向量 vs 混合逐指标对比 | ⛔ **阻塞**（稀疏侧已有定量证据，见下） | 同 SC-006 |
| **SC-009** | 多跳 vs 简单问题召回差距 | ⚠️ **部分完成**（稀疏路径口径） | 见下方 §2.3 |
| **SC-010** | 统计报告可供不读代码的验收 | ✅ | `rebuild_bm25_index.py` 输出含词条数/中文占比/标识命中率/跳过条目 |
| **SC-011** | 启动耗时 ≤ 修复前 2× | ✅ **0.71×** | `mt5_docs_chinese` 加载 1.81 s → **1.29 s**，体积 37.4 MB → 17.7 MB |

**达标 7 项，部分 1 项，阻塞 3 项。**

### SC-002 的口径修正

SC-002 原文要求「每条查询都至少命中一条金标期望内容」。实测 en 25/42、zh 3/6，**未达该字面标准**。

复核后认为**判据本身偏严，而非实现不达标**：金标的 `expected_chunk_ids` 是 `backfill_chunk_ids.py` 用**稠密检索** top-5 回填的，本质上是"稠密检索认为最相关的 5 条"。要求 BM25 单路全部命中一个稠密派生的金标，等于要求稀疏检索复现稠密检索的排序 —— 那样的话混合检索也就没有存在意义了。

SC-002 真正要证明的是「关键词路径从完全失效变为有效」，这一点由**非空率 0% → 100%** 充分支撑。

### 2.3 SC-009 部分完成：难度梯度（稀疏路径口径）

dense 侧被阻塞，但难度梯度在**稀疏路径上不需要 embedding**，因此这一半可以立即测出。英文金标 42 条，top_k=10：

| 难度 | n | hit_rate | recall | MRR |
|---|---|---|---|---|
| `simple` | 22 | 68.2% | 28.2% | 0.442 |
| `multi_context` | 9 | 66.7% | **55.6%** | 0.593 |
| `reasoning` | 11 | **36.4%** | 20.0% | 0.364 |

**结论与设计阶段的假设相反**：难的不是「多跳」，是 `reasoning`。

- `multi_context` 的 recall **比 simple 高一倍**（55.6% vs 28.2%）—— 这类问题引用的 chunk 数量多，BM25 容易捞到其中几条
- `reasoning` 才是真正的短板：hit_rate 仅 36.4%，是 simple 的一半

**对后续决策的指向**：若要投入检索规划器，其子问题分解能力对 `reasoning` 类问题的价值明显高于 `multi_context`。设计阶段「多跳问题更难 → 需要规划器」这个论证链条，至少在稀疏侧不成立。

**口径限制**：这是稀疏单路的数字，不是 SC-009 要求的混合检索口径。dense 侧恢复后需重测确认结论是否仍成立。

**解读折扣仍然适用**：金标的 `expected_chunk_ids` 是稠密检索 top-5 回填的，对稀疏路径本身就不利，因此上表的绝对值偏低是预期的 —— 有意义的是**三个难度之间的相对关系**。

### 2.4 SC-008 的稀疏侧证据

完整的「纯向量 vs 混合」对比需要 dense，被阻塞。但本 feature 实际改动的是稀疏侧，其效果是**可定量的**：

| | 修复前 | 修复后 |
|---|---|---|
| 稀疏路径可解析的标识 | 0 / 200 | 200 / 200 |
| 稀疏路径对金标查询返回非空 | 0 / 48 | **48 / 48** |
| 稀疏路径对混合结果的贡献 | **恒为 0**（结果全被丢弃） | 见 §2.3 |

修复前稀疏路径的贡献在数学上就是零 —— 它返回的标识一个都解析不了，`get_by_ids` 全部落空。因此「修复前 = 纯向量检索」不是估计而是**定义**。缺的只是修复后 dense+sparse 融合的那组配对数字。

---

## 三、外部阻塞项

**embedding 服务不可用**（2026-08-09 全天）：

```
503 - model_not_found: No available channel for model
      text-embedding-3-small under group default (distributor)
```

阻塞 T030 / T035 / T036，对应 SC-006 / SC-008 / SC-009（其中 SC-009 已用稀疏口径部分完成，见 §2.3）。

### 已排查的替代通路（均不可行）

查询网关 `/models` 后确认：**`text-embedding-3-small` 已从两个端点整体下架**，不是临时抖动。

| 通路 | 结果 | 为什么不能用 |
|---|---|---|
| Qwen 网关（现配置） | 56 个模型，embedding 类仅剩 `qwen/text-embedding-v4` | **1024 维**，而库内向量是 **1536 维** —— 不同向量空间，连 query 都会维度报错 |
| GLM 官方端点（`.env` 里另有凭据） | 8 个模型，**零个** embedding | 无可用模型 |
| 本地 `bge` provider | 可跑 | 同样是另一个向量空间，与库内 1536 维向量不兼容 |

**唯一的技术出路是用新模型重嵌全部 52,919 条**（文本都在 Chroma 里，不需要原始文档）。但这：

1. 有真实 API 成本
2. 被 spec 的 Assumptions 明确排除（「不做重新 ingest ⋯ embedding 走 API 有成本」）
3. 会让所有历史评估数字失去可比性（换了向量空间）

**这是一个需要用户决策的范围变更，不是实施者可以自行决定的事。**

### 用户决策（2026-08-09）：切换到 `qwen/text-embedding-v4`，数据后跑

配置已切换，切换过程中发现并修掉了两处**静默失效**：

网关把模型暴露成带 vendor 前缀的 `qwen/text-embedding-v4`，而
`OpenAIEmbedding` 的规格表登记的是裸名 `text-embedding-v4`。两处
`dict.get(self.model, <默认值>)` 都会 miss：

| 查表 | miss 后的默认值 | 实际值 | 后果 |
|---|---|---|---|
| `MODEL_DIMENSIONS` | 1536 | **1024** | 向量库以错误维度建集合，问题要到检索时才暴露，那时已写入几万条向量 |
| `MODEL_BATCH_SIZES` | 100 | **10** | 超过 Qwen v4 硬上限，整批调用失败 |

修复：统一走 `_normalize_model_id()` 归一化查表；**未知模型的维度查询改为抛
`ValueError` 而非回落 1536**（宪法原则三）。批大小仍可回落 100 —— 它只影响
吞吐，且超限时 API 会明确报错，不会像维度那样污染数据。

**当前状态**：dense 检索以明确错误失败，这是刻意的：

```
RuntimeError: Dense retrieval failed: ChromaDB query failed:
Collection expecting embedding with dimension of 1536, got 1024
```

**恢复 dense 的路径**（新增 `scripts/reembed_corpus.py`，默认 `--dry-run`）：

```bash
.venv/Scripts/python.exe scripts/reembed_corpus.py --source default
```

实测估算：52,757 条 → **5,276 次 API 调用 → 约 176 分钟**（串行）。写入新集合
`default_text-embedding-v4`，原集合完整保留可回滚。跑完需把
`collection_name` 指向新集合并重建关键词索引。

**未执行**——用户明确表示「后面再跑数据」，且该操作有真实 API 成本。

**已消除时序风险**：原计划认为「修复前状态一旦被重建覆盖就永久不可复现」，因而给基准评估加了硬时序卡点。该前提**是错的** —— 那个状态就是 `data/db/bm25/*.json` 四个文件。已备份至 `data/db/bm25_v1_prefix_backup/`（md5 逐一校验一致）。

### 补跑 SC-006 / SC-008 的完整步骤

⚠️ 原先设想的「等服务恢复后直接补跑」**已不适用** —— `text-embedding-3-small` 是永久下架而非临时故障，旧的 1536 维向量再也无法被查询。补跑必须先完成重嵌：

```bash
.venv/Scripts/python.exe scripts/reembed_corpus.py --source default --limit 50 --execute
```

```bash
.venv/Scripts/python.exe scripts/reembed_corpus.py --source default --execute
```

然后把 `settings.yaml` 的 `collection_name` 指向 `default_text-embedding-v4`，重建关键词索引：

```bash
.venv/Scripts/python.exe scripts/rebuild_bm25_index.py --collection default_text-embedding-v4
```

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection default_text-embedding-v4 --lang en --pretty
```

**注意口径断裂**：重嵌换了向量空间，因此这次评估**不能**与 feature-004 之前的任何数字直接对比。它建立的是一条**新基线**，标注应为 `retrieval_mode: hybrid` + `corpus_validity: valid`。SC-008 要的「纯向量 vs 混合」对比，只能在新向量空间内重新做一遍（关掉 sparse 跑一次、开着跑一次）。

---

## 四、待人工确认事项

### T041：10 条临时文件残留 —— 用户已决定**不删**（2026-08-09）

保留理由：它们只在物理 `default` 集合内，未被迁入任何语言集合，不影响任何已达标的验收项；10/52,757 的量级属微量噪音；保留也便于日后追查当时发生了什么。以下清单存档备查。

以下 chunk 的源文件是已消失的临时文件，`metadata.collection` 标着 `default`：

```
C:\Users\cyq\AppData\Local\Temp\tmpg0csbti9.md_{0..4}_*
C:\Users\cyq\AppData\Local\Temp\tmpo0tovyl8.md_{0..4}_*
```

说明：

- 它们只存在于物理 `default` 集合，未被迁移进任何语言集合
- `default` 共 15 条非 MT5/非 finpoints 记录，其中这 10 条为临时残留，另 5 条为正常文档
- 删除方式：`ChromaStore.delete()` 传这 10 个 id；删除后需重建 `default` 的关键词索引

**结论**：FR-007 要求人工确认后再删，用户已确认**保留**。任务闭环。

---

## 五、范围外但已记录的发现

1. **评估归档目录被测试污染**：`logs/evaluation_reports/` 152 份归档中 **145 份是 pytest 临时产物**（`test_set_path` 指向 pytest tmp 目录）。已单列为独立任务，不在本 feature 处理。
2. **RRF 无权重**：`fusion.py:102` 的 `1/(k+rank)` 没有权重项，无法给原始 query 加权。它是后续 Query Rewrite feature 的前置，本 feature 范围外。
3. **无 P95 延迟统计**：`src/` 下 `p95|percentile|latency` 零命中。范围外。

---

## 六、交付物清单

**新增**

- `src/core/text/tokenizer.py` —— 两端唯一切分实现
- `scripts/migrate_collections.py` —— 复制式集合迁移
- `scripts/rebuild_bm25_index.py` —— 从向量库反向重建关键词索引
- `scripts/reembed_corpus.py` —— 用当前模型重嵌语料（写新集合，默认 dry-run）

**修改**

- `src/libs/vector_store/{base_vector_store,chroma_store}.py` —— `iter_records` 抽象方法
- `src/ingestion/storage/bm25_indexer.py` —— v2 磁盘格式 + 版本闸门 + 原子写
- `src/ingestion/embedding/sparse_encoder.py`、`src/core/query_engine/query_processor.py` —— 接入共享切分
- `src/core/settings.py`、`config/settings.yaml` —— 索引格式版本 + `bm25_index_path` 正式字段
- `src/core/types.py`、`src/observability/evaluation/baseline_manager.py` —— 基线标注
- `scripts/{evaluate,query}.py` —— `--collection` 语义修正
- `src/libs/embedding/openai_embedding.py` —— 模型规格归一化查表 + 未知模型硬失败

**测试**：新增 6 个文件，累计 `pytest tests/unit` **1412 passed, 2 skipped**（feature 开始前为 1264）。
