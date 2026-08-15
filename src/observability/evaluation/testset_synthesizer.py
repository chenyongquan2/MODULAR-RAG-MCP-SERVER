"""TestsetSynthesizer — 包装 RAGAS TestsetGenerator 合成候选金标 (T019, FR-004).

实现 spec § FR-004 "测试集生成流程 MUST 从已摄入的真实 MT5 语料自动合成
至少 100 条候选 (question, ground_truth) 对" + research § Decision 5
(distribution).

设计:
- 从项目 vector store 拉 N 个真实 chunks 当作 RAGAS 合成的语料源
- 通过 _ragas_wrappers 复用 LLMFactory / EmbeddingFactory(provider-agnostic)
- 输出含 ``_synthesis_metadata`` 与 candidate cases 的 dict;每个 case 含
  partial tags(精修阶段补齐 content_type 等);留 expected_chunk_ids 由 backfill
  阶段填(US2 step B3)

使用方式:
    >>> synth = TestsetSynthesizer(settings)
    >>> candidate = synth.synthesize(
    ...     collection="mt5_docs_chinese", lang="zh", target_count=100
    ... )
    >>> # candidate["test_cases"] is a list of partial cases
    >>> # candidate["_synthesis_metadata"] tracks generator/judge/embedding ids
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability.evaluation.language_check import (
    LanguageCheck,
    check_language,
    supported_languages,
)
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings


logger = get_logger(__name__)


# RAGAS 0.1.x 的标准三类 evolution 名(简化字符串接口,内部映射到 ragas
# 的 SimpleEvolution / ReasoningEvolution / MultiContextEvolution 实例)
DEFAULT_DISTRIBUTION: dict[str, float] = {
    "simple": 0.5,
    "reasoning": 0.3,
    "multi_context": 0.2,
}



# 目标语言代码 → RAGAS 的语言标识。**集中定义**，不散落在调用点（T-2.3）。
# 新增语种时同时在 language_check._LANGUAGE_RANGES 登记字符集规则。
RAGAS_LANGUAGE_BY_CODE: dict[str, str] = {
    "zh": "chinese",
}

# 无需 adapt 的语言：RAGAS 内置 prompt 本就是英文。
_NO_ADAPT_LANGUAGES: frozenset[str] = frozenset({"en"})

# 旁挂的缓存元数据文件名。刻意不塞进 RAGAS 自己的 json —— 那是上游格式，
# 往里加私货会在 RAGAS 升级时炸。
ADAPT_METADATA_FILENAME = "_adapt_metadata.json"


def _adapt_prompt_files(lang_cache: "Path") -> list["Path"]:
    """缓存目录里 RAGAS 写出的 prompt 文件（排除我们旁挂的元数据）。"""
    return [
        f for f in sorted(lang_cache.glob("*.json"))
        if f.name != ADAPT_METADATA_FILENAME
    ]


def _validate_adapt_output(
    lang_cache: "Path", lang: str, settings: "Settings"
) -> dict[str, LanguageCheck]:
    """校验 adapt 产物**确实是目标语言**（T-2.1，本变更的核心）。

    为什么必须校验产物而不是只捕获异常:2026-08-14 实测,
    ``adapt(language=chinese)`` **不抛任何异常**地返回了未翻译的英文提示词
    —— 五个「中文」文件的 CJK 字符数全部为 0。只捕获异常的 fail-fast 对这种
    形态完全无效。**「没报错」不等于「做对了」。**

    Args:
        lang_cache: 该语言的缓存目录。
        lang: 目标语言代码。
        settings: 读 ``evaluation.synthesis.adapt_language_ratio_min``。

    Returns:
        ``{文件名: 校验结果}``。目录不存在或没有 prompt 文件时返回空字典 ——
        调用方须把「空」也当作失败（没有产物可以证明翻译成功）。
    """
    threshold = settings.evaluation.synthesis.adapt_language_ratio_min
    out: dict[str, LanguageCheck] = {}
    if not lang_cache.exists():
        return out
    for f in _adapt_prompt_files(lang_cache):
        out[f.name] = check_language(
            f.read_text(encoding="utf-8"), lang, threshold
        )
    return out


def _write_adapt_metadata(
    lang_cache: "Path",
    lang: str,
    checks: dict[str, LanguageCheck],
    settings: "Settings",
) -> None:
    """把校验结果与产出模型写进旁挂元数据（T-2.2）。

    没有这份元数据，事后无法判断一份缓存是好是坏 —— 实测中那份被污染的缓存
    让后续每次合成都读到英文提示词，而且没有任何迹象表明问题出在缓存上。
    """
    from datetime import datetime, timezone

    judge = settings.evaluation.judge_llm
    payload = {
        "language": lang,
        "produced_by": f"{judge.provider}:{judge.model}",
        "threshold": settings.evaluation.synthesis.adapt_language_ratio_min,
        "validated": all(c.passed for c in checks.values()) and bool(checks),
        "file_ratios": {n: round(c.ratio, 4) for n, c in checks.items()},
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    lang_cache.mkdir(parents=True, exist_ok=True)
    (lang_cache / ADAPT_METADATA_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cached_adapt_is_usable(
    lang_cache: "Path", lang: str, settings: "Settings"
) -> bool:
    """判断磁盘缓存能否直接使用（T-2.2）。

    **缺元数据即不可用** —— 那是来源不明的旧缓存，可能正是那份「假装已翻译」
    的产物。宁可多跑一次 adapt，也不能让坏缓存继续毒化后续每一次合成。
    """
    meta_path = lang_cache / ADAPT_METADATA_FILENAME
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not meta.get("validated"):
        return False
    if meta.get("language") != lang:
        return False
    if not _adapt_prompt_files(lang_cache):
        return False
    return True


class TestsetSynthesizer:
    """RAGAS TestsetGenerator 的项目侧包装(provider-agnostic)。"""

    # 阻止 pytest 把这个类当成测试类(类名以 Test 开头会被 pytest 默认收集)
    __test__ = False

    def __init__(self, settings: "Settings") -> None:
        """初始化合成器(延迟构建 RAGAS judge/embedding,直到 synthesize 触发)。"""
        self._settings = settings
        self._generator: Any = None  # ragas.testset.generator.TestsetGenerator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        collection: str,
        lang: str,
        target_count: int = 100,
        distribution: Optional[dict[str, float]] = None,
        chunk_sample_size: Optional[int] = None,
        source_filter: Optional[str] = None,
        force_adapt: bool = False,
    ) -> dict[str, Any]:
        """合成候选测试集。

        Args:
            collection: 项目 vector store 中的 collection 名(中文/英文 MT5)。
            lang: ``"zh"`` 或 ``"en"``,写入 candidate 的顶层 language 字段。
                未在 ``RAGAS_LANGUAGE_BY_CODE`` 或 ``_NO_ADAPT_LANGUAGES`` 中
                登记的语言会**明确报错**,不会静默按英文 prompt 合成。
            force_adapt: 忽略磁盘上的既有 adapt 缓存,强制重新翻译。用于换了
                合成端模型、或怀疑缓存有问题时 —— 缺元数据的旧缓存本就不会
                被使用,本参数是在「元数据显示通过」时也要重来的逃生口。
            target_count: 目标合成数(默认 100;精修后通常缩到 ≥ 40)。
            distribution: 难度分布,key ∈ {simple, reasoning, multi_context},
                value 求和应 ≈ 1.0。默认 50/30/20。
            chunk_sample_size: 从 collection 取多少 chunk 作为合成语料。
                None 时取 ``min(target_count * 5, collection.count)`` —— 经验值,
                让 RAGAS 有足够的多样性可挑。
            source_filter: 可选 substring 过滤;只保留 ``metadata.source`` 含此
                子串的 chunks(用于混合语种 collection 中按文件名筛选,
                例如 ``"Chinese.chm"`` / ``"English.chm"``)。默认 None = 不过滤。

        Returns:
            ``{"_schema_version": 1, "language": ..., "_synthesis_metadata": {...},
              "test_cases": [...]}`` 形式的 candidate dict。

        Raises:
            ValueError: 配置非法(distribution 总和远离 1.0、target_count <= 0、
                collection 不存在或为空、过滤后无 chunks)。
            RuntimeError: RAGAS 合成失败。
        """
        if target_count <= 0:
            raise ValueError(f"target_count must be > 0, got {target_count}")
        dist = self._validate_distribution(distribution or DEFAULT_DISTRIBUTION)

        # source_filter 模式下设上限:RAGAS InMemoryDocumentStore 会 embed 每个
        # 拉取到的 chunk(实测 ~750 chunks 跑 ~10 min;再多就拖 LLM 时间)。
        # T026 zh 实证 *50 (target=15 → 750 chunks) 跑通 ~10 min;> 50 倍数会
        # 让 embedding 步骤拖到几十分钟以上。无过滤场景仍是 *5。
        fetch_limit = chunk_sample_size or (
            target_count * 50 if source_filter else target_count * 5
        )
        chunks = self._fetch_chunks(collection, fetch_limit, source_filter=source_filter)
        if not chunks:
            extra = (
                f" (with source_filter='{source_filter}')" if source_filter else ""
            )
            raise ValueError(
                f"collection '{collection}' contains no chunks{extra}; "
                "please run scripts/ingest.py first to populate it, or relax "
                "the source_filter substring."
            )

        documents = self._chunks_to_langchain_docs(chunks)

        self._ensure_generator()
        ragas_distributions = self._build_ragas_distributions(dist)

        # 关键:RAGAS 0.1.x 默认 evolution prompt 是英文,Judge 据此产出英文 question。
        # 中文 corpus 必须先用 generator.adapt() 把内部 prompt 翻译到目标语言。
        #
        # adapt 内部调 LLM 翻译每个 prompt + example,要求返回 valid JSON。minimax 等
        # 模型偶发返回非 JSON 解释文本(2026-04-28 实证 ~50% 失败率),触发 RAGAS
        # pydantic 验证错误。我们用「重试 + 磁盘缓存」双保险:
        #   1. cache_dir 指向项目固定目录,首次 adapt 成功后写入磁盘,后续直接读
        #      (绕过 LLM 输出稳定性问题)
        #   2. 重试 3 次:每次都从头 init evolution 后再 adapt(避免脏状态污染)
        # en 是 RAGAS 默认 prompt 语言,无需 adapt。
        ragas_lang = RAGAS_LANGUAGE_BY_CODE.get(lang.lower())
        if lang.lower() not in _NO_ADAPT_LANGUAGES and ragas_lang is None:
            # 未支持的语言必须明确报错，**不能静默按 RAGAS 默认的英文 prompt 合成**
            # —— 那正是第一代产出 33 条英文问题的形态（T-2.3）。
            raise ValueError(
                f"unsupported target language for synthesis: {lang!r}. "
                f"Supported: {sorted(set(RAGAS_LANGUAGE_BY_CODE) | _NO_ADAPT_LANGUAGES)}. "
                "Falling back to the default (English) prompts would silently "
                "produce questions in the wrong language — that is exactly the "
                "failure this check exists to prevent."
            )

        if ragas_lang is not None:
            from pathlib import Path
            cache_dir = Path(
                self._settings.evaluation.synthesis.adapt_cache_dir
            ).resolve()
            cache_dir.mkdir(parents=True, exist_ok=True)
            lang_cache = cache_dir / ragas_lang

            # 缓存必须先过校验才能用（T-2.2）。缺元数据 = 来源不明的旧缓存，
            # 它可能正是那份「假装已翻译」的产物 —— 实测存在过。
            if not force_adapt and _cached_adapt_is_usable(
                lang_cache, lang, self._settings
            ):
                logger.info("reusing validated adapt cache: %s", lang_cache)
            else:
                if lang_cache.exists():
                    logger.warning(
                        "discarding unusable adapt cache at %s "
                        "(missing/failed validation metadata, or force rebuild)",
                        lang_cache,
                    )
                    import shutil
                    shutil.rmtree(lang_cache, ignore_errors=True)

                logger.info(
                    "Adapting RAGAS evolution prompts to language=%s (lang=%s, "
                    "cache=%s)",
                    ragas_lang, lang, cache_dir,
                )

                adapt_succeeded = False
                last_exc: Optional[Exception] = None
                for attempt in range(1, 3):
                    try:
                        self._generator.adapt(
                            language=ragas_lang,
                            evolutions=list(ragas_distributions.keys()),
                            cache_dir=str(cache_dir),
                        )
                        adapt_succeeded = True
                        if attempt > 1:
                            logger.info("RAGAS adapt succeeded on attempt %d", attempt)
                        break
                    except Exception as exc:
                        last_exc = exc
                        logger.warning(
                            "RAGAS adapt(language=%s) attempt %d/3 failed: %s",
                            ragas_lang, attempt, str(exc)[:200],
                        )
                if not adapt_succeeded:
                    # 情形 A：调用本身炸了（网络 / 模型故障）。重试或换网络。
                    raise RuntimeError(
                        f"RAGAS adapt(language={ragas_lang}) RAISED after 2 attempts. "
                        f"Last error: {last_exc}. This is a CALL failure (network or "
                        "model outage), not a translation-quality problem — retry, or "
                        "check the gateway. Distinct from the "
                        "'produced untranslated output' failure below."
                    )

                # 情形 B：调用成功，但产物没被翻译。**这才是实测发生过的形态** ——
                # adapt 不抛异常地返回英文，只捕获异常的 fail-fast 完全无效。
                checks = _validate_adapt_output(lang_cache, lang, self._settings)
                failed = {n: c for n, c in checks.items() if not c.passed}
                if failed or not checks:
                    import shutil
                    shutil.rmtree(lang_cache, ignore_errors=True)
                    detail = "; ".join(f"{n}: {c.describe()}" for n, c in checks.items())
                    raise RuntimeError(
                        f"RAGAS adapt(language={ragas_lang}) COMPLETED WITHOUT ERROR "
                        f"but produced output that is not in the target language. "
                        f"{detail or 'no prompt files were written at all'}. "
                        "The bad cache has been deleted so it cannot poison later "
                        "runs. This is NOT a transient failure — retrying the same "
                        "model will reproduce it. Change "
                        "evaluation.judge_llm.model to one that can translate the "
                        "prompts, then re-run."
                    )

                _write_adapt_metadata(lang_cache, lang, checks, self._settings)
                logger.info(
                    "adapt output validated: %s",
                    ", ".join(f"{n}={c.ratio:.1%}" for n, c in checks.items()),
                )

        try:
            from datasets import Dataset
            testset = self._generator.generate_with_langchain_docs(
                documents=documents,
                test_size=target_count,
                distributions=ragas_distributions,
                raise_exceptions=False,  # 单 case 失败不应让整个 100 条都丢
            )
        except Exception as exc:
            raise RuntimeError(f"RAGAS testset synthesis failed: {exc}") from exc

        candidate = self._testset_to_candidate(testset, lang=lang, distribution=dist)
        logger.info(
            "Synthesized %d candidates for lang=%s collection=%s (target was %d)",
            len(candidate["test_cases"]),
            lang,
            collection,
            target_count,
        )
        return candidate

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_generator(self) -> None:
        """构建 RAGAS TestsetGenerator(generator_llm + critic_llm + embeddings)。

        生成器与 critic 可以共用同一个 LLM 实例(RAGAS 允许),减少模型差异。
        """
        if self._generator is not None:
            return

        from ragas.testset.generator import TestsetGenerator

        from src.observability.evaluation._ragas_wrappers import (
            build_ragas_embedding,
            build_ragas_judge,
        )

        # 复用 wrapper:LangchainLLMWrapper / LangchainEmbeddingsWrapper
        # TestsetGenerator.__init__ 期望 BaseRagasLLM / BaseRagasEmbeddings(已包装)
        judge = build_ragas_judge(self._settings)
        embedding = build_ragas_embedding(self._settings)

        # InMemoryDocumentStore 需要 splitter+embeddings+extractor 全部填上
        # (extractor 也用同一个 judge wrapper,保持 provider-agnostic)
        self._generator = TestsetGenerator(
            generator_llm=judge,
            critic_llm=judge,  # 共用,降低 LLM 调用差异
            embeddings=embedding,
            docstore=self._build_docstore(embedding=embedding, judge=judge),
        )

    def _build_docstore(self, embedding: Any, judge: Any) -> Any:
        """构建 RAGAS 的 InMemoryDocumentStore (使用 Batched 子类)。

        RAGAS 0.1.x 的原生 ``InMemoryDocumentStore.add_nodes`` 通过 Executor
        把每个 node 当成一次 ``embed_text(text)`` 异步任务,最终走到
        ``aembed_documents([text])`` 单元素列表 → 我们的 wrapper 每次只发 1
        条 HTTP 请求。即使 max_workers=16 并发,也被 asyncio 线程池束缚到
        ~1.4 it/s,5000 nodes 要 ~50 min。

        ``BatchedInMemoryDocumentStore`` 重写 ``add_nodes``:
            1. 一次批量 ``embeddings.embed_documents([all node texts])`` →
               单次 HTTP(实际 OpenAI 兼容 API 一次最多 500 文本,自动分批)
            2. keyphrase extract 仍走 Executor 并发(LLM 调用,每节点必须)
            3. 把批量结果回写到 each ``node.embedding``

        实测:5000 nodes embed 阶段 ~50 min → ~1 min(60x)。
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from ragas.testset.extractor import KeyphraseExtractor

        from src.observability.evaluation._ragas_wrappers import (
            BatchedInMemoryDocumentStore,
        )

        splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=100)
        extractor = KeyphraseExtractor(llm=judge)
        return BatchedInMemoryDocumentStore(
            splitter=splitter,
            embeddings=embedding,
            extractor=extractor,
        )

    def _fetch_chunks(
        self,
        collection: str,
        limit: Optional[int],
        source_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """从 vector store 拉取 chunks 用作合成语料。

        直接通过 chromadb 客户端读取(本工具是数据准备脚本,不走 query 链路;
        provider-agnostic 约束适用于 query path,不适用于 ingestion-time / 数据
        准备工具,符合 spec § Architecture stability rule)。

        Args:
            collection: ChromaDB collection 名。
            limit: 上限拉取量。
            source_filter: 可选 substring,只保留 metadata.source 含此子串
                的 chunks(用于混合语种 collection 按文件名分流)。
        """
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb required for testset synthesis; install via "
                "pip install -e \".[dev]\""
            ) from exc

        client = chromadb.PersistentClient(
            path=self._settings.vector_store.persist_path
        )
        try:
            col = client.get_collection(collection)
        except Exception as exc:
            raise ValueError(
                f"collection '{collection}' not found in vector store: {exc}"
            ) from exc

        count = col.count()
        if count == 0:
            return []

        # 关键约束:server-side where 路径仍要传 limit,否则会一次拉全部匹配的
        # chunks(可能数万条),让下游 RAGAS InMemoryDocumentStore 按全量 embed —
        # 实测拉 31K 英文 chunks 后 RAGAS embedding 跑了 60K+ 节点,ETA 7+ 小时。
        # 真实使用 chunk_sample_size 上限(target_count * 100 经验值,够 RAGAS 选种子)。
        effective_limit = (
            count if limit is None
            else min(int(limit), count)
        )

        # 当 source_filter 设置时,优先尝试 chromadb 的 server-side where clause
        # 在 metadata 上精确匹配,O(K) 而非 O(N)。ChromaDB 支持 $eq;若 source_filter
        # 与某个常见 metadata key 的 value 匹配(典型:collection / source / source_path
        # 完整值),server-side 路径直接命中,避免拉全集 + 客户端过滤的开销。
        # 失败 → fallback 客户端 substring 过滤(此时仍受 limit 上限保护)。
        result = None
        if source_filter:
            for key in ("collection", "source", "source_path"):
                try:
                    r = col.get(
                        where={key: source_filter},
                        limit=effective_limit,
                        include=["documents", "metadatas"],
                    )
                    if r.get("ids"):
                        logger.info(
                            "server-side where filter '%s == %s' returned %d chunks "
                            "(limit=%d)",
                            key, source_filter, len(r["ids"]), effective_limit,
                        )
                        result = r
                        break
                except Exception as exc:
                    logger.debug("server-side where '%s' failed: %s", key, exc)
                    continue

        # 客户端路径(无 source_filter,或 server-side 没命中):按 limit 拉,客户端过滤
        if result is None:
            result = col.get(limit=effective_limit, include=["documents", "metadatas"])

        ids = result.get("ids", [])
        docs = result.get("documents", []) or []
        metas = result.get("metadatas", []) or []

        chunks: list[dict[str, Any]] = []
        for cid, text, meta in zip(ids, docs, metas):
            if not text or not isinstance(text, str) or not text.strip():
                continue
            meta_dict = dict(meta) if meta else {}
            # server-side filter 已在 DB 层应用,client-side 仍做一次 substring fallback
            # (覆盖 server-side 没匹配但 substring 可匹配的场景,例如部分文件名)
            if source_filter:
                src = str(meta_dict.get("source") or meta_dict.get("source_path") or "")
                logical_col = str(meta_dict.get("collection") or "")
                if (
                    source_filter not in src
                    and source_filter not in logical_col
                    and source_filter != src
                    and source_filter != logical_col
                ):
                    continue
            chunks.append({
                "id": cid,
                "text": text,
                "metadata": meta_dict,
            })
        logger.info(
            "Fetched %d non-empty chunks from collection '%s' (collection size: %d, source_filter=%r)",
            len(chunks),
            collection,
            count,
            source_filter,
        )
        return chunks

    @staticmethod
    def _chunks_to_langchain_docs(chunks: list[dict[str, Any]]) -> list[Any]:
        """把项目 chunk dicts 转成 LangChain Documents(RAGAS 需要的输入格式)。"""
        from langchain_core.documents import Document

        return [
            Document(
                page_content=c["text"],
                metadata={
                    "source": c.get("metadata", {}).get("source", c["id"]),
                    "chunk_id": c["id"],
                    **{
                        k: v for k, v in c.get("metadata", {}).items()
                        if k not in ("source",)
                    },
                },
            )
            for c in chunks
        ]

    @staticmethod
    def _validate_distribution(dist: dict[str, float]) -> dict[str, float]:
        """校验 distribution dict;允许少量浮点误差。"""
        valid_keys = {"simple", "reasoning", "multi_context"}
        unknown = set(dist.keys()) - valid_keys
        if unknown:
            raise ValueError(
                f"distribution contains unknown keys: {sorted(unknown)}; "
                f"valid options: {sorted(valid_keys)}"
            )
        # 缺失 key 视作 0(允许只给 simple+reasoning)
        normalized = {k: float(dist.get(k, 0.0)) for k in valid_keys}
        total = sum(normalized.values())
        if not 0.95 <= total <= 1.05:
            raise ValueError(
                f"distribution values must sum to ~1.0 (got {total:.3f}): "
                f"{normalized}"
            )
        return normalized

    @staticmethod
    def _build_ragas_distributions(dist: dict[str, float]) -> dict[Any, float]:
        """把字符串 distribution 映射到 RAGAS 的 evolution 实例。"""
        from ragas.testset.evolutions import multi_context, reasoning, simple

        mapping = {
            "simple": simple,
            "reasoning": reasoning,
            "multi_context": multi_context,
        }
        # 只把非零项加入(RAGAS 不接受 0 weight)
        return {mapping[k]: v for k, v in dist.items() if v > 0.0 and k in mapping}

    def _testset_to_candidate(
        self,
        testset: Any,
        lang: str,
        distribution: dict[str, float],
    ) -> dict[str, Any]:
        """把 RAGAS testset 对象转成项目 candidate JSON schema。"""
        from src.observability.evaluation._ragas_wrappers import (
            get_embedding_identifier,
            get_judge_identifier,
        )

        # RAGAS 0.1.x testset 有 to_pandas() / test_data 等接口;不同子版本可能
        # 略有差异,这里多路径兜底
        rows: list[dict[str, Any]] = []
        if hasattr(testset, "to_pandas"):
            df = testset.to_pandas()
            rows = df.to_dict(orient="records")
        elif hasattr(testset, "test_data"):
            rows = [
                {
                    "question": getattr(td, "question", ""),
                    "ground_truth": getattr(td, "ground_truth", ""),
                    "contexts": getattr(td, "contexts", []),
                    "evolution_type": getattr(td, "evolution_type", "simple"),
                }
                for td in testset.test_data
            ]
        else:
            rows = list(testset)

        test_cases = []
        for row in rows:
            question = str(row.get("question") or row.get("user_input") or "").strip()
            if not question:
                continue
            ground_truth = str(
                row.get("ground_truth") or row.get("answer") or row.get("reference") or ""
            ).strip()
            contexts = row.get("contexts") or row.get("reference_contexts") or []
            if isinstance(contexts, str):
                contexts = [contexts]
            evolution_type = str(row.get("evolution_type") or "simple").strip()
            # RAGAS evolution_type 与我们的 difficulty 对齐
            difficulty_map = {
                "simple": "simple",
                "reasoning": "reasoning",
                "multi_context": "multi_context",
            }
            difficulty = difficulty_map.get(evolution_type.lower(), "simple")

            test_cases.append({
                "query": question,
                "expected_chunk_ids": [],  # 由 backfill 阶段补齐 (US2 step B3)
                "expected_sources": [],
                "ground_truth": ground_truth,
                "_synth_contexts": list(contexts),  # 临时字段,refine 阶段可参考
                "tags": {
                    # content_type 由精修阶段判断(text/code/table/mixed),先占位
                    "content_type": "text",
                    "difficulty": difficulty,
                    "language": lang,
                    "doc_version": "v1",
                },
            })

        return {
            "_schema_version": 1,
            "language": lang,
            "_synthesis_metadata": {
                "generator": "ragas.testset.TestsetGenerator",
                "ragas_version": self._ragas_version(),
                "judge_llm_identifier": get_judge_identifier(self._settings),
                "embedding_identifier": get_embedding_identifier(self._settings),
                "distribution": dict(distribution),
                "synthesized_at": datetime.now(timezone.utc).isoformat(),
            },
            "test_cases": test_cases,
        }

    @staticmethod
    def _ragas_version() -> str:
        try:
            import ragas
            return str(getattr(ragas, "__version__", "unknown"))
        except ImportError:
            return "unavailable"
