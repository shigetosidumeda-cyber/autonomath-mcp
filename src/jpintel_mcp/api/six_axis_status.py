"""Wave 38 — `GET /v1/status/six_axis` agent-readable health surface.

The dashboard at `site/status/six_axis_dashboard.html` and external AI
agents fetch this endpoint to learn the current state of jpcite's 6
design axes (data 量 / data 質 / 鮮度 / 組み合わせ / 多言語 / output).

Two routes:

* ``GET /v1/status/six_axis`` returns the full snapshot rendered by
  ``scripts/ops/six_axis_sanity_check.py`` (read from a JSON sidecar in
  the repo so the API never has to re-run the probe on the hot path).
* ``GET /v1/status/six_axis/{axis_id}/{sub_id}`` returns just the sub-axis
  detail — useful for agents that already cached the index and want to
  drill into a single failing probe.

Implementation notes
--------------------

* The endpoint is **public** (no AnonIpLimitDep, no auth). Same posture
  as ``/v1/meta/freshness`` — a transparency surface, not internal debug.
* The JSON sidecar path is configurable via ``SIX_AXIS_STATUS_PATH``;
  defaults match where the daily cron writes
  (``analytics/six_axis_status.json``). When the sidecar is missing the
  endpoint returns a 503 with ``ready: false`` instead of a 500 so
  agents can distinguish "not yet probed" from "broken".
* Cache directives: short ``Cache-Control: max-age=180`` (3 minutes) so
  agents can poll without hammering the origin while keeping the latency
  to a breach <= 5 minutes from cron firing.
* Zero LLM, zero DB access. Pure JSON I/O.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATUS_PATH = REPO_ROOT / "analytics" / "six_axis_status.json"
MIRROR_STATUS_PATH = REPO_ROOT / "site" / "status" / "six_axis_status.json"


router = APIRouter(prefix="/v1/status", tags=["status", "transparency"])


def _resolve_status_path() -> Path:
    env = os.environ.get("SIX_AXIS_STATUS_PATH", "").strip()
    if env:
        return Path(env)
    if DEFAULT_STATUS_PATH.exists():
        return DEFAULT_STATUS_PATH
    return MIRROR_STATUS_PATH


def _load_report() -> dict[str, Any] | None:
    path = _resolve_status_path()
    if not path.exists():
        return None
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _attach_cache_headers(response: Response) -> None:
    # 3-minute browser/CDN cache; matches cron min-cycle granularity.
    response.headers["Cache-Control"] = "public, max-age=180"


@router.get("/six_axis")
def get_six_axis_status(response: Response) -> dict[str, Any]:
    """Return the 6-axis production sanity snapshot.

    The JSON shape mirrors what ``scripts/ops/six_axis_sanity_check.py``
    writes (schema_version 1). When the daily cron has not yet produced
    a sidecar (e.g. fresh deploy) we return a ``503 ready=false`` so
    agents distinguish "not yet probed" from "broken".
    """
    report = _load_report()
    _attach_cache_headers(response)
    if report is None:
        response.status_code = 503
        return {
            "ready": False,
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "message": (
                "six-axis sanity probe has not run yet. The daily cron "
                "writes analytics/six_axis_status.json at 06:30 UTC."
            ),
        }
    return {"ready": True, **report}


@router.get("/six_axis/{axis_id}/{sub_id}")
def get_six_axis_sub_detail(
    axis_id: str,
    sub_id: str,
    response: Response,
) -> dict[str, Any]:
    """Return the detail block for a single sub-axis (e.g. ``2a``).

    Agents that already cached the index can drill into a failing probe
    without re-fetching the full payload.
    """
    report = _load_report()
    _attach_cache_headers(response)
    if report is None:
        raise HTTPException(status_code=503, detail="six-axis sidecar not present")
    for axis in report.get("axes", []):
        if str(axis.get("axis_id")) != axis_id:
            continue
        for sub in axis.get("sub_results", []):
            if str(sub.get("sub_id")) == sub_id:
                return {
                    "schema_version": report.get("schema_version", 1),
                    "generated_at": report.get("generated_at"),
                    "axis_id": axis_id,
                    "axis_label": axis.get("label"),
                    "axis_verdict": axis.get("verdict"),
                    "sub": sub,
                }
        raise HTTPException(
            status_code=404,
            detail=f"sub_id {sub_id} not found within axis {axis_id}",
        )
    raise HTTPException(status_code=404, detail=f"axis_id {axis_id} not found")


__all__ = ["router"]
