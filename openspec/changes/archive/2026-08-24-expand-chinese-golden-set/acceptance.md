# 验收记录 —— expand-chinese-golden-set

**日期**：2026-08-14 ~ 08-24　**分支**：`dev-from-clean-start`
**状态**：17 个任务（含归档核对时补出的 2.4）—— **9 个完成，8 个显式关闭**（§4 全节 + 5.1/5.2/5.3）。
关闭依据是 `design.md:86` 预置的分支与任务 3.3，**不是半途而废**。

## 一、一句话结论

**目标没达成，但达成了比目标更值钱的东西。**

原目标是「中文金标从 6 条扩到 ≥ 40 条」。实测证明它的前置条件不成立 ——
RAGAS 的 `adapt(language=chinese)` 在**三个候选模型上全部产出 0.0% 中文**，
而且**全部不抛异常**。所以本变更止步于把这个静默失效**变成显式失败**：
从「以为合成了中文、实际是英文」变成「知道做不到，且下次一定会当场报错」。

## 二、决定性实测：三个候选模型全部 FAIL（T-3.1 / T-3.2）

一模型一进程重跑（首轮因 RAGAS 模块级可变单例污染，后两个模型只跑了 3.0 s / 0 文件，无效）：

| 模型 | `effective_judge` | 耗时 | 产出文件 | CJK 占比 | 抛异常 | 判定 |
|---|---|---|---|---|---|---|
| `minimax/minimax-m2.7` | `glm:minimax/minimax-m2.7` | 679.9 s | 11 | 全部 **0.0%** | **否** | **FAIL** |
| `z-ai/glm-5.2` | `glm:z-ai/glm-5.2` | 922.9 s | 11 | 全部 **0.0%** | **否** | **FAIL** |
| `z-ai/glm-5.2-free` | `glm:z-ai/glm-5.2-free` | 769.5 s | 11 | 全部 **0.0%** | **否** | **FAIL** |

原始数据：`logs/ragas_adapt_probe/summary.json`（首轮，仅 minimax 一条有效）、
`summary_z-ai_glm-5.2.json`、`summary_z-ai_glm-5.2-free.json`。
探针脚本：`scripts/dev/probe_ragas_adapt.py`（**破例入库** —— `scripts/dev/` 通常是
一次性脚本，但这三条数字是本变更唯一的判定依据，必须留下复现路径）。

**三者形态完全一致**：跑满 11~15 分钟、写满 11 个 prompt 文件、一个 CJK 字符都没有、
不报错。**这种一致性本身就是结论** —— 失败点不在模型能力，在 RAGAS 0.1.21 的
`adapt()` 实现。

### 两个既有猜想被否证

| 猜想 | 来源 | 实测结论 |
|---|---|---|
| 「minimax 做不了，换 GLM 就行」 | 项目早期记录 | **否证**。两个 GLM 与 minimax 同样 0.0% |
| 「GLM 系不遵从 JSON 其实是 `max_tokens` 误诊」（`retriever-agnostic-golden-labels` 的发现） | 上一个变更 | **在 adapt 任务上不成立**。那个修正对**标注**任务是对的（给足 `max_tokens` 后 1800+ 次判定全部可解析），但 adapt 的失败与 `max_tokens` 无关 —— 它写出了完整的 11 个文件，只是没翻译 |

**判定：无可用合成端模型。** 因此**不更换 `evaluation.judge_llm`**（保持
`glm:minimax/minimax-m2.7`）。连带：`screening_llm`（`glm:z-ai/glm-5.2-free`）与它
仍异源 ✅；`acceptance_thresholds` **无需重新校准**（judge 未变）。

## 三、已落地的净收益（§1 / §2，6 个任务）

原目标的**防护层部分全部做完了**，与合成能否成功无关：

| 能力 | 实现位置 | 关键点 |
|---|---|---|
| 目标语言占比校验（纯函数） | `src/observability/evaluation/language_check.py` | 不 import ragas、不联网 → 单测完全离线 |
| adapt 产物立即校验 + 不通过则删缓存 | `testset_synthesizer.py` | 错误信息与「adapt 抛异常」**明确区分**（前者换模型，后者重试/查网络） |
| 缓存元数据 `_adapt_metadata.json` | `testset_synthesizer.py:65,106` | 记模型完整标识 / 目标语言 / 校验结果 / 实测占比 / 写入时间。**缺元数据或校验未过的缓存 MUST NOT 被使用** |
| 未支持语言明确报错 | `lang_to_ragas` 集中映射 | **不静默按英文合成** —— 那正是第一代产出 33 条英文问题的形态 |
| 合成产物的语种一致性量化 + 越限告警 | `testset_synthesizer._testset_to_candidate` | **2026-08-24 补做**,见 § 六之二 —— 此前是死配置 |
| 配置项 | `SynthesisSettings`：`adapt_language_ratio_min: 0.05` / `question_language_mismatch_warn: 0.20` | 抛 `SettingsError`（非 `ValueError`，本模块既有约定）。0.05 的校准锚点是「未翻译时实测恒为 0.0%」 |

**测试**：本变更相关 **90 个用例**
（`test_language_check.py` / `test_settings_synthesis.py` / `test_adapt_validation.py` /
`test_testset_synthesizer.py`）。全仓 `pytest tests/unit`：**2032 passed, 2 skipped**（硬约束 7 ✅）。

`test_language_check.py::TestRealUntranslatedPrompt` 直接用实际坏产物的形态做输入 ——
**这种产物现在不可能静默通过**。

## 四、被污染的缓存已清除，物证已隔离保留

