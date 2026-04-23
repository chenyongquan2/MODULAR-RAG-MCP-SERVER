# RAGAS 执行与调优实战手册（Playbook）

> **文档性质**：RAGAS 评估的实战工作流手册，2026-04-23 创建。
> **与已有文档的关系**：
> - [docs/ragas-guide.md](ragas-guide.md) 侧重**指标原理与 CLI 参考**
> - [docs/rag-acceptance-plan.md](rag-acceptance-plan.md) 侧重**一次性验收的项目方案**
> - **本文档**侧重**日常"跑→看→调→回归"的执行循环**，适合反复翻阅
> **目标读者**：需要反复跑 RAGAS 做 RAG 调优的开发者。

---

## 0. 核心问题

> 如何跑 RAGAS？主要观察哪些基线指标？如何根据指标进行调整？

**本文档的三个主线**：
1. **怎么跑**（§1 完整工作流）
2. **看什么**（§2 八个关键指标的分层解读）
3. **怎么调**（§3-§4 调优决策表 + 实战案例）

---

# 一、跑 RAGAS 的完整工作流

## 1.1 一次标准评估的四个动作

```
准备配置 → 执行评估 → 读取报告 → 定位问题 → 调整 → 回归
   ↓         ↓          ↓          ↓        ↓      ↑
  5 分钟   1-10 分钟    5 分钟    15 分钟   视情况  循环
```

## 1.2 第一次跑 RAGAS：烟雾测试（最重要）

**目标**：用最少成本验证"链路是通的"，而不是拿正式分数。

### 步骤 1 — 开启 RAGAS backend

编辑 [config/settings.yaml](../config/settings.yaml) 的 evaluation 章节：

```yaml
evaluation:
  backends:
    - custom
    - ragas           # ← 解除注释
  golden_test_set: ./tests/fixtures/golden_test_set.json
```

### 步骤 2 — 配置 Judge LLM（GLM-4）

在 `.env` 中配置 GLM 的 OpenAI 兼容端点（RAGAS 默认从 `OPENAI_API_KEY` 读取）：

```bash
OPENAI_API_KEY=your_glm_api_key
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
```

### 步骤 3 — 把现有 golden set 的 chunk_id 换成真实 ID

[tests/fixtures/golden_test_set.json](../tests/fixtures/golden_test_set.json) 里 `expected_chunk_ids` 是 `chunk_azure_001` 这种占位符，**必须换成 ChromaDB 里真实存在的 UUID**，否则 Hit Rate 会永远是 0。

查真实 chunk_id 的办法：
```bash
python scripts/query.py --query "你知道的任何问题" --top-k 5
```
从输出的 `chunk_id` 字段里挑一个，回填到 golden set。

### 步骤 4 — 跑一次完整评估

```bash
python scripts/evaluate.py --generate-answers --pretty
```

`--generate-answers` 会走真实的 `ResponseBuilder` 生成 answer，`faithfulness` 和 `answer_relevancy` 才有值。

### 烟雾测试成功标准

- ✅ 8 个 `aggregate_metrics` 字段都有**非零非 NaN** 数值
- ✅ 没有 `ValueError: contexts must be a list of non-empty strings`
- ✅ 没有 `ImportError: ragas`
- ✅ 单条结果里 `contexts` 字段是**可读文本**（项目 commit `7a87eec` 已修过这个坑）

---

## 1.3 两种常用的执行模式

| 场景 | 命令 | 耗时 | 成本 |
|---|---|---|---|
| **日常开发**（改 splitter/embedding/top_k 后快速验证） | `python scripts/evaluate.py --no-generate-answers --pretty` | 秒级 | 0 |
| **发版前完整评估**（或正式验收） | `python scripts/evaluate.py --generate-answers --pretty > logs/eval_$(date +%F).json` | 1-10 分钟 | 每条 ~¥0.01-0.05 |

**核心区分**：
- `--no-generate-answers` → 只跑 custom 的 Hit/MRR/Recall/NDCG，零 LLM 成本
- `--generate-answers` → 跑完整 RAGAS 4 指标，消耗 judge LLM 额度

