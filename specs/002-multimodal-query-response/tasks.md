# Tasks: 多模态查询响应链路闭合（Multimodal Query Response）

**Input**: Design documents from `/specs/002-multimodal-query-response/`
**Prerequisites**: [plan.md](./plan.md) ✅, [spec.md](./spec.md) ✅, [research.md](./research.md) ✅, [data-model.md](./data-model.md) ✅, [contracts/query_knowledge_hub_tool.md](./contracts/query_knowledge_hub_tool.md) ✅

**Tests**: 本 feature spec 的 FR-009 与 SC-002 明确要求"端到端自动化测试"，因此**包含测试任务**（非 TDD 严格顺序，测试与实现在同 story 内紧密绑定）。

**Organization**: 按 spec 三个 User Story（P1/P2/P3）组织。US1 是 MVP：单独完成即可让"纯检索模式"返图。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 归属哪个 User Story（US1/US2/US3）
- 每条任务含绝对或项目相对文件路径

## Path Conventions

**Single project**（见 plan.md Structure Decision）：`src/` + `tests/` 位于仓库根。

---

## Phase 1: Setup（Shared Infrastructure）

**Purpose**：建立 implementer 上下文。本 feature 为既有项目扩展，无需新建 scaffolding。

- [X] T001 阅读 [spec.md](./spec.md)、[plan.md](./plan.md)、[research.md](./research.md)、[data-model.md](./data-model.md)、[contracts/query_knowledge_hub_tool.md](./contracts/query_knowledge_hub_tool.md)、[quickstart.md](./quickstart.md) 建立上下文；确认当前分支为 `002-multimodal-query-response`、`.specify/feature.json` 指向本 feature dir。

---

## Phase 2: Foundational（Blocking Prerequisites）

**Purpose**：所有 User Story 都依赖的配置与组件扩展。

**⚠️ CRITICAL**：完成本 phase 之前不得开始 US1/US2/US3。

- [X] T002 [P] 在 [src/core/settings.py](src/core/settings.py) 新增 `QuerySettings` dataclass，字段 `max_images_per_response: int = 10`（含类级 docstring 说明语义）。
- [X] T003 [P] 在 [config/settings.yaml](config/settings.yaml) 新增 `query:` 段，位置**插在 `retrieval:` 之后、`rerank:` 之前**；内容为 `max_images_per_response: 10`（含中文注释说明）。
- [X] T004 在 [src/core/settings.py](src/core/settings.py) 的 `Settings` dataclass 挂载 `query: QuerySettings = field(default_factory=QuerySettings)`（位置紧跟 `retrieval`）；并在 `load_settings()`/启动校验处追加检查 `max_images_per_response > 0`，违反时抛 `SettingsError`。依赖 T002、T003。
- [X] T005 [P] 在 [src/core/response/multimodal_assembler.py](src/core/response/multimodal_assembler.py) 的 `assemble()` 新增 `max_images: Optional[int] = None` 参数：`None` 保持现行为；正整数则在排序后截取前 N；`0` 返回纯文本（无 ImageContent）；负数抛 `ValueError`。保持 `{"images": [...]}` 元数据 dict 反映截取后的结果。
- [X] T006 新建 [tests/unit/test_multimodal_assembler_limit.py](tests/unit/test_multimodal_assembler_limit.py) 覆盖边界：`max_images=None` 不限制、`max_images=3` 从 5 张图截前 3、`max_images=0` 返回只含 TextContent、`max_images=-1` 抛 ValueError；断言 `{"images": [...]}` 元数据长度与返回 ImageContent 数一致。依赖 T005。
- [X] T007 运行 `pytest tests/unit -v` 确保 QuerySettings 装配、load_settings 校验、assemble max_images 扩展均通过（含既有测试无回归）。

**Checkpoint**：Foundation 就绪——US1/US2/US3 可开始。

---

## Phase 3: User Story 1 - 纯检索模式下 MCP 客户端看到图片（Priority: P1）🎯 MVP

**Goal**：用户通过 MCP 客户端以 `use_llm=false` 查询时，响应同时含文本与命中 chunk 关联图片的二进制内容，且图片可直接在客户端渲染。

**Independent Test**：摄取一份含图 PDF → MCP 调用 `query_knowledge_hub({query, use_llm: false})` → 响应 `list` 中包含 ≥1 个 `TextContent` + ≥1 个 `ImageContent`（`mimeType` 以 `image/` 开头、`data` base64 合法）。

### Implementation for User Story 1

