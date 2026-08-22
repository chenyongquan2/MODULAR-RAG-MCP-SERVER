# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a modular RAG (Retrieval-Augmented Generation) server that exposes knowledge retrieval capabilities through the Model Context Protocol (MCP). The project is designed with a pluggable architecture where every component (LLM, embedding, splitter, vector store, reranker, evaluator) can be swapped without code changes.

**Current Status**: Work in progress, expected completion March 2026. The `dev-from-clean-start` branch contains ongoing development with DEV_SPEC task tracking.

## Branch Strategy

- **`main`**: Single commit with latest complete code
- **`dev`**: Full commit history showing incremental development
- **`clean-start`**: Skeleton framework for learning from scratch
- **`dev-from-clean-start`**: Active development branch from clean-start, with DEV_SPEC task tracking

## Common Commands

### Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .           # Editable install
pip install -e ".[dev]"    # With dev dependencies
pip install -e ".[rerank]" # Cross-Encoder 重排（可选，本地推理零 token，默认关闭）
```

### Testing
```bash
pytest tests/unit                    # Run unit tests only
pytest -m unit                       # Tests marked as unit
pytest -m integration                # Integration tests (requires external services)
pytest -m e2e                        # End-to-end pipeline tests
pytest --cov=src                     # With coverage report
pytest tests/unit/test_llm_factory.py -v   # Run single test file
pytest tests/unit/test_llm_factory.py::test_factory_creation -v  # Run single test
```

### Running the System
```bash
python main.py                       # Start MCP server (transport 由 settings.yaml 的 mcp_server.transport 决定: stdio | sse)
python scripts/ingest.py --path <file_or_dir> [--collection <name>] [--force]  # Offline document ingestion
python scripts/query.py --query <text> [--top-k <n>] [--collection <name>]     # Standalone query testing
python scripts/evaluate.py           # Run evaluation suite
python scripts/start_dashboard.py   # Launch Streamlit dashboard
```

**Ingest Examples**:
```bash
python scripts/ingest.py --path ./asset/rag_test_doc.md --force
python scripts/ingest.py --path ./tests/fixtures/sample_documents/ --collection my_docs
```

**Query Examples**:
```bash
python scripts/query.py --query "北极星到底是什么？"
python scripts/query.py --query "How to configure LLM?" --top-k 10
```

### Configuration

All configuration is in `config/settings.yaml`. Change any provider by modifying the corresponding section:

| Setting | Options |
|---------|---------|
| `llm.provider` | glm, azure, openai, ollama, deepseek |
| `embedding.provider` | bge, openai, azure, ollama, glm |
| `splitter.strategy` | recursive, semantic, fixed |
| `rerank.backend` | none（默认）, cross_encoder（需 `.[rerank]` extra）, llm |
| `evaluation.backends` | ragas, custom |

No code changes needed - factories auto-load the new implementation on restart.

**Environment Variables**:
- Use `${VAR_NAME}` syntax in settings.yaml (e.g., `${GLM_API_KEY}`)
- Support default values: `${VAR_NAME:-default_value}`
- Auto-injection: `LLM_API_KEY` and `EMBEDDING_API_KEY` are automatically injected if corresponding fields are empty
- Copy `.env.example` to `.env` and fill in your API keys

## Architecture

### Pluggable Architecture Pattern

Every component follows the same pattern:

1. **Base Abstract Class** in `src/libs/<component>/base_<component>.py`
   - Defines interface with `@abstractmethod`
   - Includes metadata methods like `get_model_name()`, `get_backend_name()`

2. **Provider Implementations** in same directory
   - Example: `azure_llm.py`, `openai_llm.py`, `ollama_llm.py`

3. **Factory** in `<component>_factory.py`
   - Registry pattern: providers auto-register on import
   - `create()` method reads `settings.yaml` and instantiates the configured provider

4. **Configuration Section** in `config/settings.yaml` + corresponding dataclass in `src/core/settings.py`

**To switch providers**: Just edit `settings.yaml` and restart - zero code changes needed.

### Data Flow

**Ingestion Pipeline:**
```
PDF → Loader → Markdown → Splitter → Chunks → Transform →
  ├─ DenseEncoder → VectorUpserter → ChromaDB
  ├─ SparseEncoder → BM25Indexer → BM25 Index
  └─ ImageCaptioner → ImageStorage
```

**Query Pipeline:**
```
Query → QueryProcessor → HybridSearch
  ├─ DenseRetriever → ChromaDB → dense results
  └─ SparseRetriever → BM25 → sparse results
    → Fusion (RRF) → Reranker → ResponseBuilder → Final Response
