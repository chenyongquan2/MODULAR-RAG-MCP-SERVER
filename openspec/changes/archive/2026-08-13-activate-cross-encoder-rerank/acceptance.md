# 验收记录 —— activate-cross-encoder-rerank

**日期**：2026-08-13　**分支**：`dev-from-clean-start`

## 一、一句话结论

cross-encoder 重排从「代码完备、运行为零」变成了**可运行、可观测、可测量**，三处死配置/死代码被清掉；但 A/B 显示在本项目金标上是**负增益**，因此 `settings.yaml` 默认保持 `backend: none`。

**这不是失败**。proposal 把「跑通」的验收信号定为 trace 而非分数，正是为了这种情况：目标是让这条路径从「从未运行」变为「可测量」，负面结论也是结论。而且下面 § 五 会说明，这个「负增益」很可能是评估装置的偏差而非重排的性质。

## 二、A/B 结果

**配置**：集合 `default_text-embedding-v4`、`backends: [custom]`（临时停用 ragas）、`--no-generate-answers`、`fusion_weights: {dense: 1.0, sparse: 0.1}`、`rerank.model: BAAI/bge-reranker-base`、`top_m: 50`、`batch_size: 8`。

### 英文金标（42 条）

| 指标 | `none` | `cross_encoder` | delta |
|---|---|---|---|
| **`custom__mrr`**（主判据） | 0.4914 | **0.3668** | **−0.1246** |
| **`custom__ndcg`**（主判据） | 0.4182 | **0.3373** | **−0.0809** |
| `custom__hit_rate` | 0.6905 | 0.6905 | 0.0000 |
| `custom__recall` | 0.4571 | 0.4190 | −0.0381 |

`run_id`：`12b1c44a-7212-4705-ac55-8fb81ba5a2f3`（none）/ `fbf9f4fd-8d00-4a3c-9d0d-b92f2d0794ae`（cross_encoder）

> 基线复现验证：`none` 组的 `hit_rate` 69.05% 与 CLAUDE.md 记录的 69.0% 吻合，说明基线可信、对比有意义。

### 中文金标（6 条）

| 指标 | `none` | `cross_encoder` | delta |
|---|---|---|---|
| `custom__mrr` | 0.5833 | 0.4167 | −0.1666 |
| `custom__ndcg` | 0.3193 | 0.3073 | −0.0120 |
| `custom__hit_rate` | 0.6667 | 0.5000 | −0.1667 |
| `custom__recall` | 0.2667 | **0.3000** | **+0.0333** |

`run_id`：`4bef0ef9-51fd-4d1a-bc9c-9c6e5fad3b46` / `b14daf8f-d6ef-4fb1-9cf7-57d11586cb98`

⚠️ **n=6，基本是噪声**。中文金标只有 6 条（settings.yaml 注释里也写着「小样本验证用，完整 SC-002 验收需要 ≥ 40/language」），不足以支撑任何结论。

### `llm` 组未跑

每查询约 40 次串行网关调用 × 48 条金标 ≈ 1920 次调用、1.5–3M input token、30+ 分钟。与本变更「让 cross_encoder 跑通」的目标不成比例，且结论大致可预见（慢、贵、不可复现，作为评测基线不合格）。`top_m` 已经给它装上了刹车，需要时再跑。

## 三、延迟实测

测量环境：AMD Zen 3（Family 25 Model 116）、Python 3.12、`batch_size=8`、**真实语料 chunk（中位 428 字符）**。

| 候选数 | 中位耗时 | 每候选 |
|---|---|---|
| 10 | 1.21 s | 121 ms |
| 20 | 2.51 s | 125 ms |
| **40**（生产实际：`top_k_dense` 20 + `top_k_sparse` 20） | **5.21 s** | 130 ms |
| 50（`top_m` 上限） | 7.33 s | 147 ms |

其他实测值：权重 **1081.8 MB**；首次下载经 `hf-mirror.com` **493 s**（一次性）；`import sentence_transformers` 冷启动 **44.5 s**；进程内首次模型加载（权重已缓存）**11–22 s**。

评估实测的增量约 **1.74 s/query**（42 条：51 s → 135 s，扣除 11 s 模型加载），反推出融合后平均只有约 13 条候选到达重排 —— dense 与 sparse 的召回重叠度很高。

**依赖增量只有约 9 MB**（4 个包）。`torch 2.12.0` 早已由核心依赖 `docling` 经 `docling-ibm-models` 拉入，不是重排引入的。

## 四、被证伪的前提（三处）

规划阶段写进 proposal/design 的三个判断，实施时被证据推翻：

| 原判断 | 实际 | 影响 |
|---|---|---|
| 「sentence-transformers 会拖 torch，CPU 版 200MB+」（design D1 理由） | **错**。torch 已在 venv 里，增量只有 9 MB。`docs/learning/rerank-and-cross-encoder.md` §10.2 原始估计「新增 4 包约 9 MB」完全正确，是我怀疑错了 | 结论不变（仍用 extra），但理由换成「默认关闭的能力显式 opt-in」 |
| 「rerank 的 timeout 是死代码」（引自学习文档 §6.4） | **错**。`src/libs/reranker/` 与 core reranker 里一个 `timeout` 字样都没有，文中提到的 `self.timeout` / `_score_pairs()` / `CoreReranker.config.timeout` 全不存在 —— 不是「配了不生效」而是**从未实现** | 从「修接线」变成「从零设计机制」，工作量与设计难度都上升 |
| 「启动期探测让 `except ImportError` 分支不可达，应删除」（design D7） | **错**。`probe_backend` 用 `find_spec`，只证明模块**找得到**、不执行模块。装坏了的依赖（Windows 上 torch DLL 加载失败）会通过探测但在真正 import 时抛 ImportError | 撤回删除决定。两个分支互补：前者挡「没装」，后者兜「装了但坏了」 |

