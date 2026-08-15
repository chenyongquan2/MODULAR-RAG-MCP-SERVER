# 验收记录 —— retriever-agnostic-golden-labels

**日期**：2026-08-13 ~ 08-14　**分支**：`dev-from-clean-start`　**状态**：15/15 任务完成。6.2 的校准闸门以**跨模型盲评**满足（95.8% 一致），非人工复核 —— 用户明确委派判断、不做领域复核，残留风险已入长期记忆

## 一、一句话结论

**只换金标的构造方式，重排从「明显有害」翻转为「明显有益」** —— 同一个模型、同一份语料、同一套指标。这是本变更最强的验证：此前的负增益是**测量工具的产物**，不是重排的性质。

判定可信度以**跨模型盲评**校准：24 条三元组一致率 **95.8%**（`claude-opus-5` vs `glm:z-ai/glm-5.2-free`）。**这不是人工复核** —— 两个判定方都是 LLM，可能共享人类会发现的盲点，元数据里 `human_agreement_rate` 因此保持 `null`。详见 § 五。

## 一之二、决定性结果：重排 A/B 在两代金标下方向相反（T-6.3）

英文金标，`backends: [custom]`，`--no-generate-answers`，集合 `default_text-embedding-v4`：

| 指标 | v1（dense 锚定，42 条） | **v2（检索器无关，41 条）** |
|---|---|---|
| `custom__mrr` | 0.4914 → 0.3668　**−0.1246** | 0.8585 → **0.9350**　**+0.0764** |
| `custom__ndcg` | 0.4182 → 0.3373　**−0.0809** | 0.7140 → **0.7916**　**+0.0776** |
| `custom__recall` | 0.4571 → 0.4190　**−0.0381** | 0.4584 → **0.5081**　**+0.0497** |
| `custom__hit_rate` | 0.6905 → 0.6905　0 | 0.9756 → 0.9756　0 |

`run_id`：`d08e540d`（none）/ `97743b41`（cross_encoder）

**这与集成测试的证据终于一致了** —— 那里同一个模型每次都能把故意放在末位的相关段落提到首位。模型一直在做正确的事，是尺子在说谎。

⚠️ **绝对值不可跨代比较**：v2 每 case 均值 14.9 条标签（v1 恒为 5 条），所以 hit_rate 从 0.69 涨到 0.98 主要是「标签变多了更容易命中」，不是检索变好了。**只有同代内的 delta 有意义** —— 报告的 `delta_comparable: false` 就是为此设的。

⚠️ 上述结论建立在**跨模型校准**（95.8% 一致，§ 五）而非人工校准的 LLM 判定之上。它有力地证明了「金标构造方式会决定结论的方向」；至于「重排一定有益」这个更强的主张，还差一道真人抽检。

## 二、实测结果（中文金标 6 条，`default_text-embedding-v4`）

**产出**：`tests/fixtures/golden_test_set_zh_v2.json`（`version: v2.0`，`_labeling_method: pooled-llm-judged`）

| 项 | 值 |
|---|---|
| 候选池规模 | 均值 **36.17**，最大 40（dense 20 + sparse 20 + rerank 20 去重后） |
| 判定调用 | **234 次**（accepted 72 / rejected 145 / judge-failed 17 / skipped 0） |
| 判定模型 | `glm:z-ai/glm-5.2-free`（异源于 judge 的 `glm:minimax/minimax-m2.7`） |
| **与纯 dense top-K 的 Jaccard** | **0.328**（告警线 0.90，远低于它 ✅） |
| 耗时 | 约 35 分钟（约 8 s/判定，含重排路的本地 CPU 推理） |

### 分级分布

| grade | 含义 | 条数 |
|---|---|---|
| 3 | 直接回答 | 61 |
| 2 | 部分支撑 | 11 |
| 1 | 沾边 | **66** |
| 0 | 无关 | 62 |
| 失败 | 输出无法解析 | 17 |

grade 1（沾边）是最大的一档且被 `relevance_threshold: 2` 排除 —— 说明判定确实在做区分，而不是一律说「有关」。

