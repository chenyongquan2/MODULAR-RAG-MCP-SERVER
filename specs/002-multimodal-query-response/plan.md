# Implementation Plan: 多模态查询响应链路闭合

**Branch**: `002-multimodal-query-response` | **Date**: 2026-04-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-multimodal-query-response/spec.md`

## Summary

**核心需求**（来自 spec）：为 MCP 工具 `query_knowledge_hub` 闭合"查询 → 返回图片"链路。摄取侧已完整（Docling 提图、Vision Captioning、SQLiteImageStorage、caption 融合向量化），检索链路已透传 image 元数据，但 MCP 工具层**从未调用** `MultimodalAssembler`，客户端只能拿到文字。

**技术路径**：
- 在 `MCPServer._do_initialize_runtime()` 新增 `SQLiteImageStorage` + `MultimodalAssembler` 实例化，注入到 `QueryKnowledgeHubTool`。
- `QueryKnowledgeHubTool.execute()` 返回类型从 `list[TextContent]` 扩展为 `list[TextContent | ImageContent]`。两种模式（`use_llm` 布尔）统一在末尾调用 `assembler.assemble(...)` 附加图片。
- `MultimodalAssembler.assemble()` 已有的"去重 + 按 text_offset 排序 + 缺图降级"全部复用；**本 feature 唯一需要改**的是新增**数量上限**参数（对应 spec FR-004，配置项 `query.max_images_per_response`，默认 10）。
- `Settings` 新增 `QuerySettings` dataclass，`config/settings.yaml` 新增 `query:` 段。
- 可观测性：查询 trace 中新增 `assemble_multimodal` stage，记录 `image_count_requested / image_count_returned / duration_ms`。
- 测试：新增 `tests/integration/test_multimodal_query.py` 覆盖端到端；扩展 `tests/unit/test_query_knowledge_hub.py` 覆盖装配与降级；新增 `tests/unit/test_multimodal_assembler_limit.py` 覆盖上限边界。

## Technical Context

**Language/Version**: Python 3.11+（pyproject.toml 已锁定）
**Primary Dependencies**: `mcp` (MCP SDK, `TextContent`/`ImageContent`)、既有 `MultimodalAssembler`、`SQLiteImageStorage`、`HybridSearch`、`ResponseBuilder`、`Settings`
**Storage**: 既有 `data/db/image_index.db`（SQLite 索引）+ `data/images/{collection}/{image_id}.png`（文件）——**不新增**
**Testing**: pytest（现有约定：`tests/unit`、`tests/integration`、`tests/e2e` 三层，按 marker 运行）
**Target Platform**: 本地 / 内网，Windows + Linux 均支持（项目当前在 Windows 11 开发）
**Project Type**: MCP stdio server（单进程 Python，不涉及前后端拆分）
**Performance Goals**: SC-004——含图查询 e2e 延迟增加 ≤ 20%（10 张图以内、单图 ≤ 1MB）
**Constraints**:
- 响应体不压缩/不跳过大图（clarify Q3 已定，选项 A）
- 图片数量上限可配置（clarify Q1 已定，选项 B）
- `use_llm=true/false` 两种模式附图策略一致（clarify Q2 已定，选项 A）
**Scale/Scope**: 单次响应最多 10 张图（默认上限）；摄取侧文档规模已由现有测试覆盖，本 feature 不扩展

**无 NEEDS CLARIFICATION**（spec 的 `## Clarifications` 段已全部消解）。

## Constitution Check

本项目 `.specify/memory/constitution.md` 目前为空模板（MEMORY `project_sdd_status.md` 明确：L2 constitution 留给第一个 feature 跑完再写）。作为替代，本次 gate 引用 [CLAUDE.md 的 Key Design Principles](../../CLAUDE.md) 进行评估：