另外两处成本判断在实施中纠正：`evaluation.backends` 实际是 `[custom, ragas]`（我 grep 时上下文不足，误判成 custom-only），所以每轮评估本来会烧 Judge LLM + 答案生成；以及前几次「评估卡死」的判断有一半是 stdout 全缓冲造成的假象，加 `-u` 才看到它一直在正常推进。

## 五、最重要的发现：金标无法公正评判重排

**证据矛盾**：

- 集成测试里把相关段落故意放在**末位**（原始分数最低），重排**每次都能把它提到首位** —— 中文、英文、跨语言三组判据全部通过
- 同一个模型在金标上让 MRR 掉了 0.12

**原因**：金标的 `expected_chunk_ids` 是 [`backfill_chunk_ids.py`](../../../scripts/backfill_chunk_ids.py) 用**纯 dense 检索 top-5** 回填的 —— 标准答案本身就是「embedding 模型认为最相关的那几条」。而重排的全部工作就是**不同意第一阶段的排序**。任何有效的重排器都会因为「敢于改变名次」而被这套金标扣分。

这比 CLAUDE.md 已记录的偏差更严重。已记录的说法是「`recall` / `hit_rate` 偏向 dense，比较混合与单路时看 `MRR` / `nDCG` 更可信」。**但那条只适用于 dense-vs-sparse 的路径比较**：对重排而言，四项指标**全都**是 dense-anchored 的，`MRR` / `nDCG` 并不比 `recall` / `hit_rate` 更中立。我在 proposal 里把 MRR/nDCG 定为主判据，就是踩了这个坑。

**这意味着**：在换掉金标构造方式之前，本项目**没有任何可用于评判重排的离线指标**。Feature-005 的验收记录早已把「金标 `expected_chunk_ids` 的构造方式」列为「比调权重更根本的改进」—— 这次的结果是同一个问题的第二次、且更强的一次撞击。

## 六、变更规模

**新增**
- `pyproject.toml`：optional extra `[rerank]`
- `src/core/settings.py`：`RerankSettings.timeout_sec` / `batch_size`、`VALID_RERANK_BACKENDS`、`_validate_rerank_settings`、`_probe_rerank_backend`
- `src/libs/reranker/reranker_factory.py`：`probe_backend` + `_BACKEND_REQUIREMENTS`
- `src/libs/reranker/base_reranker.py`：`supports_batch_scoring` / `score_batch`（optional 能力）
- `src/core/query_engine/reranker.py`：`_rerank_with_timeout` / `_describe_backend` / `_describe_model`
- 测试：`test_settings_rerank.py`(51) / `test_reranker_probe_backend.py`(21) / `test_reranker_top_m.py`(20) / `test_reranker_timeout.py`(20) / `test_reranker_trace.py`(20) / `test_reranker_batch_scoring.py`(21) / `tests/integration/test_cross_encoder_rerank_real_model.py`(15)

**改动**
- `config/settings.yaml`：rerank 段（`backend` 仍 `none`）
- `src/libs/reranker/cross_encoder_reranker.py`：删模型名隐式兜底、`batch_size` 配置化、错误消息区分依赖缺失与权重获取失败、新增 `score_batch`
- `src/libs/reranker/llm_reranker.py`：新增 `score_batch`（让 `llm` 后端也受超时保护）
- `src/core/query_engine/reranker.py`：`top_m` 截断 + 余量回填、重排分数写进 metadata
- `src/observability/dashboard/services/config_service.py`：暴露 `timeout_sec` / `batch_size`
- `docs/learning/rerank-and-cross-encoder.md`：§6.4 事实更正、§7.2 实测延迟、§10.1–10.3 状态更新

**测试**：`pytest tests/unit` **1648 passed, 2 skipped**（新增约 155 个用例）；集成 15 passed。

**四个受保护测试文件的断言零修改**（`git diff` 过滤 assert 行为空）。只改了两处 fixture 构造（裸 `Mock()` → 真实 `RerankSettings` dataclass，因为代码现在真的读这些字段）和一个坏测试的缺失模拟。

## 七、遗留事项

| 项 | 状态 |
|---|---|
| `llm` 后端的 A/B | 未跑。约 1920 次串行网关调用，需要时单独安排 |
| RAGAS 四项在重排前后的对比 | 未跑。需网关稳定时进行（本次实测到 embedding 超时与 RAGAS `TimeoutError`） |
| 中文金标扩容到 ≥ 40 条 | **前置阻塞项**。现在 6 条，任何中文侧结论都不成立 |
| 金标 `expected_chunk_ids` 改为人工标注答案边界 | **本次最重要的遗留**。见 § 五 —— 不解决它，重排（以及任何敢改变名次的改进）都无法被离线评估 |
| 是否默认开启 `cross_encoder` | **不开**。等金标问题解决后重新评估 |
| 跨语言压分的缓解（按语言过滤候选 / 换多语对齐更好的模型） | 未做，不在本次范围 |
| `scripts/evaluate.py` 与 `scripts/query.py` 都不写 query trace | 本次发现的独立缺口。只有 MCP server 路径写 `traces.jsonl`，导致延迟只能靠专门的基准脚本量 |
| `logs/evaluation_reports/` 的 pytest 污染 | 本次再次观察到（跑单元测试会写入归档目录）。仍是独立待办 |
