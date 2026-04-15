# Modular RAG MCP Server

一个可插拔、可观测的模块化 RAG（检索增强生成）服务框架，通过 MCP（Model Context Protocol）协议对外暴露工具接口，支持 Copilot / Claude Desktop 等客户端直接调用。

## 项目能力

- Ingestion Pipeline：PDF/Markdown/CHM -> Chunk -> Transform -> Embedding -> Upsert
- Hybrid Search：Dense + Sparse(BM25) + RRF Fusion + 可选 Rerank
- MCP Server：提供 `query_knowledge_hub`、`list_collections`、`get_document_summary`
- Dashboard：6 页面管理台（总览、数据浏览、Ingestion 管理、Ingestion Trace、Query Trace、评估）
- Evaluation：支持 golden test set 的评估与回归

## 快速开始

### 1. 环境准备（Windows PowerShell）

推荐使用 `uv` 进行依赖管理（更快、可锁定、环境更可复现）。

```powershell
cd C:\workspace\MODULAR-RAG-MCP-SERVER

# 安装 uv（若你尚未安装）
python -m pip install uv

# 创建并激活虚拟环境
uv venv .venv
.\.venv\Scripts\Activate.ps1

# 首次生成锁文件并安装（开发环境）
uv lock
uv sync --extra dev
```

若你暂时不使用 `uv`，也可以继续使用 `pip`（兼容旧流程）：

```powershell
cd C:\workspace\MODULAR-RAG-MCP-SERVER
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 1.1 迁移后日常依赖工作流（推荐）

日常开发建议统一使用 `uv` 命令，避免 `pip` / `uv` 混用导致环境漂移。

```powershell
# 拉取最新代码后，先同步依赖
.\.venv\Scripts\Activate.ps1
uv sync --extra dev

# 运行项目脚本（推荐通过 uv run）
uv run python scripts/ingest.py --path .\tests\fixtures\sample_documents --collection default
uv run python scripts/query.py --query "北极星是什么？" --top-k 5 --collection default
uv run pytest tests/unit -v
```

依赖变更规范：
- 新增运行时依赖：`uv add <package>`
- 新增开发依赖：`uv add --dev <package>`
- 删除依赖：`uv remove <package>`
- 升级并刷新锁文件：`uv lock --refresh && uv sync --extra dev`
- 提交代码时，`pyproject.toml` 与 `uv.lock` 需一并提交

详细说明见：[docs/DEPENDENCY_WORKFLOW.md](docs/DEPENDENCY_WORKFLOW.md)

### 2. 配置 API Key

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，至少补充你要使用的 provider 对应密钥。默认配置下建议先补：

- `GLM_API_KEY`
- `GLM_BASE_URL`
- `QWEN_EMBEDDING_API_KEY`
- `QWEN_EMBEDDING_BASE_URL`

### 3. 首次摄取（Ingest）

```powershell
# 摄取单个文件
python scripts/ingest.py --path .\asset\rag_test_doc.md --collection default --force

# 摄取目录（递归扫描 .pdf/.md/.markdown/.chm）
python scripts/ingest.py --path .\tests\fixtures\sample_documents --collection default
```

### 4. 查询验证

```powershell
python scripts/query.py --query "北极星是什么？" --top-k 5 --collection default
```

### 5. 启动 Dashboard

```powershell
python scripts/start_dashboard.py
```

默认访问 `http://localhost:8501`。

### 6. 启动 MCP Server（支持 stdio / SSE）

```powershell
python main.py
```

默认读取 `config/settings.yaml` 中的 `mcp_server.transport`：
- `stdio`：适配 Copilot / Claude Desktop 本地子进程模式
- `sse`：适配 HTTP/SSE 部署模式（容器、内网网关、远程调用）

## 配置说明（config/settings.yaml）

统一由 `load_settings()` 读取，业务代码不要直接解析 YAML。

### LLM

```yaml
llm:
  provider: glm      # glm | azure | openai | ollama | deepseek
  model: GLM-4.7
  api_key: ${GLM_API_KEY}
  base_url: ${GLM_BASE_URL}
```

