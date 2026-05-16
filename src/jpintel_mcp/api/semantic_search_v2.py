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

Performance-safety contract (packet A9 — Wave 43.2.1 hardening)
---------------------------------------------------------------

This module bounds four failure modes:

* **Bounded query time** — every SQLite branch (FTS5 + vec) runs under
  a per-call progress-handler deadline (``_set_sqlite_deadline``) plus
  a request-level ``REQUEST_BUDGET_MS`` deadline that gates whether the
  encode + rerank stages are even attempted. A SQLite ``interrupted``
  raises :class:`SemanticSearchTimeoutError` which the REST handler
  converts to HTTP 503.
* **Vector overfetch** — ``_vec_fetch_limit`` over-fetches by
  ``VECTOR_KIND_OVERFETCH_MULTIPLIER`` only when a ``record_kinds``
  filter is supplied, and the over-fetch is capped at
  ``MAX_VECTOR_FETCH_WINDOW`` rows so a small ``top_k`` cannot cause an
  unbounded vec scan.
* **Model load failures** — both ``_get_e5_model`` and
  ``_get_reranker_model`` are called inside ``_encode_query_e5`` /
  ``_rerank_pairs`` ``try`` blocks that catch a broad family of
  loader errors (``ImportError`` for missing dep, ``OSError`` for I/O
  faults pulling the weights, ``RuntimeError`` for sentence-transformers
  internal failures, ``ValueError`` for malformed config and
  ``Exception`` as a defensive catch-all so a brand-new loader error
  type does not crash the request). On any of these, the circuit opens
  for ``MODEL_CB_COOLDOWN_SECONDS`` and the branch is silently dropped
  (vec branch → empty; reranker → skip and keep RRF order).
* **Stale model circuit** — once the circuit opens it stays open until
  ``MODEL_CB_COOLDOWN_SECONDS`` have elapsed (monotonic clock — wall
  clock jumps cannot reset it). Subsequent calls see
  ``_model_circuit_open()`` and return ``None`` without touching the
  loader, so a model that is genuinely broken (e.g. corrupted cache
  dir) cannot resurface load failures on every request.

Residual P1 (DO NOT REMOVE without process-isolation work)
----------------------------------------------------------

**Local model inference cannot be hard-aborted after it starts.**
Python's ``sentence_transformers.SentenceTransformer.encode`` /
``CrossEncoder.predict`` call into native PyTorch / ONNX kernels which
do **not** check a Python-level cancellation flag once the C++ kernel
is running. Our deadline checks therefore can only:

  1. *Refuse to start* inference if remaining budget is below
     ``ENCODE_START_MIN_REMAINING_MS`` /
     ``RERANK_START_MIN_REMAINING_MS``.
  2. *Open the circuit and discard the result* if the call eventually
     returns past the deadline.

There is no portable way to wall-clock-kill a torch ``encode`` call
from the request thread without (a) moving inference into a separate
process / subprocess pool with ``signal.alarm`` / kill, or
(b) switching to a provider with native cancellation tokens
(gRPC ``Context.with_deadline``, etc.). Both are out of scope for
v0.3.x. Until then, an adversary that triggers an extremely slow
encode can still hold the request thread for the full encode duration
even after the deadline has fired — the only protection is that the
circuit then opens and subsequent requests skip the model entirely.

