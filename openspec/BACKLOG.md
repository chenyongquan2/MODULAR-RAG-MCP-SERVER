# 待办计划表（Backlog）

> **这份文档是什么**：2026-08-24 一次全仓扫描后整理的待办清单，按价值排序分梯队。
> 扫描范围：`openspec/changes/`（1 个在途 + 3 个归档）、`specs/001-005`、`DEV_SPEC.md`、
> `docs/learning/agentic-retrieval-boundary.md` §8.2、`CLAUDE.md` / `config.yaml` § 已知陷阱、
> `config/settings.yaml` 实际生效值、`logs/baselines.json`、`tests/fixtures/`。
>
> **这份文档不是什么**：它不是 OpenSpec 产物，`openspec list` 看不到它。梯队二/三里标了
> 「走 SDD」的项，动手时仍要正常走 `/opsx:propose`。
>
> **怎么用**：一次开一个干净窗口做**一个梯队**，做完再开下一个。每项都写了完成判据，
> 做完把该项标 `[x]` 并把结论回填到本文档对应位置。

---

## ✅ 已修复（2026-08-24）：`CLAUDE.md` 那条过期结论

> 下面这段是 A2 的原始问题描述，**A2 已完成**，`CLAUDE.md` 与 `openspec/config.yaml` 现已一致。
> 保留原文作为「文档不一致会造成真实损失」的记录。

<details>
<summary>原始问题（已解决）</summary>

### ⚠️ `CLAUDE.md` 有一条结论已过期

`CLAUDE.md` 里那条「**⚠️ 金标无法公正评判重排** …… 在换掉金标构造方式之前，本项目没有可用于
评判重排的离线指标」**已被推翻**，但文件至今没改（这就是下面的 A2）。

事实是：`retriever-agnostic-golden-labels`（2026-08-14 归档）换掉了金标构造方式，重排 A/B
**方向翻转** —— 第一代 MRR −0.1246，第二代 **+0.0764**。`openspec/config.yaml` 已更新，
`CLAUDE.md` 没有，两份文档目前互相矛盾。

**后果是真实的**：2026-08-24 的会话里，AI 助手照着 `CLAUDE.md` 给出了「本项目没有能评判重排的
指标」这个错误的战略建议。任何新会话都会被同样误导，直到 A2 做完。

</details>

**A2 实际做的**：`CLAUDE.md` 的标题改为「`dense-top-k` 金标（第一代）无法公正评判重排 ——
但这个局限已被第二代解除」并附两代 A/B 对照表；v1/v2 称呼全部改为标注方式名；
连带修掉一个失效的代码引用（`eval_runner.py:88` → 真实判据在 `:421`）。

---

## 状态核对（每次开新窗口先跑一遍，确认本文档没过期）

```bash
openspec list && git log --oneline -5 && git status --short
```

看当前生效的金标指向：

```bash
grep -A 3 golden_test_sets_by_lang config/settings.yaml
```

---

# 梯队一 · 现在就做（合计 ≈ 1 天）

> **这三项共享 `CLAUDE.md` 与 `openspec/config.yaml`，必须在同一个窗口连续做完，不要拆给多个
> agent 并行** —— 理由见 § 并行指南。

## [x] A2 · 修正 `CLAUDE.md` 的重排结论　`30 min`　✅ 2026-08-24

**为什么排第一**：`CLAUDE.md` 每次会话都被完整加载进上下文。一条过期结论坐在那里，就是一个
持续污染每一次判断的源头，而且这种损失不会记进任何 acceptance.md。性价比全表最高。

**改什么**：

1. 「⚠️ 金标无法公正评判重排」那条 —— 保留「第一代金标 dense 锚定」的诊断（它是对的），
   但必须补上第二代已经翻转了结论。建议改写为「**第一代**金标无法公正评判重排」并附翻转数据。
2. 「金标有两代」那条 —— `openspec/config.yaml:149` 已确立称呼规约：**一律用标注方式名
   （`dense-top-k` / `pooled-llm-judged`），不要用 v1/v2**，因为文件名后缀、JSON 的 `version`
   字段、`_labeling_method` 三者会打架，**只有 `_labeling_method` 是代码判据**
   （`src/observability/evaluation/eval_runner.py:88`，缺失即视为第一代）。
   `CLAUDE.md` 目前还在用 v1/v2 称呼，对齐过来。

**完成判据**：`CLAUDE.md` 与 `openspec/config.yaml` 对「重排是否可评」「金标怎么称呼」两件事
表述一致，不再互相矛盾。

---

## [x] A1 · 收口 `expand-chinese-golden-set` 并归档　`2–3 h`　✅ 2026-08-24

**当前进度**：16 个任务完成 5 个（1.1 / 1.2 / 2.1 / 2.2 / 2.3），3.1 数据已齐但复选框还是 `[~]`。

**决定性实测结果**（`logs/ragas_adapt_probe/summary*.json`，一模型一进程，已绕开 RAGAS
模块级单例污染）：

| 模型 | 耗时 | 产出文件 | CJK 占比 | 抛异常 | 判定 |
|---|---|---|---|---|---|
| `minimax/minimax-m2.7` | 679.9 s | 11 | 0.0% | 否 | FAIL |
| `z-ai/glm-5.2` | 922.9 s | 11 | 0.0% | 否 | FAIL |
| `z-ai/glm-5.2-free` | 769.5 s | 11 | 0.0% | 否 | FAIL |

**三个候选全部做不到**，因此按 tasks.md 的 T-3.3 与 design.md:86 预置的分支收口：

1. 勾掉 3.1（数据已齐）
2. 3.2 判定为「无可用模型」，记录理由
3. 4.1–4.4、5.1–5.3 **随之关闭**（依赖合成能力，已证不可行），在 tasks.md 里显式标注关闭原因，
   不要留成看起来还没做的样子
4. 写 `openspec/changes/expand-chinese-golden-set/acceptance.md`（即任务 5.4）
5. `/opsx:archive`

**5.4 要回写的两条通用教训**（本项收尾的真正价值所在）：

- **缓存会把坏产物永久固化**。2026-04-28 那次 adapt 的英文产物被写进磁盘缓存，此后任何一次
  合成都从磁盘读到英文 prompt，换什么模型都一样。缓存本是为了绕过「LLM 输出不稳定」，
  结果把不稳定的产物永久化了。**缓存必须带来源与校验标记。**
- **只捕获异常检测不出静默失效**。原有 fail-fast 只捕 `RuntimeError`，而真实失败形态是
  **不抛异常但没翻译** —— 它「成功」了。**必须校验产物本身，不能只看有没有报错。**

> 这两条不是 RAGAS 专属。把这个项目的事故排一排：`top_m` 死配置、`--collection` 死参数、
> `max_tokens=200` 饿死判定、CJK 全链路 ASCII-only、chunk_id 两边不相交、adapt 静默不翻译、
> 缓存固化坏产物 —— **七次事故同一个病：看起来生效、实际没生效、而且不报错**。
> 写进 `CLAUDE.md` + `openspec/config.yaml` § 已知陷阱 时，重点写这个模式，别只写 RAGAS。

