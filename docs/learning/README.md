# 学习笔记索引

> **这是索引，不是教程。** 它只回答一个问题：**我该从哪份文档开始读。**
> **最后更新**：2026-08-17

---

## 30 秒选路

**直接找你现在想干的那件事，别通读本页。**

| 你现在想干什么 | 去哪 | 大概花多久 |
|---|---|---|
| 想学会**判断 RAG 答得好不好**（跑评估、看报告、决定改动该不该留） | [RAG 评估专题](rag-evaluation/README.md) —— 先看它开头那段「先用人话说」 | 系统学 6 h，速览 5 min |
| 想让模型**稳定返回程序能直接用的数据**（JSON 老是解析失败） | [结构化输出专题](structured-output/README.md) | 系统学 2 h |
| 想搞懂**重排（rerank）**是怎么回事、要不要开 | [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) | 1 h。⚠️ 想看懂「为什么开了指标反而跌」得先有评估专题 02 + 04 |
| 想搞懂**查询改写 / HyDE** | [query-rewriting-strategies.md](query-rewriting-strategies.md) | 45 min |
| 纠结**「有了 skill 还要不要做 RAG」** | [skill-vs-rag-knowledge-delivery.md](skill-vs-rag-knowledge-delivery.md) | 50 min |
| 纠结**该不该用 LlamaIndex 这类框架** | [tech-selection-llamaindex.md](tech-selection-llamaindex.md) | 30 min |
| 想知道**哪些活该 RAG 服务干、哪些该调用方干** | [agentic-retrieval-boundary.md](agentic-retrieval-boundary.md) | 50 min |
| **只想查一个参数怎么填** | 别读本目录 —— 查 `config/settings.yaml` 的注释，或 [../ragas-guide.md](../ragas-guide.md) | 2 min |

**不确定选哪个？** 两个专题的 README 开头都有一段不含术语的导读（各 5 分钟），读完就知道是不是你要的。

**被术语卡住了？** RAG 评估专题有一份 [术语速查表](rag-evaluation/glossary.md)，「召回率有三种意思」这类坑都在里面 —— 查表用，不用顺读。

---

## 0. 为什么有「专题」和「单篇」两种形态

简单说：**专题是带你从零学会，单篇是已经会了来搞懂原理。** 用错了会很痛苦 —— 拿单篇入门会一直被不认识的词卡住。

| 形态 | 体裁 | 特征 | 什么时候选它 |
|---|---|---|---|
| **`<topic>/` 目录** | **Tutorial 教程** | 编号短章、有固定顺序、每章 20-35 min、带自测题 | 第一次接触这个主题 |
| **`<topic>-explained.md` 单篇** | **Explanation 解释** | 深、长、有取舍论证；**预设你已知道这东西是干什么的** | 已有基础，来搞懂原理 |

⚠️ **用 Explanation 入门会有「每篇都看懂了、合起来不会用」的感觉** —— 缺的不是内容，是最下面两级台阶。这正是两个专题存在的理由。

---

## 1. 两个专题（有阅读顺序，从这里开始）

| 专题 | 章数 | 总时长 | 解决什么 | 分水岭在哪 |
|---|---|---|---|---|
| **[RAG 评估系统](rag-evaluation/README.md)** | 8 | ~3.5 h | 怎么把 RAG 质量变成可信的数字 | **05 元评估** —— 指标不是中立观察者，是有立场的参与者 |
| **[结构化输出](structured-output/README.md)** | 6 | ~2 h | 怎么让 LLM 稳定返回可被代码消费的数据 | **03 约束解码** —— 四种方法之间是「请求」与「物理不可能」的区别 |

两者的交叉点：**评估里 judge 的 `unparseable` 降级，根因是结构化输出问题。** 评估专题 03·05 章会交接过去。

---

## 2. 九份深文（按主题归位）

**每份都标了归属和是否已挂到专题上。** ⚠️ 标记的是「主体不属该专题，只借出一节」。

### 2.1 评估主题

| 文档 | 行数 | 归属 | 前置 |
|---|---|---|---|
| [ragas-basics.md](ragas-basics.md) | 527 | 评估专题 **03 层**的深入阅读 | 先走专题 00 → 03 |
| [golden-test-set-explained.md](golden-test-set-explained.md) | 647 | 评估专题 **04·05 层**。**本项目最完整的一篇** | 先走专题 00 → 04 |