---

# 二、观察哪些基线指标（8 个全家福）

跑完后 `aggregate_metrics` 里会有 8 个关键字段：

```json
{
  "aggregate_metrics": {
    "custom__hit_rate":         0.75,  // ① 检索 - 是否命中
    "custom__mrr":              0.58,  // ② 检索 - 排名是否靠前
    "custom__recall":           0.80,  // ③ 检索 - 覆盖率（commit a999a20 新增）
    "custom__ndcg":             0.72,  // ④ 检索 - 排序质量（新增）
    "ragas__context_precision": 0.82,  // ⑤ 检索 - 精确率（LLM judge）
    "ragas__context_recall":    0.78,  // ⑥ 检索 - 召回率（LLM judge）
    "ragas__faithfulness":      0.87,  // ⑦ 生成 - 防幻觉
    "ragas__answer_relevancy":  0.91   // ⑧ 生成 - 答非所问
  }
}
```

## 2.1 分层理解这 8 个指标

```
┌───────────────────────────────────────────────────────┐
│ 🟦 检索层（6 个指标）                                    │
│   ├─ chunk ID 级（custom，免费快速）                   │
│   │    ├─ hit_rate   ：top-K 有没有至少 1 个命中         │
│   │    ├─ mrr        ：第一个命中的 chunk 排第几         │
│   │    ├─ recall     ：该召回的都召回了吗               │
│   │    └─ ndcg       ：考虑排序质量的召回率             │
│   └─ 语义级（ragas，LLM judge）                        │
│        ├─ context_precision ：相关片段是否排在前面       │
│        └─ context_recall    ：ground_truth 知识点被覆盖吗│
├───────────────────────────────────────────────────────┤
│ 🟨 生成层（2 个指标，只有 ragas）                        │
│   ├─ faithfulness     ：answer 有没有胡编               │
│   └─ answer_relevancy ：answer 有没有答到点上            │
└───────────────────────────────────────────────────────┘
```

## 2.2 基线门槛参考（行业经验值）

| 指标 | 🔴 差 | 🟡 合格 | 🟢 良好 | 🟢🟢 优秀 |
|---|---|---|---|---|
| `custom__hit_rate` | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| `custom__mrr` | <0.3 | 0.3-0.5 | 0.5-0.7 | >0.7 |
| `custom__recall` | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| `custom__ndcg` | <0.4 | 0.4-0.6 | 0.6-0.8 | >0.8 |
| `ragas__context_precision` | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| `ragas__context_recall` | <0.5 | 0.5-0.7 | 0.7-0.85 | >0.85 |
| `ragas__faithfulness` | <0.6 | 0.6-0.75 | 0.75-0.9 | >0.9 |
| `ragas__answer_relevancy` | <0.7 | 0.7-0.8 | 0.8-0.9 | >0.9 |

## 2.3 关键认知：成对看，不单看

这是新手最容易犯的错——**盯着一个指标调参**。正确方法是**成对诊断**：

### 诊断矩阵 A：hit_rate × context_recall

| `custom__hit_rate` | `ragas__context_recall` | 判断 |
|---|---|---|
| 高 | 高 | 检索完美 ✅ |
| 高 | 低 | chunk 命中了但覆盖不全 → **chunk_size 太小**，关键信息被切碎 |
| 低 | 高 | 期望的 ID 对不上但语义覆盖到了 → **expected_chunk_ids 过时**（换了 splitter 后没更新）|
| 低 | 低 | 检索真的差 → 动 embedding / splitter / top_k |

### 诊断矩阵 B：context_recall × faithfulness

| `ragas__context_recall` | `ragas__faithfulness` | 判断 |
|---|---|---|
| 高 | 高 | 全链路 OK ✅ |
| 高 | 低 | **检索对了但生成器胡编** → 改 prompt，强制"基于上下文回答" |
| 低 | 高 | 生成器克制但无料可用 → 先修检索 |
| 低 | 低 | 先修检索（生成器没弹药也白搭）|