| Principle | 适用性 | 本 feature 符合性 |
|-----------|--------|-------------------|
| **Provider-Agnostic** | 适用 | ✅ `QueryKnowledgeHubTool` 通过 `BaseImageStorage` 抽象接收实例，不硬编码 SQLite |
| **Configuration-Driven** | 适用 | ✅ 图片上限 `query.max_images_per_response` 通过 `settings.yaml` 驱动 |
| **Fail-Fast Validation** | 适用 | ✅ 构造器在 image_storage 为 None 时抛 ValueError；settings 加载期校验上限 > 0 |
| **Explicit Tracing** | 适用 | ✅ 新增 `assemble_multimodal` stage，复用既有 TraceContext 约定 |
| **Structured Logging** | 适用 | ✅ 复用 `observability.logger.get_logger()`，不引入 print |
| **Type Safety** | 适用 | ✅ `execute()` 返回 `list[TextContent \| ImageContent]` 由 MCP SDK 原生类型 |

**Gate 结论**：全部通过，无需 Complexity Tracking 豁免。

## Project Structure

### Documentation (this feature)

```text
specs/002-multimodal-query-response/
├── plan.md              # 本文件
├── spec.md              # 需求规约（已完成 + 已 clarify）
├── research.md          # Phase 0：决策与 rationale
├── data-model.md        # Phase 1：既有类型复用说明（无新实体）
├── quickstart.md        # Phase 1：端到端验证脚本
├── contracts/
│   └── query_knowledge_hub_tool.md   # 工具 I/O 契约变更
├── checklists/
│   └── requirements.md  # spec 阶段 checklist（已完成）
└── tasks.md             # 由 /speckit-tasks 生成，本 plan 不创建
```

### Source Code（改动点清单）

本 feature 为 **Single project 结构**（项目 CLAUDE.md 明确 `src/` 根 + `tests/` 三层分层）。

```text
src/
├── core/
│   ├── settings.py                           # ✏️ 新增 QuerySettings dataclass，加入 Settings
│   └── response/
│       └── multimodal_assembler.py           # ✏️ assemble() 新增 max_images 参数（默认 None=不限制）
├── mcp_server/
│   ├── server.py                             # ✏️ _do_initialize_runtime: 实例化 ImageStorage + Assembler 并注入
│   └── tools/
│       └── query_knowledge_hub.py            # ✏️ 构造器 + execute() 扩展；新增 _build_multimodal_response()
└── ingestion/storage/image_storage.py        # ✅ 不动（复用）

config/
└── settings.yaml                             # ✏️ 新增 query: 段，含 max_images_per_response: 10

tests/
├── unit/
│   ├── test_query_knowledge_hub.py           # ✏️ 扩展：构造器参数、两种模式附图、ImageStorage 不可用降级
│   └── test_multimodal_assembler_limit.py    # 🆕 图片数量上限边界
└── integration/
    └── test_multimodal_query.py              # 🆕 端到端：摄取→查询→断言 ImageContent
```

**Structure Decision**: 选 Single project 布局，直接复用 `src/` 根分层。本 feature 不涉及 backend/frontend 拆分，也不涉及新子包。

## Complexity Tracking

> 无 Constitution 违反项，本段留空。

## Phase 0 / 1 Artifacts

- [research.md](./research.md) — 5 个关键决策的 Decision/Rationale/Alternatives
- [data-model.md](./data-model.md) — 既有类型复用清单（无新实体）
- [contracts/query_knowledge_hub_tool.md](./contracts/query_knowledge_hub_tool.md) — 工具 I/O 契约变更
- [quickstart.md](./quickstart.md) — 端到端验证 30 分钟脚本

## Post-Design Constitution Re-Check

重新评估 Phase 1 后设计是否引入新违反项：
- 新增 `QuerySettings` 符合既有 dataclass 模式（Configuration-Driven ✅）
- `MultimodalAssembler.assemble()` 新增可选参数向后兼容（不破坏既有调用 ✅）
- 新增 trace stage 字段复用既有 TraceContext 结构（Explicit Tracing ✅）

**结论**：通过，可进入 `/speckit-tasks` 生成任务清单。
