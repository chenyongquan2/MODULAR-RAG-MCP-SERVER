# Data Model: 多模态查询响应链路闭合

> **本 feature 不引入新数据实体**——所有涉及的类型都在项目既有代码中已定义。本文档的目标是**明确复用契约**，并标注本 feature 对现有类型的新增约束（如有）。

---

## 既有类型清单（复用，不修改）

### E-1: `ImageReference`（`src/core/types.py`）

Chunk 元数据中"该 chunk 关联哪些图"的引用结构。

| 字段 | 类型 | 语义 | 本 feature 依赖 |
|-----|------|------|----------------|
| `id` | `str` | 全局唯一 image_id（格式 `img_{doc_hash}_{page}_{seq}`） | ✅ 用作 ImageStorage 查询键 |
| `path` | `str` 或 `None` | 图片文件路径（冗余，便于跳过 storage 直读） | ✅ 可选读取 |
| `text_offset` | `int` | `[IMAGE: id]` 占位符在 chunk.text 的字符偏移 | ✅ 用于排序 |
| `text_length` | `int` | 占位符长度 | ⚠️ 本 feature 未用 |

**本 feature 约束**：
- 读取端假定 `id` 非空；若某 image_ref 的 `id` 缺失，**MUST** 跳过并记录 warning（当前 `_extract_image_refs` 已实现）。
- 读取端假定 `text_offset` 为非负整数；若缺失，fallback 为 0。

### E-2: `RetrievalResult`（`src/core/types.py:232-278`）

检索返回的结果对象，本 feature 作为**只读消费者**：

| 字段 | 本 feature 依赖 |
|-----|----------------|
| `chunk_id` | ⚠️ trace 记录用（可选） |
| `text` | ⚠️ ResponseBuilder 用，本 feature 不动 |
| `score` | ❌ |
| `metadata` | ✅ **关键**：从 `metadata["images"]: List[ImageReference]` 提取 image refs |

### E-3: `Chunk` / `ChunkRecord`（`src/core/types.py`）

仅作为摄取侧产物的消费端参考。查询侧通过 `RetrievalResult.metadata["images"]` 间接读取，**本 feature 不触及 Chunk 本身**。

### E-4: `TextContent` / `ImageContent`（`mcp.types`）

MCP SDK 定义的协议层 content 类型。

| 类型 | 关键字段 | 本 feature 用法 |
|------|---------|----------------|
| `TextContent` | `type: "text"`, `text: str` | ✅ 承载既有文本响应（纯检索格式化文本、LLM 总结 markdown + citations） |
| `ImageContent` | `type: "image"`, `data: str (base64)`, `mimeType: str` | ✅ 承载图片二进制（PNG/JPEG，由 `mimetypes.guess_type` 检测） |

**本 feature 约束**：
- `ImageContent.data` **MUST** 是合法 base64 字符串（UTF-8 可解码）。
- `ImageContent.mimeType` **MUST** 以 `image/` 开头（`MultimodalAssembler._load_image` 已实现此校验）。
- 非法图片类型（非 image/*）**MUST** 被跳过并记录 warning，不引入新的 mimeType 列表维护成本。

### E-5: `StructuredContent`（`src/core/response/citation_generator.py`）

`ResponseBuilder.build()` 的返回类型。

| 字段 | 本 feature 依赖 |
|-----|----------------|
| `markdown` | ✅ 传给 `assembler.assemble(markdown=...)` 作为"组装基准文本" |
| `citations` | ✅ 在 `_build_multimodal_response` 里拼接到 markdown 末尾（保持现有 `citations_text` 格式） |

---

## 新增类型

### E-New-1: `QuerySettings`（`src/core/settings.py`）

```python
@dataclass
class QuerySettings:
    """查询响应相关配置。"""
    max_images_per_response: int = 10
```

**验证规则**（在 `load_settings` 中强制）：
- `max_images_per_response` **MUST** 为正整数（> 0）。0 或负数抛 `SettingsError`。
- 上限值本身无硬性 max（允许用户设为 1000），但 log 一条 info 级别提示"上限超过 100 可能影响响应体积"。

**挂载点**：`Settings` dataclass 新增字段 `query: QuerySettings = field(default_factory=QuerySettings)`，位置建议**插在 `retrieval` 之后、`rerank` 之前**（符合"先检索、再响应"的语义流）。

### E-New-2: `MultimodalTraceStage`（非类型，是 trace 结构字段约定）

不是 Python 类，而是 trace 记录的 JSON 字段约定（写入 `logs/traces.jsonl`）：

```json
{
  "stage": "assemble_multimodal",
  "image_count_requested": 5,
  "image_count_returned": 3,
  "image_count_failed": 1,
  "max_images": 10,
  "duration_ms": 12.4
}
```

字段合约在 [contracts/query_knowledge_hub_tool.md](./contracts/query_knowledge_hub_tool.md) 详述。

---

## 数据流（本 feature 视角）

```text
摄取侧（已完成，本 feature 不动）
  PDF/MD → Chunk.metadata["images"]: List[ImageReference]
           + data/images/{collection}/{image_id}.png（文件）
           + data/db/image_index.db（索引）

                        ↓
                    向量库（ChromaDB）
                        ↓
查询侧
  query → HybridSearch → List[RetrievalResult]
                          └─ result.metadata["images"] 完整透传

                        ↓  本 feature 的新流水线
  QueryKnowledgeHubTool.execute()
    ├─ (use_llm=true)  ResponseBuilder.build() → StructuredContent(markdown, citations)
    │                    └─ markdown + citations_text → assemble(markdown, results)
    │
    └─ (use_llm=false) _format_search_results + _serialize_results → formatted_with_json
                         └─ formatted_with_json → assemble(markdown, results)

  assemble(markdown, results, max_images=settings.query.max_images_per_response):
    ├─ _extract_image_refs(results) → 去重 + text_offset 排序
    ├─ _load_image(ref) × N → ImageContent（缺图/非法则跳过并 warning）
    ├─ _sort_by_text_offset → 按 markdown 占位符顺序（无占位符则保持 extract 顺序）
    ├─ truncate to max_images
    └─ return [TextContent, *ImageContent..., {"images": [...]}]

                        ↓
  MCP SDK → 客户端（Claude Desktop / Copilot）
```

---

## 状态与生命周期

本 feature 是**纯无状态的请求/响应链路**——无持久化、无会话、无缓存。

- 图片读取是**读-only** 操作，不修改 ImageStorage。
- `QuerySettings` 在 `load_settings()` 时加载一次，进程生命周期内不变。
- `MultimodalAssembler` 和 `SQLiteImageStorage` 实例在 MCP server 启动时创建一次，全 tool 调用共享（线程安全由 SQLite 的 `_get_connection` 保证）。

---

**Phase 1 data-model 结论**：仅新增 1 个配置 dataclass + 1 个 trace 字段约定，其余全为既有类型的契约化复用。
