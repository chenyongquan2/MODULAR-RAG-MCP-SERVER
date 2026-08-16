## Why

**报告里公布的 RAGAS 分数，分母不是全样本。**

judge 输出无法解析时，该 case 的该指标记为 NaN，`eval_runner` 设计为**不计入分母**（[eval_runner.py:14](../../../src/observability/evaluation/eval_runner.py#L14)）。这个设计本身有道理——NaN 参与平均会污染整列。但它把「判不出来」变成了**静默的样本流失**：

2026-08-15 复核 run `80a82405`（42 条英文金标）：

| 指标 | 公布值 | 实际分母 | 降级 |
|---|---|---|---|
| `faithfulness` | 0.8887 | **n=27** | 15/42 (36%) |
| `context_precision` | 0.7643 | **n=31** | 11/42 (26%) |
| `answer_relevancy` | 0.8473 | n=42 | 0 |
| `context_recall` | 0.8333 | n=42 | 0 |

`degraded_case_count: 23` = **54.8%**，是 SC-006 所定 ≤ 5% 门槛的 **11 倍**。

**警报建过，响了，没人读。** 该字段躺在报告 JSON 里，不参与 `acceptance_status` 判定，不出现在日常查看的 8 项聚合指标中。这一整类失败正是项目反复撞见的那个模式：**看起来生效、实际没生效、而且不报错**——与 `top_m` 死配置、`--collection` 死参数、`max_tokens=200` 饿死判定同源。

后果有二：

1. **绝对值被幸存者偏差抬高**——judge 判不出来的往往是难 case
2. **两次运行的分母不同则严格不可比**——现有 delta 机制会把「分母变了」呈现为「质量变了」

配对实验（同一批 42 条冻结元组，旧 `glm:minimax/minimax-m2.7` vs `glm:anthropic/claude-sonnet-5`）进一步定位了病因：

- 换强 judge 只把总降级率从 55% 压到 33%
- `context_precision` 那一路 26% → **5%**（基本修复，属 judge 能力问题）
- `faithfulness` 仍有 **29%** 判不出 —— **强 judge 救不了，病因在输入侧**

## What Changes

- **降级率纳入验收判定**：`acceptance_status` 不再只看 8 项聚合指标；降级率超过配置门槛即判 `fail`，`--exit-on-fail` 返回非零。门槛做成配置项而非硬编码（默认取 SC-006 的 5%）
- **每个指标的有效分母显式落盘**：报告新增每指标的 `valid_count` / `degraded_count`，让「0.8887 是 27 条的均值」这件事在数据里可见，而不是要靠人去数 `case_results`
- **判定失败必须留原因**：当前 NaN 是个不可归因的黑洞。新增按 case、按指标的失败原因分类（如响应为空 / JSON 解析失败 / 超时 / 上游拒绝），写入报告
- **跨运行可比性守卫**：delta 比较时检查两次运行各指标的有效分母；不一致则在报告中标注该指标不可比，沿用现有 `delta_comparable` 的语义。**不改写已归档的历史报告**——它们是事实记录
- **三条降级成因的归因验证**（只验证，不修复）：
  1. `JudgeLLMSettings` 至今无 `max_tokens` 字段，judge 路径不传该参数、用网关默认值；而 `LabelingLLMSettings` 正因同类问题踩过坑（硬编码 200 → 空响应 → 全标 `judge_failed`，已修为 800）
  2. 英文金标产出中文答案（实测多条），statement 抽取与 answer_relevancy 反向生成均受损
  3. 答案过短（最短 48 字符、中位 228），statement 抽取无从下手
- **若线索 1 成立则一并修复**：为 `JudgeLLMSettings` 补 `max_tokens`，属评估侧配置，边界之内

**BREAKING（验收语义）**：降级率进入 `acceptance_status` 后，现有 55% / 33% 的数据会让评估**立刻变红**。这是有意为之——当前的 `pass` 本就建立在静默收缩的分母上。已归档报告不受影响（不回填、不重算）。

## Non-goals

明确**不做**以下事项：

- **不修「英文问题产出中文答案」**。它是生产侧的生成缺陷，真实用户同样会遇到，属 `ResponseBuilder` / 生成链路的语言控制问题。本变更只负责**证明它是降级主因并留下证据**，修复另开 change。理由：本变更的验收标准应当只涉及「评估的可观测性与完整性」，掺入生成正确性会让两类标准互相绑架
- **不回填、不重算、不作废历史报告**。346 条归档索引原样保留
- **不改动 NaN 不计入分母这一聚合策略本身**。它是对的；问题在于流失没有被暴露，而不是流失被排除
- **不做 judge 校准 / 人工一致率**。那是独立缺口（v2 金标 `human_agreement_rate` 仍为 `null`），与本变更正交
- **不改任何检索、融合、重排行为**
- **不碰合成端**。adapt 语言校验与中文金标扩充由在途的 `expand-chinese-golden-set` 负责，两者不重叠：那个管「问题从哪来」，本变更管「判定为什么失败」

## 判定成败的口径

**本变更不以移动检索质量指标为目标**，因此 recall / hit_rate 偏向 dense 的已知偏差在此不适用——那条偏差影响的是「用金标评判检索路径」，而本变更评判的是「评估流程自身的完整性」。

- **金标集合**：`tests/fixtures/golden_test_set_en.json`（42 条，第一代 `dense-top-k` 口径），collection `default_text-embedding-v4`。选它是因为 run `80a82405` 的基线数据就在这批上，可直接对照
- **判定成败看两项**：
  1. **降级率可被发现**：报告中每指标的 `valid_count` / `degraded_count` 齐全，且降级率超标时 `acceptance_status = fail`、`--exit-on-fail` 退出码非零
  2. **降级率可被归因**：全部降级 case 都带失败原因分类，无「未知」兜底占比 > 10%
- **不把「降级率降到 5% 以下」作为本变更的验收条件**——主因（答案语言）的修复在范围之外，强行要求会让本变更绑架另一个 change。降到多少由归因数据说话

## Capabilities

### New Capabilities

- `evaluation/run-integrity`: 评估运行自身的完整性与可信度 —— 判定失败的可发现性、可归因性，有效分母的显式披露，以及跨运行比较的可比性守卫。区别于 `evaluation/golden-labels`（哪些 chunk 算正确答案）与 `evaluation/testset-synthesis`（问题从哪来），本能力覆盖的是「这次评估的结果本身能不能信」。

### Modified Capabilities

无。现有 `evaluation/golden-labels` 覆盖标注口径，不涉及评估执行期的判定失败处理。

## Impact

**代码**
- `src/observability/evaluation/eval_runner.py`：分指标有效分母统计、降级原因收集、报告字段扩展
- `src/observability/evaluation/threshold_evaluator.py`：降级率纳入 `acceptance_status` 判定
- `src/observability/evaluation/ragas_evaluator.py`：NaN 产生处捕获并上报失败原因（当前信息在此丢失）
- `src/observability/evaluation/baseline_manager.py`：delta 比较的分母一致性守卫
- `src/core/settings.py` + `config/settings.yaml`：降级率门槛配置项；`JudgeLLMSettings.max_tokens`（若线索 1 成立）
- `scripts/evaluate.py`：降级率与原因分布的 stdout 呈现

**数据**
- `logs/evaluation_reports/`：新报告增加字段；**已归档报告不动**
- `logs/baselines.json`：不变更结构

**兼容性**
- 报告 JSON 为增量加字段，dashboard 读旧报告不受影响
- `acceptance_status` 语义扩大，现有基线会由 `pass` 转 `fail`（见 BREAKING）

**成本**
- 归因验证需在 42 条英文金标上重跑评估，量级约 600 次 judge 调用/轮，预计 2-3 轮