**顺手做掉的琐碎项**（都在这一趟里，别单独排期）：

- [x] **A3** · `docs/learning/agentic-retrieval-boundary.md` §8.2 回写 T2 gate 结论。当初假设
  「多跳更难」，实测相反：`multi_context` recall **68.9%** > `simple` **40.0%** > `reasoning`
  **25.5%**（`specs/004-retrieval-infra-fix/tasks.md:118`）。
  **规划器的靶子应改为推理类**，笔记里「条件性、取决于 T2」那句至今悬着。
- [x] **A4** · 勾掉 `openspec/changes/archive/2026-08-13-activate-cross-encoder-rerank/tasks.md`
  的任务 4.1。代码早已落实（`src/libs/reranker/cross_encoder_reranker.py:68` 显示 `getattr`
  兜底已删、`batch_size` 从配置读），只是归档时漏勾。
- [x] **A5** · 处置 `golden_test_set_zh_v3.json` —— **D1 已按选项 B 执行**：改名为 `tests/fixtures/_ARTIFACT_contaminated_zh_candidate.json` 并加 `_do_not_use` 标记。选 B 而非删除，是因为 `openspec/config.yaml` 拿它当「文件名 / `version` / `_labeling_method` 三者打架」的实例，删了那条引用就悬空。⚠️ **顺带修掉一个比重命名重要得多的问题**：三份学习笔记在**推荐**拿它去补标注（`docs/learning/rag-evaluation/07-this-project.md` 把这事标为 P1「一次调用换 5 倍分辨率」），而它 25/29 条 query 是英文 —— 照做只会得到一份 86% 英文的「中文金标」。已在三份笔记里加更正块。

**完成判据**：`openspec list` 为空；`acceptance.md` 如实记录三个模型占比；两条教训进了
`CLAUDE.md` 和 `config.yaml`。

### ✅ 实际完成情况（2026-08-24）

已归档至 `openspec/changes/archive/2026-08-24-expand-chinese-golden-set/`，`openspec list` 为空，
delta spec 已同步为主规格 `openspec/specs/evaluation/testset-synthesis/spec.md`（4 条 ADDED 全部落地）。
两条教训 + 第八例已写入 `CLAUDE.md` § 招牌病 与 `config.yaml` § 已知陷阱。

**⚠️ 一个上面这份计划没预料到的发现 —— 招牌病的第八例，就在这个变更内部**：

写 acceptance 时逐条核对 delta spec，发现第三条 ADDED 需求（**合成产物的语种一致性必须被量化**）
**只做了一半**：`language_check.mismatch_ratio` / `summarize_language` 有实现、有单测，
**但没有任何生产路径调用它们**；`synthesis.question_language_mismatch_warn` 被
`load_settings()` 校验取值范围，**然后没有任何代码读它** —— 彻头彻尾的死配置。

**所以上面第 115 行那句「七次事故」现在是八次。** 而第八例最有说服力的地方在于：
它发生在**专门为消灭这个病而立的变更内部**。说明这个病不是「粗心」，而是
「写实现 + 写单测」这套流程**结构上不覆盖「实现有没有被接上」** —— 单测测的是函数，
没人测那条线。**对策**：每个新配置项配一条「改了它，结论就该变」的用例。

已补做（任务 T-2.4）：`_testset_to_candidate` 现在产出
`_synthesis_metadata.language_consistency`，越限告警且措辞指向 adapt 而非语料。
未登记字符集的语言标 `measured: false` 且**不给** `mismatch_ratio` —— 刻意不回落成 `0.0`，
否则「没测」会长得跟「测过且完美」一样（那就是再造一个同病）。
`pytest tests/unit`：**2032 passed / 2 skipped**（补做前 2026）。

---

## [x] B1 + B2 · 切到第二代金标 + 重标基线　`半天`　✅ 2026-08-24

**为什么**：错误传染性最高。现在 `evaluation.golden_test_sets_by_lang` 指向的是**第一代**
（dense 锚定）金标，而这把尺子已被实测证明会给出**方向相反**的结论。不切，则今后每一个
检索侧实验都在一把已知会说谎的尺子上做 —— 这是复利型损失。

**B1 改配置**（`config/settings.yaml`）：

```yaml
evaluation:
  golden_test_sets_by_lang:
    zh: ./tests/fixtures/golden_test_set_zh_v2.json   # 6 条，pooled-llm-judged
    en: ./tests/fixtures/golden_test_set_en_v2.json   # 41 条，pooled-llm-judged
```

- **英文**：`en_v2` 41 条，直接可用，是重排翻转结论的依据。
- **中文**：`zh_v2` 虽只有 6 条，但**问题和第一代是同一批，只是标签重做了**。切过去零成本、
  严格更优（去掉了 dense 锚定）。条数不够是另一个问题（见梯队三 C1），不影响现在就切。

**B2 重标基线**：当前 baseline 是 `80a82405` / `feature-004-T037-en` / 2026-08-10 /
`acceptance_status: fail`，**早于**重排落地、降级治理、`en_v2` 标注 —— 已经完全过时。

```bash
.venv/Scripts/python.exe -u scripts/evaluate.py --pretty --collection default_text-embedding-v4
```

**跑之前注意三件事**：

1. **跨代 delta 会被标 `delta_comparable: false`** —— 这是对的，别把「标注口径变了」读成
   「质量变了」。旧基线保留作「第一代参照」，不要删。
2. **先看 `degraded_case_count`**，再看任何 RAGAS 数字。当前降级率 **54.8%**（23/42），
   是门槛 5% 的 11 倍，意味着 RAGAS 四项目前基本不可用（`custom` 四项不受影响）。
3. **绝对值不可跨代比**：`en_v2` 每 case 均值 14.9 条标签（第一代恒为 5 条），所以 hit_rate
   从 0.69 涨到 0.98 主要是「标签变多了更容易命中」，不是检索变好了。**只有同代内的 delta 有意义。**

**完成判据**：新基线已标；报告里 `_labeling_method: pooled-llm-judged`；`custom` 四项有了
可用于后续对比的同代基准。

### ✅ 已完成（2026-08-24）

**B1 已完成** —— `golden_test_sets_by_lang` 已切到 `zh_v2` / `en_v2`。

⚠️ **上面那条命令有误,别照抄**：`scripts/evaluate.py` **不加 `--lang` 会去跑
`golden_test_set`(4 条占位集)**,不是 41/6 条的真金标。正确写法：

```bash
.venv/Scripts/python.exe -u scripts/evaluate.py --lang en --pretty --collection default_text-embedding-v4
```

**⚠️ 跑第一轮时抓到一个更严重的问题(已修,commit `6859dc3`)**：
`eval_runner._load_test_cases` 构造 meta 时**没拷 `_labeling_method`**,于是报告的
`labeling_method` **恒回落成 `dense-top-k`** —— 也就是说本条的完成判据
「报告里 `_labeling_method: pooled-llm-judged`」**在修之前根本不可能达成**。
连带后果：文档里那条「跨代 delta 会被标 `delta_comparable: false`」在标注方式这一维上
**从未生效过**（实证：`97743b41` / `d08e540d` 跑的是 `en_v2`，报告里都写着 `dense-top-k`）。