```

### Tracing System

Two trace types (both JSONL to `logs/traces.jsonl`):

| Trace Type | Stages |
|------------|--------|
| Query (`trace_type: "query"`) | query_processing → dense → sparse → fusion → rerank |
| Ingestion (`trace_type: "ingestion"`) | load → split → transform → embed → upsert |

The Streamlit dashboard reads these traces and dynamically renders based on `method`/`provider` fields - no dashboard code changes needed when swapping components.

## Development Workflow

### Mandatory SDD Workflow — OpenSpec

自 2026-08-12 起本项目用 **OpenSpec** 做 spec-driven development(此前是 GitHub Spec-Kit,已退役,见下节 § SDD 历史)。

**硬约束与项目底座在 [openspec/config.yaml](openspec/config.yaml) 的 `context:` 字段** —— 七条核心原则(provider 无关、配置驱动、快速失败、追踪显式、结构化日志、类型安全、测试支撑变更)、追溯性要求、以及一份「已知陷阱」清单都在那里。**冲突时以 config.yaml 为准。**

> OpenSpec 的规格是 **delta 模型**(`ADDED` / `MODIFIED` / `REMOVED`),只描述这次改了什么、不重述整个系统。这意味着 AI 必须先知道「现在是什么」—— 所以 `config.yaml` 的 § 已知陷阱 和本文件的 § Important Implementation Notes 是 delta 能否成立的前提,**它们不是可选背景资料**。

目录布局:

| 路径 | 含义 |
|---|---|
| `openspec/specs/` | 当前真相 —— 已落地能力的需求规格 |
| `openspec/changes/<name>/` | 在途变更(`proposal.md` / `design.md` / `tasks.md` / `specs/`) |
| `openspec/changes/archive/` | 已完成变更,按日期归档 |
| `openspec/config.yaml` | 项目底座 + 各产物的撰写规则 |

流程(非平凡变更走这条,slash command 或同名 skill 均可):

1. `/opsx:explore` —— 想不清楚时先探索,不产出正式产物(可跳过)
2. `/opsx:propose "<想做什么>"` —— 一步生成 proposal + design + specs + tasks
3. `/opsx:apply` —— 按 tasks 实现;改完 `src/` 必须在 `.venv` 下 `pytest tests/unit -v` 全绿
4. `/opsx:archive` —— 归档,并把这次的教训回写到 `CLAUDE.md` + `config.yaml` 的 § 已知陷阱

常用 CLI:`openspec list` / `openspec status <change>` / `openspec validate --all` / `openspec view`。

**没有相位门** —— 任何产物随时可改,改方向不需要重跑整条链。这是换掉 Spec-Kit 的主要原因。代价是纪律靠约定而非工具强制,所以下面的例外清单要自觉遵守。

**例外(不需要走 SDD)**:单文件 typo / 注释;依赖版本升级;`scripts/dev/` 下一次性探索脚本;根因明确且 < 10 行的 bug 修复;纯文档变更(`docs/`、`DEV_SPEC.md`、`CLAUDE.md`);为已有代码补测试(纯 `tests/` 新增,不改 `src/`)。

**追溯性**:修改 `src/` 的 commit message 需引用对应任务(如 `refs T-003`),上述例外不强制。

### SDD 历史(只读,不要在里面新增)

| 资产 | 时期 | 现状 |
|---|---|---|
| `specs/001-005/` + `.specify/` | 2026-04 ~ 2026-08,GitHub Spec-Kit | **已冻结**。当作探索时的参考材料,不要转换成 OpenSpec 规格。宪法 v1.0.0 原文留在 `.specify/memory/constitution.md` 作 ADR,其效力已转移到 `openspec/config.yaml` |
| `.specify/archived-skills/` | 同上 | 8 个 `speckit-*` skill 已停用移入此处(`.claude/` 被 gitignore,故存于跟踪目录以便回滚) |
| `DEV_SPEC.md` + `auto-coder` skill | 更早的自研 SDD | DEV_SPEC.md 现仅作高层技术设计参考(类似 ADR);`auto-coder` skill 保留,用于处理尚未迁移的 legacy 任务。**新 feature 不走这两条** |

### Adding a New Provider

Example: Adding a new LLM provider "anthropic"

1. Create `src/libs/llm/anthropic_llm.py`:
```python
from .base_llm import BaseLLM

class AnthropicLLM(BaseLLM):
    def __init__(self, settings, **kwargs):
        # Initialize Anthropic client
        pass

    def generate(self, prompt: str, **kwargs) -> str:
        # Implement generation logic
        pass

    def get_model_name(self) -> str:
        return self.settings.llm.model
```

2. Register in `src/libs/llm/llm_factory.py`:
```python
def _register_builtin_providers() -> None:
    from .anthropic_llm import AnthropicLLM
    LLMFactory.register_provider("anthropic", AnthropicLLM)
