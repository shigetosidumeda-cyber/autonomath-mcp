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

import hmac
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
_FUNNEL_EVENT_PATH = "/v1/funnel/event"


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
    # Constant-time comparison: a naive `x_api_key != configured` leaks the
    # length of the matching prefix via response timing. hmac.compare_digest
    # short-circuits in O(min(len(a), len(b))) time only on length mismatch
    # (no information about content), and is constant-time within equal-length
    # strings.
    if not x_api_key or not hmac.compare_digest(
        x_api_key.encode("utf-8"), configured.encode("utf-8")
    ):
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


class CronRunRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    cron_name: str
    started_at: str
    finished_at: str | None = None
    status: str
    rows_processed: int | None = None
    rows_skipped: int | None = None
    error_message: str | None = None
    metadata_json: str | None = None
    workflow_run_id: str | None = None
    git_sha: str | None = None


class CronStatusCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    cron_name: str
    ok: int = 0
    error: int = 0
    partial: int = 0
    dry_run: int = 0
    running: int = 0
    last_started_at: str | None = None
    last_status: str | None = None


class CronRunsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    since: str
    limit_per_cron: int
    runs: list[CronRunRow]
    status_counts: list[CronStatusCounts]
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
# Cron heartbeat read-side (migration 102 — `cron_runs` populated by
# `scripts/cron/*.py` via `jpintel_mcp.observability.heartbeat`).
# ---------------------------------------------------------------------------


