## Context

见 [proposal.md](proposal.md) § Why。

设计上唯一的硬约束来自 **`ragas==0.1.21` 是基线锚定点，不能升级也不能改其源码**。而 NaN 恰恰产生在 RAGAS 内部：judge 的原始响应被 RAGAS 吞掉，`ragas_evaluate()` 只把结果表达为 NaN 交出来。因此「为什么判不出来」这个信息，在现有数据流里**已经丢失**，不是没被记录，而是拿不到。

唯一还能看到 judge 原始响应的位置，是项目自己的适配层 [`_ragas_wrappers.py`](../../../src/observability/evaluation/_ragas_wrappers.py) —— RAGAS 通过它回调项目的 `BaseLLM`。这决定了整个设计的形状。

## Goals / Non-Goals

**Goals:**
- 在不改 RAGAS、不升级版本的前提下，把判定失败的成因捞回来
- 降级信号从「躺在 JSON 里」变成「进入验收判定 + 打到 stdout」
- 分母不一致的比较被挡住，且不动历史数据

**Non-Goals（设计层面，proposal 的范围之外不再重复）：**
- 不为降级 case 做自动重试。重试会把「判定失败率」这个观测量本身搅浑，且掩盖成因——本变更的目的是先看清
- 不为原因分类做语义推断（如猜测「模型觉得内容不足」）。只做机械可判的分类，兜底类别保持诚实

## Decisions

**D1. 失败原因在适配层采集，不在 evaluator 推断**
- 选：在 `_ProjectLLMAsLangChain._call` 处记录每次 judge 调用的结果特征（空响应 / 异常类型 / 耗时），按当前 case 归集；`RagasEvaluator` 在单条 `evaluate()` 结束后，把调用记录归约成该 case 各指标的降级原因
- 否：仅在 `eval_runner` 用 `isnan` 反推 —— 拿得到「失败了」，拿不到「为什么」，等于现状

**D2. 采集用显式传入的收集器，不用线程局部变量**
- 选：`RagasEvaluator` 持有收集器实例并显式注入适配层闭包，生命周期与单次 `evaluate()` 对齐
- 否：`contextvars` / `threading.local` —— 违反硬约束 4

**D3. 降级率纳入既有的 `ThresholdEvaluator`，不新建判定器**
- 选：扩展 `ThresholdEvaluator`，让它在 8 项指标阈值之外多看一项降级率；`acceptance_status` 语义保持单一出口
- 否：在 `eval_runner` 里另判一次再合并 —— 会出现两个真相来源

**D4. 有效分母按「指标 × 运行」记录，而非只记全局 `degraded_case_count`**
- 选：报告新增按指标的 `valid_count` / `degraded_count` / `degraded_reasons`；保留现有 `degraded_case_count` 字段不动（向后兼容）
- 否：只留全局计数 —— 无法回答「0.8887 是几条的均值」，而这正是本变更要解决的问题

**D5. 历史报告缺字段时保守标不可比**
- 选：`BaselineManager` 比较时若基线不含分母信息，将其全部判定类指标差异标为不可比
- 否：假定历史基线分母 = 总条数 —— 那是错的（run `80a82405` 就不是），会制造假可比

**D6. `JudgeLLMSettings.max_tokens` 先验证再落地**
- 选：任务顺序上先做归因（线索 1 是否成立），成立才加字段。加则默认 `800`，与 `LabelingLLMSettings` 已验证过的值对齐
- 否：直接加上 —— 未经验证的配置项是下一个死配置（项目已有 `top_m`、`--collection` 两次前科）

### 新增配置

