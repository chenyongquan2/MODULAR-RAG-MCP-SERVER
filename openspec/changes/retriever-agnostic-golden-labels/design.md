## Context

动机见 [proposal.md](proposal.md) § Why，行为契约见 [specs/evaluation/golden-labels/spec.md](specs/evaluation/golden-labels/spec.md)。

设计上最重要的现状事实：**Feature-003 已经把「异源 LLM 判定 + 三态结论 + 可审计元数据 + 中断保留」这套基础设施建好了**，用在金标精修的预筛上。本变更要做的判定在结构上几乎同形，因此主线是**复用**而不是新建：

| 已有资产 | 位置 | 本变更如何用 |
|---|---|---|
| `SourceRelation`（DIVERGENT / SAME_SOURCE / UNVERIFIABLE） | `src/observability/evaluation/testset_screener.py:92` | 直接复用，判定端 vs 合成端的同源关系 |
| `get_judge_identifier` / `get_screening_identifier` | `src/observability/evaluation/_ragas_wrappers.py:351` | 复用 `<provider>:<model>` 标识格式与比对口径 |
| `ScreeningUnavailableError`（模型整体不可用 vs 输出不合格的区分） | 同上 `testset_screener.py` | 复用这个区分 —— 它正是「不要把两种失败混成一个」的先例 |
| `_review_metadata` 审计字段 + `v0.9-partial` 中断标记 | `scripts/refine_testset.py` | 复用形态，改名为标注元数据 |
| 退出码约定（2 = 前置不满足 / 3 = 模型不可用 / 130 = 中断但写出） | Feature-003 quickstart | 沿用同一套，使用者不必学第二套语义 |

其余约束：

- `custom_evaluator.py` 读的是 `expected_chunk_ids: list[str]`，二值相关度。保持该字段的名与类型 → 评估器与报告 schema 零改动。
- 检索三路已各有现成入口：`DenseRetriever` / `SparseRetriever` / `Reranker`，且 `HybridSearch` 已把它们编排好。
- 网关实测不稳（embedding 超时、RAGAS `TimeoutError`、模型下架是常态），续跑不是加分项而是必需项。

## Goals / Non-Goals

范围边界见 proposal § Non-goals。设计层面额外两条：

- **Goal**：判定逻辑与「怎么拿到候选」解耦。池化产出一个 `(query, chunk)` 列表，判定只消费这个列表 —— 这样将来加第四路召回不必改判定代码。
- **Non-Goal**：不做判定结果缓存层。续跑靠「已判定的候选记录在产出文件里」实现，不引入独立缓存 —— 缓存的失效口径（语料变了？prompt 变了？模型变了？）会比它省下的调用更麻烦。

## Decisions

**D1 · 新脚本而非改造 `backfill_chunk_ids.py`**：新增 `scripts/label_golden_chunks.py`，旧脚本保留但在 docstring 顶部标注「产出第一代（dense-anchored）标签，新标注用 label_golden_chunks.py」。
否掉原地改造 —— 旧脚本是第一代金标的可复现来源，删了就无法重现历史基线是怎么来的。

**D2 · 池化走 `HybridSearch` 的组件而非重新实现检索**：直接用 `DenseRetriever` / `SparseRetriever` / `Reranker` 三个现成组件各自取 top-N。
否掉调 `HybridSearch.search()` 一次拿融合结果 —— 融合已经把三路揉成一个排序，拿不到「这条是谁贡献的」，而 spec 要求记录每个候选的贡献来源。

**D3 · 用 `query` 而非 `ground_truth` 作为检索输入**：池化时用问题去检索。
这是与第一代的一个关键差异：旧脚本用 `ground_truth`（答案）去检索，那是「找像答案的段落」；评估时系统面对的是 query。用 query 池化才能覆盖「真实检索会看到的候选空间」。`ground_truth` 仍然用 —— 作为判定时给 LLM 的参考答案。

**D4 · 判定输出二值 + 分级并存**：LLM 返回 0-3 分级相关度（0 无关 / 1 沾边 / 2 部分支撑 / 3 直接回答），`>= 2` 纳入 `expected_chunk_ids`。分级原值与判定理由写入 sidecar 字段 `_chunk_labels`。
否掉只要二值 —— 分级几乎不增加调用成本（同一次调用的输出），却为将来的 graded nDCG 留下数据。也否掉直接改用分级算 nDCG —— 那要改 `custom_evaluator.py`，属独立变更（proposal § Non-goals）。

