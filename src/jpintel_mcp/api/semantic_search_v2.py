"""Wave 43.2.1 — Dim A semantic search v2 (hybrid FTS5 + sqlite-vec + reranker).

``POST /v1/search/semantic`` returns top-k canonical entities for a
plain-text query by fusing:

  1. FTS5 BM25 results over ``am_entities_fts``,
  2. sqlite-vec k-NN over ``am_entities_vec_e5`` (384-dim e5-small),
  3. cross-encoder reranker (MS-MARCO-MiniLM-L-6-v2) on top 50 → top 10.

Pricing: 1 request = **2 metered units** (¥6 incl. 税). The heavier
billing reflects the reranker inference cost vs the 1-unit
``/v1/semantic_search`` (which only does cosine k-NN with no rerank).

NO LLM API import: the only inference is via local
``sentence_transformers`` (e5-small) + ``sentence_transformers.CrossEncoder``
(MS-MARCO-MiniLM-L-6-v2). All inference is local CPU.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body, get_corpus_snapshot_id
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.semantic_search_v2")

router = APIRouter(prefix="/v1", tags=["semantic-search-v2"])

EXPECTED_EMBEDDING_DIM = 384
RRF_K = 60
DEFAULT_TOP_K = 10
DEFAULT_CANDIDATE_WINDOW = 50
MAX_TOP_K = 50
E5_MODEL = "intfloat/multilingual-e5-small"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_DISCLAIMER = (
    "hybrid semantic surface (FTS5 + sqlite-vec + cross-encoder reranker); "
    "出力は情報検索結果であり、税務 (税理士法 §52) ・法務 (弁護士法 §72) ・"
    "経営判断を代替しません。最終確認は一次資料 (source_url) と専門家確認を "
    "必ず経てください。§52 / §47条の2 / §72 / 行政書士法 §1 sensitive surface."
)


class SemanticSearchV2Body(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(
        ...,
        min_length=2,
        max_length=512,
        description=(
            "Plain-text query in any language. jpcite encodes locally "
            "with multilingual-e5-small (384-dim) — no LLM API call."
        ),
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description=f"Top-K rows to return. Clamped to [1, {MAX_TOP_K}].",
    )
    rerank: bool = Field(
        default=True,
        description=(
            "If True (default), run cross-encoder reranker on top 50 → "
            "top_k. If False, return RRF-merged FTS5 + vec results."
        ),
    )
    record_kinds: list[str] | None = Field(
        default=None,
        description=(
            "Optional record_kind filter (e.g. ['program','law','case_study']). "
            "When None, all 12 record_kinds participate."
        ),
    )


def _open_autonomath_ro() -> sqlite3.Connection | None:
    p: Path = settings.autonomath_db_path
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.OperationalError:
            pass
        vec0 = os.environ.get("AUTONOMATH_VEC0_PATH")
        if vec0 and Path(vec0).exists():
            try:
                conn.enable_load_extension(True)
                conn.load_extension(vec0)
                conn.enable_load_extension(False)
            except (sqlite3.OperationalError, AttributeError):
                pass
        else:
            try:
                conn.enable_load_extension(True)
                import sqlite_vec  # type: ignore[import-not-found]

                sqlite_vec.load(conn)
            except (ImportError, sqlite3.OperationalError, AttributeError):
                pass
        return conn
    except sqlite3.OperationalError:
        return None


def _encode_query_e5(query: str) -> list[float] | None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        cache_dir = os.environ.get("HF_HOME") or os.environ.get(
            "SENTENCE_TRANSFORMERS_HOME"
        )
        kwargs: dict[str, Any] = {}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        model = SentenceTransformer(E5_MODEL, **kwargs)
        vec = model.encode(f"query: {query}", normalize_embeddings=True)
        return [float(x) for x in vec]
    except (ImportError, OSError, RuntimeError) as exc:
        logger.warning("e5-small encode failed (%s); vec branch skipped", exc)
        return None


def _rerank_pairs(query: str, candidates: list[dict[str, Any]]) -> list[float] | None:
    if not candidates:
        return []
    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

        cache_dir = os.environ.get("HF_HOME") or os.environ.get(
            "SENTENCE_TRANSFORMERS_HOME"
        )
        kwargs: dict[str, Any] = {}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        ce = CrossEncoder(RERANKER_MODEL, **kwargs)
        pairs = [
            (query, c.get("primary_name") or c.get("snippet") or "") for c in candidates
        ]
        scores = ce.predict(pairs)
        return [float(s) for s in scores]
    except (ImportError, OSError, RuntimeError) as exc:
        logger.warning("cross-encoder rerank failed (%s); RRF order kept", exc)
        return None


def _serialize_vec(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()


def _fts5_search(
    conn: sqlite3.Connection, query: str, limit: int, kinds: list[str] | None
) -> list[dict[str, Any]]:
    safe = query.replace('"', '""')
    where_kind = ""
    params: list[Any] = [f'"{safe}"', int(limit)]
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        where_kind = f"AND e.record_kind IN ({placeholders}) "
        params = [f'"{safe}"', *kinds, int(limit)]
    sql = f"""
        SELECT e.rowid AS rid,
               e.canonical_id AS cid,
               e.primary_name AS pn,
               e.record_kind AS rk,
               e.source_url AS surl,
               bm25(am_entities_fts) AS bm25_score
        FROM am_entities_fts
        JOIN am_entities e ON e.rowid = am_entities_fts.rowid
        WHERE am_entities_fts MATCH ?
        {where_kind}
        ORDER BY bm25_score ASC
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("FTS5 search failed: %s", exc)
        return []
    return [
        {
            "rid": int(r["rid"]),
            "canonical_id": r["cid"],
            "primary_name": r["pn"],
            "record_kind": r["rk"],
            "source_url": r["surl"],
            "bm25_score": float(r["bm25_score"]) if r["bm25_score"] is not None else 0.0,
        }
        for r in rows
    ]