Documented per packet A9 (parallel_agent_task_matrix_2026-05-13.md
lines 286-313).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import sqlite3
import struct
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, cast

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
MAX_RECORD_KIND_FILTERS = 16
MAX_RECORD_KIND_LENGTH = 64
VECTOR_KIND_OVERFETCH_MULTIPLIER = int(
    os.environ.get("SEMANTIC_SEARCH_V2_VECTOR_KIND_OVERFETCH_MULTIPLIER", "4")
)
MAX_VECTOR_FETCH_WINDOW = int(os.environ.get("SEMANTIC_SEARCH_V2_MAX_VECTOR_FETCH_WINDOW", "200"))
E5_MODEL = "intfloat/multilingual-e5-small"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
SQLITE_PROGRESS_OPS = 1_000
SQLITE_SEARCH_TIMEOUT_MS = int(os.environ.get("SEMANTIC_SEARCH_V2_SQLITE_TIMEOUT_MS", "2500"))
REQUEST_BUDGET_MS = int(os.environ.get("SEMANTIC_SEARCH_V2_REQUEST_BUDGET_MS", "8000"))
ENCODE_START_MIN_REMAINING_MS = int(
    os.environ.get("SEMANTIC_SEARCH_V2_ENCODE_START_MIN_REMAINING_MS", "250")
)
RERANK_START_MIN_REMAINING_MS = int(
    os.environ.get("SEMANTIC_SEARCH_V2_RERANK_START_MIN_REMAINING_MS", "1000")
)
MODEL_CB_COOLDOWN_SECONDS = int(
    os.environ.get("SEMANTIC_SEARCH_V2_MODEL_CB_COOLDOWN_SECONDS", "30")
)
# R3 P1-5: cross-encoder cold-load timeout. First-call model load is normally
# 150-400 ms when the HF cache is warm, but a cold interpreter or evicted file
# cache can balloon to 2 s+. If `_get_reranker_model` exceeds this budget we
# open the model circuit so the request falls back to vector-only RRF order
# instead of holding the request thread on a slow torch import. Tunable via
# SEMANTIC_SEARCH_V2_RERANKER_COLD_LOAD_TIMEOUT_MS for ops; default 2000 ms.
RERANKER_COLD_LOAD_TIMEOUT_MS = int(
    os.environ.get("SEMANTIC_SEARCH_V2_RERANKER_COLD_LOAD_TIMEOUT_MS", "2000")
)

_MODEL_LOCK = threading.Lock()
_E5_MODEL_CACHE: dict[tuple[str, str | None], Any] = {}
_RERANKER_MODEL_CACHE: dict[tuple[str, str | None], Any] = {}
_MODEL_CIRCUIT_OPEN_UNTIL: dict[str, float] = {}

_DISCLAIMER = (
    "hybrid semantic surface (FTS5 + sqlite-vec + cross-encoder reranker); "
    "出力は情報検索結果であり、税務 (税理士法 §52) ・法務 (弁護士法 §72) ・"
    "経営判断を代替しません。最終確認は一次資料 (source_url) と専門家確認を "
    "必ず経てください。§52 / §47条の2 / §72 / 行政書士法 §1の2 sensitive surface."
)


RecordKindFilter = Annotated[str, Field(min_length=1, max_length=MAX_RECORD_KIND_LENGTH)]


