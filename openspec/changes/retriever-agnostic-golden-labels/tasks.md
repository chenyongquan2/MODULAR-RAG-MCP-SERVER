> 全部命令在 `.venv` 下运行，**脚本一律加 `-u`**（stdout 管道下全缓冲会伪装成卡死，本项目已踩过）。每条任务 = 一次 `pytest tests/unit -v` 全绿的提交，commit message 引用任务号（如 `refs T-2.1`）。

## 1. 配置层

- [x] 1.1 `src/core/settings.py`：新增 `LabelingSettings`（`pool_top_n_dense` / `pool_top_n_sparse` / `pool_top_n_rerank` / `relevance_threshold` / `max_judgements` / `judge_failure_warn_ratio` / `dense_overlap_warn` / `human_agreement_warn`）与 `evaluation.labeling_llm`（与 `judge_llm` 同构）。`load_settings()` 新增校验：三个 `pool_top_n_*` >= 0 **且至少两路 > 0**（单路池化违反 spec 第一条需求，必须挡住）、`relevance_threshold ∈ {1,2,3}`、`max_judgements > 0`、三个比例项在 `[0,1]`。**异源校验不放这里**（它要读 candidate 文件里的合成端标识，属运行期前置）。配套 `tests/unit/` 覆盖每条校验的通过与拒绝两侧
- [x] 1.2 `config/settings.yaml` 的 `evaluation` 段按 design § 新增配置项 写入，`labeling_llm.model` 留空（必填，由前置检查兜住），`pool_top_n_rerank` 默认 `0`（重排依赖是 optional extra，保持核心安装即可标注）。注释里写明各项的成本含义与「换模型必须重新校准」

## 2. 候选池化

- [x] 2.1 新增池化模块（`src/observability/evaluation/chunk_pooler.py`）：用 `DenseRetriever` / `SparseRetriever` / `Reranker` 三个现成组件各自取 top-N，**用 `query` 而非 `ground_truth` 作检索输入**（design D3 —— 这是与第一代的关键差异），按 chunk 标识并集去重，每个候选记录 `contributed_by: list[str]`。**不要调 `HybridSearch.search()`** —— 融合后拿不到贡献来源，而 spec 要求记录它。配套单测：三路共同贡献、某一路空结果不中断、去重正确、贡献来源准确、`pool_top_n_rerank=0` 时跳过重排路
- [x] 2.2 池化产出与「纯 dense top-5」的 Jaccard 重合度计算 + 超 `dense_overlap_warn` 时产出告警（不阻断）。这是 spec 里「单路垄断被识别为异常」那条需求的落点 —— 它守的是「池化到底有没有起作用」。配套单测含高重合与低重合两侧

## 3. LLM 判定

- [x] 3.1 判定模块（`src/observability/evaluation/chunk_labeler.py`）：对每个 `(query, ground_truth, chunk)` 让 LLM 返回 0-3 分级相关度 + 理由，`>= relevance_threshold` 纳入。**严格区分「模型整体不可用」与「输出不合格」** —— 复用 `testset_screener.py` 的 `ScreeningUnavailableError` 先例，前者显式失败、后者标记判定失败并继续。配套单测（LLM 全 mock，不触网）：四档解析、无法解析 → 标记失败而非静默算不相关、失败率超阈值告警、单候选失败不终止整轮
- [x] 3.2 异源前置检查：复用 `SourceRelation`（`testset_screener.py:92`）与 `get_judge_identifier`（`_ragas_wrappers.py:351`）的口径，比对 `labeling_llm` 标识与 candidate 的 `_synthesis_metadata.judge_llm_identifier`。**同源 → 拒绝执行（退出码 2）；provider 同名但模型不同 → 视为异源；无法确认 → 默认拒绝，`--allow-same-source` 可豁免但不豁免已确认的同源**。沿用 Feature-003 的退出码语义，使用者不必学第二套。配套单测覆盖三种 relation

## 4. CLI 与产出