def _vec_search(
    conn: sqlite3.Connection,
    embedding: list[float],
    limit: int,
    kinds: list[str] | None,
) -> list[dict[str, Any]]:
    emb_bytes = _serialize_vec(embedding)
    sql = """
        SELECT v.entity_id AS rid,
               v.distance   AS l2,
               e.canonical_id AS cid,
               e.primary_name AS pn,
               e.record_kind AS rk,
               e.source_url AS surl
        FROM am_entities_vec_e5 v
        LEFT JOIN am_entities e ON e.rowid = v.entity_id
        WHERE v.embedding MATCH ?
          AND k = ?
        ORDER BY v.distance ASC
    """
    try:
        rows = conn.execute(sql, (emb_bytes, int(limit))).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("vec search failed: %s", exc)
        return []
    out = []
    for r in rows:
        if kinds and r["rk"] not in kinds:
            continue
        l2 = float(r["l2"]) if r["l2"] is not None else math.inf
        out.append(
            {
                "rid": int(r["rid"]),
                "canonical_id": r["cid"],
                "primary_name": r["pn"],
                "record_kind": r["rk"],
                "source_url": r["surl"],
                "l2_distance": l2,
                "cosine_similarity": max(-1.0, min(1.0, 1.0 - (l2 * l2) / 2.0)),
            }
        )
    return out