- [X] T008 [US1] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 修改 `QueryKnowledgeHubTool.__init__`，新增 `multimodal_assembler: MultimodalAssembler` 与 `max_images_per_response: int` 参数；四参数均 Fail-Fast 校验（`None` 抛 `ValueError`，`max_images_per_response <= 0` 抛 `ValueError`）；将依赖存到 `self._multimodal_assembler` 与 `self._max_images_per_response`；新增 `from mcp.types import ImageContent` 导入。
- [X] T009 [US1] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 将 `execute()` 的返回类型签名从 `list[TextContent]` 改为 `list[TextContent | ImageContent]`；同步更新该方法的 docstring 示例。
- [X] T010 [US1] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 重构 `execute()` 的 `use_llm=false` 分支：在 `_format_search_results` + `_serialize_results` 拼好 `formatted_with_json` 之后，将它作为 `markdown` 传入 `self._multimodal_assembler.assemble(markdown=formatted_with_json, results=results, trace=<trace>, max_images=self._max_images_per_response)`，return 其结果。保留"无结果友好提示"分支不变。
- [X] T011 [US1] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 的 `execute()` 总 `try/except` 块补充 assembler 失败降级：若 `assemble()` 抛异常，`logger.error` 记录并 fallback 返回 `[TextContent(text=<原拼好的 markdown 字符串>)]`（FR-006）；保持"hybrid_search 抛错""response_builder 抛错"等既有降级路径不变。
- [X] T012 [US1] 在 [src/mcp_server/server.py](src/mcp_server/server.py) 的 `MCPServer._do_initialize_runtime()`（约 L62-76）新增 `from src.ingestion.storage.image_storage import SQLiteImageStorage` 与 `from src.core.response.multimodal_assembler import MultimodalAssembler`；实例化 `image_storage = SQLiteImageStorage()` 与 `assembler = MultimodalAssembler(image_storage=image_storage)`；将 `QueryKnowledgeHubTool(hybrid_search, response_builder)` 改为 `QueryKnowledgeHubTool(hybrid_search, response_builder, assembler, settings.query.max_images_per_response)`。`handle_call_tool` 的返回 type hint 从 `list[TextContent]` 改为 `list[TextContent | ImageContent]`。
- [X] T013 [P] [US1] 更新 [tests/integration/test_query_knowledge_hub.py](tests/integration/test_query_knowledge_hub.py)（实际位于 integration/ 而非 unit/，tasks 原假设有误）：所有既有测试的构造器调用增补 mock assembler + `max_images_per_response=10`；新增用例验证「None multimodal_assembler 抛 ValueError」「max_images_per_response<=0 抛 ValueError」「`use_llm=false` 路径调用 `assembler.assemble` 一次且 max_images 来自构造时注入值」「assembler 抛错时 fallback 为纯 TextContent」「`use_llm=true` 暂不调 assembler（留给 US2）」。
- [X] T014 [US1] 新建 [tests/integration/test_multimodal_query.py](tests/integration/test_multimodal_query.py)（标 `@pytest.mark.integration`），覆盖 P1 路径：fixture 用真实 `SQLiteImageStorage` 指向临时目录 + 真 PNG 文件，mock HybridSearch 返回含 2 张图的 chunk → 调用 `QueryKnowledgeHubTool.execute({use_llm: False})` → 断言返回列表含 2 张 `ImageContent`、`mimeType` 以 `image/` 开头、`data` base64 可解码；额外 3 个用例：图片文件缺失降级、max_images=1 截取、无命中返回友好提示。
- [~] T015 [US1] pytest 验证：`pytest tests/integration/test_query_knowledge_hub.py tests/integration/test_multimodal_query.py tests/unit/test_multimodal_assembler*.py -v` **通过 39/39** ✅。手工 e2e（[quickstart.md](./quickstart.md) Step 1~4.2 在 Claude Desktop 观察图片渲染）**待用户执行**。

**Checkpoint**：US1 完成——纯检索模式已可返图，feature 达到 MVP，可独立交付。

---

## Phase 4: User Story 2 - LLM 总结模式下图文结合的答案（Priority: P2）

**Goal**：`use_llm=true` 时，LLM 生成的 Markdown 文本之后同样附上命中 chunk 的图片；附图策略与 US1 完全一致（不依赖 LLM 引用行为）。

**Independent Test**：摄取同样含图 PDF → 调用 `query_knowledge_hub({query, use_llm: true})` → 断言返回内容同时含 LLM 生成的 Markdown 文本（其中出现图片描述关键词）+ 相关图片 `ImageContent`；两种模式返回的 image_id 集合一致。

### Implementation for User Story 2

