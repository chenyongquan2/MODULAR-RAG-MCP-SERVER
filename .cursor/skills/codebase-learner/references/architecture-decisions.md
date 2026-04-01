# 架构决策说明 (Architecture Decisions)

本文档记录了项目中的关键架构决策及其原因。

---

## ADR-001: 可插拔架构

### 决策
所有核心组件（LLM、Embedding、Splitter、VectorStore、Reranker、Evaluator）采用可插拔设计。

### 原因
1. **灵活性**: 不同场景需要不同的提供者（如成本、性能、隐私考量）
2. **可测试性**: 可以轻松替换为 Mock 实现进行测试
3. **可扩展性**: 添加新提供者无需修改核心代码
4. **配置驱动**: 用户通过配置文件切换，无需改代码

### 实现
- 每个组件有 `base_xxx.py` 定义抽象接口
- 每个提供者独立文件实现接口
- `xxx_factory.py` 负责创建实例
- `settings.yaml` 控制使用哪个提供者

### 示例
```python
# 切换 LLM 只需改配置
llm:
  provider: openai  # 从 glm 切换到 openai
```

---

## ADR-002: 工厂模式 + 注册表

### 决策
使用工厂模式配合注册表创建组件实例。

### 原因
1. **解耦**: 调用者不需要知道具体实现类
2. **延迟加载**: 只在需要时创建实例
3. **自动发现**: 新提供者只需注册，无需修改工厂代码

### 实现
```python
class LLMFactory:
    _providers = {}  # 注册表

    @classmethod
    def register_provider(cls, name: str, provider_class):
        cls._providers[name] = provider_class

    @classmethod
    def create(cls, settings) -> BaseLLM:
        provider = settings.llm.provider
        return cls._providers[provider](settings)
```

---

## ADR-003: 混合检索策略

### 决策
同时使用稠密检索（Dense）和稀疏检索（Sparse），通过 RRF 融合结果。

### 原因
1. **互补性**:
   - 稠密检索擅长语义理解（"如何优化性能" → 找到 "性能调优指南"）
   - 稀疏检索擅长精确匹配（"GLM-4" → 找到包含 "GLM-4" 的文档）
2. **鲁棒性**: 单一检索可能遗漏相关结果
3. **业界实践**: 混合检索已成为 RAG 系统的标准做法

### 实现
```
Query → DenseRetriever → dense_results
     → SparseRetriever → sparse_results
     → RRF Fusion → fused_results
     → Reranker → final_results
```

---

## ADR-004: 显式追踪上下文

### 决策
使用显式传递的 `TraceContext` 对象，而非线程本地存储。

### 原因
1. **透明性**: 追踪上下文在函数签名中可见
2. **可测试性**: 测试中可以轻松创建和传递追踪上下文
3. **避免隐式状态**: 线程本地存储可能导致意外的状态共享
4. **异步友好**: 在异步代码中更可靠

### 实现
```python
def process_query(query: str, trace: TraceContext) -> Result:
    with trace.stage("dense_retrieval"):
        results = dense_retriever.search(query)
    return results
```

---

## ADR-005: YAML 配置 + 环境变量

### 决策
使用 YAML 作为主配置格式，支持环境变量替换。

### 原因
1. **可读性**: YAML 比 JSON 更易读，支持注释
2. **安全性**: 敏感信息（API Key）通过环境变量注入
3. **灵活性**: 支持不同环境（开发、测试、生产）使用不同配置

### 实现
```yaml
# settings.yaml
llm:
  api_key: ${OPENAI_API_KEY}  # 从环境变量读取
```

---

## ADR-006: 结构化日志到 stderr

### 决策
所有日志输出到 stderr，不污染 stdout。

### 原因
1. **MCP 协议要求**: MCP 使用 stdout 进行协议通信，日志不能干扰
2. **可重定向**: stdout 和 stderr 可以分别重定向
3. **调试友好**: 日志和输出分离，便于问题排查

### 实现
```python
# observability/logger.py
import sys

def get_logger(name: str):
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stderr)  # 输出到 stderr
    logger.addHandler(handler)
    return logger
```

---

## ADR-007: JSONL 追踪日志

### 决策
追踪日志使用 JSONL 格式（每行一个 JSON 对象）。

### 原因
1. **流式处理**: 可以逐行读取和处理，无需加载整个文件
2. **追加友好**: 新日志直接追加，无需修改文件结构
3. **工具支持**: 可以使用 `jq` 等工具快速查询
4. **Dashboard 友好**: Streamlit 可以逐行解析并可视化

### 实现
```python
# 每行一个 JSON 对象
{"trace_type": "query", "query": "...", "latency": 1.5, ...}
{"trace_type": "ingestion", "doc_id": "...", "chunks": 10, ...}
```

---

## ADR-008: 分层测试策略

### 决策
测试分为三层：单元测试、集成测试、端到端测试。

### 原因
1. **速度**: 单元测试快速反馈，集成测试验证集成，E2E 验证完整流程
2. **隔离**: 单元测试不依赖外部服务，集成测试可以
3. **成本**: 单元测试免费运行，集成测试可能消耗 API 配额

### 实现
```python
@pytest.mark.unit
def test_llm_factory():
    # 快速，无外部依赖
    pass

@pytest.mark.integration
def test_openai_embedding():
    # 需要 API Key，调用真实服务
    pass

@pytest.mark.e2e
def test_full_pipeline():
    # 完整流程测试
    pass
```

---

## ADR-009: 类型提示优先

### 决策
所有公共 API 必须有类型提示。

### 原因
1. **IDE 支持**: 更好的自动补全和类型检查
2. **文档作用**: 类型提示即文档
3. **重构安全**: 修改代码时编译器会提示类型错误
4. **代码质量**: 强制思考数据流和接口设计

### 实现
```python
def search(
    query: str,
    top_k: int = 10,
    filters: dict[str, str] | None = None
) -> list[SearchResult]:
    ...
```

---

## ADR-010: 单一数据源原则

### 决策
DEV_SPEC.md 是任务进度的唯一数据源，其他文件由脚本自动生成。

### 原因
1. **一致性**: 避免多个文件之间的同步问题
2. **可追溯**: 所有修改都在一个文件中
3. **自动化**: 减少手动同步错误

### 实现
```
DEV_SPEC.md (手动编辑)
    ↓
sync_all_skills.py (自动同步)
    ↓
specs/06-schedule.md (自动生成，禁止手动编辑)
```

---

## 决策模板

记录新决策时使用以下模板：

```markdown
## ADR-XXX: [决策标题]

### 决策
[简述决策内容]

### 原因
1. [原因1]
2. [原因2]
3. [原因3]

### 实现
[代码示例或实现说明]

### 后果
[决策带来的影响，包括正面和负面]
```
