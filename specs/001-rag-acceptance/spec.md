# Feature Specification: RAG 质量验收（中英双语基线）

**Feature Branch**: `001-rag-acceptance`
**Created**: 2026-04-25
**Status**: Draft
**Input**: User description: "对现有 MT5 中英文 RAG 系统建立可量化、可回归的质量验收基线。RAGAS 4 指标 + 4 个 custom 检索指标，GLM-4 作为 Judge LLM，中英各 40-50 条共 80-100 条自合成测试集（人工精修）。"

## Clarifications

### Session 2026-04-25

- Q: 8 个聚合指标各自的"合格"绝对阈值采用哪一档预设? → A: Industry reference(业界参考值):RAGAS 4 项 ≥ {context_recall 0.70, context_precision 0.65, faithfulness 0.85, answer_relevancy 0.75};Custom 4 项 ≥ {hit_rate@5 0.60, mrr 0.55, recall@10 0.70, ndcg@10 0.55}。faithfulness 阈值最高,因为幻觉是 RAG 系统的底线问题。
- Q: by-tag 切片子聚合是否参与 pass/fail 判定? → A: 不参与。pass/fail 只看 8 个主聚合指标;切片子聚合(如 `aggregate_metrics_by_content_type.code.*`)仅作为定位短板的诊断信息展示,不构成红线。理由:切片样本量小、噪声大,主聚合的 pass/fail 信号更稳定。
- Q: 当报告输出 `acceptance_status: fail` 时,对"标记基线"操作的限制是? → A: 仅信号提示,不阻断。fail 报告允许被标记为基线(以便在系统未达标阶段也能建立"早期参考点"驱动 SC-005 的回归机制),面板必须以颜色/标签视觉区分 pass/fail 基线;不引入软/硬阻断逻辑。
- Q: Judge LLM 是否可配置(不绑定 GLM-4)? → A: 必须可配置。新增 FR-016 规定 Judge LLM 通过 settings.yaml 配置切换,复用项目现有 LLMFactory 的 5 个 provider(`glm` / `azure` / `openai` / `ollama` / `deepseek`),默认 GLM-4(免费额度 + 中英双语覆盖足够);评估报告的 `judge_llm_identifier` 字段必须如实记录该次评估所用 provider + model,保证跨 Judge 的报告可追溯。理由:与项目"配置驱动、provider-agnostic"的核心架构一致,避免在 spec 层把 Judge 写死。
- Q: Vector store 后端是否在 spec 层绑定 ChromaDB? → A: 不绑定。spec 通篇引用"项目当前 vector store",MVP 阶段实际后端为 ChromaDB(项目当前唯一实现),但 FR-007 与所有 user story 不在 spec 层硬编码"ChromaDB"。理由:与 GLM-4 同构的 provider-agnostic 问题——若未来加 Qdrant / Milvus,本 spec 不需修改。
- Q: FR-013 阈值清单是否随 Judge 切换需要重新校准,且是否可配置? → A: 是。阈值改为可配置(默认值即原 industry reference 8 项,可通过 settings.yaml 的 `evaluation.acceptance_thresholds.*` 覆盖)。Assumption 补充"Judge 切换与阈值校准"条目,说明换 Judge 时建议先重跑校准而非直接套用默认。EvaluationReport 新增 `acceptance_thresholds_snapshot` 字段,固化每次评估生效的阈值,便于跨评估对比时查阅。
- Q: 评估流程使用的 embedding 模型是否需要在 spec 显式约束(避免隐式硬编码)? → A: 是,新增 FR-017。embedding 必须通过 settings.yaml 配置、复用项目 EmbeddingFactory 的 5 个 provider(`bge` / `openai` / `azure` / `ollama` / `glm`),默认与 production query 用的 embedding **保持一致**(避免 train-eval skew)。评估流程的所有 embedding 环节(RAGAS 内部相似度、ground_truth-chunk 语义匹配等)MUST 使用同一配置;评估报告 `embedding_identifier` 必须记录所用 provider + model。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 端到端跑通评估管线（Priority: P1）🎯 MVP