def _rrf_fuse(
    fts: list[dict[str, Any]],
    vec: list[dict[str, Any]],
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    scores: dict[int, float] = {}
    rows: dict[int, dict[str, Any]] = {}
    for rank, r in enumerate(fts, start=1):
        rid = r["rid"]
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
        rows[rid] = {**rows.get(rid, {}), **r, "fts_rank": rank}
    for rank, r in enumerate(vec, start=1):
        rid = r["rid"]
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
        rows[rid] = {**rows.get(rid, {}), **r, "vec_rank": rank}
    fused = []
    for rid, score in scores.items():
        merged = rows[rid]
        merged["rrf_score"] = score
        fused.append(merged)
    fused.sort(key=lambda r: r["rrf_score"], reverse=True)
    return fused


@router.post(
    "/search/semantic",
    summary="Hybrid semantic search v2 (FTS5 + e5-small + cross-encoder)",
    description=(
        "Plain-text semantic search over the unified am_entities corpus "
        "(503,930+ entities). Combines BM25 (FTS5) + cosine k-NN (sqlite-vec "
        "384-dim e5-small) via Reciprocal Rank Fusion + optional cross-"
        "encoder reranker (MS-MARCO-MiniLM-L-6-v2). All inference local — "
        "NO LLM API call.\n\n"
        "**Pricing:** ¥6/req (2 metered units — reranker cost; 1 unit when "
        "`rerank=false`). Anonymous tier shares the 3 req/日 IP cap."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Hybrid top-k envelope."},
    },
)
def search_semantic(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[
        SemanticSearchV2Body,
        Body(description="Plain-text query + top_k + rerank flag"),
    ],
) -> dict[str, Any]:
    t0 = time.perf_counter()
    am = _open_autonomath_ro()
    if am is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "autonomath_db_unavailable",
                "message": "autonomath.db is not available on this instance.",
            },
        )

    candidate_window = min(DEFAULT_CANDIDATE_WINDOW, max(body.top_k * 4, 20))

    fts = _fts5_search(am, body.query, limit=candidate_window, kinds=body.record_kinds)

    embedding = _encode_query_e5(body.query)
    vec: list[dict[str, Any]] = []
    if embedding is not None and len(embedding) == EXPECTED_EMBEDDING_DIM:
        vec = _vec_search(am, embedding, limit=candidate_window, kinds=body.record_kinds)

    fused = _rrf_fuse(fts, vec)
    rrf_state = "ready" if fused else "empty"

    reranker_state = "skipped"
    top = fused[:candidate_window]
    if body.rerank and top:
        scores = _rerank_pairs(body.query, top)
        if scores is not None and len(scores) == len(top):
            for cand, s in zip(top, scores, strict=True):
                cand["reranker_score"] = s
            top.sort(key=lambda r: r.get("reranker_score", -math.inf), reverse=True)
            reranker_state = "ready"
        else:
            reranker_state = "unavailable"

    final = top[: body.top_k]

    try:
        am.close()
    except Exception:  # noqa: BLE001
        pass

    latency_ms = int((time.perf_counter() - t0) * 1000)
    snapshot_id = get_corpus_snapshot_id()
    quantity = 2 if body.rerank else 1
    body_out: dict[str, Any] = {
        "total": len(final),
        "limit": body.top_k,
        "candidate_window": candidate_window,
        "query": body.query,
        "query_hash": _query_hash(body.query),
        "embedding_dim": EXPECTED_EMBEDDING_DIM,
        "fts_count": len(fts),
        "vec_count": len(vec),
        "rrf_state": rrf_state,
        "reranker_state": reranker_state,
        "reranker_model": RERANKER_MODEL if reranker_state == "ready" else None,
        "embed_model": E5_MODEL,
        "results": final,
        "corpus_snapshot_id": snapshot_id,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": quantity,
        "_latency_ms": latency_ms,
    }

    log_usage(
        conn,
        ctx,
        "search_semantic",
        params={"query_len": len(body.query), "top_k": body.top_k, "rerank": body.rerank},
        latency_ms=latency_ms,
        result_count=len(final),
        quantity=quantity,
        strict_metering=True,
    )
    attach_seal_to_body(
        body_out,
        endpoint="search_semantic",
        request_params={"top_k": body.top_k, "rerank": body.rerank},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body_out


__all__ = [
    "router",
    "SemanticSearchV2Body",
    "EXPECTED_EMBEDDING_DIM",
    "_rrf_fuse",
    "_query_hash",
]
