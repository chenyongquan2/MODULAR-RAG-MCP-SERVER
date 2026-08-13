## Why

重排是本项目检索链路的最后一环，**代码能力完备，运行能力为零**：`sentence-transformers` 从未出现在 `pyproject.toml`，`config/settings.yaml` 是 `backend: none` + `model: ""`，真实的 Cross-Encoder 模型从未被加载过一次。现有 4 个 rerank 单元测试全部通过依赖注入喂 mock 模型，对「依赖是否可用、真实模型能否加载」这一层完全无感。

Feature-005 的负面结论把这件事推到了台面上：英文金标上 sparse 任何正权重都会让 hit_rate 下降，说明**融合权重这条路已经走到尽头**，提升检索质量的下一步必须换维度。重排是最直接的那个维度，而它现在是死的。

顺带三处在排查时暴露的缺陷，都属于「看起来可配、实际不起作用」这一类（与 Feature-004 修掉的 `getattr(..., "bm25_index_path", default)`、`GLMLLM` 不传 timeout 同源）：

1. **`rerank.top_m` 是死配置** —— 全仓只有三处引用：[settings.py:172](../../../src/core/settings.py) 定义、[config_service.py:124](../../../src/observability/dashboard/services/config_service.py) 展示给 dashboard、一个单元测试传值。[reranker.py:88](../../../src/core/query_engine/reranker.py) 把**全部**候选转 dict 交给后端，从不按 `top_m` 截断。今天撞不到上限（融合后最多 40 条 < 50），但它是 `llm` 后端唯一能挡住 token 爆炸的旋钮，必须真的生效。
2. **超时机制根本不存在** —— 不是「死代码」。[docs/learning/rerank-and-cross-encoder.md](../../../docs/learning/rerank-and-cross-encoder.md) §6.4 说 `CrossEncoderReranker.__init__` 存了 `self.timeout`、`_score_pairs()` 里没有超时检查、`CoreReranker.config.timeout` 从未被使用 —— 对着当前代码 grep，`src/libs/reranker/` 与 `src/core/query_engine/reranker.py` 里**一个 `timeout` 字样都没有**，文档描述的那些成员全不存在。该文档段落需要一并更正。
3. **配置错误被当成运行期故障静默吞掉** —— [cross_encoder_reranker.py:222](../../../src/libs/reranker/cross_encoder_reranker.py) 的 `except ImportError` 分支把「依赖没装」降级成返回原序 + `reranked_by: "none"`。这与硬约束 3（快速失败校验）冲突：用户明确配了 `backend: cross_encoder`，得到的却是一次不报错的普通检索。

## What Changes

- **依赖声明**：`pyproject.toml` 新增 optional extra `[rerank]`，内含 `sentence-transformers`。不进核心 `dependencies` —— 它会拖 `torch`（CPU 版通常 200MB+），核心安装不该为一个默认关闭的能力付这个代价。**光装不声明等于没修**，这是根因所在。
- **默认模型改为 `BAAI/bge-reranker-base`**：278M 参数、约 1.1GB 权重、基于 XLM-RoBERTa 的中英双语模型。当前代码里的兜底默认值 `cross-encoder/ms-marco-MiniLM-L-6-v2` 是纯英文 MS MARCO 模型，对本项目一半语料（中文 MT5 文档）无效。**本地推理，零 token**，与 `llm` 后端的成本模型完全相反。
- **`rerank.top_m` 变成真配置**：Core 层在把候选交给后端之前按 `top_m` 截断，超出部分保持原序追加在重排结果之后（不丢结果，只是不参与重排）。
- **新增 `rerank.timeout_sec` 并实现兜底**：Cross-Encoder 是本地同步推理，不能像 HTTP 那样靠 client 参数超时，需要分批推理 + 批间检查已耗时的机制。超时时保留已算出的部分排序、未评分部分保持原序追加。
- **区分「配置错误」与「运行期故障」**：`backend: cross_encoder` 但 `sentence-transformers` 不可用 → `load_settings()` 期抛 `ValueError`（快速失败）；模型已加载后的推理异常 → 保留现有降级行为（检索链路不能因重排失败而整体不可用）。
- **补集成测试**：`tests/integration/` 下新增真实模型加载与打分的测试，标 `integration` marker，不进 `pytest tests/unit` 默认路径。现有 4 个单元测试的 mock 断言不动。
- **跑三组 A/B 并实测延迟**：`none` / `cross_encoder` / `llm` 在本项目语料上的真实增益，以及 CPU 上的真实延迟。用实测数字替换 rerank 学习文档里全部标了【推算】的延迟估计（该文档自己声明「可能偏差 2–3 倍」）。
- **`settings.yaml` 默认仍为 `backend: none`**：本次只让这条路径「能真实跑通」，不改变默认行为。既有中英金标基线全部是无重排产出的，改默认会让后续 delta 无法与历史对比。A/B 数据出来后再单独一行配置切换。