```

3. Add config section in `config/settings.yaml`:
```yaml
llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
```

4. Update dataclass in `src/core/settings.py` if new fields needed

## Key Design Principles

1. **Provider-Agnostic**: Never hardcode provider names in business logic - always use abstract interfaces
2. **Configuration-Driven**: All behavior controlled via `settings.yaml`, not environment-specific code
3. **Fail-Fast Validation**: Settings validated at startup in `src/core/settings.py`
4. **Explicit Tracing**: TraceContext passed explicitly (not thread-local) for transparency
5. **Structured Logging**: Use `observability.logger.get_logger()` - logs to stderr to avoid MCP stdout pollution
6. **Type Safety**: Shared types in `src/core/types.py` (Document, Chunk, SearchResult, etc.)

## Code Conventions

- **Imports**: Use absolute imports from `src/` root (e.g., `from core.settings import load_settings`)
- **Type Hints**: All public functions should have type hints
- **Docstrings**: Use Google-style docstrings for public APIs
- **Error Handling**: Raise `ValueError` for validation errors, `RuntimeError` for operational errors
- **Settings Access**: Always use `settings = load_settings()` to get configuration; never read YAML directly

## MCP Server Details

The MCP server supports **两种 transport**,由 `config/settings.yaml` 的 `mcp_server.transport` 切换(`stdio` | `sse`,见 `src/core/settings.py` 的 `VALID_TRANSPORTS`)。SSE 模式经 Starlette + uvicorn 提供 HTTP 服务(`src/mcp_server/server.py` 的 `run_sse()`),适用于常驻服务型调用方;stdio 适用于 Claude Desktop / Claude Code 这类按会话拉起子进程的客户端。

It exposes three tools:

| Tool | Description |
|------|-------------|
| `query_knowledge_hub` | Main RAG query endpoint (hybrid search + rerank + response generation with citations) |
| `list_collections` | List available document collections |
| `get_document_summary` | Get metadata for specific documents |

MCP clients (GitHub Copilot, Claude Desktop, etc.) connect via stdio and can call these tools to retrieve knowledge context.

**MCP Client Configuration**: The project-root `.mcp.json` file configures the MCP server connection for Claude Code. Paths are relative to the project root, so the file works unchanged if the project is moved.

> Windows 注意:`command` 指向 `.venv/Scripts/python.exe`。若在 Linux/macOS 使用,改为 `.venv/bin/python`。

## Streamlit Dashboard

Six-page management platform (`scripts/start_dashboard.py`):

1. **System Overview**: Current component configuration and data stats
2. **Data Browser**: View indexed documents, chunks, metadata, images
3. **Ingestion Manager**: Upload files, trigger ingestion, view progress, delete documents
4. **Query Traces**: Query history, latency waterfall, dense/sparse comparison, rerank diff
5. **Ingestion Traces**: Ingestion history, stage-by-stage breakdown
6. **Evaluation Panel**: Run evaluations, view metrics, historical trends

The dashboard is fully dynamic - component names displayed are read from trace logs, so it automatically adapts when you switch providers.

## Important Implementation Notes

- **Settings Loading**: `core.settings.load_settings()` loads from `config/settings.yaml` with env var overrides
- **Logger Usage**: Always import `from observability.logger import get_logger` and call `logger = get_logger(__name__)`
- **PDF Loading**: Currently only PDF and Markdown formats supported via `src/libs/loader/` (uses MarkItDown for PDF → Markdown conversion)
- **Vector Store**: ChromaDB is the only implemented backend currently
- **生效集合是 `default_text-embedding-v4`(1024 维)**。2026-08-09 `text-embedding-3-small` 从网关永久下架,已用 `scripts/reembed_corpus.py` 全量重嵌到 `qwen/text-embedding-v4`(52,757 条 / 5,276 次调用 / 136.5 分钟 / 零失败),dense 与 sparse 均正常。旧的 1536 维集合(`default` / `mt5_docs_*`)保留作归档与回滚,但**模型已下架,无法再产出匹配的查询向量**,不要把 `collection_name` 指回去
- **模型下架是这个网关的常态**,不是一次性事故:同一天 `text-embedding-3-small` 与 `z-ai/glm-4.7` 先后 `503 model_not_found`。遇到该错误先跑 `curl ${GLM_BASE_URL}/models` 看当前可用清单,再改 `settings.yaml` —— 项目是 provider 无关设计,换模型只改配置
- **Collection 语义**(Feature-004 起):`settings.vector_store.collection_name` 是 **dense 与 sparse 两路共同的唯一真源** —— dense 用它决定打开哪个物理 collection,sparse 用它决定加载哪个 BM25 索引文件。CLI 的 `--collection` **覆盖这个值**(真正切换检索范围),而不是塞进 `filters` 做融合后过滤。`filters` 只用于 `doc_type`/`tags` 等维度
- **BM25 索引格式**:v2,契约见 [specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md](specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md)。chunk 标识字典化(倒排项存整数下标)。**版本不匹配时 `BM25Indexer.load()` 直接抛 `ValueError`,不静默降级** —— 跑 `python scripts/rebuild_bm25_index.py --all` 重建
- **切分口径**:查询端与索引端**必须**共用 `src/core/text/tokenizer.py`,禁止各留一份。两端漂移的失败是静默的(不报错,只是召回恒为空),由 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 守住
- **金标评估集合**:`golden_test_set_{zh,en}.json` **必须**在含全部语料的集合上评估(当前是 `default_text-embedding-v4`),**不要指向 `mt5_docs_chinese` / `mt5_docs_english`**。中英文语料是同一份 MT5 文档的两个语言版本,金标回填时匹配跨了语言(en 集 42 条里 18 条跨语料、210 个 chunk_id 里 20 个指向中文),分语言集合只能解析 190/210,评估会直接触发 `chunk_id_validation` 失败
- **`custom__recall` 与 `ragas__context_recall` 量的不是一回事**:前者是「检索到的 chunk id 与回填脚本挑的那 5 个的重合比例」,后者是「检索到的上下文实际支撑答案的比例」。实测同一批结果分别是 0.30 与 0.83 —— 金标的 `expected_chunk_ids` 是 `backfill_chunk_ids.py` 机器按 top-5 回填的,非人工标注的答案边界,解读 `custom__recall` / `custom__ndcg` 时必须计入这个折扣
- **⚠️ RAGAS 聚合指标的分母是浮动的,报告里的数不是全样本均值**:judge 输出无法解析时该 case 的该指标记为 NaN,`eval_runner` 设计为**不计入分母**(见 [eval_runner.py:14](src/observability/evaluation/eval_runner.py#L14) 与 `degraded_case_count`),于是 42 条的金标可能只有 27 条参与了 faithfulness 的平均。2026-08-15 复核 run `80a82405`:`faithfulness` 15/42 降级(公布值 0.8887 实为 n=27 的均值)、`context_precision` 11/42 降级(0.7643 实为 n=31),`degraded_case_count: 23` = **54.8%,是 SC-006 所定 ≤ 5% 门槛的 11 倍**。后果有二:①单次报告的绝对值被幸存者偏差抬高;②**两次运行若降级条数不同则严格不可比**(delta 会把「分母变了」读成「质量变了」)。看 RAGAS 指标前**先看 `degraded_case_count`** —— 这个字段在报告 JSON 里,不在聚合指标里,极易漏读。**已治理**(change `evaluation-degradation-governance`):报告新增按指标的 `metric_integrity`(`valid_count` / `degraded_count` / `reasons`),降级率进 `acceptance_status`(门槛 `evaluation.degradation.max_ratio`,默认 0.05),`scripts/evaluate.py` 结束时把摘要打到 stderr,`BaselineManager` 在分母不一致时标注该指标不可比
- **降级的病因是「英文问题产出中文答案」,不是 judge 弱、不是 `max_tokens`**(2026-08-16 归因,42 条冻结元组,判定 `glm:z-ai/glm-5.2-free`,详见 [acceptance.md](openspec/changes/archive/2026-08-16-evaluation-degradation-governance/acceptance.md)):
  - **完全分离**:剔除网关限流干扰后的 14 条真实判定失败**全部**是「英文问题 + 中文答案」;语言一致的 14 条**零失败**。42 条里有 **28 条(66.7%)** 答案语言与问题不符
  - 机制上讲得通:faithfulness 先把 answer 拆成 statements、再拿 contexts 逐条做 NLI。answer 中文而 contexts 英文时两步都在跨语言做,而 RAGAS 0.1.x 的内部 prompt 是英文写的
  - **`max_tokens` 猜想已否证**:595 次成功判定调用**零空响应**,最长响应 3378 字符。labeling 路径那个前科(硬编码 200 致空响应)**没有**在 judge 路径重演,所以 `JudgeLLMSettings` **刻意不加** `max_tokens` —— 加一个不解决任何问题的配置项就是第三个 `top_m`。限定:该否证只在 `glm-5.2-free` 上做过
  - 「答案过短」不是独立成因:4 条短答案全都同时是语言错乱,而语言错乱且答案 ≥100 字符的仍有 71% 降级
  - **两个能力悬殊的 judge 收敛到同一残余降级率**(sonnet-5 33%、glm-5.2-free 扣除限流后 33%),这是「病因在输入侧」的旁证
  - ⚠️ **用免费模型跑批时,限流会伪装成降级**:本次 21 条降级里 7 条实为 `upstream_error`,且集中在连续区间 idx 17/23-28(突发窗口,非 case 属性)。看归因结果先按 `upstream_error` 过滤一遍
- **judge 强度对四项 RAGAS 指标的影响不均等,不要笼统地说「换 judge 分数就不能比」**(2026-08-15 配对实验,42 条冻结元组,旧 `glm:minimax/minimax-m2.7` vs `glm:anthropic/claude-sonnet-5`,方法见下):
  - `faithfulness` **稳健**:配对子集 n=23 上 0.9085 → 0.9478(p=0.29,不显著),**方向与「弱 judge 漏检矛盾致虚高」的预期相反**。业界那条警告在本项目语料上未兑现,现有 faithfulness 结论可以照用
  - `context_precision` **对 judge 最敏感**:配对 n=30 上 0.7861 → 0.7037(**p=0.0013**,18 降/3 升),报告口径 0.7643(n=31) → 0.6498(n=40)。**幅度 0.08~0.11 远大于日常决策所依据的差异** —— 它此前的值是在弱 judge 下测的,换 judge 后必须重新校准基线。这条对重排评估尤其要紧:`context_precision` 是四项里唯一不锚定 `expected_chunk_ids` 的指标(因而是当前**唯一可能公正评判重排**的候选),但它同时也是最经不起 judge 漂移的
  - `answer_relevancy` 显著下降但仍过阈:0.8473 → 0.8018(p=0.0028);`context_recall` 无显著变化(p=0.46)
  - **强 judge 能压降级率但压不平**:任一指标降级 55% → 33%,其中 `context_precision` 26% → 5%(基本修复),但 `faithfulness` 仍有 29% 判不出 —— 说明该项的降级**不是 judge 弱造成的**,病因在输入侧(实测:英文问题产出中文答案、最短答案仅 48 字符,statement 抽取无从下手)
  - **方法可复用**:不要用重跑 `scripts/evaluate.py` 做 judge 对照 —— 那会连检索与答案生成一起重做(`llm.temperature` 未设为 0),分数变化无法归因。正确做法是**拿归档报告 `case_results` 里已存的 query/answer/contexts/ground_truth 四元组**喂不同 judge,做严格配对比较;judge 在内存里覆写,不改 `settings.yaml`
  - ⚠️ **谁对谁错仍无人工裁判**:分歧最大的 case 41 两个 judge 给出 1.000 与 0.000 的相反判断,无法裁决。这与 v2 金标 `human_agreement_rate` 为 `null` 是同一个缺口 —— **两个 LLM 打架时本项目没有基准**
- **融合权重是配置项且语料相关**(Feature-005 起):`retrieval.fusion_weights` 控制 dense / sparse 两路在 RRF 中的相对分量,`retrieval.rrf_k` 控制平滑参数(此前硬编码 60)。**只有相对比例有意义** —— `{dense:1, sparse:0.5}` 与 `{dense:2, sparse:1}` 排序完全相同。当前值 `sparse=0.1` 由英文金标校准得出,**换语料必须重新校准**:`python scripts/calibrate_fusion_weights.py --build-cache --lang en` 然后 `--sweep --lang en`。完整曲线见 [specs/005-weighted-fusion/acceptance.md](specs/005-weighted-fusion/acceptance.md)
- **金标的 recall / hit_rate 不是混合检索的中立裁判**:`backfill_chunk_ids.py:85` 直接调 `vector_store.query()` 回填期望 chunk_id —— **纯 dense 检索,无 BM25、无融合**。因此这两项结构性地偏向 dense:任何 sparse 贡献挤掉一条 dense 命中就只能拉低它们。比较混合与单路时,`MRR` / `nDCG` 比 `recall` / `hit_rate` 可信。Feature-005 实测:英文金标上 `sparse` 任何正权重都会让 hit_rate 从 69.0% 掉到 66.7%(1 条 case),而 MRR 从 0.4365 升到最高 0.5395
- **重排是可选能力,默认关闭**(change `activate-cross-encoder-rerank` 起):`cross_encoder` 后端需 `pip install -e ".[rerank]"`(增量仅约 9 MB 4 个包 —— `torch` 早已由核心依赖 `docling` 拉入,不是重排引入的)。**本地推理,零 token**。推荐 `BAAI/bge-reranker-base`(中英双语,权重 1.08 GB,首次下载需 `HF_ENDPOINT=https://hf-mirror.com`)。`settings.yaml` **默认仍是 `backend: none`** —— A/B 显示负增益,见下条
  - `backend != none` 时 `model` **必填**,启动期校验。刻意不留隐式默认值(此前的兜底是纯英文 `ms-marco`,对中文语料无效且不报错)
  - 依赖没装却配了 `cross_encoder` → `load_settings()` 直接抛 `SettingsError` 并给出安装命令,**不静默降级**。探测在 `RerankerFactory.probe_backend`(不在 settings 里,否则库名会硬编码进 `src/core/`)
  - `rerank.top_m` **此前是死配置**(全仓只有定义和 dashboard 展示,从未截断过候选),现已生效:超出部分按原名次追加,不参与重排但不丢弃
  - `rerank.timeout_sec` / `batch_size` 为新增。超时靠**分批 + 批间计时**实现 —— cross-encoder 是同步 CPU 推理,`signal.alarm` 在 Windows 无效、线程 join 无法中断 torch。代价是超时粒度 = 一批的推理时间
  - **延迟实测**(AMD Zen 3、真实 chunk 中位 428 字符、`batch_size=8`):每候选 **121-147 ms** → 40 条候选约 **5.2 秒**。别拿短文本微基准(约 25 ms/pair)做规划,cross-encoder 开销随 token 数走