作为 RAG 系统的质量负责人，我希望在不改动评估代码（仅启用配置）的前提下，把现有占位测试集替换为指向真实知识片段的最小可用集合，并运行一次完整评估，确认输出包含全部目标指标且无错误——以此证明"评估管线本身在我们的语料上是可用的"，从而消除"代码已写好但从未在真实 MT5 数据上验证过"的不确定性。

**Why this priority**：这是整条验收链条的"地基"。在花时间合成 80-100 条测试集（US2）之前，必须先确认评估管线在真实语料上能跑通。如果 Judge LLM 接入异常、`contexts` 字段是 chunk ID 而非真实文本、或某个指标抛 ValueError，那 US2 产出的大数据集也会浪费。MVP 自身就有独立交付价值：让团队第一次在真实 MT5 数据上看到 RAG 系统的"粗略画像"。

**Independent Test**：把现有占位测试集（位于 `tests/fixtures/golden_test_set.json` 等项目内已有 fixture）中 4 条用例的 expected_chunk_ids 改为项目当前 vector store 中存在的真实 chunk ID（任意 4 个；MVP 阶段实际后端为 ChromaDB,spec 不绑定具体后端）,针对中文 collection 跑一次端到端评估（含答案生成），观察输出 JSON 中 `aggregate_metrics` 字段是否同时包含 `custom__hit_rate / custom__mrr / custom__recall / custom__ndcg / ragas__faithfulness / ragas__answer_relevancy / ragas__context_precision / ragas__context_recall` 共 8 个键、值是否都为 0~1 之间的有限数字（非 NaN/None），且整个流程无未捕获异常。

**Acceptance Scenarios**：

1. **Given** RAGAS 评估 backend 当前被禁用且占位测试集 expected_chunk_ids 与真实数据不匹配，**When** 启用 RAGAS backend、在 settings.yaml 中配置任一受支持的 Judge LLM(默认 GLM-4)、修正占位测试集后运行一次中文评估，**Then** 评估报告中 8 个聚合指标全部存在且为有限数字、`per_case_metrics` 中每条用例的 `contexts` 字段是可读文本（非 chunk ID）、`judge_llm_identifier` 字段如实记录所用 Judge,评估流程无未捕获异常。
2. **Given** Judge LLM 配置错误（例如错误的 base URL 或 API Key,无论 provider 是 GLM/OpenAI/Azure 等哪一个），**When** 运行评估，**Then** 系统在最早合理阶段报错并明确指出 Judge 配置问题，而不是静默产出 NaN 或退化为非 LLM 评估。
3. **Given** 中文集合评估通过，**When** 切换 collection 到英文跑同样的流程，**Then** 英文评估同样产出 8 个指标的有限数字（数值可不同，结构一致）。

---

### User Story 2 - 合成并精修真实 MT5 测试集（Priority: P2）

作为质量负责人，我希望基于已摄入的真实 MT5 中英文语料自动合成大约 100 条候选 (question, ground_truth) 对，再人工精修筛选到 80-100 条最终测试集，并把对应的 expected_chunk_ids 回填到真实知识片段——以此把"4 条占位用例"升级为"足够支撑统计意义评估"的金标集合，让基线指标具备代表性而不是采样噪声。

**Why this priority**：US1 跑通后只能用 4-8 条用例做"烟雾测试"，统计意义弱（单条用例命中/不命中就能让 hit_rate 跳 25%）。要建立"可作为后续回归对比的基线"，必须达到行业最佳实践的下限规模（每语种 40+ 条）。但这个工作必须依赖 US1 验证过的管线，所以排在 P2。

**Independent Test**：跑完 US2 后，仓库内存在两份金标测试集（中文一份、英文一份），每份 ≥ 40 条用例；对每份随机抽 10% 用例由人工 review，question 通顺、ground_truth 可在原始语料中验证、expected_chunk_ids 指向项目 vector store 中实际存在的 chunk；测试集难度分布同时包含简单事实题、推理题、跨段综合题（任一类型 ≥ 10%）。

