"""切分实现 —— 查询端与索引端的**唯一**来源。

⚠️ **禁止在别处复制这里的逻辑。**

本模块的存在理由是 Feature-004 修复的缺陷 D3:此前
``src/ingestion/embedding/sparse_encoder.py`` 与
``src/core/query_engine/query_processor.py`` **各自维护了一份切分实现**,
两份都只保留 ASCII 字符。后果是名为 ``mt5_docs_chinese`` 的索引里
7165 个词条中含汉字的有 **0 个** —— 中文语料的关键词检索完全失效。

比"中文失效"更危险的是这类失败的形态:**两端口径一旦漂移,查询切出的
词条就永远匹配不上索引里的词条,而这个过程不报错、不告警,只是召回
恒为空**。D3 正是这样潜伏至今的。因此本模块是单一实现,并由
``tests/unit/test_tokenizer.py`` 的往返测试守住这条不变量。

切分规则见 specs/004-retrieval-infra-fix/data-model.md § 1。

实现将在 T022/T023 填充。
"""

from __future__ import annotations
