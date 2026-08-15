## Why

中文金标只有 **6 条**，而 SC-002 要求每语种 ≥ 40。任何中文侧的检索结论都站不住 —— 上一个变更（`retriever-agnostic-golden-labels`）的中文数据就只能当噪声看，重排 A/B 的结论完全靠英文 42 条撑着。

**但真正的阻塞不是「条数不够」，而是一处从未被识别的静默失效。**

项目记录里写的是「`minimax/minimax-m2.7` 无法完成 RAGAS `adapt(language=chinese)`，输出非 JSON」。实测下来事实更糟：

```
logs/ragas_adapt_cache/chinese/
  answer_formulate.json       4493B   CJK 字符 0  (0.0%)
  find_relevant_context.json  2702B   CJK 字符 0  (0.0%)
  keyphrase_extraction.json   1633B   CJK 字符 0  (0.0%)
  rewrite_question.json       3193B   CJK 字符 0  (0.0%)
  score_context.json          4332B   CJK 字符 0  (0.0%)
```

五个「中文」prompt 文件里**一个中文字符都没有**。所以：

1. **adapt 没有抛异常** —— 它「成功」了，只是产出的是未翻译的英文。现有的 fail-fast（2 次重试后抛 `RuntimeError`）**从来没被触发过**，因为它只捕获异常，不校验产物
2. **这份坏结果被写进了磁盘缓存**（2026-04-28）。那个缓存本是为了绕过「LLM 输出不稳定」的双保险，结果把不稳定的产物**永久固化**了
3. 于是**后续任何一次合成都会从磁盘读到英文 prompt**，无论换什么模型都一样 —— 47 条候选里 33 条因 `language_mismatch_en_query_in_zh_set` 被丢，根源在此

这是本项目反复撞见的同一类病：**看起来生效、实际没生效、而且不报错**。与 `top_m` 死配置、`--collection` 死参数、`max_tokens=200` 饿死判定同源。

顺带一个直接相关的修正：项目当初把 judge 从 `glm-4.7` 换成 minimax，理由是「GLM 系对 JSON schema 遵从差」。而 `retriever-agnostic-golden-labels` 证明了——至少在标注任务上——「不遵从 JSON」的真实原因是 **`max_tokens` 给少了**（367 字符的 chunk 就返回空响应），给足后同一个 GLM 模型 1800+ 次判定输出全部干净可解析。**所以「GLM 做不了中文 adapt」这个结论很可能是同一个误诊**，值得在本变更里实测。

语料侧没有问题：抽样 20000 条 chunk，**16274 条（81.4%）是中文**。

## What Changes

- **adapt 产物必须校验目标语言**：翻译完成后检查产出的 prompt 确实包含目标语言字符，不达标即失败，**并且不写缓存**。这是本变更的核心 —— 没有它，换模型、清缓存都只是治标
- **被污染的缓存必须能被识别与清除**：现有缓存无版本、无来源、无校验标记，无法判断它是好是坏。新增缓存元数据（产出模型标识、校验结果、写入时间），并提供强制重建的手段
- **重新选择合成端模型**：在真实 adapt 任务上实测候选模型能否完成中文翻译，用数据而非既有印象定夺
- **合成 → 精修 → 标注全链路跑通中文**，目标 ≥ 40 条：合成用 `synthesize_testset.py`，精修用 `refine_testset.py --auto-mode`（异源预筛），标注用**第二代** `label_golden_chunks.py`（多路池化 + LLM 分级判定）
- **BREAKING（评估语义）**：新的中文金标条数从 6 变为 ≥ 40 且标注方式为 `pooled-llm-judged`，**与现有中文基线完全不可比**。跨代由报告的 `delta_comparable: false` 标注

## Capabilities

### New Capabilities

- `evaluation/testset-synthesis`: 金标候选合成能力 —— 目标语言适配的正确性保证、适配产物的缓存契约、语种一致性校验。

### Modified Capabilities

无。`evaluation/golden-labels` 覆盖的是「哪些 chunk 算正确答案」（标注），本能力覆盖的是「问题从哪来」（合成），两者不重叠。

## Impact

**代码**
- `src/observability/evaluation/testset_synthesizer.py`：adapt 产物校验、缓存元数据与失效判定
- `config/settings.yaml` + `src/core/settings.py`：合成端语言校验相关配置项
- 可能需要调整 `evaluation.judge_llm`（合成端），届时 `acceptance_thresholds` 需重新校准

**数据**
- `logs/ragas_adapt_cache/chinese/`：**现存内容已确认无效，需删除**
- `tests/fixtures/golden_test_set_zh.json`：保留（第一代，6 条），**不覆盖**
- 新增 `golden_test_set_zh_v2.json`（≥ 40 条，`pooled-llm-judged`）

**成本**
- 合成：RAGAS TestsetGenerator 对 ~100 条候选，含 adapt（单次约 5 分钟）
- 精修：`--auto-mode` 异源预筛，borderline 需人工
- 标注：按英文实测比例，40 条 × 约 34 候选 ≈ **1400 次判定调用**
- 网关实测存在常态性中断，全链路需可续跑（标注侧已具备）

## 验收判据

**主判据是语种一致性，不是检索指标** —— 本变更产出的是评估资产，不是检索改进：

1. **adapt 产物确实是中文**：缓存文件的 CJK 字符占比超过阈值；不达标时**失败且不落盘**
2. **合成候选的语种一致率**：`language_mismatch` 类丢弃比例显著低于第一代的 33/47（70%）。这是 adapt 是否真的修好的直接证据
3. **最终条数 ≥ 40**（SC-002）
4. **标注质量**：与纯 dense top-K 的 Jaccard 应落在英文（0.406）/ 中文 6 条（0.328）的量级，若接近 1.0 说明池化或判定未生效
5. 单元测试全绿（硬约束 7）

**评估集合**：`default_text-embedding-v4`（含全部语料）。不得指向 `mt5_docs_chinese` —— 中英金标存在跨语言匹配，分语言集合会触发 `chunk_id_validation` 失败。

## Non-goals

- **不追求「中文结论与英文一致」**。扩容后中文侧可能得出与英文不同的结论（例如重排在中文上无效），那是**有价值的发现**，不是失败。上一个变更已实测到跨语言压分现象（中文 query 对语义等价的英文答案只得 0.2973 vs 同语言 0.9998）
- **不重跑英文金标**。英文 42 条已完成，本变更只补中文
- **不做人工级 ground truth**。沿用第二代的 LLM 判定 + 跨模型/人工抽检，局限与上一个变更相同
- **不改 `custom_evaluator.py` 的指标公式**
- **不修 RAGAS 上游**。若某模型确实无法完成 adapt，换模型而不是改 RAGAS
- **不把第一代中文 6 条并入新集合**。两代标注口径不同，混在一起就再也分不清哪条是怎么来的；旧文件原样保留
- **不顺手扩容英文**。英文已达标，混进来会让本变更的验收判据失焦
- **不做多语种泛化**（日文等）。`lang_to_ragas` 映射留着可扩，但本次只验证中文
