# Contract: `query_knowledge_hub` MCP 工具（v2，多模态）

> 本契约是 **v2**，相对 v1（纯文本返回）的**向后兼容扩展**。客户端若未渲染 `ImageContent`，仍能正确消费 `TextContent`。

---

## 1. 工具定义（MCP `Tool` schema）

### 1.1 输入参数（**不变**）

```json
{
  "name": "query_knowledge_hub",
  "description": "基于混合检索（Dense + Sparse + RRF + Rerank）查询知识库，并生成包含引用的响应。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query":    { "type": "string", "description": "用户查询" },
      "top_k":    { "type": "integer", "default": 10 },
      "use_llm":  { "type": "boolean", "default": false },
      "filters":  { "type": "object",  "description": "metadata 过滤" }
    },
    "required": ["query"]
  }
}
```

**本 feature 不修改输入 schema**。spec FR-004 决定「图片数量上限」通过 `settings.yaml` 而非 per-query 参数暴露（clarify Q1 选项 B）。

### 1.2 输出类型（**变更**）

| 版本 | Python type hint | MCP content types |
|------|------------------|-------------------|
| v1（现状） | `list[TextContent]` | 仅 `TextContent` |
| **v2（本 feature）** | `list[TextContent \| ImageContent]` | `TextContent` + 0~N 个 `ImageContent` |

**契约要点**：
- 列表首元素 **MUST** 是 `TextContent`（保持 v1 语义；客户端解析首元素文本内容不应 break）。
- `ImageContent` 元素（若有）**MUST** 在 `TextContent` 之后。
- `MultimodalAssembler.assemble()` 当前会在列表末尾追加一个 `dict` 形如 `{"images": [{"id", "mimeType"}, ...]}`——**契约保留此行为**（它是对 MCP SDK 非标准协议项的扩展，用于 trace / debug 可观测性，客户端遇到非 Content 类型应当忽略）。

---

## 2. `QueryKnowledgeHubTool` 构造器（**变更**）

### 2.1 现状（v1）

```python
def __init__(
    self,
    hybrid_search: HybridSearch,
    response_builder: ResponseBuilder,
) -> None:
```

### 2.2 新契约（v2）

```python
def __init__(
    self,
    hybrid_search: HybridSearch,
    response_builder: ResponseBuilder,
    multimodal_assembler: MultimodalAssembler,
    max_images_per_response: int,
) -> None:
```

**Fail-Fast 规则**（沿用既有模式）：
- 四个参数均 **MUST NOT** 为 `None`，违反时抛 `ValueError`。
- `max_images_per_response` **MUST** `> 0`，否则抛 `ValueError`。

**向后兼容策略**：
- 由于构造器签名变化，**所有既有测试** `tests/unit/test_query_knowledge_hub.py` 需同步更新（提供 mock assembler + 固定上限）。
- 不做 default 参数（违反 Fail-Fast，且 assembler 真实依赖 image_storage，不适合默认构造）。

---

## 3. `MultimodalAssembler.assemble()` 签名（**变更**）

### 3.1 现状

```python
def assemble(
    self,
    markdown: str,
    results: List[RetrievalResult],
    trace: Optional[Any] = None,
) -> List[TextContent | ImageContent | dict[str, Any]]:
```

### 3.2 新契约

```python
def assemble(
    self,
    markdown: str,
    results: List[RetrievalResult],
    trace: Optional[Any] = None,
    max_images: Optional[int] = None,
) -> List[TextContent | ImageContent | dict[str, Any]]:
```

**语义**：
- `max_images=None`（默认）→ 保持现有行为（不限制），**向后兼容**。
- `max_images=N`（正整数）→ 在"排序 + 去重 + 加载"全部完成**之后**截取前 N 张图片。
- `max_images=0` → 退化为"不返回任何 ImageContent"（等同图片全丢失），`TextContent` 仍返回。此为 edge case 兼容，不做 ValueError。
- `max_images<0` → 抛 `ValueError("max_images must be >= 0")`。

**截取顺序依据**：`_sort_by_text_offset` 返回顺序（即 markdown 中占位符出现顺序，无占位符时保持 `_extract_image_refs` 的 text_offset 升序）。这对应 spec FR-004 的"按命中 chunk 的 rerank 顺序"的精化——严格说是 chunk 内图片序，而非严格 rerank 序，但"chunk 已按 rerank 排序"成立，所以整体单调不变。

---

## 4. `QueryKnowledgeHubTool.execute()` 行为契约（**变更**）

### 4.1 无结果时（`results == []`）

**保持 v1 行为**：返回 `[TextContent("未找到相关内容……")]`。不调用 assembler。

### 4.2 有结果 + `use_llm=false`（纯检索模式）