- [X] T016 [US2] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 重构 `execute()` 的 `use_llm=true` 分支：在 `response_builder.build()` 得到 `structured_content` 且拼出 `citations_text` 之后，把 `structured_content.markdown + citations_text` 作为 `markdown` 传入 `self._multimodal_assembler.assemble(markdown=..., results=results, trace=<trace>, max_images=self._max_images_per_response)`，return 其结果。保留既有 logger.info "Response built" 追踪；补充 assembler 失败降级。
- [X] T017 [P] [US2] 扩展 [tests/integration/test_query_knowledge_hub.py](tests/integration/test_query_knowledge_hub.py)：反转原 `test_use_llm_true_not_calling_assembler_yet` 为 `test_use_llm_true_calls_assembler_with_llm_markdown`；新增 `test_both_modes_extract_same_image_refs` 验证两种模式 results 一致；新增 `test_use_llm_true_assembler_failure_falls_back_to_text` 验证降级；更新 `test_execute_with_llm_mode` 的断言兼容新列表结构。
- [X] T018 [US2] 扩展 [tests/integration/test_multimodal_query.py](tests/integration/test_multimodal_query.py)：新增 `mock_response_builder_with_llm_output` fixture + `test_use_llm_true_returns_llm_markdown_and_images`（LLM 模式含 2 张图）+ `test_both_modes_return_same_image_set`（两种模式 image_id 集合一致）。
- [~] T019 [US2] pytest 验证 **通过 43/43** ✅。手工 e2e（[quickstart.md](./quickstart.md) Step 4.3 Claude Desktop `use_llm=true` 问题）**待用户执行**。

**Checkpoint**：US1 与 US2 均独立可跑。

---

## Phase 5: User Story 3 - 可观测性与回归保障（Priority: P3）

**Goal**：新链路具备 trace 可观测性；既有查询相关测试零回归；quickstart 验收全通。

**Independent Test**：任意含图查询在 `logs/traces.jsonl` 中可检索到 `stage=assemble_multimodal` 记录，含 5 个字段（requested/returned/failed/max_images/duration_ms）；`pytest tests/` 全部通过。

### Implementation for User Story 3

- [X] T020 [US3] 在 [src/core/response/multimodal_assembler.py](src/core/response/multimodal_assembler.py) 的 `assemble()` 内新增 `_record_trace_stage` 辅助方法：复用既有 `TraceContext.record_stage()` API，写入 `stage=assemble_multimodal` + 5 个约定字段（requested/returned/failed/max_images/duration_ms）；`trace=None` 或非 TraceContext 对象时静默跳过（Fail-Safe）。
- [X] T021 [US3] 在 [src/mcp_server/tools/query_knowledge_hub.py](src/mcp_server/tools/query_knowledge_hub.py) 的 `execute()` 顶部创建 `TraceContext(trace_type="query")` 并附加 query/top_k/use_llm metadata；把 trace 传给 `assembler.assemble(trace=trace)`（两个分支）；`try/finally` 末尾 `trace.finish()` + `TraceCollector.collect()`。构造器新增可选 `trace_collector: Optional[TraceCollector]` 参数，None 时不 flush（测试场景）；server.py 装配时按 `settings.observability.enabled` 传入 `TraceCollector()`。
- [X] T022 [P] [US3] 新建 [tests/unit/test_multimodal_assembler_trace.py](tests/unit/test_multimodal_assembler_trace.py) 5 个用例：5 字段齐全 + 值正确、无图时仍写 stage、失败计数正确（failed=1）、trace=None 静默、非 TraceContext 对象优雅降级。
- [X] T023 [US3] 回归：feature 相关 **48/48 通过**；查询管线（MCP server、HybridSearch、ResponseBuilder、Reranker、Citation、QueryProcessor、ChromaStore）**154/154 通过**，零回归。既有 9 fail + 12 error 全部是**预先存在**的环境问题（docling 未安装、Azure Vision LLM 模块名不匹配、Ollama embedding 配置），与本 feature 无关。
- [~] T024 [US3] 执行 [quickstart.md](./quickstart.md) Step 5（边界：图缺失、上限生效、无图 chunk）的**代码部分已由集成测试覆盖**（`test_image_file_missing_degrades_gracefully` / `test_max_images_limit_truncates_response` / `test_no_hits_returns_friendly_text_without_error` / trace 5 字段测试）；手工 Dashboard / Step 5.2 改 config + 重启 server / SC-004 时延对比 **待用户执行**。

**Checkpoint**：spec 的全部 6 条 Success Criteria 已验证。

---

## Phase 6: Polish & Cross-Cutting

**Purpose**：收尾与跨 story 清理。

