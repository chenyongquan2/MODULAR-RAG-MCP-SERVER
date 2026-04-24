# Feature Specification: 多模态查询响应链路闭合（Multimodal Query Response）

**Feature Branch**: `002-multimodal-query-response`
**Created**: 2026-04-23
**Status**: Draft
**Input**: User description: "为 MCP 查询工具 query_knowledge_hub 闭合多模态返回链路。项目已实现文档图片的提取、Vision Captioning、存储、caption 融合向量化与检索层透传，但 MCP 工具层未调用 MultimodalAssembler，导致客户端只能看到文字。"

## Clarifications

### Session 2026-04-23

- Q: 图片数量上限（默认 10）应硬编码还是配置化？ → A: 配置化，在 `settings.yaml` 新增 `query.max_images_per_response`，默认 10（选项 B）。
- Q: `use_llm=true` 模式下附图策略（命中 chunk 所有图 vs LLM 精细引用过滤）？ → A: 命中 chunk 所有关联图都附上，与 `use_llm=false` 一致；不依赖 LLM 文本引用（选项 A）。
- Q: 超大图片（> 5MB）是否需服务端压缩/跳过？ → A: 原样返回，不压缩、不跳过（选项 A）。后续若实际出现响应体过大问题，再开独立 feature 处理。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 用户通过 MCP 客户端检索图片内容（Priority: P1）

作为一名通过 Claude Desktop / GitHub Copilot 等 MCP 客户端使用本知识库的业务用户，当我的问题与文档中的某张插图相关时（例如"架构图里的 Reranker 与 Fusion 的关系是什么？"），我希望检索结果里**直接附上这张图**，而不是只拿到一段引用了图片的文字。这样我能一眼确认 AI 的回答是否对应我记忆中的图示，也避免我再去硬盘/原始 PDF 里翻找。

**Why this priority**：这是本 feature 存在的唯一理由。图片摄取管线已完成大量工作（提取、Vision LLM 描述、存储、与 chunk 融合），但若查询链路最后一步缺失，前面全部工作对最终用户不可见。P1 覆盖纯检索模式（`use_llm=false`），是最小价值切片。

**Independent Test**：可独立验证——摄取一份含 2+ 张图的 PDF（如 `asset/rag_test_doc.md` 扩展版或现成的 `tests/fixtures/sample_documents/` 含图样本）→ 在 MCP 客户端调用 `query_knowledge_hub({query: "<涉及图片的问题>", use_llm: false})` → 断言返回的内容列表**同时**包含 `TextContent`（检索到的 chunk 文本）与至少一条 `ImageContent`（base64 非空、mimeType 合法），且该图确实属于命中 chunk 的引用图。

**Acceptance Scenarios**:

1. **Given** 知识库已摄取含图 PDF 且生成了 caption，**When** 用户用 `use_llm=false` 调用 `query_knowledge_hub` 查询涉及某张图的问题，**Then** MCP 响应里同时包含命中 chunk 的文本与该 chunk 关联图片的二进制内容（可直接在 MCP 客户端 UI 渲染）。
2. **Given** 命中的 chunk 没有关联图片，**When** 用户查询该 chunk，**Then** MCP 响应只包含文本，**不报错**，不出现空的 ImageContent 占位。
3. **Given** 某个 image_id 在 metadata 中存在但磁盘文件已丢失（被手动清理），**When** 查询命中该 chunk，**Then** 响应返回文本 + 降级日志（不中断响应），其余可读的图片仍被返回。

---

### User Story 2 - 用户在 LLM 总结模式下看到图文结合的答案（Priority: P2）

作为同一类业务用户，当我开启 `use_llm=true` 让系统生成一段总结性答案时，我希望 LLM 不仅在文字里提到"下图说明了……"，而且**真的能把被引用的图片一起返回**。进一步，LLM 在生成回答时应能**感知到图片描述**（因为 caption 已经融合进 chunk 文本），从而在答案里自然地指涉图片。

**Why this priority**：P2 而非 P1，因为：(a) 总结模式消耗 LLM token，是进阶用法；(b) 即便不做此项，P1 已能让用户看到图片，价值未丢失。但做了 P2，图文答案的阅读体验显著优于纯检索。

