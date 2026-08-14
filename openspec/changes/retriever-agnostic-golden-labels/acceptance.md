# 验收记录 —— retriever-agnostic-golden-labels

**日期**：2026-08-13　**分支**：`dev-from-clean-start`　**状态**：13/14 任务完成，6.2 人工抽检待用户执行

## 一、一句话结论

金标的 `expected_chunk_ids` 不再由单一检索路径决定：中文金标实测 **72 条标签里有 22 条（31%）是纯 dense 结构上永远看不到的**，与纯 dense top-K 的 Jaccard 仅 **0.328**。但**判定可信度尚未校准** —— 抽检样本已导出，人工复核未做，在那之前这些标签不该当作 ground truth 使用。

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

## 五、未完成：6.2 人工抽检（必要闸门，不可跳过）

样本已导出：`tests/fixtures/labeling_sample_zh.json` —— **24 个三元组，12 相关 / 12 不相关**（分层抽样，`--seed 20260813` 可复现）。

每条含 query、chunk 正文、LLM 给的 grade 与理由，以及待填的 `human_label`（`true`/`false`）。填完后：

```bash
.venv/Scripts/python.exe -u scripts/label_golden_chunks.py --input tests/fixtures/golden_test_set_zh_v2.json --import-sample tests/fixtures/labeling_sample_zh.json
```

一致率会写进 `_labeling_metadata.human_agreement_rate`，低于 `human_agreement_warn`（0.80）产出告警。

**为什么这一步不能省**：本变更把「某个检索器的排序」换成了「某个 LLM 的判断」。它确实去掉了检索路径锚定（§ 二 的 Jaccard 0.328 与 31% 的 dense 盲区就是证据），但引入了判定模型自身的偏好。抽检是唯一能校准后者的手段。**跳过它，本变更就只是把一种未验证的偏差换成了另一种** —— 这句话是 proposal 的 Non-goals 里写下的，此处重申。

## 六、也未做

| 项 | 原因 |
|---|---|
| 6.1 的英文金标（42 条） | 按比例约 **1500-1700 次判定调用、3-4 小时**。中文 6 条已验证机制有效，英文放到抽检一致率达标之后再跑更合理 —— 否则可能用一套未校准的判定口径烧掉 4 小时 |
| 6.3 用新金标重跑重排 A/B | 依赖 6.1 的英文产出 |
| 中文金标扩容到 ≥ 40 条 | 独立阻塞项。**顺序上现在才轮到它** —— 构造方式已修好，扩容才有意义 |

## 七、变更规模

**新增**：`src/observability/evaluation/chunk_pooler.py`、`chunk_labeler.py`、`scripts/label_golden_chunks.py`、`LabelingSettings` + `LabelingLLMSettings` + `_validate_labeling_settings`、`EvalReport.labeling_method` / `delta_comparable` / `delta_incomparable_reason`、`LABELING_METHOD_DENSE_TOP_K`

**改动**：`config/settings.yaml`（`evaluation.labeling` / `labeling_llm` 两段）、`scripts/backfill_chunk_ids.py`（标注代次 + 修死参数 `--collection`）、`eval_runner.py`（跨代 delta 标注不可比）、`tests/unit/test_settings_secret_hygiene.py`（检测器类型过滤）

**测试**：`pytest tests/unit` **1858 passed, 2 skipped**，本变更累计新增 **约 210 个用例**
