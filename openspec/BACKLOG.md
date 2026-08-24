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

## [ ] B1 + B2 · 切到第二代金标 + 重标基线　`半天`

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

### 进行中（2026-08-24）

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

# 梯队二 · 尺子校正完就做

## [ ] C4 · Query Rewriting（agentic 路线图位置①）　`大 · 走 SDD`

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
| **C3** | 治理「英文问题产出中文答案」（42 条里 **28 条 = 66.7%** 语言不符，是 RAGAS 降级的已归因病因） | 它解锁的是 **RAGAS 四项**。但 B1 之后 **`custom` 四项已够用**（重排 A/B 就只用了 custom），所以**它不是 C4 的前提** | 中 · 走 SDD |
| **C1** | 中文金标 ≥40 条：绕开 RAGAS evolution，直接用 LLM 从中文 chunk 生成问题 | 语料 **81.4% 是中文**，中文只有 6 条确实是硬伤。但要新建一整条合成链路，且目前没有中文侧实验在等它 | 大 · 走 SDD |
| **B3** | 是否开启重排（`rerank.backend: none` → `cross_encoder`） | 等 B1 之后用正确尺子重测一次再定。**大概率答案是「不开」**：+0.076 MRR 换 40 条候选 **5.2 秒**延迟，对 MCP 场景是很差的交易 | 小（决策） |

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

## D2 · B3（重排开关）—— 见梯队三，等 B1 之后再定

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
| `rerank.backend` | `none` | B3 待定 |

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
