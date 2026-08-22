# 03 · 生成指标：让 LLM 当裁判

> **专题**：[RAG 评估系统学习](README.md) 第 03 章
> **前置**：[02 章](02-retrieval-metrics.md)（确定性指标做参照系）、[00 章 § 4](00-prerequisites.md#4-llm-当裁判不神秘它就是一次普通-api-调用)（judge 是一次普通 API 调用）
> **本章目标**：认得四项 RAGAS 指标各问什么、读哪些字段、低分意味着什么；建立「LLM 判定的分数带着多大不确定性」的直觉。
> **预计**：30 分钟
> 📖 **遇到不认识的词** → [术语速查表](glossary.md)（查表用，不用顺读）

> ### 用人话说，这章解决什么
>
> 上一章解决了「有没有翻到该看的那页」—— 那件事能用算术做，因为「该翻哪页」是有确定答案的。
>
> 这一章解决第二种病：**「翻到了但瞎写」怎么变成数字。** 难在这里没有确定答案可以对 —— 同一个意思能有一百种写法。
>
> **所以只剩一条路：再请一个 AI 来读、来判。** 这个专门打分的 AI 就叫 **judge（裁判）**，本章讲它的四种给分规则。
>
> 从这一章开始，分数不再是「算出来的」，而是「判出来的」—— **会贵、会慢、会波动、还会失败**。这三章之后你对指标的信任程度会一路下降，这是正常的，也是必要的。

---

## 1. 为什么生成段没法用 02 章那套

02 章的五个指标能成立，靠一个前提：**「对」是可以枚举的** —— 标准答案是一个 chunk ID 列表，比对是字符串相等。

生成段这个前提直接塌了：

```
问题：只能在主服务器上运行的应用才能改配置吗？

答案 A：是的，只能从主服务器上运行的应用程序添加或更新配置。
答案 B：对。非主服务器上的应用会收到 MT_RET_ERR_NOTMAIN。
答案 C：Yes — configuration updates are restricted to the main server.
```

三个答案**语义相同、字符零重合**。任何基于字符串比对的指标都会把其中两个判为错。

所以生成段只有一条路：**找一个理解语义的东西来读。** 目前唯一可规模化的选择就是另一个 LLM。这就是 **LLM-as-judge**。

> 【推断】新手常问「用 LLM 评 LLM 不是循环论证吗」。**部分是。** 但注意任务难度不对称：让模型「判断这句话在这段材料里有没有出处」比「从零写出正确答案」容易得多。judge 是在做一个更简单的任务，所以它能提供信息 —— 但也仅此而已，它绝不是人工标注的等价物。整个 05 章就在处理这个折扣。

---

## 2. 先认清楚四个字段，再看谁读谁

### 2.1 judge 打分时，桌面上摆着四样东西

评一条 case 时，judge 手边能拿到的**全部材料**就是这四个字段（[00 章 § 2.1](00-prerequisites.md#21-六步) 六步表的第 5b 行）。先用改卷子的比喻把它们各自是谁、**从哪来的**认清楚：

| 字段 | 是什么 | 从哪来 | 打比方 |
|---|---|---|---|
| `query` | 提给系统的问题 | **金标里预先写好**，每次评估都一样 | 考题 |
| `ground_truth` | 出题人预先认可的参考答案（文字版） | **金标里预先写好**，每次评估都一样 | 标准答案 |
| `contexts` | **这次运行**中检索模块实际捞回来的片段原文 | **系统当场产出**，改了检索就会变 | 学生翻开的那几页书 |
| `answer` | **这次运行**中生成模块实际写出的回答 | **系统当场产出**，改了 prompt/模型就会变 | 学生写下的答案 |

**分界线在「从哪来」这一列**：前两个是**预先写好的**（考题和标准答案），后两个是**系统当场产出的**（学生的翻书结果和作答）。评估要打分的对象只能是后两个 —— 前两个是拿来当**参照物**的。

拿 [00 章 § 2.3](00-prerequisites.md#23-一条真实-case-的完整数据) 那条真实 case【实测】填进去，四样东西长这样：

```
query        : 只能在主服务器上运行的应用程序才能添加或更新配置吗？   ← 考题
ground_truth : 是的，……对于其他应用程序，将返回错误代码
               MT_RET_ERR_NOTMAIN。                                  ← 标准答案
contexts[0]  : "注意\n\n只能从主服务器上运行的应用程序添加或更新配置。
                对于所有其他应用程序，将返回响应代码[MT_RET_ERR_NOTMAIN]…"
                                                                     ← 学生翻开的书页
answer       : 是的，只能从主服务器上运行的应用程序添加或更新配置。
               对于所有其他应用程序，将返回响应代码
               `MT_RET_ERR_NOTMAIN` [1][2][3]…                       ← 学生写的答案
```

### 2.2 「读哪些字段」不用背 —— 从指标问的问题推出来

每个指标本质上是同一个动作：**把某样东西拆开，逐条拿另一样东西核对**。把它问的问题写成这个形式，字段清单自己就出现了：

| 指标 | 它问的问题 | 拆开逐条检查的 X | 拿来对照的 Y | 分数记在谁头上 |
|---|---|---|---|---|
| `faithfulness` | 你**写的每句话**，在你**翻开的书页**里有出处吗？ | `answer` | `contexts` | 生成 |
| `answer_relevancy` | 你**写的答案**，是在回答**我问的这个问题**吗？ | `answer` | `query` | 生成 |
| `context_precision` | 你**翻开的每一页**，对写出**标准答案**有用吗？排前面了吗？ | `contexts` | `ground_truth`（+ `query`） | 检索 |
| `context_recall` | **标准答案**需要的每句话，你**翻开的页**里都找得到吗？ | `ground_truth` | `contexts` | 检索 |

**一个指标读哪些字段 = X 列 + Y 列的并集，一个不多、一个不少。**

> ⚠️ **注意 `context_recall` 那一行：被拆的和被打分的不是同一个东西。** 前三行都是「拆谁就是评谁」（拆 answer 评生成、拆 contexts 评检索），唯独 `context_recall` 反过来 —— 它把**参照物**（标准答案）拆成一张检查清单，逐项去**产出**（contexts）里核对，缺一项扣一分，**账记在检索头上**（材料没捞全），不是在给标准答案打分。
>
> 这个「反向」不是设计失误，是**查全类指标的必然结构**：查准（precision、faithfulness）拆的是产出，逐条问「这条有用/有出处吗」；查全（recall）只能拆参照物 —— 因为「全不全」这个问题，产出自己回答不了「本该有多少」，清单必须来自参照物。§ 3.5 的对称性就是这条规律的另一种说法。

由这张表能直接推出两条本章反复要用的结论：

- **`faithfulness` 只碰 `answer` 和 `contexts` —— 两头都是系统自己的产出**。它做的是「答案与材料之间的内部一致性检查」，从头到尾没碰过标准答案。所以它不需要 `ground_truth`；也所以它量的只是「有没有出处」而不是「对不对」（§ 3.1 展开）。
- **需要 `ground_truth` 的两个（`context_precision` / `context_recall`），都是拿标准答案当尺子** —— precision 拿它当判「这页有没有用」的标准，recall 把它拆成「该找到什么」的清单。「材料有没有用」「材料全不全」这两个问题，脱离「正确答案需要什么」就没法问。所以它们只能在金标上跑，上不了线上流量。

用 § 2.1 那条真实 case 走一遍，感受一下「同一桌材料、四个指标各拿各的」：

- `faithfulness`：把 `answer` 拆成句子，逐句去 `contexts` 里找出处 —— 「返回 MT_RET_ERR_NOTMAIN」这句在 contexts[0] 里原文就有 → 有出处。全程没看 ground_truth。
- `answer_relevancy`：从 `answer` 倒推「这在回答什么问题」，和 `query` 比 —— 倒推出来的大概就是「谁能改配置」，和原问题很像 → 高分。全程没看 contexts 的内容对不对。
- `context_recall`：把 `ground_truth` 拆成句子，逐句去 `contexts` 里核对 —— 标准答案提到的 MT_RET_ERR_NOTMAIN 在材料里有 → 这项打勾；哪句找不到，就记检索一笔「没捞全」。全程没看 answer。

### 2.3 四项指标的坐标系

把上面的推导压缩成一张 2×2 的表 —— **按「评哪一段 × 要不要参考答案」**放置，四个指标的分工一目了然：

|  | **评检索** | **评生成** |
|---|---|---|
| **需要 `ground_truth`** | `context_recall`<br>`context_precision` | — |
| **不需要 `ground_truth`** | — | `faithfulness`<br>`answer_relevancy` |

这张表本身就是信息：

- **左列**回答「检索干得怎么样」，**右列**回答「生成干得怎么样」。哪一列低就改哪个模块 —— 这正是 01 章 § 4 的分段诊断，只是换成了 LLM 判定的版本。
- **下排两个不需要标准答案**（§ 2.2 推过：它们的参照物是 `query` 和 `contexts`，都不是预先标注的东西）。这意味着 `faithfulness` 和 `answer_relevancy` 可以直接在**线上生产流量**上跑，不需要任何人工标注【文献】。这是 RAGAS 最有价值的特性之一。

最后把 § 2.2 的「被检对象 + 参照物」摊平成勾选表，方便以后查（**不用背**，忘了就按 § 2.2 的问题重推一遍）：

| 指标 | 读 `query` | 读 `answer` | 读 `contexts` | 读 `ground_truth` |
|---|---|---|---|---|
| `faithfulness` | | ✅ | ✅ | |
| `answer_relevancy` | ✅ | ✅ | | |
| `context_precision` | ✅ | | ✅ | ✅ |
| `context_recall` | (\*) | | ✅ | ✅ |

> (\*) 较真的话：`context_recall` 发给 judge 的 prompt 里**也带着 `question`**【代码】（[_context_recall.py:149](../../../.venv/Lib/site-packages/ragas/metrics/_context_recall.py#L149)），但判定准则（逐句归因）不使用它，只是背景信息。上表按「判定依据」打勾。

**`faithfulness` 那一行是本章最该记住的一件事** —— 它**根本不读 `ground_truth`**。后面 § 3.1 讲这意味着什么。

> ⚠️ **上表还有一个「不读」值得单独点出来：整张表里没有 `expected_chunk_ids` 这一列。**
>
> 【代码】RAGAS 的计算只用 `question` / `answer` / `contexts` / `ground_truth` 四个字段（[ragas_evaluator.py:295](../../../src/observability/evaluation/ragas_evaluator.py#L295)）。`golden_ids` 虽然出现在方法签名里，但**仅为接口统一**，源码注释写着「RAGAS 本身不使用 ID」（[:138](../../../src/observability/evaluation/ragas_evaluator.py#L138)）—— **它不知道「本该捞哪几个片段」**。
>
> 所以虽然 `context_recall` / `context_precision` 在上表里归为「评检索」，**它们评的是「捞回来的文字够不够、干不干净」，不是「捞对了哪几个片段」**。「第一条正确片段排第几」这类问题它们结构上答不了 —— 那是 [02 章](02-retrieval-metrics.md) 四项 `custom__*` 的活。
>
> 这也正是本项目**两组指标都要留**的根本原因，完整论证见 [02 章 § 6](02-retrieval-metrics.md#6-在本项目里)。

---

## 3. 四项指标：各问什么

四个指标里有三个走同一个套路（[00 章 § 4.2](00-prerequisites.md#42-那它凭什么吐出-0889-这种连续分数) 已经讲过）：

> **拆解 → 逐条判是/否 → 数比例。**

所以下面只讲**拆的是什么、拿什么判**。完整算法与例子在 [ragas-basics.md § 4](../ragas-basics.md)，学完本章直接过去。

### 3.1 `faithfulness` —— 「你是不是在编」

| | |
|---|---|
| **拆什么** | `answer` → 一组原子陈述 |
| **拿什么判** | `contexts`：每条陈述能否被检索到的材料支撑（NLI） |
| **分数** | 被支撑的陈述数 ÷ 总陈述数 |
| **低分意味着** | 模型在幻觉 |
| **要 `ground_truth` 吗** | **不要**。它的「参照物」就是 `contexts` 本身 —— 问的是「你说的话在给你的材料里有没有」,和标准答案是什么无关。这正是它能跑在无标注线上流量上的原因 |

**名字怎么理解**：faithful 本义是「忠诚的」，它天然要求一个宾语 —— 忠于**谁**？这里的宾语是 `contexts`，不是事实、不是标准答案。所以译作「忠实度」而**不要**读成「真实性 / 准确性」（那两个词暗示和事实比对，而它从不碰 `ground_truth`）。最贴切的人话版是开卷考试的「**照书作答率**」：老师不管你答得对不对，只查每句话能不能在你翻开的页里找到依据。

**关键判别 —— 它量的不是「对」，是「有没有出处」**：

```
contexts 里写着「build 2000 起生效」（材料本身是错的）
answer 照抄「build 2000 起生效」
→ faithfulness = 1.0    ← 满分，但答案是错的
```

> **faithfulness = 1.0 只证明模型忠实于给它的材料，不证明答案正确。** 材料错了它照样满分。这是四项指标里最容易被误读的一条。

本项目给它的阈值最高：`0.85`【代码】（[config/settings.yaml:340](../../../config/settings.yaml#L340)）—— 因为幻觉几乎总是最严重的问题。

### 3.2 `answer_relevancy` —— 「你是不是答非所问」

| | |
|---|---|
| **怎么算** | **反向验证**：从 `answer` 倒推出 N 个「这在回答什么问题」，再算它们与真实 `query` 的 embedding 余弦相似度，取均值 |
| **低分意味着** | 答跑偏了，或者模型在推诿 |
| **要 `ground_truth` 吗** | **不要**。它的「参照物」是 `query` 本身 —— 判「答没答在点上」不需要知道正确答案长什么样,只需要知道问题问的是什么 |

思路很巧：**如果回答确实在答那个问题，从回答倒推的问题就该和原问题很像。**

两个必须知道的细节：

- 它会识别 **noncommittal**（「我不知道」「资料中未提及」）并直接给 0【文献】—— 堵死「什么都不说反而拿高分」的作弊路径。
- **这是四项里唯一需要 embedding 模型的**。所以本项目的 `evaluation.embedding` 才单独有一节，且注释强调评估链路所有 embedding 环节必须用同一配置（避免 train-eval skew）【代码】。

### 3.3 `context_precision` —— 「捞上来的干不干净，且排序对不对」

| | |
|---|---|
| **拆什么** | `contexts` 的每一条 |
| **拿什么判** | 参照 `ground_truth`：这条 chunk 对回答问题有用吗 |
| **分数** | 本质是 AP（Average Precision）：对每个「有用」的位置算 precision@k 再平均【代码】（[_context_precision.py:122](../../../.venv/Lib/site-packages/ragas/metrics/_context_precision.py#L122)）；跨 case 再平均后才是 MAP |
| **低分意味着** | 召回了太多噪声，或排序不好 |
| **要 `ground_truth` 吗** | **要**。「这条 chunk 有没有用」是相对于「正确答案需要什么材料」而言的 —— 没有参考答案,judge 就没有判断「有用」的标尺,只能凭空猜 |

**名字怎么理解**：这里的 precision 是信息检索义的「**查准率**」（捞回来的东西里有用的占几成），**不是**日常义的「精确、精密」。它和 recall（查全率）是一对固定搭档：**查准问「网里的有多少是鱼」，查全问「海里的鱼有多少进了网」** —— 分子相同、分母不同（一个除以「你捞的」，一个除以「该捞的」）。两者天然此消彼长，所以永远成对出现。

**它对顺序敏感** —— 5 条里 3 条有用，排在 1/2/3 位得 1.0，排在 3/4/5 位只有约 0.48。这正是重排模块该改善的东西。

> 💡 **这条对本项目特别重要**。它是四项 RAGAS 指标里**唯一不锚定 `expected_chunk_ids`** 的 —— 它让 LLM 现场判断每条 chunk 有没有用，不依赖任何预先标好的 ID 列表。因此它在结构上是**目前唯一可能公正评判重排**的候选。但它同时也是最经不起 judge 漂移的一项（05 章 § 3 有配对实验数据）。

### 3.4 `context_recall` —— 「该找的找全了吗」

| | |
|---|---|
| **拆什么** | `ground_truth` → 一组句子 |
| **拿什么判** | `contexts`：每句话能否归因到检索结果 |
| **分数** | 能归因的句数 ÷ 总句数 |
| **低分意味着** | 检索漏了（切分粒度、embedding 不匹配、top_k 太小） |
| **要 `ground_truth` 吗** | **必须要**。它拆的就是 `ground_truth` —— 「该找的」由标准答案定义,没有标准答案,「找全了没有」这个问题本身就不成立。注意被拆的是参照物、被打分的是检索,见 § 2.2 的警告块 |

一个和 `context_precision` 恰成对照的实现细节【代码】：judge 判归因时，全部 `contexts` 是**拼成一整块**喂进去的（[_context_recall.py:150](../../../.venv/Lib/site-packages/ragas/metrics/_context_recall.py#L150)），所以它**对顺序完全不敏感** —— 而 precision 是逐条、按位置算分的。这也符合直觉：「全不全」和顺序无关，「干不干净且排得好不好」才和顺序有关。

### 3.5 一个能帮你一次记住四个的对称性

**`faithfulness` 和 `context_recall` 的算法几乎完全一样** —— 都是「拆成句子 → 逐句判能否归因到 contexts」。

**区别只在拆的是谁**：

```
faithfulness    : 拆 answer        → 「模型说的话有没有出处」→ 生成段
context_recall  : 拆 ground_truth  → 「该说的话有没有材料」  → 检索段
                       ↑
                  差别只在这里
```

同理，`context_precision` 与 `context_recall` 方向相反：precision 问「捞到的有没有用」，recall 问「该有的捞到没有」。

再补一层：**`faithfulness` 本质上也是一种查准率** —— 它拆开「你写的话」逐句问「有出处吗」，和 `context_precision` 拆开「你捞的页」逐条问「有用吗」是同一个查准结构（拆产出、逐条判、数比例），只是查的对象不同。四个指标里查全结构只有 `context_recall` 一个（拆参照物当清单，见 § 2.2 的警告块）。

理解这两组对称性，四个指标就不用死记了。

### 3.6 算法这么对称，名字为什么不对称

读到这里你可能已经在嘀咕：`faithfulness` 和 `context_recall` 算法几乎一样，命名风格却完全是两路的。**这不是错觉，它有真实的历史原因：四个名字借自两个不同的研究社区。**

| 指标 | 词从哪来 | 命名风格 |
|---|---|---|
| `context_precision` / `context_recall` | **信息检索（IR）**：precision / recall 是 1950 年代就定型的经典术语【文献】 | 「评估对象前缀 + 经典指标名」，刻意复用老词换取辨识度 |
| `faithfulness` / `answer_relevancy` | **NLG / 摘要评估**：faithfulness 是 2020 年前后摘要幻觉研究的既定术语（与 factual consistency、hallucination 同族）【文献】 | 「性质名」，像形容词，描述产出的一种品质 |

评检索的两个继承了 IR 的行话，评生成的两个继承了摘要评估的行话 —— 两个社区各说各话几十年，RAGAS 把它们拼进同一份报告，风格断层就这么来的。

而且这套名字是**长出来的，不是设计出来的**：RAGAS 原始论文（2023）里只有 faithfulness、answer relevance、context relevance 三个指标【文献】，`context_precision` / `context_recall` 是后来在库的迭代里加进去的，从没人回头做过统一重命名（0.1.x 里还有 `context_utilization`、`context_entities_recall` 这类更晚的旁支，风格更杂）。连 `answer_relevancy` 都和论文里的 "answer relevance" 差着一个后缀。

假如强行按 § 2.2 的「拆 X 对照 Y」结构统一命名【推断】，对称性会立刻显形：

```
faithfulness      →  answer_precision_wrt_contexts       （拆答案，查出处 —— 查准结构）
context_recall    →  ground_truth_coverage_by_contexts   （拆参照物，查覆盖 —— 查全结构）
```

但名字又长又丑，还丢掉了「让 IR 的人认出 precision、让 NLG 的人认出 faithfulness」的辨识度红利。RAGAS 选了**对社区熟悉度优化、放弃内部一致性** —— 是个真实的取舍，不是草率。

> **对你最有用的推论：别从名字反推算法。** 三个现成的反例就在本章：`context_precision` 的名字里看不出它要读 `ground_truth`；`faithfulness` 明明是查准结构，名字里没有 precision 一个字；`context_recall` 拆的是 ground_truth，名字里却只有 context。**这个领域的指标名是历史沉积物，不是接口文档** —— 名字只当检索关键词用，定义一律回到 § 2.2 那张「拆 X 对照 Y」的表。

---

## 4. 用它必须先接受的三件事

### 4.1 贵，而且慢

**每条 case 要发十几次 judge 调用**（拆陈述 1 次、逐条判 N 次、反向生成问题 3 次、逐条判 context 有用性 k 次……）。42 条金标跑一轮就是几百到上千次调用。

【实测】本项目 run `80a82405` 的 judge 调用统计（2026-08-16 归因时清点）：**595 次成功判定调用**。这是 42 条 case 的量级。

**直接推论**：RAGAS 不适合每次改代码都跑。日常回归用免费的 `custom__*` 四项，RAGAS 留给阶段性验收。

### 4.2 分数不可跨 judge 比较

换 judge 模型 = 换了裁判，分数会漂。这不是玄学，05 章 § 3 有本项目的配对实验数字（同一批数据、两个 judge，`context_precision` 差 0.08~0.11）。

**推论**：报告里的 `judge_llm_identifier` 字段不是装饰。比较两份报告前先对一眼。

### 4.3 judge 会失败，分母会缩

[00 章 § 5](00-prerequisites.md#5-平均值的分母是会变的) 已经讲过机制。这里只强调一条纪律：

> **看 RAGAS 分数前，先看 `metric_integrity`。**

---

## 5. 在本项目里

### 5.1 真实报告：一个必须自己会拆的例子

run `5efa34ab`【实测】（中文金标 6 条，2026-08-16）：

| 指标 | 聚合值 | `valid_count` | 真实分母 |
|---|---|---|---|
| `ragas__faithfulness` | **1.0** | **2** | 2/6 |
| `ragas__context_precision` | 0.8906 | 3 | 3/6 |
| `ragas__answer_relevancy` | 0.6862 | 6 | 6/6 ✅ |
| `ragas__context_recall` | 0.8333 | 6 | 6/6 ✅ |

**读法**：
- `faithfulness = 1.0` 不能用。2 条样本，且是「judge 恰好能判出来的那 2 条」—— 幸存者偏差。
- `answer_relevancy` 和 `context_recall` 的分母是满的，**这两个数可以用**。
- 注意 `answer_relevancy = 0.6862` 低于阈值 0.75【代码】—— 这是这份报告里少数几个既可信又不及格的信号。

> ⚠️ **不要因为「有降级」就把整份报告扔掉。** 降级是按指标发生的，分母满的那些指标依然有效。这正是 `metric_integrity` 按指标披露而不是只给一个总数的原因。

### 5.2 降级的病因已经查清了，而且不在 judge 身上

这是本项目一个完整的归因故事，**它是 05 章「元评估」的一次实战预演**。

背景：run `80a82405`（英文 42 条）的 `degraded_case_count` 高达 **23/42 = 54.8%**，是验收门槛 5% 的 11 倍。

2026-08-16 的归因结论【实测】（42 条冻结元组，判定模型 `glm:z-ai/glm-5.2-free`）：

| 假设 | 结论 |
|---|---|
| judge 太弱 | ❌ **部分否证**。换成 `claude-sonnet-5` 后降级率 55% → 33%，压得下但压不平 |
| `max_tokens` 不够 | ❌ **已否证**。595 次成功调用**零空响应**，最长响应 3378 字符 |
| 答案太短 | ❌ 不是独立成因。4 条短答案全都同时是语言错乱 |
| **英文问题产出中文答案** | ✅ **完全分离**：剔除限流干扰后的 14 条真实判定失败**全部**是「英文问题 + 中文答案」；语言一致的 14 条**零失败** |

机制上讲得通：faithfulness 先把 answer 拆成 statements、再拿 contexts 逐条做 NLI（§ 3.1）。**answer 是中文而 contexts 是英文时，这两步都在跨语言做**，而 RAGAS 0.1.x 的内部 prompt 是英文写的。

**病因在输入侧，不在裁判侧。** 42 条里有 28 条（66.7%）答案语言与问题不符 —— 那是答案生成链路的问题，不是评估的问题。

> ⚠️ 【实测】**用免费模型跑批时，限流会伪装成降级**：本次 21 条降级里 7 条实为 `upstream_error`，且集中在连续区间（突发窗口，不是 case 属性）。**做降级归因第一步先按 `upstream_error` 过滤一遍**，否则会把网关抖动读成质量问题。

完整归因记录见 [evaluation-degradation-governance/acceptance.md](../../../openspec/changes/archive/2026-08-16-evaluation-degradation-governance/acceptance.md)。

### 5.3 中文 RAGAS 有一个额外的坑

RAGAS 的内部 prompt 是英文的，跑中文要先做 `adapt(language=chinese)` 把提示词翻译过去。

【实测】2026-08-14：**adapt 在不抛任何异常的情况下返回了未翻译的英文提示词，并被写进磁盘缓存永久固化** —— `logs/ragas_adapt_cache/chinese/` 下五个「中文」文件的 CJK 字符数全为 0。

后果：第一代中文金标 47 条候选里 33 条（70%）因语种不符被丢，**只活下来 6 条** —— 这就是中文金标至今只有 6 条的原因。

**教训**：「没报错」不等于「做对了」。现有 fail-fast 只捕获异常，对这种形态完全无效。本项目现在用 `evaluation.synthesis.adapt_language_ratio_min` 做产物校验【代码】拦这一类失效。

---

## 6. 自测

<details><summary><b>Q1.</b> 某条 case 的 <code>faithfulness = 1.0</code>，能说明答案是对的吗？</summary>

不能。faithfulness 只判「答案里的每句话在 contexts 里有没有出处」，**完全不看 ground_truth**。如果检索到的材料本身是错的，模型忠实照抄照样满分。（§ 3.1）
</details>

<details><summary><b>Q2.</b> 四项 RAGAS 指标里，哪些能在没有标准答案的线上流量上跑？为什么这很有价值？</summary>

`faithfulness` 和 `answer_relevancy` —— 它们不读 `ground_truth`。价值在于线上没有人工标注，这两项是仅有的能直接监控生产质量的指标。（§ 2）
</details>

<details><summary><b>Q2.5</b> 不翻书：`context_precision` 读哪几个字段？说出你的推导过程，而不是背出答案。</summary>

它问的是「**捞上来的每一页**，对写出**标准答案**有用吗」→ 拆开逐条检查的是 `contexts`，拿来对照的是 `ground_truth`（判「有用」时还要知道问题是什么，所以带上 `query`）。所以它读 `query` + `contexts` + `ground_truth`，不读 `answer` —— 它评的是翻书环节，学生最后写了什么与它无关。（§ 2.2）
</details>

<details><summary><b>Q3.</b> `faithfulness` 和 `context_recall` 的算法有什么关系？</summary>

几乎完全一样（拆成句子 → 逐句判能否归因到 contexts），**区别只在拆的是 `answer` 还是 `ground_truth`**。前者问「模型说的有没有出处」，后者问「该说的有没有材料」。（§ 3.5）
</details>

<details><summary><b>Q4.</b> 报告写着 <code>ragas__faithfulness: 1.0</code>，你的第一个动作是什么？</summary>

去看 `metric_integrity.ragas__faithfulness.valid_count`。真实案例里它是 2（共 6 条），那个 1.0 是幸存者偏差。（§ 4.3、§ 5.1）
</details>

<details><summary><b>Q5.</b> 你发现降级率 55%。有人说「换个更强的 judge 就行了」。这个判断对吗？</summary>

**只对一半。** 本项目实测换成 sonnet-5 后 55% → 33%，压得下但压不平；而剩下的 33% 归因到「英文问题产出中文答案」—— **病因在输入侧**。换 judge 治不了输入侧的问题。

顺带：做归因前先按 `upstream_error` 过滤限流噪声。（§ 5.2）
</details>

<details><summary><b>Q6.</b> 为什么日常改一行代码不该跑 RAGAS？</summary>

每条 case 十几次 judge 调用，42 条一轮约 595 次【实测】，又慢又贵，且分数会因 judge 波动。日常回归用免费的 `custom__*` 四项，RAGAS 留给阶段性验收。（§ 4.1）
</details>

---

## 本章小结

| 问题 | 答案 |
|---|---|
| 生成段为什么必须用 LLM 判 | 语义相同的答案字符可以零重合，比对法失效 |
| 四个字段各是谁 | `query`/`ground_truth` 金标预先写好（考题/标准答案），`contexts`/`answer` 系统当场产出（翻开的书页/写下的答案） |
| 指标读哪些字段怎么记 | **不用背** —— 每个指标 = 「拆开检查的 X + 拿来对照的 Y」，把它问的问题写出来字段清单自动出现；唯一的弯是 `context_recall`：拆的是参照物，打分打的是检索 |
| 四项指标的坐标系 | 评检索/评生成 × 要不要 ground_truth |
| 最易误读的一项 | `faithfulness` —— 量的是「有没有出处」，不是「对不对」 |
| 唯一不锚定 chunk_id 的 | `context_precision`，因而是唯一可能公正评判重排的候选 |
| 记忆窍门 | faithfulness 与 context_recall 只差「拆 answer 还是拆 ground_truth」 |
| 名字为何不对称 | 借自两个社区（IR 的 precision/recall vs NLG 的 faithfulness），历史沉积物 —— **别从名字反推算法**，定义回到 § 2.2 的表 |
| 用它的三条前提 | 贵、不可跨 judge 比、分母会缩 |
| 本项目的降级病因 | **英文问题产出中文答案**（输入侧），不是 judge 弱、不是 max_tokens |

## 深入阅读

| 想深入 | 去哪 |
|---|---|
| 四个指标的完整算法、逐步例子、数据契约 | [ragas-basics.md § 4-5](../ragas-basics.md) |
| RAGAS 的六个坑（版本 pin、成本、中文 adapt） | [ragas-basics.md § 8](../ragas-basics.md) |
| judge 为什么 `unparseable`，怎么根治 | [结构化输出学习专题](../structured-output/README.md) |

**下一章** → [04 · 测试集：标准答案从哪来](04-golden-set.md) —— 到目前为止我们一直假设「标准答案是对的」。下一章拆掉这个假设。