### 被接受的 72 条标签，按贡献来源

| 贡献路径 | 条数 |
|---|---|
| `rerank+sparse` | 18 |
| `dense` | 18 |
| `dense+rerank+sparse` | 16 |
| `dense+rerank` | 16 |
| `sparse` | 4 |

**仅 dense 18 条、仅 sparse 4 条、仅 rerank 0 条。**

关键数字是 `rerank+sparse` 的 18 加上 `sparse` 的 4 —— 共 **22 条（31%）被 dense 完全没召回**。第一代做法下这 22 条连进入标准答案的机会都没有。这就是「去掉检索器锚定」的具体含义。

## 三、被证伪的判断（三处，全部是我自己写的）

| 原判断 | 实际 | 处置 |
|---|---|---|
| spec「仅重排提升的 chunk 都存在」可作池化生效的判据 | **错**。重排路重排的是 dense∪sparse 的并集，**构造上无法引入任何新 chunk**，只能重新标记已在池中的。所以「仅 rerank」恒为 0（实测确认） | spec 已加更正说明。判定池化生效应看「仅 dense」与「仅 sparse」是否都非空 |
| `max_tokens=200` 够用（我在 `chunk_labeler` 里硬编码的） | **错，而且是致命的**。首轮标注**几乎每条都判定失败**。实测：301 字符 chunk 截断在 JSON 中间，367 与 430 字符**直接返回空响应** | 改为配置项 `labeling_llm.max_tokens`，默认 800。修复后同一模型全部完整输出 |
| 敏感字段检测器的 `"token" in name` 启发式 | **误判**。`max_tokens: int` 被当成密钥要求 `repr=False`，那毫无意义只会让调试变难 | 加类型过滤（密钥一定是字符串）。检查未削弱：6 个 `api_key` 字段仍全部被检测 |

第二条值得单独说：**它正是本会话一直在修的那类病 —— 硬编码可调参数（违反宪法原则二）。我在别处修 `batch_size` 硬编码、修 `top_m` 死配置，同时自己又写了一个 `max_tokens=200`。** 而它的表现极具误导性：看起来像「模型不会遵从 JSON 格式」（项目里对 GLM 系模型正有这个先验 —— judge 就是因此从 `glm-4.7` 换成 minimax 的），真实原因是没给它写完的余量。若不去看原始输出，很容易得出「换个模型吧」的错误结论。

**设计上唯一救了这一轮的是「judge_failed ≠ 不相关」。** 首轮 234 次判定几乎全失败，但因为解析失败标记的是 `judge_failed`、`grade` 保持 `None` 而非兜底成 0，产出里能一眼看出「判定全废」而不是「语料里没有相关内容」。如果当初图省事兜底成 0 分，这一轮会产出一份看起来正常、实际全空的金标。

## 四、遗留告警

3 个 case 的判定失败率超过 10% 阈值（11.4% / 17.6% / 13.9%），整体 17/234 = **7.3%**。`max_tokens` 修复后残留的失败仍需排查 —— 可能是个别超长 chunk 仍不够余量，或模型偶发不遵从格式。

另一处：**两代金标都没有机器可读的合成端标识**。它们建于 2026-04-28，早于 Feature-003 引入 `_review_metadata`；只有 `_reviewer` / `_review_notes` 自由文本（中文那份的 notes 里确实提到了 `minimax/minimax-m2.7`）。所以异源检测正确地返回 `UNVERIFIABLE`，本轮用 `--allow-same-source` 显式承担了风险 —— 人可以核实（judge 是 minimax，判定端是 glm-5.2-free，显然异源），但程序不能。**我刻意没往金标里补写标识**：en 那份的 notes 是空的，凭推断往评估资产里写溯源信息比留着这个缺口更危险。

## 四之二、真实故障暴露的第四处缺陷（2026-08-13 晚）