class SemanticSearchTimeoutError(RuntimeError):
    """Raised when SQLite interrupts a semantic-search branch by deadline."""


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
    record_kinds: list[RecordKindFilter] | None = Field(
        default=None,
        max_length=MAX_RECORD_KIND_FILTERS,
        description=(
            "Optional record_kind filter (e.g. ['program','law','case_study']). "
            f"At most {MAX_RECORD_KIND_FILTERS} values. When None, all "
            "record_kinds participate."
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
                import sqlite_vec

                sqlite_vec.load(conn)
            except (ImportError, sqlite3.OperationalError, AttributeError):
                pass
        return conn
    except sqlite3.OperationalError:
        return None


def _cache_dir() -> str | None:
    return os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME")


def _model_circuit_open(name: str) -> bool:
    return time.monotonic() < _MODEL_CIRCUIT_OPEN_UNTIL.get(name, 0.0)


def _open_model_circuit(name: str) -> None:
    _MODEL_CIRCUIT_OPEN_UNTIL[name] = time.monotonic() + MODEL_CB_COOLDOWN_SECONDS


def _get_e5_model() -> Any:
    cache_dir = _cache_dir()
    key = (E5_MODEL, cache_dir)
    with _MODEL_LOCK:
        model = _E5_MODEL_CACHE.get(key)
        if model is not None:
            return model
        from sentence_transformers import SentenceTransformer

        kwargs: dict[str, Any] = {}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        model = SentenceTransformer(E5_MODEL, **kwargs)
        _E5_MODEL_CACHE[key] = model
        return model


def _get_reranker_model() -> Any:
    """Load the cross-encoder reranker with a cold-load timeout (R3 P1-5).

    Warm path (cache hit) is constant-time. On a cold first call we measure
    the wall-clock cost of constructing the ``CrossEncoder`` instance: if
    it exceeds ``RERANKER_COLD_LOAD_TIMEOUT_MS`` (default 2000 ms) we open
    the reranker circuit and return ``None`` so the caller falls back to
    pure RRF order. The slow model is *not* cached — a subsequent call
    after the cooldown elapses re-attempts the load. This guards against
    a Python interpreter / HF file-cache eviction event ballooning the
    first call to 2 s+ on a path that is normally 150-400 ms.
    """
    cache_dir = _cache_dir()
    key = (RERANKER_MODEL, cache_dir)
    with _MODEL_LOCK:
        model = _RERANKER_MODEL_CACHE.get(key)
        if model is not None:
            return model
        from sentence_transformers import CrossEncoder

        kwargs: dict[str, Any] = {}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        load_start = time.perf_counter()
        model = CrossEncoder(RERANKER_MODEL, **kwargs)
        load_ms = int((time.perf_counter() - load_start) * 1000)
        if load_ms > RERANKER_COLD_LOAD_TIMEOUT_MS:
            _open_model_circuit(RERANKER_MODEL)
            logger.warning(
                "cross-encoder cold load exceeded budget (%sms > %sms); "
                "circuit opened, model NOT cached",
                load_ms,
                RERANKER_COLD_LOAD_TIMEOUT_MS,
            )
            return None
        _RERANKER_MODEL_CACHE[key] = model
        return model


def _prime_reranker_model_cache(model: Any) -> None:
    """Install a boot-warmed reranker into this module's process cache.

    The ops warmup script constructs the ``CrossEncoder`` itself so it can
    tolerate slow-but-successful cold loads without opening the request-time
    circuit. Once dummy inference succeeds, it calls this helper so the
    first real request in the same interpreter uses the warm model instead
    of repeating construction through ``_get_reranker_model``.
    """
    key = (RERANKER_MODEL, _cache_dir())
    with _MODEL_LOCK:
        _RERANKER_MODEL_CACHE[key] = model
        _MODEL_CIRCUIT_OPEN_UNTIL.pop(RERANKER_MODEL, None)


def _set_sqlite_deadline(conn: sqlite3.Connection, timeout_ms: int) -> None:
    """Install a SQLite progress handler that interrupts the current
    query once ``timeout_ms`` elapses.

    Bounded query time guard #1: SQLite checks the progress callback
    every ``SQLITE_PROGRESS_OPS`` VM ops; returning non-zero causes the
    next op to raise ``OperationalError("interrupted")``, which the
    FTS5 / vec branches translate to :class:`SemanticSearchTimeoutError`.
    Unlike the model deadline guards, this DOES hard-abort the SQLite
    call — sqlite3 surfaces a real cancellation token here, so the
    residual P1 caveat (model inference can't be aborted) does not
    apply to the SQL branch.
    """
    deadline = time.perf_counter() + (timeout_ms / 1000.0)

    def _progress() -> int:
        return 1 if time.perf_counter() > deadline else 0

    with suppress(sqlite3.OperationalError):
        conn.set_progress_handler(_progress, SQLITE_PROGRESS_OPS)


def _clear_sqlite_deadline(conn: sqlite3.Connection) -> None:
    with suppress(sqlite3.OperationalError):
        conn.set_progress_handler(None, 0)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _request_deadline(start: float) -> float:
    return start + (max(0, REQUEST_BUDGET_MS) / 1000.0)


def _remaining_ms(deadline: float | None) -> int | None:
    if deadline is None:
        return None
    return max(0, int((deadline - time.perf_counter()) * 1000))


def _has_remaining_budget(deadline: float | None, min_remaining_ms: int = 0) -> bool:
    remaining = _remaining_ms(deadline)
    return remaining is None or remaining > max(0, min_remaining_ms)


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.perf_counter() >= deadline


def _sqlite_timeout_ms(deadline: float | None) -> int:
    remaining = _remaining_ms(deadline)
    if remaining is None:
        return SQLITE_SEARCH_TIMEOUT_MS
    return max(1, min(SQLITE_SEARCH_TIMEOUT_MS, remaining))


def _should_skip_rerank(deadline: float | None) -> bool:
    return not _has_remaining_budget(deadline, RERANK_START_MIN_REMAINING_MS)


def _projected_cap_response(
    conn: sqlite3.Connection,
    ctx: Any,
    units: int,
) -> Any | None:
    """Run the same exact multi-unit cap gate used by batch endpoints."""
    if units <= 0:
        return None
    from jpintel_mcp.api.middleware.customer_cap import (
        projected_monthly_cap_response,
    )

    return projected_monthly_cap_response(conn, ctx.key_hash, units)


def _encode_query_e5(
    query: str,
    deadline: float | None = None,
    *,
    min_remaining_ms: int = ENCODE_START_MIN_REMAINING_MS,
) -> list[float] | None:
    # Residual P1: once `model.encode` is dispatched into the underlying
    # torch / ONNX kernel we cannot hard-abort it from the request
    # thread. The pre-call budget gate below is the only true "do not
    # start" guard; post-call deadline checks can only discard the
    # result and open the circuit so subsequent calls skip the model.
    if _model_circuit_open(E5_MODEL):
        logger.warning("e5-small circuit open; vec branch skipped")
        return None
    if not _has_remaining_budget(deadline, min_remaining_ms):
        logger.info("e5-small encode skipped; remaining request budget too low")
        return None
    try:
        model = _get_e5_model()
        if _deadline_expired(deadline):
            logger.warning("e5-small encode skipped after model load; request budget exhausted")
            return None
        encode_start = time.perf_counter()
        vec = model.encode(f"query: {query}", normalize_embeddings=True)
        if _deadline_expired(deadline):
            _open_model_circuit(E5_MODEL)
            logger.warning(
                "e5-small encode exceeded request budget (%sms); circuit opened",
                _elapsed_ms(encode_start),
            )
            return None
        return [float(x) for x in vec]
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        # Known loader / runtime failure modes: missing dep, weight I/O
        # fault, internal torch error, malformed model config. Open the
        # circuit so we do not retry the broken loader on every request.
        _open_model_circuit(E5_MODEL)
        logger.warning("e5-small encode failed (%s); vec branch skipped", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - defensive: never crash semantic search on model fault
        # Unknown model failure (e.g. new sentence-transformers exception
        # type in a future upgrade). Treat identically to the known
        # failures above so a single bad model load cannot 500 the
        # endpoint. Logged at warning so it surfaces in monitoring.
        _open_model_circuit(E5_MODEL)
        logger.warning(
            "e5-small encode raised unexpected %s (%s); vec branch skipped",
            type(exc).__name__,
            exc,
        )
        return None


def _rerank_pairs(
    query: str,
    candidates: list[dict[str, Any]],
    deadline: float | None = None,
    *,
    min_remaining_ms: int = RERANK_START_MIN_REMAINING_MS,
) -> list[float] | None:
    # Residual P1: same caveat as `_encode_query_e5` — once
    # `CrossEncoder.predict` dispatches into the underlying kernel we
    # cannot hard-abort. Pre-call budget gate is the only true "do not
    # start" guard; post-call deadline check discards the result and
    # opens the circuit.
    if not candidates:
        return []
    if _model_circuit_open(RERANKER_MODEL):
        logger.warning("cross-encoder circuit open; RRF order kept")
        return None
    if not _has_remaining_budget(deadline, min_remaining_ms):
        logger.info("cross-encoder rerank skipped; remaining request budget too low")
        return None
    try:
        ce = _get_reranker_model()
        if ce is None:
            # R3 P1-5: cold-load timeout rejected the model. Circuit is
            # already opened inside `_get_reranker_model`; skip silently
            # so the request falls back to RRF order.
            logger.info("cross-encoder rerank skipped; cold-load timeout opened circuit")
            return None
        if not _has_remaining_budget(deadline, min_remaining_ms):
            logger.warning("cross-encoder rerank skipped after model load; budget too low")
            return None
        pairs = [(query, c.get("primary_name") or c.get("snippet") or "") for c in candidates]
        rerank_start = time.perf_counter()
        scores = ce.predict(pairs)
        if _deadline_expired(deadline):
            _open_model_circuit(RERANKER_MODEL)
            logger.warning(
                "cross-encoder rerank exceeded request budget (%sms); circuit opened",
                _elapsed_ms(rerank_start),
            )
            return None
        return [float(s) for s in scores]
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        _open_model_circuit(RERANKER_MODEL)
        logger.warning("cross-encoder rerank failed (%s); RRF order kept", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - defensive: never crash semantic search on model fault
        _open_model_circuit(RERANKER_MODEL)
        logger.warning(
            "cross-encoder rerank raised unexpected %s (%s); RRF order kept",
            type(exc).__name__,
            exc,
        )
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
        if "interrupted" in str(exc).lower():
            raise SemanticSearchTimeoutError("fts5 branch exceeded sqlite deadline") from exc
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
    target_limit = max(0, int(limit))
    if target_limit == 0:
        return []
    search_limit = _vec_fetch_limit(target_limit, kinds)
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
        rows = conn.execute(sql, (emb_bytes, int(search_limit))).fetchall()
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise SemanticSearchTimeoutError("vector branch exceeded sqlite deadline") from exc
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
        if len(out) >= target_limit:
            break
    return out


def _vec_fetch_limit(limit: int, kinds: list[str] | None) -> int:
    """Compute the vec k-NN fetch window, applying bounded overfetch
    when a ``record_kinds`` filter would otherwise starve the result.

    Vector overfetch guard: without a ``kinds`` filter the limit is
    passed through unchanged. With a filter we overfetch by
    ``VECTOR_KIND_OVERFETCH_MULTIPLIER`` so post-filter trimming still
    has enough rows, but the result is capped by
    ``MAX_VECTOR_FETCH_WINDOW`` so a small ``top_k`` plus a restrictive
    filter cannot kick off an unbounded vec scan.
    """
    base = max(1, int(limit))
    if not kinds:
        return base
    multiplier = max(1, VECTOR_KIND_OVERFETCH_MULTIPLIER)
    cap = max(base, MAX_VECTOR_FETCH_WINDOW)
    return min(cap, base * multiplier)


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
    quantity = 2 if body.rerank else 1
    cap_response = _projected_cap_response(conn, ctx, quantity)
    if cap_response is not None:
        return cast("dict[str, Any]", cap_response)

    t0 = time.perf_counter()
    deadline = _request_deadline(t0)
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

    try:
        _set_sqlite_deadline(am, _sqlite_timeout_ms(deadline))
        fts = _fts5_search(am, body.query, limit=candidate_window, kinds=body.record_kinds)
    except SemanticSearchTimeoutError as exc:
        with suppress(Exception):
            am.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "semantic_search_timeout",
                "message": (
                    "Semantic search exceeded the database time budget. "
                    "Reduce top_k or filters and retry."
                ),
            },
        ) from exc
    finally:
        _clear_sqlite_deadline(am)

    embedding = _encode_query_e5(body.query, deadline=deadline)
    vec: list[dict[str, Any]] = []
    if (
        embedding is not None
        and len(embedding) == EXPECTED_EMBEDDING_DIM
        and _has_remaining_budget(deadline)
    ):
        try:
            _set_sqlite_deadline(am, _sqlite_timeout_ms(deadline))
            vec = _vec_search(am, embedding, limit=candidate_window, kinds=body.record_kinds)
        except SemanticSearchTimeoutError as exc:
            with suppress(Exception):
                am.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "semantic_search_timeout",
                    "message": (
                        "Semantic search exceeded the database time budget. "
                        "Reduce top_k or filters and retry."
                    ),
                },
            ) from exc
        finally:
            _clear_sqlite_deadline(am)

    fused = _rrf_fuse(fts, vec)
    rrf_state = "ready" if fused else "empty"

    reranker_state = "skipped"
    top = fused[:candidate_window]
    if body.rerank and top:
        if _should_skip_rerank(deadline):
            reranker_state = "timeout_skipped"
        else:
            scores = _rerank_pairs(body.query, top, deadline=deadline)
            if scores is not None and len(scores) == len(top):
                for cand, s in zip(top, scores, strict=True):
                    cand["reranker_score"] = s
                top.sort(key=lambda r: r.get("reranker_score", -math.inf), reverse=True)
                reranker_state = "ready"
            else:
                reranker_state = (
                    "timeout_skipped" if _should_skip_rerank(deadline) else "unavailable"
                )

    final = top[: body.top_k]

    with suppress(Exception):
        am.close()

    latency_ms = int((time.perf_counter() - t0) * 1000)
    snapshot_id = get_corpus_snapshot_id()
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