**Independent Test**：摄取同样含图 PDF → 调用 `query_knowledge_hub({query: "总结图中展示的架构", use_llm: true})` → 断言返回内容同时含有 LLM 生成的 Markdown 文本（其中明确引用了图中元素）+ 相关图片的 ImageContent。

**Acceptance Scenarios**:

1. **Given** 命中的 chunk 文本里含 `[图片描述: ...]` 段（由 TextEnricher 注入），**When** LLM 总结模式被调用，**Then** 生成的答案能在语义上引用图片内容（说明 LLM 感知到了描述），且响应里附带被引用的图片。
2. **Given** 同一查询命中多个 chunk、涉及多张图，**When** LLM 总结模式生成答案，**Then** 返回的 ImageContent 按照被引用的相关性顺序排列，且不重复返回同一张图（以 image_id 去重）。

---

### User Story 3 - 运维/开发者通过测试与日志信任此链路（Priority: P3）

作为本项目的维护者，我希望这条新链路有**可重复的自动化测试**与**清晰的可观测性**，以便未来重构检索或响应层时不会悄悄回归。

**Why this priority**：非用户直接使用场景，但对项目长期质量至关重要。P3 合理，因为 P1/P2 的手工验证已能 ship，测试是第二波保障。

**Independent Test**：`pytest` 运行新增的集成测试（`tests/integration/test_multimodal_query.py`），在 mock 过的 MCP 环境下覆盖「摄取→查询→返回 ImageContent」完整路径；在 logs/traces.jsonl 中能看到多模态组装阶段的 trace 记录。

**Acceptance Scenarios**:

1. **Given** 运行 `pytest tests/integration -v`，**When** 新增用例执行，**Then** 用例通过，且至少验证了「响应含 ImageContent」「base64 非空」「mimeType 合法」「图片读取失败时不中断文本返回」四点。
2. **Given** 运行一次含图查询，**When** 查看 `logs/traces.jsonl`，**Then** 能看到查询 trace 里新增的组装阶段（如 `assemble_multimodal`）及其耗时、组装图片数。

---

### Edge Cases

- **图片文件缺失**：metadata 中记录了 image_id，但 `data/images/<collection>/<image_id>.png` 被删除。系统须记录 warning 日志、跳过该图、继续返回其余内容，不抛异常。
- **超大图片**：某张图体积很大（> 5MB），base64 编码后显著增加响应体大小。本版本**直接原样返回，不做服务端压缩/裁剪/跳过**；由 MCP 协议与客户端自身的大小策略兜底。若未来实际出现响应体过大问题，再开独立 feature 引入压缩逻辑。
- **图片数量爆炸**：一次查询命中 20 个 chunk，每个 chunk 3 张图。需有上限，避免响应过大。默认上限：**每次响应最多返回前 10 张去重后的图片**，按 chunk rerank 顺序取。
- **LLM 总结模式下 LLM 输出未引用图片**：LLM 自由发挥，生成的文字里可能完全不提图。此时是否仍附图？采用"附上命中 chunk 的图"策略（不依赖 LLM 引用行为），保持与 P1 一致。
- **纯 Markdown 文档摄取（未含图）**：查询时没有图片可返回。链路须兼容，返回纯文本不报错。
- **图片 ID 格式异常 / ImageStorage 不可用**：降级为纯文本返回，记录 error 日志。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 当 MCP 客户端调用 `query_knowledge_hub` 且命中的 chunk 在元数据中含有图片引用时，响应 MUST 同时返回文本与对应图片的二进制内容（以 MCP 协议规定的图片内容类型编码），且两者在同一次响应内返回。
- **FR-002**: 系统 MUST 在 `use_llm=false`（纯检索）与 `use_llm=true`（LLM 总结）两种模式下均附加图片，且两种模式下「哪些图被返回」的判定规则一致——以**命中 chunk 的图片引用集合**为准，不依赖 LLM 输出文本。
- **FR-003**: 单次响应返回的图片 MUST 按 image_id 去重；多 chunk 命中同一张图时仅返回一份。
- **FR-004**: 单次响应返回的图片数量 MUST 有上限，该上限通过配置项 `query.max_images_per_response`（位于 `config/settings.yaml`）控制，默认值为 10；超出时按命中 chunk 的 rerank 顺序取前 N 张。
- **FR-005**: 当图片文件在磁盘上缺失或读取失败时，系统 MUST 记录 warning 级别日志并跳过该图，继续返回其余文本与可用图片，**不得中断整个响应**。
- **FR-006**: 当 ImageStorage 组件不可用（初始化失败、数据库损坏等）时，系统 MUST 降级为纯文本响应并记录 error 级日志，不得让查询接口整体失败。
- **FR-007**: LLM 总结模式下，LLM 的上下文 MUST 能读到 chunk 文本中融合的 `[图片描述: ...]` 片段（已由 TextEnricher 在摄取时写入，查询侧无需特殊处理，仅需确保不剥离该片段）。
- **FR-008**: 新链路 MUST 保留并扩展现有可观测性——查询 trace 记录（`logs/traces.jsonl`）中需新增反映"多模态组装"的阶段字段（名称、组装图片数、耗时），与现有 stage 字段保持一致风格。
- **FR-009**: 系统 MUST 提供针对"查询返回图片"端到端路径的自动化测试，覆盖：响应含图、base64 合法、缺图降级、无图查询兼容。
- **FR-010**: 现有所有不涉及图片的查询测试用例 MUST 不回归（同样的输入产生同样的文本输出）。
- **FR-011**: 响应中返回的图片 MUST 能被标准 MCP 客户端（Claude Desktop、GitHub Copilot 等）直接渲染；至少需支持 PNG 与 JPEG 两种 mimeType。

