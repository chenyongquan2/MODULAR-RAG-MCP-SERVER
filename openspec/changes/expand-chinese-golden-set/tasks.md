> 全部命令在 `.venv` 下运行，**脚本一律加 `-u`**（stdout 管道下全缓冲会伪装成卡死，本项目已踩过两次）。每条任务 = 一次 `pytest tests/unit -v` 全绿的提交，commit message 引用任务号（如 `refs T-1.1`）。

## 1. 语言校验（纯函数，零依赖）

- [x] 1.1 新增语言校验模块：给定文本与目标语言，返回该语言字符的占比与是否达标。**纯函数，不 import ragas、不联网** → 单测可完全离线。中文用 CJK 统一表意文字区间占比（design D1/D2）。同时提供「统计一批文本里语种不一致的比例」的函数，供 T-3.2 复用。配套单测：纯中文 / 纯英文 / 中英混合 / 空串 / 只有标点与 JSON schema 的文本；**必须覆盖「未翻译的 RAGAS prompt」这个真实形态**（实测占比 0.0%）
- [x] 1.2 `src/core/settings.py` 新增 `SynthesisSettings`（`adapt_language_ratio_min` / `question_language_mismatch_warn`），`load_settings()` 校验两者在 `[0.0, 1.0]`，违规抛 `SettingsError`（**不是 `ValueError`** —— 本模块既有约定）；`config/settings.yaml` 写入并注释清楚「未翻译时实测恒为 0.0%」这个校准锚点。配套单测覆盖通过与拒绝两侧

## 2. adapt 产物校验与缓存治理

- [ ] 2.1 `testset_synthesizer.py`：adapt 调用后**立即校验产物语言**，不通过则删除 RAGAS 刚写出的缓存目录并抛错。错误信息必须与「adapt 调用抛异常」**明确区分** —— 两者处置不同（前者换模型，后者重试/查网络）。这是本变更的核心：现有 fail-fast 只捕获异常，而实测的失败形态是**不抛异常但没翻译**。配套单测用假 adapt 产物覆盖三条路径：已翻译通过 / 未翻译被拒且缓存被删 / adapt 抛异常
- [ ] 2.2 缓存元数据 `_adapt_metadata.json`（旁挂，不改 RAGAS 自己的文件）：记产出模型完整标识、目标语言、校验结果与实测占比、写入时间。**缺元数据或校验未通过的缓存 MUST NOT 被使用**；提供强制重建的手段。配套单测：无元数据的旧缓存被拒、校验未通过的缓存被拒、强制重建忽略既有缓存
- [ ] 2.3 未支持的目标语言明确报错并列出已支持项，**不静默按默认语言（英文）合成** —— 那正是第一代产出 33 条英文问题的形态。`lang_to_ragas` 映射集中定义。配套单测

## 3. 合成端模型选型（实测定，不用印象定）

- [ ] 3.1 删除被污染的缓存 `logs/ragas_adapt_cache/chinese/`（现存 5 个文件 CJK 字符数全为 0，已确认无保留价值），然后写一个**只跑 adapt 的探针脚本**，对候选模型各跑一次并输出产物的 CJK 占比。候选至少含 `minimax/minimax-m2.7`（现 judge，据称做不到）与 `z-ai/glm-5.2` / `z-ai/glm-5.2-free`（本会话证明 GLM 的「不遵从 JSON」旧结论其实是 `max_tokens` 误诊）。**不要跳过 minimax** —— 需要它作对照来确认「换模型」是否真是解法
- [ ] 3.2 据实测结果选定合成端模型并记录理由。若最终换掉 `evaluation.judge_llm`，**必须同时确认 `screening_llm` 与它仍异源**（Feature-003 硬要求），并在验收记录里标注 `acceptance_thresholds` 需重新校准
- [ ] 3.3 **若所有候选模型都做不到** —— 本变更止步于「把静默失效变成显式失败」，如实记录各模型的实测占比，把「绕开 RAGAS evolution、直接用 LLM 从中文 chunk 生成问题」列为后续独立变更。**这仍是净收益**：从「以为合成了中文、实际是英文」变成「知道做不到」

## 4. 全链路产出中文金标

- [ ] 4.1 合成：`python -u scripts/synthesize_testset.py --collection default_text-embedding-v4 --lang zh`，目标条数留足余量（第一代 47 条只活下来 6 条；即便 adapt 修好，精修仍会丢一部分）。**记录语种不一致比例**并与第一代的 70%（33/47）对照 —— 这是 adapt 是否真的修好的直接证据
- [ ] 4.2 精修：`python -u scripts/refine_testset.py --input <candidate> --auto-mode`。前置确认预筛端与合成端异源（退出码 2 会挡住）。目标保留 ≥ 40 条
- [ ] 4.3 标注：`python -u scripts/label_golden_chunks.py --input <refined> --output tests/fixtures/golden_test_set_zh_v2.json --collection default_text-embedding-v4`。约 1400 次判定调用，网关会中断 —— 续跑机制已在英文那轮实战验证（跨 4 次中断累积完成）。**不复用第一代的 6 条**（design D7）
- [ ] 4.4 校验产出：条数 ≥ 40、与纯 dense top-K 的 Jaccard 落在英文 0.406 / 中文 6 条 0.328 的量级（接近 1.0 说明池化或判定未生效）、无解 case 已被移出并记进 `unanswerable_cases`

## 5. 验收与文档

- [ ] 5.1 `settings.yaml` 的 `golden_test_sets_by_lang.zh` 指向新文件，旧文件保留；重标中文基线（旧基线是 6 条 + 第一代标注，**完全不可比**）
- [ ] 5.2 抽检：`--export-sample` 导出 ≥ 20 条三元组做校准。**沿用上一个变更确立的做法** —— 若由模型交叉判定，必须**盲评**（先藏掉原判定与理由，否则第二判定方会附和），且结果记为 `cross_judge_agreement_rate` 而非 `human_agreement_rate`
- [ ] 5.3 用新中文金标重跑一次重排 A/B（`none` vs `cross_encoder`）。**不预设结果** —— 中文与英文结论相反是合法发现，上一个变更已实测跨语言压分（中文 query 对语义等价英文答案 0.2973 vs 同语言 0.9998）
- [ ] 5.4 写 `acceptance.md`：如实记录各模型的 adapt 实测占比、语种一致率前后对比、条数、抽检结果、A/B 结论（含负面）。更新 `CLAUDE.md` 与 `openspec/config.yaml` § 已知陷阱 —— **重点是「缓存会把坏产物永久固化」和「只捕获异常检测不出静默失效」这两条通用教训**，它们不限于 RAGAS adapt