### 诊断矩阵 C：faithfulness × answer_relevancy

| `ragas__faithfulness` | `ragas__answer_relevancy` | 判断 |
|---|---|---|
| 高 | 高 | 生成完美 ✅ |
| 高 | 低 | **说的都对但没答到问题点** → query 被曲解（查 QueryProcessor）或 prompt 跑题 |
| 低 | 高 | 答得很"相关"但在编 → 更严重，立刻改 prompt 或换更严谨模型 |

---

# 三、如何根据指标调整

## 3.1 问题定位 → 行动清单（对照表）

| 症状 | 根本原因 | 调整位置 | 具体动作 |
|---|---|---|---|
| `hit_rate` 低 | 向量召回不准 | embedding / splitter | 1. 换更强 embedding（如 bge-large-zh-v1.5）<br>2. 检查 chunk_size 是否合理<br>3. 开启 hybrid 检索（dense+sparse）|
| `mrr` 低但 `hit_rate` 高 | 命中了但排名靠后 | reranker / fusion | 1. `rerank.backend` 从 `none` 改 `cross_encoder`<br>2. 调 RRF 权重 `fusion.rrf_weight_dense`<br>3. 提高 `retrieval.top_k_rerank` |
| `context_precision` 低 | 检索结果噪声大 | top_k / reranker | 1. 调小 `retrieval.top_k_final`（如 10→5）<br>2. 必开 reranker<br>3. 改 splitter 策略（chunk 太长会稀释相关性）|
| `context_recall` 低 | 检索漏召回 | top_k / splitter / hybrid | 1. 调大 `retrieval.top_k_final`<br>2. chunk_size 减小（关键信息被大 chunk 稀释）<br>3. 开启 BM25 稀疏检索 |
| `faithfulness` 低 | 生成器幻觉 | prompt / LLM | 1. prompt 加约束：「严格基于上下文回答，没有依据时回答"文档未涉及"」<br>2. 换更严谨的 LLM（如 deepseek-chat → GLM-4）<br>3. 降 LLM `temperature`（设 0 或 0.1）|
| `answer_relevancy` 低 | 答非所问 | prompt / QueryProcessor | 1. prompt 加「直接回答问题，不要发散」<br>2. 检查 QueryProcessor 是否改写得离谱<br>3. 给 prompt 加 few-shot 示例 |

## 3.2 调整的正确顺序（自底向上）

不要随意调各层，有**严格的先后次序**：

```
① 先修检索（custom + context_recall/precision）
       ↓
② 检索没问题后再看生成（faithfulness + answer_relevancy）
       ↓
③ 生成没问题后再考虑 prompt 工程
       ↓
④ prompt 也没问题才考虑换模型
```

**原因**：检索不准时，改 prompt 和换模型都是徒劳——LLM 手里是垃圾弹药，再好的枪也没用。

## 3.3 每次只调一个变量

**严格遵守**：
- ❌ 不要一次同时改 chunk_size + top_k + reranker
- ✅ 改一个 → 重跑 RAGAS → 看 delta → 接受或回滚

**为什么**：如果一次改 3 个参数指标上升了，你不知道是哪一个带来的收益；下次再调时就没有依据。

### 推荐的实验节奏

```
commit baseline.json (基线)
  ↓ 只改 chunk_size
commit experiment_1.json
  ↓ 和 baseline 对比 delta
  ↓ 收益明显 → 接受；否则回滚
  ↓ 再改下一个参数
commit experiment_2.json
```

## 3.4 用 Dashboard 管理基线对比

```bash
python scripts/start_dashboard.py
```

进入**评估面板**，操作：
1. 跑一次评估 → 点 **"Mark as Baseline"**
2. 调完参数重跑 → Dashboard 自动对比，显示 `delta_aggregate_metrics`
3. 正向 delta → 保留改动；负向 → 回滚

这是项目架构里 [evaluation_service.py](../src/observability/dashboard/services/evaluation_service.py) 的 `mark_as_baseline` 的核心价值——**让"每次改动都能量化衡量"**。

