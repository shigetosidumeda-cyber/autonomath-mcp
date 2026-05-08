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
       "first_metered_request":N,"requests":N,"keys_with_requests":N,
       "metered_requests":N,"billable_units":N,
       "revenue_jpy_ex_tax":N,"stripe_unsynced_units":N},
      ...
    ],
    "totals": {"billable_units":N,"revenue_jpy_ex_tax":N},
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
DAILY_BILLABLE_UNITS_GOAL = 100_000


class FunnelRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    visitors: int = 0  # distinct ip_hash from anon_rate_limit
    api_keys_issued: int = 0  # api_keys.created_at within day
    first_metered_request: int = 0  # keys whose FIRST metered=1 fell in day
    requests: int = 0  # total usage_events in day
    keys_with_requests: int = 0  # distinct key_hash in usage_events
    metered_requests: int = 0  # successful metered usage_events rows in day
    billable_units: int = 0  # SUM(quantity) for successful metered rows
    keys_with_billable_units: int = 0  # distinct key_hash for successful metered rows
    revenue_jpy_ex_tax: int = 0  # billable_units * ¥3
    revenue_jpy_inc_tax_estimate: float = 0.0  # billable_units * ¥3.30
    stripe_unsynced_units: int = 0  # metered units not yet marked synced to Stripe
    daily_goal_billable_units: int = DAILY_BILLABLE_UNITS_GOAL
    daily_goal_progress_pct: float = 0.0


class FunnelTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    visitors: int = 0
    api_keys_issued: int = 0
    first_metered_request: int = 0
    requests: int = 0
    keys_with_requests: int = 0
    metered_requests: int = 0
    billable_units: int = 0
    keys_with_billable_units: int = 0
    revenue_jpy_ex_tax: int = 0
    revenue_jpy_inc_tax_estimate: float = 0.0
    stripe_unsynced_units: int = 0
    average_daily_billable_units: float = 0.0
    daily_goal_billable_units: int = DAILY_BILLABLE_UNITS_GOAL
    average_daily_goal_progress_pct: float = 0.0


class FunnelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    rows: list[FunnelRow]
    totals: FunnelTotals
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
    metered_requests_by_day: dict[str, int] = {}
    billable_units_by_day: dict[str, int] = {}
    billable_keys_by_day: dict[str, int] = {}
    stripe_unsynced_units_by_day: dict[str, int] = {}
    active_keys_total = 0
    billable_keys_total = 0

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

        rows = conn.execute(
            "SELECT substr(ts,1,10) AS d, "
            "       COUNT(*) AS metered_requests, "
            "       COUNT(DISTINCT key_hash) AS metered_keys, "
            "       COALESCE(SUM(COALESCE(quantity, 1)), 0) AS units, "
            "       COALESCE(SUM(CASE "
            "           WHEN stripe_synced_at IS NULL THEN COALESCE(quantity, 1) "
            "           ELSE 0 END), 0) AS unsynced_units "
            "FROM usage_events "
            "WHERE substr(ts,1,10) >= ? "
            "  AND metered = 1 "
            "  AND (status IS NULL OR status < 400) "
            "GROUP BY d",
            (start.isoformat(),),
        ).fetchall()
        for r in rows:
            d = r["d"]
            metered_requests_by_day[d] = int(r["metered_requests"] or 0)
            billable_keys_by_day[d] = int(r["metered_keys"] or 0)
            billable_units_by_day[d] = int(r["units"] or 0)
            stripe_unsynced_units_by_day[d] = int(r["unsynced_units"] or 0)

        # First metered request per key — bucket the day of FIRST event with metered=1.
        rows = conn.execute(
            "SELECT substr(MIN(ts),1,10) AS d, key_hash "
            "FROM usage_events "
            "WHERE metered = 1 AND (status IS NULL OR status < 400) "
            "GROUP BY key_hash"
        ).fetchall()
        for r in rows:
            d = r["d"]
            if d and d >= start.isoformat():
                first_metered_by_day[d] = first_metered_by_day.get(d, 0) + 1
        active_keys_total = int(
            conn.execute(
                "SELECT COUNT(DISTINCT key_hash) AS n FROM usage_events WHERE substr(ts,1,10) >= ?",
                (start.isoformat(),),
            ).fetchone()["n"]
            or 0
        )
        billable_keys_total = int(
            conn.execute(
                "SELECT COUNT(DISTINCT key_hash) AS n FROM usage_events "
                "WHERE substr(ts,1,10) >= ? "
                "  AND metered = 1 "
                "  AND (status IS NULL OR status < 400)",
                (start.isoformat(),),
            ).fetchone()["n"]
            or 0
        )
    else:
        notes.append("usage_events missing")

    out_rows: list[FunnelRow] = []
    for d in days_seq:
        units = billable_units_by_day.get(d, 0)
        out_rows.append(
            FunnelRow(
                date=d,
                visitors=visitors_by_day.get(d, 0),
                api_keys_issued=keys_issued_by_day.get(d, 0),
                first_metered_request=first_metered_by_day.get(d, 0),
                requests=requests_by_day.get(d, 0),
                keys_with_requests=keys_active_by_day.get(d, 0),
                metered_requests=metered_requests_by_day.get(d, 0),
                billable_units=units,
                keys_with_billable_units=billable_keys_by_day.get(d, 0),
                revenue_jpy_ex_tax=units * 3,
                revenue_jpy_inc_tax_estimate=round(units * 3.3, 2),
                stripe_unsynced_units=stripe_unsynced_units_by_day.get(d, 0),
                daily_goal_progress_pct=round(
                    (units / DAILY_BILLABLE_UNITS_GOAL) * 100,
                    2,
                ),
            )
        )
    total_billable_units = sum(row.billable_units for row in out_rows)
    average_daily_billable_units = (
        round(total_billable_units / len(out_rows), 2) if out_rows else 0.0
    )
    totals = FunnelTotals(
        visitors=sum(row.visitors for row in out_rows),
        api_keys_issued=sum(row.api_keys_issued for row in out_rows),
        first_metered_request=sum(row.first_metered_request for row in out_rows),
        requests=sum(row.requests for row in out_rows),
        keys_with_requests=active_keys_total,
        metered_requests=sum(row.metered_requests for row in out_rows),
        billable_units=total_billable_units,
        keys_with_billable_units=billable_keys_total,
        revenue_jpy_ex_tax=sum(row.revenue_jpy_ex_tax for row in out_rows),
        revenue_jpy_inc_tax_estimate=round(
            sum(row.revenue_jpy_inc_tax_estimate for row in out_rows),
            2,
        ),
        stripe_unsynced_units=sum(row.stripe_unsynced_units for row in out_rows),
        average_daily_billable_units=average_daily_billable_units,
        average_daily_goal_progress_pct=round(
            (average_daily_billable_units / DAILY_BILLABLE_UNITS_GOAL) * 100,
            2,
        ),
    )
    return FunnelResponse(
        start=start.isoformat(),
        end=today.isoformat(),
        rows=out_rows,
        totals=totals,
        note="; ".join(notes) if notes else None,
    )


__all__ = ["DAILY_BILLABLE_UNITS_GOAL", "router"]
