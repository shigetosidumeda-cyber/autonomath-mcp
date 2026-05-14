"""GET/POST /v1/intel/actionable/* — pre-rendered actionable Q/A cache.

Wave 30-5 RE-RUN landing surface. Top-N (intent_class × input_dict) tuples are
precomputed offline by `scripts/cron/precompute_actionable_answers.py` into
`am_actionable_qa_cache` (migration 169). The endpoints below let the customer
LLM either:

  1. GET  /v1/intel/actionable/{cache_key}        — direct key lookup
  2. POST /v1/intel/actionable/lookup             — body={intent_class,
                                                          input_dict}
                                                    server hashes input

Why a separate cache from migration 168's `am_actionable_answer_cache`:
  * 168 is keyed by (subject_kind, subject_id) and only fits the
    program/houjin/match 360-style composites.
  * The W28-5 instrumentation measured 0% cache-hit on the on-demand
    composite path because the actual user intents arrive as parameter
    SHAPES (subsidy_search by pref+industry, eligibility_check by
    program×houjin_size, amendment_diff by program, citation_pack by
    program) — none of which the (subject_kind, subject_id) key can
    represent without a synthetic encoding.
  * The new (cache_key, intent_class, input_hash) layout matches the way
    the populator enumerates top combos (47 pref × 7 industries =
    329 subsidy_search rows etc.) and the way the customer LLM phrases
    their queries.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside the endpoint. Pure SQLite + sha256 hash.
* The endpoint never composes — it only reads pre-rendered envelopes.
  On miss it returns 404 with `{_not_cached: true}` so the caller knows
  to either (a) call the on-demand composer or (b) wait for the next
  precompute window.
* hit_count is bumped via a single UPDATE (no transaction overhead).
  The bump is best-effort — if the writable connection fails (rare), the
  envelope is still returned.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.intel_actionable")

router = APIRouter(prefix="/v1/intel/actionable", tags=["intel"])


# Allowed intent classes — MUST match what the populator enumerates.
# Keep this list narrow; widening it is a deliberate Wave-bump decision so
# the populator's combo budget stays predictable.
ALLOWED_INTENTS: frozenset[str] = frozenset(
    {
        "subsidy_search",
        "eligibility_check",
        "amendment_diff",
        "citation_pack",
    }
)


# §52 / 行政書士法 §1の2 / 公認会計士法 §47条の2 disclaimer envelope. The cached
# JSON already contains this; the lookup endpoint preserves it verbatim. The
# constant lives here so a stale cached row that lost its disclaimer (e.g.
# manual surgery on the table) still gets one re-attached on the way out.
_DISCLAIMER_FALLBACK = (
    "本キャッシュ済みエンベロープは jpcite が公的機関 (各省庁・自治体・国税庁・"
    "日本政策金融公庫 等) の公開情報を機械的に整理した結果を返却するものであり、"
    "税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1の2 に基づく個別具体的な"
    "税務助言・監査意見・申請書面作成の代替ではありません。最終的な申請可否・"
    "税務判断は資格を有する士業へご相談ください。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_input_hash(input_dict: dict[str, Any]) -> str:
    """Return sha256-hex of the canonical-JSON encoding of ``input_dict``.

    Canonical JSON = ``sort_keys=True`` + ``separators=(',', ':')`` +
    ``ensure_ascii=False``. The same canonicalisation is used by the
    populator so a customer LLM that hashes its own input can predict the
    cache key without server round-trip.
    """
    blob = json.dumps(input_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_cache_key(intent_class: str, input_hash: str) -> str:
    """Return the canonical cache_key for (intent_class, input_hash)."""
    return f"{intent_class}:{input_hash}"


def _open_autonomath_rw() -> sqlite3.Connection:
    """Writable connection to autonomath.db at the configured path.

    Mirrors ``api/audit_proof._open_autonomath_rw``. We use a non-cached
    open here because the hit_count UPDATE happens on the request thread
    and we do not want to pin a per-thread connection in the
    autonomath_tools.db pool.
    """
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table_exists(conn: sqlite3.Connection) -> bool:
    """Best-effort idempotent CREATE TABLE so the endpoint stays self-healing
    even when migration 169 has not yet been applied (fresh dev DB, CI
    sandbox). Returns True on success, False if even the CREATE failed
    (extremely rare; surfaced as 503 by the caller).
    """
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
                  cache_key             TEXT PRIMARY KEY,
                  intent_class          TEXT NOT NULL,
                  input_hash            TEXT NOT NULL,
                  rendered_answer_json  TEXT NOT NULL,
                  rendered_at           INTEGER NOT NULL,
                  hit_count             INTEGER NOT NULL DEFAULT 0,
                  corpus_snapshot_id    TEXT NOT NULL
                )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_am_actionable_intent_hash "
            "ON am_actionable_qa_cache(intent_class, input_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_am_actionable_rendered_at "
            "ON am_actionable_qa_cache(rendered_at DESC)"
        )
        conn.commit()
        return True
    except sqlite3.OperationalError as exc:
        logger.warning("am_actionable_qa_cache CREATE TABLE failed: %s", exc)
        return False


def _lookup_cache_row(conn: sqlite3.Connection, cache_key: str) -> dict[str, Any] | None:
    """SELECT one row by cache_key. Bumps hit_count on hit (best-effort)."""
    try:
        row = conn.execute(
            "SELECT cache_key, intent_class, input_hash, rendered_answer_json, "
            "rendered_at, hit_count, corpus_snapshot_id "
            "FROM am_actionable_qa_cache WHERE cache_key = ? LIMIT 1",
            (cache_key,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        logger.warning("am_actionable_qa_cache SELECT failed: %s", exc)
        return None
    if row is None:
        return None
    # Bump hit_count — best effort; never fail the read on this.
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "UPDATE am_actionable_qa_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )
        conn.commit()
    return dict(row)


def _wrap_envelope(
    row: dict[str, Any],
    *,
    request: Request | None,
    cache_key: str,
) -> dict[str, Any]:
    """Parse the rendered_answer_json blob and attach the standard wrapper.

    The wrapper preserves whatever was stored (including any pre-existing
    `_disclaimer` / `corpus_snapshot_id`) and re-asserts:
      * `_billing_unit: 1` (cache hits are still ¥3 metered — that is the
        product, not a discount lever)
      * `_disclaimer` (fallback if the cached blob was somehow stripped)
      * `corpus_snapshot_id` (mirrored from the cache row's column so the
        auditor can verify the cache was warmed against the same snapshot
        the on-demand path would have used)
      * `_cache_meta` — bookkeeping for the customer LLM (hit_count + age
        + intent_class + input_hash for traceability)
    """
    try:
        body = json.loads(row["rendered_answer_json"])
    except (TypeError, ValueError) as exc:
        logger.error("rendered_answer_json parse failed for %s: %s", cache_key, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "cached_envelope_corrupt",
                "cache_key": cache_key,
                "message": "rendered_answer_json could not be JSON-decoded.",
            },
        ) from exc
    if not isinstance(body, dict):
        # Cached blob must be a dict envelope; anything else is corrupt.
        raise HTTPException(
            status_code=500,
            detail={
                "error": "cached_envelope_not_dict",
                "cache_key": cache_key,
                "type": type(body).__name__,
            },
        )

    body.setdefault("_disclaimer", _DISCLAIMER_FALLBACK)
    body.setdefault("_billing_unit", 1)
    body["corpus_snapshot_id"] = row["corpus_snapshot_id"]
    body["_cache_meta"] = {
        "cache_hit": True,
        "cache_key": cache_key,
        "intent_class": row["intent_class"],
        "input_hash": row["input_hash"],
        "rendered_at": row["rendered_at"],
        "hit_count": int(row["hit_count"]) + 1,  # post-bump value
        "age_seconds": max(0, int(time.time()) - int(row["rendered_at"])),
        "basis_table": "am_actionable_qa_cache",
    }
    if request is not None and wants_compact(request):
        return to_compact(body)
    return body


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ActionableLookupRequest(BaseModel):
    """POST body for /v1/intel/actionable/lookup."""

    intent_class: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=("Intent class name. Must be one of: " + ", ".join(sorted(ALLOWED_INTENTS))),
    )
    input_dict: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Canonicalised input parameters. Server hashes via sha256 over "
            "json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=False)."
        ),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{cache_key}",
    summary="Direct cache key lookup for a pre-rendered actionable Q/A envelope",
    description=(
        "Returns the cached envelope when present (`hit_count` bumped) or "
        "404 with `{_not_cached: true}` when the cache_key is unknown. "
        "Use POST /v1/intel/actionable/lookup if you would prefer the "
        "server to compute the cache_key from `(intent_class, input_dict)`. "
        "Both surfaces are ¥3 metered (`_billing_unit: 1`). NO LLM call."
    ),
    responses={
        200: {"description": "Cached envelope."},
        404: {"description": "Cache miss — _not_cached flag set."},
        503: {"description": "autonomath.db unavailable."},
    },
)
def get_actionable(
    cache_key: Annotated[
        str,
        Path(min_length=1, max_length=256, description="cache_key (intent_class:input_hash)"),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()
    try:
        am_conn = _open_autonomath_rw()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": str(exc),
            },
        ) from exc
    try:
        # Self-heal: the table is created by migration 169 + entrypoint.sh,
        # but in test/dev we tolerate a missing table by creating it now.
        _ensure_table_exists(am_conn)
        row = _lookup_cache_row(am_conn, cache_key)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    latency_ms = int((time.perf_counter() - _t0) * 1000)

    if row is None:
        miss_body: dict[str, Any] = {
            "_not_cached": True,
            "cache_key": cache_key,
            "_disclaimer": _DISCLAIMER_FALLBACK,
            "_billing_unit": 1,
            "_cache_meta": {
                "cache_hit": False,
                "cache_key": cache_key,
                "basis_table": "am_actionable_qa_cache",
            },
        }
        miss_body = attach_corpus_snapshot(miss_body, conn)
        log_usage(
            conn,
            ctx,
            "intel.actionable.get",
            status_code=404,
            latency_ms=latency_ms,
            result_count=0,
            params={"cache_key": cache_key, "hit": False},
        )
        attach_seal_to_body(
            miss_body,
            endpoint="intel.actionable.get",
            request_params={"cache_key": cache_key},
            api_key_hash=ctx.key_hash,
            conn=conn,
        )
        return JSONResponse(status_code=404, content=miss_body)

    body = _wrap_envelope(row, request=request, cache_key=cache_key)
    log_usage(
        conn,
        ctx,
        "intel.actionable.get",
        latency_ms=latency_ms,
        result_count=1,
        strict_metering=True,
        params={
            "cache_key": cache_key,
            "intent_class": row["intent_class"],
            "hit": True,
        },
    )
    attach_seal_to_body(
        body,
        endpoint="intel.actionable.get",
        request_params={"cache_key": cache_key},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(status_code=200, content=body)


@router.post(
    "/lookup",
    summary="Compute cache_key from (intent_class, input_dict) and look up",
    description=(
        "Server canonicalises `input_dict` via sort_keys=True + "
        "separators=(',',':') + ensure_ascii=False, then sha256-hashes the "
        'resulting blob. The cache_key is `f"{intent_class}:{input_hash}"`. '
        "On hit returns the cached envelope (200). On miss returns 404 with "
        "`{_not_cached: true, intent_class, input_hash, cache_key}` so the "
        "caller can either (a) fall through to the on-demand composer or "
        "(b) wait for the next precompute window. Same ¥3 metering as GET. "
        "NO LLM call."
    ),
    responses={
        200: {"description": "Cached envelope."},
        404: {"description": "Cache miss — _not_cached flag set."},
        422: {"description": "intent_class not in ALLOWED_INTENTS."},
        503: {"description": "autonomath.db unavailable."},
    },
)
def post_actionable_lookup(
    payload: Annotated[ActionableLookupRequest, Body(...)],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    intent_class = payload.intent_class.strip()
    if intent_class not in ALLOWED_INTENTS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_intent_class",
                "field": "intent_class",
                "allowed": sorted(ALLOWED_INTENTS),
                "got": intent_class,
            },
        )

    input_hash = canonical_input_hash(payload.input_dict)
    cache_key = build_cache_key(intent_class, input_hash)

    try:
        am_conn = _open_autonomath_rw()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": str(exc),
            },
        ) from exc
    try:
        _ensure_table_exists(am_conn)
        row = _lookup_cache_row(am_conn, cache_key)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    latency_ms = int((time.perf_counter() - _t0) * 1000)

    if row is None:
        miss_body: dict[str, Any] = {
            "_not_cached": True,
            "intent_class": intent_class,
            "input_hash": input_hash,
            "cache_key": cache_key,
            "_disclaimer": _DISCLAIMER_FALLBACK,
            "_billing_unit": 1,
            "_cache_meta": {
                "cache_hit": False,
                "cache_key": cache_key,
                "intent_class": intent_class,
                "input_hash": input_hash,
                "basis_table": "am_actionable_qa_cache",
            },
        }
        miss_body = attach_corpus_snapshot(miss_body, conn)
        log_usage(
            conn,
            ctx,
            "intel.actionable.lookup",
            status_code=404,
            latency_ms=latency_ms,
            result_count=0,
            params={
                "intent_class": intent_class,
                "input_hash": input_hash,
                "hit": False,
            },
        )
        attach_seal_to_body(
            miss_body,
            endpoint="intel.actionable.lookup",
            request_params={
                "intent_class": intent_class,
                "input_hash": input_hash,
            },
            api_key_hash=ctx.key_hash,
            conn=conn,
        )
        return JSONResponse(status_code=404, content=miss_body)

    body = _wrap_envelope(row, request=request, cache_key=cache_key)
    log_usage(
        conn,
        ctx,
        "intel.actionable.lookup",
        latency_ms=latency_ms,
        result_count=1,
        strict_metering=True,
        params={
            "intent_class": intent_class,
            "input_hash": input_hash,
            "hit": True,
        },
    )
    attach_seal_to_body(
        body,
        endpoint="intel.actionable.lookup",
        request_params={
            "intent_class": intent_class,
            "input_hash": input_hash,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(status_code=200, content=body)
