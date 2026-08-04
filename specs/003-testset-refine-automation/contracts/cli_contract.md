# CLI Contract: `scripts/refine_testset.py`(改造后)

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04
**基线契约**: [001-rag-acceptance/contracts/cli_contracts.md § 3](../../001-rag-acceptance/contracts/cli_contracts.md)

本文件只描述**相对 Feature-001 契约的增量**。未提及的部分一律保持原样(FR-004)。

---

## 1. 参数

### 既有参数(不变)

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input <path>` | ✅ | candidate JSON 路径 |
| `--output <path>` | ❌ | 默认 `tests/fixtures/golden_test_set_<lang>.json` |
| `--mode <interactive\|batch>` | ❌ | 默认 `interactive`。**语义不变** |

### 新增参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--auto-mode` | 关闭 | 启用异源 LLM 预筛 + borderline 路由。**不加该参数时行为与改造前完全一致**(FR-004) |
| `--allow-same-source` | 关闭 | 仅在无法确认异源(candidate 缺 `judge_llm_identifier`)时,显式承担风险继续。**不能**用于绕过已确认的同源(FR-002 仍硬失败) |
| `--skip-compliance-sample` | 关闭 | 跳过抽样自检。跳过时 `_review_metadata.compliance` 为 `null` 且记入 `warnings` |

> **向后兼容判据**:不带任何新增参数时,不读取 `evaluation.screening_llm` 配置、不发起任何 LLM 调用、输出不含 `_review_metadata` 字段。

---

## 2. 退出码

| 码 | 条件 | 状态 |
|---|---|---|
| `0` | 精修完成,金标已写出 | 既有 |
| `1` | 输入文件不存在或非法 JSON | 既有 |
| `130` | 用户 Ctrl-C(进度部分保存) | 既有 |
| `2` | **新增** —— auto 模式前置条件不满足:`evaluation.screening_llm.provider/model` 未配置,或检测到与合成端同源(FR-002) | 新增 |
| `3` | **新增** —— auto 模式下预筛模型整体不可用(如凭据失效、网络不可达),已明确失败而非静默降级(spec Edge Cases) | 新增 |

> 退出码 `2` / `3` 仅在 `--auto-mode` 下可能出现,不影响既有默认路径的退出码契约。
>
> **合规率不达标不改变退出码** —— 按 FR-007 只告警、仍写出文件。若将来要用作 CI 门控,需另行决定新增退出码(spec FR-007 已显式标注为待定项)。

---

## 3. 行为契约

### 3.1 auto 模式流程

```text
1. 加载 settings,校验 evaluation.screening_llm.provider/model 非空   → 否则 exit 2
2. 读 candidate,取 _synthesis_metadata.judge_llm_identifier
   ├─ 与预筛标识相等                    → exit 2(同源,FR-002)
   ├─ 缺失/为空 且无 --allow-same-source → exit 2 并提示该参数
   └─ 其余                              → 继续
3. 逐条预筛 → ScreeningVerdict(异常一律降级 borderline,FR-008)
   └─ 全部调用均失败                    → exit 3
4. 自动保留 / 自动丢弃 / borderline 交人工(复用既有 y/e/d/s/q 交互)
5. borderline 占比 > borderline_ratio_warn → 记 warning(FR-011)
6. 抽样自检(除非 --skip-compliance-sample)
   └─ 合规率 < compliance_gate           → 记 warning(FR-007),不改退出码
7. 写出金标(含 _review_metadata)        → exit 0
```

### 3.2 stdout / stderr 分工

沿用既有约定:交互提示与用例预览走 stdout(已强制 UTF-8);告警与诊断信息走 stderr。`src/` 侧模块零 `print()`,日志经 `observability.logger` 输出 stderr(宪法 Rule V)。

### 3.3 中断语义

auto 模式下于 borderline 人工处置期间 Ctrl-C:已完成的自动决策与人工决策全部保留,`version` 标为 `v0.9-partial`,`_review_metadata.partial = true`,退出码 `130`。与既有中断行为一致(FR-010)。

---

## 4. 输出契约

见 [data-model.md § 3](../data-model.md)。要点:

- `_schema_version` 保持 `1`
- `_refine_summary` 的 `keep` / `edit` / `drop` / `skip` 四键名称与语义不变
- `_review_metadata` 为**新增可选字段**,仅 auto 模式写入;默认模式下不出现

---

## 5. 契约测试要点

| 场景 | 断言 |
|---|---|
| 不带 `--auto-mode` | 无 LLM 调用;输出无 `_review_metadata`;既有测试全过 |
| 同源 | 退出码 `2`;不写出文件 |
| 缺 `judge_llm_identifier` 无豁免参数 | 退出码 `2`;提示 `--allow-same-source` |
| 预筛返回非法 JSON | 该用例进 borderline,不静默处置 |
| 全部预筛调用失败 | 退出码 `3` |
| 保留数 < 10 | 抽样数为 1,不跳过自检 |
| 合规率 < 门控 | 有 warning;退出码仍 `0`;文件已写出 |
