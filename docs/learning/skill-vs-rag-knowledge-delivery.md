# Skill 形态 vs RAG 服务：两种知识交付范式的分界线在哪

> **记录日期**：2026-08-10
> **关联代码**：`src/core/text/tokenizer.py`、`src/ingestion/embedding/sparse_encoder.py`、`scripts/rebuild_bm25_index.py`
> **关联外部产物**：`~/.claude/skills/mt4-api-docs/`、`~/.claude/skills/mt5-api-docs/`（两个 MetaTrader 文档查询 skill）
> **起因**：既然两个 MT 文档 skill 已经能让 AI 查到 MT4/MT5 的参考资料，本 RAG 项目是否就多余了？为回答这个问题，把两个 skill 的产物完整拆解了一遍，顺带反推出它们的制作流程、AI 参与度，下钻到 SQLite FTS5 的机制，并回答了「为何两个 skill 形式完全不同、却没人统一」

## 置信度标注约定

沿用 [rerank-and-cross-encoder.md](rerank-and-cross-encoder.md)、[agentic-retrieval-boundary.md](agentic-retrieval-boundary.md) 的约定：

| 标注 | 含义 |
|---|---|
| **【实测】** | 在本机对 skill 产物实际运行命令验证过，2026-08-10；复现命令见附录 A |
| **【代码】** | 从本项目源码直接读出 |
| **【文献】** | 来自 SQLite 官方文档，高置信但请以最新版为准 |
| **【推断】** | 本文作者的综合判断，**不是共识，引用前请自行核验** |

> ⚠️ 本文对两个 skill 制作流程的复原属于**产物反推**，不是从作者处得到的一手说明。证据链在文中逐条给出，但「作者当时确实是这么做的」始终是【推断】。

---

## 目录

