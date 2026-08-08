# Quickstart: 金标精修自动化

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04

面向「已合成 candidate,要产出金标」的使用者。实现完成后本文即为操作手册。

---

## 前置:配置预筛模型

在 `config/settings.yaml` 的 `evaluation` 节下配置 `screening_llm`,**模型标识必须与 `judge_llm` 不同**(合成端用的是 `judge_llm`):

```yaml
evaluation:
  judge_llm:
    provider: glm
    model: minimax/minimax-m2.7      # ← 合成端(既有配置)

  screening_llm:
    provider: glm
    model: z-ai/glm-5.2-free         # ← 预筛端,与上面不同即可
    api_key: ${GLM_API_KEY}
    base_url: ${GLM_BASE_URL}
```

> **model id 要带 `z-ai/` 前缀**(与顶层 `llm.model` 同理)—— finpoints 网关的上游代理如此要求。列出全部可用值:
>
> ```bash
> curl -s -H "Authorization: Bearer $GLM_API_KEY" "$GLM_BASE_URL/models" | python -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data']]"
> ```
>
> 上面这份配置**已实测可用**(2026-08-08,`z-ai/glm-5.2-free` 为公司网关免费额度,预筛约 50 次调用成本为 0)。

想确认当前 candidate 的合成端标识:

```bash
python -c "import json;print(json.load(open('tests/fixtures/candidates/zh_smoke_v2.json',encoding='utf-8'))['_synthesis_metadata']['judge_llm_identifier'])"
```

---

## 用法一:自动模式(推荐)

```bash
python scripts/refine_testset.py --input tests/fixtures/candidates/zh_smoke_v2.json --auto-mode
```

会发生什么:

1. 逐条请预筛模型判定「保留 / 丢弃 / 存疑」
2. 高置信度的保留与丢弃**自动完成**,不打扰你
3. 只有「存疑」用例弹出既有的 `[y]keep / [e]edit / [d]drop / [s]skip / [q]quit` 提示
4. 收尾时随机抽 10% 保留用例请你确认结构合规性
5. 写出金标,附带 `_review_metadata` 审计记录

预期:约 40-50 条用例,人工只需处理 10-20% 存疑项 + 抽样 4-5 条,总计 ≤ 15 分钟。

**实测机器耗时**(2026-08-08,`z-ai/glm-5.2-free`):**11-16 秒/条**,随上下文长度浮动(smoke 集 10.7s,zh.json 47 条实测 15.5s)。故 47 条的预筛阶段约 **12 分钟**。这段时间无需人工看守 —— 只有预筛跑完、进入 borderline 处置后才需要你。

---

## 用法二:保持原有全交互(默认)

```bash
python scripts/refine_testset.py --input <candidate.json>
```

**行为与改造前完全一致** —— 逐条确认、不调用任何 LLM、输出不含 `_review_metadata`。已有习惯或不想花 LLM 成本时用这个。

---

## 看审计记录

```bash
python -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(json.dumps(d.get('_review_metadata'),ensure_ascii=False,indent=2))" tests/fixtures/golden_test_set_zh.json
```

输出可回答四个问题(SC-005):多少条机器决定、用的哪个预筛模型、当时阈值多少、抽样合规率多少。

---

## 常见情况

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 `2`,提示同源 | 预筛模型标识与合成端完全相同 | 换 `screening_llm.model` |
| 退出码 `2`,提示缺 `judge_llm_identifier` | candidate 太旧,没记合成端标识 | 确认确实异源后加 `--allow-same-source` |
| 退出码 `2`,提示未配置 | `screening_llm.provider/model` 为空 | 补配置,或去掉 `--auto-mode` 走默认模式 |
| 退出码 `3` | 预筛模型整体不可用(凭据/网络) | 修凭据,或去掉 `--auto-mode` |
| 告警「borderline 占比过高」 | 预筛没产生效益,已退化为准全人工 | 调 `keep_threshold`/`drop_threshold`,或换预筛模型 |
| 告警「合规率未达 90%」 | 抽样发现结构问题 | **不要**直接把该金标用于验收;回查合成质量或调阈值 |
| 告警「overwriting existing golden set ... compliance rate was N%」 | 输出路径已有金标,本次会覆盖 | 对比新旧合规率再决定。注意抽样有随机性,单次数值低不必然代表质量差 |
| 审计里 `compliance: null` + 「skipped」告警 | 用了 `--skip-compliance-sample` | 该金标**未经质量门控**,别当作已验收 |
| 审计里 `compliance: null` + 「partial result」告警 | 中途 `q` 或 Ctrl-C 退出 | 半成品不做抽样;补完剩余用例后重跑 |

> 告警不阻止文件写出(FR-007),所以看到合规率告警时要自己拦住,别直接拿去跑验收。

### 中断了怎么办

