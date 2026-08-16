> 顺序遵循 [design.md](design.md) § Migration Plan 的三阶段：**先能看见 → 再能解释 → 最后才拦截**。
> 把「评估变红」放在最后，是为了让它发生在已经能解释原因之后。

## 1. 可见性：分母与降级统计落盘

- [x] 1.1 在 `src/core/types.py` 定义降级原因枚举与按指标的统计结构；`eval_runner` 按指标统计 `valid_count` / `degraded_count` 并写入报告，保留现有 `degraded_case_count` 不动（向后兼容）。配套 `tests/unit/` 覆盖 spec 场景「部分样本降级时披露分母」「无降级时字段依然存在」「非判定类指标不受影响」
- [x] 1.2 `scripts/evaluate.py` 在运行结束时输出降级率与原因分布摘要（`src/` 内不得 `print()`，硬约束 5）。配套测试覆盖「存在降级时输出摘要」「无降级时不制造噪声」
  > 实施调整：`DegradationSettings` 与其区间校验**提前到本任务**落地（摘要要点出门槛值就必须先有配置）。这符合 design § Migration Plan 第一阶段「加字段」，只有「接入 `acceptance_status`」仍留在第三阶段。5.1 相应收窄。

## 2. 可归因性：把失败原因从 RAGAS 内部捞回来

- [x] 2.1 在 `_ragas_wrappers.py` 的 LangChain 适配闭包中接入显式注入的调用结果收集器（禁 `contextvars` / `threading.local`，硬约束 4），记录空响应 / 解析失败 / 超时 / 上游拒绝四类特征。配套单测用桩 LLM 构造四类失败，验证均被正确采集
- [x] 2.2 `RagasEvaluator` 在单条 `evaluate()` 结束后把调用记录归约成各指标的降级原因，无法确定归属的落兜底类别；报告输出按原因聚合的降级计数。配套测试覆盖「空响应被归类」「解析失败被归类」「原因分布可聚合」「兜底类别不得掩盖问题」

## 3. 归因验证（只查不修，产出结论）

- [x] 3.1 在 `golden_test_set_en.json`（42 条，collection `default_text-embedding-v4`）上跑一轮带归因的评估，量化三条线索各自解释了多少降级：①judge 无 `max_tokens`；②英文问题产出中文答案；③答案过短。结论写入本 change 的 `acceptance.md`，含兜底占比
  > 结论：①**否证**（595 次成功调用零空响应）②**成立且为唯一主因**（14 条真实判定失败全是语言错乱，语言一致组零失败）③**被 ② 完全吸收**。兜底占比 **0.0%**
- [x] 3.2 若线索 1 成立：为 `JudgeLLMSettings` 新增 `max_tokens`（默认 800，见 design D6），复测并记录降级率变化；若不成立，在 `acceptance.md` 写明否证依据并**不加该字段**。改 `src/` 时配套 settings 校验单测
  > 线索 1 否证 → **不加字段**，并撤回为验证臂临时加的透传代码（留着就是第三个「配了不生效」的死配置）。否证依据见 [acceptance.md](acceptance.md) § 三

## 4. 可比性守卫

- [x] 4.1 `BaselineManager` 在 delta 比较时校验两次运行各指标的有效分母，不一致则标注该指标不可比；基线缺分母信息时保守判定为全部判定类指标不可比，且不修改历史报告。配套测试覆盖「分母不同则标注不可比」「分母相同则正常比较」「基线缺少分母信息时保守处理」

## 5. 拦截：降级率进入验收判定

- [x] 5.1 ~~新增 `DegradationSettings`~~ —— 已在 1.2 落地（含 `[0, 1]` 区间校验与 settings 单测，见该任务下的实施调整说明）
- [x] 5.2 扩展 `ThresholdEvaluator` 使降级率参与 `acceptance_status`，超标即 `fail`、`--exit-on-fail` 退出码非零。配套测试覆盖「降级率超标判失败」「降级率达标不影响原有判定」「门槛可配置」「指标阈值通过但降级率超标」

## 6. 收口

- [x] 6.1 `pytest tests/unit -v` 全绿；`openspec validate --all` 通过；把归因结论与「降级率现值」回写到 `CLAUDE.md` § 已知陷阱和 `openspec/config.yaml` § 已知陷阱（该处已有本变更的前置记录，需更新为最终结论）
  > 2026 passed / 2 skipped；`openspec validate --strict` 通过；两处陷阱清单已更新（含 `max_tokens` 否证、语言错乱主因、限流伪装成降级、RAGAS 吞响应四条）