**Acceptance Scenarios**：

1. **Given** US1 已交付（评估管线可用）且中英 MT5 语料已分别摄入到独立 collection，**When** 运行测试集合成流程，**Then** 产出中英各约 100 条 (question, ground_truth, source contexts) 候选用例。
2. **Given** 候选用例已生成，**When** 人工精修流程把每条用例标记为 keep / edit / drop，**Then** 最终保留 80-100 条用例，且每条至少经过一次人工读过。
3. **Given** 精修后用例尚无 expected_chunk_ids，**When** 跑回填流程把每条 question 的 ground_truth 与项目 vector store 中真实 chunk 做语义匹配，**Then** 每条用例的 expected_chunk_ids 是 vector store 中真实存在的标识符（非占位字符串），且抽检 10% 用例时回填的 chunk 与 ground_truth 语义相符。
4. **Given** 精修后的金标集合，**When** 检视任意一条用例，**Then** 该用例必须含 `tags` 字段，至少包含 `content_type`（text / code / table / mixed）、`difficulty`（simple / reasoning / multi_context）、`language`（zh / en）、`doc_version`（首版固定为 `v1`）四个维度。
5. **Given** 最终金标集合就绪，**When** 用它对中英任一 collection 重跑 US1 的评估流程，**Then** 8 个指标全部产出有限数字（结构与 US1 一致），且因为样本量提升数值稳定性显著高于 4 条样例的结果。

---

### User Story 3 - 标记基线并支持回归对比（Priority: P3）

作为质量负责人，我希望能把任意一次完整评估结果标记为"基线"，之后每次重跑评估都能立即看到与基线的 delta，并通过可视化面板查看趋势——以此把"一次性的验收实验"升级为"日常迭代的回归保障"，让后续任何检索/生成层改动都能被量化评估其影响。

**Why this priority**：没有 US3，US1+US2 的产物只是一次"快照式验收"，无法支撑后续系统迭代。但 US3 完全依赖 US2 产出的稳定测试集（用占位用例标基线没意义），所以排在 P3。

**Independent Test**：在 US2 完成后，针对中英各跑一次完整评估并标记两份结果为基线；之后任意修改一项 RAG 配置（例如 top_k 从 5 改 10），重跑同一份测试集，能在可视化面板上同时看到"当前结果"与"基线"，并展示每个指标的 delta；面板中存在历史趋势视图。

**Acceptance Scenarios**：

1. **Given** 中英两份完整评估报告已生成，**When** 在面板中把它们各自标记为基线，**Then** 后续访问面板时可以识别哪份是当前基线，并看到基线的元数据（评估时间、所用测试集版本、所用 collection）。
2. **Given** 中文基线已标记，**When** 修改任一 RAG 配置后用相同测试集重跑评估，**Then** 面板可同时显示当前结果与基线，且每个聚合指标都附带 delta 值（含正负方向）。
3. **Given** 已积累 ≥ 3 次评估记录，**When** 进入面板的趋势视图，**Then** 可看到每个指标随时间的折线变化，可识别趋势上升/下降。
4. **Given** 评估完成后产出了报告，**When** 检视报告的 `aggregate_metrics`，**Then** 除了"全集"维度的指标之外，还能按 `tags.content_type` 与 `tags.difficulty` 各自独立聚合的子指标存在（例如 `aggregate_metrics_by_content_type.code.ragas__faithfulness`），用于定位"哪种内容类型/难度的能力短板"。

---

### Edge Cases

