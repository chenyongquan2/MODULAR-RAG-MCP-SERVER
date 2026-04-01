# 术语表 (Glossary)

## 核心概念

### RAG (Retrieval-Augmented Generation)
检索增强生成。一种结合信息检索和文本生成的AI技术，先从知识库检索相关文档，再基于检索结果生成回答。

### MCP (Model Context Protocol)
模型上下文协议。一种标准化的协议，让AI模型能够与外部工具和数据源交互。

### Dense Retrieval (稠密检索)
使用向量嵌入进行语义相似度搜索。将文本转换为高维向量，通过向量距离找到语义相关的文档。

### Sparse Retrieval (稀疏检索)
使用关键词匹配进行检索，如 BM25。基于词频和逆文档频率计算相关性。

### Hybrid Search (混合搜索)
结合稠密检索和稀疏检索的结果，通过融合算法（如 RRF）得到最终结果。

### RRF (Reciprocal Rank Fusion)
倒数排名融合。一种将多个检索结果列表合并的算法，基于排名位置计算分数。

### Reranking (重排序)
对检索结果进行二次排序，使用更精确的模型（如 Cross-Encoder）重新计算相关性分数。

## 架构术语

### Factory Pattern (工厂模式)
一种创建型设计模式，提供创建对象的接口，由子类决定实例化哪个类。

### Strategy Pattern (策略模式)
一种行为型设计模式，定义一系列算法，让它们可以互相替换。

### Provider (提供者)
在本项目中，指可插拔的组件实现，如 LLM Provider、Embedding Provider。

### Pluggable Architecture (可插拔架构)
一种软件架构，允许在不修改核心代码的情况下添加或替换组件。

## 数据结构

### Document (文档)
原始输入文档，包含内容和元数据。

### Chunk (文本块)
文档分割后的片段，是检索和嵌入的基本单位。

### Embedding (嵌入)
文本的向量表示，用于语义搜索。

### Vector Store (向量数据库)
存储向量嵌入并支持相似度搜索的数据库，本项目使用 ChromaDB。

### BM25 Index (BM25 索引)
用于关键词检索的倒排索引。

## 流程术语

### Ingestion (导入)
将文档加载、分割、嵌入并存储到数据库的过程。

### Query (查询)
用户提问，系统检索相关文档并生成回答的过程。

### Trace (追踪)
记录系统执行过程的日志，用于调试和分析。

## 配置术语

### Settings (设置)
系统配置，定义在 `config/settings.yaml` 中。

### Environment Variable (环境变量)
系统环境中的变量，用于存储敏感信息如 API Key。

## 测试术语

### Unit Test (单元测试)
测试单个函数或类的行为，不依赖外部服务。

### Integration Test (集成测试)
测试多个组件协作的行为，可能依赖外部服务。

### E2E Test (端到端测试)
测试完整系统流程，从输入到输出。

### Mock (模拟)
在测试中替代真实对象的假对象。

## LLM 相关

### Prompt (提示词)
发送给 LLM 的输入文本。

### Context Window (上下文窗口)
LLM 能处理的最大 token 数量。

### Temperature (温度)
控制 LLM 输出随机性的参数，值越高输出越随机。

### Token (词元)
LLM 处理文本的基本单位，通常一个 token 约等于 4 个英文字符或 0.75 个单词。
