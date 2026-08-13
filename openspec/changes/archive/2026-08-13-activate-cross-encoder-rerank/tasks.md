> 全部命令在 `.venv` 下运行。每条任务 = 一次 `pytest tests/unit -v` 全绿的提交，commit message 引用任务号（如 `refs T-2.1`）。

## 1. 依赖与前置验证

- [x] 1.1 `pyproject.toml` 新增 `[project.optional-dependencies] rerank`（含 `sentence-transformers`），`pip install -e ".[rerank]"` 安装，然后**实测 `BAAI/bge-reranker-base` 能否被 `CrossEncoder(model_name)` 加载并对一组中英混合的 (query, passage) 打出可排序的分数**。这是 design § Risks 里唯一未验证的前提，不通过则按 design 回落到 `bge-reranker-large` 或 `v2-m3` 并更新 design D2。同时记下实际权重体积与首次下载耗时，供 6.2 使用

## 2. 配置层（快速失败）

- [x] 2.1 `src/core/settings.py`：`RerankSettings` 新增 `timeout_sec` / `batch_size` 字段；`load_settings()` 新增校验 —— `backend` 白名单、`backend != none` 时 `model` 非空、`top_m` / `timeout_sec` / `batch_size` 均 > 0，违规抛 `ValueError`。配套 `tests/unit/` 用例覆盖每条校验的通过与拒绝两侧
- [x] 2.2 `src/libs/reranker/reranker_factory.py`：新增 `probe_backend(name) -> None`，不可用时抛 `ValueError` 并带上可执行的安装命令；`load_settings()` 的 rerank 校验段调用它。错误消息必须能区分「依赖缺失」与「权重获取失败」两种原因（后者提示 `HF_ENDPOINT` 镜像）。**具体库名只出现在 factory 与 libs 层，`src/core/` 不得 import `sentence_transformers`**（硬约束 1）。配套单测，用 monkeypatch 模拟依赖缺失
- [x] 2.3 `config/settings.yaml` 的 `rerank` 段按 design § 新增配置项 更新（**`backend` 保持 `none`**，`model` 留空并在注释里写明推荐值与零 token 性质）；`src/observability/dashboard/services/config_service.py` 暴露 `timeout_sec` / `batch_size`。配套更新 `tests/unit/observability/dashboard/test_config_service.py`

## 3. Core 编排层

- [x] 3.1 `src/core/query_engine/reranker.py`：实现 `top_m` 截断 —— 只把前 `top_m` 条交给后端，超出部分按原名次追加在重排结果之后（不丢结果）。配套单测覆盖「超过上限」「未超过上限」「恰好等于上限」三种情形，断言总条数不减少且余量顺序正确
- [x] 3.2 超时兜底：后端提供分批打分入口，Core 层每批之后用 `time.monotonic()` 检查累计耗时，超过 `timeout_sec` 就停止后续批次，已评分部分按分数排序、未评分部分按原名次追加。**超时不得抛异常、不得丢候选**。配套单测用可控的假后端（每批 sleep 固定时长）验证部分结果的边界
- [x] 3.3 trace 打点：rerank 阶段记录后端标识、真实模型名、送入/产出条数、耗时，并用**互不重叠的字段**区分「未启用」「运行期降级」「超时」三态（规格明确要求不能用同一个标记表达多种含义）。配套单测断言三种路径各自的 trace 形态

## 4. libs 后端清理

- [ ] 4.1 `src/libs/reranker/cross_encoder_reranker.py`：删除 `model` 的 `getattr(..., "cross-encoder/ms-marco-MiniLM-L-6-v2")` 隐式兜底（模型名由 2.1 强制显式配置）；`batch_size` / `max_length` 改读配置而非硬编码。**`except ImportError → 降级` 分支保留** —— 原计划删它，理由（「2.2 的探测让它不可达」）已被证伪，见 design D7 的修正说明。运行期 `except Exception → 降级` 同样保持不变

  **测试改动的边界**（原护栏「4 个 rerank 测试文件断言不得修改」按实施发现修订，见 2026-08-13 会话）：
  - **不得触碰**：`test_reranker_fallback.py` 全部，以及 `test_cross_encoder_reranker.py::test_rerank_falls_back_on_import_error` / `test_rerank_falls_back_on_predict_error` —— 这些是降级语义的护栏，护栏的本意就是守住它们
  - **必须修**：`test_model_loading_raises_import_error_if_library_missing` —— 它**从未模拟过「库缺失」**，之所以一直通过只是因为依赖真的没装；装上之后它会去真连 HuggingFace 下载模型（5 次退避重试，让全量跑从常规耗时涨到 428 秒）。补上真正的缺失模拟，断言与意图不变
  - **允许改期望值**：`batch_size == 32` 的两处断言（:105 与 :368）与「改读配置」在语义上不可两全，改期望值是配置化的必然结果，不属于弱化断言

## 5. 集成测试

- [x] 5.1 `tests/integration/test_cross_encoder_rerank_real_model.py`：标 `integration` marker，真实加载 `BAAI/bge-reranker-base`、对真实候选打分、断言 trace 中 `fallback: false` 且模型名为实际加载的模型。依赖或权重不可用时 `pytest.mark.skipif` 跳过。**不进 `pytest tests/unit` 默认路径**。这一条是补上「现有测试全 mock、对装配层无感」这个缺口的正题

## 6. 验收与文档

- [x] 6.1 A/B 三组：在 `default_text-embedding-v4` 集合上，用 `scripts/evaluate.py --pretty --collection default_text-embedding-v4` 分别以 `backend: none` / `cross_encoder` / `llm` 各跑一轮中英金标（`golden_test_set_zh.json` / `golden_test_set_en.json`）。**以 `custom__mrr` 与 `custom__ndcg` 判定，不以 `custom__recall` / `custom__hit_rate` 判定**（期望 chunk_id 是纯 dense 回填的，这两项结构性偏向 dense）。RAGAS 四项仅作参考观察。`llm` 组注意 `top_m` 已生效，记录实际调用次数与 token 消耗
- [x] 6.2 从 `logs/traces.jsonl` 的 rerank 阶段取真实耗时，统计 `cross_encoder` 与 `llm` 两条路径的延迟，**替换 `docs/learning/rerank-and-cross-encoder.md` 中全部标了【推算】的数字**（该文档自己声明可能偏差 2–3 倍），并写明测量环境（CPU 型号、候选条数、batch_size）
- [x] 6.3 文档收口：更正 `rerank-and-cross-encoder.md` §6.4 的事实错误（超时不是「死代码」，而是**从未存在** —— 文中提到的 `self.timeout` / `_score_pairs()` / `CoreReranker.config.timeout` 在代码里都不存在）；更新 §10.2 待办清单十条的状态；`CLAUDE.md` 把 rerank 从「未实现」改为「可选能力，需 `pip install -e ".[rerank]"`，本地推理零 token，默认关闭」；在本变更目录写 `acceptance.md` 记录 A/B 结论（**含负面结论** —— 若重排无增益，如实记录并说明判据为何仍成立）
