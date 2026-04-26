"""AutonoMath multi-layer embedding pipeline.

Tier A (record-level) + Tier B (facet-level) embeddings stored in sqlite-vec.

Primary model: cl-nagoya/ruri-v3-310m (Japanese, 768d) -- NOT USED (>500MB cap)
Fallback model: intfloat/multilingual-e5-small (471MB, 384d)

Reference design:
  /tmp/autonomath_analysis_2026-04-24/04_embedding_search.md
  /tmp/autonomath_analysis_2026-04-24/07_chunking_rag.md
"""

from .config import (
    DB_PATH,
    DEFAULT_MODEL,
    EMBED_DIM,
    TIERS,
)

__version__ = "0.3.0"
__all__ = [
    "DB_PATH",
    "DEFAULT_MODEL",
    "EMBED_DIM",
    "TIERS",
    "smart_search",
    "SmartSearchResult",
    "QueryEmbeddingCache",
    "warm_reranker",
]


def get_reranker():  # pragma: no cover — convenience
    from .rerank import get_default_reranker
    return get_default_reranker()


# Re-exports — kept lazy so importing the package doesn't load torch.
def smart_search(*args, **kwargs):  # type: ignore[no-redef]
    from .smart_search import smart_search as _impl
    return _impl(*args, **kwargs)


def warm_reranker():  # type: ignore[no-redef]
    from .smart_search import warm_reranker as _impl
    return _impl()


class _SmartSearchResultShim:
    def __new__(cls, *a, **kw):
        from .smart_search import SmartSearchResult
        return SmartSearchResult(*a, **kw)


class _QueryEmbeddingCacheShim:
    def __new__(cls, *a, **kw):
        from .query_cache import QueryEmbeddingCache
        return QueryEmbeddingCache(*a, **kw)


SmartSearchResult = _SmartSearchResultShim
QueryEmbeddingCache = _QueryEmbeddingCacheShim
