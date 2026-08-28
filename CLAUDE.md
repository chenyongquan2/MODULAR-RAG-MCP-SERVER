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

### ⚠️ 先读这条:本项目的招牌病是「看起来生效、实际没生效、而且不报错」

排一排事故:`rerank.top_m` 死配置(全仓只有定义,从未截断过候选)、`--collection` 死参数(塞进 `filters` 做融合后过滤,没真正切集合)、`labeling_llm.max_tokens=200` 饿死判定(367 字符 chunk 就返回空响应,表现得像「模型不遵从 JSON」)、CJK 全链路 ASCII-only、chunk_id 两端不相交、RAGAS `adapt()` 静默不翻译、磁盘缓存固化坏产物、`synthesis.question_language_mismatch_warn` 只被校验从不被读、`_labeling_method` 从未流到报告、`query_rewrite` 段从未接进 `load_settings()` —— **十次事故同一个病。十次里有六次都有日志,只是日志说的是「成功」。**

  **第十例是第九例的翻版,而且发生在「已经知道这个病」之后**(2026-08-25):`QueryRewriteSettings` 加了、校验函数写了并挂进 `validate_settings`、`settings.yaml` 也写了 —— **但 `load_settings()` 构造 `Settings(...)` 时漏了 `query_rewrite=` 那一行**,无论 YAML 写什么运行时都是默认值。发现它时,该变更已有 100+ 条用例全绿,**包括一整个专门守「改了配置结论就该变」的文件** —— 它们全都直接构造 dataclass,**绕过了 YAML 加载这一段**。真正撞见它是改完配置顺手打印了一下。**新增配置项时,必须有一条用例写一份临时 `settings.yaml` 走真实 `load_settings()`**,而不是构造 dataclass;并且要**验证拆掉接线它会红** —— 抓不到 bug 的回归测试等于没有

  **第九例最狠:它连单测都有**(2026-08-24 修)。`eval_runner._load_test_cases` 构造 meta 时只拷了三个键,**没拷 `_labeling_method`** —— 而它是金标代次的唯一代码判据。于是 `labeling_method` **恒回落成 `dense-top-k`**,文档里那条「跨代 delta 会被标 `delta_comparable: false`」在标注方式这一维上**从未生效过**(实证:归档报告 `97743b41` / `d08e540d` 跑的是 `pooled-llm-judged` 的 `en_v2`,报告里却都写着 `dense-top-k`)。⚠️ **重排翻转结论不受影响** —— 那次 A/B 两臂用的是同一份正确金标,错的只是报告上的标签。**教训在于既有单测的形状**:`TestLabelingMethodField` 测的是「`EvalReport` 收到值后会不会序列化」,**从没测过这个值有没有被读出来** —— 单测测的是终点,没人测那条线。**「有单测」不等于「接上了」**;要守的是**端到端那条线**(文件写 X,报告就必须是 X),不是端点行为

  **第八例最有教育意义,因为它发生在「专门为消灭这个病」的变更内部**(2026-08-24 归档核对时抓到):`language_check.mismatch_ratio` 写好了、有单测、`question_language_mismatch_warn` 进了 settings 并被校验取值范围 —— **然后没有任何生产路径调用它们**。说明这个病不是「粗心」,而是「写实现 + 写单测」这套流程**结构上不覆盖「实现有没有被接上」**:单测测的是函数,没人测那条线。**补一个「改了这个配置,结论就该变」的用例** —— 死配置的判据正是「改了它什么都不变」。

**可操作的判据**:任何「配置项 / 参数 / 转换步骤」上线时,先回答一句 **「它没生效的时候,我怎么会知道?」** 答不出来就补一条校验或一个断言测试。这比事后加日志有效得多。**还有一条**:不要用「回落成看起来正常的默认值」来处理「没测 / 测不了」—— 那会让「没测」和「测过且完美」长得一样。正确形态是显式的 `measured: false` + **不给**那个会被误读的数(现例:`_synthesis_metadata.language_consistency`)。两条最常踩的具体形态:

- **只捕获异常检测不出静默失效**(2026-08-24,change `expand-chinese-golden-set`):RAGAS `adapt(language=chinese)` 的 fail-fast 只捕 `RuntimeError`,而真实失败形态是**不抛异常但没翻译** —— 它「成功」了,写出完整的 11 个 prompt 文件,CJK 占比**全为 0.0%**。**必须校验产物本身,不能只看有没有报错。** 现已由 `src/observability/evaluation/language_check.py`(纯函数,不 import ragas)+ `testset_synthesizer.py` 的产物校验守住,配置项 `synthesis.adapt_language_ratio_min`(默认 0.05,锚点是「未翻译时实测恒为 0.0%」)
- **缓存会把坏产物永久固化**(同上):2026-04-28 那次 adapt 的英文产物被写进磁盘缓存,此后**每次合成都从磁盘读到英文 prompt,换什么模型都一样** —— 第一代中文金标 47 条候选丢掉 33 条(70%)的根因就在这里。**缓存本是为了绕过「LLM 输出不稳定」,结果把不稳定的产物永久化了。** 缓存 LLM 产物必须带来源标识与校验标记(现为旁挂的 `_adapt_metadata.json`:模型完整标识 / 目标语言 / 校验结果 / 实测占比 / 写入时间),**缺元数据或校验未过者 MUST NOT 被读取**,并留强制重建的手段。物证保留在 `logs/ragas_adapt_cache_POISONED_EVIDENCE/`
- **⚠️ RAGAS 的 `adapt(language=chinese)` 在本项目上无可用模型**(2026-08-16 实测,一模型一进程):`minimax/minimax-m2.7`(679.9 s)、`z-ai/glm-5.2`(922.9 s)、`z-ai/glm-5.2-free`(769.5 s)**三者形态完全一致** —— 跑满十几分钟、写满 11 个文件、CJK 占比全 0.0%、不抛异常。**这种一致性说明失败点在 RAGAS 0.1.21 的实现,不在模型能力,换模型不是解法**。此前「换掉 GLM 是因为它不遵从 JSON」那个结论也**不适用于 adapt**(该误诊的真实原因是 `max_tokens`,只对标注任务成立)。中文金标扩容需**绕开 evolution**、直接用 LLM 从中文 chunk 生成问题,已登记为 [BACKLOG](openspec/BACKLOG.md) 梯队三 C1。⚠️ 另外:RAGAS 的 `simple` / `reasoning` / `multi_context` 是**模块级可变单例**,一个进程里跑第二个模型的 `adapt()` 会因「已适配」立刻返回 —— **探针必须一模型一进程**,否则会误判成「秒过」

