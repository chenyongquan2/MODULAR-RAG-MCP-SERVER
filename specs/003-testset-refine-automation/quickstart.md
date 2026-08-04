# Quickstart: 金标精修自动化

**Feature**: 003-testset-refine-automation
**Date**: 2026-08-04

面向「已合成 candidate,要产出金标」的使用者。实现完成后本文即为操作手册。

---

## 前置:配置预筛模型

在 `config/settings.yaml` 的 `evaluation` 节下新增 `screening_llm`,**模型标识必须与 `judge_llm` 不同**(合成端用的是 `judge_llm`):

```yaml
evaluation:
  judge_llm:
    provider: glm
    model: minimax/minimax-m2.7      # ← 合成端(既有配置)

  screening_llm:
    provider: glm
    model: glm-4.6                   # ← 预筛端,与上面不同即可
    api_key: ${GLM_API_KEY}
```

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

> 告警不阻止文件写出(FR-007),所以看到合规率告警时要自己拦住,别直接拿去跑验收。

---

## 阈值需要校准

`keep_threshold` / `drop_threshold` 的默认值 `0.80` 是初始猜测。**不同模型的置信度标度不可互换** —— 换预筛模型后阈值必须重新校准,这与 Feature-001 已确立的「换 Judge 后阈值失效」是同一回事。

校准办法:先跑一轮,看 `_review_metadata.borderline_ratio`。

- 远高于 20%(如 > 40%,会触发告警)→ 阈值太严,调低
- 接近 0% → 阈值太松,机器几乎全自动决策,抽样合规率会暴露质量问题

每份金标都带 `thresholds_snapshot`,所以历史金标始终可追溯当时的判定条件。
