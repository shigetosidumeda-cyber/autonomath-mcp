"""Internal admin endpoints (`/v1/admin/*`).

Out-of-band surface for us (the operators) to observe the conversion funnel
specified in `docs/conversion_funnel.md` §6 the moment launch traffic starts
flowing. Not part of the public `/v1/*` contract:

- Router is registered with `include_in_schema=False`, so admin paths do NOT
  appear in `/openapi.json` exports (`docs/openapi/v1.json`, SDK generation).
- Auth is a dedicated `ADMIN_API_KEY` env var (`settings.admin_api_key`)
  read via `X-API-Key`. Never reuse a customer key here.
- If `admin_api_key` is empty, every endpoint returns 503
  "admin endpoints disabled" — safer default than allowing an
  uninitialised key through.

Tables probed but tolerated-missing:

- `funnel_daily` — written by the nightly rollup cron (`/docs/conversion_funnel.md`
  §2.3). Missing → empty list + structured warning.
- `cohort_retention` — same rollup. Missing → empty response.
- `usage_events.status` — present in current schema; scanned for `status >= 400`.

All SQL is hand-written and parameterised; no ORM.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.config import settings

if TYPE_CHECKING:
    import sqlite3


_log = logging.getLogger("jpintel.admin")

# include_in_schema=False keeps /v1/admin/* out of app.openapi() output.
router = APIRouter(prefix="/v1/admin", tags=["admin"], include_in_schema=False)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_admin(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Guard admin endpoints behind settings.admin_api_key.

    - empty admin_api_key           -> 503 "admin endpoints disabled"
    - missing / wrong X-API-Key     -> 401
    """
    configured = settings.admin_api_key
    if not configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "admin endpoints disabled"
        )
    if not x_api_key or x_api_key != configured:
        client_ip = request.client.host if request.client else "unknown"
        _log.warning(
            "admin_auth_failed",
            extra={
                "event": "admin_auth_failed",
                "ip": client_ip,
                "path": request.url.path,
            },
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin key")


AdminAuthDep = Annotated[None, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Response models (all frozen, strict)
# ---------------------------------------------------------------------------


class FunnelDay(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    visits: int = 0
    ctas: int = 0
    checkouts_started: int = 0
    checkouts_paid: int = 0
    keys_issued: int = 0
    first_api_calls: int = 0
    d7_retained: int = 0
    d30_retained: int = 0


class FunnelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    rows: list[FunnelDay]
    note: str | None = None  # populated if rollup table missing


class CohortResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort_month: str
    active_d7: int = 0
    active_d14: int = 0
    active_d21: int = 0
    active_d28: int = 0
    churn_count: int = 0
    churn_reason_breakdown: dict[str, int] = Field(default_factory=dict)
    note: str | None = None


class TopError(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: str
    status_code: int
    error_class: str  # "4xx" | "5xx" (coarse bucket; finer class requires a separate error table)
    count: int
    sample_message: str | None = None
    first_seen: str
    last_seen: str


class TopErrorsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    hours: int
    limit: int
    errors: list[TopError]
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    # PRAGMA can't be parameterised; we explicitly allow only ASCII identifiers.
    if not table.replace("_", "").isalnum() or not column.replace("_", "").isalnum():
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _parse_date(raw: str, field: str) -> str:
    """Validate YYYY-MM-DD; return the canonical string."""
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field} must be YYYY-MM-DD",
        ) from exc
    return d.isoformat()


def _parse_cohort_month(raw: str) -> str:
    try:
        datetime.strptime(raw, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "cohort_month must be YYYY-MM"
        ) from exc
    return raw


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/funnel", response_model=FunnelResponse)
def get_funnel(
    _auth: AdminAuthDep,
    conn: DbDep,
    start: str,
    end: str,
) -> FunnelResponse:
    """Daily funnel rollup. Reads `funnel_daily`; returns 0-row if missing."""
    start_iso = _parse_date(start, "start")
    end_iso = _parse_date(end, "end")
    if start_iso > end_iso:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "start must be <= end"
        )

    if not _table_exists(conn, "funnel_daily"):
        _log.warning(
            "funnel_daily table missing; returning empty rollup",
            extra={"start": start_iso, "end": end_iso},
        )
        return FunnelResponse(
            start=start_iso,
            end=end_iso,
            rows=[],
            note="funnel_daily table not yet provisioned (pending migration 004)",
        )

    rows = conn.execute(
        """SELECT date, visits, ctas, checkouts_started, checkouts_paid,
                  keys_issued, first_api_calls, d7_retained, d30_retained
             FROM funnel_daily
            WHERE date >= ? AND date <= ?
         ORDER BY date ASC""",
        (start_iso, end_iso),
    ).fetchall()

    out = [
        FunnelDay(
            date=r["date"],
            visits=r["visits"] or 0,
            ctas=r["ctas"] or 0,
            checkouts_started=r["checkouts_started"] or 0,
            checkouts_paid=r["checkouts_paid"] or 0,
            keys_issued=r["keys_issued"] or 0,
            first_api_calls=r["first_api_calls"] or 0,
            d7_retained=r["d7_retained"] or 0,
            d30_retained=r["d30_retained"] or 0,
        )
        for r in rows
    ]
    return FunnelResponse(start=start_iso, end=end_iso, rows=out)


@router.get("/cohort", response_model=CohortResponse)
def get_cohort(
    _auth: AdminAuthDep,
    conn: DbDep,
    cohort_month: str,
) -> CohortResponse:
    """Single cohort slice (`cohort_month` = paying month, 'YYYY-MM')."""
    month = _parse_cohort_month(cohort_month)

    if not _table_exists(conn, "cohort_retention"):
        _log.warning(
            "cohort_retention table missing; returning zero cohort",
            extra={"cohort_month": month},
        )
        return CohortResponse(
            cohort_month=month,
            note="cohort_retention table not yet provisioned (pending migration 004)",
        )

    row = conn.execute(
        """SELECT active_d7, active_d14, active_d21, active_d28,
                  churn_count, churn_reason_breakdown_json
             FROM cohort_retention
            WHERE cohort_month = ?""",
        (month,),
    ).fetchone()

    if row is None:
        return CohortResponse(cohort_month=month, note="no rows for cohort_month")

    import json

    raw_breakdown = row["churn_reason_breakdown_json"]
    try:
        breakdown = json.loads(raw_breakdown) if raw_breakdown else {}
    except (TypeError, ValueError):
        breakdown = {}

    return CohortResponse(
        cohort_month=month,
        active_d7=row["active_d7"] or 0,
        active_d14=row["active_d14"] or 0,
        active_d21=row["active_d21"] or 0,
        active_d28=row["active_d28"] or 0,
        churn_count=row["churn_count"] or 0,
        churn_reason_breakdown=breakdown if isinstance(breakdown, dict) else {},
    )


@router.get("/top-errors", response_model=TopErrorsResponse)
def get_top_errors(
    _auth: AdminAuthDep,
    conn: DbDep,
    hours: int = 24,
    limit: int = 20,
) -> TopErrorsResponse:
    """Top error patterns in `usage_events` (status >= 400)."""
    if hours < 1:
        hours = 1
    if hours > 24 * 30:
        hours = 24 * 30
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    if not _table_exists(conn, "usage_events"):
        return TopErrorsResponse(
            hours=hours, limit=limit, errors=[], note="usage_events table missing"
        )

    # schema.sql names the column `status`. The design doc referred to it as
    # `status_code`; accept either so future migrations don't silently 500.
    status_col = (
        "status"
        if _column_exists(conn, "usage_events", "status")
        else "status_code"
        if _column_exists(conn, "usage_events", "status_code")
        else None
    )
    if status_col is None:
        return TopErrorsResponse(
            hours=hours,
            limit=limit,
            errors=[],
            note="usage_events has no status/status_code column",
        )

    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

    # f-string on column name is safe: we validated status_col is one of two
    # compile-time literals. No user input reaches the SQL string.
    rows = conn.execute(
        f"""SELECT endpoint,
                   {status_col} AS status_code,
                   COUNT(*) AS n,
                   MIN(ts) AS first_seen,
                   MAX(ts) AS last_seen
              FROM usage_events
             WHERE {status_col} >= 400
               AND ts >= ?
          GROUP BY endpoint, {status_col}
          ORDER BY n DESC
             LIMIT ?""",
        (since, limit),
    ).fetchall()

    errors = [
        TopError(
            endpoint=r["endpoint"],
            status_code=r["status_code"],
            error_class="5xx" if r["status_code"] >= 500 else "4xx",
            count=r["n"],
            sample_message=None,  # usage_events doesn't carry a message; null-safe
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
        )
        for r in rows
    ]

    return TopErrorsResponse(hours=hours, limit=limit, errors=errors)


# ---------------------------------------------------------------------------
# Kill-switch status (P0 abuse / DoS lever — audit a7388ccfd9ed7fb8c)
# ---------------------------------------------------------------------------


class KillSwitchStatus(BaseModel):
    """Snapshot of the global kill-switch state for the operator runbook.

    Backed by ``KillSwitchMiddleware`` (``api/middleware/kill_switch.py``):
    the env var ``KILL_SWITCH_GLOBAL=1`` flips the switch app-wide, and
    ``KILL_SWITCH_REASON`` carries a free-text reason. ``since_iso`` is
    the first time the current process observed the switch as active —
    useful when triaging "is this still on?" without reading flyctl
    history. None when the switch is off in this worker.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool
    since_iso: str | None = None
    reason: str | None = None


@router.get("/kill_switch_status", response_model=KillSwitchStatus)
def get_kill_switch_status(_auth: AdminAuthDep) -> KillSwitchStatus:
    """Return the current kill-switch state. Admin-only.

    Operator runbook: ``docs/_internal/launch_kill_switch.md``. Flip via
    ``flyctl secrets set KILL_SWITCH_GLOBAL=1 -a autonomath-api`` (and
    optionally ``KILL_SWITCH_REASON='ddos from 1.2.3.0/24 — see Sentry
    incident 12345'``).
    """
    from jpintel_mcp.api.middleware.kill_switch import (
        _kill_switch_active,
        _kill_switch_reason,
        _kill_switch_since,
    )

    return KillSwitchStatus(
        enabled=_kill_switch_active(),
        since_iso=_kill_switch_since(),
        reason=_kill_switch_reason(),
    )


__all__ = ["router", "require_admin"]