- **Settings Loading**: `core.settings.load_settings()` loads from `config/settings.yaml` with env var overrides
- **Logger Usage**: Always import `from observability.logger import get_logger` and call `logger = get_logger(__name__)`
- **PDF Loading**: Currently only PDF and Markdown formats supported via `src/libs/loader/` (uses MarkItDown for PDF → Markdown conversion)
- **Vector Store**: ChromaDB is the only implemented backend currently
- **生效集合是 `default_text-embedding-v4`(1024 维)**。2026-08-09 `text-embedding-3-small` 从网关永久下架,已用 `scripts/reembed_corpus.py` 全量重嵌到 `qwen/text-embedding-v4`(52,757 条 / 5,276 次调用 / 136.5 分钟 / 零失败),dense 与 sparse 均正常。旧的 1536 维集合(`default` / `mt5_docs_*`)保留作归档与回滚,但**模型已下架,无法再产出匹配的查询向量**,不要把 `collection_name` 指回去
- **模型下架是这个网关的常态**,不是一次性事故:同一天 `text-embedding-3-small` 与 `z-ai/glm-4.7` 先后 `503 model_not_found`。遇到该错误先跑 `curl ${GLM_BASE_URL}/models` 看当前可用清单,再改 `settings.yaml` —— 项目是 provider 无关设计,换模型只改配置
- **Collection 语义**(Feature-004 起):`settings.vector_store.collection_name` 是 **dense 与 sparse 两路共同的唯一真源** —— dense 用它决定打开哪个物理 collection,sparse 用它决定加载哪个 BM25 索引文件。CLI 的 `--collection` **覆盖这个值**(真正切换检索范围),而不是塞进 `filters` 做融合后过滤。`filters` 只用于 `doc_type`/`tags` 等维度
- **BM25 索引格式**:v2,契约见 [specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md](specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md)。chunk 标识字典化(倒排项存整数下标)。**版本不匹配时 `BM25Indexer.load()` 直接抛 `ValueError`,不静默降级** —— 跑 `python scripts/rebuild_bm25_index.py --all` 重建
- **切分口径**:查询端与索引端**必须**共用 `src/core/text/tokenizer.py`,禁止各留一份。两端漂移的失败是静默的(不报错,只是召回恒为空),由 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 守住
- **当前生效的金标与基线**(2026-08-24 起):`evaluation.golden_test_sets_by_lang` 指向 **`_v2` 两份**(`golden_test_set_zh_v2.json` 6 条 / `golden_test_set_en_v2.json` 41 条,均为 `pooled-llm-judged`)。集合 `default_text-embedding-v4` 的**当前基线**是 run `16e13a32`(2026-08-28 标,`marked_by: production-config-rerank-on-en-2026-08-28`,英文 41 条,**与生产配置一致:`sparse=0.75` + `rerank: cross_encoder`**,41/41 完成零 ERROR)。历史基线按序降级进 `logs/baselines.json` 的 `history`:`0798cc98` → `80a82405`(第一代金标) → `57259cb6`(第二代 + sparse=0.1) → `728a77ab`(sparse=0.75 + 旧提示词) → `b3706441`(答案语言已修,但 `rerank: none`),**都不要删**。
  - **当代 custom 四项基准(英文,生产配置 = sparse 0.75 + 重排开)**:`hit_rate 0.9756` / `mrr 0.9350` / `ndcg 0.7948` / `recall 0.5107`(run `16e13a32`)
  - 上一版(同配置但 `rerank: none`,run `b3706441`)是 `0.9756 / 0.8748 / 0.7184 / 0.4584` —— 与它的 delta 就是重排那一步的收益
  - ⚠️ **这轮的三个 delta 与 B3 检索专项 A/B 逐位相同**(MRR +0.0602 / nDCG +0.0764 / recall +0.0523),而两次跑法完全不同(本轮带答案生成 + RAGAS + `custom__` 前缀键名;B3 那两臂是 `--no-generate-answers` + 无前缀)。**这是对「检索侧完全可复现」的一次独立交叉验证**,也说明重排结论不依赖于跑法
  - ⚠️ **该报告 `acceptance_status` 是 `fail`,但两个失败项都不代表检索质量退步**:①`custom__recall` 0.5107 < 阈值 0.70 —— 而第二代金标每 case 平均 **15.37** 个标签、`top_k_final=10`,**理论 recall 上限只有 0.7116**,阈值等于要求达到理论极限的 98.4%。**这个阈值是给第一代金标(恒 5 个标签,top-10 轻松 recall=1.0)定的,换金标后没人重新校准** —— 它报「质量不达标」,实际是「尺子换了阈值没跟着换」。②降级率 22.0%(9/41)超 5% 门槛,但该量本身不可复现(见下文,同配置两轮曾为 4.9% 与 31.7%)。**阈值重校准尚未立项**
  - 再上一版(sparse=0.1 + 无重排)是 `0.9756 / 0.8585 / 0.7140 / 0.4584` —— 与 `b3706441` 的 delta 就是权重那一步的收益(MRR +0.0163、nDCG +0.0044,零延迟零 token)
  - **中文 6 条已在 0.75 下补测**(2026-08-27,run `9f56c494`,`--no-generate-answers` + `backends:[custom]`):`0.8333 / 0.6667 / 0.6120 / 0.4584`。⚠️ **权重升到 0.75 在中文上是负增益** —— 对照 sparse=0.1 的 `0.8333 / 0.7500 / 0.6230 / 0.4584`,MRR **−0.0833**、nDCG −0.0110,hit_rate 与 recall 持平。**但 n=6,`−0.0833` 恰好等于 `(1 − 1/2)/6`,即「一条 case 从第 1 名掉到第 2 名」** —— 方向可信,幅度不可当精确值。含义:**`sparse: 0.75` 是在英文 41 条上校准的,它对中文并非最优**,而语料 81.4% 是中文。分语种权重尚未立项;开重排后中文 MRR 回到 0.75(见重排那条),这个损失在生产配置下被盖过去了
  - ⚠️ **同一份 zh 报告 2026-08-25 就已经在 0.75 下跑过一次**(run `1863a523`,四项与 `9f56c494` **逐位相同**),只是没人把它回写进本文件 —— 于是「尚未重测」这句话在文档里多活了两天。顺带再次印证检索侧可复现
  - **检索侧完全可复现** —— 这几个数在三次独立运行里逐位重合(含归档 A/B 的 `none` 臂),可放心当基准
  - ⚠️ **RAGAS 四项在这次权重变更上大部分不可比**:`faithfulness`(n 25→27)、`answer_relevancy`(40→41)、`context_precision`(36→33)三项被报告自动标进 `delta_incomparable_metrics`(分母不一致)。**只有 `context_recall` 分母未变(41→41),其 delta 是 −0.0122**。看到 RAGAS 那几个「改善」先查分母,别当成权重的收益
  - 跑法:`scripts/evaluate.py` **必须加 `--lang`**,否则会去跑 4 条的占位集 `golden_test_set`:`.venv/Scripts/python.exe -u scripts/evaluate.py --lang en --pretty --collection default_text-embedding-v4`
  - 标基线:`.venv/Scripts/python.exe -u scripts/dev/mark_baseline.py --report-id <uuid> --marked-by <label>`(先 `--dry-run` 看会降级掉谁)。⚠️ `BaselineManager` 是**原子写但无锁**,并发标基线会静默丢一次更新
  - ⚠️ **基线只按 collection 存一份,不分语种**:标了英文基线后跑中文,会拿 6 条中文去比 41 条英文,而 `delta_comparable` 仍是 `True`(标注方式相同),只有 `delta_incomparable_metrics` 以「分母不一致」拦住 —— **拦住了但理由说错了**。看中文 delta 时留意这点