**重排翻转结论不受影响** —— 那次 A/B 两臂用的是同一份正确金标，错的只是报告上的标签。
但这是招牌病的**第九例**，且**它连单测都有**：既有 `TestLabelingMethodField` 测的是
「`EvalReport` 收到值后会不会序列化」，从没测过「这个值有没有被读出来」。
**结论：写测试要守端到端那条线（文件写 X → 报告必须是 X），不是端点行为。**

**中文 6 条首轮结果**（run `6edd013e`，修 label bug 前，故报告标签是错的，需重跑）：

| 指标 | 值 |
|---|---|
| `custom__hit_rate` | 0.8333 |
| `custom__mrr` | 0.7500 |
| `custom__ndcg` | 0.6230 |
| `custom__recall` | 0.4584 |
| 降级率 | **66.7%（4/6）** — `faithfulness` 4/6 降级、`context_precision` 2/6 |

新增的 `metric_integrity` stderr 摘要工作正常（按指标列出有效/降级条数与原因）。
`upstream_error` 各 1 条，说明**限流污染仍在**，绝对值要按此折价。

---

### 最终结果

**新基线**：`57259cb6-cbd3-4f1a-b267-700a6a350195`（英文 41 条，`marked_by: B2-pooled-llm-judged-en-2026-08-24`）。
旧基线 `80a82405` 已降级进 `history`，未删除。标记入口：`scripts/dev/mark_baseline.py`（新增）。

| 指标 | **英文 41 条**（run `57259cb6`，**新基线**） | 中文 6 条（run `31f2ed71`） |
|---|---|---|
| `custom__hit_rate` | **0.9756** | 0.8333 |
| `custom__mrr` | **0.8585** | 0.7500 |
| `custom__ndcg` | **0.7140** | 0.6230 |
| `custom__recall` | **0.4584** | 0.4584 |
| `ragas__context_recall` | 0.9146 *(41/41)* | 0.8333 *(6/6)* |
| `ragas__context_precision` | 0.7995 *(36/41)* | 0.8450 *(6/6)* |
| `ragas__answer_relevancy` | 0.8921 *(40/41)* | 0.8470 *(6/6)* |
| `ragas__faithfulness` | 0.8562 *(**25**/41)* | 1.0000 *(**1**/6)* |
| 降级率 | **46.3%（19/41）** | **83.3%（5/6）** |

*斜体是 `metric_integrity` 的 valid/total。* **中文那个 `faithfulness = 1.0000` 是 1 条算出来的** ——
这是「先读 `metric_integrity` 再读数」最好的教材。

**三个值得留下的观察**：

1. **英文 custom 四项与归档 A/B 的 `none` 臂（`d08e540d`）逐位重合**（0.9756 / 0.8585 / 0.7140 / 0.4584），
   中文两轮之间也逐位重合。**检索侧完全可复现** —— 这四个数可以放心当基准用。
2. **降级率从第一代的 54.8% 降到 46.3%**，但仍是 5% 门槛的 **9 倍**。病灶集中在
   `faithfulness`（39.0% 降级，16/41 全部 `unparseable`）；`context_recall` 反而 **0 降级**。
   与既有归因一致（病因在输入侧的语言错乱，不是 judge 弱）。
3. ⚠️ **这次跑批遇到一次网关突发限流**（21:13–21:16 连续 `Connection error`），
   第 29 条时 `ResponseBuilder` 抛错终止整轮，**80 分钟全丢**。3 分钟后探测 3/3 健康，重跑
   零错误一次过。已登记为 **C9**。

**修掉的两个 bug**（都不在原计划里，都是招牌病）：

- **`_labeling_method` 从未流到报告**（commit `6859dc3`）—— 本条的完成判据「报告里
  `_labeling_method: pooled-llm-judged`」**在修之前根本不可能达成**。修后
  `delta_comparable: False` **第一次真正触发**，并给出了正确的说明文本。
- **`mark_baseline.py` 的成功提示用了 emoji**（commit `a9cde03`）—— GBK 控制台抛
  `UnicodeEncodeError`，而它在 `mark_as_baseline` **之后**，于是「基线标成功了、脚本报错退出」。

**新登记的两项**：C9（`evaluate.py` 无续跑）、**C10（基线只按 collection 存一份，不分语种）**。
C10 **已被本次实测确认**：中文 6 条那份 run 的 `delta_comparable` 是 `True`（标注方式与基线相同），
但它比的基线是 **41 条英文** —— 8 项全被 `delta_incomparable_metrics` 以「分母不一致」拦住了，
`delta_comparable` 本身却说「可比」。**拦住了，但理由说错了。**

---

# 梯队二 · 尺子校正完就做

## [~] C4 · Query Rewriting（agentic 路线图位置①）　`大 · 走 SDD`　第一刀已完成 ✅ 2026-08-25

> ### 第一刀已完成并归档（2026-08-25）
>
> `openspec/changes/archive/2026-08-25-per-route-metrics-and-synonym-rewrite/`，13/13 任务，
> `pytest tests/unit` 2168 passed。范围 = 策略笔记 §8 的**阶段 0 + 阶段 1**。
>
> **结果一半成功、一半是有价值的失败**：
>
> - ✅ **阶段 0 分路径评估口径做成了**，报告新增 `aggregate_metrics_by_route`。
>   基准（英文 41 条，`sparse=0.1`）：dense 单路 MRR **0.7793**、sparse 单路 MRR **0.8104**。
>   ⚠️ **sparse 的排序质量反而高于 dense**，「瓶颈在 sparse」只在 `recall`/`hit_rate`
>   维度成立 —— 这条修正了本文档此前的表述。
> - ❌ **阶段 1 同义词扩展实测有害**，sparse 单路 MRR **−0.0610 ~ −0.0793**，已判定
>   **不启用**（`query_rewrite.strategy` 保持 `none`；能力保留可配，理由见 acceptance §8.2）。
>
> **最重要的一条**：融合后的 delta 只有 `+0.0000` / `−0.0006` ——
> **没有分路径指标，这次会被读成「改写没效果」，而它实际在明确造成伤害**。
> 把阶段 0 定为硬前置的判断，在这个变更内部就得到了验证。
>
> **机制已量化**：给 BM25 选扩展词的判据是「扩展目标够不够**稀有**」而非「够不够常见」。
> `manager` 占语料 26.3%、IDF 1.030，而被它替换的 `grp` IDF 8.257 —— 扩展等于往高区分度
> 查询里塞一个匹配四分之一语料的词。这份 API 参考语料的判别力集中在罕见标识符
> （IDF 8~10），**任何普通英文词汇的扩展都在稀释它**。
>
> **剩余阶段**：
> - **阶段 2 Multi-Query** —— ⚠️ 它会新增融合路径名，而 `Fusion.weight_for()` 查不到会
>   **静默回落 1.0**、作废 Feature-005 校准出的 `sparse: 0.1`。风险已作为注释留在
>   `fusion.py` 的 `weight_for()` 上，不只留在文档里
> - ~~**阶段 3 `fusion_weights` 重校准**~~ —— ✅ **2026-08-25 完成**。`sparse` 0.1 → 0.75，
>   新基线 run `728a77ab`。custom 四项分母不变故 delta 可信：**MRR +0.0163、nDCG +0.0044**，
>   hit_rate/recall 持平，**零延迟零 token**。
>   ⚠️ RAGAS 三项（`faithfulness` / `answer_relevancy` / `context_precision`）因分母变化
>   被自动标进 `delta_incomparable_metrics`，其「改善」**不可当作权重收益**；
>   只有 `context_recall` 分母未变，delta 是 **−0.0122**。
>   ⚠️ 提前到阶段 2 之前做，理由与笔记原文不同：**0.1 不是「会随语料过时」，而是当时就偏低** ——
>   它在第一代 dense-top-k 金标上校准，那把尺子系统性压低 sparse 权重。
>   ⚠️ 中文 6 条**尚未在 0.75 下重测**（基线按 collection 单槽，见 C10）。
> - **阶段 4 HyDE** —— 仍判定不对症，且本次结果**进一步支持**这个判断：
>   往 sparse 里加普通词汇已被证明有害，而 HyDE 正是喂它 LLM 生成的散文
> - **单复数扩展**（`parameter` 1692 / `parameters` 8428）—— 缺口真实、机制不同，值得单独测