- [X] T025 [P] 跑 `code-review-expert`，发现 0 P0 / 2 P1 / 2 P2 / 2 P3；按"最小 scope"原则**本 feature 内修 2 个 P1**（`trace` 下游传递到 hybrid_search/response_builder、`except ValueError` 追加 `error_type` metadata）；2 个 P2（query trace PII 脱敏 / SQLiteImageStorage 路径配置化）spawn 为独立任务（非本 feature 引入，违反 scope 原则不应在此处理）；2 个 P3 就地忽略。修复后 feature+查询管线 71/71 绿。
- [X] T026 [P] 更新 [CLAUDE.md](CLAUDE.md) L248 "Image Handling" 段落，增补"自 feature-002 起 query_knowledge_hub 通过 MultimodalAssembler 返回文本+ImageContent、两种 use_llm 模式策略一致、数量由 query.max_images_per_response 配置"。"Data Flow - Query Pipeline"（L111+）无需改（既有描述粒度到 Reranker，不展开响应层）。
- [X] T027 验证 [DEV_SPEC.md](DEV_SPEC.md) §3.2.2 (L408-435) 的"多模态内容返回"设计（TextContent + Base64 ImageContent + Client 适配策略）**已对齐本 feature 实现**；§3.5 (L864+) 是摄取侧"图转文"策略，与查询侧闭环无冲突。**无需追加说明**。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**：无依赖，可立即开始
- **Phase 2 Foundational**：依赖 Phase 1；**阻塞** US1/US2/US3
- **Phase 3 US1**：依赖 Phase 2 完成；与 US2/US3 理论上可并行，但由于均改同一文件 `query_knowledge_hub.py` / `multimodal_assembler.py`，实际**串行执行**（US1 → US2 → US3）
- **Phase 6 Polish**：依赖所有 User Story 完成

### User Story Dependencies

- **US1 (P1)**：Foundation 之后即可开始；是 MVP
- **US2 (P2)**：建议 US1 之后（共用 execute() 主体重构）
- **US3 (P3)**：建议 US1/US2 之后（trace 需要覆盖两种模式）

### Within Each User Story

- Implementation → Unit tests（同 story 内紧邻）→ Integration tests → 手工 e2e（quickstart）

### Parallel Opportunities

| 并行组 | Tasks | 说明 |
|-------|-------|-----|
| Phase 2 foundational | T002 [P] / T003 [P] / T005 [P] | 三个文件完全独立：settings.py（新 dataclass 部分）、settings.yaml、multimodal_assembler.py |
| US1 测试 | T013 [P] | 测试文件独立于实现修改 |
| US2 测试 | T017 [P] | 同上 |
| US3 测试 | T022 [P] | 独立测试文件 |
| Polish | T025 [P] / T026 [P] | code-review 与文档并行 |

注：T004 改 settings.py（挂载 + 校验）与 T002 同文件但**顺序依赖**，不能并行。

---

## Parallel Example: Phase 2 Foundational

```bash
# 三项可同时推进（不同文件，无依赖）：
Task: "T002 新增 QuerySettings dataclass 到 src/core/settings.py"
Task: "T003 config/settings.yaml 新增 query 段"
Task: "T005 MultimodalAssembler.assemble() 新增 max_images 参数"

# T002/T003 完成后：
Task: "T004 挂载 query 字段到 Settings + load_settings 校验"

# T005 完成后：
Task: "T006 新建 test_multimodal_assembler_limit.py"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1 Setup（T001，~10 min）
2. 完成 Phase 2 Foundational（T002~T007，~2 h）
3. 完成 Phase 3 US1（T008~T015，~3 h）
4. **STOP & VALIDATE**：跑 quickstart Step 1~4.2，确认 MCP 客户端能在 `use_llm=false` 下看到图
5. 可选择此时合入主干（MVP 发布：纯检索模式返图）

### Incremental Delivery

1. MVP 发布（US1 完成）
2. + US2（T016~T019）→ LLM 总结模式也返图
3. + US3（T020~T024）→ 可观测性 + 全回归
4. + Polish（T025~T027）→ 代码审查 + 文档收口

### 单人开发估时

- Phase 1：10 min
- Phase 2：2 h（配置 + assembler 扩展 + 单测）
- US1：3 h（核心改动 + 单测 + 集成 + 手工 e2e）
- US2：1.5 h（增量改动）
- US3：2 h（trace + 回归 + quickstart 验收）
- Polish：1 h
- **合计：约 9.5 h / 1~2 工作日**

---

## Notes

- [P] = 不同文件、无未完成依赖
- [Story] 标签用于追溯到 spec 的 User Story
- 每个 User Story 完成后建议 git commit 一次（粒度 = 完整可跑的 story 增量）
- T021 中 TraceContext 的处理方式若发现项目基础设施尚未支持，可**保守降级为 logger.info JSON 行**，并在 research.md 追加 D-4 增补段记录此折中
- 避免：跨 story 的隐式耦合（除 execute() 同文件顺序之外）、测试与实现放在不同 commit
