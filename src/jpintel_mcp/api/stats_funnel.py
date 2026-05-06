"""Operator-only funnel stats endpoint.

GET /v1/stats/funnel?days=N — daily acquisition→activation→revenue funnel.

Distinct from the public `/v1/stats/usage` (which is anonymous-aggregate
cumulative counts) and from `/v1/admin/funnel` (which reads a precomputed
`funnel_daily` rollup written by a separate cron). This endpoint computes
the funnel **live** from the raw tables so the operator can see numbers
before the rollup catches up.

Auth: shares the `ADMIN_API_KEY` env var (same gate as `/v1/admin/*`).
The admin agent's docs/conversion_funnel.md design specifies this is the
only auth path for operator-only views — we deliberately reuse it
instead of inventing a new scope.

Pulls from jpintel.db only (no cross-DB JOIN — see CLAUDE.md "Database"
constraint). Stripe events are not in this DB; we surface the
`first_metered_request` proxy (first usage_events row with metered=1)
which equals "first paid invoice line item" 1:1 in the metered model.

Response shape (mirrors admin.FunnelResponse for cross-tool consistency):
  {
    "start": "2026-04-22",
    "end": "2026-04-29",
    "rows": [
      {"date":"2026-04-29","visitors":N,"api_keys_issued":N,
       "first_metered_request":N,"requests":N,"keys_with_requests":N},
      ...
    ],
    "note": null  # populated when a probed table is missing
  }
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 (runtime annotation for _table_exists helper)
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from jpintel_mcp.api.admin import AdminAuthDep  # noqa: TC001 (FastAPI Depends resolution)
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (FastAPI Depends resolution)

router = APIRouter(prefix="/v1/stats", tags=["stats", "operator"])


class FunnelRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    visitors: int = 0  # distinct ip_hash from anon_rate_limit
    api_keys_issued: int = 0  # api_keys.created_at within day
    first_metered_request: int = 0  # keys whose FIRST metered=1 fell in day
    requests: int = 0  # total usage_events in day
    keys_with_requests: int = 0  # distinct key_hash in usage_events


class FunnelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    rows: list[FunnelRow]
    note: str | None = None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


@router.get("/funnel", response_model=FunnelResponse, include_in_schema=False)
def funnel(
    _admin: AdminAuthDep,
    conn: DbDep,
    days: int = Query(default=14, ge=1, le=90),
) -> FunnelResponse:
    """Live funnel rollup — operator-only (admin key required)."""
    if days < 1 or days > 90:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "days must be 1..90")

    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    days_seq = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    notes: list[str] = []
    visitors_by_day: dict[str, int] = {}
    keys_issued_by_day: dict[str, int] = {}
    first_metered_by_day: dict[str, int] = {}
    requests_by_day: dict[str, int] = {}
    keys_active_by_day: dict[str, int] = {}

    if _table_exists(conn, "anon_rate_limit"):
        rows = conn.execute(
            "SELECT date, COUNT(DISTINCT ip_hash) AS n FROM anon_rate_limit "
            "WHERE date >= ? GROUP BY date",
            (start.isoformat(),),
        ).fetchall()
        visitors_by_day = {r["date"]: int(r["n"]) for r in rows}
    else:
        notes.append("anon_rate_limit missing")

    if _table_exists(conn, "api_keys"):
        rows = conn.execute(
            "SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM api_keys "
            "WHERE substr(created_at,1,10) >= ? GROUP BY d",
            (start.isoformat(),),
        ).fetchall()
        keys_issued_by_day = {r["d"]: int(r["n"]) for r in rows}
    else:
        notes.append("api_keys missing")

    if _table_exists(conn, "usage_events"):
        rows = conn.execute(
            "SELECT substr(ts,1,10) AS d, COUNT(*) AS n, "
            "       COUNT(DISTINCT key_hash) AS k "
            "FROM usage_events WHERE substr(ts,1,10) >= ? GROUP BY d",
            (start.isoformat(),),
        ).fetchall()
        for r in rows:
            requests_by_day[r["d"]] = int(r["n"])
            keys_active_by_day[r["d"]] = int(r["k"])

        # First metered request per key — bucket the day of FIRST event with metered=1.
        rows = conn.execute(
            "SELECT substr(MIN(ts),1,10) AS d, key_hash "
            "FROM usage_events WHERE metered = 1 GROUP BY key_hash"
        ).fetchall()
        for r in rows:
            d = r["d"]
            if d and d >= start.isoformat():
                first_metered_by_day[d] = first_metered_by_day.get(d, 0) + 1
    else:
        notes.append("usage_events missing")

    out_rows = [
        FunnelRow(
            date=d,
            visitors=visitors_by_day.get(d, 0),
            api_keys_issued=keys_issued_by_day.get(d, 0),
            first_metered_request=first_metered_by_day.get(d, 0),
            requests=requests_by_day.get(d, 0),
            keys_with_requests=keys_active_by_day.get(d, 0),
        )
        for d in days_seq
    ]
    return FunnelResponse(
        start=start.isoformat(),
        end=today.isoformat(),
        rows=out_rows,
        note="; ".join(notes) if notes else None,
    )


__all__ = ["router"]
