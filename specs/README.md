# specs/ —— 已冻结(2026-08-12)

**本目录只读。不要在这里新增或修改任何东西。**

这是 2026-04 ~ 2026-08 用 **GitHub Spec-Kit** 做的 5 个 feature 的规格文档,Spec-Kit
已于 2026-08-12 退役。现行 SDD 流程是 **OpenSpec**,新变更去 `openspec/changes/`。

| Feature | 主题 | 产物数 | 行数 |
|---|---|---|---|
| [001-rag-acceptance](001-rag-acceptance/) | RAG 质量验收体系(8 项指标 / RAGAS + custom 双后端) | 11 | 2078 |
| [002-multimodal-query-response](002-multimodal-query-response/) | 查询响应返图(MCP ImageContent) | 8 | 1153 |
| [003-testset-refine-automation](003-testset-refine-automation/) | 金标精修自动化(异源 LLM 预筛 + borderline 路由) | 12 | 1417 |
| [004-retrieval-infra-fix](004-retrieval-infra-fix/) | 检索基础设施修正(混合检索从未生效) | 9 | 1534 |
| [005-weighted-fusion](005-weighted-fusion/) | 带权重的结果融合 + 权重校准 | 9 | 1426 |

## 怎么用它

按 OpenSpec 对既有文档的建议:**当作探索阶段的参考材料,不要批量转换成 OpenSpec
规格**。需要背景时读它,不要试图迁移它。

仍被 `CLAUDE.md` 正文引用、有长期价值的几份:

- [001 evaluation settings 契约](001-rag-acceptance/contracts/settings.evaluation.schema.md) —— `evaluation.*` 配置的完整 schema
- [004 BM25 索引契约](004-retrieval-infra-fix/contracts/bm25_index.schema.md) —— 索引格式 v2
- [005 acceptance.md](005-weighted-fusion/acceptance.md) —— 融合权重的完整校准曲线
- [003 quickstart.md](003-testset-refine-automation/quickstart.md) —— `--auto-mode` 精修用法

真正沉淀下来的教训已经收进 `CLAUDE.md` 与 `openspec/config.yaml` 的 § 已知陷阱 ——
那两处才是长期记忆,本目录是过程产物。