### 2.2 检索主题（**尚无专题**）

| 文档 | 行数 | 主体讲什么 | 与评估的关系 |
|---|---|---|---|
| [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md) | 654 | Bi-Encoder vs Cross-Encoder 原理、模型选型、部署核验、延迟实测 | ⚠️ 只有 § 重排评估局限 属评估专题 05 层 |
| [query-rewriting-strategies.md](query-rewriting-strategies.md) | 493 | 查询改写的各种策略（HyDE、多查询、分解） | ⚠️ 只有「HyDE 分数虚高」那节属评估专题 |
| [agentic-retrieval-boundary.md](agentic-retrieval-boundary.md) | 586 | 改写 / 规划 / 迭代该由 RAG 服务方做还是调用方做；本项目第二个消费方的接入边界 | 检索级循环的效果验证需要评估专题的判读纪律 |

> 💡 这三份加起来 1733 行，**主题一致（检索能力）但没有教程层**。如果将来要建第三个专题，这里是最该建的位置。

### 2.3 结构化输出主题

| 文档 | 行数 | 归属 |
|---|---|---|
| [structured-output-explained.md](structured-output-explained.md) | 1217 | 结构化输出专题的深入阅读（全部 6 章共同的参考层） |

### 2.4 工程与选型（独立，无专题）

| 文档 | 行数 | 讲什么 | 什么时候读 |
|---|---|---|---|
| [skill-vs-rag-knowledge-delivery.md](skill-vs-rag-knowledge-delivery.md) | 585 | Skill 形态 vs RAG 服务：两种知识交付范式的分界线；下钻到 SQLite FTS5 | 想清楚「有了 skill 还要不要 RAG」 |
| [tech-selection-llamaindex.md](tech-selection-llamaindex.md) | 361 | 技术选型：为什么（不）用 LlamaIndex | 考虑引入框架时 |
| [understand-anything-knowledge-graph.md](understand-anything-knowledge-graph.md) | 269 | 代码库知识图谱工具的原理与用法 | 要理解一个陌生代码库时 |

---

## 3. 置信度约定（全目录统一）

| 标注 | 含义 |
|---|---|
| **【实测】** | 在本机实际运行 / 从归档产物读出，**标日期或 run_id**，可复核 |
| **【代码】** | 从本仓库源码读出，**附文件行号** |
| **【文献】** | 官方文档或论文，高置信；**API 演进快，以最新版为准** |
| **【推断】** | 由机制推导，逻辑自洽但**未验证**。不是共识，引用前请自行核验 |

**硬规则：没跑过就不许标【实测】。** 宁可标【推断】并注明未验证。

---

## 4. 相关但不在本目录的东西

学习笔记只负责「讲清楚」。另外三类文档负责别的事，**别拿它们当教材**：

| 位置 | 是什么 | 什么时候去 |
|---|---|---|
| [../ragas-guide.md](../ragas-guide.md) / [../ragas-tuning-playbook.md](../ragas-tuning-playbook.md) | Reference / How-to，写于 2026-04 | 查参数；⚠️ playbook 的调优决策表早于 v2 金标与重排，**当史料读** |
| `specs/` + `openspec/changes/archive/` | 规格契约与验收记录 | 要改代码，或要质疑某个结论的证据 |
| [../../CLAUDE.md](../../CLAUDE.md) § Important Implementation Notes | **所有既有结论的权威汇总** | 与任何学习笔记冲突时**以它为准** |

> ⚠️ 写「本项目现状」类内容前，**先核对 CLAUDE.md / openspec / 代码注释里的既有结论**。新证据不自动作废旧归因 —— 本项目已因此翻车一次，记录在 [structured-output/05-this-project.md § 4](structured-output/05-this-project.md)。

---

## 5. 新增文档时

1. **先判体裁**（§ 0）。系统化 / 适合新手 / 要补前置 → 建专题目录；单一概念深挖 → 单篇 `<topic>-explained.md`
2. 文件名**英文 kebab-case**，正文中文
3. 建完**回来更新本索引** —— 否则下一个人找不到它
4. 若属于某个已有专题，**在文档开头加路标**（指向专题 README 与它默认已知的前置）
5. 完整规范见 `learning-topic` skill
