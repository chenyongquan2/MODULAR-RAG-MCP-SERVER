# 被污染的 adapt 缓存（证据保留，勿删）

2026-08-14 发现：RAGAS `adapt(language=chinese)` 在**不抛任何异常**的情况下
返回了未翻译的英文提示词，并被写进磁盘缓存永久固化。

这份是当时 `logs/ragas_adapt_cache/chinese/` 的原样拷贝。五个文件的
CJK 字符数**全部为 0**：

| 文件 | 大小 | CJK 字符 |
|---|---|---|
| answer_formulate.json | 4493B | 0 |
| find_relevant_context.json | 2702B | 0 |
| keyphrase_extraction.json | 1633B | 0 |
| rewrite_question.json | 3193B | 0 |
| score_context.json | 4332B | 0 |

后果：第一代中文金标 47 条候选里 33 条（70%）因语种不符被丢，只活下来 6 条。

保留理由：它是 change `expand-chinese-golden-set` 的核心证据，也是
`tests/unit/test_language_check.py::TestRealUntranslatedPrompt` 的取材来源。