> ### ⚠️ 开工前必读：两条 C4 的硬约束 + 一份已经量好的权重曲线
>
> 这三条都不在本文档原来的 C4 条目里，是 2026-08-24 前期调研时从
> `openspec/config.yaml` § 已知陷阱 与代码里挖出来的。**不看会直接得出错误结论。**
>
> #### ① 路径命名会静默作废融合权重 —— 这是 C4 最容易踩的雷
>
> `Fusion.weight_for()` 是 `self._weights.get(route, DEFAULT_ROUTE_WEIGHT)`，而
> `DEFAULT_ROUTE_WEIGHT = 1.0`、配置里的键名是 `sparse`
> （[fusion.py:99](../src/core/query_engine/fusion.py#L99)【代码】）。
> **一旦把改写后的路径命名成 `sparse_q0`，查表落空就拿 1.0，而不是校准出的 0.1** ——
> Feature-005 的权重被悄悄作废、sparse 回到等权，**系统照常运行、不报错**。
>
> 对策：权重必须按**路径族**查找（从 `sparse_q0` 剥出 `sparse`），并配一条
> 「改了配置结论就该变」的单测固定住。这条在 delta 规格里必须显式写。
>
> #### ② 改写的增益主要在 sparse 单路，融合后的 8 项指标会稀释掉它
>
> dense 的 embedding 天然对同义/措辞鲁棒，「换个说法」类策略对它边际递减；
> BM25 是字面匹配、对措辞极度敏感，才是真正受益方。而现有指标量的**都是融合后
> 结果**，sparse 那点改善会被权重压到看不见。
>
> **所以做 A/B 前必须先补分路径指标**（单独量 sparse 路的 recall/MRR）。
> 现状核验【实测 2026-08-24】：`src/observability/evaluation/` 下**没有**任何分路径
> 指标；`retrieval_mode`（`dense_only`/`hybrid`）只是 `BaselineManager` 上一个
> **人工填的标注字符串**，不是算出来的。这个缺口是真的。
>
> #### ③ 融合权重已在第二代金标上重新量过，结论：0.75 而不是生产的 0.1
>
> 生产的 `sparse: 0.1` 是在**第一代 dense 锚定金标**上校准的 —— 那把尺子结构性
> 惩罚 sparse（任何 sparse 贡献挤掉一条 dense 命中就拉低 recall/hit_rate），
> **与它惩罚重排是同一根因**。第二代金标上重测（英文 41 条，端到端跑真实管线，
> `--no-generate-answers` + `backends: [custom]`）：
>
> | sparse | hit_rate | MRR | nDCG | recall |
> |---|---|---|---|---|
> | **0.1（当前生产）** | 0.9756 | 0.8585 | 0.7140 | 0.4584 |
> | 0.25 | 0.9756 | 0.8585 | 0.7157 | 0.4584 |
> | 0.5 | 0.9756 | 0.8707 | 0.7177 | 0.4584 |
> | **0.75（最优）** | 0.9756 | **0.8748** | **0.7184** | 0.4584 |
> | 1.0 | 0.9756 | 0.8726 | 0.7027 | 0.4483 ↓ |
>
> 离线扫描（`calibrate_fusion_weights.py --sweep`）独立给出同一推荐 **0.75**。
>
> **已决定暂不改生产配置** —— `settings.yaml` 自己写明「改写与融合权重必须联合
> 校准」，C4 会改变 sparse 信噪比，0.75 届时还要再调；现在花 90 分钟重标基线换
> +0.0163 MRR 很可能白做。**C4 落地时连同权重一起定，这张表直接拿去用。**
>
> ⚠️ **别拿离线扫描的绝对值外推到管线**：扫描在 top-20 上打分给出
> 0.8390 → 0.8900（+0.051），端到端（`top_k_final=10`）只有 +0.0163。
> **扫描是选权重的排序工具，不是端到端增益的预测器。**
>
> #### 参考量级
>
> 重排 `none → cross_encoder` 是 **+0.0764 MRR**，代价 40 候选 **5.2 秒**。
> 权重改动 **+0.0163 MRR**，零成本。C4 的增益若低于这两者，就要重新想清楚它的价值。



**背景**：`docs/learning/agentic-retrieval-boundary.md` §8.2 把它排在后续 feature 的第 1 位。
前置的「带权重 RRF 改造」已由 Feature-005 完成。

**现状核验**（2026-08-24 实测）：

```bash
grep -rilE "agentic|react|rewrite|planner|sub_quer|subquer" src/
```

零命中。`query_processor.py` 全程不调 LLM（只有 docstring 里出现 "LLM" 字样）；
`src/core/query_engine/hybrid_search.py:218` 仍只喂 `{"dense", "sparse"}` 两路。
§6.1 那句「三个位置都是空的」今天依然成立。

**为什么现在可以做了**：此前挡住它的理由是「没有能公正评判它的指标」—— **这个理由随 B1 消失**。
第二代金标下 `custom__mrr` / `custom__ndcg` 不再锚定 dense，重排 A/B 就是用它们测出来的，
改写同样能用。**不需要等 C3**（RAGAS 四项）。

**一个战略判断**（供参考，不是硬结论）：这个项目在「测量」上已投入六轮（001 / 003 / 004 / 005
+ 两个金标 change），其中五轮在修尺子；而路线图上真正的能力项至今 `src/` 零命中。
**第七个评估修正的边际价值，已明显低于第一个 agentic 能力。**

**可复用基建**（都已就位）：`fusion.py` 的 `fuse()` 签名天然支持 N 路，改写出的多个 query
各自检索后直接喂进去即可；元数据过滤在 `hybrid_search.py:231`；trace 分阶段耗时已有。

**接口约束**：第二个消费方 `smart-appointment-ai-agent` 的 `KnowledgeSearchPort` 是
**单次调用、无状态、进 query 出文档**。改写必须发生在这次调用**内部**，调用方没有插入点。

---

# 梯队三 · 有价值但可以等

| # | 事项 | 为什么可以等 | 规模 |
|---|---|---|---|
| ~~**C3**~~ | 治理「答案语言与问题语言不符」 | ✅ **2026-08-25 完成并归档**（`archive/2026-08-25-answer-language-follows-question/`，10/10）。**语言一致率 39.0% → 95~100%**（两轮独立测量，主判据成立）。⚠️ 降级率的改善**方向明确但幅度不可靠** —— 同配置两轮为 4.9% 与 31.7%，见归档 acceptance §一之二。⚠️ 修正了两处既有认识 + 查出两个关于测量本身的问题，见下方 | 中 · 走 SDD |
| **C1** | 中文金标 ≥40 条：绕开 RAGAS evolution，直接用 LLM 从中文 chunk 生成问题 | 语料 **81.4% 是中文**，中文只有 6 条确实是硬伤。但要新建一整条合成链路，且目前没有中文侧实验在等它 | 大 · 走 SDD |
| ~~**B3**~~ | 是否开启重排（`rerank.backend: none` → `cross_encoder`） | ✅ **2026-08-27 已拍板：开**。英文 nDCG **+0.0764**、中文 **+0.0914**，零 token，约 2.8 秒/查询，按 MCP 场景（调用方是 agent）接受。此前那句「大概率不开」依据的**两个数都是错的**，见下方 | 小（决策） |

### 2026-08-24 新登记

| # | 事项 | 为什么可以等 | 规模 |
|---|---|---|---|
| **C9** | `scripts/evaluate.py` **无断点续跑，且答案生成一次失败就终止整轮** | 不影响结论正确性，只影响跑批体验 —— 但代价很实：本次英文 41 条跑到第 29 条时网关连续 `Connection error`，`ResponseBuilder` 抛错直接 `Evaluation runtime failed`，**80 分钟的工作全部丢失且没有归档任何报告**。标注脚本 `label_golden_chunks.py` 早就有续跑（英文那轮跨 4 次中断累积完成），评估脚本没有 | 中 |

| **C10** | 基线只按 **collection** 存一份,不区分语种 / 测试集 | 现在中英共用 `default_text-embedding-v4` 这一个基线槽 —— 标了英文基线,之后跑中文就会拿 6 条中文去和 41 条英文比 delta。`delta_incomparable_metrics` 会因分母不同标出来,但**原因写的是「分母不一致」而不是「你在拿中文比英文」**,读的人容易归因错 | 小~中 |

**C10 的关键事实**：`BaselineManager` 的 key 是 `collection`（`logs/baselines.json` 的
`current.<collection>`）。最小修法是把 key 扩成 `<collection>:<lang>` 或
`<collection>:<test_set_basename>`，并让 `delta_incomparable_reason` 能说出
「测试集不同」这个更根本的原因 —— 与 `_labeling_method` 那条修复是同一类：
**让报告说出它到底在比什么。**

### 2026-08-25 只读调研（C4 阶段 2 前期）查出的其余风险

> 来源：一次严格只读的代码调研，全部结论带文件+行号。**四条已修**（见 commit
> `7191221`）：分路径聚合静默补零、`fusion_weights` 键名无校验、Query Traces 面板
> `TypeError`、路径名常量两份。下面是**登记未修**的，都不阻塞当前工作。

| # | 事项 | 为什么可以等 | 规模 |
|---|---|---|---|
| **C11** | trace 记的 `weights` 是**构造期配置映射**，不是每路生效权重 | 当前两路都在配置里，两者恰好一致，所以是**潜伏态**。引入多路后 trace 里仍只有 `{dense, sparse}` 两条，**每路实际生效的权重无法反推** —— 而 `fusion.py` 的 docstring 声称记录「本次实际生效的权重」，届时与实际行为不符 | 小 |
| **C12** | 分路径指标**面板完全不渲染** | `evaluation_panel.py` 只读 `aggregate_metrics`；整个 `dashboard/` 对 `by_route` / `route_metrics` 零命中。数字只存在于归档 JSON 里 —— 能用，但要手翻 | 小~中 |
| **C13** | `fuse(top_k=effective_top_k * 2)` 那个 `2` **无依据注释** | 它是否代表「两路」未确认（无注释、无测试断言其来源）。多路时这个乘数该是几，现在没人知道 | 小（先补注释或测试） |
| **C14** | 重名 trace 阶段：写入侧合法，**读取侧只取第一个** | `trace_service.get_stage_duration/get_stage_data` 命中即 return。多路会产生多个 `dense_retrieval` 阶段 → 面板只显示第 1 路，其余静默丢失。**引入多路前必须先处理** | 中 |
| **C15** | `query_traces.py` 硬编码 5 个阶段名 + Dense/Sparse 两列 + `input_dense`/`input_sparse` | 多路下这两个键若换名，页面用 `.get(..., 0)` 显示 **0** —— 不报错，看起来像「输入为空」 | 中 |
| **C16** | 相关改写变体各成一路时，同一 chunk 得分**成倍累加**，无贡献次数上限 | Multi-Query 的 3 个改写高度相关，同一 chunk 很可能被 3 路同时命中 → 得分近似 ×3。契约只写「多路出现则相加」，**没讨论相关路径** | 中（Multi-Query 的前置） |

### 2026-08-27 新登记（B3 拍板时撞见）

| # | 事项 | 为什么可以等 | 规模 |
|---|---|---|---|
| **C17** | **检索专项跑与全量跑的指标键名不同，把前者标成基线会让 delta 静默落空** | 不影响任何已有结论（B3 两臂是手工对照读数，没走 delta），但它是招牌病的**第 11 例形态**，且踩上去毫无征兆 | 小 |

**C17 的实证**（都是【实测 2026-08-27】/【代码】）：

- `--no-generate-answers` + `backends: [custom]` 的检索专项跑，`aggregate_metrics` 的键是
  **无前缀**的 `['hit_rate', 'mrr', 'ndcg', 'recall']`（报告 `47e841b8`）
- 全量跑是 `['custom__hit_rate', …, 'ragas__faithfulness']` 八项（报告 `b3706441`）
- `BaselineManager._compute_delta` 逐键取基线值，**`base_value is None` 就 `continue`**
  （[baseline_manager.py:256](../src/observability/evaluation/baseline_manager.py#L256)）
  —— 两边键集不相交时 `per_metric_delta` 是**空 dict**，不报错、不告警、`delta_comparable`
  也不会变 `False`（它判的是标注方式，不是键集）

**「它没生效的时候我怎么会知道？」的答案是「不会知道」** —— 所以这条要修。最小修法：
delta 计算时若**键集交集为空**，显式标一个 `delta_incomparable_reason: "metric key sets disjoint"`，
而不是返回空 delta。与 C10（基线不分语种）、`_labeling_method` 那条是同一类：
**让报告说出它到底在比什么。**

⚠️ **在 C17 修好之前**：不要用 `--no-generate-answers` 的专项跑去标基线。要重标当前基线
（`b3706441` 仍是 `rerank: none` 下测的，已与生产配置不符）必须跑一轮**带答案生成的完整英文评估**。

**C14 / C15 / C16 是 Multi-Query 的真实前置** —— 比「实现多路检索」本身更该先做，
否则多路一上，观测面（trace、面板）与打分口径（相关路径累加）会同时失真。

**一处口径不对称（既有，未修）**：`SearchOutcome.routes` 存的是**过滤后**结果，
而喂给 `fuse()` 的是**未过滤**结果（过滤发生在融合之后）。docstring 只承诺
routes 经过同样过滤，没说融合输入未过滤。当前 `filters` 在评估路径恒为 `None`，
所以没有触发面。

**C9 第二次造成损失（2026-08-27，实测）**：为把基线重标到「重排已开」的生产配置，跑一轮
完整英文评估（41 条，带答案生成 + RAGAS）。**跑到 51 分钟时**（20:46 → 21:37）网关进入
突发窗口，连续 `Connection error`，`ResponseBuilder` 抛错 → `Evaluation runtime failed`，
**整轮终止、零报告归档**（归档目录计数前后均为 606）。

关键细节，都指向「重试解决不了」：

- `llm.max_retries` 已是 **4**、`request_timeout_sec` 已是 **180** —— SDK 层重试已耗尽
- 突发窗口只持续约 **1 分钟**（21:37:01 → 21:37:56），事后立即探测 **3/3 健康**
- 也就是说：**一分钟的网络抖动，销毁了 51 分钟的工作**，而其中 40 条 case 的答案早已生成
- 与 2026-08-24 那次（80 分钟，第 29 条失败）**形态完全相同**

**这次也复现了另一个坑**：后台跑的退出码是 `0`，因为命令末尾接了 `tail`，`$?` 取的是 `tail`
的退出码。**「exit 0」被读成了「跑成功」，实际日志最后一行是 `Evaluation runtime failed`。**
判定长跑结果必须看日志内容，不能只看退出码 —— 这是本项目「静默失效」在运维侧的同构形态。

**C9 的关键事实**：网关的限流是**突发窗口**（本次 21:13–21:16 密集失败，21:20 探测 3/3 健康），
所以「失败即重头再来」在这个网关上是很差的设计。两个方向：①每条 case 评估完就落盘（增量
写 `case_results`），重启时跳过已完成的；②答案生成失败按降级处理（记 `upstream_error`，
该 case 的 RAGAS 生成类指标标 NaN），而不是终止整轮 —— **项目已有降级基础设施
（`degradation_reasons` / `metric_integrity`），只是答案生成这一步没接进去**。
⚠️ 方向②要小心别把「限流」洗成「质量问题」：`metric_integrity` 已能按 `upstream_error`
分类，所以是安全的。

### ✅ C3 的结果（2026-08-25 归档）

英文 41 条，改前 `728a77ab` → 改后 `6985e140`：

| | 改前 | 改后 |
|---|---|---|
| 语言一致率 | 16/41 = **39.0%** | **100.0%**（#1）/ **95.1%**（#2） |
| 降级率 | 17/41 = **41.5%** | 4.9%（#1）/ **31.7%**（#2）⚠️ |
| `faithfulness` 有效 | 27/41 | 39/41（#1）/ 35/41（#2） |
| `context_precision` 有效 | 33/41 | 40/41（#1）/ 33/41（#2） |

⚠️ **改后跑了两轮同配置的运行，降级率相差 6.5 倍** —— 语言一致率的结论稳（两轮都
≥95%），降级率只能看方向、不能设阈值。详见归档 acceptance 的 §一之二。

中文侧 6/6 仍全中文答案（未倒退），降级 5→3。

根因就是提示词单语：system 消息与模板全为中文，且**没有任何一句提到输出语言**。
修法是中英并列书写 + 显式要求「用提问所用的语言回答」。

⚠️ **RAGAS 分数本身不作为成功依据** —— 两项因分母变化不可比，另两项分母稳定却下降
（见下方「两个关于测量的发现」②）。本变更的依据是语言一致率与降级率，
一个纯字符统计、一个计数，都是确定性的。

### ⚠️ 顺带查出两个关于测量本身的问题（比 C3 本身更通用）

**① 一次 embedding 超时就能污染「逐位不变」的回归判据**

T-3.2 首次比对失败（dense 四项 + 融合后两项变了）。逐条定位只有 1 条 case 变，
其 dense 单路全部归零 —— 日志里有一条
`OpenAI Embedding API call failed: Request timed out.`，`HybridSearch` 捕获后降级为
空列表（既有设计，正确）。**重放该 case 完全恢复**；dense 连跑三次逐位稳定、
embedding 对同一文本两次调用逐位相同。

项目那句「检索侧完全可复现」是真的，**前提是网关不抖**。
**做「逐位不变」类判定前必须先按 `ERROR` 过滤日志** —— 与「限流会伪装成降级」同类。

**② `judge_llm.temperature = 0.0` 并没有让托管 judge 变确定**

`context_recall` 只依赖 `(question, ground_truth, contexts)`，这三者**逐字相同**，
判定仍在 **4/41 = 9.8%** 条上翻转（0.5→0.0、1.0→0.0、0.5→1.0）。

所以 **RAGAS 的 ±0.05 级 delta 即使分母稳定也不可归因**。项目此前的对策是
「冻结元组」—— 现在知道**冻结元组还不够**。要比较就多次重复取均值给区间，
不要拿单次两个数做减法。

（另注：`llm.temperature` **这个字段根本不存在**，答案生成用 provider 默认温度，
所以 `answer_relevancy` 在 **38/41** 条上都会变。）

### ⚠️ C3 立项时（2026-08-25）修正的两处既有认识

在第二代金标 + 当前配置上复核（run `728a77ab` 英文 41 条 / `31f2ed71` 中文 6 条），
两条此前记录的结论需要更新：

**① 判据是「答案是不是英文」，不是「答案与上下文是否一致」**

此前的表述是「answer 中文而 contexts 英文时两步都在跨语言做」。实测按上下文分组：

| 上下文 | 答案 | n | 降级率 |
|---|---|---|---|
| en | en | 11 | **18%** |
| en | zh | 12 | 58% |
| **zh** | **en** | 5 | **0%** |
| zh | zh | 13 | 62% |

答案**匹配**上下文的组 42% 降级，**不匹配**的组 41% 降级 —— **没有区别**。
而「中文上下文 + 英文答案」是 **0%**。所以跨语言配对不是障碍，
**答案是中文**才是。（n 小，尤其那 5 条；方向明确但幅度别当精确值。）

**② 这修不好中文侧 —— 而且它与 adapt 失败是同一个根因**

中文那轮 **6/6 语言一致**（中文问 → 中文答），仍 **5/6 降级**，
`faithfulness` 只剩 1 条有效。所以「答案跟问题同语言」**不是充分条件**。

更精确的机制：**`ragas==0.1.21` 的内部提示词是英文的，它对中文答案做 statement
抽取本身就不行。** 这与「`adapt(language=chinese)` 在三个模型上全部产出 0.0% 中文」
是**同一句话的两面**：RAGAS 实质只能工作在英文上，而让它支持中文的机制是坏的。

**含义**：C3 能让**英文金标**上的 RAGAS 可用；**中文侧的 RAGAS 仍不可用**，
而语料 81.4% 是中文。要解决那一半只有换掉 RAGAS 或绕开它 —— 那是另一个量级的决定，
**尚未立项**。

### ✅ B3 重测结果（2026-08-25）—— 已于 2026-08-27 拍板：**开启重排**

在**当前配置**下重测（英文 41 条 `pooled-llm-judged`，`sparse=0.75`，
答案语言已修，`--no-generate-answers` + `backends: [custom]`）：

| | none（`1adc0e4e`） | cross_encoder（`47e841b8`） | delta |
|---|---|---|---|
| hit_rate | 0.9756 | 0.9756 | ±0 |
| **MRR** | 0.8748 | **0.9350** | **+0.0602** |
| **nDCG** | 0.7184 | **0.7948** | **+0.0764** |
| **recall** | 0.4584 | **0.5107** | **+0.0523** |

**延迟实测**：none 臂 34 秒 / cross_encoder 臂 148 秒（41 条）→ **约 2.8 秒/查询**（含模型加载）。

#### ⚠️ 此前那句「大概率不开」依据的两个数都是错的

1. **代价被高估一倍**。原话是「40 条候选 5.2 秒」，但**重排拿到的是融合后截断的
   结果**（`top_k_final * 2 = 20`），实测每次只收到 **12~19 条**。那个 40 是
   **融合前**两路之和。真实约 **2.8 秒**。
2. **收益是在错的权重下测的**。+0.0764 那个数测于 `sparse=0.1`，而现在是 0.75。
   重测后 MRR +0.0602、**nDCG +0.0764**、recall +0.0523。

**参照量级**：刚做完的融合权重重校准是 nDCG **+0.0044** —— 重排是它的 **17 倍**，
且**零 token**（本地 CPU 推理）。

#### 拍板需要的信息

这是个**产品级取舍**，不是技术判断：

- ✅ 收益是本项目迄今测到的**最大单项检索改进**，且零 token
- ⚠️ 代价是每次查询 **+2.8 秒**。当前无重排时端到端约 0.8 秒/查询，开启后约 3.6 秒
- 两个消费方的容忍度可能不同：MCP（调用方是 agent，等几秒通常可接受）
  vs `smart-appointment-ai-agent`（可能是面向用户的对话）

⚠️ **`rerank.top_m: 50` 是不可达的**（上游截断 20 更紧）。想让重排看更多候选，
要改 `top_k_final` 或 `hybrid_search` 里那个 `* 2`，**改 `top_m` 无效**。

#### ✅ 拍板结论（2026-08-27）：**开**

`config/settings.yaml` 已切到 `backend: cross_encoder` + `model: BAAI/bge-reranker-base`。
理由：收益是本项目迄今最大的单项检索改进且**零 token**，2.8 秒对 MCP 场景（调用方是 agent）
可接受。若 `smart-appointment-ai-agent` 那侧是面向真人的对话且不能忍这 2.8 秒，
它可以在自己的配置里把 `backend` 关回 `none` —— 这本来就是一个配置项。

**中文 6 条同向且相对增益更大**（`9f56c494` none → `804f57a9` cross_encoder）：
MRR `0.6667 → 0.7500`（**+0.0833**）、nDCG `0.6120 → 0.7034`（**+0.0914**）、
recall `0.4584 → 0.5556`（**+0.0972**）。与 `bge-reranker-base` 是中英双语模型一致。
⚠️ 顺带盖过了「`sparse=0.75` 在中文上是负增益（MRR −0.0833）」那个损失 ——
**中文 MRR 回到了 0.75**。分语种融合权重因此不再紧急，但问题仍在（见 CLAUDE.md）。

**两条新税（都已写进 CLAUDE.md）**：

1. ⚠️ **开启后每次冷启动都会尝试联网**。权重已落盘时 `sentence_transformers` 仍会向
   HuggingFace 发校验请求，墙内**静默挂起** —— 实测 6 条的评估跑了 10 分钟零 CPU 占用，
   看起来像死循环。**跑批前设 `HF_HUB_OFFLINE=1`**，同一轮 48 秒跑完。
2. ⚠️ **当前基线 `b3706441` 是 `rerank: none` 下测的，已与生产配置不符**，但**不能**拿
   B3 的两臂去重标 —— 它们是 `--no-generate-answers` + `backends:[custom]` 的检索专项跑，
   `aggregate_metrics` 用**无前缀键名**（`mrr`），而全量报告用 `custom__mrr`，
   标成基线会让此后所有 delta **静默落空**（见 C17）。要重标必须跑一轮带答案生成的完整英文评估。

**C3 的关键事实**（做的时候直接用，别重新挖）：病因**不是** judge 弱、**不是** `max_tokens`。
剔除限流干扰后 14 条真实判定失败**全部**是「英文问题 + 中文答案」，语言一致的 14 条**零失败**；
`max_tokens` 猜想已被 595 次成功调用零空响应否证。两个能力悬殊的 judge 收敛到同一残余降级率
33%，佐证病因在输入侧。

---

# 已决定推迟 / 砍掉

| # | 事项 | 砍掉的理由 |
|---|---|---|
| **B4** | 换 judge 到 `claude-sonnet-5` | **换 judge 治不好病**。实测降级率 55% → 33%，仍是 5% 门槛的 6.6 倍；两个能力悬殊的 judge 收敛到同一残余率，已证明病因在输入侧（C3）。换了还要重新校准全部 `acceptance_thresholds` —— **代价确定，收益已被证伪** |
| **C2** | 补真人抽检（`human_agreement_rate` 仍是 `null`） | **边际信息量太低**：跨模型盲评已 95.8% 一致，最可能的结果是「确认没问题」。且 `config.yaml` 自己写明触发条件是「**结论被质疑时**」—— 现在没人质疑。**按需触发，不排期**。审阅表已就绪：`tests/fixtures/labeling_review_zh.md` |
| **C6** | P95 延迟统计（`src/` 至今零命中） | 没有人在等这个数字。除非要往简历里写延迟指标 |
| **C5 / C7 / C8** | 检索规划器 / 细粒度检索工具 / 端到端三点对比 | 依赖 C4 的结果。**而且 C4 做完可能就发现不需要规划器** —— T2 gate 已显示难的是 `reasoning` 类而非多跳，改写有可能吃掉大部分收益 |

> 砍掉不等于否定。B4 / C2 都有明确的**重启条件**写在上面，条件满足再捡回来。

---

# 并行指南

**结论：实际并行度是 2，不是 5。** 这批活的瓶颈是判断与叙事一致性，不是可切分的工作量。

## 三个阻断点

1. **A1 和 A2 抢同一批文件**。A1 的 5.4 要改 `CLAUDE.md` + `config.yaml`，A2 就是改 `CLAUDE.md`。
2. **更麻烦的是：A2 要修的 bug 本身就是「并行改文档」造成的**。`CLAUDE.md` 说重排有害、
   `config.yaml` 说重排有益，正是因为两份文档在不同时间被独立更新。A1/A2/A3 本质是**同一批事实
   写进四份文档**，拆给三个 agent 就是让三个 agent 各自决定怎么措辞同一个结论 ——
   **原地复现同一个 bug**。
3. **共享网关 + 共享状态文件**：
   - 这个网关的**限流会伪装成评估降级**（实测 21 条降级里 7 条实为 `upstream_error`，且集中在
     连续 index 区间）。并发跑批只会放大这个污染源，而它污染的正是你要用来决策的数字。
   - `src/observability/evaluation/baseline_manager.py:433` 是**原子写但无锁**
     （`mkstemp` + `os.replace`）。并发标基线不会写坏文件，但会**静默丢掉一次更新且不报错** ——
     又是本项目的招牌失败模式。

## 逐项判定

| 项 | 能否并行 | 理由 |
|---|---|---|
| A1 + A2 + A3 + A4 | ❌ 合成一个窗口连续做 | 共享 `CLAUDE.md` / `config.yaml` + 共享叙事 |
| A5 | ✅ 可独立 | 唯一真正 disjoint 的文件（但只有 5 分钟的活，且需先决策） |
| B1 | ⚠️ 必须在 A1 之后 | 不冲突，但结论要写进 A 组文档 |
| B2 | ⚠️ **后台跑，别开第二个 agent** | 长任务，独占网关 + `baselines.json` |
| C4 | ❌ 不要并行起步 | 要走 OpenSpec propose，需人的设计决策；改 `src/` 每任务需 `pytest` 全绿 |

## 唯一值得开并行 agent 的地方

**C4 的前期只读调研**：`query_processor.py` 现有接口形状、`fusion.fuse()` 接多路的实际约束、
`KnowledgeSearchPort` 单次调用下改写结果怎么回传、trace 怎么打点。**只读扫描** —— 不写文件、
不调网关、不碰共享状态，天然安全，可与梯队一完全并行。

---

# 待拍板的决策

## D1 · `golden_test_set_zh_v3.json` 怎么处置（挡着 A5）

29 条里 **25 条是英文问题**、`expected_chunk_ids` **全空**（2026-08-24 实测）。它是 Feature-003
时期在**被污染的 adapt 缓存**下产出的残骸，文件名却叫 "zh_v3" —— `openspec/config.yaml:149`
已经把它列为「文件名 / `version` / `_labeling_method` 三者打架」的典型实例。

- **选项 A：删除**。物证已另有保留 —— `logs/ragas_adapt_cache_POISONED_EVIDENCE/`（含 README）
  存了那份被污染的缓存本身，这个金标文件是冗余物证。
- **选项 B：改名 + 显式标记**，例如 `_ARTIFACT_contaminated_zh_candidate.json`，并在文件里
  加一个醒目的 `_do_not_use` 字段。

## ~~D2 · B3（重排开关）~~ —— ✅ 2026-08-27 已拍板开启，见梯队三

## D3 · B4（换 judge）—— 已倾向砍掉，重启条件见 § 已决定推迟

---

# 事实速查表

> 给新窗口用，避免重新挖掘。**所有数字均为【实测】**，来源已标。

## 重排 A/B 在两代金标下方向相反

英文金标，`backends: [custom]`，`--no-generate-answers`，集合 `default_text-embedding-v4`
（`run_id`：`d08e540d` = none / `97743b41` = cross_encoder）：

| 指标 | 第一代 `dense-top-k`（42 条） | **第二代 `pooled-llm-judged`（41 条）** |
|---|---|---|
| `custom__mrr` | 0.4914 → 0.3668　**−0.1246** | 0.8585 → **0.9350**　**+0.0764** |
| `custom__ndcg` | 0.4182 → 0.3373　**−0.0809** | 0.7140 → **0.7916**　**+0.0776** |
| `custom__recall` | 0.4571 → 0.4190　−0.0381 | 0.4584 → **0.5081**　+0.0497 |
| `custom__hit_rate` | 0.6905 → 0.6905　0 | 0.9756 → 0.9756　0 |

## 金标文件清单

| 文件 | 条数 | 标注方式 | 说明 |
|---|---|---|---|
| `golden_test_set_zh.json` | 6 | 第一代 | **当前生效** |
| `golden_test_set_en.json` | 42 | 第一代 | **当前生效** |
| `golden_test_set_zh_v2.json` | 6 | `pooled-llm-judged` | B1 切到这个 |
| `golden_test_set_en_v2.json` | 41 | `pooled-llm-judged` | B1 切到这个 |
| `golden_test_set_zh_v3.json` | 29 | 无（无 chunk_ids） | **残骸**，见 D1 |
| `golden_test_set.json` | 4 | — | US1 占位 |

与纯 dense top-K 的 Jaccard：英文 **0.406** / 中文 **0.328**（远低于 0.90 告警线，说明池化与判定确实生效）。

## `settings.yaml` 当前生效值

| 项 | 值 | 备注 |
|---|---|---|
| `golden_test_sets_by_lang` | 第一代 zh/en | **B1 要改** |
| `judge_llm` | `glm:minimax/minimax-m2.7` | B4 已倾向不换 |
| `screening_llm` | `glm:z-ai/glm-5.2-free` | 与 judge 异源 ✅ |
| `rerank.backend` | **`cross_encoder`** + `BAAI/bge-reranker-base` | B3 已拍板 ✅ 2026-08-27 |

## 难度分组召回（T2 gate，英文金标）

| 难度类 | hit_rate | recall |
|---|---|---|
| `simple`(22) | 63.6% | 40.0% |
| `multi_context`(9) | 77.8% | **68.9%** |
| `reasoning`(11) | 45.5% | **25.5%** |

**难的是 `reasoning`，不是多跳** —— 与原设计假设相反。

## 其他关键数字

- 评估降级率 **54.8%**（23/42），门槛 5%，是它的 **11 倍**
- 答案语言与问题不符：**28/42 = 66.7%**
- judge 配对实验（sonnet-5 vs minimax）：`context_precision` 0.7861 → 0.7037（**p=0.0013**）；
  `faithfulness` 0.9085 → 0.9478（p=0.29，不显著）；`answer_relevancy` 0.8473 → 0.8018（p=0.0028）；
  降级率 55% → 33%
- 重排延迟：每候选 **121–147 ms**，40 条候选约 **5.2 s**（AMD Zen 3，chunk 中位 428 字符，`batch_size=8`）
- 语料语言构成：抽样 20000 条 chunk，**81.4% 是中文**

---

> **全局约束提醒**：所有脚本与测试必须在 `.venv` 下运行（全局 Python 的 protobuf 会让
> `import chromadb` 失败）；跑 Python 脚本**一律加 `-u`**（stdout 管道下全缓冲会伪装成卡死，
> 本项目已踩过两次）；不为单个变更开 git 分支，沿用 `dev-from-clean-start`。