- **⚠️ 金标无法公正评判重排**(本项目当前最重要的评估局限):`expected_chunk_ids` 是 `backfill_chunk_ids.py` 用**纯 dense top-5** 回填的 —— 标准答案本身就是「embedding 认为最相关的那几条」,而重排的全部工作就是**不同意第一阶段的排序**。因此**四项 custom 指标全是 dense-anchored 的**,`MRR` / `nDCG` 对重排**并不比** `recall` / `hit_rate` 更中立(上一条关于 MRR/nDCG 更可信的说法只适用于 dense-vs-sparse 的路径比较)。实测:英文 42 条 MRR 0.4914 → 0.3668、中文 6 条 0.5833 → 0.4167,**而集成测试里同一模型每次都能把故意放在末位的相关段落提到首位**。模型在做正确的事,指标却在跌 —— 在换掉金标构造方式之前,本项目**没有可用于评判重排的离线指标**。详见 [activate-cross-encoder-rerank/acceptance.md](openspec/changes/archive/2026-08-13-activate-cross-encoder-rerank/acceptance.md) § 五
- **金标有两代,`expected_chunk_ids` 的构造方式不同,分数不可跨代比较**(change `retriever-agnostic-golden-labels` 起):
  - **第一代**(`version: v1.0`,报告里 `labeling_method: dense-top-k`):`scripts/backfill_chunk_ids.py` 把 `ground_truth` 编码后查 **纯 dense top-5** 回填。标准答案就是「embedding 认为最像答案的那几条」—— 这就是上一条说的那个评估局限的来源。**该脚本刻意保留**(第一代金标的可复现来源),但不要再用它产出新金标
  - **第二代**(`version: v2.0`,`labeling_method: pooled-llm-judged`):`scripts/label_golden_chunks.py` 用 **query**(不是答案)从 dense / sparse / rerank 三路各取 top-N 取并集,再让 LLM 判 0-3 分级相关度。中文 6 条实测:与纯 dense top-K 的 Jaccard 仅 **0.328**,被接受的 72 条里 **22 条(31%)是纯 dense 结构上看不到的**
  - **跨代 delta 会被报告显式标注 `delta_comparable: false`** —— 别把「标注口径变了」读成「检索质量变了」。换代次后必须重标基线
  - `evaluation.labeling_llm` **必须与 `judge_llm` 异源**(合成 `ground_truth` 的就是 judge),判据同 `screening_llm`:完整标识串相等即同源。**同源不可用 `--allow-same-source` 豁免**,该参数只豁免「无法确认」
  - ⚠️ **两代金标都没有机器可读的合成端标识**(建于 2026-04-28,早于 Feature-003 的 `_review_metadata`),所以异源检测返回 `UNVERIFIABLE`,当前只能靠 `--allow-same-source` 显式承担风险
  - ⚠️ **LLM 判定不等于人工级 ground truth**。它去掉了检索器锚定,但引入了判定模型自身的偏好。`--export-sample` / `--import-sample` 的人工抽检是校准手段
  - ⚠️ **v2 金标的校准是「跨模型」而非「人工」**(2026-08-14):24 条三元组由 `anthropic:claude-opus-5` 盲评,与 `glm:z-ai/glm-5.2-free` 一致率 **95.8%(23/24)**,唯一分歧那条复盘为原判定更正确。元数据里记的是 `cross_judge_agreement_rate`,**`human_agreement_rate` 是 `null`** —— 两个判定方都是 LLM,**可能共享人类会发现的盲点**。若将来重排结论(或任何依赖 v2 金标的结论)被质疑,**第一件该做的事就是补真人抽检**:审阅表在 `tests/fixtures/labeling_review_zh.md`,可直接对照两方分歧
  - `labeling_llm.max_tokens` **不要调小**。此前硬编码 200,真实语料上 367 字符的 chunk 就返回**空响应**,导致每条都标 `judge_failed` —— 表现得像「模型不遵从 JSON 格式」,真实原因是没给它写完的余量。默认 800
