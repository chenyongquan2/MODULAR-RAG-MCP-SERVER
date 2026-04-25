# Quickstart: RAG 质量验收(中英双语基线)

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Audience**: 实施期开发者 / 验收期试跑者

本文件给出本 feature 完成后,**从零跑通 US1(MVP 烟雾测试)** 的 10 步指南,以及 US2 / US3 的快速启动入口。

---

## Prerequisites

- 已 `pip install -e ".[dev]"`(本 feature 实施后,`pyproject.toml` 会新增 `ragas==0.1.<x>` 与 `langchain-openai` 等依赖,见 [research.md § Decision 1](research.md))
- 已配置 `.env`,`GLM_API_KEY` 已填(默认 Judge LLM)
- 已摄入 MT5 中英文文档到独立 collection(`mt5_docs_chinese` / `mt5_docs_english`),或先用 `default` collection 跑 US1 占位测试

---

## Path A:US1 — MVP 烟雾测试(10 步)

**目标**:在不合成新测试集的前提下,把现有 4 条占位用例的 expected_chunk_ids 替换为 ChromaDB 真实 ID,跑通 RAGAS + custom 8 项指标全管线。

### Step 1:启用 RAGAS backend

编辑 `config/settings.yaml`:

```yaml
evaluation:
  backends:
    - custom
    - ragas        # ← 新增
```

### Step 2:配置 Judge LLM(默认 GLM-4)

`config/settings.yaml` 同段:

```yaml
evaluation:
  judge_llm:
    provider: glm
    model: glm-4
    api_key: ${GLM_API_KEY}
    base_url: ${GLM_BASE_URL}
    temperature: 0.0
    request_timeout_sec: 60
```

### Step 3:确认 embedding 配置(默认复用 production)

`config/settings.yaml` 同段:

```yaml
evaluation:
  embedding:
    provider: ""    # 留空 = 自动复用顶层 embedding(避免 train-eval skew)
    model: ""
```

### Step 4:启用 chunk_id 校验(默认就是 true,确认下)

```yaml
evaluation:
  chunk_id_validation: true
```

### Step 5:获取 vector store 中真实 chunk ID

```bash
python -c "
from src.core.settings import load_settings
import chromadb
s = load_settings()
client = chromadb.PersistentClient(path=s.vector_store.persist_path)
col = client.get_collection(s.vector_store.collection_name)
ids = col.peek(limit=10).get('ids', [])
for i in ids:
    print(i)
"
```

输出几个真实 chunk_id(类似 `1a2b3c4d-...-uuid`)。

### Step 6:修复占位金标

