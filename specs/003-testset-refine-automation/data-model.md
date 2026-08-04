# Phase 1 Data Model: 金标精修自动化

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04

字段结构均以现有真实数据核对(`tests/fixtures/candidates/zh_smoke_v2.json`,10 条用例)与现有代码为准。

---

## 1. 输入:Candidate 文件(既有结构,本 feature 不改)

由 `scripts/synthesize_testset.py` 产出。**只读,不修改**。

```text
{
  "_schema_version": 1,
  "language": "zh",
  "_synthesis_metadata": {
    "generator": "ragas.testset.TestsetGenerator",
    "ragas_version": "0.1.21",
    "judge_llm_identifier": "glm:minimax/minimax-m2.7",   ← 同源检测的判据来源
    "embedding_identifier": "openai:text-embedding-3-small",
    "distribution": {...},
    "synthesized_at": "..."
  },
  "test_cases": [ CandidateCase, ... ]
}
```

### CandidateCase(既有)

| 字段 | 类型 | 说明 | 精修后保留 |
|---|---|---|---|
| `query` | str | 问题 | ✅ |
| `ground_truth` | str | 参考答案 | ✅ |
| `expected_chunk_ids` | list[str] | 预期命中 chunk 标识 | ✅ |
| `expected_sources` | list[str] | 预期来源文档 | ✅ |
| `tags` | dict | `content_type` / `difficulty` / `language` / `doc_version` | ✅ |
| `_synth_contexts` | list[str] | 合成期上下文,仅供人工预览 | ❌ 由 `_strip_synth_artifacts` 剥离(前缀 `_synth` 一律剔除) |

> **约束**:本 feature 不新增 case 级字段。预筛判定不写回 case 内部 —— 否则会污染金标结构并触发既有测试的键集合断言。判定结果只进汇总审计字段。

---

## 2. 中间态:ScreeningVerdict(新增,不落盘)

单条用例的机器判定结果。仅存在于运行期内存,用于路由决策与审计汇总。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `decision` | enum | `keep` \| `drop` \| `borderline` | 三态结论(FR-001) |
| `confidence` | float | `0.0 ≤ x ≤ 1.0` | 置信度;超出区间视为非法 → 降级为 `borderline`(FR-008) |
| `reason` | str | 可为空 | 判断理由;人工处置 borderline 时作为上下文展示 |
| `case_index` | int | `≥ 0` | 对应 candidate 中的用例序号,用于关联 |

**状态迁移(路由规则)**:

```text
LLM 返回可解析 JSON ──┬─ decision=keep  且 confidence ≥ keep_threshold  ──→ 自动保留
                      ├─ decision=drop  且 confidence ≥ drop_threshold  ──→ 自动丢弃
                      └─ 其余(含置信度不达阈值)                        ──→ borderline → 人工
LLM 调用失败 / 返回不可解析 / 字段非法 ────────────────────────────────→ borderline → 人工
```

> 关键不变式:**任何异常路径都只能流向 borderline**,不得流向自动保留或自动丢弃(FR-008)。这保证机器的不确定性只会增加人工量,不会污染金标。

---

## 3. 输出:金标文件(既有结构 + 1 个新增字段)

```text
{
  "_schema_version": 1,                    ← 必须保持 1(既有测试 line 183 断言)
  "language": "zh",
  "version": "v1.0" | "v0.9-partial",
  "created_at": "...",
  "source_corpus_collection": "...",
  "_refine_summary": {                     ← 键名与语义不可变(既有测试多处下标断言)
    "keep": int, "edit": int, "drop": int, "skip": int
  },
  "_review_metadata": { ReviewMetadata },  ← 【本 feature 新增】仅 auto 模式下写入
  "test_cases": [ ... ]
}
```

### ReviewMetadata(新增)

对应 FR-005 与 SC-005:仅凭金标文件自身即可回答「多少条机器决定、用哪个模型、阈值多少、抽样合规率多少」。

| 字段 | 类型 | 说明 | 对应需求 |
|---|---|---|---|
| `auto_decided` | int | 机器自动决策数(自动保留 + 自动丢弃) | FR-005 |
| `human_reviewed` | int | 经人工处置数(borderline + 抽样自检) | FR-005 |
| `dropped` | int | 丢弃总数(机器 + 人工) | FR-005 |
| `screening_llm_identifier` | str | `"<provider>:<model>"`,与合成端标识同格式 | FR-005 |
| `synthesis_llm_identifier` | str | 从 candidate 复制,便于一眼看出异源关系 | FR-002 审计 |
| `thresholds_snapshot` | dict | 当次生效的阈值(keep / drop / borderline 上限 / 合规率门控) | FR-005 |
| `borderline_ratio` | float | borderline 占比,用于复核 FR-011 告警是否触发 | FR-011 |
| `compliance` | object \| null | 抽样自检结果;未执行自检时为 `null` | FR-006 |
| `partial` | bool | 是否为中断产生的部分结果 | FR-005 |
| `warnings` | list[str] | 当次触发的告警(同源无法确认 / borderline 超限 / 合规率不达标) | FR-007, FR-011 |