- **`scripts/evaluate.py` 与 `scripts/query.py` 都不写 query trace** —— 只有 MCP server 路径写 `logs/traces.jsonl`。想量某个阶段的真实耗时得写专门的基准脚本,别指望从 trace 里捞
- **跑 Python 脚本调试时务必加 `-u`** —— stdout 在管道下是全缓冲的,不加会看到空输出并误判成「进程卡死」。本项目的日志走 stderr、进度条走 stdout,两者混在一起时尤其容易误判
- **Image Handling**: Images extracted from PDFs are captioned using Vision LLM and stored separately. 自 feature-002 起，查询命中含图 chunk 时，`query_knowledge_hub` 工具会通过 `MultimodalAssembler` 同时返回文本与图片（MCP `ImageContent`，base64），两种模式（`use_llm=true/false`）策略一致。返图数量上限由 `query.max_images_per_response` 配置（默认 10）

## Evaluation System

Supports pluggable evaluators (Ragas, custom metrics). Evaluations run against golden test sets in `tests/fixtures/golden_test_set.json` (US1 占位) 或 `golden_test_set_{zh,en}.json` (US2 后真实金标)。

**8 项主聚合指标**(Feature-001 后默认):
- RAGAS 4 项:`ragas__context_recall` / `ragas__context_precision` / `ragas__faithfulness` / `ragas__answer_relevancy`
- Custom 4 项:`custom__hit_rate` / `custom__mrr` / `custom__recall` / `custom__ndcg`