- **Judge LLM 不可用**：评估期间 Judge LLM 调用超时或返回非法 JSON，单条用例的 RAGAS 指标退化为 NaN——系统应在报告中明确标记降级用例数量，而不是静默丢弃，以便人工判断是否重跑。
- **chunk_id 漂移**：测试集生成后再次执行摄取（例如 splitter 调整），原 expected_chunk_ids 失效，custom 指标全 0——系统应在评估开始前校验所有 expected_chunk_ids 在项目当前 vector store 中存在，缺失时给出可定位的错误信息（哪条用例哪个 ID 缺失）。
- **测试集人工精修产出 < 40 条**：US2 验收前置门槛，此时 US3 的"基线"会因样本量不足而失效——系统应在标记基线时检查测试集大小，< 40 条时拒绝标记或显著警告。
- **中英语料规模差异**：MT5 中英文文档篇幅/章节数可能不对称，导致合成阶段两种语言生成数量不均衡——合成流程应允许各自独立设置目标量，并在精修阶段允许其中一种保留更多用例（保持总量 80-100）。
- **首次评估时无基线**：US3 的回归对比依赖基线已存在，首次评估必须既"产出报告"又"承担基线候选"——系统应在面板提供"标记为基线"显式动作，而非自动把首份报告设为基线。
- **文档形态扩展（v1 → v2）**：未来语料从纯文本扩展到含代码/表格内容时，需要支持"老题不退化 + 新题达标"双红线评估——系统应允许按 `doc_version` 过滤金标用例，针对 v1 子集重跑评估并与 v1 时代基线做 delta 对比（历史回归），同时新增 v2 题目专测新内容类型（新能力达标）；本 feature MVP 阶段只需要 schema 与切片能力到位，真正"v2 增量题"在后续 feature 启动。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**：评估系统 MUST 在单次执行中同时产出 RAGAS 系列指标（faithfulness、answer_relevancy、context_precision、context_recall）与 custom 检索系列指标（hit_rate、mrr、recall、ndcg），且每个指标都是 0~1 之间的有限数字（NaN 仅允许在显式降级场景）。
- **FR-002**：评估系统 MUST 支持把中文 MT5 与英文 MT5 作为两个独立 collection 分别评估，单次评估只针对一个 collection。
- **FR-003**：评估管线 MUST 在每条用例的 `per_case_metrics` 中保存检索到的 contexts 字段为可读知识片段文本，而不是 chunk ID 或仅元数据，以满足 RAGAS 指标的输入约定。
- **FR-004**：测试集生成流程 MUST 从已摄入的真实 MT5 语料自动合成至少 100 条候选 (question, ground_truth) 对，候选难度同时覆盖简单事实题、推理题、跨段综合题。
- **FR-005**：测试集精修流程 MUST 提供逐条人工 keep / edit / drop 操作的最小工具支持（不限定 CLI 或脚本形式），并把精修结果固化为可重复使用的金标 JSON 文件。
- **FR-006**：最终金标测试集（中、英各一份）的合计规模 MUST 在 80-100 条之间，单语种规模 MUST ≥ 40 条；每条用例 MUST 同时含 question / ground_truth / expected_chunk_ids / expected_sources 四个字段。
- **FR-007**：金标测试集的 expected_chunk_ids MUST 全部为项目当前配置的 vector store 中实际存在的 chunk 标识符（非占位字符串;具体实现后端由项目 vector store 配置决定,本 feature MVP 阶段实际后端为 ChromaDB,但 spec 不绑定具体后端）；评估开始前 MUST 校验所有 ID 存在，缺失时拒绝执行并输出可定位的错误信息。
- **FR-008**：评估结果 MUST 可通过可视化面板显式标记为"基线"；同一 collection 在任意时刻只能有一份当前基线，但可保留历史基线记录。
- **FR-009**：每次评估完成后，系统 MUST 自动计算当前结果与同 collection 当前基线之间每个聚合指标的 delta（含方向），并在面板中展示。
- **FR-010**：面板 MUST 提供历史评估的趋势视图，至少展示每个聚合指标的时序折线。
- **FR-011**：本验收过程产出的中间数据（候选测试集、精修临时文件、评估日志）MUST 按现有版本控制规则处理，不要求修改 `.gitignore` 现状。
- **FR-012**：金标测试集本身（最终的 JSON 文件）MUST 可被多次重复使用以支撑回归对比，即测试集在被新一轮"再合成"覆盖之前内容稳定。
- **FR-013**：评估流程 MUST 输出"验收结论"标识（pass / fail），判定规则为：当且仅当当次评估报告的 8 个主聚合指标全部满足该次评估生效的阈值清单时输出 pass，否则 fail。阈值清单 MUST 通过 settings.yaml 配置(例如 `evaluation.acceptance_thresholds.<metric_name>` 字段,具体 schema 由 plan 阶段决定);未在配置中指定时使用以下**默认值**(业界参考值,绑定默认 Judge=GLM-4 假设):`ragas__context_recall ≥ 0.70`、`ragas__context_precision ≥ 0.65`、`ragas__faithfulness ≥ 0.85`、`ragas__answer_relevancy ≥ 0.75`、`custom__hit_rate@5 ≥ 0.60`、`custom__mrr ≥ 0.55`、`custom__recall@10 ≥ 0.70`、`custom__ndcg@10 ≥ 0.55`。每次评估生成的报告 MUST 在 `acceptance_thresholds_snapshot` 字段中固化该次评估实际生效的阈值清单(便于跨评估对比时知道阈值是否变过)。pass/fail 仅作为基线消费方的可读结论标识，不阻断报告输出本身。
- **FR-014**：金标测试集每条用例 MUST 含 `tags` 字段（结构化对象），至少覆盖 4 个维度：`content_type`（取值 `text` / `code` / `table` / `mixed`）、`difficulty`（取值 `simple` / `reasoning` / `multi_context`）、`language`（取值 `zh` / `en`）、`doc_version`（首版固定为 `v1`，未来文档形态扩展时递增）。本 feature MVP 阶段中文集合可全部为 `content_type=text`，但 schema 字段必须存在（为未来扩展预留 hook）。
- **FR-015**：评估报告 MUST 在主聚合指标之外，额外提供按 `tags` 切片的子聚合指标——至少支持按 `content_type` 与 `difficulty` 两个维度独立聚合，命名形如 `aggregate_metrics_by_content_type.<value>.<metric>`；切片时每片样本量 < 5 条则跳过该片并在报告中显式标注（避免噪声）。切片子聚合 MUST NOT 参与 FR-013 的 pass/fail 判定,仅作为定位短板(哪个 content_type/difficulty 表现差)的诊断信息展示。
- **FR-016**：Judge LLM MUST 通过 settings.yaml 配置(例如 `evaluation.judge_llm.provider` / `model` / `api_key` 等字段,具体 schema 由 plan 阶段决定)指定,且 MUST 复用项目现有的 LLMFactory 注册的 provider 列表(`glm` / `azure` / `openai` / `ollama` / `deepseek`)——切换 Judge 不需要修改评估代码,仅需改配置后重启。默认 provider 为 GLM-4(已与 owner 在 2026-04-22 确认,理由:免费额度 + 中英双语覆盖足够);评估报告 `judge_llm_identifier` 字段 MUST 如实记录该次评估实际使用的 provider + model 标识符,以保证不同 Judge 跑出的报告可追溯、可对比。
- **FR-017**：评估流程使用的 embedding 模型 MUST 通过 settings.yaml 配置指定,且 MUST 复用项目现有的 EmbeddingFactory 注册的 provider 列表(`bge` / `openai` / `azure` / `ollama` / `glm`),不引入"评估专用 embedding"这一独立通道。默认 embedding MUST 与项目 production 阶段 query 流程使用的 embedding **保持一致**(避免 train-eval skew——若评估用 BGE 但 production 用 OpenAI,评出的 context_recall / context_precision 反映的是评估器自己的偏好而非真实查询体验)。**评估流程内部需要 embedding 的所有环节** MUST 使用同一配置:含(a) RAGAS context_precision / context_recall 内部的相似度判断、(b) US2 ground_truth 与 chunk 的语义匹配回填流程、(c) 任何其他需要句向量的环节;不允许评估流程的不同环节使用不同 embedding。评估报告 `embedding_identifier` 字段 MUST 如实记录该次评估实际使用的 embedding provider + model,以保证不同 embedding 跑出的报告可追溯、可对比。

