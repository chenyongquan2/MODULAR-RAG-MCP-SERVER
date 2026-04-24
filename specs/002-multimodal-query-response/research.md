# Research: 多模态查询响应链路闭合

> Phase 0 输出。本 feature 在 `/speckit-clarify` 阶段已消解全部 NEEDS CLARIFICATION，本研究文档聚焦于"实现层技术决策的 Decision / Rationale / Alternatives"，为后续 tasks/implement 提供清晰依据。

---

## D-1：注入点选择（QueryKnowledgeHubTool vs ResponseBuilder）

**Decision**：在 `QueryKnowledgeHubTool` 层注入 `MultimodalAssembler`（以及其依赖的 `BaseImageStorage`），而非在 `ResponseBuilder` 层。

**Rationale**：
- `ResponseBuilder.build()` 的职责是**纯文本 RAG**（构建 prompt → 调 LLM → 生成 `StructuredContent(markdown, citations)`），其输出的 `StructuredContent` 不含 MCP 协议相关类型。让它返回 `ImageContent` 会跨层职责（business logic ↔ protocol）。
- 相反，`QueryKnowledgeHubTool` 本身就是 MCP 协议适配层（工具定义、输入解析、输出 `list[TextContent]`），引入 `ImageContent` 是自然延伸。
- `MultimodalAssembler` 已经实现了"组装 MCP 协议 content"的职责，放在工具层注入是一一对应。

**Alternatives considered**：
- **在 `ResponseBuilder` 注入**：被拒。跨层职责、破坏 `StructuredContent` 的纯数据性、纯检索模式（不走 ResponseBuilder）无法复用。
- **在 `HybridSearch` 注入**：被拒。HybridSearch 只管召回，不管返回形态；且 rerank 前塞图片会浪费。
- **在 MCP handler（server.py 的 `handle_call_tool`）里兜底转换**：被拒。handler 是协议分发层，注入业务依赖会让 server.py 膨胀，且每个 tool 都要重复适配。

---

## D-2：图片数量上限的实现位置

**Decision**：上限在 `MultimodalAssembler.assemble()` 内部实现（新增 `max_images: Optional[int] = None` 参数）；`QueryKnowledgeHubTool` 从 `settings.query.max_images_per_response` 读取后传入。

**Rationale**：
- `MultimodalAssembler.assemble()` 已经负责"从 results 提取 image_refs → 去重 → 按 text_offset 排序"的整条流水线。上限是这条流水线的自然一环（排序后截取前 N）。
- 放在 QueryKnowledgeHubTool 层实现会导致"组装 → 截取"两步发生在不同对象，截取逻辑需要解析 assemble 的输出结构，耦合度反而上升。
- 默认 `max_images=None` 时保持原行为（不限制），向后兼容既有调用方（如 dashboard 若未来复用 assembler）。

**Alternatives considered**：
- **硬编码在 QueryKnowledgeHubTool**：违反 clarify Q1 的选项 B（配置化）。
- **截取逻辑放在 `_extract_image_refs`**：该函数职责是"提取 + 去重 + 排序"，截取语义不同，放此处会让单元测试难以复用。

---

## D-3：LLM 总结模式下 markdown 的来源

**Decision**：`use_llm=true` 时传给 `assembler.assemble(markdown=..., ...)` 的 `markdown` 是 `ResponseBuilder.build().markdown + citations_text`（即现有代码在返回前拼好的字符串）。该字符串通常**不含** `[IMAGE: {id}]` 占位符，此时 `assembler._sort_by_text_offset` 将 fallback 为按 `image_refs` 提取顺序排序（即按命中 chunk 的 rerank 顺序）。

**Rationale**：
- LLM 输出不稳定地包含占位符（现有 prompt 未约束 LLM 保留 `[IMAGE: id]`），强求会引入新的 prompt 工程；clarify Q2 已明确"不依赖 LLM 引用"。
- `_sort_by_text_offset` 的 fallback 是"若 markdown 中找不到占位符，保留原有顺序"——这个顺序是 `_extract_image_refs` 按 `text_offset` 排序过的，即按 chunk 内图片原序。对用户而言顺序稳定、可预测。
- 需要确认：既有 `_sort_by_text_offset` 对"占位符不存在"是否真的保留传入顺序（非乱序）。若不是，则在 Phase 1 contracts 中补充"无占位符时保持 extract 顺序"约束，并在测试中验证。