**配置**:通过 `evaluation.backends` 启用 backend(`custom` 永久启用,`ragas` 视场景);Judge LLM、embedding、阈值、归档目录全部由 `config/settings.yaml` `evaluation.*` 控制(详见 [specs/001-rag-acceptance/contracts/settings.evaluation.schema.md](specs/001-rag-acceptance/contracts/settings.evaluation.schema.md))。

**Judge / Embedding 切换提示**(spec § Assumptions § Judge 切换与阈值校准):
- 不同 Judge LLM 对同一 (q, ctx, answer) 评分有 3-10% 系统性差异
- 切换 Judge(`evaluation.judge_llm.provider/model`)或 embedding(`evaluation.embedding.*`)后,**FR-013 默认阈值不再适用**;建议:
  1. 先在新 Judge 下用现有金标重跑评估、观察分数分布
  2. 据新分布在 `evaluation.acceptance_thresholds.*` 重新校准
- 每份评估报告自带 `acceptance_thresholds_snapshot` + `judge_llm_identifier` + `embedding_identifier`,跨 Judge 报告可追溯

**关键 CLI**:
- `scripts/evaluate.py --pretty --collection <name>` — 跑评估,自动 archive + delta vs baseline
- `scripts/synthesize_testset.py --collection <c> --lang {zh,en}` — RAGAS TestsetGenerator 合成候选(US2)
- `scripts/refine_testset.py --input <candidate>` — interactive y/e/d/s/q 精修
- `scripts/refine_testset.py --input <candidate> --auto-mode` — **异源 LLM 预筛 + borderline 路由**(Feature-003),只对存疑用例点人 + 收尾抽样自检
- `scripts/backfill_chunk_ids.py --input <golden> --collection <c>` — **第一代**回填(纯 dense top-5;保留作历史可复现,新金标不要用)
- `scripts/label_golden_chunks.py --input <golden> --output <v2> --collection <c>` — **第二代**标注(多路池化 + LLM 分级判定)。`--dry-run` 只池化不判定(零成本);`--export-sample N` / `--import-sample <f>` 做人工抽检

