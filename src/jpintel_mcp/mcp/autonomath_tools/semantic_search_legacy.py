"""semantic_search_legacy — Wave 46 dim 19 / Dim A booster (v1 legacy MCP wrap).

The v2 hybrid surface (``semantic_search_v2``) is the modern path: BM25 +
sqlite-vec + cross-encoder reranker over the 384-dim e5-small embedding
table ``am_entities_vec_e5`` (one row per ``am_entities`` record). The
v1 / legacy surface at ``POST /v1/semantic_search`` is the original
1024-dim ``multilingual-e5-large`` canonical vec corpus (one row per
``am_entities.canonical_id``), reading the family of 7
``am_canonical_vec_*`` tables from migration 166.

This module wraps the legacy v1 REST handler as an MCP tool so an
agent (Claude / GPT / Gemini) that already has a 1024-dim e5-large
embedding can call us directly without a second HTTP hop. The client
supplies the embedding — jpcite never calls an LLM API from this tool.

Pricing: 1 metered unit / call. Mirrors the REST handler's
``_billing_unit = 1`` (single ¥3/req event regardless of top_k).

NO LLM API
----------
This tool delegates to ``jpintel_mcp.api.semantic_search`` (the v1
REST handler). That handler is documented as having ZERO LLM SDK
imports (see file docstring) and is enforced by the 5-axis CI guard
in ``tests/test_no_llm_in_production.py``. This wrapper adds no new
LLM call paths.

§52 / §47条の2 / §72 / §1 sensitive envelope.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.semantic_search_legacy")

_ENABLED = (
    get_flag(
        "JPCITE_SEMANTIC_SEARCH_LEGACY_ENABLED",
        "AUTONOMATH_SEMANTIC_SEARCH_LEGACY_ENABLED",
        "1",
    )
    == "1"
)

_DISCLAIMER = (
    "legacy v1 surface — 1024d multilingual-e5-large convention over "
    "canonical vec corpus (program / law / case_study + 4 wired-but-not-"
    "launched kinds)。本 response は embedding 類似度 検索結果のみで、"
    "税務代理 (税理士法 §52) ・申請代理 (行政書士法 §1) ・法律事務 "
    "(弁護士法 §72) の代替ではありません。 業務判断は必ず source_url で "
    "一次資料を確認してください。"
)


def _legacy_impl(
    embedding: list[float],
    corpus: str = "program",
    top_k: int = 20,
) -> dict[str, Any]:
    """Delegate to the v1 REST handler logic (in-process, no HTTP).

    Returns the same envelope shape the REST handler emits (less the
    audit seal which is HTTP-layer attached). ``corpus_state`` markers
    are preserved verbatim so the agent can branch on
    ``"empty" / "ready" / "db_unavailable" / "vec_extension_unavailable"``.
    """
    from jpintel_mcp.api.semantic_search import (
        _CORPUS_TO_MAP_TABLE,
        _CORPUS_TO_VEC_TABLE,
        _F2_COMMITTED,
        EXPECTED_EMBEDDING_DIM,
        _encode_embedding,
        _knn,
        _open_autonomath_ro,
        _vec_table_has_rows,
    )

    if corpus not in _CORPUS_TO_VEC_TABLE:
        return {
            "results": [],
            "total": 0,
            "corpus": corpus,
            "corpus_state": "unknown_corpus",
            "allowed_corpus": sorted(_CORPUS_TO_VEC_TABLE.keys()),
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }
    if len(embedding) != EXPECTED_EMBEDDING_DIM:
        return {
            "results": [],
            "total": 0,
            "corpus": corpus,
            "corpus_state": "embedding_dim_mismatch",
            "embedding_dim_actual": len(embedding),
            "embedding_dim_expected": EXPECTED_EMBEDDING_DIM,
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    am = _open_autonomath_ro()
    vec_table = _CORPUS_TO_VEC_TABLE[corpus]
    map_table = _CORPUS_TO_MAP_TABLE[corpus]
    results: list[dict[str, Any]] = []
    corpus_state = "empty"
    if am is None:
        corpus_state = "db_unavailable"
    elif not _vec_table_has_rows(am, vec_table):
        corpus_state = "empty"
    else:
        try:
            results = _knn(
                conn=am,
                vec_table=vec_table,
                map_table=map_table,
                embedding_bytes=_encode_embedding(embedding),
                top_k=int(top_k),
            )
            corpus_state = "ready"
        except Exception as exc:  # noqa: BLE001 — convert all DB errors into envelope
            logger.warning("legacy v1 knn failure: %s", exc)
            corpus_state = "vec_extension_unavailable"
        finally:
            with contextlib.suppress(Exception):
                am.close()

    return {
        "results": results,
        "total": len(results),
        "corpus": corpus,
        "corpus_state": corpus_state,
        "corpus_committed_at_launch": corpus in _F2_COMMITTED,
        "embedding_dim": EXPECTED_EMBEDDING_DIM,
        "vec_table": vec_table,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def semantic_search_legacy_am(
        embedding: Annotated[
            list[float],
            Field(
                description=(
                    "Pre-computed 1024-dim L2-normalised float vector "
                    "(multilingual-e5-large convention). 顧客側 LLM "
                    "/ encoder で生成し、jpcite に渡してください。 "
                    "jpcite は LLM API を呼びません。"
                ),
            ),
        ],
        corpus: Annotated[
            str,
            Field(
                description=(
                    "対象 corpus。デフォルト 'program'。F2 launch commit "
                    "= {program, law, case_study}。 ほか {enforcement, "
                    "corporate_entity, statistic, tax_measure} も wired。"
                ),
            ),
        ] = "program",
        top_k: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description="返す件数 (1..100)。デフォルト 20。",
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """いつ使う: 1024-dim e5-large embedding を持つ agent が canonical 1-row-per-canonical_id corpus で cosine top-k を 1 call で取りたい時。 入力: embedding (1024d L2-normalised float list), corpus (default 'program'), top_k (1-100, default 20)。 出力: results (canonical_id / primary_name / record_kind / source_url / l2_distance / cosine_similarity)、corpus_state ('ready' | 'empty' | 'db_unavailable' | 'vec_extension_unavailable' | 'unknown_corpus' | 'embedding_dim_mismatch')。 エラーは envelope に包んで 200 を返す (例外を投げない)。"""
        return _legacy_impl(embedding=embedding, corpus=corpus, top_k=top_k)


__all__ = ["_legacy_impl"]