**Alternatives considered**：
- **修改 LLM prompt 强制输出 `[IMAGE: id]` 占位符**：被拒，理由同 clarify Q2 选项 A 的 rationale。
- **对纯检索模式传入 JSON 字符串作为 markdown**：被拒，JSON 字符串里不会有占位符，和 LLM 模式等价，徒增复杂度；直接用纯检索模式现有的 formatted 文本即可。

---

## D-4：新增 trace stage 的命名与字段

**Decision**：stage 名 `assemble_multimodal`，字段：
- `image_count_requested`: 从 results 提取到的去重后图片总数（未应用上限前）
- `image_count_returned`: 实际返回的图片数（应用上限 + 缺图降级后）
- `image_count_failed`: 读取失败的图片数
- `duration_ms`: 组装耗时
- `max_images`: 本次生效的上限值（便于调试配置）

**Rationale**：
- 与现有 query trace 的 stage 命名风格一致（`dense` / `sparse` / `fusion` / `rerank` 都是单词动词/名词短语）。`assemble_multimodal` 清晰表达"多模态组装"语义。
- 字段都是量化数字，便于 Streamlit dashboard 未来接入（符合 CLAUDE.md 的"Dashboard 动态渲染"原则）。
- `image_count_requested - image_count_returned = dropped`（上限 + 失败），在调试时一眼看出发生了什么。

**Alternatives considered**：
- **stage 名 `multimodal` / `image_assembly`**：前者太泛、后者冗长。
- **只记录 `duration_ms`**：信息量不足，无法回答"为什么这次没返回图"。

---

## D-5：`QuerySettings` dataclass 的字段范围

**Decision**：本 feature 只新增一个字段：

```python
@dataclass
class QuerySettings:
    """查询响应相关配置。"""
    max_images_per_response: int = 10
```

**Rationale**：
- YAGNI：spec 只要求一个配置项（FR-004）。`top_k`、`filters` 等已经是 `query_knowledge_hub` 工具的运行时参数，不是全局配置，不放 `QuerySettings`。
- 预留：未来若需要"图片尺寸阈值""压缩开关"等（见 Assumptions 倒数第 3 条"后续独立 feature"），再向同一个 dataclass 追加字段即可，不需要重命名。
- `Settings` 装配处（`src/core/settings.py`）加一行 `query: QuerySettings = field(default_factory=QuerySettings)`，对其他 dataclass 零影响。

**Alternatives considered**：
- **复用 `RetrievalSettings`**：被拒。retrieval 语义是"检索层"（dense/sparse/fusion），而本配置作用在"响应组装层"，混入会让语义混乱。
- **放在 `MCPServerSettings`**：被拒。MCP 是协议层，这是业务行为，不匹配。
- **放在 `ObservabilitySettings`**：被拒，完全无关。

---

## 验证过的既有实现事实（供 tasks 参考）

1. `MultimodalAssembler.assemble(markdown, results, trace=None)` 已存在，返回 `List[TextContent | ImageContent | dict]`；dict 的结构是 `{"images": [{"id", "mimeType"}, ...]}`（现有实现附加的引用元数据）。
2. `MultimodalAssembler.__init__(image_storage=None)`：None 时默认 `SQLiteImageStorage()`（即默认路径 `data/db/image_index.db` 和 `data/images/`）。
3. `SQLiteImageStorage(db_path="data/db/image_index.db", images_root="data/images")`：默认路径已就绪，摄取侧写入、查询侧读取路径一致，**无需在 settings.yaml 新增图片存储路径配置**。
4. `QueryKnowledgeHubTool.__init__(hybrid_search, response_builder)`：两个参数，均用 `if X is None: raise ValueError` 做 Fail-Fast 校验；本 feature 需把校验扩展到 `image_storage` 或 `multimodal_assembler`。
5. MCP SDK 的 `list[TextContent | ImageContent]` 是被 `handle_call_tool` 正确返回的（虽然 `server.py:113-115` 的 handler 标注了 `-> list[TextContent]`，这是旧 type hint，运行时 MCP SDK 接受 union，需要在实现时同步修正 hint）。

---

**Phase 0 结论**：无未解决项；所有决策均可直接进入 Phase 1 契约定义。