### 金标精修自动化(Feature-003)

`--auto-mode` 把逐条 100% 人工确认改为「机器预筛 → 只看存疑 → 抽样自检」,单语种人工耗时目标 30-60 min → ≤ 15 min。**不加该参数时行为与之前完全一致**,不读配置也不调用任何 LLM。

**前置配置** —— `config/settings.yaml` 的 `evaluation.screening_llm`,**必须与 `judge_llm` 异源**(合成端用的就是 judge_llm):

```yaml
evaluation:
  judge_llm:
    model: minimax/minimax-m2.7      # 合成端
  screening_llm:
    provider: glm
    model: z-ai/glm-4.7              # 预筛端,与上面不同即可
    api_key: ${GLM_API_KEY}
```

> 同源判据是**完整标识串** `<provider>:<model>` 相等,不是 provider 相等。实测 judge 标识为 `glm:minimax/minimax-m2.7` —— provider 名义是 glm 但模型经 OpenAI 兼容端点路由到 minimax;只比 provider 会把真正异源的 `glm:glm-4.6` 误判为同源。

**退出码**(仅 `--auto-mode` 下可能出现,不影响默认路径):

| 码 | 含义 |
|---|---|
| 2 | 前置条件不满足:`screening_llm` 未配置 / 与合成端同源 / 无法确认异源(可加 `--allow-same-source` 豁免后者,但**不豁免已确认的同源**) |
| 3 | 预筛模型整体不可用(凭据、网络)。与「模型通但输出不合格」严格区分——后者会全部降级 borderline 交人工 |
| 130 | 中断。**文件仍会写出**并标 `v0.9-partial`,已完成决策不丢 |

**审计记录**:auto 模式产出的金标带 `_review_metadata` 字段,含各路径计数、两端模型标识、阈值快照、borderline 占比、抽样合规率(含 SC-006 的 auto-kept 子集拆分)与告警列表。默认交互模式**不写出**该字段。