- [x] 4.1 新增 `scripts/label_golden_chunks.py`：串起 2.x 池化 + 3.x 判定，写出 `expected_chunk_ids`（二值，字段名与类型不变 → `custom_evaluator.py` 零改动）+ sidecar `_chunk_labels`（分级原值、理由、贡献来源、判定时间）+ `_labeling_metadata`（各路贡献计数、池规模、通过/拒绝/失败计数、两端模型标识、配置快照、告警列表）。`version: "v2.0"` + `_labeling_method: "pooled-llm-judged"`。**不原地覆盖输入文件**（design D9）
- [x] 4.2 `max_judgements` 上限生效 + 续跑：达到上限即停止并写出部分结果，元数据记录**被跳过的候选数**（不谎称已全部判定）；再次执行时读入已有产出，只对无 `label` 的候选发起调用。中断（Ctrl-C）时写出并标 partial，沿用 Feature-003 的 130 退出码。配套单测：上限截断、续跑跳过已判定、中断保留
- [x] 4.3 人工抽检：`--export-sample N` 导出随机三元组（**必须覆盖判定为相关与不相关两类**，不能只抽通过的），`--import-sample` 回填 `human_label` 并把一致率写进元数据，低于 `human_agreement_warn` 产出告警。配套单测：抽样分层、一致率计算、告警触发

## 5. 两代金标可区分

- [x] 5.1 报告侧读 `version` + `_labeling_method`：评估报告记录所用金标的代次与标注方式；当报告与其基线代次不同时，**该 delta 显式标注为不可比**（spec 要求）。涉及 `src/observability/evaluation/eval_runner.py` 与 `baseline_manager.py`。配套单测：同代可比、跨代标不可比
- [x] 5.2 `scripts/backfill_chunk_ids.py` 收尾：docstring 顶部标注「产出第一代（dense-anchored）标签，新标注用 `label_golden_chunks.py`」；修掉死参数 `--collection`（被接受但从不用于实际查询，脚本自己的 docstring 第 74-77 行已承认）—— 要么真正生效，要么移除并说明。**脚本本身保留**，它是第一代金标的可复现来源

## 6. 验收与文档

- [~] 6.1 在 `default_text-embedding-v4` 上跑英文金标（42 条）标注，产出 `golden_test_set_en_v2.json`。**记录实际判定调用数与耗时**。验证 spec 第一条需求：产出中「仅 dense 召回的」「仅 sparse 召回的」「仅重排提升的」chunk **都存在**；若与纯 dense top-5 的 Jaccard > `dense_overlap_warn`，先排查池化/判定是否真的生效再往下走

  **2026-08-13 实际执行:改用中文金标(6 条)先验证,英文 42 条未跑。** 理由是英文按比例约 1500-1700 次判定调用、3-4 小时,而判定口径尚未经人工抽检校准 —— 先用 1/7 的成本验证机制,校准后再跑英文更合理。中文实测结果见 [acceptance.md](acceptance.md) § 二:Jaccard 0.328、31% 的标签是纯 dense 结构上看不到的,机制有效。
  另:本任务原写「仅重排提升的 chunk 都存在」作为判据,**该判据不可满足** —— 重排路重排的是 dense∪sparse 并集,构造上无法引入新候选,详见 spec 里的更正说明
- [ ] 6.2 抽检 ≥ 20 个三元组人工复核，算一致率。**这是判定可信度的唯一闸门，不可跳过**。一致率不达标则先调分级措辞（design § Open Questions 已标该 prompt 需按抽检结果定稿）再重跑，而不是直接接受结果
- [ ] 6.3 用新金标重跑重排 A/B（`none` vs `cross_encoder`，英文）。**不预设结果** —— 负增益缩小或转正都是有效结论，仍为负也是（区别在于这次判据可信）。同时记录 `custom` 四项在两代金标下的差异，作为「金标口径变化」的量化留档
- [x] 6.4 写 `acceptance.md`：如实记录一致率、A/B 结果（含负面）、成本实测。**必须写明本变更去掉的是检索器锚定、不是达到人工级 ground truth**，以及若跳过抽检就等于把一种未验证偏差换成另一种。更新 `CLAUDE.md`（金标代次、新脚本入口、既有基线失效）+ `openspec/config.yaml` § 已知陷阱；`docs/rag-acceptance-plan.md` 与 `docs/learning/agentic-retrieval-boundary.md` 里关于金标构造的待办改为已完成并指向本变更
