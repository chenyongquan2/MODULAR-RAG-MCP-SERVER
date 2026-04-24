# Quickstart: 多模态查询响应链路闭合

> 端到端验证 30 分钟脚本。跑完这份 quickstart 即意味着 spec 的 P1 / P2 / P3 三个 User Story 全部可观测通过。

---

## 前置条件

- Python 3.11 venv 已激活（`.venv\Scripts\activate` on Windows）
- `pip install -e ".[dev]"` 已完成
- `.env` 已配好 `GLM_API_KEY` / `AZURE_*` 等所需 key（参考 `.env.example`）
- 本 feature 的代码改动已落地（或 implement 阶段进行中）

---

## Step 1：确认配置（2 min）

打开 `config/settings.yaml`，确认有以下新段（若无，手动添加）：

```yaml
query:
  max_images_per_response: 10
```

确认 `loader.extract_images: true` 和 `ingestion.image_captioner.enabled: true`（摄取侧图片流水线开启）。

---

## Step 2：摄取一份含图 PDF（5 min）

```bash
python scripts/ingest.py --path ./asset/rag_test_doc.md --force
```

或使用现成含图测试 fixture：

```bash
python scripts/ingest.py --path ./tests/fixtures/sample_documents/ --collection qs_test
```

**预期输出**：
- `logs/traces.jsonl` 追加一条 `trace_type: "ingestion"`，`stages` 含 `load / split / transform / embed / upsert`
- `data/db/image_index.db` 体积增长
- `data/images/{collection}/` 出现 `.png` 文件

```bash
ls data/images/qs_test/ | head -5   # 应看到若干 img_*.png
```

---

## Step 3：纯检索模式查询（5 min，验证 P1）

```bash
python scripts/query.py --query "<触及图片内容的问题>" --top-k 5
```

> Tip：选一个你**知道**会命中含图 chunk 的问题（比如若 rag_test_doc 里有架构图，问"架构图里 Reranker 的位置"）。

**期望**（需要在 `query.py` 也走 MCP 工具链路，或者直接走 MCP 客户端）：
- 返回包含多条结果
- `logs/traces.jsonl` 最后一条 `trace_type: "query"` 的 `stages` 中**包含** `assemble_multimodal` stage，且 `image_count_returned > 0`

验证 trace：

```bash
tail -1 logs/traces.jsonl | python -m json.tool | grep -A 5 assemble_multimodal
```

---

## Step 4：MCP 客户端端到端（10 min，P1 核心验证）

### 4.1 启动 MCP server

```bash
python main.py
```

server 应打印：
```
Modular RAG MCP Server - Starting with transport=stdio
Prepared tool: query_knowledge_hub
```

### 4.2 从 Claude Desktop 连接

确认 `.claude/mcp.json` 或 Claude Desktop 的 MCP 配置指向 `main.py`。重启 Claude Desktop，询问：

> 用 query_knowledge_hub 查一下「<你在 Step 3 用的那个问题>」，use_llm=false

**预期**：
- Claude Desktop 的消息框里**直接渲染出图片**（而不仅仅是文本引用）
- 响应里同时出现命中 chunk 的文本 + 至少 1 张图

若**成功看到图** → P1 ✅。

### 4.3 LLM 总结模式（验证 P2）

再问：

> 用 query_knowledge_hub 查一下「<同一问题>」，use_llm=true

**预期**：
- 得到 LLM 生成的一段 Markdown 文字（内容应自然引用图中元素，因为 caption 已经通过 TextEnricher 融入 chunk.text）
- 文字之后**同样附上图片**（与 use_llm=false 选中的图集合一致，因为 clarify Q2 选了"命中 chunk 所有图"策略）

---

## Step 5：边界场景验证（5 min）

### 5.1 图片缺失降级

故意删除一张图片文件：

```bash
rm data/images/qs_test/img_<some_id>.png
```

再跑 Step 4.2。**预期**：
- 响应仍含文本与其他可用图，不抛错
- `logs/traces.jsonl` 对应 query 的 `assemble_multimodal` 字段 `image_count_failed >= 1`

### 5.2 上限配置生效

把 `config/settings.yaml` 改为：

```yaml
query:
  max_images_per_response: 2
```

重启 server。再跑一个命中 ≥ 3 张图的查询。**预期**：
- 响应只含 2 张 ImageContent
- trace 中 `image_count_returned == 2`、`max_images == 2`

### 5.3 无图 chunk 兼容

问一个**不会命中任何含图 chunk** 的问题（如纯代码/纯文本章节）。**预期**：
- 响应只含 TextContent，不报错
- trace 中 `image_count_requested == 0`、`image_count_returned == 0`

---

## Step 6：自动化测试（3 min，验证 P3）

```bash
pytest tests/unit -v                    # 既有单测 + 新增 test_multimodal_assembler_limit
pytest tests/integration -v             # 包含 test_multimodal_query.py
pytest -m integration -k multimodal     # 只跑本 feature 的集成测试
```

**预期**：
- 所有既有用例通过（零回归，对应 spec FR-010 + SC-003）
- `test_multimodal_query.py` 的 e2e 用例通过（对应 spec SC-002）

---

## 验收清单（映射回 Success Criteria）

| SC | 验证 |
|----|------|
| SC-001（100% 看到相关图）| Step 4.2 肉眼观察 |
| SC-002（集成测试通过率 100%）| Step 6 |
| SC-003（零回归）| Step 6 |
| SC-004（时延增加 ≤ 20%）| 对比 Step 3 在摄取含图 vs 纯文本时 `query.py` 的总 duration（trace 的 `duration_ms` 汇总） |
| SC-005（图缺失零失败）| Step 5.1 |
| SC-006（trace 可检索）| Step 3 / 5.2 / 5.3 的 `tail -1 logs/traces.jsonl` |

全部 ✅ → feature ready to merge。

---

## 常见问题

- **Q: Step 4 Claude Desktop 连接失败？**
  A: 检查 `.claude/mcp.json` 路径是否已更新到当前项目；检查 `python main.py` 是否能独立启动无报错。

- **Q: Step 4 看到图片 base64 但不渲染？**
  A: 检查 `ImageContent.mimeType` 是否以 `image/` 开头；Claude Desktop 只渲染 `image/png` 和 `image/jpeg`。

- **Q: Step 5.1 删图后响应变成纯错误？**
  A: 检查 `MultimodalAssembler._load_image` 是否吞掉异常（应返回 None 而非抛错）；若抛错到 assemble 层，则检查 execute 的 exception handler 是否按 §4.4 v2 规则降级为纯文本而非整体失败。