auto 模式下按 `q` 或 Ctrl-C,**已完成的决策不会丢** —— 文件照常写出,标记 `version: v0.9-partial`,审计里 `partial: true`。`q` 的退出码是 `0`(正常保存退出),Ctrl-C 是 `130`。两种情况都会跳过抽样自检。

---

## ⚠️ auto 模式与 100% 人工精修的质量差距

2026-08-08 实测对比(用确定性规则扫描结构缺陷):

| 文件 | 有缺陷用例 | 产出方式 |
|---|---|---|
| `candidates/en.json` | ~13 / 48 | 合成原始输出 |
| `golden_test_set_en.json` | **1 / 42** | Feature-001 的**逐条 100% 人工确认** |
| `candidates/zh.json` | 43 / 47 | 合成原始输出 |

**逐条人工确认曾把合成缺陷清得很干净。** 早期版本的 auto 模式漏掉了其中一大类 —— 合成模型会把自己的脚手架(`**Question:**`、`Based on the given context…`)甚至答案本身写进 `query` 字段,而预筛只作语义判断,反而给出 0.85 "Question is self-contained"。

**已修复**:提示词新增「判据 1:QUESTION 字段必须只含问题本身」,要求最先机械检查。实测对 6 条已知缺陷全部 drop(置信度 0.98-1.00),3 条良好用例仍 keep,无误伤。

**但这条经验值得记住**:预筛模型擅长语义判断,不擅长发现「字段被污染」这类结构问题 —— 因为它读到的就是被污染后的内容,看上去仍然通顺。换预筛模型后建议用同类缺陷回归一次,别默认新模型也会查。

## ℹ️ zh 金标当前的已知限制

`candidates/zh.json` 有 **40/47 条 query 是纯英文**。这不是精修阶段的问题,而是 `config/settings.yaml` 已记录的上游缺陷:

> minimax 无法完成 RAGAS adapt(中文 prompt 翻译需返 valid JSON),中文金标合成被 deferred

**不要在精修阶段用机器翻译修补** —— 那会让金标来源既非合成产出、也非人工撰写,不可追溯,还会掩盖上游问题。等 zh 合成修好后重新合成。

## 阈值需要校准

`keep_threshold` / `drop_threshold` 的默认值是初始猜测。**不同模型的置信度标度不可互换** —— 换预筛模型后阈值必须重新校准,这与 Feature-001 已确立的「换 Judge 后阈值失效」是同一回事。

校准办法:先跑一轮,看 `_review_metadata.borderline_ratio`。

- 远高于 20%(如 > 40%,会触发告警)→ 阈值太严,调低
- 接近 0% → 阈值太松,机器几乎全自动决策,质量全靠抽样自检兜底

### 实测校准记录(2026-08-08,`z-ai/glm-5.2-free`,zh.json 47 条)

在 47 条真实用例上扫描 `keep_threshold`(`drop_threshold` 固定 0.80):

| `keep_threshold` | borderline 占比 | 评价 |
|---|---|---|
| 0.80 | 4.3% | 太松,几乎全自动 |
| 0.85 | 6.4% | 仍偏松 |
| **0.90**(当前值) | **10.6%** | ✅ 落进预期 10-20% 区间 |
| 0.95 | 29.8% | 偏严,接近 40% 告警线 |
| 1.00 | 51.1% | 退化为准全人工 |

模型原始判定:`keep 40 / drop 6 / borderline 1` —— 有 6 条被主动丢弃,说明预筛确实在过滤而非橡皮图章。

置信度分布:

```
1.00 ██████████████████ 18      0.85 ██  2
0.95 ███████████        11      0.80 ██  2
0.90 ████████████       12      0.75 █   1
                               0.60 █   1
```

按 0.90 估算单语种人工量:约 5 条 borderline + 抽样 4 条 ≈ **9/47 ≈ 19%**,满足 SC-002 的 ≤ 25%。

### ⚠️ 同一输入的判定并不稳定

**`temperature: 0.0` 在该网关上不保证确定性。** 对同一份 candidate 连跑三轮,置信度分布每轮都不同(10 条样本):

| 轮次 | 分布 |
|---|---|
| 1 | 1.00×2, 0.95×6, 0.90×1, 0.80×1 |
| 2 | 1.00×3, 0.95×2, 0.90×3, 0.85×2 |
| 3 | 1.00×3, 0.95×2, 0.90×3, 0.85×2 |

两点推论:

1. **小样本上的占比不可当结论**。上面 47 条的扫描才是定阈值的依据;10 条那轮曾给出 0%/20% 两个截然不同的数,纯属样本太小。
2. **重复运行会得到不同的自动决策集合**。这正是 `warn_if_overwriting()` 存在的理由 —— 覆盖既有金标前会把旧的合规率摆出来对比,别让偶然性把好金标换成差的。

每份金标都带 `thresholds_snapshot`,所以历史金标始终可追溯当时的判定条件。
