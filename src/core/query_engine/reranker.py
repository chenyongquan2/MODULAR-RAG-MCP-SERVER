"""重排序模块 (None/CrossEncoder/LLM)。

本模块实现了 Core 层重排序编排器，负责接入 libs.reranker 后端，
并提供失败/超时回退机制，确保不影响最终返回结果。

当 reranker 不可用时，保持原始排名顺序并标记 fallback=true。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import RetrievalResult
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class Reranker:
    """Core 层重排序编排器。

    负责调用 libs.reranker 后端对检索结果进行重排序，
    并在失败时提供 graceful degradation。

    Design Principles Applied:
    - Fail-Fast Validation: 验证输入参数
    - Graceful Degradation: 任何 reranker 异常都回退到原始顺序
    - Observability: 在 metadata 中标记 rerank 相关状态

    Example:
        >>> reranker = Reranker(settings)
        >>> results = reranker.rerank(query, candidates)
    """

    def __init__(
        self,
        settings: Settings,
        reranker_backend: Optional[Any] = None,
    ) -> None:
        """Initialize Reranker.

        Args:
            settings: Application settings containing rerank configuration.
            reranker_backend: Optional reranker backend instance (created from factory if not provided).

        Raises:
            ValueError: If settings is None.
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings

        if reranker_backend is not None:
            self._reranker = reranker_backend
        else:
            from src.libs.reranker.reranker_factory import RerankerFactory

            self._reranker = RerankerFactory.create(settings)

    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """Rerank candidates using the configured reranker backend.

        Args:
            query: The original search query.
            candidates: List of RetrievalResult to rerank.
            trace: Optional TraceContext for observability.

        Returns:
            List of RetrievalResult sorted by reranked score (descending).
            If reranking fails, returns candidates in original order with
            metadata['rerank_fallback'] = True.
        """
        if not candidates:
            return []

        if not query or not query.strip():
            return candidates

        stage_started = time.monotonic()
        if trace is not None:
            trace.start_stage("rerank")

        # 后端与模型标识：从后端自报，而不是从配置读。两者可能不一致（例如
        # 配置写了模型名但后端根本没加载它），trace 要记的是**实际发生的事**。
        backend_name = self._describe_backend()
        model_name = self._describe_model()
        enabled = backend_name != "none"

        # ── top_m 截断 ──────────────────────────────────────────────────
        # 只把前 top_m 条交给后端重排，其余按原名次追加在重排结果之后。
        #
        # 为什么需要上限：cross-encoder 必须把 query 与每条候选拼接后过一遍
        # Transformer（无法像 dense 检索那样预计算），LLM 后端更是每条候选
        # 一次独立的网关调用。候选数直接决定延迟与成本，所以必须有闸门。
        #
        # 为什么余量要保留而不是丢弃：top_m 是「重排多少条」的预算，不是
        # 「返回多少条」的上限。返回条数由 retrieval.top_k_final 决定，在
        # HybridSearch 里截断。这里丢结果会让 top_m 变成一个隐蔽的召回削减。
        top_m = self._settings.rerank.top_m
        head = candidates[:top_m]
        carried_over = candidates[top_m:]

        candidates_dicts: List[Dict[str, Any]] = [
            {
                "id": r.chunk_id,
                "text": r.text,
                "score": r.score,
                "_retrieval_result": r,
            }
            for r in head
        ]

        rerank_output_count = len(candidates)
        fallback = False
        timed_out = False
        scored_count = len(head)

        try:
            # 支持分批打分的后端走带超时的路径；不支持的退回整体调用。
            #
            # 这里刻意用 `is True` 而不是普通真值判断，也刻意用 getattr 兜住
            # 方法不存在的情况 —— 后端是鸭子类型的（`Reranker` 可以注入任意
            # 对象，测试里常用 `Mock()`）。对 `Mock()` 而言任何方法调用都返回
            # 一个**真值** Mock，用真值判断会把它误判成支持分批，接着 zip 一个
            # Mock 分数列表并炸成降级。严格身份判断让「没明确声明支持」的后端
            # 落回本变更之前的整体调用路径，这才是正确的向后兼容默认。
            supports_batch = getattr(self._reranker, "supports_batch_scoring", None)
            if callable(supports_batch) and supports_batch() is True:
                reranked_dicts, timed_out, scored_count = self._rerank_with_timeout(
                    query, candidates_dicts
                )
            else:
                reranked_dicts = self._reranker.rerank(
                    query, candidates_dicts, trace=trace
                )

            results: List[RetrievalResult] = []
            for d in reranked_dicts:
                original = d.get("_retrieval_result")
                if original and isinstance(original, RetrievalResult):
                    if "rerank_fallback" in original.metadata:
                        del original.metadata["rerank_fallback"]
                    original.metadata["reranked"] = True
                    # 把后端写在 dict 上的重排信息搬进 metadata。不搬就会丢 ——
                    # 下游拿到的是 RetrievalResult，dict 用完即弃。
                    if "rerank_score" in d:
                        original.metadata["rerank_score"] = d["rerank_score"]
                    if "reranked_by" in d:
                        original.metadata["reranked_by"] = d["reranked_by"]
                    results.append(original)
                else:
                    results.append(
                        RetrievalResult(
                            chunk_id=d.get("id", ""),
                            score=d.get("score", 0.0),
                            text=d.get("text", ""),
                            metadata={"reranked": True},
                        )
                    )

            # 未参与重排的余量按原名次追加。标记 reranked=False 以便下游
            # （及 dashboard）能区分「重排过的」与「顺位带过来的」。
            for result in carried_over:
                result.metadata["reranked"] = False
                results.append(result)

            rerank_output_count = len(results)
            return results

        except Exception:
            fallback = True
            for result in candidates:
                result.metadata["rerank_fallback"] = True
            return candidates
        finally:
            if trace is not None:
                trace.finish_stage(
                    "rerank",
                    {
                        "method": self._reranker.__class__.__name__,
                        "input_count": len(candidates),
                        "reranked_count": len(head),
                        "carried_over_count": len(carried_over),
                        "top_m": top_m,
                        "output_count": rerank_output_count,
                        # ── 三态用互不重叠的字段表达 ──────────────────────
                        # 规格明确要求「不使用同一个标记表达多种含义」。三种
                        # 非正常路径的成因与处置完全不同，混成一个标记会让
                        # 排查从一开始就少了关键信息：
                        #   enabled=False  → 压根没配重排，什么都没发生
                        #   fallback=True  → 后端炸了，原序返回（是错）
                        #   timed_out=True → 打分没跑完，部分生效（是慢）
                        # 三者可以同时为假（正常完成），但语义上互不蕴含。
                        "enabled": enabled,
                        "fallback": fallback,
                        "timed_out": timed_out,
                        "scored_count": scored_count,
                        "timeout_sec": self._settings.rerank.timeout_sec,
                        # 真实模型标识 —— 判别静默降级最可靠的信号。类名
                        # （method）只说明装配了哪个类，不说明它真的加载了模型。
                        "backend": backend_name,
                        "model": model_name,
                        "elapsed_sec": round(time.monotonic() - stage_started, 4),
                    },
                )

    def _describe_backend(self) -> str:
        """后端自报的标识（如 ``"cross_encoder"`` / ``"none"`` / ``"llm"``）。

        用 ``get_backend_name()`` 而非配置里的 ``rerank.backend``：后端是可注入
        的，实际生效的对象才是事实。取不到时回退到类名，绝不因为一个可观测性
        字段取不到就让查询失败。
        """
        getter = getattr(self._reranker, "get_backend_name", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:  # noqa: BLE001 —— 可观测性不得影响主流程
                pass
        return self._reranker.__class__.__name__

    def _describe_model(self) -> str:
        """后端实际使用的模型标识，取不到则 ``"n/a"``。

        这是判别静默降级最可靠的信号之一：类名只说明装配了哪个类，模型名才
        说明它真的打算加载什么。``NoneReranker`` 没有模型，返回 ``"n/a"``。
        """
        for attr in ("model_name", "get_model_name"):
            value = getattr(self._reranker, attr, None)
            if callable(value):
                try:
                    return str(value())
                except Exception:  # noqa: BLE001
                    continue
            elif isinstance(value, str) and value:
                return value
        return "n/a"

    def _rerank_with_timeout(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], bool, int]:
        """分批打分并在批间检查耗时，超时则停止后续批次。

        为什么只能这么做：cross-encoder 是同步 CPU 推理，Python 里没有能中断
        一段正在跑的同步计算的可用手段 —— ``signal.alarm`` 在 Windows 不支持
        且非主线程无效；工作线程 + ``join(timeout)`` 超时后线程仍在跑，无法
        中断 torch 推理，只会泄漏线程并继续吃 CPU。所以唯一可行的是把工作切
        成小批、在批的**间隙**检查已耗时。

        代价是超时粒度 = 一批的推理时间：最坏情况会超出 ``timeout_sec`` 一个
        批次。这是同步推理不可中断的固有成本，``batch_size`` 就是这个精度与
        吞吐之间的旋钮。

        超时时的语义（规格要求）：已打分部分按分数降序，未打分部分保持原名次
        追加在其后。**不抛异常、不丢候选** —— 超时是慢，不是错。

        Args:
            query: 查询文本。
            candidates: 已按 ``top_m`` 截断的候选（dict 形态）。

        Returns:
            三元组 ``(排序后的候选, 是否超时, 实际打分条数)``。
        """
        batch_size = self._settings.rerank.batch_size
        timeout_sec = self._settings.rerank.timeout_sec

        started = time.monotonic()
        # (分数, 原始下标, 候选) —— 带上下标是为了同分时有确定性次序
        scored: List[tuple[float, int, Dict[str, Any]]] = []
        timed_out = False

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            batch_scores = self._reranker.score_batch(query, batch)

            for offset, (candidate, score) in enumerate(zip(batch, batch_scores)):
                scored.append((score, start + offset, candidate))

            # 关键：检查放在打分**之后**。放在之前会让第一批还没跑就可能被
            # 判超时，那时一条都没打分，等于白等一场。
            # 同时要求「还有剩余批次」才算超时 —— 全部打完了就是正常完成，
            # 哪怕总耗时超了限也没有任何东西被牺牲。
            elapsed = time.monotonic() - started
            if elapsed >= timeout_sec and (start + batch_size) < len(candidates):
                timed_out = True
                logger.warning(
                    "rerank timed out: scored %d/%d candidates in %.3fs "
                    "(limit %.3fs, batch_size=%d); remaining candidates keep "
                    "their original ranking",
                    len(scored),
                    len(candidates),
                    elapsed,
                    timeout_sec,
                    batch_size,
                )
                break

        # 已打分部分按分数降序。同分时按原始下标升序 —— 让排序完全确定，
        # 不依赖 Python 排序实现的偶然行为（与 fusion.py 的确定性排序同理）。
        scored.sort(key=lambda item: (-item[0], item[1]))

        # 把分数写回，供下游（trace / dashboard）观察
        for score, _, candidate in scored:
            candidate["rerank_score"] = score
            candidate["original_score"] = candidate.get("score", 0.0)
            candidate["reranked_by"] = self._reranker.get_backend_name()

        results = [candidate for _, _, candidate in scored]
        # 未打分的候选按原名次追加（超时时才会有）
        scored_indices = {idx for _, idx, _ in scored}
        results.extend(
            candidate
            for idx, candidate in enumerate(candidates)
            if idx not in scored_indices
        )

        return results, timed_out, len(scored)
