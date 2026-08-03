# 重排（Rerank）与 Cross-Encoder 学习笔记

> **记录日期**：2026-08-03
> **关联代码**：`src/libs/reranker/`、`src/core/query_engine/reranker.py`、`config/settings.yaml`
> **本机环境快照**：见 [§7.1](#71-环境硬约束实测) 与 [§9](#9-部署条件核验实测)

## 置信度标注约定

本文所有数据都标注来源，避免把估算当事实：

| 标注 | 含义 |
|---|---|
| **【实测】** | 在本机实际运行命令验证过，2026-08-03 |
| **【文献】** | 来自官方文档/论文，高置信但请以最新版为准 |
| **【推算】** | 按参数量/层数估算，**未实测，可能偏差 2–3 倍** |
| **【代码】** | 从本仓库源码直接读出，附文件行号 |

---

## 目录

1. [先分清三个概念的层级](#1-先分清三个概念的层级)
2. [核心原理：Bi-Encoder vs Cross-Encoder](#2-核心原理bi-encoder-vs-cross-encoder)
3. [工程细节与踩坑点](#3-工程细节与踩坑点)
4. [sentence-transformers 是什么](#4-sentence-transformers-是什么)
5. [Cohere 是什么](#5-cohere-是什么)
6. [本项目现状核验](#6-本项目现状核验)
7. [模型选项分析](#7-模型选项分析)
8. [本地 vs 线上：决策与理由](#8-本地-vs-线上决策与理由)
9. [部署条件核验](#9-部署条件核验实测)
10. [结论与待办](#10-结论与待办)
11. [附录：术语表](#附录术语表)

---

## 1. 先分清三个概念的层级

最初的困惑是「我项目的 cross-encoder 是不是 cohere」。这个问题本身包含一个层级混淆——三个词根本不在同一维度：

| 名词 | 概念层级 | 类比 |
|---|---|---|
| **Cross-Encoder** | 一种**神经网络架构 / 打分方法** | 「内燃机」 |
| **sentence-transformers** | 一个**开源 Python 库**，提供该架构的实现 | 「某牌子的发动机厂」 |
| **Cohere** | 一家**AI 公司**，卖托管 Rerank API（内部也是 cross-encoder 类模型，但闭源） | 「买整车服务，不给看引擎」 |

所以「cross-encoder 是不是 cohere」≈「内燃机是不是丰田」。

**本项目答案**【代码】：用的是 sentence-transformers 这个开源库的**本地实现**，与 Cohere 无关。仓库里唯一的 `cohere` 字样在 `DEV_SPEC.md:92`，是"未来可能支持云端服务"的设计愿景，**从未实现**。

---

## 2. 核心原理：Bi-Encoder vs Cross-Encoder

理解 Cross-Encoder 必须先理解它在对抗什么。RAG 里有两种给「query 与文档相关性」打分的方式。

### 2.1 Bi-Encoder（双塔）——本项目的 embedding 就是它

```
  query "如何配置 RRF"          文档 chunk_042
         │                            │
    ┌────▼────┐                  ┌────▼────┐
    │ Encoder │                  │ Encoder │   ← 两次独立前向传播
    └────┬────┘                  └────┬────┘      彼此看不见对方
         │                            │
    [1536 维向量]              [1536 维向量]   ← 可离线算好、存进 Chroma
         └──────────┬─────────────────┘
              cosine 相似度  →  0.83
```

**关键性质**：文档侧向量与 query 无关，因此能在灌库时一次算完并建 ANN 索引。查询时只编码 query。

本项目对应：`text-embedding-ada-002`（1536 维）+ ChromaDB。

**代价**：query 与文档的**唯一交互点是最后那个点积**。整篇文档的语义被压缩成 1536 个数字，而压缩时并不知道将来会有什么 query。信息瓶颈极窄。

### 2.2 Cross-Encoder（交叉编码 / 单塔）

```
  "如何配置 RRF"  +  chunk_042 全文
         └────────┬────────┘
                  │  拼成一条序列：
       [CLS] 如何配置RRF [SEP] rrf_k 是 RRF 融合的平滑常数… [SEP]
                  │
         ┌────────▼────────┐
         │   Transformer   │  ← query 每个 token 都能 attend 到
         │  (full self-    │     文档每个 token，反之亦然，逐层交互
         │   attention)    │
         └────────┬────────┘
                  │
             [CLS] 向量  →  线性分类头  →  一个标量 8.42 (logit)
```

**关键性质**：query 与文档在模型内部**每一层做 token 级交互**。能捕捉 bi-encoder 结构上不可能捕捉的东西：

- **精确术语匹配**：query 问 `rrf_k`，文档里是 `rrf_k` 还是 `dense_top_k`，attention 直接对齐
- **否定与限定**：「不支持 Qdrant」vs「支持 Qdrant」——两者 embedding 余弦相似度通常 >0.95，bi-encoder 几乎分不开，cross-encoder 能分
- **多跳条件**：query 含两个约束（「Azure 下的 embedding 维度」），能验证文档是否同时满足
- **按需聚焦**：长文档时可只看与当前 query 相关的几句，而非被迫平均整篇

### 2.3 为什么 Cross-Encoder 不能用于检索

因为它**没有可预计算的文档表示**。分数 `f(query, doc)` 不可分解——无法把「文档那部分」先算好。

| | Bi-Encoder | Cross-Encoder |
|---|---|---|
| 灌库时能预计算 | ✅ 文档向量 | ❌ 什么都算不了 |
| 查一次的前向传播次数 | 1（只编码 query） | **N**（每个候选一次） |
| 能建 ANN 索引 | ✅ HNSW / IVF | ❌ 不存在"索引" |
| 10 万文档检索耗时 | ~10 ms | ~小时级 |
| 10 个候选打分耗时 | — | ~0.1 秒 |

本项目 Chroma 里约 **5.2 万个 chunk**【实测，由 `length.bin` 210320 B ÷ 4 推算】。用 cross-encoder 直接检索意味着每次查询跑 5.2 万次前向传播——物理上不可行。

### 2.4 两阶段检索范式（retrieve-then-rerank）

上述矛盾正是这个范式存在的**全部原因**：

```
第一阶段 · 召回（要快、要全，允许不准）
  Bi-Encoder + BM25  →  从 5.2 万里捞出 10~100 个候选
                         ↓
第二阶段 · 重排（要准，只处理少量）
  Cross-Encoder      →  给候选精细打分，取 Top 5
```

用便宜模型做**广度筛选**，用昂贵模型做**深度精排**。经典漏斗式级联架构。

---

## 3. 工程细节与踩坑点

### 3.1 输出是 logit，不是概率，不可跨 query 比较

`ms-marco-MiniLM-L-6-v2` 由二分类训练，输出未归一化的 logit，实测范围约 **-11 ~ +11**【文献】。

- 想变成"相关概率"：套 `sigmoid()`
- ⚠️ **绝对不要跨 query 设阈值**（如"分数 <0 就丢弃"）。同一 query 内的相对排序可靠，**不同 query 之间的分数尺度不可比**

本项目只用它做降序排序（`cross_encoder_reranker.py:260`）【代码】，用法正确。

### 3.2 512 token 硬截断

这类模型输入上限 512 token，`query + 文档` 合计。超出即截断，默认 `longest_first` 策略——**被砍掉的是文档尾部**，**静默发生，不报错不警告**。

本项目 `chunk_size: 1000`（**字符**，见 `recursive_splitter.py:34`）【代码】：

| 语料 | 1000 字符 ≈ | 是否截断 |
|---|---|---|
| 英文 | ~250 token | ✅ 安全 |
| **中文** | ~1000+ token | ⚠️ **砍掉约一半** |

### 3.3 批处理是性能关键

`model.predict(pairs)` 内部默认 `batch_size=32`，把所有 pair 打包成批。本项目一次性传入全部 pair（`cross_encoder_reranker.py:222`）【代码】，正确——逐条循环会慢一个数量级。

### 3.4 模型命名解剖

```
cross-encoder / ms-marco - MiniLM - L-6 - v2
      │             │         │       │     │
      │             │         │       │     └─ 第 2 版
      │             │         │       └─────── 6 层 Transformer
      │             │         └─────────────── MiniLM 骨干（知识蒸馏小模型，
      │             │                          hidden=384，约 2270 万参数）
      │             └───────────────────────── 在 MS MARCO 上微调
      │                                        （Bing 真实搜索日志，53 万英文 query）
      └─────────────────────────────────────── HuggingFace 组织名，归 SBERT 项目
```

**层数就是精度/延迟的旋钮**。同系列还有 L-12、L-4、L-2、TinyBERT-L-2。

### 3.5 参数量 ≠ 算力（重要）

`bge-reranker-base` 号称 2.78 亿参数，听起来吓人。拆开看：

```
词表 embedding   250,002 × 768  = 192.0 M   ← 占 69%！（XLM-R 多语言词表）
位置 embedding       514 × 768  =   0.4 M
12 层 Transformer               =  84.9 M   ← 只占 31%
─────────────────────────────────────────
总计                            ≈ 278 M
```

**那 192 M 的 embedding 表只是一张查找表——占内存，几乎不占算力**（O(1) 内存读取，不是矩阵乘法）。

真实对比：

| | 内存占用 | **实际算力** |
|---|---|---|
| `ms-marco-MiniLM-L-6-v2` | 22 M 参数 | 6 层 × 384 维 |
| `bge-reranker-base` | 278 M 参数（**12.2×**） | 12 层 × 768 维 = **8.0×** |

算力比 = 层数 2× × 隐层维度² 4× = 8×（自注意力与 FFN 的 FLOPs 随 `d_model²` 增长）。

**结论：内存涨 12 倍（有 32 GB，无痛），算力只涨 8 倍——后者才是真实代价，体现为延迟。**

---

## 4. sentence-transformers 是什么

**一个开源 Python 库**，学术界通称 **SBERT**。

- **出身**：2019 EMNLP 论文 *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks*，Nils Reimers 等，德国达姆施塔特工大 UKP Lab。现由 Hugging Face 维护
- **本质**：`transformers` + PyTorch 之上的高阶封装。原始 `transformers` 要手写 tokenize / pooling / pad / batch，SBERT 收敛成两三行
- **同时提供两种架构的实现**，这点很有教学价值：

```python
from sentence_transformers import SentenceTransformer, CrossEncoder

# Bi-Encoder：产出向量，可入库
bi = SentenceTransformer("BAAI/bge-small-zh-v1.5")
vecs = bi.encode(["文档1", "文档2"])          # → (2, 384) 矩阵

# Cross-Encoder：产出分数，不可入库  ← 本项目用的这个
ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
scores = ce.predict([("query", "文档1"), ("query", "文档2")])  # → [8.4, -2.1]
```

- **模型来源**：`CrossEncoder("名字")` 从 HuggingFace Hub 下载权重，缓存在 `~/.cache/huggingface/`。首次联网，之后完全离线
- **在本项目的角色**：纯本地推理引擎。零 API key、零网络调用、零按次费用

---

## 5. Cohere 是什么

**一家公司**，不是一种技术。

- 加拿大 AI 公司，2019 年成立。联合创始人 Aidan Gomez 是 Transformer 原始论文 *Attention Is All You Need* 的共同作者之一
- 定位：面向企业的 LLM 服务商。三条产品线——**Command**（对话模型）、**Embed**（向量模型）、**Rerank**（重排 API）
- **Cohere Rerank** 把重排包成 HTTP 接口：

```python
import cohere
co = cohere.Client("your-api-key")
res = co.rerank(query="如何配置 RRF", documents=[...], top_n=5, model="rerank-v3.5")
```

- 模型内部结构未公开，业界普遍认为是 cross-encoder 或 late-interaction 类架构的改良版。**只能拿到分数，看不到也改不了模型**
- 计费按 "search unit"（1 unit ≈ 1 query + 最多 100 文档）。单价请查 <https://cohere.com/pricing>
- **文档内容要出网**发到 Cohere 服务器——企业内部知识库场景常是硬性否决项

---

## 6. 本项目现状核验

### 6.1 pipeline 中的位置

串起配置看（`config/settings.yaml:60-73`）【代码】：

```
用户 query
    │
    ├─ 稠密检索  dense_top_k: 20   （ada-002 + Chroma，bi-encoder）
    └─ 稀疏检索  sparse_top_k: 20   （BM25 关键词）
             │
             ▼
        RRF 融合  rrf_k: 60  →  fusion_top_k: 10   ← 漏斗第一层出口
             │
             ▼
      Cross-Encoder 重排  →  top_k: 5              ← 漏斗第二层出口
             │
             ▼
        塞进 LLM prompt 作为上下文
```

MCP 工具侧另有一处过量召回：`initial_top_k = top_k * 2`（`query_knowledge_hub.py:341`），默认 top_k=5 → 召回 10 个送进重排。

漏斗比例（20+20 → 10 → 5）设计合理。

### 6.2 能力成熟度分层核验

「是否具备 cross-encoder 能力」不是布尔值。逐层核验：

| # | 层级 | 状态 | 证据 |
|---|---|---|---|
| 1 | 抽象接口 | ✅ | `BaseReranker` 定义 `rerank()` + `validate_*` |
| 2 | 实现代码 | ✅ | `cross_encoder_reranker.py` 289 行，pair 构造→批量打分→附分排序 |
| 3 | 工厂注册 | ✅ | `reranker_factory.py:84-86` 懒注册 `"cross_encoder"` |
| 4 | Core 层编排 | ✅ | `CoreReranker` 类型转换 + 降级 + 计时 |
| 5 | Pipeline 接线 | ✅ | `query_knowledge_hub.py:283` 真实调用 |
| 6 | 可观测性 | ✅ | `reranker.py:305` 写 trace stage，dashboard 有详情页 |
| 7 | 配置 schema | ✅ | `RerankSettings(enabled/provider/model/top_k)`（`settings.py:135`） |
| 8 | 单元测试 | ⚠️ | `test_cross_encoder_reranker.py` 存在，但**全部注入 `MockCrossEncoder` 或 patch `_load_cross_encoder_model`**（:114）——零测试触碰真实模型 |
| 9 | **依赖声明** | ❌ | `pyproject.toml` 搜 `sentence`/`transformers`/`torch` **零命中** |
| 10 | **依赖安装** | ❌ | `import sentence_transformers` → `No module named`【实测】 |
| 11 | **配置开启** | ❌ | `enabled: false`，`provider: "none"` |
| 12 | **真实模型跑通** | ❌ | 综合 9/10/11 → **不可能发生过** |
| 13 | 模型-语料匹配 | ❌ | 英文 MS MARCO 模型 vs 中英双语 MT5 语料 |
| 14 | 效果验证 | ❌ | 无 A/B、无基线数据 |

**结论：代码能力完备，运行能力为零。这是一个已完成实现但从未激活、也从未验证过的功能分支。**

第 9 层是根因：依赖从未被声明，意味着**任何一次干净安装（`pip install -e .`）都不可能装上 sentence-transformers**。修复时必须同时改 `pyproject.toml`，光装不声明等于没修。

第 8 层的性质要说清：单测用 mock **本身不是缺陷**（单测就该快、确定、隔离外部下载），`MockCrossEncoder` 设计是对的。但客观后果是**测试套件对第 9/10 层完全无感**——CI 全绿，同时 cross-encoder 一次没真跑过。`tests/integration/` 下只有 `test_reranker_llm.py`，**没有 cross-encoder 集成测试**。

### 6.3 静默失败链（重要风险）

若现在把配置改成 `enabled: true` + `provider: cross_encoder`：

```
_load_cross_encoder_model()      → ImportError: sentence-transformers is required
  ↓ 被包装
CrossEncoderReranker.__init__    → CrossEncoderRerankError
  ↓ 被包装
RerankerFactory.create()         → RuntimeError
  ↓ 被 catch
CoreReranker.__init__            → logger.warning(...) + 退回 NoneReranker
                                   (reranker.py:124-126)
```

**系统正常返回结果，不报错不中断。唯一信号是一行 WARNING 日志。**

好消息是这个静默失败**在 trace 上可见**：降级后 `is_enabled` 为 False，`_apply_rerank` 在 `query_knowledge_hub.py:374` 提前 return，**根本不会写入 rerank stage**。

⚠️ 区分两种"重排没生效"，trace 表现不同：

| 情况 | trace 表现 |
|---|---|
| 依赖缺失 / 初始化失败 | **没有** rerank stage |
| 运行时打分失败 | 有 rerank stage，metadata 带 `rerank_fallback: True`（`reranker.py:342`） |

### 6.4 已知隐患：timeout 是死代码

- `CrossEncoderReranker.__init__` 存了 `self.timeout`，但 `_score_pairs()` 里**没有任何超时检查**
- `CoreReranker.config.timeout`（默认 30.0）也**从未被使用**
- `RerankSettings` 甚至没有 `timeout` 字段，`getattr` 永远取默认值

**后果：选重模型时没有超时兜底，慢查询会一直阻塞。** 若上本地重排，建议一并补上。

### 6.5 值得肯定的设计

- **降级语义正确**：重排失败自动回退原始顺序而非抛错（`reranker.py:328-352`），并把 `rerank_fallback: True` 写进 metadata 留痕。重排是**质量增强**而非**功能必需**，这个语义是对的
- **插件化到位**：三个 provider（`none`/`cross_encoder`/`llm`）共存，改一行配置切换，为 A/B 对比提供了基础设施

---

## 7. 模型选项分析

### 7.1 环境硬约束【实测】

> 探测日期 2026-08-03，本机 Windows 11

| 约束 | 实测值 | 影响 |
|---|---|---|
| **算力** | `torch 2.12.0+cpu`，`cuda_available=False` | **纯 CPU 推理**。最强约束 |
| GPU | AMD Radeon 780M（核显） | Windows 无可用 PyTorch 后端（ROCm 不支持 Windows，780M 不在支持列表）。**指望不上** |
| CPU | Ryzen 7 7840HS，8 核 16 线程，Zen 4 | 支持 AVX-512 + VNNI，对 fp32 矩阵乘有利 |
| Python | 3.12.1 AMD64 | ✅ |
| transformers | **5.8.1**（v5 大版本） | 曾担心 ST 会降级它，已排除，见 §9 |
| sentence-transformers | **未安装** | 见 §6.2 第 10 层 |
| **语料语言** | `mt5_docs_chinese.json` 39 MB + `mt5_docs_english.json` 53 MB | **中英双语各占一半**。多语言是硬需求，非优化项 |
| 语料规模 | 约 **5.2 万 chunk** | 召回压力大，但重排只处理 10 个 |
| 语料领域 | MetaTrader 5 平台技术文档 | 强垂直领域，与通用网页搜索差异大 |

**代码层面的加载约束**【代码】：

```python
model = CrossEncoder(model_name)     # cross_encoder_reranker.py:117 — 零 kwargs
```

- 不能传 `trust_remote_code` → 需自定义代码的模型**直接报错**
- 不能传 `device` / `max_length` / `batch_size`
- `RerankSettings` 是 frozen dataclass，只有 4 个字段，加参数要改 schema

### 7.2 候选模型矩阵

#### A 组：MS MARCO 英文系列（当前配置所在）

| 模型 | 层数/参数 | TREC-DL19 NDCG@10【文献】 | V100 吞吐【文献】 | CPU 10 候选【推算】 |
|---|---|---|---|---|
| `ms-marco-TinyBERT-L-2-v2` | 2 / ~4.4M | ~69.8 | ~9000/s | ~0.05 s |
| `ms-marco-MiniLM-L-2-v2` | 2 / ~16M | ~71.0 | ~4100/s | ~0.1 s |
| `ms-marco-MiniLM-L-4-v2` | 4 / ~19M | ~73.0 | ~2500/s | ~0.2 s |
| **`ms-marco-MiniLM-L-6-v2`** ← 当前 | 6 / ~23M | ~74.3 | ~1800/s | ~0.3 s |
| `ms-marco-MiniLM-L-12-v2` | 12 / ~33M | ~74.3 | ~960/s | ~0.6 s |

（数据来自 SBERT 官方 Pretrained Cross-Encoders 页面）

**值得记住的结论**：L-12 的 NDCG@10 与 L-6 基本相同（74.31 vs 74.30），速度只有一半。**加层数在这条曲线上已经饱和**——L-6 是该系列的性价比拐点。

**但整组对本项目不适用**，理由不是精度渐进差，而是两重一票否决：

1. **语言**：训练数据是 53 万条英文 Bing query，骨干是英文 uncased 词表。中文语料（占一半）喂进去，输出**看似合理但接近随机的排序**
2. **领域**：MS MARCO 是通用网页搜索意图；本项目是 MT5 平台 API/配置文档，存在明显领域偏移

第 1 点尤其危险，因为它**静默失败**——不报错、不降级，只是排序变差。

#### B 组：多语言开源 Reranker

| 模型 | 骨干/参数 | 语言 | max_len | 许可 | **本项目能直接加载?** | CPU 10 候选【推算】 |
|---|---|---|---|---|---|---|
| **`BAAI/bge-reranker-base`** | XLM-R base / ~278M | 中英 | 512 | Apache-2.0 | ✅ 标准 seq-cls | ~2–4 s |
| `BAAI/bge-reranker-large` | XLM-R large / ~560M | 中英 | 512 | Apache-2.0 | ✅ | ~6–12 s |
| `BAAI/bge-reranker-v2-m3` | BGE-M3 / ~568M | 多语言 | **8192** | Apache-2.0 | ✅ | ~8–15 s |
| `jinaai/jina-reranker-v2-base-multilingual` | ~278M | 多语言 | 长 | ⚠️ **CC-BY-NC-4.0 禁商用** | ❌ 需 `trust_remote_code=True` | ~2–4 s |
| `BAAI/bge-reranker-v2-gemma` | Gemma-2B | 多语言 | — | Gemma 许可 | ❌ 需 `FlagEmbedding` 库 | 不可用 |
| `BAAI/bge-reranker-v2-minicpm-layerwise` | MiniCPM | 多语言 | — | — | ❌ 需 `FlagEmbedding` | 不可用 |
| `Qwen/Qwen3-Reranker-0.6B` | Qwen3 / 0.6B | 多语言强 | 32K | Apache-2.0 | ⚠️ 需较新 ST 版本，**须先验证** | ~10–20 s |

> 许可与版本兼容性请以 HF 模型页为准（本文知识有截止日期）。

**筛选后真正可选集只有 3 个**：`bge-reranker-base` / `bge-reranker-large` / `bge-reranker-v2-m3`。其余要么改代码、要么许可不许、要么架构不兼容。

Jina 的 **CC-BY-NC 禁止商业使用**——若项目要写进简历甚至将来商用，这是实质性风险。

### 7.3 关键权衡：CPU 让「精度换延迟」曲线变陡

```
精度 ▲
     │                              ● v2-m3 (568M, ~10s)
     │                        ● large (560M, ~8s)
     │                 ● bge-base (278M, ~3s)   ← 唯一落在可用区的双语模型
     │
     │   ● L-6 (23M, ~0.3s)  ← 快，但中文场景无效
     │  ● L-4
     │ ● L-2
     └────────────────────────────────────────► CPU 延迟
       0.1s        1s      ┊    5s        15s
                           ┊
                    交互式可接受边界（约 2-3s）
```

**没有免费午餐**：能处理中文的最小可用模型（`bge-reranker-base`）比当前配置大 12 倍，CPU 上换成约 8 倍延迟（见 §3.5）。

**选定：`BAAI/bge-reranker-base`。** 理由不是"最好"，而是**约束交集下只剩这一个**——同时满足「支持中文 + 代码能直接加载 + Apache-2.0 + CPU 延迟勉强可接受」。

---

## 8. 本地 vs 线上：决策与理由

### 8.1 先排除两个无效论据

本地方案最常被引用的两个优势，**在本项目架构里是零**：

```
用户 query
   ↓
Azure embedding  ────────────────→ 出网（query 发给 Azure）
   ↓
Chroma + BM25 召回
   ↓
重排  ← 讨论的就是这一步
   ↓
Azure gpt-4o 生成  ──────────────→ 出网（query + 全部命中 chunk 发给 Azure）
```

- ❌ **"数据不出网"**：最后一步已把**同一批 chunk 原文**发给 Azure，重排改本地一个字节都没少
- ❌ **"离线可用"**：embedding 和生成都依赖 Azure，系统本来就不能离线

**别用这两条说服自己。**

### 8.2 真正成立的四条理由

**① 确定性 —— 对本项目是硬需求（最重）**

Cross-encoder 是纯函数：同样 `(query, chunk)` 永远得到同样分数。LLM 重排即使 `temperature: 0` 也不保证跨调用一致，还多一层输出解析（格式跑偏、截断、拒答）。

RAG 质量验收方案里，**用不确定的组件做基线，测出的 hit_rate / MRR 波动无法归因**——分不清是检索改动带来的变化，还是重排器这次心情不同。评测链路每个环节都该可复现。

**② 边际成本为零 —— 重排会被高频重复调用**

关键不在单次查询，在**评测**。一轮验收几十上百个 query，调参阶段跑几十轮。

粗算（gpt-4o 公开定价，以 Azure 实际价目为准）：LLM 重排每次查询多约 3000 input token ≈ **人民币 5–6 分/次**。一轮 100 query ≈ ¥5.5，50 轮调参 ≈ ¥275。金额不致命，但它**叠加在生成调用之上**，且会让人在"想多跑一轮实验"时产生犹豫——**评测环节的心理摩擦是真实成本**。

**③ 学习与项目纵深**

调 API vs「本地加载 2.78 亿参数模型、理解 512 截断、量测 CPU 批处理吞吐、对比 XLM-R 与 MiniLM 骨干」，技术深度不是一个量级。面试里能被追问三层的是后者。

**④ 延迟其实是平手，不是劣势**

| | 实际延迟 |
|---|---|
| 本地 `bge-reranker-base`（CPU 8 核） | ~2–4 s【推算】 |
| Azure gpt-4o 重排 | ~1–3 s（网络往返 + 生成） |

线上略快但未拉开差距。**若有 GPU，本地降到 ~50 ms 直接碾压**——这条只是"当前平手"，不是固有短板。

### 8.3 四条路线完整对比（按本机真实环境）

| 方案 | 延迟 | 金钱成本 | 中文能力 | 数据出网 | 确定性 | 落地工作量 |
|---|---|---|---|---|---|---|
| `none`（现状） | 0 | 0 | — | ❌ | — | 0 |
| **`cross_encoder` + `bge-reranker-base`** | ~2–4 s | **0** | 良好 | ❌ | **✅ 强** | 装依赖 + 改 3 行配置 |
| `cross_encoder` + `bge-reranker-v2-m3` | ~8–15 s | 0 | 更好 | ❌ | ✅ | 同上，但延迟大概率不可接受 |
| `llm` + gpt-4o | ~1–3 s | 每次 token 费 | 最好 | ✅ | ⚠️ 弱 | 已实现，改 1 行 |
| 托管 Rerank API（Cohere/Voyage/Jina） | ~0.2–0.5 s | 按次计费 | 良好 | ✅ | ✅ | **需新写 provider** |

### 8.4 决策

**主线走本地 `bge-reranker-base`。**

**`llm` provider 不要删** —— 它的价值是当**精度上限的对照组**。LLM 重排通常代表这个环节的天花板，用它衡量本地小模型差多少，比看任何公开 benchmark 都可信。这恰是插件化架构的回报。

**明确不推荐现在接托管 Rerank API** —— 要新写 provider、要付费、要出网，换来省 2 秒。还没到需要这 2 秒的阶段，做了是纯粹的复杂度支出。

### 8.5 什么情况下反过来选线上

诚实的边界：

- **实测延迟超 5 秒且不可接受** —— 但第一反应应是**降候选数**（`query_knowledge_hub.py:341` 的 `top_k * 2`），延迟与候选数**严格线性**，砍一半快一倍。先调候选数，再考虑换方案
- **查询意图复杂到需要推理**（多跳、隐含约束）—— 2.78 亿参数的 cross-encoder 做不到，gpt-4o 能。这是 LLM 重排的真实护城河
- **上生产、有并发** —— 本地 CPU 推理无法横向扩展，届时该上 GPU 或托管 API

---

## 9. 部署条件核验【实测】

### 9.1 资源需求 vs 本机配置

| 资源 | `bge-reranker-base` 需要 | 本机 | 判定 |
|---|---|---|---|
| **磁盘** | ~1.1 GB 权重 + 缓存余量 | **45.7 GB** 可用 | ✅ 富余 40 倍 |
| **内存峰值** | ~2–2.5 GB（权重 1.1 GB + 激活 + torch 运行时）【推算】 | **31.2 GB** 总，探测时空闲 5.8 GB | ✅ 够 |
| **GPU** | **不需要** | 无 CUDA | ✅ 非阻塞 |
| **CPU 指令集** | AVX2 起步，AVX-512 更快 | Zen 4 支持 AVX-512 + VNNI | ✅ 有利 |
| **CPU 核数** | 越多越好 | 8 核 16 线程 | ✅ |
| **Python** | ≥3.9 | 3.12.1 | ✅ |
| **torch** | ≥1.11 | 2.12.0+cpu **已装** | ✅ 省 2 GB 下载 |
| **网络** | 首次拉 ~1.1 GB from HF Hub | HF 缓存已有 505 MB（docling 模型下载成功过） | ✅ 通路已验证 |

验证 AVX-512 是否真被用上：

```bash
.venv/Scripts/python.exe -c "import torch; print(torch.backends.cpu.get_cpu_capability())"
```

输出 `AVX512` 为最好情况。

### 9.2 依赖冲突风险：已实测排除

原本担心 sentence-transformers 会把 `transformers 5.8.1` **降级**到 4.x，弄坏现有 docling 摄取链路。dry-run 解析结果：

```
sentence-transformers 5.6.1 要求 transformers<6.0.0,>=4.41.0   ← 兼容 5.8.1
Would install: joblib-1.5.3 scikit-learn-1.9.0 sentence-transformers-5.6.1 threadpoolctl-3.6.0
```

**零降级、零冲突、零现有包被改动。** 只新增 4 个包，wheel 下载总量约 **9 MB**（torch / transformers / huggingface-hub 全部 already satisfied）。

**整个部署成本 = 9 MB Python 包 + ~1.1 GB 模型权重。**

### 9.3 首次下载

一次性 ~1.1 GB，之后走 `C:\Users\cyq\.cache\huggingface` 缓存永久离线。若偏慢可临时挂镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

（若该仓库同时存 `.bin` 与 `.safetensors` 两份权重，实际可能下到约 2 GB。磁盘不构成问题。）

### 9.4 延迟不可接受时的退路（按优先级）

1. **降候选数** —— 改 `query_knowledge_hub.py:341` 的 `top_k * 2`。延迟严格线性，**首选，零风险零成本**
2. **int8 量化 + ONNX Runtime** —— CPU 上通常 2–4× 加速，代价是新增 `optimum[onnxruntime]` 依赖并改 `_load_cross_encoder_model`。有工程量但收益确定
3. **切 `llm` provider** —— 已实现，改一行配置
4. 换更小的多语言 reranker —— 可选集很小，收益有限，最后考虑

### 9.5 判定

**硬件不是瓶颈**——32 GB 内存对一个 1.1 GB 模型是压倒性富余。瓶颈只有一个：没有 GPU 导致的延迟，而它可通过降候选数线性调节。

---

## 10. 结论与待办

### 10.1 三句话总结

1. 本项目的 cross-encoder 是 **sentence-transformers 本地实现**，与 Cohere 无关；Cohere 只是 `DEV_SPEC.md` 里未落地的愿景
2. **代码能力完备，运行能力为零**——依赖未声明未安装、配置未开启、真实模型从未加载过
3. 推荐**本地 `BAAI/bge-reranker-base`**，理由是**确定性**（评测需要可复现基线）+ **零边际成本**（评测高频调用）+ **学习纵深**；"数据不出网/离线可用"在本架构里是无效论据

### 10.2 待办清单

| # | 事项 | 优先级 | 说明 |
|---|---|---|---|
| 1 | `pip install sentence-transformers` | 高 | 已验证无冲突，新增 4 包约 9 MB |
| 2 | **写进 `pyproject.toml`** | 高 | §6.2 第 9 层是根因，光装不声明等于没修 |
| 3 | `settings.yaml` 换 `model: "BAAI/bge-reranker-base"` | 高 | 当前英文模型对一半语料无效 |
| 4 | 开 `enabled: true` + `provider: "cross_encoder"` | 高 | |
| 5 | 跑真实 MT5 查询，确认 trace 出现 rerank stage | 高 | 判别静默降级的可靠信号（§6.3） |
| 6 | **实测延迟**，替换本文所有【推算】数字 | 高 | 五分钟的事，可能偏差 2–3 倍 |
| 7 | 补 cross-encoder **集成测试** | 中 | 现有测试全 mock，对装配层无感（§6.2 第 8 层） |
| 8 | 补 **timeout 实际生效**逻辑 | 中 | 目前是死代码（§6.4），慢查询无兜底 |
| 9 | 跑 `none` / `cross_encoder` / `llm` 三组 A/B | 中 | 用自己的语料测增益，公开 benchmark 不可迁移 |
| 10 | 视情况把 `fusion_top_k` / `top_k*2` 调小 | 低 | 延迟旋钮，线性收益 |

### 10.3 尚未验证、不要当结论的事项

- ⚠️ 本文**所有 CPU 延迟数字均为【推算】**，按参数量与层数估算，**可能偏差 2–3 倍**
- ⚠️ `Qwen3-Reranker` 与本项目 `CrossEncoder(model_name)` 的兼容性**未验证**
- ⚠️ 各模型许可条款以 HF 模型页为准，本文知识有截止日期
- ⚠️ 重排在"RRF 已融合双路召回"链路上的**实际增益未知**——只有本项目自己的语料能回答

---

## 附录：术语表

| 术语 | 含义 |
|---|---|
| **Bi-Encoder** | 双塔编码器。query 与文档独立编码成向量，靠余弦/点积比相似度。文档向量可预计算入库 |
| **Cross-Encoder** | 交叉编码器。query 与文档拼接后一起过 Transformer，输出单个相关性分数。无法预计算 |
| **Late Interaction** | 折中架构（如 ColBERT）。保留 token 级向量，查询时做轻量交互，介于两者之间 |
| **Rerank / 重排** | 两阶段检索的第二阶段，对召回的少量候选做精细重新排序 |
| **RRF** | Reciprocal Rank Fusion，倒数排名融合。合并多路召回结果的无参数方法，本项目 `rrf_k: 60` |
| **logit** | 未经 sigmoid/softmax 归一化的原始模型输出。可排序，但不是概率，不可跨样本比阈值 |
| **MS MARCO** | 微软发布的大规模英文检索数据集，源自 Bing 真实搜索日志，约 53 万 query |
| **NDCG@10** | Normalized Discounted Cumulative Gain，检索排序质量指标，看前 10 位 |
| **XLM-R** | XLM-RoBERTa，多语言预训练模型，词表 25 万，覆盖 100 种语言。BGE reranker 的骨干 |
| **MiniLM** | 微软通过知识蒸馏得到的小型 Transformer，本项目当前模型的骨干 |
| **SBERT** | sentence-transformers 库的通称，源自 Sentence-BERT 论文 |
| **seq-cls** | `AutoModelForSequenceClassification`，HuggingFace 的序列分类模型头。cross-encoder 的标准形态 |