英文金标那轮跑到**第 20 个 case 时网关挂掉**（`Connection error`，非超时），该 case 的 20 次判定全部传输层失败 → 抛 `LabelingUnavailableError` → 退出码 3，拒绝产出全是「不相关」的空金标。**这部分完全按设计工作。**

但 CLI 的 `except LabelingUnavailableError` 分支**直接 return，没写出已完成的部分** —— 前 19 个 case 约 630 次判定、**2.5 小时的工作全部丢失**。而续跑恰恰依赖产出文件存在，于是「模型不可用」这条快速失败路径把 spec 要求的「可续跑」直接架空了。

| | 修复前 | 修复后 |
|---|---|---|
| 已完成判定 | 丢失 | 写出并标 `v2.0-partial` |
| 退出码 | 3 | 3（不变，仍是要修网关的信号） |
| 元数据 | — | `model_unavailable: true` + 告警 |
| 续跑 | 不可能 | 重跑同一命令即从断点继续 |

**为什么会漏掉**：当时的单测只验了「异常被抛出」，没验 CLI 在那条路径上的写盘行为 —— **测了库，没测集成**。已补 4 个回归测试。

判据上的澄清：快速失败要防的是「产出一份全是不相关的空金标」，**不是「丢掉已经算好的结果」** —— 两者并不冲突。写出部分结果 + 标 partial + 退出码 3，既留痕又不让调用方误以为跑完了。

## 五、6.2 收口：校准闸门以跨模型盲评满足

用户明确表示「具体的知识库我也没怎么看过，请你先帮我客观去分析然后决定」，于是对那 24 个三元组做了**盲评**（先藏掉 LLM 的判定与理由，避免锚定偏差），判据统一为「只读这段 chunk 能否回答这个问题」。

| | |
|---|---|
| 一致率 | **95.8%（23/24）** |
| 交叉判定方 | `anthropic:claude-opus-5` |
| 原判定方 | `glm:z-ai/glm-5.2-free` |
| 唯一分歧 | 第 20 条 |

**第 20 条复盘下来是我判错、LLM 判对。** 那段讲服务器校验交易请求的流程（含「客户组是否允许交易品种交易」「请求时间是否为假期」），说明了假期**会被检查**这个机制，但没说客户在假期**能做什么**。LLM 给 1 分（沾边、拒绝）比我的「相关」更站得住 —— 我被「客户组 + 交易品种 + 假期」三要素同时出现带偏了。

**两个判定者只在一条边缘案例上分歧、没有系统性偏差**，这本身是有信息量的：说明 v2 的标签不是 `glm-5.2-free` 一家的特异偏好。

### 这是「跨模型证据」，不是「人工确认」——差别必须留痕

元数据里刻意分开记：`cross_judge_agreement_rate: 0.9583` + `cross_judge_identifier`，而 **`human_agreement_rate` 保持 `null`**，另加 `human_review_status` 说明为什么。理由：

- 两个判定方都是 LLM，**可能共享人类会发现的盲点**（比如都把 API 文档的导航页判为无关是对的，但都可能对某类领域语义有系统性误解）
- 本变更的 Non-goals 里写的是「人工抽检是唯一校准手段」，把跨模型一致率写进 `human_agreement_rate` 就是伪造 provenance —— 而重排 A/B 的翻转结论完全依赖判定可信度这个前提

  > **对 Non-goals 那句话的修订**：「唯一」说过头了。跨模型盲评同样能检出「标签是否为单一模型的特异偏好」，它只是**检不出两个模型共有的盲点**。准确的表述是：人工抽检是唯一能覆盖**全部**失效模式的手段。

**它把「完全未校准」推进到「有跨模型证据支持」。**

用户明确表示不做领域复核并委派判断，所以原设计的人工复核不会发生，本任务据此收口。**残留风险已写进 `CLAUDE.md` 与 `openspec/config.yaml` § 已知陷阱** —— 若将来重排结论（或任何依赖 v2 金标的结论）被质疑，第一件该做的事就是补真人抽检：审阅表在 `tests/fixtures/labeling_review_zh.md`，可直接对照两个判定方的分歧看。

