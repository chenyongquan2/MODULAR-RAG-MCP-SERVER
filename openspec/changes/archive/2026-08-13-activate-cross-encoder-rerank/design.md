## Context

动机见 [proposal.md](proposal.md) § Why，行为契约见 [specs/retrieval/rerank/spec.md](specs/retrieval/rerank/spec.md)。

设计上需要顶住的现状约束：

- **`Reranker`（Core 层编排）与三个后端（libs 层）已存在且分层正确**。本次不重构分层，只在两层各补缺失的行为。
- **交叉编码器是同步 CPU 推理**，不像 HTTP 客户端那样有现成的超时参数可传。
- **`load_settings()` 位于 `src/core/`，按硬约束 1 不得知道任何具体库名**，所以「依赖是否可用」这个检查不能直接写在 settings 里。
- 现有 4 个 rerank 单元测试全靠依赖注入喂 mock，**它们的断言是本次改动的回归闸门，不得修改**。

## Goals / Non-Goals

范围边界见 proposal § Non-goals。设计层面额外划两条：

- **Goal**：`top_m` 截断与超时兜底都实现在 Core 编排层，一处生效于全部后端。libs 层的后端只负责「能分批打分、能报告自己是否可用」。
- **Non-Goal**：不引入异步。重排在查询链路上是同步阻塞的一环，改成 async 会波及 `HybridSearch` 全链路，收益与本次目标无关。

## Decisions

**D1 · 依赖声明位置**：`pyproject.toml` 的 `[project.optional-dependencies] rerank`。
否掉核心 `dependencies` —— 重排默认关闭，显式 opt-in 更清晰；且既有部署不会因为一次 `git pull` 就自动获得该依赖，D4 的启动期探测对它们是真实保护。

> **T-1.1 实测修正**：本条原先的理由是「会拖 `torch`（CPU 版通常 200MB+）」，**这是错的**。`torch 2.12.0` 早已由核心依赖 `docling`（经 `docling-ibm-models`）拉入 venv，`pip install -e ".[rerank]"` 的实际增量只有 4 个包约 9MB（`sentence-transformers` / `scikit-learn` / `joblib` / `threadpoolctl`）—— 与 `docs/learning/rerank-and-cross-encoder.md` §10.2 的原始估计一致。结论不变（仍用 extra），但不要再用「torch 税」作为论据。

**D2 · 默认模型 `BAAI/bge-reranker-base`**：278M 参数、中英双语，本地推理零 token。**T-1.1 已实测通过**：权重 1081.8 MB，中文 / 英文 / 跨语言三组相关性判据全部正确排序，单 pair 推理 25.0 ms（batch_size=8，40 条候选约 1.0s）。
否掉 `cross-encoder/ms-marco-MiniLM-L-6-v2`（纯英文，对一半语料无效）与 `BAAI/bge-reranker-v2-m3`（CPU 延迟约 2 倍以上，交互式查询等不起）。

**D3 · 消除隐式模型默认值**：`RerankSettings.model` 的 dataclass 默认保持 `""`，改为在 `load_settings()` 校验「`backend != none` 时 `model` 不得为空」。
否掉现有的 `getattr(settings.rerank, "model", "cross-encoder/...")` 兜底写法 —— 它正是 Feature-004 修掉的那类「看起来可配、实际取默认值」的病灶，这次一并删掉，模型名必须在 `settings.yaml` 里显式写出。

**D4 · 可用性探测由 Factory 承担**：`RerankerFactory` 新增类方法 `probe_backend(name) -> None`，不可用时抛 `ValueError` 并带上安装命令；`load_settings()` 的 rerank 校验段调用它。
否掉在 `settings.py` 里直接 `importlib.util.find_spec("sentence_transformers")` —— 那会把具体库名硬编码进 `src/core/`，直接违反硬约束 1。Factory 是唯一允许知道 provider 细节的地方。

**D5 · 超时靠分批推理 + 批间计时**：把候选切成小批（`rerank.batch_size`，默认 8），每批推理完检查 `time.monotonic()` 累计耗时，超限就停止后续批次。
否掉 `signal.alarm`（Windows 不可用、非主线程无效）与工作线程 + join 超时（无法中断 torch 推理，只会泄漏线程并继续吃 CPU）。代价是超时粒度 = 一批的推理时间，所以 `batch_size` 从现有硬编码的 32 降到 8 并变成配置项。