**不变式**:`auto_decided + human_reviewed == 输入用例总数`(非 partial 时)。`dropped ≤ 该总数`。

### ComplianceSample(嵌在 `ReviewMetadata.compliance`)

| 字段 | 类型 | 说明 | 对应需求 |
|---|---|---|---|
| `sampled_case_indices` | list[int] | 实际抽中的用例序号(不固定 seed,靠记录结果保证可复核) | research § D7 |
| `sample_size` | int | `max(1, ceil(保留数 × 0.10))`,保留数为 0 时为 `0`(不抽样) | FR-006 |
| `compliant` | int | 判定合规条数 | FR-006 |
| `compliance_rate` | float | `compliant / sample_size`;`sample_size == 0` 时为 `None` | FR-006 |
| `gate_passed` | bool | `compliance_rate ≥ 门控阈值(默认 0.90)` | FR-007 |
| `auto_kept_sampled` | int | 抽中用例中**由机器自动保留**的条数 | SC-006 |
| `auto_kept_compliant` | int | 上述子集中判定合规的条数 | SC-006 |
| `auto_kept_noncompliance_rate` | float \| null | `1 - auto_kept_compliant / auto_kept_sampled`;子集为空时为 `null` | SC-006 |

> **为什么需要后 3 个字段** —— 这是 analyze 阶段发现的设计缺口:
>
> SC-006 要求「**机器自动保留的**用例中,经抽样复核不合规的比例 ≤ 10%」,而抽样池按 Assumptions 是**全部保留用例**(为与 SC-002 口径对齐)。若只记 `compliance_rate`,SC-006 **无法计算** —— 分不清抽中的那几条是机器决定的还是人工确认过的。
>
> 因此抽样结果必须额外按「决策来源」拆分出 auto-kept 子集。`compliance_rate` 服务 SC-003(全量口径),`auto_kept_noncompliance_rate` 服务 SC-006(机器准确性口径),两者并存不冲突。

#### 决策来源的追踪方式(不污染 case 结构)

计算上述拆分需要知道每条保留用例的决策来源(机器自动保留 / 人工保留)。**不在 case 内部写 provenance 字段** —— 那会改变金标的 case 结构并触发既有测试的键集合断言(见 § 1 约束)。

改为在运行期维护 `case_index → provenance` 的内存映射:`screen_all()` 已按 `case_index` 产出 verdict 列表,auto 流程再记录哪些 index 走了人工。抽样时按 index 反查来源即可。落盘只落聚合数字,不落逐条来源。

---

## 4. 配置实体:ScreeningLLMSettings(新增)

与既有 `JudgeLLMSettings`([settings.py:274](../../src/core/settings.py))对称,同样经 `_build_sub_settings` 装配。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `provider` | str | `""` | LLM provider;auto 模式下为空则快速失败(Rule III) |
| `model` | str | `""` | 模型标识 |
| `api_key` | str | `""` | 支持 `${VAR}` 注入 |
| `base_url` | str | `""` | 可选,OpenAI 兼容端点 |
| `temperature` | float | `0.0` | 判定应尽量确定,与 Judge 同取 0.0 |
| `request_timeout_sec` | int | 同 Judge 默认 | 单次调用超时 |
| `keep_threshold` | float | `0.80` | ≥ 此值的 keep 判定自动保留 |
| `drop_threshold` | float | `0.80` | ≥ 此值的 drop 判定自动丢弃 |
| `borderline_ratio_warn` | float | `0.40` | borderline 占比超此值告警(FR-011) |
| `compliance_gate` | float | `0.90` | 抽样合规率门控(FR-007,来自 Feature-001 SC-002) |
| `sample_ratio` | float | `0.10` | 抽样比例(FR-006,来自 SC-002) |

> 阈值全部配置化而非写死,理由见 spec Assumptions「置信度阈值需要校准」—— 不同模型的置信度标度不可互换,这与 Feature-001 已确立的「换 Judge 后阈值失效」结论一致。