### Embedding

```yaml
embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: ${QWEN_EMBEDDING_API_KEY}
  base_url: ${QWEN_EMBEDDING_BASE_URL}
```

### Vector Store / Retrieval / Rerank

```yaml
vector_store:
  backend: chroma
  persist_path: ./data/db/chroma
  collection_name: default

retrieval:
  sparse_backend: bm25
  fusion_algorithm: rrf
  top_k_dense: 20
  top_k_sparse: 20
  top_k_final: 10

rerank:
  backend: none      # none | cross_encoder | llm
  model: ""
  top_m: 50
```

### Ingestion 与 Observability

```yaml
ingestion:
  chunk_refiner:
    use_llm: false
  metadata_enricher:
    use_llm: false
  image_captioner:
    enabled: true
    use_fallback: true

observability:
  enabled: true
  log_file: ./logs/traces.jsonl

evaluation:
  backends: [custom]
  golden_test_set: ./tests/fixtures/golden_test_set.json

mcp_server:
  transport: stdio         # stdio | sse
  host: 127.0.0.1          # 仅 transport=sse 生效
  port: 8000               # 仅 transport=sse 生效
  sse_path: /sse           # SSE 连接端点（GET）
  message_path: /messages/ # 消息上行端点（POST）
```

## MCP 配置示例

### GitHub Copilot（`mcp.json`）

```json
{
  "servers": {
    "modular-rag": {
      "type": "stdio",
      "command": "python",
      "args": ["main.py"],
      "cwd": "C:/workspace/MODULAR-RAG-MCP-SERVER"
    }
  }
}
```

### Claude Desktop（`claude_desktop_config.json`）

```json
{
  "mcpServers": {
    "modular-rag": {
      "command": "python",
      "args": ["main.py"],
      "cwd": "C:/workspace/MODULAR-RAG-MCP-SERVER"
    }
  }
}
```

说明：
- 若你使用的是虚拟环境 Python，可把 `command` 改为 `.venv/Scripts/python.exe`（Windows）。
- MCP 通信为 stdio，日志请查看 `logs/` 下文件，不要依赖 stdout 调试信息。

### SSE 部署示例

1. 修改 `config/settings.yaml`：

```yaml
mcp_server:
  transport: sse
  host: 0.0.0.0
  port: 8000
  sse_path: /sse
  message_path: /messages/
```

2. 启动服务：

```powershell
python main.py
```

3. 服务端点：
- SSE 握手地址（GET）：`http://<host>:<port>/sse`
- 消息上行地址（POST）：`http://<host>:<port>/messages/?session_id=<id>`

说明：
- `message_path` 会在握手后由服务端通过 `endpoint` 事件自动告知客户端，一般不需要手工拼接。
- 生产环境建议在反向代理层加 TLS 与鉴权，不建议直接公网裸露端口。

### Codex 客户端同时配置 stdio + SSE（示例）

你可以在 Codex MCP 配置中同时保留两个入口，按场景切换：

```json
{
  "servers": {
    "modular-rag-stdio": {
      "type": "stdio",
      "command": ".venv/Scripts/python.exe",
      "args": ["main.py"],
      "cwd": "C:/workspace/MODULAR-RAG-MCP-SERVER"
    },
    "modular-rag-sse": {
      "type": "sse",
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

建议：
- 本机开发联调用 `modular-rag-stdio`（启动简单，进程生命周期由客户端托管）。
- 远程部署或多端共享用 `modular-rag-sse`（服务端常驻，便于网关治理）。

仓库内也提供了可直接复制的模板文件：
- [docs/examples/mcp.codex.example.json](C:/workspace/MODULAR-RAG-MCP-SERVER/docs/examples/mcp.codex.example.json)

## Dashboard 使用指南

启动命令：

```powershell
python scripts/start_dashboard.py
```

页面说明：

- Overview：展示当前组件配置、数据统计、最近链路状态
- Data Browser：浏览文档与 Chunk，查看 metadata 和图片引用
- Ingestion Manager：上传/选择文件执行摄取，查看进度并删除文档
- Ingestion Traces：查看摄取阶段耗时瀑布图
- Query Traces：查看查询链路阶段耗时与召回/重排变化
- Evaluation Panel：运行评估并查看指标报表

截图示例（建议放在 `docs/images/`）：

```markdown
![Dashboard Overview](docs/images/dashboard-overview.png)
![Data Browser](docs/images/dashboard-data-browser.png)
![Ingestion Traces](docs/images/dashboard-ingestion-traces.png)
![Query Traces](docs/images/dashboard-query-traces.png)
![Evaluation Panel](docs/images/dashboard-evaluation-panel.png)
```

你可以先按上述文件名保存截图，后续直接复用这段 Markdown。

## 运行测试

```powershell
# 单元测试（默认开发必跑）
pytest tests/unit -v

