"""Wave 16 F2 — production semantic search endpoint (NO LLM API).

``POST /v1/semantic_search`` returns the top-k canonical entities whose
pre-computed embedding has the smallest cosine distance to the query
embedding supplied by the caller.

THE CLIENT SUPPLIES THE EMBEDDING. jpcite does NOT call any LLM API
provider from this handler. Two operator-side guarantees uphold this:

  * `tests/test_no_llm_in_production.py` (5-axis CI guard) AST-scans
    this file for direct LLM SDK dependencies and for references to
    `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
    `GEMINI_API_KEY` / `GOOGLE_API_KEY`. None of those appear here.
  * The batch embedding driver (`tools/offline/batch_embedding_refresh.py`)
    runs on the operator workstation with a local sentence-transformers
    model. Its output (sqlite-vec rows in `am_canonical_vec_*`) is
    what this handler reads. Production has no path to call out.

Pricing: ¥3/req (¥3.30 incl. 税), single metered event regardless of
``top_k``. Anonymous tier shares the 3/日 IP cap via ``AnonIpLimitDep``
applied at the router mount point in ``api/main.py``.

Vec backend:
    Five tiered virtual tables landed via migration 166 (the canonical
    family) plus the legacy migration 147 tier suffix family. This
    handler reads ONLY the canonical family because they key on the
    stable canonical_id substrate that `tools/offline/embed_canonical_entities.py`
    populates:

        +-----------------+------------------------------+
        | corpus          | vec table                    |
        +-----------------+------------------------------+
        | program         | am_canonical_vec_program     |
        | law             | am_canonical_vec_law         |
        | case_study      | am_canonical_vec_case_study  |
        +-----------------+------------------------------+

    The 4 remaining canonical kinds (enforcement / corporate_entity /
    statistic / tax_measure) are wired in the same loop and selectable
    via ``corpus`` filter; the Wave 16 F2 launch plan only commits the
    3 above.

Cosine similarity:
    The CLIENT is expected to send an L2-normalised float vector
    (multilingual-e5-large convention, dim 1024). The vec0 distance
    column returns L2 distance; for L2-normalised inputs we convert
    to cosine similarity as ``cos_sim = 1 - L2² / 2`` (the standard
    identity on the unit sphere). Both the raw L2 distance and the
    derived cosine similarity are returned so callers can pick either.

Honest gaps:
    * If ``am_canonical_vec_*`` is empty for the requested corpus
      (operator has not yet run the batch driver), the handler returns
      200 with ``results=[]`` and an honest ``corpus_state=empty``
      marker — NOT a 500. Customers calling against a partially-loaded
      corpus get the same shape, just with fewer rows.
    * Dimension is validated up-front. A wrong-dim embedding returns
      422 with a precise message naming the expected dim.
    * sqlite-vec extension load failure (vec0 not available) returns
      503 with ``code=vec_extension_unavailable``. This is the only
      503 path on the endpoint.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import struct
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body, get_corpus_snapshot_id
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.semantic_search")

router = APIRouter(prefix="/v1", tags=["semantic-search"])


# Vec model dimension. Mirrors tools/offline/embed_canonical_entities.py
# (multilingual-e5-large). Hardcoded — clients that pass a different
# dim get a precise 422 instead of a silent vec0 type mismatch.
EXPECTED_EMBEDDING_DIM = 1024

# Default + max top_k. The endpoint is "starter set for an agent" — same
# convention as `discover_related`. Higher caps amplify scan cost
# without adding value (the agent can re-query with a refined embedding).
_DEFAULT_TOP_K = 20
_MAX_TOP_K = 100
_SQLITE_PROGRESS_OPS = 1_000
_KNN_TIMEOUT_MS = int(os.environ.get("SEMANTIC_SEARCH_KNN_TIMEOUT_MS", "2500"))

# Canonical vec family — keyed by canonical_id substrate via the map
# sidecar. Migration 166 created these; tools/offline/embed_canonical_entities.py
# populates them. Order here = supported `corpus` values in the request.
_CORPUS_TO_VEC_TABLE: dict[str, str] = {
    "program": "am_canonical_vec_program",
    "law": "am_canonical_vec_law",
    "case_study": "am_canonical_vec_case_study",
    "enforcement": "am_canonical_vec_enforcement",
    "corporate_entity": "am_canonical_vec_corporate",
    "statistic": "am_canonical_vec_statistic",
    "tax_measure": "am_canonical_vec_tax_measure",
}
_CORPUS_TO_MAP_TABLE: dict[str, str] = {
    "program": "am_canonical_vec_program_map",
    "law": "am_canonical_vec_law_map",
    "case_study": "am_canonical_vec_case_study_map",
    "enforcement": "am_canonical_vec_enforcement_map",
    "corporate_entity": "am_canonical_vec_corporate_map",
    "statistic": "am_canonical_vec_statistic_map",
    "tax_measure": "am_canonical_vec_tax_measure_map",
}

# Wave 16 F2 launch plan only commits the first 3. The remaining 4 are
# wired but flagged as `not_committed` in the response so a caller knows
# the launch plan's quoted row counts (11,601 / 6,493 / 2,286) reflect
# these 3 only.
_F2_COMMITTED = frozenset({"program", "law", "case_study"})


_DISCLAIMER = (
    "embedding-based 類似度 surface; 出力は情報検索結果であり、税務・法務・"
    "経営判断を代替しません。最終確認は一次資料 (source_url) と専門家確認を"
    "必ず経てください。§52 / §47条の2 / 行政書士法 §1 sensitive surface."
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SemanticSearchBody(BaseModel):
    """Request body for ``POST /v1/semantic_search``.

    NOTE: ``embedding`` MUST be pre-computed by the caller (or by the
    caller's agent). jpcite does NOT call any LLM API from this handler.
    Callers using Claude / GPT-4 / Gemini agents should generate the
    embedding on their side and POST it here; jpcite simply returns
    cosine top-k from the pre-built vec corpus.
    """

    model_config = ConfigDict(extra="ignore")

    embedding: list[float] = Field(
        ...,
        description=(
            "L2-normalised float vector of length "
            f"{EXPECTED_EMBEDDING_DIM} (multilingual-e5-large "
            "convention). The caller computes this client-side; jpcite "
            "never calls an LLM API from this endpoint."
        ),
    )
    corpus: str = Field(
        default="program",
        description=(
            "Which canonical corpus to search. Wave 16 F2 commits "
            "{program, law, case_study} (11,601 / 6,493 / 2,286 rows). "
            "Other canonical kinds (enforcement / corporate_entity / "
            "statistic / tax_measure) are wired but not part of the F2 "
            "launch surface."
        ),
    )
    top_k: int = Field(
        default=_DEFAULT_TOP_K,
        ge=1,
        le=_MAX_TOP_K,
        description=(
            f"Top-K rows to return. Clamped to [1, {_MAX_TOP_K}]. Default {_DEFAULT_TOP_K}."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers — pure sqlite + sqlite-vec, NO LLM
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only with sqlite-vec loaded.

    Mirrors the pattern in :mod:`jpintel_mcp.api.discover` so smoke
    tests and production share one helper shape. Returns ``None`` if
    the DB file is missing — handler then returns ``corpus_state=empty``.
    """
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
        # sqlite-vec extension load. Required for the MATCH operator on
        # vec0 virtual tables. Failure → handler returns 503.
        vec0 = os.environ.get("AUTONOMATH_VEC0_PATH")
        if vec0 and Path(vec0).exists():
            try:
                conn.enable_load_extension(True)
                conn.load_extension(vec0)
                conn.enable_load_extension(False)
            except (sqlite3.OperationalError, AttributeError):
                pass
        return conn
    except sqlite3.OperationalError:
        return None


def _encode_embedding(embedding: list[float]) -> bytes:
    """Pack a float list into the little-endian f32 bytes vec0 expects.

    Mirrors what ``embed_canonical_entities.py`` writes — same byte
    layout so MATCH compares apples-to-apples. NO LLM here; just struct
    packing.
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)


def _l2_to_cosine(l2_distance: float) -> float:
    """Convert vec0's L2 distance to cosine similarity on unit-normalised inputs.

    For L2-normalised vectors `a`, `b` on the unit sphere:
        ||a - b||² = 2 - 2·(a·b) = 2·(1 - cos_sim)
    Therefore:
        cos_sim = 1 - (l2_distance²) / 2
    L2 distance is already the square root, so we square it back here.
    Clamped to [-1, 1] to guard against floating-point drift.
    """
    cos_sim = 1.0 - (l2_distance * l2_distance) / 2.0
    if cos_sim > 1.0:
        return 1.0
    if cos_sim < -1.0:
        return -1.0
    return cos_sim


def _vec_table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    """Return True iff the vec table exists AND has at least one row."""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (table,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    if not row:
        return False
    try:
        one_row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return False
    return one_row is not None


def _set_sqlite_deadline(conn: sqlite3.Connection, timeout_ms: int) -> None:
    deadline = time.perf_counter() + (timeout_ms / 1000.0)

    def _progress() -> int:
        return 1 if time.perf_counter() > deadline else 0

    with suppress(sqlite3.OperationalError):
        conn.set_progress_handler(_progress, _SQLITE_PROGRESS_OPS)


def _clear_sqlite_deadline(conn: sqlite3.Connection) -> None:
    with suppress(sqlite3.OperationalError):
        conn.set_progress_handler(None, 0)


def _knn(
    conn: sqlite3.Connection,
    vec_table: str,
    map_table: str,
    embedding_bytes: bytes,
    top_k: int,
) -> list[dict[str, Any]]:
    """Run the canonical vec MATCH + join the map sidecar + am_entities.

    All-in-one SQL — single round-trip. Pure SQLite. NO LLM.

    Returns rows shaped:
        {canonical_id, primary_name, record_kind, source_url,
         l2_distance, cosine_similarity}
    """
    sql = f"""
        SELECT
            v.synthetic_id   AS synthetic_id,
            v.distance       AS l2_distance,
            m.canonical_id   AS canonical_id,
            m.source_text    AS source_text,
            e.primary_name   AS primary_name,
            e.record_kind    AS record_kind,
            e.source_url     AS source_url
          FROM {vec_table} v
          JOIN {map_table} m
            ON m.synthetic_id = v.synthetic_id
          LEFT JOIN am_entities e
            ON e.canonical_id = m.canonical_id
         WHERE v.embedding MATCH ?
           AND k = ?
         ORDER BY v.distance ASC
    """
    try:
        cur = conn.execute(sql, (embedding_bytes, int(top_k)))
        rows = cur.fetchall()
    except sqlite3.OperationalError as exc:
        # Most common cause: vec extension not loaded (MATCH unknown),
        # or table missing on a fresh checkout. The handler maps this
        # to 503 / empty corpus respectively at the caller layer.
        logger.warning("knn failure on %s: %s", vec_table, exc)
        raise

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            l2 = float(r["l2_distance"]) if r["l2_distance"] is not None else math.inf
        except (TypeError, ValueError):
            l2 = math.inf
        out.append(
            {
                "canonical_id": r["canonical_id"],
                "primary_name": r["primary_name"],
                "record_kind": r["record_kind"],
                "source_url": r["source_url"],
                "l2_distance": l2,
                "cosine_similarity": _l2_to_cosine(l2),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/semantic_search",
    summary="Semantic search over jpcite corpora (NO LLM, client-supplied embedding)",
    description=(
        "Return top-k canonical entities by cosine similarity to a "
        "**client-supplied** query embedding. jpcite never calls an LLM "
        "API from this endpoint — the caller (or the caller's agent) "
        "must pre-compute the embedding and POST it here.\n\n"
        "**Wave 16 F2 surface:** ~20,380 entities across the 3 committed "
        "corpora (program 11,601 / law 6,493 / case_study 2,286). "
        "Pre-computed embeddings sit in `am_canonical_vec_*` populated "
        "by `tools/offline/batch_embedding_refresh.py`.\n\n"
        "**Pricing:** ¥3/req (1 unit, regardless of `top_k`). "
        "Anonymous callers share the 3/日 per-IP cap (JST 翌日 00:00 リセット)."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Top-k envelope. `results` is sorted by L2 distance ASC "
                "(== cosine similarity DESC). `corpus_state` flags "
                "whether the requested vec table is populated."
            ),
        },
    },
)
def semantic_search(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[
        SemanticSearchBody,
        Body(
            description=(
                "Pre-computed query embedding + corpus selector. "
                "Client-side embedding ONLY — jpcite does not call any "
                "LLM API from this handler."
            ),
        ),
    ],
) -> dict[str, Any]:
    """POST /v1/semantic_search — production cosine top-k handler."""
    t0 = time.perf_counter()

    # --- 1. Validate corpus ---
    if body.corpus not in _CORPUS_TO_VEC_TABLE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unknown_corpus",
                "message": (
                    f"corpus={body.corpus!r} is not supported; "
                    f"allowed: {sorted(_CORPUS_TO_VEC_TABLE.keys())}"
                ),
            },
        )

    # --- 2. Validate dim ---
    if len(body.embedding) != EXPECTED_EMBEDDING_DIM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "embedding_dim_mismatch",
                "message": (
                    f"embedding length {len(body.embedding)} != "
                    f"expected {EXPECTED_EMBEDDING_DIM} "
                    "(multilingual-e5-large convention)."
                ),
            },
        )

    # --- 3. Open autonomath.db read-only + load sqlite-vec ---
    am = _open_autonomath_ro()
    vec_table = _CORPUS_TO_VEC_TABLE[body.corpus]
    map_table = _CORPUS_TO_MAP_TABLE[body.corpus]

    results: list[dict[str, Any]] = []
    corpus_state = "empty"
    error_marker: str | None = None

    if am is None:
        corpus_state = "db_unavailable"
    elif not _vec_table_has_rows(am, vec_table):
        corpus_state = "empty"
    else:
        emb_bytes = _encode_embedding(body.embedding)
        try:
            _set_sqlite_deadline(am, _KNN_TIMEOUT_MS)
            results = _knn(
                conn=am,
                vec_table=vec_table,
                map_table=map_table,
                embedding_bytes=emb_bytes,
                top_k=body.top_k,
            )
            corpus_state = "ready"
        except sqlite3.OperationalError as exc:
            # MATCH unsupported → vec extension not loaded. This is the
            # documented 503 path.
            error_marker = str(exc)
            if "interrupted" in str(exc).lower():
                corpus_state = "timeout"
            else:
                corpus_state = "vec_extension_unavailable"
        finally:
            _clear_sqlite_deadline(am)

    # --- 4. Close + meter ---
    try:
        if am is not None:
            am.close()
    except Exception:  # noqa: BLE001
        pass

    if corpus_state == "vec_extension_unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vec_extension_unavailable",
                "message": (
                    "sqlite-vec extension is not loaded on this instance; "
                    "semantic_search is temporarily unavailable. "
                    f"backend_error={error_marker!r}"
                ),
            },
        )
    if corpus_state == "timeout":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "semantic_search_timeout",
                "message": (
                    "semantic_search exceeded its local sqlite deadline; "
                    f"backend_error={error_marker!r}"
                ),
            },
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    snapshot_id = get_corpus_snapshot_id()
    body_out: dict[str, Any] = {
        "total": len(results),
        "limit": body.top_k,
        "offset": 0,
        "corpus": body.corpus,
        "corpus_state": corpus_state,
        "corpus_committed_at_launch": body.corpus in _F2_COMMITTED,
        "embedding_dim": EXPECTED_EMBEDDING_DIM,
        "vec_table": vec_table,
        "results": results,
        "corpus_snapshot_id": snapshot_id,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
        "_latency_ms": latency_ms,
    }

    log_usage(
        conn,
        ctx,
        "semantic_search",
        params={"corpus": body.corpus, "top_k": body.top_k},
        latency_ms=latency_ms,
        result_count=len(results),
        quantity=1,
        strict_metering=True,
    )

    attach_seal_to_body(
        body_out,
        endpoint="semantic_search",
        request_params={"corpus": body.corpus, "top_k": body.top_k},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body_out


__all__ = [
    "router",
    "SemanticSearchBody",
    "EXPECTED_EMBEDDING_DIM",
    "_l2_to_cosine",
]
