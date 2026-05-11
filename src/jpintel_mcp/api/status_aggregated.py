"""Wave 41 Agent H — aggregated status REST endpoint.

Provides ``GET /v1/status/all`` and ``GET /v1/status/alerts`` so agents can
fetch the union of the 5 specialty dashboards (RUM / 9-axis audit / data
freshness / 6-axis sanity / cron health) plus the active alert list in
**one fetch**.

The hot path is pure JSON I/O — it reads pre-computed snapshot files
produced by ``scripts/cron/aggregate_status_alerts_hourly.py`` and the
existing per-dashboard cron writers. Zero DB access, zero LLM, zero
external HTTP. When a snapshot file is missing the route returns it as
``None`` (honest-null) instead of 500, so agents can distinguish "not yet
probed" from "broken".

Public posture: no auth, no AnonIpLimitDep — same transparency surface as
``meta_freshness_router`` and ``six_axis_status_router``. Browser/CDN
cache is 3 minutes (matches the hourly cron granularity plus margin).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE_STATUS = REPO_ROOT / "site" / "status"
ANALYTICS = REPO_ROOT / "analytics"

# Snapshot file paths (best-effort; missing files degrade to ``None``).
RUM_JSON = SITE_STATUS / "rum.json"
STATUS_JSON = SITE_STATUS / "status.json"
SIX_AXIS_JSON = ANALYTICS / "six_axis_status.json"
FRESHNESS_JSON = ANALYTICS / "freshness_rollup.json"
CRON_HEALTH_JSON = ANALYTICS / "cron_health_24h.json"
ALERTS_JSON = SITE_STATUS / "status_alerts_w41.json"

# Environment overrides — same convention as six_axis_status.
_ENV_PATHS = {
    "rum": "STATUS_RUM_PATH",
    "status": "STATUS_AUDIT_PATH",
    "six_axis": "STATUS_SIX_AXIS_PATH",
    "freshness": "STATUS_FRESHNESS_PATH",
    "cron_health": "STATUS_CRON_HEALTH_PATH",
    "alerts": "STATUS_ALERTS_PATH",
}


router = APIRouter(prefix="/v1/status", tags=["status", "transparency"])


def _resolve(default: Path, env_var: str) -> Path:
    env = os.environ.get(env_var, "").strip()
    if env:
        return Path(env)
    return default


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _attach_cache_headers(response: Response, max_age: int = 180) -> None:
    response.headers["Cache-Control"] = f"public, max-age={max_age}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_aggregate() -> dict[str, Any]:
    """Compose the 5-dashboard union payload.

    Each axis surface is returned either as the raw snapshot dict (when
    the file exists and parses) or ``None`` (honest-null). Per-dashboard
    URLs are co-located so agents can drill down without consulting a
    separate manifest.
    """
    snapshots: dict[str, Any] = {
        "rum": _load(_resolve(RUM_JSON, _ENV_PATHS["rum"])),
        "audit": _load(_resolve(STATUS_JSON, _ENV_PATHS["status"])),
        "six_axis": _load(_resolve(SIX_AXIS_JSON, _ENV_PATHS["six_axis"])),
        "freshness": _load(_resolve(FRESHNESS_JSON, _ENV_PATHS["freshness"])),
        "cron_health": _load(_resolve(CRON_HEALTH_JSON, _ENV_PATHS["cron_health"])),
    }
    ready_count = sum(1 for v in snapshots.values() if v is not None)
    return {
        "schema_version": 1,
        "snapshot_ts": _now_iso(),
        "wave": 41,
        "agent": "H",
        "ready": ready_count == len(snapshots),
        "ready_count": ready_count,
        "total_axes": len(snapshots),
        "snapshots": snapshots,
        "dashboards": {
            "rum": "https://jpcite.com/status/rum.html",
            "audit": "https://jpcite.com/status/audit_dashboard.html",
            "freshness": "https://jpcite.com/data-freshness",
            "six_axis": "https://jpcite.com/status/six_axis_dashboard.html",
            "ax": "https://jpcite.com/status/ax_dashboard.html",
            "monitoring": "https://jpcite.com/status/monitoring.html",
        },
        "alert_feed": "https://jpcite.com/status/feed.atom",
        "context": "https://schema.org",
        "@type": "Observation",
    }


@router.get("/all")
def get_status_all(response: Response) -> dict[str, Any]:
    """Aggregated 5-dashboard snapshot (Wave 41 Agent H).

    Reads pre-computed JSON sidecars written by:

    * ``rum`` — ``scripts/ops/rum_aggregator.py`` (Wave 16)
    * ``audit`` — ``scripts/ops/status_probe.py`` (Wave 20)
    * ``six_axis`` — ``scripts/ops/six_axis_sanity_check.py`` (Wave 38)
    * ``freshness`` — ``scripts/cron/rollup_freshness_daily.py`` (Wave 37)
    * ``cron_health`` — derived 24h cron snapshot
    """
    _attach_cache_headers(response)
    return _build_aggregate()


@router.get("/alerts")
def get_status_alerts(response: Response) -> dict[str, Any]:
    """Currently active alert list (Wave 41 Agent H).

    Returns the sidecar JSON written by the hourly aggregator cron
    ``scripts/cron/aggregate_status_alerts_hourly.py``. When the sidecar
    is missing returns an empty list with ``ready=False`` so agents can
    distinguish "no alerts" (``alerts=[]``, ``ready=True``) from "cron
    not yet run" (``alerts=[]``, ``ready=False``).
    """
    _attach_cache_headers(response)
    payload = _load(_resolve(ALERTS_JSON, _ENV_PATHS["alerts"]))
    if payload is None:
        return {
            "schema_version": 1,
            "snapshot_ts": _now_iso(),
            "wave": 41,
            "agent": "H",
            "ready": False,
            "max_severity": "unknown",
            "alerts": [],
            "feed_atom": "https://jpcite.com/status/feed.atom",
            "context": "https://schema.org",
            "@type": "AlertList",
        }
    payload.setdefault("ready", True)
    payload.setdefault("feed_atom", "https://jpcite.com/status/feed.atom")
    payload.setdefault("context", "https://schema.org")
    payload.setdefault("@type", "AlertList")
    return payload
