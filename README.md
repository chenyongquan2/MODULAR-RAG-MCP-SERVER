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
uv sync --extra dev --extra rerank
```

> ⚠️ **`rerank` extra 不是可选的**（除非你打算关掉重排）。出厂配置
> `rerank.backend: cross_encoder` 需要它；缺依赖时 `load_settings()` 会在**启动期**
> 直接抛 `SettingsError` 并给出安装命令 —— 刻意不静默降级成「不重排」。
> 不想装就把 `config/settings.yaml` 的 `rerank.backend` 改成 `none`。
> 增量约 9 MB / 4 个包（`torch` 早已由核心依赖 `docling` 拉入，不是重排引入的）。

若你暂时不使用 `uv`，也可以继续使用 `pip`（兼容旧流程）：

```powershell
cd C:\workspace\MODULAR-RAG-MCP-SERVER
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,rerank]"
```

### 1.1 迁移后日常依赖工作流（推荐）

日常开发建议统一使用 `uv` 命令，避免 `pip` / `uv` 混用导致环境漂移。

```powershell
# 拉取最新代码后，先同步依赖
.\.venv\Scripts\Activate.ps1
uv sync --extra dev --extra rerank

# 运行项目脚本（推荐通过 uv run）
uv run python scripts/ingest.py --path .\tests\fixtures\sample_documents --collection default_text-embedding-v4
uv run python scripts/query.py --query "北极星是什么？" --top-k 5 --collection default_text-embedding-v4
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
python scripts/ingest.py --path .\asset\rag_test_doc.md --collection default_text-embedding-v4 --force

# 摄取目录（递归扫描 .pdf/.md/.markdown/.chm）
python scripts/ingest.py --path .\tests\fixtures\sample_documents --collection default_text-embedding-v4
```

### 4. 查询验证

```powershell
python scripts/query.py --query "北极星是什么？" --top-k 5 --collection default_text-embedding-v4
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
  provider: openai         # bge | openai | azure | ollama | glm
  model: qwen/text-embedding-v4
  api_key: ${QWEN_EMBEDDING_API_KEY}
  base_url: ${QWEN_EMBEDDING_BASE_URL}
```

> ⚠️ **不要改回 `text-embedding-3-small`** —— 该模型 2026-08-09 已从网关永久下架
> （`503 model_not_found`）。它是 1536 维，而现存集合是 1024 维，换回去会直接维度不匹配报错
> （刻意不静默降级）。**模型下架在这个网关上是常态**：遇到该错误先
> `curl ${GLM_BASE_URL}/models` 看当前清单，再改配置 —— 项目是 provider 无关设计，换模型只改配置。

### Vector Store / Retrieval / Rerank

```yaml
vector_store:
  backend: chroma
  persist_path: ./data/db/chroma
  # dense 与 sparse 两路共用的唯一真源：dense 用它决定打开哪个物理 collection，
  # sparse 用它决定加载哪个 BM25 索引。切换语料只改这一个值。
  collection_name: default_text-embedding-v4

retrieval:
  sparse_backend: bm25
  fusion_algorithm: rrf
  rrf_k: 60                # RRF 平滑参数
  fusion_weights:          # 两路在融合中的相对分量，只有比例有意义
    dense: 1.0
    sparse: 0.75           # 在英文 41 条金标上校准得出
  top_k_dense: 20
  top_k_sparse: 20
  top_k_final: 10

rerank:
  backend: cross_encoder   # none | cross_encoder | llm
  model: BAAI/bge-reranker-base
  top_m: 50
  timeout_sec: 30.0
  batch_size: 8
```

> **关于重排默认开启**（2026-08-27 起）：`cross_encoder` 需要 `pip install -e ".[rerank]"`，
> **本地 CPU 推理、零 token**。实测收益（英文 41 条金标）nDCG **+0.0764**、MRR +0.0602，
> 中文 6 条 nDCG **+0.0914**；代价约 **2.8 秒/查询**。若你的调用方是面向真人的对话、
> 不能接受这个延迟，把 `backend` 改回 `none` 即可 —— 这本来就是一个配置项。
>
> ⚠️ **跑批前请设 `HF_HUB_OFFLINE=1`**。权重已落盘时 `sentence_transformers` 仍会向
> HuggingFace 发校验请求，墙内会**静默挂起**（看起来像死循环，实际阻塞在网络）。
> 首次下载权重则设 `HF_ENDPOINT=https://hf-mirror.com`。

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
  backends: [custom, ragas]      # custom 永久启用；ragas 需配置 judge_llm
  # 真正的金标按语种分开，由 scripts/evaluate.py 的 --lang 选择
  golden_test_sets_by_lang:
    zh: ./tests/fixtures/golden_test_set_zh_v2.json   # 6 条
    en: ./tests/fixtures/golden_test_set_en_v2.json   # 41 条

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

当前单元测试 **2,253 条**全绿（另有集成与 E2E 测试）。

### 运行评估

```powershell
$env:HF_HUB_OFFLINE = "1"      # 开了重排必须设，否则会静默挂在网络请求上
python -u scripts/evaluate.py --lang en --pretty --collection default_text-embedding-v4
```

> ⚠️ **必须加 `--lang`**。不加会去跑 `golden_test_set.json` —— 那是 4 条的占位集，
> 不是真金标。真金标由 `evaluation.golden_test_sets_by_lang` 指向（zh 6 条 / en 41 条）。
>
> ⚠️ **调试脚本时加 `-u`**。stdout 在管道下是全缓冲的，不加会看到空输出并误判成「进程卡死」。

**当前生产配置下的英文基准**（41 条 `pooled-llm-judged` 金标）：

| 指标 | 值 |
|---|---|
| `custom__hit_rate` | 0.9756 |
| `custom__mrr` | 0.9350 |
| `custom__ndcg` | 0.7948 |
| `custom__recall` | 0.5107 |

> 检索侧指标在多次独立运行中逐位可复现。⚠️ 但 RAGAS 四项**不可**这样解读 ——
> 它们的分母随判定失败浮动，看数前先看报告里的 `metric_integrity` 与 `degraded_case_count`。

### 额度恢复后回归清单（防遗忘）

若 Embedding 中转/API 额度不足导致 `ingest/query/evaluate` 报错，请在额度恢复后按以下顺序补跑：

```powershell
# 1) 激活环境 + 清理可能干扰的环境变量
.\.venv\Scripts\Activate.ps1
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue

# 2) I5 手工全链路验收
python scripts/ingest.py --path tests/fixtures/sample_documents/ --collection test --force
python scripts/query.py --query "测试查询" --top-k 5 --collection test
python -u scripts/evaluate.py --lang en --pretty --collection default_text-embedding-v4

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
uv sync --extra dev --extra rerank
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