1. [先把三者的机制摆平](#1-先把三者的机制摆平)
2. [反推：这两份语料是怎么造出来的](#2-反推这两份语料是怎么造出来的)
3. [AI 参与在哪一步：一组天然对照实验](#3-ai-参与在哪一步一组天然对照实验)
4. [「索引」在这里指三种不同的东西](#4-索引在这里指三种不同的东西)
5. [下钻：SQLite FTS5 到底是什么](#5-下钻sqlite-fts5-到底是什么)
6. [skill 的物理构成与隐性依赖](#6-skill-的物理构成与隐性依赖)
7. [实测发现的两个缺陷](#7-实测发现的两个缺陷)
8. [为何两个 skill 形式不同，且没有统一](#8-为何两个-skill-形式不同且没有统一)
9. [五条主线结论](#9-五条主线结论)
10. [对本项目的启示](#10-对本项目的启示)
11. [附录 A：复现命令](#附录-a复现命令)
12. [附录 B：术语表](#附录-b术语表)

---

## 1. 先把三者的机制摆平

「谁多余」的争论多半源于没看清机制。先把三者拆开【实测】：

| | mt4-api-docs | mt5-document | 本项目 |
|---|---|---|---|
| 存储 | SQLite FTS5 单文件，479 KB | 123 个 Markdown，2.3 MB | ChromaDB 52,757 chunk + BM25 索引，1.8 GB |
| 索引单位 | 235 行结构化记录（3 TOC + 35 类目 + 197 函数） | **无索引**，只有 SKILL.md 里手写的 126 行主题映射表 | 语义切分的 chunk |
| 检索方式 | FTS5 关键词匹配（本质是 BM25 倒排） | **AI 读路由表猜文件 → 整文件读进上下文** | dense 向量 + sparse BM25 → RRF 融合 → rerank |
| 单次成本 | 0（本地 sqlite） | 0，但吃上下文：最大文件 45 KB ≈ 12k token | embedding + rerank + LLM 调用 |
| 质量可度量 | 无 | 无 | 金标集 + 8 项指标 + trace 落盘 |
| 消费方 | 仅 Claude 客户端 | 仅 Claude 客户端 | MCP（stdio/SSE），任意 agent |

> 命名说明：目录名是 `mt5-api-docs`，但 SKILL.md 的 `name:` 字段写的是 `mt5-document`【实测】。本文按功能称其为「MT5 skill」。

**第一个关键观察**：mt5-document **根本没有检索**。它是「人工写死的路由表 + 全文件加载」。mt4-api-docs 有检索，但是纯关键词的——它做的事情恰好等于本项目 sparse 那一路，缺 dense 和 rerank。

### 1.1 诚实的一半：在 MT 文档这个场景上 skill 确实更划算

不回避这一点【推断】：

1. **语料规模没到 RAG 的适用区间**。MT5 全部文档 2.3 MB、123 个文件。这个量级下，一张手写主题表的命中率往往高于向量检索——人分类比模型分类准，且没有切分损失。
2. **切分会伤这类文档**。`groups_settings.md`（45 KB）、`enums_trading.md` 是大表格和枚举清单。chunk 切开后「这一列属于哪张表」的上下文就丢了；skill 整文件读入反而保真。
3. **专有名词场景 FTS 更稳**。查 `TradeTransaction` 的签名，精确关键词匹配比向量相似度可靠——向量对生僻标识符本来就不敏感。
4. **零成本零延迟**，不会遇到模型下架、超时重试这类运营问题（本项目 2026-08-09 刚踩过 `text-embedding-3-small` 下架）。

### 1.2 另一半：skill 的四个硬天花板

1. **路由表不可扩展**。126 行主题映射是人手写的。文档翻到 1000 个文件时，这张表要么写不动，要么长到本身就占满上下文。
2. **语义查询直接失效**。问「怎么禁止客户在某类账户上反向开仓」——FTS5 匹配不到任何词，路由表也不知道该去 `groups_settings` 还是 `routing_rules`。这正是 dense 检索存在的理由。
3. **只有 Claude 能用**。skill 是 Claude 客户端的私有格式，第二个消费方（`smart-appointment-ai-agent`，经 `KnowledgeSearchPort` 接入）用不了，MCP 才能接。
4. **质量不可度量、不可回归**。skill 答错了不会有人知道，也没法证明改动后变好了。

### 1.3 结论：比较的层次错位了

**MT 文档在本项目里是语料，不是目的。** 用 skill 能答 MT 问题来论证 RAG 多余，逻辑上等于用「我有份 Excel 就能算工资」论证工资系统多余——在 5 个人的公司这话是对的。

- 就「回答 MT 文档问题」这一件事：当前语料规模下 skill 赢，RAG 是过度工程。
- 就「做一套可换 provider、可度量、可被任意 agent 复用的检索基础设施」：skill 连参赛资格都没有——它没有索引层、没有评估层、没有服务接口。

---

## 2. 反推：这两份语料是怎么造出来的

### 2.1 MT4：爬取 → 结构化解析 → 灌 FTS5

证据：`function_fts.url` 字段存的是完整原始地址 `https://support.metaquotes.net/en/docs/mt4/api/manager_api/...`【实测】。

复原流程【推断】：

1. **爬** MetaQuotes 官方 Manager API 文档站
2. **按页面类型分三类解析**——TOC 页、类目页、函数页。关键在这一步：函数页不是整页存文本，而是**按 HTML 结构拆成字段**（`signature` / `parameters` / `remarks` / `return_value`），`parameters` 存成 `[{"name":…,"description":…}]` 的 JSON 数组
3. **建 FTS5 虚拟表**，三张表对应三个层级
4. **手写 SKILL.md**，教 AI 怎么拼 `MATCH` 查询

这套做法质量上限很高，因为结构化字段是从 HTML 语义里抠出来的，无损。代价是解析器绑死站点结构，MetaQuotes 改版就得重写。

### 2.2 MT5：爬取 → 一页一文件 → AI 合并 → 手写路由表

证据：`core/id_lookup.json` 里有 **482 条** `id → {title, filename, keywords, version}` 记录，但 `data/` 下只有 **123 个** md 文件【实测】。这个差值是整条流程的关键指纹。

复原流程【推断】：

1. **爬** 482 个 htm 页，一页一个 md（`version: "mt5administrator"` 说明按产品线打了标）
2. **生成三份索引**：`file_index.json`、带关键词的 `id_lookup.json`、字母序的 `core/index.md`
3. **AI 合并**——482 页压成 123 个主题文件
4. **链接重写**：正文里 1439 处已改成 `.md`，但**还剩 825 处 `.htm` 没改**【实测】（如 `spreads.md` 里的 `group_position.htm#netting`）
5. **手写 SKILL.md 的 126 行主题路由表**——因为合并后原索引全废，只能重写一份

> 旁证：目录里有 `__MACOSX/` 和一堆 `._*` 文件【实测】。这是 macOS 打 zip 时留下的资源分叉，说明产物是在 Mac 上打包、在 Windows 上解压的。

---

## 3. AI 参与在哪一步：一组天然对照实验

这是整次分析里最有意思的一段。「AI 做的」和「脚本做的」在产物里留的指纹完全不同。

### 3.1 MT4 的数据里零 AI

查 `TradeTransaction` 那条记录，`signature` 字段是这样的【实测】：

```
int CManagerInterface::TradeTransaction ( TradeTransInfo* info ) //+---…---+
//| Opening a pending order | … int main( int argc, char * argv[]) { CManager manager; …
```

**函数签名把整段 40 行示例代码也吞进去了**，且所有换行被压成空格（典型的 `' '.join(text.split())`）。原因是原站页面上签名块和示例代码块共用同一个 HTML 容器/class，CSS 选择器一把抓了。

这是确定性抓取才会犯的错——**AI 生成绝不会把示例代码塞进「函数签名」字段**。再看 `remarks` 是 `["段落1", "段落2"]` 的数组（机械按段落切），`description` 是 MetaQuotes 官方原文一字不改。

> **结论**：MT4 的 db 是 100% 脚本产物，AI 只写了 SKILL.md 那份使用说明。

### 3.2 MT5 里存在一组天然对照实验

`id_lookup.json` 记的 482 个原始文件名中，**71 个在 `data/` 里原样存活**，另有 **52 个是合并后新造的**（`*_all.md`、`enums_trading.md` 这类），71 + 52 = 123【实测】。

把两组的加工痕迹并排统计【实测】：

| | 1:1 保留（71 个） | 合并新造（52 个） |
|---|---|---|
| 网站面包屑残留 | **70 处**（几乎每文件一处） | **0 处** |
| 二级以下标题（`##`/`###`） | **0 个** | **1383 个** |

对照极其干净：

- **71 个存活文件**是 html2text 的裸输出——`| | [ MetaTrader 5 Trading Platform ](beginning.md) / [ Platform Setup ]… |` 这种导航垃圾原封不动躺在正文里，而且**一个二级标题都没有**（原站靠加粗和表格做层次，转换器还原不出来）。零加工。
- **52 个合并文件**导航垃圾清零，重建了 1383 个标题层级，表格规范化。标题还是自拟的：`# Backup Server (Consolidated)`、`# MT5 Administrator Enumerations (Consolidated)`、`# Trading Enumerations (MT5)`——原站没有这些页面名。

`enums_trading.md` 的正文长这样【实测】：

```markdown
## Order Enums
### EnOrderType
Types of trade orders.
| Value | Name | Description |
| 0 | OP_BUY | A Buy order. |
```

散落在十几个原始页面里的枚举被重新归类成干净的表。**这是 AI 重写，不是拼接**——拼接会留下多个 H1 和重复面包屑，这里一个都没有。

### 3.3 一句话总结参与度

| 环节 | MT4 | MT5 |
|---|---|---|
| 爬取 + 转 Markdown | 脚本 | 脚本 |
| 内容加工 | **无**（纯字段抽取） | **AI 重写**（52/123 个文件） |
| 数据索引 | SQLite FTS5 自动建 | 脚本机械切词 |
| 给 AI 用的路由索引 | 无（靠 SQL） | AI/人手写的主题表 |

---

## 4. 「索引」在这里指三种不同的东西

这是最容易混淆的一点。同一个词在这两个 skill 里指三样东西，制作方式完全不同：

| 层次 | 谁做的 | 判定证据 |
|---|---|---|
| ① FTS5 倒排索引 | **SQLite 自动**，写完 `CREATE VIRTUAL TABLE` 就不用管 | 五张影子表自动出现 |
| ② `id_lookup.json` 关键词 | **脚本机械切词** | 见下 |
| ③ `index.md` / SKILL.md 路由表 | **AI 或人写** | 「问佣金公式该去哪个文件」是语义判断，无法脚本生成 |

### 4.1 ② 的判定过程

假设「keywords = 标题小写 → 按空格和 `/` 切词 → 补一条完整标题」，实测 **482 条里 411 条完全复现**，剩下 71 条的差异**全部是停用词**【实测】：

```
title:    "Import of Accounts and Trades"
keywords: ["import", "accounts", "trades", "import of accounts and trades"]
                    ↑ of / and 被过滤掉了
```

加上一张停用词表就是 100% 复现。**纯脚本，无任何语义理解。**

这个方法本身值得记：**判断一份数据是不是机器生成的，就试着用规则复现它，看复现率。** 复现率 85% 且残差有统一模式（这里是停用词），基本可以定死是脚本。

### 4.2 ③ 才是 MT5 skill 真正的检索层

```
| 路由规则 (routing_rules) | data/routing_rules.md |
| 保证金、利润、佣金公式    | data/calculations.md  |
```

这张表整个进上下文，AI 自己在表里做语义匹配，然后 Read 文件。**本质上是把检索职责外包给了 LLM 的注意力机制**——这是第 8 节主线结论的起点。

---

## 5. 下钻：SQLite FTS5 到底是什么

FTS = **F**ull-**T**ext **S**earch，5 是版本号（SQLite 3.9+ 内置，取代老的 FTS3/4）【文献】。一句话定位：**它就是本项目 sparse 那一路的内置 C 实现**——倒排索引 + BM25 打分，打包进了 SQLite。

### 5.1 虚拟表：一行 DDL 换六张表

```sql
CREATE VIRTUAL TABLE function_fts USING fts5(url, title, description, signature, …)
```

`VIRTUAL TABLE` 意思是这张表没有真实存储，读写被转交给 FTS5 模块。实际落盘的是自动创建的五张**影子表**（shadow table）【实测】：

| 影子表 | 装什么 |
|---|---|
| `function_fts_data` | 倒排数据本体（词条 → 文档列表，压缩成 blob） |
| `function_fts_idx` | 页级稀疏索引，用来定位 `_data` 里的哪一页 |
| `function_fts_content` | 原始字段内容（`c0` `c1` … 对应声明的每一列） |
| `function_fts_docsize` | 每篇文档各列的词数，BM25 长度归一化要用 |
| `function_fts_config` | 分词器等配置 |

平时只碰 `function_fts` 这一张，其余五张 SQLite 自己维护——**每次 INSERT 自动更新倒排索引**。这是它相对本项目最省事的地方：本项目 BM25 索引要显式跑 `scripts/rebuild_bm25_index.py`。

### 5.2 倒排索引长什么样

`function_fts_idx` dump 出来是这样【实测】：

```
segid | term    | pgno
    1 | 0bee    |    4
    1 | 0datab  |    6
    1 | 0metat  |   10
```

注意词都是断的——`datab`、`metat`。**这不是词干化**，FTS5 默认不做 stemming。原因是 `_idx` 不是完整词典，而是 **B-tree 的页级索引**：每行记录「第 pgno 页的第一个词条是 term」，term 只存到能唯一区分相邻页的最短前缀就够了【文献】。完整词条和 posting list（哪些文档、哪一列、第几个位置）压在 `_data` 的 blob 里。

查询 `MATCH 'margin'` 的路径：`_idx` 二分定位到页 → 读 `_data` 那一页解压 → 拿到 posting list → 得到候选文档。这与本项目 BM25 索引「倒排项存整数下标」是同一思路，只是压得更狠。

### 5.3 BM25 是内置函数

```sql
SELECT bm25(function_fts), title FROM function_fts
WHERE function_fts MATCH 'margin' ORDER BY bm25(function_fts)
```

实测输出【实测】：

```
-7.747  CManagerInterface::MarginLevelGet
-7.592  CManagerInterface::MarginsGet
-6.234  CManagerInterface::MarginLevelRequest
```

**分数是负的**——SQLite 故意取负，这样 `ORDER BY` 默认升序就是相关性降序，不用写 `DESC`【文献】。公式是标准 BM25（k1=1.2, b=0.75），`_docsize` 表存的列长度用于长度归一化。

还能给列加权，比如标题权重 10 倍、正文 1 倍：

```sql
ORDER BY bm25(function_fts, 10.0, 1.0)
```

> **本项目缺这个能力**：BM25 是在扁平 chunk 文本上算的，没有字段概念，无法「标题命中比正文命中更重要」。这在 Feature-005 带权融合之外，是另一个可以考虑的加权维度。

### 5.4 分词器：直接关系到本项目的暗礁

FTS5 默认分词器是 `unicode61`，按 Unicode 类别切词。建内存表实测中文【实测】：

| 查询 | 命中 |
|---|---|
| `MATCH '保证金'` | **0** |
| `MATCH '计算'` | **0** |
| `MATCH '保证金计算方式'` | 1 |
| `MATCH 'margin'` | 1 |

原因：`unicode61` 把汉字归为「字母类」，于是**一整串连续汉字被当成一个 token**。`保证金计算方式` 是一个词条，`保证金` 是另一个完全不同的词条，自然匹配不上。英文靠空格天然分开，所以没事。

这正是本项目 [tokenizer.py](../../src/core/text/tokenizer.py) 对 CJK 走 bigram 分支的理由。该文件开头注释记录的 Feature-004 缺陷 D3（`mt5_docs_chinese` 索引 7165 个词条含汉字 **0** 个）【代码】是同一类问题的另一种表现形式：

| | 失败形式 | 后果 |
|---|---|---|
| FTS5 `unicode61` | **不切分**汉字，整串当一个词 | 除非查询串与文档串完全一致，否则中文召回为 0 |
| 本项目旧代码（D3） | **丢弃**汉字，正则只留 ASCII | 中文召回恒为 0 |

**表现不同，后果一样，而且都不报错。**

### 5.5 与本项目 sparse 路的对照

| | SQLite FTS5 | 本项目 sparse 路 |
|---|---|---|
| 倒排索引 | 自动维护，INSERT 即更新 | 手动 `rebuild_bm25_index.py` |
| BM25 | 内置 `bm25()`，支持列加权 | 自己实现，无字段权重 |
| 中文 | 默认不可用，要换 tokenizer（`icu` 或自写扩展） | bigram 切分，可用 |
| 语义检索 | **完全没有** | dense 那一路补上 |
| 部署 | 一个 .db 文件，零依赖 | ChromaDB + 索引文件 |

**FTS5 = 精确关键词检索的工业级默认选项**。它把 sparse 这一路做到了开箱即用，但天花板也在那儿——它不理解「反向开仓」和「对冲持仓」是一回事。dense + RRF 融合补的正是这一块。

---

## 6. skill 的物理构成与隐性依赖

一个常见误解：既然叫「SQLite FTS5」，skill 里是不是打包了一个数据库？**不是。**

整个 mt4-api-docs 只有两个文件【实测】：

```
mt4-api-docs/
├── SKILL.md                   3.8 KB   ← 给 AI 看的说明书（纯文本）
└── references/mt4docs.db    479.2 KB   ← 数据文件
```

没有 .exe、没有服务进程、没有一行可执行代码。`.db` 的前 16 字节是 `SQLite format 3\0`【实测】——它就是个普通文件，只是内部按 SQLite 格式排布了页和 B-tree。

三者的实际关系：

| 东西 | 在哪 | 是什么 |
|---|---|---|
| SQLite **引擎** | 本机 `sqlite3.exe`（实测在 `C:\workspace\tools\sqlite-tools-win-x64-3500000\`，版本 3.50.0） | 一个约 1 MB 的程序 |
| **FTS5 模块** | 编译进上面那个 exe（`PRAGMA compile_options` 可见 `ENABLE_FTS5`） | 引擎的内置扩展 |
| `mt4docs.db` | skill 目录里 | 纯数据 + 一句「这张表要用 fts5」的声明 |

`.db` 里存的 DDL 是 `CREATE VIRTUAL TABLE … USING fts5(…)`。引擎打开文件读到 `USING fts5`，去调**自己内部**的 fts5 模块解释这张表。引擎没编译 FTS5 就直接报 `no such module: fts5`——文件还在，但打不开那张表。

### 6.1 skill 没有执行能力

流程是：AI 读 SKILL.md → 看到教的写法 → **AI 用 Bash 工具执行 `sqlite3 "$DB" "SELECT …"`** → 拿到 stdout。

真正干活的是 Claude Code 的 Bash 工具 + 本机的 sqlite3。**SKILL.md 只是一份「遇到 MT4 问题请这样查」的说明书。**

### 6.2 一个未声明的隐性依赖

Windows 默认**不带** `sqlite3.exe`。本机能用是因为在 `C:\workspace\tools\` 下手动放了一份并配了 PATH。

换一台干净的 Windows，这个 skill 直接失效——而 SKILL.md 里一个字都没提这个依赖。相比之下 mt5-document 只用 Read 读 md 文件，零外部依赖。

补救很简单，Python 自带 sqlite3 模块（实测 3.43.1，同样支持 FTS5）可作兜底：

```bash
python -c "import sqlite3;c=sqlite3.connect('mt4docs.db');print(c.execute(\"SELECT title FROM function_fts WHERE function_fts MATCH 'margin' LIMIT 5\").fetchall())"
```

### 6.3 与本项目的交付形态对照

| | mt4-api-docs skill | 本 RAG server |
|---|---|---|
| 交付物 | 2 个文件，479 KB | 代码 + `.venv` + 1.8 GB 数据 |
| 运行时 | **无**（借宿主机的 sqlite3） | 常驻进程（stdio / SSE） |
| 依赖 | 隐式 1 个，未声明 | 完整依赖树，版本敏感（踩过 protobuf 5.29 vs 3.20） |
| 分发 | 拷贝目录 | 装环境、配 key、建索引 |

**skill 之所以轻，是因为它把运行时外包给了宿主**——数据自带，引擎借用，逻辑写成给 AI 看的自然语言。代价是这类隐性依赖没人管，坏了也不报错到位。

---

## 7. 实测发现的两个缺陷

### 7.1 MT5 的索引已与语料脱节

链接完整性实测【实测】：

| 索引 | 链接总数 | 可解析 | 断链 |
|---|---|---|---|
| `references/index.md` | 505 | 76 | **429** |
| `references/core/index.md` | 483 | 72 | **411** |
| `SKILL.md` 路由表 | 99 | 99 | 0 |

`index.md` 顶部 Quick Reference 表里的 `data/server_connect.md`、`data/symbol_settings_common.md`、`data/automation.md` 全是死链。241 KB 的 `core/` 目前是死重量，而 SKILL.md 的 Option B 恰恰写着「主题不明确时去扫 `core/index.md`」——把兜底路径指向了一堆死链。

**成因由文件 mtime 直接坐实**【实测】。把 `data/` 下两组文件的修改时间分开看，整条流水线被还原出来：

| 时刻 | 发生了什么 |
|---|---|
| 04-13 **00:19** | 脚本阶段完成：71 个 1:1 文件 + `id_lookup.json` + `file_index.json` 同一分钟落盘 |
| 04-13 **00:23** | 生成 `index.md` 和 `core/index.md` |
| — | **间隔 16 小时** |
| 04-13 **16:46–17:05** | AI 合并：52 个文件在 19 分钟内产出 |
| 04-13 **17:08** | 写 SKILL.md 的 126 行路由表 |

`core/*.json` 和两份 index 从 00:23 之后**再没被碰过**。

所以这不是「设计失误」，而是：**AI 合并是第二天下午临时追加的一道工序，加完只更新了 SKILL.md，没有回头重跑凌晨那批索引。** 增量工序污染上游产物的典型形态——新工序的作者只关心自己这一步的输出，不知道（或忘了）上游还有派生物需要同步。

另外，唯一准确的 SKILL.md 路由表只覆盖 123 个文件中的 99 个，**24 个文件没有任何入口**，包括 `admin_plugins.md`、`admin_accounts.md`、`admin_groups.md`。问「MT5 插件怎么配置」，AI 按路由表找不到。

### 7.2 FTS5 默认分词器不能用于中文

见 § 5.4。MT4 那份 db 是纯英文文档所以没踩到，但如果有人照着这套做法建中文 skill，会静默失效。

---

## 8. 为何两个 skill 形式不同，且没有统一

同样是「把 MT 文档给 AI 参考」，一个做成 SQLite FTS5 数据库，一个做成手写路由表 + 整页 Markdown。为什么？为什么没人统一？拆成四层来看。

### 8.1 大部分是被语料结构逼出来的——而且这部分是对的

| | MT4 Manager API | MT5 Administrator 手册 |
|---|---|---|
| 语料本质 | **记录集**：197 个函数，每个都有相同字段槽位 | **叙述文**：482 页异构散文 + 配置说明 + 操作步骤 |
| 能否抽 schema | 能——`signature` / `parameters` / `return_value` 人人都有 | 不能——每页结构都不一样，没有共同字段 |
| 查询模式 | 「`TradeTransaction` 怎么用」→ **精确查找一条记录** | 「组权限怎么配」→ **需要整段上下文** |
| 答案单位 | 一条记录（几百字节） | 一节或一整页（几 KB） |

**有 schema 就上表，没 schema 只能整页留着**——这一步没什么可选的。MT4 那 197 个函数天然是一张表，不用 FTS5 反而浪费；MT5 的散文抽不出字段，硬切成表只会丢信息。

### 8.2 但有一部分纯粹是演进，不是设计

三条旁证都指向「这两个不是同一次设计的产物」【实测】：

| 证据 | MT4 | MT5 |
|---|---|---|
| 产物 mtime | 2026-05-14 | 2026-04-13（**早一个月**） |
| frontmatter `name` | `mt4-api-docs` | `mt5-document`（目录名 `mt5-api-docs` 是后来手动改的，改了目录没改 frontmatter） |
| 打包环境 | 无 `__MACOSX/` | 有 `__MACOSX/`（macOS 上打的 zip） |

**MT5 是更早、更朴素的方案；MT4 是一个月后更工程化的做法。** 这是时间顺序的产物，不是并行权衡的结果。分析他人产物时要能区分这两者——把演进痕迹当成深思熟虑的设计去解读，会得出过度合理化的结论。

### 8.3 那 MT5 能不能也上 FTS5？能，但收益不在检索质量上

技术上完全可以：对合并后的 123 个文件建全文索引，约一小时工作量。但要看清收益落在哪【推断】：

- **检索质量提升有限**。MT5 的问题是语义的——「怎么禁止客户反向开仓」在文档里写作「hedging 模式与 netting 模式」，关键词匹配不上。FTS5 解决不了这个，路由表借 LLM 的语义能力反而更管用。
- **答案单位没变**。FTS5 只能告诉你哪个文件命中，仍然要整文件读进上下文——结果和路由表一样，只是路由方式不同。

**真正的收益在维护侧，而这恰恰是它坏掉的地方**：

> 如果 MT5 当初上了 FTS5，§ 7.1 那 429 条断链根本不会发生——索引是从内容自动派生的，AI 合并完重跑一次 INSERT 就同步了，「忘了更新」这个可能性在结构上被消除。

这是本文最有说服力的一个反事实：**手写索引的成本不在写的那一次，在每一次内容变更之后。**

反过来 MT4 改用路由表会更差：197 个函数写成路由表就是 197 行（比 MT5 的 126 行还长），而函数名查找本来就是精确匹配场景。MT4 选 FTS5 是对的。

### 8.4 没统一的根因：制度层面根本没有约束

Claude Code 的 skill 规范只要求两样东西：一个 `SKILL.md`，里面有 `name` 和 `description` 的 frontmatter。`references/` 下放什么、怎么组织、检索层怎么实现——**完全自由**。没有 schema 校验，没有 lint，没有「检索接口必须长这样」的抽象基类。

这是**有意的设计取舍**【推断】：skill 的核心卖点是「写个 Markdown 就能扩展 AI 的能力」，门槛必须低。加一层强制的检索层规范，门槛就没了。

代价即是所见：每个 skill 自己发明一套检索层，质量参差，坏了没有任何机制会发现。MT5 那 429 条断链从 2026-04-13 存在至今（本文写于 2026-08-10，约 4 个月），零告警。

---

## 9. 五条主线结论

### ① 检索范式的分界线是「索引能否塞进上下文」

这是整次分析最重要的一条【推断】。

MT5 skill 的本质是**把检索职责外包给 LLM 的注意力**——路由表整个进上下文，AI 自己做语义匹配。

- **好处**：零检索工程，语义匹配能力直接白嫖模型的，不用 embedding、不用向量库。
- **硬约束**：索引必须小到能进上下文。126 行 ≈ 2k token 还行；语料涨 10 倍就是 20k token，每次调用都要付，且开始挤占推理空间。

RAG 把检索交给独立索引结构，**索引大小与上下文预算无关**——1.8 GB 的索引，每次查询只有 top-k 进上下文。

> **到了那个点，skill 范式不是「变慢」，是直接失效。** 这就是「什么时候 RAG 才不多余」的精确答案。

### ② skill 的真实成本不在制作，在维护索引与语料的一致性

而且失败是**静默**的：不报错、不告警，只是某类问题永远答不上来。

MT5 犯的错和本项目 Feature-004 修的 D3 是同构的。区别是本项目写了 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 守住这条不变量，MT5 没人守。

RAG 侧这件事是自动的：`python scripts/ingest.py --path <dir> --force` 重跑，索引和语料按定义一致，不存在「合并完忘了重建索引」的可能。**付出的是 embedding 调用成本，换来的是这类漂移不会发生。**

### ③ 中文分词是两种范式共同的暗礁

FTS5 不切分汉字，本项目旧代码直接丢弃汉字。表现不同，后果一样，都不报错。任何做中文检索的系统，**两端切分口径的一致性必须有测试守住**，这不是可选项。

### ④ 两者不必二选一

可行组合【推断】：skill 路由表命中就直接读文件（快、免费、保真），命中不了再走 MCP 语义检索兜底。

顺带还给本项目提供一个真实 A/B 对照组——同一批问题走两条路径，用现成的金标集量，而不是靠感觉争论。

### ⑤ skill 用「约定」代替「工程」，本项目用「工程」代替「约定」

这是 § 8.4 引出的、贯穿全文的那条对立【推断】：

| | skill 生态 | 本项目 |
|---|---|---|
| 接口约束 | 无 | `base_<component>.py` 抽象基类 + `@abstractmethod` |
| 组件替换 | 每个 skill 重新发明 | factory + registry，改 `settings.yaml` 零代码 |
| 一致性保障 | 无 | 启动时 fail-fast 校验 + 单元测试 |
| 上手门槛 | 写个 Markdown | 装环境、配 key、建索引 |

**约定的成本是零，但约定不会自己执行。** MT5 的作者「约定」了合并后要更新索引，然后忘了，没有任何东西拦住他——§ 7.1 的 mtime 时间线把这一刻记录得很清楚。

工程的成本是前期抽象层设计 + 长期维护，收益是**约束由机器执行**。本项目的 `tests/unit/test_tokenizer.py::TestBothEndsAgree` 就是把「两端切分口径必须一致」这个约定变成了工程。

所以两个 skill 不统一、而本项目所有组件都统一，不是谁做得好谁做得差，是**两条曲线在不同规模区间各自最优**：

- 语料 2 MB、单一消费方、改动频率低 → 约定够用，工程是浪费
- 语料上 GB、多消费方、持续演进 → 约定必然失守，工程是唯一出路

MT5 skill 那 429 条断链，就是第一条曲线开始往下掉的地方。

---

## 10. 对本项目的启示

| 启示 | 可操作项 |
|---|---|
| FTS5 支持**列加权** `bm25(t, 10.0, 1.0)`，本项目 BM25 无字段概念 | 可考虑给 chunk 的标题/正文分列加权，作为 Feature-005 带权融合之外的另一个维度 |
| FTS5 索引**随 INSERT 自动更新**，本项目需手动 rebuild | 若做轻量版分支，FTS5 天然消除「索引与查询端漂移」（两端共用 `_config` 表里的分词器配置） |
| skill 的隐性依赖不报错 | 本项目的 fail-fast 校验（`src/core/settings.py` 启动时验证）是对的方向，值得保持 |
| 「用规则复现数据」可判定是否机器生成 | 分析他人产物时的通用手法，见 § 4.1 |
| **派生物必须能从源自动重建**，否则「忘了更新」迟早发生 | MT5 断链的根因（§ 8.3）。检查本项目每一处派生产物是否都有重建脚本：BM25 索引有 `rebuild_bm25_index.py` ✅、金标 `expected_chunk_ids` 有 `backfill_chunk_ids.py` ✅ |
| mtime 可用于还原他人流水线的工序顺序 | 见 § 7.1；分析无文档产物时的实用手法 |

### 待办候选（未执行）

1. **修 MT5 skill 的索引**：按 `data/` 实际文件重新生成 `index.md` / `core/index.md`，批量改写 825 处残留的 `.htm` 链接。约半小时脚本工作量。
2. **建 A/B 对照**：同一批金标问题分别走 skill 路径和 RAG 路径，量化两者在 MT 文档上的实际差距。

---

## 附录 A：复现命令

```bash
# skill 物理构成
find ~/.claude/skills/mt4-api-docs -type f -exec ls -la {} \;
head -c 16 ~/.claude/skills/mt4-api-docs/references/mt4docs.db | od -c

# 引擎与 FTS5 支持
which sqlite3 && sqlite3 --version
sqlite3 :memory: "PRAGMA compile_options;" | grep -i fts

# 影子表与倒排索引
DB=~/.claude/skills/mt4-api-docs/references/mt4docs.db
sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE name LIKE 'function_fts%';"
sqlite3 "$DB" "SELECT segid, term, pgno FROM function_fts_idx LIMIT 8;"

# BM25 打分
sqlite3 -header -column "$DB" \
  "SELECT round(bm25(function_fts),3) AS score, title FROM function_fts
   WHERE function_fts MATCH 'margin' ORDER BY bm25(function_fts) LIMIT 5;"

# CSS 选择器抓多了的证据
sqlite3 "$DB" "SELECT signature FROM function_fts WHERE title LIKE '%TradeTransaction%';"

# 流水线工序顺序还原（§ 7.1 / § 8.2 的时间线证据）
cd ~/.claude/skills
stat -c '%y  %n' mt4-api-docs/SKILL.md mt4-api-docs/references/mt4docs.db
stat -c '%y  %n' mt5-api-docs/SKILL.md mt5-api-docs/references/index.md \
                 mt5-api-docs/references/core/id_lookup.json
ls -d mt*/__MACOSX 2>&1            # 打包环境痕迹：只有 MT5 有
head -2 mt4-api-docs/SKILL.md mt5-api-docs/SKILL.md | grep name:   # frontmatter 命名不一致

# FTS5 默认分词器对中文的行为
python - <<'EOF'
import sqlite3
c = sqlite3.connect(':memory:')
c.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
c.executemany("INSERT INTO t VALUES (?)", [("保证金计算方式",), ("margin calculation mode",)])
for q in ["保证金", "计算", "margin", "保证金计算方式"]:
    n = c.execute("SELECT count(*) FROM t WHERE t MATCH ?", (q,)).fetchone()[0]
    print(f"MATCH {q!r} -> {n}")
EOF
```

MT5 侧的统计脚本（1:1 保留 vs AI 合并的对照、链接完整性、keywords 复现率）见本文 § 3.2 / § 4.1 / § 7.1 所述口径，逻辑为：

- 用 `core/id_lookup.json` 的 `filename` 集合与 `data/*.md` 实际文件名求交集/差集，得到 71 / 52 两组
- 对两组分别统计面包屑正则 `MetaTrader 5 Trading Platform \]\(beginning` 与标题正则 `^#{2,4} ` 的出现次数
- 对 `index.md` / `core/index.md` 提取所有 `](*.md)` 链接，逐个 `os.path.exists` 校验

---

## 附录 B：术语表

| 术语 | 含义 |
|---|---|
| **FTS5** | SQLite 内置的 Full-Text Search 扩展第 5 版，提供倒排索引 + BM25 |
| **虚拟表（VIRTUAL TABLE）** | SQLite 中读写被转交给某个模块处理的表，本身无真实存储 |
| **影子表（shadow table）** | 虚拟表背后自动创建的真实存储表，如 `xxx_data` / `xxx_idx` |
| **posting list** | 倒排索引中某个词条对应的「文档列表」，含文档 id、列号、位置 |
| **unicode61** | FTS5 默认分词器，按 Unicode 类别切词；**把连续汉字视为单一 token** |
| **stemming（词干化）** | 把 running/ran 归并到 run；FTS5 默认**不做** |
| **html2text** | 把 HTML 转成 Markdown 的工具类统称，转换后常残留导航结构 |
| **资源分叉（`__MACOSX` / `._*`）** | macOS 打 zip 时附带的元数据，在其他系统上是垃圾文件 |
