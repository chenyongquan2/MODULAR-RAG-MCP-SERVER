# 快速参考 (Cheat Sheet)

## 常用命令

### 环境设置
```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
.\.venv\Scripts\activate   # Windows PowerShell

# 安装依赖
pip install -e .           # 基础安装
pip install -e ".[dev]"    # 包含开发依赖
```

### 运行系统
```bash
# 启动 MCP 服务器
python main.py

# 导入文档
python scripts/ingest.py --path ./documents/ --force

# 查询测试
python scripts/query.py --query "你的问题" --top-k 10

# 启动管理面板
python scripts/start_dashboard.py
```

### 测试
```bash
# 运行单元测试
pytest tests/unit -v

# 运行集成测试
pytest tests/integration -v

# 运行所有测试
pytest -v

# 带覆盖率
pytest --cov=src tests/unit

# 运行单个测试文件
pytest tests/unit/test_llm_factory.py -v

# 运行单个测试
pytest tests/unit/test_llm_factory.py::test_factory_creation -v
```

### Git 操作
```bash
# 查看状态
git status

# 查看差异
git diff

# 提交代码
git add .
git commit -m "feat(module): [TaskID] description"

# 推送到远程
git push origin <branch>
```

## 配置速查

### settings.yaml 结构
```yaml
# LLM 配置
llm:
  provider: glm          # glm | openai | azure | ollama | deepseek
  model: glm-4
  api_key: ${GLM_API_KEY}

# Embedding 配置
embedding:
  provider: bge          # bge | openai | azure | ollama | glm
  model: bge-m3
  api_key: ${BGE_API_KEY}

# 分割器配置
splitter:
  strategy: recursive    # recursive | semantic | fixed
  chunk_size: 512
  chunk_overlap: 50

# 重排序配置
rerank:
  backend: cross_encoder # none | cross_encoder | llm

# 向量数据库配置
vector_store:
  backend: chroma
  persist_directory: ./data/db
```

### 环境变量
```bash
# Linux/Mac
export GLM_API_KEY="your-key"
export OPENAI_API_KEY="your-key"

# Windows PowerShell
$env:GLM_API_KEY="your-key"
$env:OPENAI_API_KEY="your-key"

# Windows CMD
set GLM_API_KEY=your-key
```

## 代码模式

### 添加新的 LLM 提供者
```python
# 1. 创建 src/libs/llm/new_llm.py
from .base_llm import BaseLLM

class NewLLM(BaseLLM):
    def __init__(self, settings, **kwargs):
        self.settings = settings
        # 初始化客户端

    def generate(self, prompt: str, **kwargs) -> str:
        # 实现生成逻辑
        pass

    def get_model_name(self) -> str:
        return self.settings.llm.model

# 2. 在 llm_factory.py 注册
from .new_llm import NewLLM
LLMFactory.register_provider("new", NewLLM)

# 3. 更新 settings.yaml
llm:
  provider: new
```

### 添加新的 Embedding 提供者
```python
# 1. 创建 src/libs/embedding/new_embedding.py
from .base_embedding import BaseEmbedding

class NewEmbedding(BaseEmbedding):
    def __init__(self, settings, **kwargs):
        self.settings = settings

    def encode(self, texts: list[str]) -> list[list[float]]:
        # 实现编码逻辑
        pass

    def get_dimension(self) -> int:
        return 1024  # 向量维度

# 2. 在 embedding_factory.py 注册
from .new_embedding import NewEmbedding
EmbeddingFactory.register_provider("new", NewEmbedding)

# 3. 更新 settings.yaml
embedding:
  provider: new
```

### 编写单元测试
```python
import pytest
from unittest.mock import Mock, patch

@pytest.mark.unit
def test_llm_generate():
    """测试 LLM 生成功能"""
    # Arrange
    mock_settings = Mock()
    mock_settings.llm.model = "test-model"

    # Act
    llm = SomeLLM(mock_settings)
    result = llm.generate("test prompt")

    # Assert
    assert isinstance(result, str)
    assert len(result) > 0
```

## 文件位置速查

| 内容 | 位置 |
|------|------|
| 项目说明 | `CLAUDE.md`, `README.md` |
| 主配置 | `config/settings.yaml` |
| 提示词模板 | `config/prompts/` |
| 核心类型定义 | `src/core/types.py` |
| 配置数据类 | `src/core/settings.py` |
| LLM 实现 | `src/libs/llm/` |
| Embedding 实现 | `src/libs/embedding/` |
| 向量存储 | `src/libs/vector_store/` |
| 导入管道 | `src/ingestion/pipeline.py` |
| 查询引擎 | `src/core/query_engine/` |
| MCP 工具 | `src/mcp_server/tools/` |
| 单元测试 | `tests/unit/` |
| 集成测试 | `tests/integration/` |
| 测试数据 | `tests/fixtures/` |
| 运行数据 | `data/` |
| 日志文件 | `logs/` |

## 调试技巧

### 查看日志
```bash
# 查看最近的追踪日志
tail -100 logs/traces.jsonl

# 过滤查询日志
cat logs/traces.jsonl | grep '"trace_type": "query"'

# 过滤导入日志
cat logs/traces.jsonl | grep '"trace_type": "ingestion"'
```

### 常见问题排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| ImportError | 虚拟环境未激活 | 运行 `.\.venv\Scripts\activate` |
| API Key 错误 | 环境变量未设置 | 设置对应的环境变量 |
| 模块找不到 | 未安装依赖 | 运行 `pip install -e .` |
| 向量库错误 | 数据目录不存在 | 创建 `data/db/` 目录 |
| 测试失败 | 依赖服务未启动 | 检查 ChromaDB 等服务 |

### 添加调试日志
```python
from observability.logger import get_logger

logger = get_logger(__name__)

def some_function():
    logger.debug("调试信息")
    logger.info("一般信息")
    logger.warning("警告信息")
    logger.error("错误信息")
```

## 提交信息规范

```
<type>(<scope>): [<TaskID>] <description>
```

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `test` | 测试相关 |
| `refactor` | 代码重构 |
| `perf` | 性能优化 |
| `chore` | 构建/工具 |

示例:
```
feat(llm): [B7.2] implement Ollama LLM provider
fix(reranker): [B5.1] handle empty query gracefully
docs(readme): [A1] update installation guide
```
