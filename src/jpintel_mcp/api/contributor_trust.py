"""DEEP-33 contributor trust endpoint.

GET /v1/contribute/trust/{contributor_id} — public read, no auth.

Backed by `contributor_trust` table (migration wave24_182). The math
is implemented in `_contributor_trust.py` (pure SQLite + numpy, NO LLM).

Cache: 60s in-memory dict (per-process). Redis cache is not assumed —
zero-touch operation rule says we don't add Redis dependency just for
this one endpoint. The cache is invalidated by the DEEP-28 approve hook
when a contribution gets approved (see `services/contribution_hook.py`
in DEEP-28; this module exposes `invalidate_cache(contributor_id)` for
that hook to call).

Posture matches `trust.py`:
* Public, no AnonIpLimitDep — trust transparency must always be reachable.
* No §52 sensitive surface; the response carries a non-advice disclaimer
  on the trust_score's meaning.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
import threading
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from jpintel_mcp.api._contributor_trust import (
    HISTORY_BONUS_CAP,
    VERIFIED_THRESHOLD,
    compute_trust_score,
    theta_size_from_db,
)
from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.contributor_trust")

router = APIRouter(prefix="/v1", tags=["contribute", "trust"])

# ---------------------------------------------------------------------------
# In-memory 60s cache (per-process) keyed on contributor_id.
# ---------------------------------------------------------------------------
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> dict[str, Any] | None:
    with _cache_lock:
        item = _cache.get(key)
        if item is None:
            return None
        ts, payload = item
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return dict(payload)


def _cache_put(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), dict(payload))


def invalidate_cache(contributor_id: str | None = None) -> None:
    """Drop one (or all) cache entries. Called by DEEP-28 approve hook."""
    with _cache_lock:
        if contributor_id is None:
            _cache.clear()
        else:
            _cache.pop(contributor_id, None)


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------
_DISCLAIMER = "trust_score は寄稿実績の Bayesian 集約であり、寄稿者の専門資格・人格を保証しない"


class ContributorTrustResponse(BaseModel):
    contributor_id: str
    cohort: str
    trust_score: float = Field(..., ge=0.0, le=1.0)
    cumulative_contributions: int = Field(..., ge=0)
    cumulative_approved: int = Field(..., ge=0)
    cumulative_rejected: int = Field(..., ge=0)
    verified_count: int = Field(..., ge=0)
    history_bonus: float = Field(..., ge=0.0, le=HISTORY_BONUS_CAP)
    temporal_decay_weight: float = Field(..., ge=0.0, le=1.0)
    last_updated: str
    threshold: float = VERIFIED_THRESHOLD
    cached: bool = False
    disclaimer: str = Field(default=_DISCLAIMER, alias="_disclaimer")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Read-only autonomath.db connection. Returns None if DB absent.

    Returning None instead of raising lets the endpoint return a synthetic
    "no data yet" payload during cold-start / test environments.
    """
    db = settings.autonomath_db_path
    if not db.exists():
        return None
    uri = f"file:{db}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.OperationalError as exc:
        _log.warning("autonomath.db RO open failed: %s", exc)
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_row(conn: sqlite3.Connection, contributor_id: str) -> sqlite3.Row | None:
    try:
        cur = conn.execute(
            "SELECT contributor_id, cohort, "
            "       cumulative_contributions, cumulative_approved, "
            "       cumulative_rejected, latest_posterior_score, "
            "       last_updated, temporal_decay_weight, history_bonus "
            "FROM contributor_trust WHERE contributor_id = ?",
            (contributor_id,),
        )
        return cur.fetchone()
    except sqlite3.OperationalError as exc:
        _log.warning("contributor_trust SELECT failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# GET /v1/contribute/trust/{contributor_id}
# ---------------------------------------------------------------------------
@router.get(
    "/contribute/trust/{contributor_id}",
    response_model=ContributorTrustResponse,
    response_model_by_alias=True,
)
async def get_contributor_trust(
    contributor_id: Annotated[
        str,
        PathParam(min_length=1, max_length=128),
    ],
) -> ContributorTrustResponse:
    """Public trust score for one contributor.

    Looks up `contributor_trust` row, recomputes the posterior from the
    persisted (cohort, cumulative_*) tuple, and returns a §52-safe
    transparency payload.
    """
    cached = _cache_get(contributor_id)
    if cached is not None:
        cached["cached"] = True
        return ContributorTrustResponse(**cached)

    conn = _open_autonomath_ro()
    if conn is None:
        raise HTTPException(status_code=503, detail="autonomath.db missing")

    try:
        row = _fetch_row(conn, contributor_id)
        if row is None:
            raise HTTPException(status_code=404, detail="contributor not found")

        cohort = row["cohort"]
        n_total = int(row["cumulative_contributions"] or 0)
        n_approved = int(row["cumulative_approved"] or 0)
        n_rejected = int(row["cumulative_rejected"] or 0)

        # Live Θ-size probe so the posterior reflects current cluster count
        theta_size = theta_size_from_db(conn)

        score = compute_trust_score(
            cohort=cohort,
            cumulative_contributions=n_total,
            cumulative_approved=n_approved,
            cumulative_rejected=n_rejected,
            last_updated_iso=row["last_updated"],
            theta_size=theta_size,
        )

        verified_count = n_approved if score["verified"] else 0

        payload: dict[str, Any] = {
            "contributor_id": contributor_id,
            "cohort": cohort,
            "trust_score": round(score["posterior"], 4),
            "cumulative_contributions": n_total,
            "cumulative_approved": n_approved,
            "cumulative_rejected": n_rejected,
            "verified_count": verified_count,
            "history_bonus": round(score["history_bonus"], 4),
            "temporal_decay_weight": round(score["temporal_decay_weight"], 4),
            "last_updated": row["last_updated"] or _dt.datetime.now(tz=_dt.UTC).isoformat(),
            "threshold": VERIFIED_THRESHOLD,
            "cached": False,
            "_disclaimer": _DISCLAIMER,
        }
        _cache_put(contributor_id, payload)
        return ContributorTrustResponse(**payload)
    finally:
        conn.close()
