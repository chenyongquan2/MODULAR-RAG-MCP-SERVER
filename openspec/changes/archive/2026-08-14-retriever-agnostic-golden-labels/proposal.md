## Why

金标的 `expected_chunk_ids` 是 [`scripts/backfill_chunk_ids.py`](../../../scripts/backfill_chunk_ids.py) 用**纯 dense 检索**回填的：把 `ground_truth`（答案文本）编码成向量，在向量库里查 top-5，过阈值后写入。也就是说 —— **标准答案本身就是「embedding 模型认为最像答案的那 5 条」**。

后果是所有召回类指标都锚定在 dense 这一条路径上。CLAUDE.md 早就记了一半：「`recall` / `hit_rate` 结构性偏向 dense，比较混合与单路时看 `MRR` / `nDCG`」。但 2026-08-13 的重排 A/B 证明**那条免责声明还不够**：

- 英文 42 条金标，cross-encoder 重排让 `custom__mrr` 从 0.4914 掉到 0.3668、`custom__ndcg` 从 0.4182 掉到 0.3373
- 而同一个模型在集成测试里，把**故意放在末位**（原始分数最低）的相关段落**每次都提到首位**，中文、英文、跨语言三组判据全过

模型在做正确的事，指标却在跌。原因是重排的全部工作就是**不同意第一阶段的排序**，而标准答案正是第一阶段的输出 —— 所以对重排而言，`MRR` / `nDCG` **并不比** `recall` / `hit_rate` 更中立，**四项 custom 指标全都是 dense-anchored 的**。

这不只影响重排。任何「敢改变名次」的改进 —— 查询改写、查询规划、换 embedding、调融合权重 —— 都会被这套金标系统性地低估。Feature-005 的验收记录已把「金标 `expected_chunk_ids` 的构造方式」列为「比调权重更根本的改进」；重排是对同一问题的第二次、更强的一次撞击。**在修掉它之前，本项目没有可信的离线检索指标。**

## What Changes

- **候选池化取代单路 top-K**：候选来自 dense、sparse（BM25）、以及重排后顺序**三路各自 top-N 的并集**，而不是 dense 一路的 top-5。这是信息检索领域标准的 pooling 做法 —— 每条路径都有机会把自己认为相关的东西送进池子，于是没有任何一路能垄断标准答案。
- **LLM 逐条判定取代相似度阈值**：对池中每个候选，让 LLM 判断「这个 chunk 是否支撑该问题的答案」，而不是看它与答案文本的余弦相似度。相似度高 ≠ 支撑答案（一段复述问题的文字可能相似度很高却毫无信息）。
- **判定模型必须与合成端异源**：`ground_truth` 是 `evaluation.judge_llm` 合成的，用同一个模型判定「哪些 chunk 支撑我自己写的答案」会引入自我确认偏差。判据沿用 Feature-003 已确立的规则 —— 完整标识串 `<provider>:<model>` 相等即视为同源，启动期拒绝。
- **产出可审计**：新金标带元数据记录每个 chunk 由哪几路召回贡献、判定模型标识、阈值快照、池子规模、判定通过率、人工抽检结果。与 Feature-003 的 `_review_metadata` 同一思路。
- **保留 `expected_chunk_ids` 的字段名与类型**（`list[str]`），因此 `custom_evaluator.py` 与报告 schema **零改动**；另加一个 sidecar 字段存分级相关度与判定理由，为将来的 graded nDCG 留数据。
- **BREAKING（评估语义）**：新金标产出后，**既有全部基线不再可比**。基线里的分数是在 dense-anchored 标准答案下算出来的，与新标准答案下的分数不是同一把尺子。需要重标基线，并在报告里显式区分两代金标。
- 顺带修掉 `backfill_chunk_ids.py` 的一个死参数：`--collection` 被接受但从不用于实际查询（脚本自己的 docstring 第 74-77 行承认了这点），实际查的是 `settings.vector_store.collection_name`。

## Capabilities

### New Capabilities

- `evaluation/golden-labels`: 金标相关性标注能力 —— 候选池化、LLM 判定、异源约束、可审计元数据、两代金标的可区分性。