### Key Entities

- **TestCase**：单条评估用例，关键属性 = { query, expected_chunk_ids[], expected_sources[], ground_truth, **tags{ content_type, difficulty, language, doc_version }** }。
- **GoldenTestSet**：一份语种维度的金标用例集合，关键属性 = { language, version, cases[], created_at, source_corpus_collection }；同一语种在某一时刻只有一份"当前在用"。
- **EvaluationReport**：一次完整评估的完整结果，关键属性 = { collection, test_set_version, aggregate_metrics{8 项}, **aggregate_metrics_by_tag{ content_type{...}, difficulty{...} }**, per_case_metrics[], judge_llm_identifier, **embedding_identifier**, **acceptance_thresholds_snapshot{<metric_name>: threshold}**, run_id, created_at, degraded_case_count, acceptance_status (pass/fail) }。
- **Baseline**：被显式标记的某份 EvaluationReport，关键属性 = { report_id, marked_at, marked_by, lang/collection 维度 }；同一 collection 同一时刻只有一份当前基线。
- **DeltaReport**：当前评估结果与基线的对比，关键属性 = { current_report_id, baseline_report_id, per_metric_delta{}, **per_tag_delta{ content_type{...}, difficulty{...} }** }；每次评估完成后自动产生（若该 collection 已有基线）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**：在 MVP（US1）阶段交付时，针对中英任一 collection 的端到端评估能在 1 次内全部 8 个指标产出有限数字，无需重试或代码补丁。
- **SC-002**：在 US2 交付时，中英金标集合各 ≥ 40 条用例（合计 80-100 条），且对每份金标集随机抽样 10% 用例做人工 review，结构合规率（question 通顺 + ground_truth 可在原始语料中验证 + expected_chunk_ids 指向真实存在的 chunk）≥ 90%。
- **SC-003**：在 US2 完成后，单次中英完整评估端到端耗时（含答案生成 + 全 8 项指标计算）≤ 60 分钟（每语种 ≤ 30 分钟），让"改一次配置 → 看一次回归 delta"在工作时间内可承受。
- **SC-004**：在 US3 交付后，新一轮评估完成的同时，面板能在 1 分钟内呈现与基线的 delta 视图（不要求人工额外操作）。
- **SC-005**：基线建立 30 天内，至少能识别一次"系统配置改动 → 指标 delta"的真实案例（无论 delta 正负），证明回归机制实际被消费而不是摆设。
- **SC-006**：评估流程的"降级用例"占比（FR-001 中允许 NaN 的场景）在金标集上 ≤ 5%，否则视为 Judge LLM 接入或测试集质量需要回查。
- **SC-007**：在 US3 交付后,首次被标记为基线的评估报告 MUST 满足 FR-013 定义的全部 8 个主聚合指标阈值(业界参考值,见 FR-013);若任一指标低于阈值,基线仍可被标记(用于建立"早期参考点"),但报告必须显式携带 `acceptance_status: fail` 标识,且面板必须以视觉方式(例如颜色/标签)区别于 pass 基线。
- **SC-008**：未来某次文档形态扩展（v1 → v2，例如 MT5 文档新增代码段或表格）后，针对 `doc_version=v1` 子集重跑评估，每个聚合指标的 delta ≥ -0.02（不退化为统计噪声以外的下降），否则触发回归排查；本指标的可验证性依赖 FR-014 的 `tags.doc_version` 字段与 FR-015 的切片能力，在本 feature MVP 阶段只需 schema 到位即可，真正首次"v2 扩展"的验收在后续 feature。