@router.get("/cron_runs", response_model=CronRunsResponse)
def get_cron_runs(
    _auth: AdminAuthDep,
    conn: DbDep,
    since: str | None = None,
    limit_per_cron: int = 5,
) -> CronRunsResponse:
    """Recent cron heartbeats + per-cron status rollup.

    Args:
        since: ISO 8601 cutoff (default: now - 24h). Anything earlier is
            excluded from both ``runs`` and ``status_counts``.
        limit_per_cron: cap rows per cron_name returned in ``runs`` (default 5,
            max 50). The ``status_counts`` rollup is unaffected by this cap.

    Returns 200 with empty lists if migration 102 hasn't been applied yet
    (table missing). The cron writer auto-creates the table on first
    write, so this null-safe path is mainly for fresh test DBs.
    """
    if limit_per_cron < 1:
        limit_per_cron = 1
    if limit_per_cron > 50:
        limit_per_cron = 50

    if since is None:
        since_dt = datetime.now(UTC) - timedelta(hours=24)
        since_iso = since_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    else:
        # Validate but return as-is so downstream can compare lexicographic
        # ISO 8601 against stored values (which the cron writer also emits
        # in seconds-resolution Z form).
        try:
            datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "since must be ISO 8601 (e.g. 2026-04-29T00:00:00Z)",
            ) from exc
        since_iso = since

    if not _table_exists(conn, "cron_runs"):
        return CronRunsResponse(
            since=since_iso,
            limit_per_cron=limit_per_cron,
            runs=[],
            status_counts=[],
            note="cron_runs table missing (migration 102 not yet applied)",
        )

    # Per-cron status rollup. ``status`` enum is ('ok','error','partial',
    # 'dry_run','running') per migration 102 — we sum each bucket.
    status_rows = conn.execute(
        """SELECT cron_name,
                  SUM(CASE WHEN status='ok'      THEN 1 ELSE 0 END) AS ok,
                  SUM(CASE WHEN status='error'   THEN 1 ELSE 0 END) AS err,
                  SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial,
                  SUM(CASE WHEN status='dry_run' THEN 1 ELSE 0 END) AS dry_run,
                  SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                  MAX(started_at) AS last_started_at
             FROM cron_runs
            WHERE started_at >= ?
         GROUP BY cron_name
         ORDER BY cron_name ASC""",
        (since_iso,),
    ).fetchall()

    counts: list[CronStatusCounts] = []
    for r in status_rows:
        # Latest status for each cron (single extra small query per row).
        # The rollup is bounded by the number of distinct cron_names —
        # presently ~30, so N+1 is fine.
        last = conn.execute(
            """SELECT status FROM cron_runs
                WHERE cron_name = ? AND started_at >= ?
             ORDER BY started_at DESC LIMIT 1""",
            (r["cron_name"], since_iso),
        ).fetchone()
        counts.append(
            CronStatusCounts(
                cron_name=r["cron_name"],
                ok=r["ok"] or 0,
                error=r["err"] or 0,
                partial=r["partial"] or 0,
                dry_run=r["dry_run"] or 0,
                running=r["running"] or 0,
                last_started_at=r["last_started_at"],
                last_status=last["status"] if last is not None else None,
            )
        )

    # Per-cron last-N rows. Using a window function so the cap is enforced
    # in SQL rather than client-side; SQLite ≥ 3.25 supports row_number().
    rows = conn.execute(
        """WITH ranked AS (
              SELECT cron_name, started_at, finished_at, status,
                     rows_processed, rows_skipped, error_message,
                     metadata_json, workflow_run_id, git_sha,
                     ROW_NUMBER() OVER (
                         PARTITION BY cron_name
                         ORDER BY started_at DESC
                     ) AS rn
                FROM cron_runs
               WHERE started_at >= ?
           )
           SELECT cron_name, started_at, finished_at, status,
                  rows_processed, rows_skipped, error_message,
                  metadata_json, workflow_run_id, git_sha
             FROM ranked
            WHERE rn <= ?
         ORDER BY cron_name ASC, started_at DESC""",
        (since_iso, limit_per_cron),
    ).fetchall()

    runs = [
        CronRunRow(
            cron_name=r["cron_name"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            status=r["status"],
            rows_processed=r["rows_processed"],
            rows_skipped=r["rows_skipped"],
            error_message=r["error_message"],
            metadata_json=r["metadata_json"],
            workflow_run_id=r["workflow_run_id"],
            git_sha=r["git_sha"],
        )
        for r in rows
    ]

    return CronRunsResponse(
        since=since_iso,
        limit_per_cron=limit_per_cron,
        runs=runs,
        status_counts=counts,
    )


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


# ---------------------------------------------------------------------------
# /v1/admin/analytics_split — §4-E bot-vs-human conversion denominator
# ---------------------------------------------------------------------------


class AnalyticsSplitBucket(BaseModel):
    """One row of the bot/human/UA-class roll-up."""

    model_config = ConfigDict(frozen=True)

    user_agent_class: str
    is_bot: bool
    request_count: int
    distinct_paths: int
    distinct_anon_ips: int
    distinct_keys: int


class FunnelEventCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_name: str
    total_count: int
    human_count: int  # is_bot=0
    bot_count: int  # is_bot=1
    distinct_sessions: int


class SrcAttributionBucket(BaseModel):
    """§4.6 distribution-channel attribution row.

    One row per `src=` token (closed allowlist enforced in
    `analytics_recorder._classify_src`). NULL src ("direct/unknown") is
    rolled into the explicit `direct` bucket so the rollup is exhaustive.
    """

    model_config = ConfigDict(frozen=True)

    src: str
    human_request_count: int
    paid_conversion_count: int
    first_paid_within_7d_count: int
    distinct_sessions: int
    distinct_anon_ips: int


class AnalyticsSplitResponse(BaseModel):
    """§4-E bot-vs-human view + §4.6 distribution-attribution view.

    Numerator candidates (`paid_conversions`, etc.) live in `usage_events` /
    `api_keys`; this endpoint surfaces the *denominator* candidates so the
    operator can pick a defensible "human-ish" baseline (Cloudflare raw PV
    is dominated by bots and is the wrong denominator).

    §4.6 (jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md) adds
    per-`src` aggregation so the operator can see which distribution
    channel (llmstxt / cookbook_<recipe> / chatgpt_actions / gpt_custom /
    mcp_registry / claude_mcp / cursor_mcp / cline_mcp / hn_launch /
    zenn_intro) is producing first-paid customers organically.
    """

    model_config = ConfigDict(frozen=True)

    hours: int
    total_requests: int
    bot_requests: int
    human_requests: int
    paid_conversion_denominator_human_request: int
    by_ua_class: list[AnalyticsSplitBucket]
    funnel_events: list[FunnelEventCount]
    by_src: list[SrcAttributionBucket]
    note: str | None = None


@router.get("/analytics_split", response_model=AnalyticsSplitResponse)
def get_analytics_split(
    _auth: AdminAuthDep,
    conn: DbDep,
    hours: int = 24,
) -> AnalyticsSplitResponse:
    """Bot vs human split of `analytics_events` + `funnel_events`.

    §4-E receipt: dashboards must be able to compute paid-conversion
    rates with bot traffic excluded from the denominator. This endpoint
    returns both the raw split and a `paid_conversion_denominator_human_request`
    figure that downstream dashboards plug into rate calculations.
    """
    if hours < 1:
        hours = 1
    if hours > 24 * 30:
        hours = 24 * 30
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

    notes: list[str] = []

    # ---- analytics_events split (per UA class) -----------------------------
    bot_requests = 0
    human_requests = 0
    total_requests = 0
    by_ua_class: list[AnalyticsSplitBucket] = []
    if not _table_exists(conn, "analytics_events"):
        notes.append("analytics_events table missing")
    elif not _column_exists(conn, "analytics_events", "is_bot"):
        notes.append(
            "analytics_events.is_bot column missing — apply migration 123"
        )
        # Fall back to a bot-blind row so the UI doesn't 500.
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM analytics_events "
            "WHERE ts >= ? AND path != ?",
            (since, _FUNNEL_EVENT_PATH),
        ).fetchone()
        total_requests = int(row["n"] or 0)
        human_requests = total_requests
    else:
        row = conn.execute(
            """SELECT
                 COUNT(*)                                AS total,
                 SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END) AS bots,
                 SUM(CASE WHEN is_bot = 0 THEN 1 ELSE 0 END) AS humans
               FROM analytics_events
              WHERE ts >= ?
                AND path != ?""",
            (since, _FUNNEL_EVENT_PATH),
        ).fetchone()
        total_requests = int(row["total"] or 0)
        bot_requests = int(row["bots"] or 0)
        human_requests = int(row["humans"] or 0)

        ua_rows = conn.execute(
            """SELECT
                 COALESCE(user_agent_class, 'unknown') AS ua_class,
                 MAX(is_bot)                            AS is_bot,
                 COUNT(*)                               AS n,
                 COUNT(DISTINCT path)                   AS d_paths,
                 COUNT(DISTINCT anon_ip_hash)           AS d_anon,
                 COUNT(DISTINCT key_hash)               AS d_keys
               FROM analytics_events
              WHERE ts >= ?
                AND path != ?
           GROUP BY ua_class
           ORDER BY n DESC
              LIMIT 50""",
            (since, _FUNNEL_EVENT_PATH),
        ).fetchall()
        by_ua_class = [
            AnalyticsSplitBucket(
                user_agent_class=r["ua_class"],
                is_bot=bool(r["is_bot"]),
                request_count=int(r["n"] or 0),
                distinct_paths=int(r["d_paths"] or 0),
                distinct_anon_ips=int(r["d_anon"] or 0),
                distinct_keys=int(r["d_keys"] or 0),
            )
            for r in ua_rows
        ]

    # ---- funnel_events roll-up ---------------------------------------------
    funnel_rows: list[FunnelEventCount] = []
    if not _table_exists(conn, "funnel_events"):
        notes.append("funnel_events table missing — apply migration 123")
    else:
        rows = conn.execute(
            """SELECT
                 event_name,
                 COUNT(*)                                          AS n,
                 SUM(CASE WHEN is_bot = 0 THEN 1 ELSE 0 END)       AS humans,
                 SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END)       AS bots,
                 COUNT(DISTINCT session_id)                        AS sessions
               FROM funnel_events
              WHERE ts >= ?
           GROUP BY event_name
           ORDER BY humans DESC, n DESC""",
            (since,),
        ).fetchall()
        funnel_rows = [
            FunnelEventCount(
                event_name=r["event_name"],
                total_count=int(r["n"] or 0),
                human_count=int(r["humans"] or 0),
                bot_count=int(r["bots"] or 0),
                distinct_sessions=int(r["sessions"] or 0),
            )
            for r in rows
        ]

    # ---- §4.6 per-src attribution ------------------------------------------
    # Three signals per src bucket:
    #   1. human_request_per_src — analytics_events rows with is_bot=0,
    #      grouped by src (NULL bucketed as 'direct').
    #   2. paid_conversion_per_src — usage_events rows whose key_hash was
    #      first seen on an analytics_events row carrying that src.
    #   3. first_paid_within_7d_per_src — subset of (2) where the first
    #      billable usage event landed within 7 days of the src-attributed
    #      analytics_events row (= "fast organic conversion" signal).
    #
    # All three are implemented as a single CTE walk so we don't pay 3x
    # full-table-scan cost.
    by_src: list[SrcAttributionBucket] = []
    has_src_col = _column_exists(conn, "analytics_events", "src")
    if not has_src_col:
        notes.append(
            "analytics_events.src column missing — apply migration 124"
        )
    elif not _table_exists(conn, "usage_events"):
        # Without usage_events we can still emit the human_request half.
        rows = conn.execute(
            """SELECT
                 COALESCE(src, 'direct')               AS src,
                 SUM(CASE WHEN is_bot = 0 THEN 1 ELSE 0 END) AS humans,
                 COUNT(DISTINCT anon_ip_hash)          AS d_anon
               FROM analytics_events
              WHERE ts >= ?
                AND path != ?
           GROUP BY COALESCE(src, 'direct')
           ORDER BY humans DESC
              LIMIT 50""",
            (since, _FUNNEL_EVENT_PATH),
        ).fetchall()
        by_src = [
            SrcAttributionBucket(
                src=r["src"],
                human_request_count=int(r["humans"] or 0),
                paid_conversion_count=0,
                first_paid_within_7d_count=0,
                distinct_sessions=0,
                distinct_anon_ips=int(r["d_anon"] or 0),
            )
            for r in rows
        ]
    else:
        # Full join: pair every distinct (key_hash, src) seen in
        # analytics_events with the earliest usage_events row for that
        # key_hash. NULL src is rolled into 'direct' so the rollup is
        # exhaustive.
        rows = conn.execute(
            """WITH src_attr AS (
                  -- Earliest src-attributed visit per key_hash within window.
                  SELECT
                    key_hash,
                    COALESCE(src, 'direct') AS src,
                    MIN(ts)                 AS first_attr_ts
                  FROM analytics_events
                  WHERE ts >= ?
                    AND path != ?
                    AND is_bot = 0
                    AND key_hash IS NOT NULL
                  GROUP BY key_hash, COALESCE(src, 'direct')
              ),
              first_paid AS (
                  -- First billable usage_event per key_hash (any time).
                  SELECT key_hash, MIN(ts) AS first_paid_ts
                  FROM usage_events
                  WHERE key_hash IS NOT NULL
                  GROUP BY key_hash
              ),
              human_per_src AS (
                  SELECT
                    COALESCE(src, 'direct') AS src,
                    COUNT(*)                AS humans,
                    COUNT(DISTINCT anon_ip_hash) AS d_anon
                  FROM analytics_events
                  WHERE ts >= ?
                    AND path != ?
                    AND is_bot = 0
                  GROUP BY COALESCE(src, 'direct')
              ),
              paid_per_src AS (
                  SELECT
                    s.src,
                    COUNT(DISTINCT s.key_hash) AS paid_keys,
                    SUM(CASE
                          WHEN fp.first_paid_ts IS NOT NULL
                           AND julianday(fp.first_paid_ts)
                             - julianday(s.first_attr_ts) <= 7
                          THEN 1 ELSE 0 END) AS paid_within_7d
                  FROM src_attr s
                  LEFT JOIN first_paid fp ON fp.key_hash = s.key_hash
                  WHERE fp.first_paid_ts IS NOT NULL
                  GROUP BY s.src
              )
              SELECT
                h.src                                     AS src,
                h.humans                                  AS humans,
                h.d_anon                                  AS d_anon,
                COALESCE(p.paid_keys, 0)                  AS paid_keys,
                COALESCE(p.paid_within_7d, 0)             AS paid_within_7d
              FROM human_per_src h
              LEFT JOIN paid_per_src p ON p.src = h.src
              ORDER BY h.humans DESC
              LIMIT 50""",
            (since, _FUNNEL_EVENT_PATH, since, _FUNNEL_EVENT_PATH),
        ).fetchall()

        # Per-src distinct_session count from funnel_events (best-effort —
        # tolerated-missing if 124 hasn't applied to funnel_events yet).
        sessions_per_src: dict[str, int] = {}
        if _table_exists(conn, "funnel_events") and _column_exists(
            conn, "funnel_events", "src"
        ):
            sess_rows = conn.execute(
                """SELECT
                     COALESCE(src, 'direct')        AS src,
                     COUNT(DISTINCT session_id)     AS sessions
                   FROM funnel_events
                  WHERE ts >= ?
                    AND is_bot = 0
               GROUP BY COALESCE(src, 'direct')""",
                (since,),
            ).fetchall()
            sessions_per_src = {
                r["src"]: int(r["sessions"] or 0) for r in sess_rows
            }

        by_src = [
            SrcAttributionBucket(
                src=r["src"],
                human_request_count=int(r["humans"] or 0),
                paid_conversion_count=int(r["paid_keys"] or 0),
                first_paid_within_7d_count=int(r["paid_within_7d"] or 0),
                distinct_sessions=sessions_per_src.get(r["src"], 0),
                distinct_anon_ips=int(r["d_anon"] or 0),
            )
            for r in rows
        ]

    return AnalyticsSplitResponse(
        hours=hours,
        total_requests=total_requests,
        bot_requests=bot_requests,
        human_requests=human_requests,
        paid_conversion_denominator_human_request=human_requests,
        by_ua_class=by_ua_class,
        funnel_events=funnel_rows,
        by_src=by_src,
        note="; ".join(notes) if notes else None,
    )


__all__ = ["router", "require_admin"]
