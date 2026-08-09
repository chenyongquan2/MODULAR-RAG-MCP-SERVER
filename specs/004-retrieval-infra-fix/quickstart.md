# Quickstart: 检索基础设施修正

**Feature**: 004-retrieval-infra-fix
**Date**: 2026-08-09

面向执行者的操作手册。**顺序不可打乱** —— 第 ① 步一旦跳过，修复前的系统状态就永久不可复现。

> ⚠️ **所有命令必须在 `.venv` 下运行。** 全局 Python 的 protobuf 是 5.29.3，`import chromadb` 会直接失败；`.venv` 里是 3.20.3（满足 `pyproject.toml` 的 `<4` 约束）。

---

## 前置检查

确认环境可用：

```bash
.venv/Scripts/python.exe -c "import chromadb; print(chromadb.__version__)"
```

确认当前的坏状态（用于事后对比，应看到中文词条为 0）：

```bash
.venv/Scripts/python.exe scripts/rebuild_bm25_index.py --inspect-only
```

---

## ① 补跑基准评估（不可跳过，有 API 成本）

这一步产出真正的「纯向量参照」。**修复后就再也测不到修复前的状态了。**

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection mt5_docs_english --pretty --archive
```

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection mt5_docs_chinese --pretty --archive
```

记下两次的 `run_id`，后续对比要用。

> 既有的 2026-04-28 归档**不能**当参照 —— 实测表明当时 MT5 语料尚未 ingest，那两份报告检索回的是公司政策文档和临时文件，全部指标为 0。详见 [research.md](./research.md) Decision 7。

---

## ② 集合迁移（复制式，可回滚）

先看迁移计划，不实际写入：

```bash
.venv/Scripts/python.exe scripts/migrate_collections.py --dry-run
```

预期输出：`mt5_docs_chinese` 21,193 条、`mt5_docs_english` 31,387 条待迁移，另有 10 条无归属的临时文件残留被单独列出。

确认无误后执行：

```bash
.venv/Scripts/python.exe scripts/migrate_collections.py
```

**原 `default` 集合保持完整不删**，可随时回滚。那 10 条残留**不会**被自动删除，需人工确认后单独处理。

---

## ③ + ④ 重建索引

切分逻辑与索引格式的代码改动完成后，重建：

```bash
.venv/Scripts/python.exe scripts/rebuild_bm25_index.py --collection mt5_docs_chinese
```

```bash
.venv/Scripts/python.exe scripts/rebuild_bm25_index.py --collection mt5_docs_english
```

### 验收要点（对应 SC-002 / SC-003 / FR-013）

重建脚本的统计报告应显示：

| 指标 | 期望 |
|---|---|
| 含中文词条占比（中文集合） | **> 50%**（当前 0%） |
| 标识回查向量库命中率 | **100%**（当前 0/200） |
| 跳过条目数 | 应为 0 或极小且有明细 |
| 索引文件体积 | 约 17 MB 量级（不是 156 MB —— 若是，说明标识字典化没生效） |

---

## ⑤ 重跑评估并对比

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection mt5_docs_english --pretty --archive
```

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection mt5_docs_chinese --pretty --archive
```

与 ① 的结果对比即得 **SC-008**（纯向量 vs 混合的逐指标差异）。

按难度分组统计得 **SC-009**：报告的 `case_results` 含 `query` 字段，与金标按 query 关联即可取到 `tags.difficulty`（英文集 22 simple / 9 multi_context / 11 reasoning）。

> **解读 SC-009 时的折扣**：金标的 `expected_chunk_ids` 是脚本按固定 top-5 回填的，不是人工标注的真实答案边界，这会削弱召回类指标对多跳问题的判别力。

---

## ⑥ 基线标注

把修复后的结果标为新基线，并给既有记录补上标注：

```bash
.venv/Scripts/python.exe scripts/evaluate.py --collection mt5_docs_english --mark-baseline
```

既有的 2026-04-28 记录标注为 `corpus_validity: mismatched` —— 它不是「纯向量参照」，而是跑在错误语料上的无效记录。

---

## 回滚

| 需要回滚的对象 | 做法 |
|---|---|
| 集合迁移 | 原 `default` 未被修改，把 `settings.yaml` 的 `collection_name` 改回 `default` 即可 |
| 索引重建 | 重建是原子替换，回滚需重新运行重建脚本（v1 索引本就是坏的，回滚到 v1 无意义） |
| 代码改动 | 各 task 独立 commit，按 task 粒度 revert |

---

## 常见问题

**Q：加载索引时报 `ValueError: unsupported index format version`？**
A：索引还是 v1 格式，跑 `rebuild_bm25_index.py`。这是刻意设计的**硬失败** —— 若在这里静默降级，就重演了本 feature 正在修的「静默失效」。见 [contracts/bm25_index.schema.md](./contracts/bm25_index.schema.md)。

**Q：重建后中文查询的关键词路径还是没结果？**
A：先跑切分口径一致性测试 `pytest tests/unit/test_tokenizer.py -v`。查询端与索引端切分口径漂移的失败是静默的 —— 不报错，只是永远召回为空。

**Q：`--collection` 参数改了语义，旧脚本会不会受影响？**
A：会。它从「融合后按元数据过滤」变成「真正切换检索范围」。这正是修复内容 —— 旧语义下关键词侧根本不看这个参数。

**Q：重建会不会花 embedding 的钱？**
A：不会。重建只消费向量库里已有的正文与标识，零 embedding 调用（SC-005）。花钱的只有第 ① 和 ⑤ 步的评估（RAGAS judge LLM + embedding）。