**D5 · 判定模型配置项复用 `screening_llm` 还是新增 `labeling_llm`？→ 新增**：`evaluation.labeling_llm`。
否掉复用 `screening_llm` —— 两者的异源对象相同（都要 ≠ 合成端），但**校准标度不同**：预筛的 `keep/drop_threshold` 是「这条 case 该不该留」，标注的阈值是「这个 chunk 相关到什么程度」。共用一份配置会让两处校准互相干扰，而「换模型必须重新校准」是本项目已记录的陷阱。

**D6 · 续跑靠产出文件自身**：产出里每个候选带 `label` 与 `judged_at`；再次执行时读入已有产出，只对无 `label` 的候选发起调用。
否掉独立的断点文件 —— 多一个文件就多一处可能与产出不一致的状态。

**D7 · 调用量上限用「判定调用数」计，不用 case 数**：`max_judgements` 配置项，达到上限即停止并写出部分结果。
否掉按 case 数限制 —— 每个 case 的池子大小差异很大（去重后 25–40 不等），按 case 限制无法预测实际成本。

**D8 · 抽检导出为独立子命令而非自动交互**：`--export-sample N` 导出 JSON，人工填 `human_label` 后用 `--import-sample` 回填并计算一致率。
否掉在标注流程里内联交互 —— 标注要跑 20+ 分钟，中间插人工会让整个流程无法无人值守。

**D9 · 两代金标的区分靠 `version` + 新增 `_labeling_method` 字段**：现有金标 `version: "v1.0"`，新产出用 `v2.0` 并带 `_labeling_method: "pooled-llm-judged"`；第一代回填标 `"dense-top-k"`。报告侧读这两个字段判定可比性。
否掉只靠文件名区分 —— 文件名不进报告，跨代 delta 会静默误导（spec 明确要求报告能标注不可比）。

## 新增配置项

`config/settings.yaml` 的 `evaluation` 段：

```yaml
evaluation:
  # 金标标注（change retriever-agnostic-golden-labels）
  labeling:
    # 各路召回取多少条进候选池。三路并集去重后每 case 约 25-40 个候选
    pool_top_n_dense: 20
    pool_top_n_sparse: 20
    pool_top_n_rerank: 20      # 0 = 不启用重排路（重排依赖是 optional extra）
    # 分级相关度 >= 此值纳入 expected_chunk_ids（0 无关 / 1 沾边 / 2 部分支撑 / 3 直接回答）
    relevance_threshold: 2
    # 单次标注的判定调用上限。达到即停止并写出部分结果，不静默截断
    max_judgements: 2000
    # 判定失败率超过此值产出告警（区别于「模型整体不可用」）
    judge_failure_warn_ratio: 0.10
    # 与「纯 dense top-5」的 Jaccard 超过此值产出告警（池化或判定疑似未生效）
    dense_overlap_warn: 0.90
    # 人工抽检一致率低于此值产出告警
    human_agreement_warn: 0.80

  # 判定 LLM。必须与 judge_llm（合成端）异源，判据是完整标识串
  # <provider>:<model> 相等即视为同源。刻意不复用 screening_llm ——
  # 两者阈值标度不同，共用会让校准互相干扰。
  labeling_llm:
    provider: glm
    model: ""                  # 必填且不得与 judge_llm 标识相同
    api_key: ${GLM_API_KEY}
    request_timeout_sec: 60
    max_retries: 3
```

`src/core/settings.py`：

```python
@dataclass
class LabelingSettings:
    """金标标注配置。"""

    pool_top_n_dense: int = 20
    pool_top_n_sparse: int = 20
    pool_top_n_rerank: int = 0        # 0 = 不启用重排路
    relevance_threshold: int = 2      # 1..3
    max_judgements: int = 2000
    judge_failure_warn_ratio: float = 0.10
    dense_overlap_warn: float = 0.90
    human_agreement_warn: float = 0.80
```

`labeling_llm` 复用既有的 LLM 子配置 dataclass 形态（与 `judge_llm` / `screening_llm` 同构）。