**D6 · 截断与超时的余量回填在 Core 层**：`Reranker.rerank()` 先按 `top_m` 切分，重排结果与余量拼接后返回给 `HybridSearch`，由后者按 `top_k_final` 截断（现有行为不变）。
否掉在各后端内部各实现一遍 —— 三份实现必然漂移，且 `top_m` 语义会因后端而异。

**D7 · 依赖缺失 vs 运行期故障的分界**：`backend != none` 但依赖不可用 → `load_settings()` 期抛 `SettingsError`（D4 的启动期探测）；模型已加载后的推理异常 → 保留降级（检索链路不能因重排失败而整体不可用）。两侧的错误消息必须能相互区分，规格已要求。

> **T-2.2 实施时修正**：本条原先还要求「删除 `CrossEncoderReranker.rerank()` 的 `except ImportError → 降级` 分支，理由是 D4 的启动期探测已让它不可达」。**这个推理是错的，该要求撤回。** `probe_backend` 用 `importlib.util.find_spec`，它只证明模块**找得到**，并不执行模块 —— 装坏了的依赖（Windows 上 torch 的 DLL 加载失败是常见情形）会顺利通过探测，然后在真正 import 时抛 `ImportError`。删掉这个分支会把「装坏了」从一次降级变成未捕获异常，直接打断整条查询。**启动期探测与运行期 ImportError 降级是互补的两层，不是冗余**：前者挡住「没装」这个配置错误，后者兜住「装了但坏了」这个环境故障。两个分支都保留。

**D8 · A/B 复用 `scripts/evaluate.py`**，三次运行分别配 `none` / `cross_encoder` / `llm`，靠既有的 archive + delta vs baseline 机制对比；延迟从 `logs/traces.jsonl` 的 rerank 阶段耗时取。
否掉新写一个 A/B 脚本 —— evaluate.py 已有归档、快照、delta 全套，重复造轮子还会绕开 `acceptance_thresholds_snapshot` 的可追溯性。

**D9 · 集成测试用 skipif 而非 mock**：真实模型 1.1GB，`tests/integration/` 下的新测试标 `integration` marker，并在依赖或权重不可用时 `pytest.mark.skipif` 跳过。
否掉继续用 mock —— 那正是现在这个缺口的成因（现有测试全 mock，对装配层完全无感）。

## 新增配置项

`config/settings.yaml`：

```yaml
# 重排配置
rerank:
  backend: none             # none | cross_encoder | llm
  # backend != none 时必填（不再有隐式默认值，见 design D3）
  # cross_encoder 推荐: BAAI/bge-reranker-base（中英双语，本地推理零 token，
  #   约 1.1GB 权重，首次加载需能访问 HuggingFace，国内设 HF_ENDPOINT 镜像）
  model: ""
  top_m: 50                 # 送入重排的候选上限，超出部分按原名次追加在结果之后
  timeout_sec: 30.0         # 单次重排总耗时上限；超时保留已评分部分，其余保持原序
  batch_size: 8             # 分批推理的批大小，同时决定超时检查的粒度
```

`src/core/settings.py`：

```python
@dataclass
class RerankSettings:
    """重排配置。"""

    backend: str = "none"
    model: str = ""           # backend != none 时不得为空（load_settings 校验）
    top_m: int = 30           # 必须 > 0
    timeout_sec: float = 30.0 # 必须 > 0
    batch_size: int = 8       # 必须 > 0
```

`load_settings()` 新增校验：`backend ∈ {none, cross_encoder, llm}`；`backend != none` 时 `model` 非空且 `RerankerFactory.probe_backend(backend)` 通过；`top_m` / `timeout_sec` / `batch_size` 均 > 0。

**异常类型**（T-2.1 实施时按既有约定修正）：`src/core/settings.py` 的校验一律抛 `SettingsError`，不是 `ValueError` —— 这是该模块既有的统一约定（`_validate_fusion_settings` / `_validate_evaluation_settings` 皆然），不为本变更破例。libs 层的 `probe_backend` 按 CLAUDE.md 的 code convention 抛 `ValueError`，由 `load_settings()` 转成 `SettingsError` 后向上抛，保证配置校验对调用方只呈现一种异常类型。

## 七条硬约束合规性

