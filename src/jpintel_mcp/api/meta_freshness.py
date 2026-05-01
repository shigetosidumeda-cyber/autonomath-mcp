"""GET /v1/meta/freshness — public data freshness endpoint.

Backs freshness.jpcite.com. No auth. Aggregates `_meta.fetched_at` from
the enriched canonical files, keyed by unified_id (active entities only).

Anti-詐欺 signal: users can see which programs are stale (> 180 d) and
decide whether to trust / re-verify. This is a first-class transparency
surface, not an internal debug view.

Route:
    GET /v1/meta/freshness
        ?limit=50           (1..500, default 50)
        &sort_by=fetched_at_desc | fetched_at_asc | tier
        &tier=S|A|B|C|all   (default all)

Response shape:
    {
      "total": int,
      "median_fetched_at": "<ISO8601 date>" | null,
      "pct_within_30d": 0..100,
      "pct_over_180d": 0..100,
      "top_rows": [
        {"canonical_id": "UNI-...", "name": "...", "tier": "B",
         "source_fetched_at": "2026-04-20", "days_ago": 4}
      ],
      "generated_at": "<ISO8601>"
    }
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from jpintel_mcp.api._response_models import MetaFreshnessResponse

router = APIRouter(prefix="/v1/meta", tags=["meta", "transparency"])


# ----- path resolution (env override for tests) -------------------------------
def _registry_path() -> Path:
    env = os.environ.get("AUTONOMATH_REGISTRY_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "unified_registry.json"


def _enriched_dir() -> Path:
    env = os.environ.get("AUTONOMATH_ENRICHED_DIR")
    if env:
        return Path(env)
    return (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "knowledge_base"
        / "data"
        / "canonical"
        / "enriched"
    )


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_fetched_at(val: Any) -> Optional[_dt.datetime]:
    if not isinstance(val, str) or not val:
        return None
    v = val.strip()
    # Handle forms: 2026-04-20T10:24:44Z, 2026-04-20, 2026-04-20T10:24:44+00:00
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt
    except ValueError:
        # date-only fallback
        try:
            d = _dt.date.fromisoformat(v[:10])
            return _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.timezone.utc)
        except Exception:  # noqa: BLE001
            return None


# ----- core aggregation (pure, testable) --------------------------------------
def aggregate_freshness(
    registry: dict[str, Any],
    enriched_lookup: dict[str, dict[str, Any]],
    *,
    now: Optional[_dt.datetime] = None,
    tier_filter: str = "all",
) -> dict[str, Any]:
    """Compute freshness summary + per-program rows.

    Args:
      registry: unified_registry.json structure (needs .programs dict).
      enriched_lookup: { unified_id: {"_meta": {"fetched_at": ...}} } or similar.
                      Callers can supply a simplified shape for tests.
      now: override "now" for deterministic tests.
      tier_filter: "all" or a specific tier (S/A/B/C).

    Returns dict with total, median_fetched_at, pct_within_30d, pct_over_180d,
    and a sorted list of all candidate rows (callers pick top N).
    """
    now = now or _utcnow()
    programs = registry.get("programs") or {}
    rows: list[dict[str, Any]] = []

    for uid, prog in programs.items():
        # Only active / non-excluded entries.
        if prog.get("excluded"):
            continue
        status = prog.get("canonical_status")
        if status is not None and status != "active":
            continue
        tier = prog.get("tier")
        if tier_filter != "all" and tier != tier_filter:
            continue

        enriched = enriched_lookup.get(uid) or {}
        meta = enriched.get("_meta") or {}
        fa = meta.get("fetched_at") or enriched.get("fetched_at")
        dt = _parse_fetched_at(fa)
        if dt is None:
            # Skip entries with no canonical fetched_at — they're not ingest-tracked.
            continue

        days_ago = max(0, int((now - dt).total_seconds() // 86400))
        rows.append(
            {
                "canonical_id": uid,
                "name": prog.get("primary_name") or prog.get("name") or "",
                "tier": tier,
                "source_fetched_at": dt.date().isoformat(),
                "days_ago": days_ago,
            }
        )

    total = len(rows)
    median_date: Optional[str] = None
    pct_30 = 0.0
    pct_180 = 0.0
    if rows:
        days = sorted(r["days_ago"] for r in rows)
        median_age = int(statistics.median(days))
        median_date = (now - _dt.timedelta(days=median_age)).date().isoformat()
        pct_30 = round(100.0 * sum(1 for d in days if d <= 30) / total, 2)
        pct_180 = round(100.0 * sum(1 for d in days if d > 180) / total, 2)

    return {
        "total": total,
        "median_fetched_at": median_date,
        "pct_within_30d": pct_30,
        "pct_over_180d": pct_180,
        "rows": rows,
    }


# ----- loaders (cached) -------------------------------------------------------
@lru_cache(maxsize=1)
def _load_registry_cached() -> dict[str, Any]:
    p = _registry_path()
    if not p.exists():
        raise FileNotFoundError(f"registry missing at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_enriched_lookup() -> dict[str, dict[str, Any]]:
    """Build {unified_id: {"_meta": {"fetched_at": <iso>}}} for freshness aggregation.

    Primary source: `programs.source_fetched_at` in jpintel.db. Production does
    not ship the per-program `backend/.../canonical/enriched/*.json` tree; the
    column is the canonical ingest-time stamp.

    Falls back to scanning the enriched JSON dir (legacy / dev) if the env var
    `AUTONOMATH_ENRICHED_DIR` is set and exists. If both fail we return {} and
    the endpoint surfaces total=0, which the caller can detect.
    """
    # 1) DB-backed (production path).
    try:
        from jpintel_mcp.db.session import connect

        out: dict[str, dict[str, Any]] = {}
        with connect() as con:
            cur = con.execute(
                "SELECT unified_id, source_fetched_at FROM programs "
                "WHERE source_fetched_at IS NOT NULL"
            )
            for row in cur:
                uid, fa = row[0], row[1]
                if uid and fa:
                    out[uid] = {"_meta": {"fetched_at": fa}}
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass

    # 2) Legacy filesystem fallback (only if env override exists).
    d = _enriched_dir()
    if not d.exists():
        return {}
    out_fs: dict[str, dict[str, Any]] = {}
    for p in d.iterdir():
        if not (p.is_file() and p.suffix == ".json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        meta = data.get("_meta") or {}
        uid = meta.get("program_id") or p.stem
        out_fs[uid] = {"_meta": meta}
    return out_fs


# ----- endpoint ---------------------------------------------------------------
_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4}


@router.get("/freshness", response_model=MetaFreshnessResponse)
async def meta_freshness(
    limit: int = Query(50, ge=1, le=500),
    sort_by: str = Query("fetched_at_desc", pattern="^(fetched_at_desc|fetched_at_asc|tier)$"),
    tier: str = Query("all", pattern="^(all|S|A|B|C)$"),
) -> dict[str, Any]:
    try:
        registry = _load_registry_cached()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    enriched = _load_enriched_lookup()
    agg = aggregate_freshness(registry, enriched, tier_filter=tier)
    rows = agg["rows"]

    if sort_by == "fetched_at_desc":
        rows.sort(key=lambda r: r["days_ago"])
    elif sort_by == "fetched_at_asc":
        rows.sort(key=lambda r: r["days_ago"], reverse=True)
    else:  # tier
        rows.sort(key=lambda r: (_TIER_ORDER.get(r.get("tier") or "", 99), r["days_ago"]))

    return {
        "total": agg["total"],
        "median_fetched_at": agg["median_fetched_at"],
        "pct_within_30d": agg["pct_within_30d"],
        "pct_over_180d": agg["pct_over_180d"],
        "top_rows": rows[:limit],
        "generated_at": _utcnow_iso(),
    }
