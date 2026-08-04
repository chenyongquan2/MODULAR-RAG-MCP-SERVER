# Settings Contract: `evaluation.screening_llm`

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04
**对称参照**: [001-rag-acceptance/contracts/settings.evaluation.schema.md](../../001-rag-acceptance/contracts/settings.evaluation.schema.md)

新增配置节,结构与既有 `evaluation.judge_llm` 对称,经同一套 `_build_sub_settings` 装配([settings.py:559](../../../src/core/settings.py))。

---

## 1. YAML 形态

```yaml
evaluation:
  # ... 既有 backends / judge_llm / embedding / acceptance_thresholds 不变 ...

  # 【新增】金标精修的预筛模型。必须与 judge_llm 异源(FR-002)
  screening_llm:
    provider: ""                  # glm / azure / openai / ollama / deepseek
    model: ""
    api_key: ""                   # 支持 ${VAR} / ${VAR:-default}
    base_url: ""
    temperature: 0.0
    request_timeout_sec: 60

    # 路由与门控阈值(全部可调,理由见 spec Assumptions)
    keep_threshold: 0.80          # keep 判定 ≥ 此值则自动保留
    drop_threshold: 0.80          # drop 判定 ≥ 此值则自动丢弃
    borderline_ratio_warn: 0.40   # borderline 占比超此值告警(FR-011)
    sample_ratio: 0.10            # 抽样比例(FR-006,源自 SC-002)
    compliance_gate: 0.90         # 合规率门控(FR-007,源自 SC-002)
```

---

## 2. 字段约束

| 字段 | 类型 | 默认 | 校验 |
|---|---|---|---|
| `provider` | str | `""` | auto 模式下非空,且必须是 `LLMFactory` 已注册的 provider |
| `model` | str | `""` | auto 模式下非空 |
| `api_key` | str | `""` | 空时沿用既有 `EMBEDDING_API_KEY`/`LLM_API_KEY` 注入规则 |
| `base_url` | str | `""` | 可选 |
| `temperature` | float | `0.0` | `0.0 ≤ x ≤ 2.0` |
| `request_timeout_sec` | int | `60` | `> 0` |
| `keep_threshold` | float | `0.80` | `0.0 < x ≤ 1.0` |
| `drop_threshold` | float | `0.80` | `0.0 < x ≤ 1.0` |
| `borderline_ratio_warn` | float | `0.40` | `0.0 < x ≤ 1.0` |
| `sample_ratio` | float | `0.10` | `0.0 < x ≤ 1.0` |
| `compliance_gate` | float | `0.90` | `0.0 < x ≤ 1.0` |

---

## 3. 校验时机(宪法 Rule III 快速失败)

| 校验 | 时机 | 失败行为 |
|---|---|---|
| 数值区间 | `load_settings()` 期(与既有 `evaluation.*` 校验同处) | 抛 `ValueError` |
| `provider` / `model` 非空 | **仅 `--auto-mode` 时**在 CLI 入口校验 | 退出码 `2` |
| provider 已注册 | 由 `LLMFactory.create()` 抛 `ValueError` | 退出码 `2` |
| 与 `judge_llm` 异源 | CLI 入口,读 candidate 后 | 退出码 `2` |

> **为何 `provider`/`model` 非空不在 `load_settings()` 强校验**:默认交互模式不需要预筛模型,若在加载期强制要求,会让所有未配置该节的既有用法(含全部现有测试与 `python main.py`)直接启动失败 —— 违反 FR-004。这与既有 `judge_llm` 的处理一致:[settings.py:715](../../../src/core/settings.py) 也是**仅当 `backends` 含 `ragas` 时**才要求 `judge_llm.provider/model` 非空。

---

## 4. 异源标识

新增 `get_screening_identifier(settings) -> str`,与既有 [`get_judge_identifier`](../../../src/observability/evaluation/_ragas_wrappers.py) 对称:

```text
f"{settings.evaluation.screening_llm.provider}:{settings.evaluation.screening_llm.model}"
```

同源判据为**完整标识串相等**,不是 provider 相等。

**实证理由**:现有 candidate 的实际值是 `"glm:minimax/minimax-m2.7"` —— provider 名义为 `glm`,model 经 OpenAI 兼容端点路由到 minimax。若只比 provider,`glm:glm-4.6` 会被误判同源而遭拒绝,而它是真正的异源模型。详见 [research.md § Decision 2](../research.md)。

---

## 5. 配置示例(基于现有真实数据)

已知合成端为 `glm:minimax/minimax-m2.7`,则以下配置合法:

```yaml
evaluation:
  screening_llm:
    provider: glm
    model: glm-4.6          # 标识 "glm:glm-4.6" ≠ "glm:minimax/minimax-m2.7" → 异源 ✅
    api_key: ${GLM_API_KEY}
```

以下配置会被拒绝(退出码 `2`):

```yaml
evaluation:
  screening_llm:
    provider: glm
    model: minimax/minimax-m2.7   # 标识完全相同 → 同源 ❌
```