- **金标评估集合**:`golden_test_set_{zh,en}.json` **必须**在含全部语料的集合上评估(当前是 `default_text-embedding-v4`),**不要指向 `mt5_docs_chinese` / `mt5_docs_english`**。中英文语料是同一份 MT5 文档的两个语言版本,金标回填时匹配跨了语言(en 集 42 条里 18 条跨语料、210 个 chunk_id 里 20 个指向中文),分语言集合只能解析 190/210,评估会直接触发 `chunk_id_validation` 失败
- **`custom__recall` 与 `ragas__context_recall` 量的不是一回事**:前者是「检索到的 chunk id 与回填脚本挑的那 5 个的重合比例」,后者是「检索到的上下文实际支撑答案的比例」。实测同一批结果分别是 0.30 与 0.83 —— 金标的 `expected_chunk_ids` 是 `backfill_chunk_ids.py` 机器按 top-5 回填的,非人工标注的答案边界,解读 `custom__recall` / `custom__ndcg` 时必须计入这个折扣
- **⚠️ RAGAS 聚合指标的分母是浮动的,报告里的数不是全样本均值**:judge 输出无法解析时该 case 的该指标记为 NaN,`eval_runner` 设计为**不计入分母**(见 [eval_runner.py:14](src/observability/evaluation/eval_runner.py#L14) 与 `degraded_case_count`),于是 42 条的金标可能只有 27 条参与了 faithfulness 的平均。2026-08-15 复核 run `80a82405`:`faithfulness` 15/42 降级(公布值 0.8887 实为 n=27 的均值)、`context_precision` 11/42 降级(0.7643 实为 n=31),`degraded_case_count: 23` = **54.8%,是 SC-006 所定 ≤ 5% 门槛的 11 倍**(⚠️ 那是**第一代金标**上的数;2026-08-24 在第二代 `en_v2` 41 条上重测为 **46.3%(19/41)**,仍是门槛的 9 倍。病灶集中在 `faithfulness`(**39.0%**,16/41 全部 `unparseable`),而 `context_recall` **零降级** —— 与「病因在输入侧的语言错乱、不是 judge 弱」这个既有归因一致。中文 6 条上 `faithfulness` 只有 **1 条**有效,那份报告里的 `1.0000` 是单条算出来的,**是「先读 `metric_integrity` 再读数」最好的教材**)。后果有二:①单次报告的绝对值被幸存者偏差抬高;②**两次运行若降级条数不同则严格不可比**(delta 会把「分母变了」读成「质量变了」)。看 RAGAS 指标前**先看 `degraded_case_count`** —— 这个字段在报告 JSON 里,不在聚合指标里,极易漏读。**已治理**(change `evaluation-degradation-governance`):报告新增按指标的 `metric_integrity`(`valid_count` / `degraded_count` / `reasons`),降级率进 `acceptance_status`(门槛 `evaluation.degradation.max_ratio`,默认 0.05),`scripts/evaluate.py` 结束时把摘要打到 stderr,`BaselineManager` 在分母不一致时标注该指标不可比
- **降级的病因是「英文问题产出中文答案」,不是 judge 弱、不是 `max_tokens`**(2026-08-16 归因,42 条冻结元组,判定 `glm:z-ai/glm-5.2-free`,详见 [acceptance.md](openspec/changes/archive/2026-08-16-evaluation-degradation-governance/acceptance.md)):
  - **完全分离**:剔除网关限流干扰后的 14 条真实判定失败**全部**是「英文问题 + 中文答案」;语言一致的 14 条**零失败**。42 条里有 **28 条(66.7%)** 答案语言与问题不符
  - ⚠️ **2026-08-25 修正了这条的机制表述**:此前写的是「answer 中文而 contexts 英文时两步都在跨语言做」——**跨语言配对不是判据**。在第二代金标 + 当前配置上按上下文分组实测(run `728a77ab`,英文 41 条):

    | 上下文 | 答案 | n | 降级率 |
    |---|---|---|---|
    | en | en | 11 | **18%** |
    | en | zh | 12 | 58% |
    | **zh** | **en** | 5 | **0%** |
    | zh | zh | 13 | 62% |

    答案**匹配**上下文的组 42% 降级、**不匹配**的组 41% —— **没有区别**;而「中文上下文 + 英文答案」是 **0%**。所以真实判据是**答案是不是英文**,与上下文无关。机制:faithfulness 先把 answer 拆成 statements 再做 NLI,而 RAGAS 0.1.x 的内部 prompt 是英文写的 —— **它处理中文答案本身就不行**。(n 小,尤其那 5 条;方向明确但幅度别当精确值)
  - ⚠️ **「答案跟问题同语言」不是充分条件,而且这条与 `adapt` 失败同根**:中文那轮(run `31f2ed71`,6 条)**6/6 语言一致**(中文问→中文答),仍 **5/6 降级**,`faithfulness` 只剩 1 条有效。合起来看:**`ragas==0.1.21` 实质只能工作在英文上,而让它支持中文的机制(`adapt(language=chinese)`,三个模型全部产出 0.0% 中文)是坏的** —— 这是同一句话的两面。**含义:RAGAS 在本项目的中文内容上永远不会好,而语料 81.4% 是中文。** 要解决那一半只有换掉 RAGAS 或绕开它,尚未立项
  - **`max_tokens` 猜想已否证**:595 次成功判定调用**零空响应**,最长响应 3378 字符。labeling 路径那个前科(硬编码 200 致空响应)**没有**在 judge 路径重演,所以 `JudgeLLMSettings` **刻意不加** `max_tokens` —— 加一个不解决任何问题的配置项就是第三个 `top_m`。限定:该否证只在 `glm-5.2-free` 上做过
  - 「答案过短」不是独立成因:4 条短答案全都同时是语言错乱,而语言错乱且答案 ≥100 字符的仍有 71% 降级
  - **两个能力悬殊的 judge 收敛到同一残余降级率**(sonnet-5 33%、glm-5.2-free 扣除限流后 33%),这是「病因在输入侧」的旁证
  - ⚠️ **用免费模型跑批时,限流会伪装成降级**:本次 21 条降级里 7 条实为 `upstream_error`,且集中在连续区间 idx 17/23-28(突发窗口,非 case 属性)。看归因结果先按 `upstream_error` 过滤一遍
- **⚠️ 降级率(`degraded_case_count`)本身也是不可复现的量,不能设阈值判定**(2026-08-25 实测):**同配置、同提示词、同金标**跑两轮,降级率是 **4.9%(2/41)** 与 **31.7%(13/41)** —— 相差 **6.5 倍**。原因与下一条同源:答案生成无温度控制(`llm.temperature` 字段不存在)、judge 在同一输入上也会翻转。**用它看方向可以(两轮都低于修复前的 41.5%),拿它当验收阈值不行。** ⚠️ 这个坑我们自己踩过一次:`answer-language-follows-question` 的验收记录里,一边写着「RAGAS 的量不可归因」,一边拿单次的 4.9% 当判据 —— **写下「这个量不可靠」与「用这个量下结论」之间需要一道显式检查**
- **⚠️ `temperature=0` 不等于可复现 —— 冻结元组还不够**(2026-08-25 实测,change `answer-language-follows-question`):`context_recall` 只依赖 `(question, ground_truth, contexts)`,三者**逐字相同**、`judge_llm.temperature = 0.0`,判定仍在 **4/41(9.8%)** 条上翻转(0.5→0.0、1.0→0.0、0.5→1.0)。托管模型的批处理与内核非确定性都会引入抖动。**所以 RAGAS 的 ±0.05 级 delta 即使分母稳定也不可归因** —— 真要比较需多次重复取均值并给区间,不是拿单次两个数做减法。⚠️ 另注 `llm.temperature` **这个字段根本不存在**(答案生成用 provider 默认温度),所以答案每轮都不同:同一次对照里 `answer_relevancy` 在 **38/41** 条上都变了
- **⚠️ 做「逐位不变」类回归判定前,先按 `ERROR` 过滤日志**(同上变更):一次 `OpenAI Embedding API call failed: Request timed out.` 就让一条 case 的 dense 路降级为空列表(`HybridSearch` 的既有设计,正确),该路四项归零,进而改变两项融合后指标 —— 看起来像代码回归。**重放该 case 后完全恢复**(dense 检索连跑三次逐位稳定、embedding 对同一文本两次调用逐位相同)。项目那句「检索侧完全可复现」是真的,**前提是网关不抖**。这与「限流会伪装成降级」是同一类陷阱的另一面
- **judge 强度对四项 RAGAS 指标的影响不均等,不要笼统地说「换 judge 分数就不能比」**(2026-08-15 配对实验,42 条冻结元组,旧 `glm:minimax/minimax-m2.7` vs `glm:anthropic/claude-sonnet-5`,方法见下):
  - `faithfulness` **稳健**:配对子集 n=23 上 0.9085 → 0.9478(p=0.29,不显著),**方向与「弱 judge 漏检矛盾致虚高」的预期相反**。业界那条警告在本项目语料上未兑现,现有 faithfulness 结论可以照用
  - `context_precision` **对 judge 最敏感**:配对 n=30 上 0.7861 → 0.7037(**p=0.0013**,18 降/3 升),报告口径 0.7643(n=31) → 0.6498(n=40)。**幅度 0.08~0.11 远大于日常决策所依据的差异** —— 它此前的值是在弱 judge 下测的,换 judge 后必须重新校准基线。这条对重排评估尤其要紧:`context_precision` 是四项里唯一不锚定 `expected_chunk_ids` 的指标(因而是当前**唯一可能公正评判重排**的候选),但它同时也是最经不起 judge 漂移的
  - `answer_relevancy` 显著下降但仍过阈:0.8473 → 0.8018(p=0.0028);`context_recall` 无显著变化(p=0.46)
  - **强 judge 能压降级率但压不平**:任一指标降级 55% → 33%,其中 `context_precision` 26% → 5%(基本修复),但 `faithfulness` 仍有 29% 判不出 —— 说明该项的降级**不是 judge 弱造成的**,病因在输入侧(实测:英文问题产出中文答案、最短答案仅 48 字符,statement 抽取无从下手)
  - **方法可复用**:不要用重跑 `scripts/evaluate.py` 做 judge 对照 —— 那会连检索与答案生成一起重做(`llm.temperature` 未设为 0),分数变化无法归因。正确做法是**拿归档报告 `case_results` 里已存的 query/answer/contexts/ground_truth 四元组**喂不同 judge,做严格配对比较;judge 在内存里覆写,不改 `settings.yaml`
  - ⚠️ **谁对谁错仍无人工裁判**:分歧最大的 case 41 两个 judge 给出 1.000 与 0.000 的相反判断,无法裁决。这与 `pooled-llm-judged` 金标 `human_agreement_rate` 为 `null` 是同一个缺口 —— **两个 LLM 打架时本项目没有基准**
- **融合权重是配置项且语料相关**(Feature-005 起):`retrieval.fusion_weights` 控制 dense / sparse 两路在 RRF 中的相对分量,`retrieval.rrf_k` 控制平滑参数(此前硬编码 60)。**只有相对比例有意义** —— `{dense:1, sparse:0.5}` 与 `{dense:2, sparse:1}` 排序完全相同。**当前值 `sparse=0.75`**(2026-08-25 在第二代金标上重校准),**换语料必须重新校准**:`python scripts/calibrate_fusion_weights.py --build-cache --lang en` 然后 `--sweep --lang en`
  - ⚠️ **上一个值 `0.1` 不是「随语料过时」,而是当时就偏低**:它是在第一代 `dense-top-k` 金标上校准的,而那把尺子的标准答案本身就是「embedding 认为最像答案的那几条」—— 于是任何 sparse 贡献挤掉一条 dense 命中都被记为退步,校准过程被**系统性压向低 sparse 权重**。这与它结构性惩罚重排是同一根因
  - 第二代金标上的端到端曲线(英文 41 条,真实管线):`0.1 → 0.8585` / `0.5 → 0.8707` / **`0.75 → 0.8748`(最优)** / `1.0 → 0.8726`(且 nDCG、recall 开始掉)。四项无一倒退,**零延迟零 token**
  - ⚠️ **别拿离线扫描的绝对值外推到管线**:扫描在 top-20 上打分给出 +0.051 MRR,端到端(`top_k_final=10`)只有 **+0.0163**。扫描是选权重的排序工具,不是增益预测器
  - ⚠️ 校准缓存自 v2 起记录金标来源与标注方式,换了金标会**直接拒绝加载**而不是拿旧标签算出推荐值(2026-08-25 修,那是招牌病的潜伏态)
  - 第一代金标上的完整曲线仍见 [specs/005-weighted-fusion/acceptance.md](specs/005-weighted-fusion/acceptance.md),作历史参照
- **金标的 recall / hit_rate 不是混合检索的中立裁判**:`backfill_chunk_ids.py:85` 直接调 `vector_store.query()` 回填期望 chunk_id —— **纯 dense 检索,无 BM25、无融合**。因此这两项结构性地偏向 dense:任何 sparse 贡献挤掉一条 dense 命中就只能拉低它们。比较混合与单路时,`MRR` / `nDCG` 比 `recall` / `hit_rate` 可信。Feature-005 实测:英文金标上 `sparse` 任何正权重都会让 hit_rate 从 69.0% 掉到 66.7%(1 条 case),而 MRR 从 0.4365 升到最高 0.5395
- **重排是可选能力,默认关闭**(change `activate-cross-encoder-rerank` 起):`cross_encoder` 后端需 `pip install -e ".[rerank]"`(增量仅约 9 MB 4 个包 —— `torch` 早已由核心依赖 `docling` 拉入,不是重排引入的)。**本地推理,零 token**。推荐 `BAAI/bge-reranker-base`(中英双语,权重 1.08 GB,首次下载需 `HF_ENDPOINT=https://hf-mirror.com`)。**2026-08-27 起 `settings.yaml` 默认 `backend: cross_encoder` + `model: BAAI/bge-reranker-base`**(B3 拍板,依据见下条)。此前默认 `none`,理由是「A/B 显示负增益」—— **那个结论所依据的两个数都是错的**,已在重测中推翻
  - ⚠️ **开启后每次冷启动都会尝试联网** —— 权重已落盘时 `sentence_transformers` 仍会向 HuggingFace 发校验请求,墙内会**静默挂起**(实测 6 条的评估跑了 10 分钟零 CPU 占用,看起来像死循环,实际阻塞在网络)。**跑批前设 `HF_HUB_OFFLINE=1`(已下载过)或 `HF_ENDPOINT=https://hf-mirror.com`(首次下载)**。设了之后同一轮 48 秒跑完。这是「开默认」引入的新税,不是重排本身的问题
  - **B3 决策依据**(2026-08-27,英文 41 条 `pooled-llm-judged` / `sparse=0.75`;`1adc0e4e` = none vs `47e841b8` = cross_encoder):MRR `0.8748 → 0.9350`(**+0.0602**)、nDCG `0.7184 → 0.7948`(**+0.0764**)、recall `0.4584 → 0.5107`(**+0.0523**)、hit_rate 持平。**中文 6 条同向**(`9f56c494` → `804f57a9`):MRR `0.6667 → 0.7500`(**+0.0833**)、nDCG `0.6120 → 0.7034`(**+0.0914**)、recall `0.4584 → 0.5556`(**+0.0972**) —— 中文的相对增益比英文还大,与 `bge-reranker-base` 是中英双语模型一致。代价约 **2.8 秒/查询**,**零 token**。取舍已按 MCP 场景(调用方是 agent)拍板接受
  - ✅ **基线已于 2026-08-28 重标到生产配置**(run `16e13a32`,带答案生成的完整英文评估)。⚠️ 但 C17 那条约束仍然成立:**不要用 `--no-generate-answers` + `backends:[custom]` 的检索专项跑去标基线** —— 其 `aggregate_metrics` 用无前缀键名(`mrr`),与全量报告的 `custom__mrr` 键集不相交,而 `BaselineManager._compute_delta` 对缺失基线键是静默 `continue`,delta 会**整个变成空 dict 且不告警**
  - `backend != none` 时 `model` **必填**,启动期校验。刻意不留隐式默认值(此前的兜底是纯英文 `ms-marco`,对中文语料无效且不报错)
  - 依赖没装却配了 `cross_encoder` → `load_settings()` 直接抛 `SettingsError` 并给出安装命令,**不静默降级**。探测在 `RerankerFactory.probe_backend`(不在 settings 里,否则库名会硬编码进 `src/core/`)
  - `rerank.top_m` **此前是死配置**(全仓只有定义和 dashboard 展示,从未截断过候选),现已生效:超出部分按原名次追加,不参与重排但不丢弃
  - `rerank.timeout_sec` / `batch_size` 为新增。超时靠**分批 + 批间计时**实现 —— cross-encoder 是同步 CPU 推理,`signal.alarm` 在 Windows 无效、线程 join 无法中断 torch。代价是超时粒度 = 一批的推理时间
  - **延迟实测**(AMD Zen 3、真实 chunk 中位 428 字符、`batch_size=8`):每候选 **121-147 ms**。别拿短文本微基准(约 25 ms/pair)做规划,cross-encoder 开销随 token 数走
  - ⚠️ **候选量此前记错了一倍**(2026-08-25 修):归档记录写「40 条候选约 5.2 秒」,并注「生产实际:`top_k_dense` 20 + `top_k_sparse` 20」—— 但那 40 是**融合前**两路之和,而重排拿到的是**融合后截断**的结果。`hybrid_search` 把融合结果截到 `top_k_final * 2`,实测重排每次只收到 **12~19 条**,所以真实延迟约 **2 秒**而非 5.2 秒
  - ⚠️ **`rerank.top_m: 50` 永远不会 binding** —— 上游截断是 `top_k_final * 2 = 20`,比它紧得多。想让重排看更多候选,要改的是 `top_k_final`(或那个 `*2`),改 `top_m` 无效。这是 `top_m` 的第三种死法:被读了、也在用,但值因上游更紧的约束而不可达。⚠️ `tests/unit/test_no_dead_settings.py` 那个守卫**抓不到这类** —— 它守的是有没有读取点(语法层),这是语义层。由 `tests/unit/test_rerank_candidate_budget.py` 守住
- **⚠️ `dense-top-k` 金标(第一代)无法公正评判重排 —— 但这个局限已被第二代解除**(2026-08-13 发现,2026-08-14 随 change `retriever-agnostic-golden-labels` 翻转):第一代的 `expected_chunk_ids` 是 `backfill_chunk_ids.py` 用**纯 dense top-5** 回填的 —— 标准答案本身就是「embedding 认为最相关的那几条」,而重排的全部工作就是**不同意第一阶段的排序**。因此**在第一代金标下**四项 custom 指标全是 dense-anchored 的,`MRR` / `nDCG` 对重排**并不比** `recall` / `hit_rate` 更中立(上一条关于 MRR/nDCG 更可信的说法只适用于 dense-vs-sparse 的路径比较)。**换掉标注方式后 A/B 方向直接翻转**(英文金标、`backends: [custom]`、`--no-generate-answers`、集合 `default_text-embedding-v4`;`run_id` `d08e540d` = none / `97743b41` = cross_encoder):

  | 指标 | `dense-top-k`(42 条) | `pooled-llm-judged`(41 条) |
  |---|---|---|
  | `custom__mrr` | 0.4914 → 0.3668　**−0.1246** | 0.8585 → 0.9350　**+0.0764** |
  | `custom__ndcg` | 0.4182 → 0.3373　**−0.0809** | 0.7140 → 0.7916　**+0.0776** |
  | `custom__recall` | 0.4571 → 0.4190　−0.0381 | 0.4584 → 0.5081　+0.0497 |
  | `custom__hit_rate` | 0.6905 → 0.6905　0 | 0.9756 → 0.9756　0 |

  当时集成测试里同一模型每次都能把故意放在末位的相关段落提到首位,指标却在跌 —— **模型在做正确的事,是尺子在说谎**。**当前口径**:`pooled-llm-judged` 金标下 `custom__mrr` / `custom__ndcg` **可以**用来评判重排,以及任何「敢改变名次」的改进(查询改写、HyDE 同理);**但不要再用第一代金标去评它们**。⚠️ 绝对值仍不可跨代比 —— 第二代每 case 均值 **14.9** 条标签(第一代恒为 5 条),`hit_rate` 从 0.69 涨到 0.98 主要是「标签变多了更容易命中」。详见 [activate-cross-encoder-rerank/acceptance.md](openspec/changes/archive/2026-08-13-activate-cross-encoder-rerank/acceptance.md) § 五(局限的原始诊断)与 [retriever-agnostic-golden-labels/acceptance.md](openspec/changes/archive/2026-08-14-retriever-agnostic-golden-labels/acceptance.md)(翻转的实测)
- **金标有两代标注方式,`expected_chunk_ids` 的构造方式不同,分数不可跨代比较**(change `retriever-agnostic-golden-labels` 起)。**一律用标注方式名称呼(`dense-top-k` / `pooled-llm-judged`),不要用「v1 / v2」** —— 文件名后缀、JSON 的 `version` 字段、`_labeling_method` 三者会打架,**只有 `_labeling_method` 是代码判据**([eval_runner.py:421](src/observability/evaluation/eval_runner.py#L421),缺失即回落为 `dense-top-k`;设计说明在同文件 [:105](src/observability/evaluation/eval_runner.py#L105))。完整解释(词源、两种答案、逐词拆解、制作流程、两代偏向)见 [golden-test-set-explained.md](docs/learning/golden-test-set-explained.md)
  - **`dense-top-k`**(第一代,文件名无后缀):`scripts/backfill_chunk_ids.py` 把 `ground_truth`(**答案**)编码后查 **纯 dense top-5** 回填。期望片段 = 某一路检索器的输出,即**检索器锚定**。**该脚本刻意保留**(第一代金标的可复现来源),但不要再用它产出新金标
  - **`pooled-llm-judged`**(第二代,文件名后缀 `_v2`):`scripts/label_golden_chunks.py` 用 **query**(不是答案)从 dense / sparse / rerank 三路各取 top-N 取并集,再让 LLM 判 0-3 分级相关度 —— 这是 TREC pooling 的做法,只是把人工评审员换成了 LLM。与纯 dense top-K 的 Jaccard:英文 **0.406** / 中文 **0.328**(远低于 0.90 告警线,说明池化与判定确实生效);中文被接受的 72 条里 **22 条(31%)是纯 dense 结构上看不到的**
  - **跨代 delta 会被报告显式标注 `delta_comparable: false`** —— 别把「标注口径变了」读成「检索质量变了」。换标注方式后必须重标基线
  - `evaluation.labeling_llm` **必须与 `judge_llm` 异源**(合成 `ground_truth` 的就是 judge),判据同 `screening_llm`:完整标识串相等即同源。**同源不可用 `--allow-same-source` 豁免**,该参数只豁免「无法确认」
  - ⚠️ **两代金标都没有机器可读的合成端标识**(建于 2026-04-28,早于 Feature-003 的 `_review_metadata`),所以异源检测返回 `UNVERIFIABLE`,当前只能靠 `--allow-same-source` 显式承担风险
  - ⚠️ **LLM 判定不等于人工级 ground truth**。它去掉了检索器锚定,但引入了判定模型自身的偏好。`--export-sample` / `--import-sample` 的人工抽检是校准手段
  - ⚠️ **`pooled-llm-judged` 金标的校准是「跨模型」而非「人工」**(2026-08-14):24 条三元组由 `anthropic:claude-opus-5` 盲评,与 `glm:z-ai/glm-5.2-free` 一致率 **95.8%(23/24)**,唯一分歧那条复盘为原判定更正确。元数据里记的是 `cross_judge_agreement_rate`,**`human_agreement_rate` 是 `null`** —— 两个判定方都是 LLM,**可能共享人类会发现的盲点**。**上面那条重排翻转结论正是建立在这个前提上的**;若它(或任何依赖第二代金标的结论)被质疑,**第一件该做的事是补真人抽检,而不是先去改检索代码**:审阅表在 `tests/fixtures/labeling_review_zh.md`,可直接对照两方分歧。做交叉判定务必**盲评**(先藏掉原判定与理由),否则第二判定方会附和,算出的一致率没有校准价值
  - `labeling_llm.max_tokens` **不要调小**。此前硬编码 200,真实语料上 367 字符的 chunk 就返回**空响应**,导致每条都标 `judge_failed` —— 表现得像「模型不遵从 JSON 格式」,真实原因是没给它写完的余量。默认 800
- **⚠️ 融合后的指标会把单路的变化藏起来 —— 增益和伤害都会**(2026-08-25,change `per-route-metrics-and-synonym-rewrite`):当时的 `fusion_weights.sparse = 0.1`(现已改为 0.75)意味着只作用于 sparse 的改动,在融合后指标上几乎不可见。⚠️ **权重升到 0.75 后这个稀释效应减弱但不消失** —— 判定单路改动仍必须看分路径指标。实测:同义词扩展让 sparse 单路 MRR 掉了 **0.061**,而**融合后只动了 0.0006** —— 光看融合后指标会读成「没效果」,实际是明确的伤害。**任何只作用于单路的改动(查询改写、分词策略、BM25 参数)必须看分路径指标判定**,报告里的 `aggregate_metrics_by_route` 就是为此加的(`EvalRunner` 经 `HybridSearch.search_with_routes()` 拿两路各自结果,复用同一套指标函数打分)
  - **分路径基准**(英文 41 条 `pooled-llm-judged`,run `0147ce03`)。⚠️ **分路径指标与融合权重无关** —— 它们量的是融合**之前**每一路自己的结果,所以这组数在权重改成 0.75 之后依然有效:dense 单路 `0.9756 / 0.7793 / 0.6835 / 0.4584`,sparse 单路 `0.9024 / 0.8104 / 0.6342 / 0.3925`(hit_rate / MRR / nDCG / recall)
  - ⚠️ **「瓶颈在 sparse」这个说法要分维度**:`recall`(0.3925 vs 0.4584)与 `hit_rate`(0.9024 vs 0.9756)上确实成立,但**排序质量上 sparse 反而更强**(MRR 0.8104 > dense 0.7793),而它的权重只有 0.1。这与「权重 0.1→0.75 让融合后 MRR 上升」互相印证
  - 正确性有两重佐证:①只留一路时该路的分路径指标**等于**融合后指标(定义上应当相等,有参数化用例守);②dense 单路 MRR 与 `calibrate_fusion_weights.py --sweep` 的「1:0 纯语义」一行**逐位相同**(两条独立实现)
- **⚠️ 给 BM25 选同义词扩展,判据是「扩展目标够不够**稀有**」,不是「够不够常见」**(同上变更,反直觉且是当次翻车的直接原因):一个词在语料里越常见,对 BM25 的判别力越低(IDF 越小)。按「缩写零信号、全称大量存在」选出的词表实测**有害** —— `manager` 占语料 **26.3%**、IDF 仅 **1.030**,而它替换掉的 `grp` IDF 是 **8.257**。扩展等于往高区分度查询里塞一个匹配四分之一语料的词,BM25 逐词求和,噪声压过真命中。按 IDF ≥ 3.0 重筛后伤害减半但**未翻转符号** —— 这份语料是 API 参考文档,sparse 的判别力集中在罕见标识符(IDF 8~10),**任何普通英文词汇的扩展都在稀释它**。**结论:同义词扩展在本语料上不适用,`query_rewrite.strategy` 保持 `none`**(能力本身已落地并可配,见 `config/synonyms.yaml` 的构建方法与 [acceptance.md](openspec/changes/archive/2026-08-25-per-route-metrics-and-synonym-rewrite/acceptance.md))
  - ⚠️ 词表若要重做,**按 IDF(语料先验统计)筛,不要按 A/B 结果筛** —— 后者在 41 条样本上就是对测试集过拟合
- **`scripts/evaluate.py` 与 `scripts/query.py` 都不写 query trace** —— 只有 MCP server 路径写 `logs/traces.jsonl`。想量某个阶段的真实耗时得写专门的基准脚本,别指望从 trace 里捞
- **跑 Python 脚本调试时务必加 `-u`** —— stdout 在管道下是全缓冲的,不加会看到空输出并误判成「进程卡死」。本项目的日志走 stderr、进度条走 stdout,两者混在一起时尤其容易误判
- **Image Handling**: Images extracted from PDFs are captioned using Vision LLM and stored separately. 自 feature-002 起，查询命中含图 chunk 时，`query_knowledge_hub` 工具会通过 `MultimodalAssembler` 同时返回文本与图片（MCP `ImageContent`，base64），两种模式（`use_llm=true/false`）策略一致。返图数量上限由 `query.max_images_per_response` 配置（默认 10）

## Evaluation System

Supports pluggable evaluators (Ragas, custom metrics). Evaluations run against golden test sets in `tests/fixtures/`:`golden_test_set.json` 是 4 条的 US1 占位集(**不加 `--lang` 时跑的就是它**),真金标是 `golden_test_sets_by_lang` 指向的 **`golden_test_set_{zh,en}_v2.json`**(`pooled-llm-judged`,2026-08-24 起生效)。第一代 `golden_test_set_{zh,en}.json` 保留作历史参照。

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
- `scripts/backfill_chunk_ids.py --input <golden> --collection <c>` — **`dense-top-k`(第一代)**回填(纯 dense top-5;保留作历史可复现,新金标不要用)
- `scripts/label_golden_chunks.py --input <golden> --output <out_v2.json> --collection <c>` — **`pooled-llm-judged`(第二代)**标注(多路池化 + LLM 分级判定)。`--dry-run` 只池化不判定(零成本);`--export-sample N` / `--import-sample <f>` 做人工抽检

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

**尚未立项的待办**(收尾项、待拍板决策、路线图上还没开 change 的能力)整理在 [openspec/BACKLOG.md](openspec/BACKLOG.md),按价值分梯队,含事实速查表。它不是 OpenSpec 产物,`openspec list` 看不到它。**这里只放指针,状态一律以该文件为准** —— 上一个块就是因为在 CLAUDE.md 里维护状态而变陈旧的。

最后一个 Spec-Kit feature 是 **005-weighted-fusion**(带权重的结果融合),已完成并冻结在 [specs/005-weighted-fusion/](specs/005-weighted-fusion/)。

> ⚠️ **本项目所有脚本与测试必须在 `.venv` 下运行**。全局 Python 的 protobuf 是 5.29.3,`import chromadb` 会失败;`.venv` 里是 3.20.3。

> 注:本项目不为单个变更开 git 分支,一律沿用 `dev-from-clean-start`。