`load_settings()` 新增校验：三个 `pool_top_n_*` 均 >= 0 且至少两路 > 0（单路池化违反 spec 第一条）；`relevance_threshold ∈ {1,2,3}`；`max_judgements > 0`；三个比例项在 `[0,1]`。**异源校验不放在 `load_settings`** —— 它需要读 candidate 文件里的合成端标识，属运行期前置检查，与 Feature-003 的 `check_auto_preconditions` 同位置。

## 七条硬约束合规性

| # | 约束 | 本设计如何满足 |
|---|---|---|
| 1 | Provider 无关 | 判定 LLM 经 `LLMFactory` 创建，脚本不 import 任何具体 provider；三路召回经现成组件的抽象接口，不出现 `if provider ==` 分支 |
| 2 | 配置驱动 | 池化条数、阈值、上限、告警线全部为 `settings.yaml` 条目 + dataclass 字段，无硬编码可调参数 |
| 3 | 快速失败 | 数值配置启动期校验；同源判定运行期前置硬失败（退出码 2）；「模型整体不可用」与「输出不合格」严格区分（沿用 `ScreeningUnavailableError` 的先例，退出码 3），不把前者降级成后者 |
| 4 | 追踪显式 | 标注是离线脚本，不在查询链路上；如需打点则 trace 作显式参数传入，不引入全局状态 |
| 5 | 结构化日志 | 走 `get_logger(__name__)` 写 stderr；进度输出走 stdout（脚本非 MCP 链路，但**运行时须加 `-u`**，否则管道下全缓冲会伪装成卡死 —— 本项目已踩过） |
| 6 | 类型安全 | 新增 public 函数完整注解；标注结果的领域类型（候选、判定、元数据）定为 dataclass |
| 7 | 测试支撑变更 | 每个改 `src/` 的任务配套 `tests/unit/`；LLM 调用全部 mock，单测不触网 |

## Risks / Trade-offs

- **判定模型自身的偏好取代了检索器偏好** → 这是本变更的固有代价，不是缺陷可修。spec 里「人工抽检是必要闸门」那条要求就是为它设的。**若跳过抽检，本变更等于把一种未验证的偏差换成另一种** —— 这句话要写进验收记录。
- **1200–1900 次判定调用，网关不稳** → D6 的续跑 + D7 的调用上限 + 单候选失败不终止整轮。三者都是 spec 的硬要求，不是优化项。
- **新金标可能让重排的负增益依然为负** → 那是合法结论，proposal § 验收判据 第 2 条已明确不预设结果。区别在于**届时的结论是可信的**。
- **`pool_top_n_rerank > 0` 需要 `pip install -e ".[rerank]"`** → 默认置 0（不启用重排路），保持「核心安装即可标注」。启用时若依赖缺失，`RerankerFactory.probe_backend` 会在启动期挡住（上一个变更已建好）。
- **既有基线全部失效** → 这是 proposal 里标了 **BREAKING** 的那条。D9 让报告能识别代次，但**重标基线是使用者的动作**，本变更只保证不会静默误导。
- **中文金标只有 6 条** → 本变更不解决。但顺序上必须先修构造再扩容，否则用有偏方法再生产 40 条。扩容是下一个独立变更。

## Migration Plan

1. `pip install -e .`（无新增第三方依赖；启用重排路才需 `.[rerank]`）
2. 配 `evaluation.labeling_llm.model`，必须 ≠ `evaluation.judge_llm.model` 的完整标识
3. `python -u scripts/label_golden_chunks.py --input tests/fixtures/golden_test_set_en.json --output tests/fixtures/golden_test_set_en_v2.json --collection default_text-embedding-v4`
4. `--export-sample 20` → 人工填 `human_label` → `--import-sample` 看一致率
5. 一致率达标后，用新金标重标基线；旧基线保留并标注为第一代

**回滚**：删掉 v2 文件，评估配置指回 v1 金标。旧脚本与旧金标全程未被修改，回滚无损。

## Open Questions

- **分级相关度的四档措辞需要在真实语料上试一轮才能定稿**。0/1/2/3 的边界（尤其 1 与 2 之间）对判定一致性影响大，但这不改变 specs、approach 或任务拆分 —— 属实施时按抽检结果调 prompt 的范围。
- **人工抽检的一致率下限 0.80 是初始猜测**，与 Feature-003 的 `keep/drop_threshold` 默认 0.80 同性质：需要跑一轮看分布再校准。已作为配置项而非硬编码。