## Assumptions

- **Judge LLM 选型**：默认使用 GLM-4 作为 RAGAS Judge（已与 owner 在 2026-04-22 确认,理由:免费额度 + 中英双语覆盖足够,详见 docs/rag-acceptance-plan.md § 0.3），通过 OpenAI 兼容协议接入。**但 Judge 不锁死**——见 FR-016,Judge LLM 通过 settings.yaml 配置切换,可选 provider 与项目其他 LLM 一致(`glm` / `azure` / `openai` / `ollama` / `deepseek`)。本 spec 不在 MVP 范围内引入"多 Judge 集成投票"或"Judge 自身能力对照"等高级模式。
- **Judge 切换与阈值校准**：不同 Judge LLM 对相同 (q, ctx, answer) 跑同一指标存在系统性偏差(论文与业界经验:大约 3~10 个百分点的判分风格差异)。FR-013 给出的默认阈值清单**绑定默认 Judge=GLM-4 假设**。切换 Judge 时建议:(a) 先在新 Judge 下用现有金标集合重跑评估、观察分数分布,(b) 据新分布在 settings.yaml 的 `evaluation.acceptance_thresholds.*` 重新校准阈值,而非直接套用默认值。本 feature MVP 不要求实现自动校准工具;`acceptance_thresholds_snapshot` 字段(见 EvaluationReport entity)使每份报告都自带"阈值上下文",方便后续校准时查阅历史。同样道理也适用于切换 embedding——embedding 改动会引起 RAGAS 内部相似度尺度变化,变更后建议参照同样的校准流程。
- **数据集策略**：采用"自动合成 + 人工精修"路径（行业最佳实践），不引入外部公开 RAG 测试集（如 RGB / CRUD-RAG / DuReader）作为验收主依据；公开测试集仅作为可选的外部参照（不在本 feature MVP 范围内）。
- **测试集规模**：中英各 40-50 条、合计 80-100 条（已与 owner 确认，详见 docs/rag-acceptance-plan.md § Context）。规模选择是"统计稳定性 vs 人工精修工时"的折中。
- **语料前置条件**：MT5 中文与英文手册已分别摄入到独立 collection(具体后端由项目 vector store 配置决定,MVP 阶段实际后端为 ChromaDB,详见 docs/rag-acceptance-plan.md § 0.4）；本 feature 不重新讨论 ingestion 策略。
- **难度分布**：合成阶段建议简单事实题 50% / 推理题 30% / 跨段综合题 20%（来自 RAGAS TestsetGenerator 默认分布的本地化调整），精修阶段允许偏离但每类不为 0。
- **Step 6 横向对照不在 MVP**：rag-acceptance-plan.md § Step 6 中描述的"在 RGB 等公开数据集上做能力对照"标记为可选，不写入本 feature MVP 范围；后续可作为独立 feature 启动。
- **现有评估代码可复用**：项目已具备 4 个 RAGAS 指标 + 4 个 custom 指标的实现（详见 docs/rag-acceptance-plan.md § Context）；本 feature 主要是"配置启用 + Judge 接入 + 数据集到位 + 基线机制"，不要求重写评估器。
- **基线消费方**：基线主要服务于本项目的开发者/AI 助手（用于回归对比），不需要对外暴露 API 或权限管理。
- **tags 设计动机（双层评估架构）**：FR-014/FR-015/SC-008 引入的 `tags` 字段与 by-tag 切片，是为应对"文档形态在系统生命周期中持续演进（纯文本 → 含代码/表格 → ...）"这一工业现实——它让金标测试集能"增量演进"（v1 题保留做历史回归，v2 题专测新能力），评估能"按维度切片定位短板"。设计原理详见 [docs/rag-acceptance-plan.md § 评估架构：双层视角](../../docs/rag-acceptance-plan.md)。本 feature MVP 阶段只引入"业务回归层"（Layer A），按能力维度的公开 benchmark 评估（Layer B，如 RGB / TabFact / CodeSearchNet）作为独立 feature 后续启动。
