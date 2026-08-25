"""查询改写（query rewriting）—— 检索前对查询做变换以提升召回质量。"""

from src.libs.query_rewriter.base_query_rewriter import (
    BaseQueryRewriter,
    NoneQueryRewriter,
)
from src.libs.query_rewriter.query_rewriter_factory import QueryRewriterFactory
from src.libs.query_rewriter.synonym_query_rewriter import SynonymQueryRewriter

__all__ = [
    "BaseQueryRewriter",
    "NoneQueryRewriter",
    "QueryRewriterFactory",
    "SynonymQueryRewriter",
]