### 若要补真人抽检（闸门升级路径）

样本已导出：`tests/fixtures/labeling_sample_zh.json` —— **24 个三元组，12 相关 / 12 不相关**（分层抽样，`--seed 20260813` 可复现）。

每条含 query、chunk 正文、LLM 给的 grade 与理由，以及待填的 `human_label`（`true`/`false`）。填完后：

```bash
.venv/Scripts/python.exe -u scripts/label_golden_chunks.py --input tests/fixtures/golden_test_set_zh_v2.json --import-sample tests/fixtures/labeling_sample_zh.json
```

一致率会写进 `_labeling_metadata.human_agreement_rate`，低于 `human_agreement_warn`（0.80）产出告警。

审阅表在 `tests/fixtures/labeling_review_zh.md`，现在可直接对照两个判定方的分歧看 —— 实际只有第 20 条需要人裁决。

## 六、也未做

| 项 | 原因 |
|---|---|
| ~~6.1 英文金标~~ | ✅ **已完成**（08-14）。42 条全标，630 accepted / 791 rejected / 28 judge-failed，Jaccard 0.406，1 条无解 case 移出。跨 4 次网关中断、靠续跑累积完成 |
| ~~6.3 重排 A/B~~ | ✅ **已完成**，见 § 一之二 —— 结论翻转 |
| 中文金标扩容到 ≥ 40 条 | 独立阻塞项。**顺序上现在才轮到它** —— 构造方式已修好，扩容才有意义 |

## 七、变更规模

**新增**：`src/observability/evaluation/chunk_pooler.py`、`chunk_labeler.py`、`scripts/label_golden_chunks.py`、`LabelingSettings` + `LabelingLLMSettings` + `_validate_labeling_settings`、`EvalReport.labeling_method` / `delta_comparable` / `delta_incomparable_reason`、`LABELING_METHOD_DENSE_TOP_K`

**改动**：`config/settings.yaml`（`evaluation.labeling` / `labeling_llm` 两段）、`scripts/backfill_chunk_ids.py`（标注代次 + 修死参数 `--collection`）、`eval_runner.py`（跨代 delta 标注不可比）、`tests/unit/test_settings_secret_hygiene.py`（检测器类型过滤）

**测试**：`pytest tests/unit` **1865 passed, 2 skipped**，本变更累计新增 **约 215 个用例**


## 八、英文金标的额外发现（08-14）

**1. 判定失败会被重试才有意义。** 首轮 625 次判定里 123 条 `judge_failed`；续跑时若把它们当已完成缓存，这 9.9% 的标签就永久丢了。改成不缓存失败项后，最终只剩 28 条 —— **95 条在重试中成功**。「解析失败」是瞬时故障，不是持久结论。

**2. 「无解 case」是合法结果，但会阻断整轮评估。** 有 1 条 query 是 `"After AG fetches cfg, what does AT do?"`（AG / AT / cfg 全是未定义缩写），40 个候选全在 grade 0-1。判定大概率是对的，但 `evaluate.py` 的前置校验要求 `expected_chunk_ids` 非空，一条空的就让整轮评估失败。现在这类 case 被移出 `test_cases` 并逐条记进 `_labeling_metadata.unanswerable_cases`（含 query、池规模、最高分级、原因）—— **移出而非静默丢弃**，否则「42 条变 41 条」会成为无从追查的差异。

**3. 续跑缓存必须按 query 而非位置索引做键。** 移出无解 case 后产出与输入条数不再一致，按索引匹配会把缓存判定套到**错误的 case** 上，而且不报错、只是标签悄悄错位。这个 bug 在写移出逻辑时同步引入、同步修掉，补了 2 个回归测试。

**4. 网关在这一轮中断了 4 次**（case 20 两次、case 37 一次、外加一次 embedding 超时）。续跑每次都从断点推进、零重复判定：19 → 36 → 42。如果没有前一晚修掉的「部分结果丢失」缺陷，这一轮根本跑不完。
