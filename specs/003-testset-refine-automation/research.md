# Phase 0 Research: 金标精修自动化

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04
**Spec**: [spec.md](./spec.md)

本阶段解决 Technical Context 中的未知点。所有结论均基于对当前代码的实际核对(附 file:line),非推测。

---

## Decision 1 — 预筛 LLM 如何以「异源」方式接入

**Decision**: 新增 `evaluation.screening_llm` 配置节,复用 `_ragas_wrappers.build_ragas_judge` 已确立的「settings 投影」模式创建 `BaseLLM` 实例;并把该模式抽成共享 helper,避免第三次复制。

**核对结果**:

`LLMFactory.create(settings, **override_kwargs)` 在 [llm_factory.py:100](../../src/libs/llm/llm_factory.py) 硬读 `settings.llm.provider`,`override_kwargs` 仅透传给 provider 构造函数 —— **无法通过参数覆写 provider**。

但项目已有成熟先例。[_ragas_wrappers.py:78-92](../../src/observability/evaluation/_ragas_wrappers.py) 的做法:

```python
judge_llm_settings = _LLMSettings(provider=eval_judge.provider, model=..., api_key=..., base_url=...)
judge_settings = copy.copy(settings)      # 浅拷贝顶层 settings
judge_settings.llm = judge_llm_settings   # 把 .llm 换成子配置节
project_llm = LLMFactory.create(judge_settings)
```

预筛 LLM 与 Judge LLM 的需求同构,应走同一条路。

**Rationale**: 该模式已在生产路径验证,且完全满足宪法 Rule I(业务代码不 import 具体 provider)与 Rule II(配置驱动)。

**Alternatives considered**:

| 方案 | 否决理由 |
|---|---|
| 给 `LLMFactory.create()` 增加 `provider=` 参数 | 改动被 5 个 provider 与多处调用点依赖的公共工厂接口,影响面远超本 feature;宪法 § 架构稳定性 要求避免此类改动 |
| 在预筛模块直接 import 具体 provider 类 | 直接违反宪法 Rule I(Provider 无关性) |
| 复用 `evaluation.judge_llm` 配置节 | 与 FR-002「必须异源」直接冲突 —— 合成端用的就是 judge_llm |

**Follow-up**: `build_ragas_judge` 与新的预筛构造将是第 2、3 个复制此模式的地方。计划中安排一个任务把「子配置节 → BaseLLM」抽成 `_ragas_wrappers` 内的共享函数,两处共用。这是重构既有代码,须在 FR-004 的回归保护下进行。

---

## Decision 2 — 同源检测的判据

**Decision**: 比较预筛模型标识与 candidate 文件中记录的合成端标识,两者相等即判定同源。

**核对结果**:

合成端在 [testset_synthesizer.py:500-506](../../src/observability/evaluation/testset_synthesizer.py) 写入:

```python
"_synthesis_metadata": {
    "generator": "ragas.testset.TestsetGenerator",
    "judge_llm_identifier": get_judge_identifier(self._settings),   # "<provider>:<model>"
    "embedding_identifier": ...,
    ...
}
```

`get_judge_identifier` 在 [_ragas_wrappers.py:317](../../src/observability/evaluation/_ragas_wrappers.py) 定义为 `f"{provider}:{model}"`。

因此:
- 新增对称的 `get_screening_identifier(settings)` → `"<provider>:<model>"`
- 同源判据:`get_screening_identifier(settings) == candidate["_synthesis_metadata"]["judge_llm_identifier"]`

**Rationale**: 判据落在已有的、格式稳定的字段上,无需新增合成端改动(合成端在本 feature 的 Out of Scope 内)。

**边界处理**(对应 spec Edge Cases):
- 字段缺失或为空 → 无法验证异源,按「无法确认异源」处理:告警并要求显式确认标志后才继续
- 仅 provider 相同但 model 不同 → 视为**异源**。判据是完整标识串相等,不是 provider 相等

**实证支持「比完整标识而非比 provider」**:现有 candidate 文件 `tests/fixtures/candidates/zh_smoke_v2.json` 的实际值为

```json
"judge_llm_identifier": "glm:minimax/minimax-m2.7"
```

即 provider 名义上是 `glm`,但 model 经 OpenAI 兼容端点实际路由到 minimax。**若只比 provider,则 `glm:glm-4.6` 会被误判为同源并遭拒绝**,而它其实是真正的异源模型。这条实测数据直接否决了「比 provider」的实现,必须比完整标识串。

---

## Decision 3 — 审计记录如何落盘(受既有测试硬约束)

**Decision**: 新增独立字段 `_review_metadata`;**保持 `_refine_summary` 的键名与语义完全不变,`_schema_version` 保持 `1`**。

**核对结果 —— 这是本 feature 最硬的约束**:

[test_refine_testset.py](../../tests/unit/test_refine_testset.py) 现有断言直接锁死了输出结构:

| 断言 | 行 | 含义 |
|---|---|---|
| `result["_refine_summary"]["keep"/"drop"/"edit"/"skip"]` | 74-76, 89, 98-99, 120-121, 144, 156-157 | 4 个计数键的名称与语义不可变 |
| `result["_schema_version"] == 1` | 183 | schema 版本号不可升 |
| 必需键集合检查 | 182 | 不可删键 |

FR-004 要求这些测试**不改断言**继续通过,因此:

- ❌ 不能把 `_refine_summary` 改名为 `_review_metadata`
- ❌ 不能把 schema 升到 2
- ✅ 只能新增可选字段 `_review_metadata`,与 `_refine_summary` 并存

**Rationale**: 新增可选字段对既有读取方(评估流程只读 `test_cases`)向后兼容,是唯一同时满足 FR-005 与 FR-004 的方案。

**Alternatives considered**:

| 方案 | 否决理由 |
|---|---|
| `_refine_summary` 扩展为完整审计对象 | 会破坏 `["keep"]` 等下标断言,违反 FR-004 |
| 升 `_schema_version` 到 2 并重构结构 | 直接违反 line 183 断言,违反 FR-004 |
| 审计信息写独立 sidecar 文件 | 违反 SC-005「仅凭金标文件自身即可追溯」 |

---

## Decision 4 — 三态判定的产出与解析

**Decision**: 预筛提示词落在 `config/prompts/` 下的独立文本文件;要求模型返回结构化 JSON(结论 + 置信度 + 理由);解析失败按 FR-008 归入 borderline。

**核对结果**: 项目已有 `config/prompts/chunk_refinement.txt`、`config/prompts/metadata_enrichment.txt` 的先例,提示词与代码分离是既有约定。

**Rationale**:
- 提示词外置符合宪法 Rule II(配置驱动),调 prompt 不必改代码
- FR-008 要求解析失败必须归 borderline(而非静默保留/丢弃),这把 LLM 不可靠性收敛为「多一条人工处理」,是安全方向的降级

**未决细节交由实现**: 具体 JSON 字段名与提示词措辞属实现细节,不在 plan 中固定;契约层面只约定「三态 + 置信度 + 理由」三项信息必须可得。

---

## Decision 5 — 代码落位(判定逻辑与 CLI 交互分离)

**Decision**:
- 预筛与判定逻辑 → `src/observability/evaluation/testset_screener.py`(新建)
- 抽样自检的纯计算部分 → 同上模块
- CLI 交互(打印、读 stdin、提示语) → 保留在 `scripts/refine_testset.py`

**Rationale**:
- 宪法 Rule V(NON-NEGOTIABLE)要求 **`src/` 内零 `print()`**,日志走 `observability.logger` 输出 stderr。判定逻辑放 `src/` 才能被单测覆盖且不引入 print
- `scripts/` 不受该条约束 —— 现有 `refine_testset.py` 用 print 做交互界面是正当的 CLI 输出。且它已在 [refine_testset.py:30-36](../../scripts/refine_testset.py) 强制 stdout 为 UTF-8(Windows GBK 会炸中文预览),这层与业务无关的适配应留在脚本侧
- 该分层也让 mock 预筛 LLM 的单测(FR 验证)不必驱动 stdin

---

## Decision 6 — 宪法 Rule IV(追踪显式化)的适用性

**Decision**: 标记 **N/A**,不为预筛流程引入 `TraceContext`。

**Rationale**: Rule IV 约束的是「pipeline 函数签名包含 `trace_ctx: TraceContext`」。本 feature 是一次性的离线金标制作工具,不属于 query / ingestion pipeline,产出物是文件而非可追踪的请求。审计需求已由 FR-005 的 `_review_metadata` 落盘满足,与 trace 系统职责不重叠。

若将来预筛被搬进 ingestion/query 链路,该判定需重新评估。

---

## Decision 7 — 抽样的可重复性

**Decision**: 不固定随机种子;把**实际抽中的用例标识**记入审计字段。

**Rationale**: 审计的诉求是「能复核当时抽了哪几条」,记录抽中结果即可满足,比固定 seed 更直接。固定 seed 反而会让重复运行始终抽到同一批用例,削弱抽样的覆盖意义。

---

## 遗留风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 置信度阈值需按模型校准 | 阈值不当会让 borderline 比例失控(过高退化为全人工,过低放过劣质用例) | 阈值配置化 + FR-011 的比例告警 + 阈值快照落盘(FR-005),首轮真实运行后校准 |
| 抽取共享 helper 触及既有 Judge 路径 | 可能影响 Feature-001 的 ragas 评估 | 该重构任务须在既有 ragas 相关单测保护下进行,且与新功能任务分开提交 |
| 预筛调用约 50 次/语种 | 成本与耗时 | spec Assumptions 已判定可接受;不做并发/缓存优化(Out of Scope) |