---

# 四、一个完整的调优案例

假设你第一次跑出来的指标是：

```json
{
  "custom__hit_rate":         0.60,  🟡
  "custom__mrr":              0.35,  🟡
  "ragas__context_recall":    0.55,  🟡
  "ragas__context_precision": 0.45,  🔴
  "ragas__faithfulness":      0.88,  🟢
  "ragas__answer_relevancy":  0.75   🟡
}
```

## 4.1 诊断过程

1. `context_precision` 最差（0.45）→ 检索排序问题
2. `hit_rate` 和 `recall` 都一般 → 召回也不完美，但不是主要矛盾
3. `faithfulness` 高 → 生成器没问题，不用动 LLM 和 prompt
4. `answer_relevancy` 一般 → 大概率被 `context_precision` 低拖累

## 4.2 行动顺序

| 次序 | 动作 | 预期效果 |
|---|---|---|
| 1 | 打开 `rerank.backend: cross_encoder` | `context_precision` ↑、`mrr` ↑ |
| 2 | 重跑评估，确认有收益 | - |
| 3 | 若 `context_recall` 还低，调 `retrieval.top_k_final: 5 → 10` | `recall` ↑（代价：可能 `precision` 略降，但有 reranker 保底）|
| 4 | 再跑评估，对比基线 | - |

## 4.3 不要做的事

- ❌ 同时开 reranker + 改 top_k + 换 embedding（变量太多无法归因）
- ❌ 看到 `answer_relevancy` 一般就立刻改 prompt（真实瓶颈在检索）
- ❌ 因为 `faithfulness` 已经 0.88 就不再关注它（后面改检索后要确认它没回退）

---

# 五、长期维护的黄金法则

1. **每次 Ingest / 模型 / 参数变更都跑一次 RAGAS**，新增一条基线记录
2. **Golden Set 持续扩充**：用户反馈（👎 的查询）→ 回填成新的测试用例
3. **关注趋势，不纠结单次绝对值**：RAGAS 有 LLM 温度带来的 ±0.02-0.05 波动
4. **CI/CD 门禁**：把 RAGAS 跑进 CI，指标低于阈值 block merge（示例在 [docs/ragas-guide.md](ragas-guide.md) §7 Q6）
5. **多部门场景**：每部门独立 golden set + 独立基线（见 [docs/enterprise-multi-tenant-deployment.md](enterprise-multi-tenant-deployment.md) §7）

---

# 六、调优速查图

```
开始调优时问自己三个问题：
  1. 哪个指标最差？          → 确定诊断起点
  2. 对应的上游指标怎么样？   → 判断是本层问题还是上游传导
  3. 我要改的这个变量，会不会同时影响别的指标？  → 决定回归范围
```

## 问题定位流程图

```
跑出指标报告
    │
    ▼
哪个指标最差？
    │
    ├─ hit_rate / recall 差  ────▶  动检索层（embedding, splitter, top_k, hybrid）
    │
    ├─ context_precision 差 ─────▶  动排序层（reranker, fusion 权重）
    │
    ├─ faithfulness 差       ────▶  动生成层（prompt 约束, LLM 严谨度）
    │                                 ⚠️ 先确认 context_recall 是否正常
    │
    └─ answer_relevancy 差   ────▶  动 query 理解（QueryProcessor, prompt 聚焦）
                                      ⚠️ 先确认 context_precision 是否正常
```

---

# 七、关联文档导航

| 要做的事 | 读哪份文档 |
|---|---|
| 理解 RAGAS 指标原理、CLI 参数详情 | [docs/ragas-guide.md](ragas-guide.md) |
| 一次性完整验收（从零到基线） | [docs/rag-acceptance-plan.md](rag-acceptance-plan.md) |
| **日常调优循环的执行手册** | **本文档** |
| 多部门企业部署架构 | [docs/enterprise-multi-tenant-deployment.md](enterprise-multi-tenant-deployment.md) |
| 项目整体架构 | [CLAUDE.md](../CLAUDE.md) |