## Capabilities

### New Capabilities

- `retrieval/rerank`: 检索结果重排能力 —— 后端选择与可用性校验、候选数上限、超时兜底、失败降级语义、可观测性打点。这是 `openspec/specs/` 下的第一份规格（此前 001-005 的规格冻结在 Spec-Kit 的 `specs/` 目录，按约定不迁移）。

### Modified Capabilities

无。`openspec/specs/` 目前为空，不存在需要修改的既有规格。

## Impact

**配置与依赖**
- `pyproject.toml` —— 新增 `[project.optional-dependencies] rerank`
- `config/settings.yaml` —— `rerank` 段填 `model`、新增 `timeout_sec`；`backend` 保持 `none`
- `src/core/settings.py` —— `RerankSettings` 新增 `timeout_sec` 字段与 `load_settings()` 期校验

**代码**
- `src/core/query_engine/reranker.py` —— `top_m` 截断、超时编排、截断/超时余量的回填
- `src/libs/reranker/cross_encoder_reranker.py` —— 默认模型名、分批推理以支持超时检查、`ImportError` 语义调整
- `src/observability/dashboard/services/config_service.py` —— 暴露新增的 `timeout_sec`

**测试**
- `tests/unit/` —— 新增 `top_m` 截断、超时兜底、配置校验的用例（硬约束 7）
- `tests/integration/` —— 新增真实模型集成测试
- 现有 `test_cross_encoder_reranker.py` / `test_llm_reranker.py` / `test_reranker_factory.py` / `test_reranker_fallback.py` 的断言不修改（改动若逼得改断言，说明改错了）

**文档**
- `docs/learning/rerank-and-cross-encoder.md` —— 更正 §6.4 的事实错误、用实测数字替换 §10.3 全部【推算】、更新 §10.2 待办清单状态
- `CLAUDE.md` —— rerank 从「未实现」变为「可选能力，需 `pip install -e ".[rerank]"`」

**运行环境**
- 首次加载模型需能访问 HuggingFace 下载权重（国内需 `HF_ENDPOINT` 镜像），落盘后完全离线可用。这是唯一的外网依赖，且只发生一次。

## 验收判据

**评估集合**：`default_text-embedding-v4`（1024 维，含全部语料）。**不得**指向 `mt5_docs_chinese` / `mt5_docs_english` —— 中英金标存在跨语言匹配，分语言集合会触发 `chunk_id_validation` 失败。

**金标**：`tests/fixtures/golden_test_set_en.json`（42 条）与 `golden_test_set_zh.json`。

**判定指标**：以 `custom__mrr` 与 `custom__ndcg` 为主。**不以 `custom__recall` / `custom__hit_rate` 判定成败** —— `backfill_chunk_ids.py` 用纯 dense 检索回填 `expected_chunk_ids`（无 BM25、无融合），这两项结构性地偏向 dense，任何重排挪动名次都可能无理由地拉低它们。RAGAS 四项作为参考观察，不作为门槛（Judge LLM 有 3-10% 系统性波动）。

**「跑通」的判据不是分数，是可观测性**：trace 中出现 rerank stage 且 `fallback: false`、`reranked_by: "cross_encoder"`、`model` 字段是真实模型名。这是判别静默降级的可靠信号 —— 分数变化可能来自任何环节，只有 trace 能证明重排真的执行了。**即使 A/B 显示重排无增益，本变更依然成立**：目标是让这条路径从「从未运行」变为「可测量」，负面结论也是结论（与 Feature-005 同理）。

## Non-goals

- **不改默认 `rerank.backend`**。本次交付后默认仍是 `none`。是否切换取决于 A/B 数据，是下一个决策，不在本变更内。
- **不重标金标基线**。默认行为不变，既有基线继续有效。
- **不做 GPU 加速 / 模型量化 / ONNX 导出**。先拿到 CPU 基准延迟，优化是有数据之后的事。
- **不实现 rerank 结果缓存**。评估会反复跑同一批 query，缓存有真实价值，但它是独立能力，会掩盖本次要测的真实延迟。
- **不做 `llm` 后端的并发化**。它现在是 40 次串行网关调用，慢且贵；本次只让 `top_m` 能挡住它，不优化其架构 —— 因为结论大概率是不用它。
- **不碰 Query Rewriting / Query Planning**。Feature-005 的结论同时指向了它们，但那是另一个变更，且边界尚未划清。
- **不引入新的 reranker provider**（Cohere / Jina 等云端重排 API）。`DEV_SPEC.md:92` 提到的 Cohere 是从未实现的愿景，保持原样。
- **不修 `docs/learning/rerank-and-cross-encoder.md` 之外的文档陈旧问题**（DEV_SPEC.md 进度表、rag-acceptance-plan.md 的 Step 1/2/3、agentic-retrieval-boundary.md 的待办清单都已陈旧，但与本变更无关）。