**阈值需要校准**:`keep_threshold` / `drop_threshold` 默认 `0.80` 是初始猜测。不同模型的置信度标度不可互换,换预筛模型后必须重新校准 —— 与上文「换 Judge 后阈值失效」是同一回事。校准办法:跑一轮看 `_review_metadata.borderline_ratio`,远高于 20% 说明阈值太严,接近 0% 说明太松。

详见 [specs/003-testset-refine-automation/quickstart.md](specs/003-testset-refine-automation/quickstart.md)。

**Dashboard**:`python scripts/start_dashboard.py` → 评估面板 → "🎯 Feature-001 基线 + 回归" tab(标基线 / 看 delta / 8 项指标趋势)。

## Working with DEV_SPEC.md

> **说明**:DEV_SPEC.md 现仅作**高层技术设计参考**(类似 ADR);新变更的任务追踪在 `openspec/changes/<name>/tasks.md`,**不在** DEV_SPEC.md。本节描述的是 legacy 流程,留作历史参考与 legacy 任务定位。

DEV_SPEC.md contains the complete technical specification organized as:
- Section 1-2: Project overview and design principles
- Section 3: Detailed technical design (RAG pipeline, pluggable architecture, tracing, evaluation)
- Section 4: Testing strategy
- Section 5: System architecture diagrams
- Section 6: **Project schedule with task tracking** - this is where task progress is marked

When implementing features, reference the corresponding section in DEV_SPEC.md for detailed requirements.

## Interaction Preferences

- **Language**: 用中文回答问题
- **Role**: 你是一个具备丰富 RAG 知识的专业高级开发工程师，用户是 RAG 开发经验尚浅的学习者
- **Code Comments**: 相关代码需要加上必要的中文注释，帮助理解 RAG 概念和实现细节
- **Testing**: 编写代码后，需要运行单元测试 (`pytest tests/unit -v`)，确保用例通过

## 学习笔记（docs/learning/）

用户要「学习笔记 / 学习文档 / 系统化整理某个主题」时，**走 `learning-topic` skill**，不要临场发挥。

**形态**：

- 落地位置 `docs/learning/`，英文 kebab-case 文件名，中文正文
- **两种体裁，别混**：单篇 `<topic>-explained.md` 是 **Explanation**（深、预设读者有基础）；`<topic>/` 目录是 **Tutorial 专题**（README + 编号短章，从 `00-prerequisites.md` 起铺台阶）。混在一篇里会让两者都变差
- 用户说「系统化」「适合新手」「补前置知识」→ 建专题，已有深文原样保留为参考层
- 已有专题：[rag-evaluation/](docs/learning/rag-evaluation/README.md)、[structured-output/](docs/learning/structured-output/README.md)

**内容（比形态更重要 —— owner 明确强调过）**：

- **必须补前置知识，不能让读者猜**。找法是**逆向定位卡点**：逐段问「新手读到这句会卡在哪」，卡点具体到某一句话，在 README 里用表格显式列出「卡点 ↔ 缺的前置」。列不出来说明前置是编的
- **读者就同一件事追问第二次 = 解释错了，不是读者笨**。追问位置精确指出缺口，且往往缺的是一整个层次（多半是缺 why it exists，只讲了 what）
- 有效动作：先纠正误解再讲正确的 / 锚到读者已有经验（如约束解码锚到 `temperature`）/ 具体走一遍带真实值 / 并排对比逼出差异 / **用实测数字不用形容词** / 类比要能回答后续问题
- 讲完机制**立刻给推论** —— 推论才是能用的东西，且上一章的推论正好是下一章的前提
- **所有数据标置信度**：`【实测】`（附日期）/`【文献】`/`【代码】`（附行号）/`【推演】`。**没跑过不许标【实测】**
- ⚠️ 写「本项目现状」类内容前，**先核对 CLAUDE.md / openspec / 代码注释里的既有结论**。新证据不自动作废旧归因（本项目已因此翻车一次，记录在 [structured-output/05-this-project.md](docs/learning/structured-output/05-this-project.md) §4②）

## Active Change

当前在途的变更用 `openspec list` 查看,不在本文件里登记 —— 这里曾有一个 `speckit-plan` 自动维护的 "Active Feature" 块,它在 2026-08-12 随 Spec-Kit 一起移除(该块设计上应覆写,实际却累积出了一个陈旧的 Feature-004 副本,是它退役的一个理由)。

最后一个 Spec-Kit feature 是 **005-weighted-fusion**(带权重的结果融合),已完成并冻结在 [specs/005-weighted-fusion/](specs/005-weighted-fusion/)。

> ⚠️ **本项目所有脚本与测试必须在 `.venv` 下运行**。全局 Python 的 protobuf 是 5.29.3,`import chromadb` 会失败;`.venv` 里是 3.20.3。

> 注:本项目不为单个变更开 git 分支,一律沿用 `dev-from-clean-start`。
