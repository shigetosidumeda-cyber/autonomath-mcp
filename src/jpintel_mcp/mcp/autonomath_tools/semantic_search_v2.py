"""semantic_search_v2 — Wave 43.2.1 Dim A hybrid semantic search MCP tool.

One MCP tool ``semantic_search_am`` that wraps the REST handler at
``POST /v1/search/semantic`` (see ``api/semantic_search_v2.py``). The
tool runs LOCAL inference end-to-end:

  1. FTS5 BM25 over ``am_entities_fts``.
  2. sqlite-vec k-NN over ``am_entities_vec_e5`` (384-dim e5-small).
  3. RRF fusion (k=60).
  4. Cross-encoder reranker (MS-MARCO-MiniLM-L-6-v2) — optional.

Pricing: 2 metered units / call when ``rerank=True`` (default), 1 unit
when ``rerank=False``. Envelope wrapper attaches ``_billing_unit``.

NO LLM API
----------
  * ``sentence_transformers.SentenceTransformer(intfloat/multilingual-e5-small)``
    encodes the query — local CPU inference, weights cached on disk.
  * ``sentence_transformers.CrossEncoder(cross-encoder/ms-marco-MiniLM-L-6-v2)``
    reranks the top 50 — local CPU inference.
  * Zero ``import anthropic`` / ``import openai`` / ``import google.generativeai``
    / ``import claude_agent_sdk``. Zero env var refs to ANTHROPIC_API_KEY
    / OPENAI_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY.

§52 / §72 / §1 sensitive envelope.
"""

from __future__ import annotations

import logging
import math
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.semantic_search_v2")

_ENABLED = get_flag("JPCITE_SEMANTIC_SEARCH_V2_ENABLED", "AUTONOMATH_SEMANTIC_SEARCH_V2_ENABLED", "1") == "1"

_DISCLAIMER = (
    "本 response は am_entities corpus 503k+ rows に対する hybrid 検索結果 "
    "(FTS5 BM25 + sqlite-vec 384d e5-small + cross-encoder reranker) で、"
    "税務代理 (税理士法 §52) ・申請代理 (行政書士法 §1) ・法律事務 "
    "(弁護士法 §72) の代替ではありません。reranker_score は heuristic で、"
    "業務判断は必ず一次資料 (source_url) を確認し、確定判断は士業へ。"
)


def _semantic_search_impl(
    query: str,
    top_k: int = 10,
    rerank: bool = True,
    record_kinds: list[str] | None = None,
) -> dict[str, Any]:
    """Delegate to the REST handler logic (in-process call, no HTTP)."""
    from jpintel_mcp.api.semantic_search_v2 import (
        E5_MODEL,
        EXPECTED_EMBEDDING_DIM,
        RERANKER_MODEL,
        _encode_query_e5,
        _fts5_search,
        _open_autonomath_ro,
        _query_hash,
        _rerank_pairs,
        _rrf_fuse,
        _vec_search,
    )

    am = _open_autonomath_ro()
    if am is None:
        return {
            "results": [],
            "fts_count": 0,
            "vec_count": 0,
            "rrf_state": "db_unavailable",
            "reranker_state": "skipped",
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    candidate_window = min(50, max(top_k * 4, 20))

    fts = _fts5_search(am, query, limit=candidate_window, kinds=record_kinds)
    embedding = _encode_query_e5(query)
    vec: list[dict[str, Any]] = []
    if embedding is not None and len(embedding) == EXPECTED_EMBEDDING_DIM:
        vec = _vec_search(am, embedding, limit=candidate_window, kinds=record_kinds)

    fused = _rrf_fuse(fts, vec)
    rrf_state = "ready" if fused else "empty"

    reranker_state = "skipped"
    top = fused[:candidate_window]
    if rerank and top:
        scores = _rerank_pairs(query, top)
        if scores is not None and len(scores) == len(top):
            for cand, s in zip(top, scores, strict=True):
                cand["reranker_score"] = s
            top.sort(key=lambda r: r.get("reranker_score", -math.inf), reverse=True)
            reranker_state = "ready"
        else:
            reranker_state = "unavailable"

    final = top[:top_k]

    try:
        am.close()
    except Exception:  # noqa: BLE001
        pass

    quantity = 2 if rerank else 1
    return {
        "results": final,
        "total": len(final),
        "fts_count": len(fts),
        "vec_count": len(vec),
        "rrf_state": rrf_state,
        "reranker_state": reranker_state,
        "reranker_model": RERANKER_MODEL if reranker_state == "ready" else None,
        "embed_model": E5_MODEL,
        "embedding_dim": EXPECTED_EMBEDDING_DIM,
        "candidate_window": candidate_window,
        "query": query,
        "query_hash": _query_hash(query),
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": quantity,
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def semantic_search_am(
        query: Annotated[
            str,
            Field(
                description=(
                    "Plain-text 検索 query (日本語/English/中国語/한국어 等)。"
                    "jpcite が multilingual-e5-small (384d) で local 推論。"
                    "minimum 2 chars, max 512."
                ),
                min_length=2,
                max_length=512,
            ),
        ],
        top_k: Annotated[
            int,
            Field(
                ge=1,
                le=50,
                description="返す件数 (1..50)。デフォルト 10。",
            ),
        ] = 10,
        rerank: Annotated[
            bool,
            Field(
                description=(
                    "True (default) で cross-encoder reranker を実行 "
                    "(top 50 → top_k)。False で RRF 順そのまま返却。"
                ),
            ),
        ] = True,
        record_kinds: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional record_kind filter (例: ['program','law',"
                    "'case_study'])。None で全 12 record_kind 対象。"
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """いつ使う: plain-text 検索 query から hybrid 検索結果 (BM25 + 384d e5-small + cross-encoder) を返す。入力: query (string 2-512), top_k (1-50, default 10), rerank (bool, default True), record_kinds (optional list). 出力: results (top-k entities w/ canonical_id, primary_name, record_kind, source_url, scores). エラー: db_unavailable で空配列 + state marker。reranker 不在で skipped。"""
        return _semantic_search_impl(
            query=query,
            top_k=top_k,
            rerank=rerank,
            record_kinds=record_kinds,
        )


__all__ = [
    "_semantic_search_impl",
    "_DISCLAIMER",
]