### Key Entities

- **图片引用（ImageReference）**：chunk 元数据中描述"该 chunk 关联哪些图片"的结构，核心属性为 image_id、在文本中的位置偏移、所属文档。摄取侧已产出，本 feature 仅消费，不修改结构。
- **图片资源（ImageAsset）**：实际的图片文件（PNG/JPEG 等），由 ImageStorage 以 image_id 为键读取。
- **多模态响应项（MultimodalContent）**：MCP 协议层面的"文本块 + 图片块"混合列表，是本 feature 向 MCP 客户端返回的最终形态。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在 MCP 客户端查询一个答案含图的问题时，**用户 100% 能直接看到相关图片**（不需要再去原始文档翻找）。（当前为 0%）
- **SC-002**: "查询返回图片"端到端集成测试通过率 = 100%，且纳入 CI/本地 `pytest` 默认运行集。
- **SC-003**: 现有查询相关测试（摄取、检索、rerank、response builder）在本 feature 上线后**零回归**。
- **SC-004**: 含图查询的端到端时延相比纯文本查询的增加**不超过 20%**（在 10 张图以内、单图 ≤ 1MB 场景下）——避免为附图引入显著性能退化。
- **SC-005**: 图片文件缺失场景下，查询接口**零失败率**（始终返回文本部分，只是图片缺失）。
- **SC-006**: 可观测性指标：任意一次含图查询在 `logs/traces.jsonl` 中**均可检索到**对应的多模态组装阶段记录。

## Assumptions

- 摄取侧（PDF 图片提取、ImageCaptioner、ImageStorage、TextEnricher、Chunk metadata 含 images）已稳定运行，本 feature 仅消费其产物，不修改。
- MCP 协议支持在同一响应中混合返回文本块与图片块（Claude Desktop、Copilot 已验证支持）。
- 主要使用场景为本地 / 内网部署，响应体大小主要受 MCP 协议客户端承受能力限制，不考虑公网带宽瓶颈。
- 单次查询命中的图片数量在 10 张以内足够覆盖 95% 以上的业务问题。
- 图片默认不压缩、不裁剪返回。若后续出现体积问题，再开独立 feature 处理。
- LLM 总结模式下，附图策略采用"与命中 chunk 对齐"而非"LLM 自引用"，原因是后者要求 LLM 可靠地输出结构化引用，在现有 prompt 下不稳定。
- 本 feature 不涉及 MarkdownLoader 对 `![](...)` 的解析、caption 的 SHA256 去重缓存、Dashboard 查询页的图片展示——这些缺口已识别，留作后续独立 feature。