| # | 约束 | 本设计如何满足 |
|---|---|---|
| 1 | Provider 无关 | 具体库名只出现在 `src/libs/reranker/` 与 `RerankerFactory`。D4 让 `src/core/settings.py` 经 Factory 探测，不 import `sentence_transformers`，不出现 `if backend == "cross_encoder"` 的业务分支 |
| 2 | 配置驱动 | 新增的 `timeout_sec` / `batch_size` 均有 `settings.yaml` 条目 + dataclass 字段；`batch_size` 从硬编码 32 变为配置项；D3 消除隐式模型默认值 |
| 3 | 快速失败 | D4 把「依赖没装」这个配置错误提到启动期硬失败；三个数值配置项启动期校验；D3 消除隐式模型默认值。运行期偶发故障（含「装了但坏了」的 ImportError）仍降级 —— 这是规格中显式区分的两种情况，不是对本约束的例外 |
| 4 | 追踪显式 | 沿用现有签名 `rerank(query, candidates, trace=...)`，trace 是显式参数，新增的超时/截断字段写入同一条 stage 记录 |
| 5 | 结构化日志 | 新增日志走 `get_logger(__name__)` 写 stderr；不新增任何 `print()`（重排在 MCP stdio 链路上，污染 stdout 会直接打断 JSON-RPC） |
| 6 | 类型安全 | 新增 public 函数（`probe_backend`）带完整注解；不引入新的跨模块领域类型，沿用 `RetrievalResult` |
| 7 | 测试支撑变更 | 每个改 `src/` 的任务配套 `tests/unit/` 用例；D9 的集成测试是额外增量，不替代单元测试。现有 4 个 rerank 测试文件的断言不得修改 —— 若改动逼得改断言，说明改错了 |

## Risks / Trade-offs

- **超时粒度受 `batch_size` 制约** → 降到 8 并可配。极端情况（单批就超时）仍会超出 `timeout_sec` 一个批次的时间，这是同步推理不可中断的固有代价，规格里的「保留已评分部分」正是为它设计的。
- **首次加载需外网访问 HuggingFace，国内可能失败** → 错误消息必须区分「依赖缺失」与「权重获取失败」（规格已要求），并提示 `HF_ENDPOINT` 镜像。落盘后完全离线。
- ~~**`bge-reranker-base` 与 `CrossEncoder(model_name)` 的兼容性未实测**~~ → **T-1.1 已验证通过**，风险关闭。首次下载经 `hf-mirror.com` 耗时 493s（一次性），`import sentence_transformers` 冷启动 44.5s。
- **跨语言 pair 的重排分数被显著压低**（T-1.1 实测发现）→ 中文 query 对中文正确答案得 0.9998，对**语义等价的英文答案**只得 0.2973。本项目语料是同一份 MT5 文档的中英双版本，所以这不是理论问题：中文 query 命中英文 chunk 时重排会把它往下压。这会影响 6.1 A/B 结果的解读 —— 中文金标上若出现负增益，需先排查是否由跨语言压分造成，而非直接归因于「重排无效」。缓解手段（按语言过滤候选、或换多语对齐更好的模型）不在本次范围，但结论必须记进 acceptance.md。
- **A/B 可能显示重排无增益或负增益** → 这不是失败。金标的 `expected_chunk_ids` 是机器按纯 dense top-5 回填的，`recall` / `hit_rate` 结构性偏向 dense，重排挪动名次就可能无理由地拉低它们；所以判据是 `MRR` / `nDCG`，且「跑通」的验收信号是 trace 而非分数（规格已明确）。负面结论照样归档，与 Feature-005 同理。
- **`llm` 后端在 `top_m` 生效后仍然慢且贵**（每条候选一次串行网关调用）→ 本次不优化，`top_m` 只是给它装上刹车。A/B 跑一轮拿到对照数据即可。

## Migration Plan

默认行为不变（`backend` 仍为 `none`），因此**不需要迁移，也不需要重标金标基线**。

- 启用：`pip install -e ".[rerank]"` → `settings.yaml` 填 `backend: cross_encoder` + `model: BAAI/bge-reranker-base` → 重启。首次查询会下载权重（约 1.1GB，一次性）。
- 回滚：`backend` 改回 `none` 并重启。已下载的权重留在 HuggingFace 缓存，不影响任何行为。
- 未安装可选依赖的既有部署完全不受影响 —— 默认配置不触碰重排依赖（规格中「默认配置不启用重排」这条要求就是为它守的）。