# 集成测试
pytest tests/integration -v

# E2E 测试
pytest tests/e2e -v

# 全量
pytest -v
```

可单独运行评估脚本：

```powershell
python scripts/evaluate.py --test-set tests/fixtures/golden_test_set.json --pretty
```

### 额度恢复后回归清单（防遗忘）

若 Embedding 中转/API 额度不足导致 `ingest/query/evaluate` 报错，请在额度恢复后按以下顺序补跑：

```powershell
# 1) 激活环境 + 清理可能干扰的环境变量
.\.venv\Scripts\Activate.ps1
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue

# 2) I5 手工全链路验收
python scripts/ingest.py --path tests/fixtures/sample_documents/ --collection test --force
python scripts/query.py --query "测试查询" --top-k 5 --collection test
python scripts/evaluate.py --test-set tests/fixtures/golden_test_set.json --pretty

# 3) 自动化回归
pytest tests/e2e -v
pytest -v
```

完成上述步骤后，建议在日志中记录：
- 执行日期
- 使用的 provider / endpoint
- `pytest -v` 结果摘要（passed/failed/skipped）

## 常见问题（FAQ）

### 1) 启动时报 API Key 缺失

现象：`Failed to load settings` 或 provider 鉴权失败。

排查：
- 确认 `.env` 是否存在（由 `.env.example` 复制而来）
- 确认 `config/settings.yaml` 引用的环境变量在 `.env` 中都有值
- 重新激活虚拟环境后再运行命令

### 2) 依赖安装后仍报 `chromadb` / `protobuf` 冲突

排查：

使用 `uv` 时：

```powershell
uv lock --refresh
uv sync --extra dev
```

使用 `pip` 时：

```powershell
pip install "protobuf>=3.20.0,<4"
pip install -e .
```

并确认当前 Python 来自 `.venv`：

```powershell
(Get-Command python).Source
```

若 `uv sync` 提示 `.venv` 文件被占用（Windows 常见）：
- 先停止正在使用 `.venv` 的进程（如 `python main.py`、编辑器 Python LSP）。
- 重新执行 `uv sync --extra dev`。
- 若仍失败，可临时执行 `uv venv .venv_new` + `UV_PROJECT_ENVIRONMENT=.venv_new uv sync --extra dev` 验证依赖，再在空闲时切回 `.venv`。

### 3) MCP Client 连接不上

排查：
- 配置中的 `cwd` 必须指向项目根目录
- `command`/`args` 要能在该目录启动 `python main.py`
- 先在终端手动执行 `python main.py`，确认服务可启动
- 检查客户端日志，确认 JSON-RPC 初始化是否成功

### 4) 查询无结果

排查：
- 先运行 `scripts/ingest.py` 完成摄取
- 确认查询时 `--collection` 与摄取集合一致
- 检查 `data/db/chroma` 与 BM25 索引是否已生成

## 目录速览

```text
src/
  core/
  ingestion/
  libs/
  mcp_server/
  observability/
scripts/
tests/
config/
```

详细设计与排期见 `DEV_SPEC.md`。

## License

MIT