```yaml
evaluation:
  # ─── 评估运行完整性 (change evaluation-degradation-governance) ───
  # 降级 = judge 未能产出可解析结果，该 case 的该指标记 NaN 且不计入分母。
  # 治理它的理由见 proposal.md：分母静默收缩会让绝对值虚高、跨运行不可比。
  degradation:
    # 降级率门槛。超过即 acceptance_status=fail(--exit-on-fail 退出码非零)。
    # 0.05 源自 Feature-001 SC-006，不是新拍的数。
    max_ratio: 0.05
    # 兜底原因("未知")占全部降级的比例超此值即告警 —— 归因能力本身失效的信号。
    unknown_reason_warn: 0.10

  judge_llm:
    # ⚠️ 仅在归因确认线索 1 成立后新增。默认 800 与 labeling_llm 对齐 ——
    #    那边实测硬编码 200 会让 367 字符的 chunk 返回空响应。
    max_tokens: 800
```

```python
@dataclass
class DegradationSettings:
    """评估降级治理配置 (change evaluation-degradation-governance)。"""

    max_ratio: float = 0.05
    unknown_reason_warn: float = 0.10


@dataclass
class EvaluationSettings:
    # ... 既有字段不变 ...
    degradation: DegradationSettings = field(default_factory=DegradationSettings)


@dataclass
class JudgeLLMSettings:
    # ... 既有字段不变 ...
    max_tokens: int = 800  # 条件新增，见 D6
```

### 七条硬约束合规性

| # | 约束 | 本变更的合规情况 |
|---|---|---|
| 1 | Provider 无关 | 采集层挂在 `_ragas_wrappers` 的通用适配闭包上，只经 `BaseLLM` 接口；不 import 任何具体 provider，原因分类不含模型名分支 |
| 2 | 配置驱动 | 门槛与告警比例全部落 `settings.yaml` + `DegradationSettings`（片段见上），无硬编码 |
| 3 | 快速失败校验 | `max_ratio` / `unknown_reason_warn` 在 `load_settings()` 校验区间 `[0, 1]`，越界抛 `ValueError`，不兜底 |
| 4 | 追踪显式 | 收集器实例显式注入（D2），禁用 `contextvars` / `threading.local` |
| 5 | 结构化日志 | 降级摘要经 `get_logger()` 写 stderr；stdout 的呈现只在 `scripts/evaluate.py` 里（`src/` 内无 `print()`） |
| 6 | 类型安全 | 新增的降级原因枚举与统计结构定义在 `src/core/types.py`（跨 evaluator / runner / baseline 三处共用） |
| 7 | 测试支撑变更 | 每条 spec 场景对应 `tests/unit/` 用例；分母守卫与阈值判定用构造报告测，不依赖真实 LLM |

## Risks / Trade-offs

- **[采集层拿到的是「调用级」信息，而 NaN 是「指标级」结果，二者未必一一对应]** → 一次 `evaluate()` 内多个指标共用若干次 judge 调用，归约可能把原因归错指标。缓解：归约规则只在能确定归属时给出具体分类，否则落兜底类别；`unknown_reason_warn` 就是用来暴露归约能力不足的
- **[降级率进入验收后，现有基线立刻变红]** → 这是 proposal 里声明的 BREAKING，属预期。缓解：门槛可配置，需要分阶段收口时可临时放宽并在报告快照里留痕
- **[RAGAS 内部可能存在不经过项目适配层的失败路径]**（如 embedding 侧异常、RAGAS 自身解析逻辑抛错）→ 这类失败采集不到原因，会落兜底类别。缓解：归因任务里显式核对兜底占比；若兜底居高不下，说明主因不在 judge 调用侧，这本身就是有价值的结论
- **[只观测不重试，短期内降级率不会下降]** → 有意为之（见 Non-Goals）。真正的下降依赖答案语言问题的修复，而那在本变更范围之外

## Migration Plan

1. 加字段与采集，报告增量扩展 —— 此阶段 `acceptance_status` 语义不变，可安全合入
2. 跑归因，产出三条线索的结论；线索 1 成立则加 `max_tokens` 并复测
3. 最后才把降级率接入 `acceptance_status` —— 放在最后是为了让「评估变红」发生在已经能解释原因之后，而不是之前

回滚：把 `degradation.max_ratio` 配成 `1.0` 即可让降级率不再影响验收，无需回退代码。