### Modified Capabilities

无。`openspec/specs/` 下目前只有 `retrieval/rerank`，与本能力不重叠。

## Impact

**新增**
- 候选池化 + LLM 判定的脚本（取代 / 并存于 `scripts/backfill_chunk_ids.py`）
- `config/settings.yaml` 的 `evaluation` 段新增标注相关配置项 + `src/core/settings.py` 对应 dataclass 字段与启动期校验
- `tests/unit/` 覆盖池化、判定解析、异源校验、元数据落盘

**改动**
- `scripts/backfill_chunk_ids.py`：死参数 `--collection` 修复或明确移除
- 金标文件：产出新版本，**旧版保留**（`v1.0` → 新版本号），不原地覆盖
- 报告需能区分两代金标（否则历史 delta 会静默误导）

**运行成本**（必须先说清楚，这是本变更最大的实际约束）
- 池子规模按 `top_k_dense` 20 + `top_k_sparse` 20 估算，去重后每 case 约 25–40 个候选
- 中英金标共 48 条 case → **约 1200–1900 次 LLM 判定调用**
- 网关此刻不稳（2026-08-13 实测到 embedding 超时与 RAGAS `TimeoutError`），需要重试与断点续跑，否则一次失败就得全部重来

## 验收判据

**这个变更的验收不能用 custom 四项指标** —— 那正是它要修的东西，用它验收是循环论证。判据是：

1. **金标不再锚定单一路径**：新金标中，仅由 dense 召回的 chunk、仅由 sparse 召回的 chunk、仅由重排提升上来的 chunk **都存在**。若产出的标签集与纯 dense top-5 高度重合（比如 Jaccard > 0.9），说明池化或判定没起作用。
2. **重排的矛盾消失或被解释**：在新金标下重跑重排 A/B。**预期是负增益缩小或转正**；若仍显著为负，则重排确实无益于本语料 —— 那也是有价值的结论，因为这次的判据是可信的。**本变更不预设 A/B 结果**。
3. **人工抽检一致率**：随机抽 ≥ 20 个 (query, chunk, 判定) 三元组人工复核，记录与 LLM 判定的一致率。低于某个水平则判定不可用。**这是唯一能校准 LLM 判定的手段**，不能省。
4. 单元测试全绿（硬约束 7）。

**评估集合**：`default_text-embedding-v4`（含全部语料）。不得指向分语言集合 —— 中英金标存在跨语言匹配，分语言集合会触发 `chunk_id_validation` 失败。

## Non-goals

- **不做人工从零标注**。48 条 case × 数十候选是数千次人工判断，不现实。本变更的定位是**去掉检索器锚定**，不是达到人工级 ground truth —— 见下条。
- **不声称 LLM 判定等于真相**。它把「某个检索器的排序」换成了「某个 LLM 的相关性判断」。后者的优点是**与检索路径无关**（这正是要修的偏差），缺点是引入了判定模型自身的偏好。判据 3 的人工抽检就是为这个缺点设的闸门，不能因为它麻烦就跳过。
- **不改 `custom_evaluator.py` 的指标公式**。现有四项是二值相关度（`rel_i ∈ {0,1}`）。分级相关度能让 nDCG 更有分辨力，但那是独立变更；本次只把分级数据**存下来**，不改用它计算。
- **不扩容金标条数**。中文只有 6 条（SC-002 要求 ≥ 40）是另一个独立阻塞项。**顺序上必须先修构造方式再扩容** —— 反过来做等于用有偏的方法再生产 40 条。
- **不重跑全部历史基线**。只重标当前需要对比的基线，历史报告标注为「第一代金标」保留。
- **不改 RAGAS 四项**。`ragas__context_recall` 等指标不依赖 `expected_chunk_ids`（它量的是上下文对答案的支撑度），不受本变更影响。
- **不动 `scripts/synthesize_testset.py` / `refine_testset.py`** 的合成与精修逻辑。本变更只替换第三步（回填标签）。
- **不引入新的 LLM provider**。判定模型从 `LLMFactory` 已注册的 provider 里选。