- `logs/ragas_adapt_cache/chinese/` —— **已删除**（5 个文件 CJK 字符数全为 0）
- `logs/ragas_adapt_cache_POISONED_EVIDENCE/` —— 原样保留 + `README.md`，作为
  「缓存固化坏产物」这条教训的实物证据

## 五、关闭的任务及其去向

| 任务 | 关闭原因 |
|---|---|
| §4 全节（4.1 合成 / 4.2 精修 / 4.3 标注 / 4.4 校验产出） | 四者全部以「adapt 能产出中文」为前置，该前置已被实测否证。强行跑只会再产出一批英文问题的「中文」候选 —— 与第一代 70% 丢弃率的成因完全相同，零信息量 |
| 5.1（settings 指向新文件 + 重标中文基线） | 无新文件可指向。**注意别混淆**：`golden_test_sets_by_lang.zh` 仍应切到上一个变更产出的 `golden_test_set_zh_v2.json`（6 条，`pooled-llm-judged`），那是 BACKLOG 梯队一 **B1**，与本任务（本变更本应合成的 ≥40 条新文件）不是同一件事 |
| 5.2（抽检 ≥ 20 条三元组） | 无新标注产出，无三元组可抽检 |
| 5.3（用新中文金标重跑重排 A/B） | 现有中文金标仅 6 条，样本量不足以支撑 A/B 判定（英文那轮用的是 41 条）。中文侧重排结论需等扩容后才有意义 |

**接续位置**：[openspec/BACKLOG.md](../../../BACKLOG.md) 梯队三 **C1** —— 绕开 RAGAS
evolution，直接用 LLM 从中文 chunk 生成问题。**不要在本变更里续做**，路线不同。

## 六、验收判据逐条对照

| # | 判据 | 结果 |
|---|---|---|
| 1 | adapt 产物确实是中文；不达标时失败且不落盘 | ✅ 机制已落地并单测覆盖。⚠️ **实测无模型能通过**，故这条机制目前只在「拒绝」侧被验证过，「通过」侧只有 fake 产物的单测 |
| 2 | 合成候选语种一致率显著优于第一代 70% | ❌ **未测** —— 合成未执行（§4 关闭） |
| 3 | 最终条数 ≥ 40（SC-002） | ❌ **未达成**。中文仍为 6 条 |
| 4 | 标注 Jaccard 落在 0.328~0.406 量级 | ❌ **未测** |
| 5 | 单元测试全绿（硬约束 7） | ✅ 2026 passed / 2 skipped |

**如实记录**：主目标（判据 3）未达成。本变更的价值全在判据 1 的机制侧与 § 二的否证结论。

## 六之二、⚠️ 归档核对时抓到本病的第八例 —— 就在本变更内部

写 acceptance 时逐条核对 delta spec，发现第三条 ADDED 需求
（**合成产物的语种一致性必须被量化**）**只做了一半**：

- `language_check.mismatch_ratio` / `summarize_language` 写好了，有单测 ✅
- **但没有任何生产路径调用它们** ❌
- `synthesis.question_language_mismatch_warn` 被 `load_settings()` 校验取值范围，
  **然后没有任何代码读它** —— 一个彻头彻尾的死配置 ❌

**这就是 `rerank.top_m` 的第八次重演，而且发生在专门为消灭这个病而立的变更内部。**
它极具说服力地说明：这个病不是「粗心」，而是「写了实现 + 写了单测」这套流程
**结构上不覆盖「实现有没有被接上」** —— 单测测的是函数，没人测那条线。

**已补做**（任务 2.4）：`_testset_to_candidate` 现在产出
`_synthesis_metadata.language_consistency`，越限时告警，措辞刻意指向 adapt 而非语料
（实测成因一直是适配没生效）。新增 6 个用例，其中一条专守「改了 `warn_above`
结论就该变」—— **死配置的判据正是「改了它什么都不变」**。

顺带修掉一个我在补做时引入的真回归：无脑调 `summarize_language` 会让英文合成路径
崩掉（`language_check` 只登记了 `zh`）。修法是 **`measured: false` + 不给
`mismatch_ratio`**，而不是回落成 `0.0` —— 后者会让「没测」和「测过且完美」
长得一样，等于又造一个同病。

**全仓测试**：2032 passed / 2 skipped（补做前 2026）。

## 七、回写的两条通用教训

已写入 `CLAUDE.md` 与 `openspec/config.yaml` § 已知陷阱。**重点不是 RAGAS**：

### ① 缓存会把坏产物永久固化

2026-04-28 那次 adapt 的英文产物被写进磁盘缓存，此后任何一次合成都从磁盘读到英文
prompt，换什么模型都一样。**缓存本是为了绕过「LLM 输出不稳定」，结果把不稳定的产物
永久化了。** 缓存 LLM 产物必须带来源标识与校验标记，且校验未过者不得被读取。

### ② 只捕获异常检测不出静默失效

原有 fail-fast 只捕 `RuntimeError`，而真实失败形态是**不抛异常但没翻译** —— 它「成功」了。
**必须校验产物本身，不能只看有没有报错。**

### 这两条指向本项目的同一个招牌病

把事故排一排：`top_m` 死配置、`--collection` 死参数、`labeling_llm.max_tokens=200`
饿死判定、CJK 全链路 ASCII-only、chunk_id 两端不相交、adapt 静默不翻译、缓存固化坏产物
—— **七次事故同一个病：看起来生效、实际没生效、而且不报错。**

**可操作的判据**：任何「配置项 / 参数 / 转换步骤」上线时，问一句
**「它没生效的时候，我怎么会知道？」** 答不出来就补一条校验或一个断言测试。
这比事后加日志有效得多 —— 上面七次里有六次都有日志，只是日志说的是「成功」。
