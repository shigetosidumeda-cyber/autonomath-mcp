"""Public confidence endpoint (P5-attribution / Bayesian Discovery+Use).

GET /v1/stats/confidence
  Returns per-tool Bayesian Discovery + Use posteriors with 95% credible
  intervals, computed live over the last 30 days of `query_log_v2` and
  `usage_events`. No auth, no anon-quota gating — same transparency
  posture as /v1/stats/coverage / /v1/stats/freshness.

PII posture (INV-21):
  * query_log_v2 carries `tool` (label, no free text) + `result_bucket`
    + `api_key_hash` (SHA-256 of the key + pepper, never the key
    itself). Upstream A5 wired the redact_pii filter so even if a
    handler forgets the contract, raw 法人番号 / email / 電話 cannot
    land in this table.
  * usage_events carries `key_hash` + endpoint label only.
  * Output is per-tool aggregates + per-cohort buckets only. Per-customer
    breakdowns are never returned.

Caching:
  * 5-minute in-memory cache (same TTL as stats.py) — recomputing the
    Bayesian posterior over 30 days of rows on every dashboard load
    would be wasteful and noisy.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from jpintel_mcp.analytics.bayesian import (
    discovery_confidence,
    overall_confidence,
    use_confidence,
)
from jpintel_mcp.api._response_models import ConfidenceResponse
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (FastAPI Depends resolution)

router = APIRouter(prefix="/v1/stats", tags=["stats", "transparency"])


# ---------------------------------------------------------------------------
# 5-minute in-memory cache
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 300  # 5 minutes
_CONFIDENCE_WINDOW_DAYS = 30
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _reset_confidence_cache() -> None:
    """Test hook — clear the in-memory cache between scenarios."""
    _cache.clear()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _load_query_log_rows(conn: sqlite3.Connection, since_unix: float) -> list[dict[str, Any]]:
    if not _table_exists(conn, "query_log_v2"):
        return []
    try:
        cur = conn.execute(
            "SELECT tool, result_bucket FROM query_log_v2 WHERE ts >= ?",
            (since_unix,),
        )
    except sqlite3.OperationalError:
        return []
    rows: list[dict[str, Any]] = []
    for r in cur.fetchall():
        rows.append({"tool": r["tool"], "result_bucket": r["result_bucket"]})
    return rows


def _load_usage_event_rows(conn: sqlite3.Connection, since_iso: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "usage_events"):
        return []
    try:
        cur = conn.execute(
            "SELECT key_hash, endpoint AS tool, ts FROM usage_events "
            "WHERE ts >= ? AND key_hash IS NOT NULL",
            (since_iso,),
        )
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        ts_s = r["ts"]
        try:
            if ts_s.endswith("Z"):
                ts_s = ts_s[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_s)
            ts_unix = dt.timestamp()
        except (AttributeError, ValueError):
            continue
        out.append(
            {
                "tool": r["tool"],
                "key_hash": r["key_hash"],
                "ts_unix": ts_unix,
            }
        )
    return out


@router.get("/confidence", response_model=ConfidenceResponse)
def stats_confidence(conn: DbDep) -> dict[str, Any]:
    """Live Bayesian Discovery + Use posteriors per tool, last 30 days."""

    def _compute() -> dict[str, Any]:
        until = datetime.now(UTC)
        since = until - timedelta(days=_CONFIDENCE_WINDOW_DAYS)
        since_unix = since.timestamp()
        since_iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        ql_rows = _load_query_log_rows(conn, since_unix)
        ue_rows = _load_usage_event_rows(conn, since_iso)
        discovery = discovery_confidence(ql_rows)
        use = use_confidence(ue_rows)
        overall = overall_confidence(discovery, use)

        # Side-by-side per-tool array, alpha-sorted by tool name. Only
        # publicly safe fields (no alpha/beta priors, no per-customer).
        per_tool: dict[str, dict[str, Any]] = {}
        for r in discovery.get("per_tool") or []:
            per_tool[r["tool"]] = {
                "tool": r["tool"],
                "discovery": r["discovery"],
                "discovery_ci95": r["ci95"],
                "discovery_hits": r["hits"],
                "discovery_trials": r["trials"],
                "use": None,
                "use_ci95": None,
                "use_hits": 0,
                "use_trials": 0,
                "by_cohort": {
                    cohort: {
                        "discovery": vals["discovery"],
                        "discovery_ci95": vals["ci95"],
                    }
                    for cohort, vals in (r.get("by_cohort") or {}).items()
                },
            }
        for r in use.get("per_tool") or []:
            bag = per_tool.setdefault(
                r["tool"],
                {
                    "tool": r["tool"],
                    "discovery": None,
                    "discovery_ci95": None,
                    "discovery_hits": 0,
                    "discovery_trials": 0,
                    "by_cohort": {},
                },
            )
            bag["use"] = r["use"]
            bag["use_ci95"] = r["ci95"]
            bag["use_hits"] = r["hits"]
            bag["use_trials"] = r["trials"]
            for cohort, vals in (r.get("by_cohort") or {}).items():
                cb = bag["by_cohort"].setdefault(cohort, {})
                cb["use"] = vals["use"]
                cb["use_ci95"] = vals["ci95"]

        per_tool_array = sorted(per_tool.values(), key=lambda x: x["tool"])
        return {
            "window_days": _CONFIDENCE_WINDOW_DAYS,
            "since": since_iso,
            "until": until_iso,
            "overall": overall,
            "per_tool": per_tool_array,
            "generated_at": (
                datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        }

    now = time.time()
    hit = _cache.get("confidence")
    if hit and hit[0] > now:
        return hit[1]
    payload = _compute()
    _cache["confidence"] = (now + _CACHE_TTL_SECONDS, payload)
    return payload