编辑 `tests/fixtures/golden_test_set.json`,把每条 case 的 `expected_chunk_ids` 占位字符串(`chunk_azure_001` 等)替换为 Step 5 获取的任一真实 ID;同时加上 `_schema_version: 1` 和每条 case 的 `tags` 字段([见 contract](contracts/golden_test_set.schema.md#6-示例us1-阶段占位文件的修复以现有-golden_test_setjson-为基础))。

### Step 7:启动期校验通过

```bash
python -c "from src.core.settings import load_settings; load_settings(); print('settings OK')"
```

预期输出 `settings OK`;若报 `ValueError: ... judge_llm.provider not in LLMFactory registry` 等,按提示修配置。

### Step 8:跑评估

```bash
python scripts/evaluate.py --pretty --collection default
```

### Step 9:验证输出包含 8 个指标 + acceptance_status

stdout 输出的 JSON 必须含:

```jsonc
{
  "aggregate_metrics": {
    "ragas__context_recall": <0~1 数字>,
    "ragas__context_precision": <0~1 数字>,
    "ragas__faithfulness": <0~1 数字>,
    "ragas__answer_relevancy": <0~1 数字>,
    "custom__hit_rate": <0~1 数字>,
    "custom__mrr": <0~1 数字>,
    "custom__recall": <0~1 数字>,
    "custom__ndcg": <0~1 数字>
  },
  "acceptance_status": "pass" 或 "fail",
  "judge_llm_identifier": "glm:glm-4",
  "embedding_identifier": "<provider>:<model>",
  "acceptance_thresholds_snapshot": { /* 8 项 */ }
}
```

任一指标为 `null` 或字段缺失 → US1 未达标,debug 后再继续。

### Step 10:确认归档落盘

```bash
ls logs/evaluation_reports/
# 应看到 <run_id>.json 与 index.jsonl

cat logs/evaluation_reports/index.jsonl
# 应看到一行精简记录
```

✅ **US1 验收完成**——SC-001 满足("1 次内全部 8 个指标产出有限数字")。

---

## Path B:US2 — 合成 + 精修 + 回填(高层指南)

完成 US1 后启动:

### Step B1:合成中文候选

```bash
python scripts/synthesize_testset.py \
  --collection mt5_docs_chinese \
  --lang zh \
  --target-count 100 \
  --distribution 0.5:0.3:0.2
```

输出:`tests/fixtures/candidates/zh.json`(100 条候选)。

### Step B2:人工精修

```bash
python scripts/refine_testset.py --input tests/fixtures/candidates/zh.json
```

逐条 prompt y/e/d/s/q,目标精修到 ≥ 40 条。

### Step B3:回填 expected_chunk_ids

```bash
python scripts/backfill_chunk_ids.py \
  --input tests/fixtures/golden_test_set_zh.json \
  --collection mt5_docs_chinese
```

(如果 backfill 报警告"匹配率过低",回到 Step B2 检查 ground_truth 文本质量。)

### Step B4:跑完整评估

```bash
python scripts/evaluate.py --lang zh --pretty
```

英文同理(`--lang en`)。

✅ **US2 验收完成**——SC-002 / SC-003 满足。

---

## Path C:US3 — 标基线 + 回归(高层指南)

完成 US2 后启动:

### Step C1:首次评估并标基线

```bash
python scripts/evaluate.py --lang zh --pretty > /tmp/zh_run1.json
# 记录 stdout 中的 run_id

python scripts/start_dashboard.py
# 浏览器打开 → 评估面板 → 找到该 run_id → 点"标记为基线"
```

### Step C2:改一项配置后重跑

```bash
# 例如把 retrieval.top_k_final 从 10 改 20
python scripts/evaluate.py --lang zh --pretty
# 此时 stdout JSON 自动含 baseline_id + delta_aggregate_metrics
```

### Step C3:面板查 delta + 趋势

dashboard → 评估面板 → 当前 run 视图 → delta 表格 + 8 项指标的时序折线。

✅ **US3 验收完成**——SC-004 / SC-005 满足(SC-005 要求 30 天内识别 1 次真实 delta,这步已经识别了 1 次)。

---

## Troubleshooting

| 症状 | 可能原因 | 修复 |
|---|---|---|
| `ValueError: judge_llm.provider not in LLMFactory registry` | 拼写错误或 provider 未注册 | 改成 `glm`/`azure`/`openai`/`ollama`/`deepseek` |
| `acceptance_thresholds.faithfulness=2.0 out of range` | 自定义阈值越界 | 改回 [0, 1] 范围 |
| `golden_test_set chunk_id missing: case[N] ...` | 测试集 expected_chunk_ids 是占位字符串或 ID 已漂移 | 重做 Step 5 / Step 6;或临时设 `chunk_id_validation: false` |
| RAGAS 指标全 NaN | Judge LLM 不可达;`degraded_case_count == total_cases` | 检查 GLM_API_KEY、base_url、网络 |
| `Judge LLM 配置错误` 之类的早期错误 | settings 校验通过,但 LangChain 包装层运行时失败 | 看 stderr 完整 traceback 定位 provider 实例化问题 |
| Dashboard 看不到趋势折线 | `logs/evaluation_reports/index.jsonl` 不存在或为空 | 至少跑 3 次 `evaluate.py --archive` |

---

## 关键参考

- 如何切换 Judge LLM(从 GLM-4 → GPT-4):改 `evaluation.judge_llm.provider` + `model` + `api_key`;**别忘了重新校准阈值**(spec § Assumptions § Judge 切换与阈值校准)
- 如何切换 vector store backend:改 `vector_store.backend`;本 feature spec 不绑定 ChromaDB,但 MVP 实际只支持 `chroma`
- spec 设计原理:[spec.md](spec.md) § Assumptions
- 7 个核心技术决策的 why:[research.md](research.md)
- 实体模型:[data-model.md](data-model.md)
- 4 份 schema 契约:[contracts/](contracts/)

---

## Definition of Done(本 feature 整体)

| Story | DoD |
|---|---|
| US1 | Path A 走通,SC-001 满足,acceptance_status 在占位测试集上正确产出(可能是 fail,但字段齐全) |
| US2 | Path B 走通,中英金标各 ≥ 40 条,人工 review 抽查合规率 ≥ 90% |
| US3 | Path C 走通,基线标记 + delta 视图正常,趋势折线 ≥ 3 数据点可见 |
| 全部 | `pytest tests/unit -v` 全绿;FR-001..FR-017 与 SC-001..SC-008 在 acceptance 阶段逐条 verify;commit 历史可从 task ID 反向追溯到 spec |