```text
1. results = hybrid_search.search(query, top_k, filters)
2. formatted = _format_search_results(results)
3. raw_json = _serialize_results(results)
4. markdown = formatted + "\n\n=== Raw Results (JSON) ===\n" + json.dumps(raw_json)
5. return multimodal_assembler.assemble(
       markdown=markdown,
       results=results,
       trace=trace,
       max_images=self._max_images_per_response,
   )
```

### 4.3 有结果 + `use_llm=true`（LLM 总结模式）

```text
1. results = hybrid_search.search(...)
2. structured = response_builder.build(query, results, trace)
3. citations_text = <现有拼接逻辑>
4. markdown = structured.markdown + citations_text
5. return multimodal_assembler.assemble(markdown, results, trace, max_images=self._max_images_per_response)
```

### 4.4 异常降级

| 场景 | 当前行为（v1） | v2 行为 |
|-----|----------------|---------|
| `hybrid_search.search()` 抛异常 | 返回友好文本 | **不变** |
| `response_builder.build()` 抛异常 | 返回友好文本 | **不变** |
| `multimodal_assembler.assemble()` 抛异常 | N/A | **新增**：记录 error 日志，降级为"纯文本响应"（构造一个 fallback TextContent 返回 assemble 本应返回的 markdown），**不把整次查询弄挂**。对应 spec FR-006。 |
| 单张图片读取失败 | N/A | **既有**：assembler 内部 warning 跳过；execute 不感知 |

---

## 5. Trace 契约（**新增**）

### 5.1 新增 stage 记录

每次 `execute()` 成功返回前，**MUST** 追加一条 trace 条目到查询 trace 的 `stages` 列表：

```json
{
  "stage": "assemble_multimodal",
  "image_count_requested": <int>,
  "image_count_returned":  <int>,
  "image_count_failed":    <int>,
  "max_images":            <int>,
  "duration_ms":           <float>
}
```

| 字段 | 计算方式 |
|-----|---------|
| `image_count_requested` | `len(_extract_image_refs(results))`——去重后 |
| `image_count_returned`  | 最终返回列表中 `ImageContent` 的个数 |
| `image_count_failed`    | `image_count_requested - image_count_returned - dropped_by_limit`（其中 `dropped_by_limit = max(0, requested - max_images)`） |
| `max_images`            | 传入 assemble 的 `max_images` 值（从 settings 读） |
| `duration_ms`           | `assemble()` 进入到返回的时间（毫秒，float） |

### 5.2 字段不变性

- 即使 `image_count_requested == 0`，**MUST** 仍写入 trace（便于排查"为什么没图"）。
- 所有字段是**本 feature 新增**，与现有 `dense` / `sparse` / `fusion` / `rerank` stage 字段**不重叠**，Dashboard 无需特殊处理即可向后兼容（未识别字段忽略）。

---

## 6. 配置契约（**新增**）

### 6.1 `config/settings.yaml` 新增段

```yaml
# Query response settings
query:
  max_images_per_response: 10   # 单次响应返回图片数上限（>0 正整数）
```

**位置**：**在 `retrieval:` 之后、`rerank:` 之前**（语义：检索 → 响应组装 → 重排）。

### 6.2 `Settings` dataclass 新增字段

```python
query: QuerySettings = field(default_factory=QuerySettings)
```

**位置**：在 `retrieval: RetrievalSettings` 之后。

### 6.3 启动校验（load_settings 内）

```python
if settings.query.max_images_per_response <= 0:
    raise SettingsError("query.max_images_per_response must be > 0")
```

---

## 7. 测试契约

| 测试层 | 文件 | 关键断言 |
|--------|------|---------|
| Unit | `tests/unit/test_query_knowledge_hub.py` | 构造器 4 参数（None 抛错）；`max_images_per_response <= 0` 抛错；execute 调用 assembler.assemble 的参数传递正确 |
| Unit | `tests/unit/test_multimodal_assembler_limit.py` | `max_images=None` 不限制；`max_images=3` 时从 5 张图截取前 3 张；`max_images=0` 返回纯文本；`max_images=-1` 抛 ValueError |
| Integration | `tests/integration/test_multimodal_query.py` | 摄取含图 PDF → `execute({use_llm: false})` 返回至少 1 张 ImageContent 且 base64 合法；`execute({use_llm: true})` 同样返回图；图片缺失文件时返回仍含 TextContent |
| Regression | 既有所有 `tests/unit/test_query_knowledge_hub*` | 必须更新构造器入参但断言语义不回归 |

---

## 8. 不在本契约范围

- 纯检索模式下 `raw_results_json` 的结构调整——**保持不变**
- `Citations` 生成逻辑、`citations_text` 格式——**保持不变**
- LLM prompt、`ResponseBuilder._build_prompt`——**保持不变**
- `SQLiteImageStorage` 的 schema、路径——**保持不变**
- `ingestion.image_captioner` / `text_enricher`——**不涉及**

---

**契约结论**：变更面清晰（3 个签名 + 1 配置 + 1 trace stage），向后兼容性明确（assemble 新参数默认 None），可直接进入 tasks 拆分。
