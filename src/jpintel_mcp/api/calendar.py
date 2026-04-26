"""GET /v1/calendar/deadlines — upcoming submission windows.

Surfaces the single question LLM agents keep asking but keep having to
reconstruct manually: "what deadlines are coming up in the next N days?".
Reads `application_window_json.end_date` across the programs corpus, filters
to windows that end between today and today+within_days, and orders by
deadline ascending so the most-urgent row comes first.

Currently pulls only from `application_window_json.end_date`. The enriched
C_procedure dimension carries richer multi-round `submission_windows[]`
structure for ~200 of the 11,211 programs; a future iteration will fold
those in when the shape stabilises.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.vocab import (
    _normalize_authority_level,
    _normalize_prefecture,
)

if TYPE_CHECKING:
    import sqlite3

router = APIRouter(prefix="/v1/calendar", tags=["calendar"])


class DeadlineEntry(BaseModel):
    """One program whose submission window ends within the query horizon."""

    model_config = ConfigDict(extra="forbid")

    unified_id: str
    primary_name: str
    tier: str | None
    authority_level: str | None
    prefecture: str | None
    end_date: str = Field(
        description="ISO YYYY-MM-DD of the next open-window close date.",
    )
    days_remaining: int = Field(
        ge=0,
        description="Whole days from today (UTC date) to end_date, inclusive of today.",
    )
    amount_max_man_yen: float | None
    application_url: str | None = Field(
        description="Where to send the applicant — aliases official_url."
    )


class DeadlinesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str = Field(
        description="Today's ISO date (UTC). Makes days_remaining reproducible."
    )
    within_days: int
    total: int = Field(description="Matching rows before `limit` was applied.")
    results: list[DeadlineEntry]


def _fetch_deadline_rows(
    conn: sqlite3.Connection,
    today_iso: str,
    horizon_iso: str,
    prefecture: str | None,
    authority_level: str | None,
    tier: list[str] | None,
    limit: int,
) -> list[sqlite3.Row]:
    """Pull programs whose application_window.end_date lies in [today, horizon].

    sqlite's json_extract lets us filter + sort in SQL rather than hydrating
    Programs in Python for thousands of rows. ISO YYYY-MM-DD sorts correctly
    lexicographically so no date casting is needed.
    """
    where: list[str] = [
        "excluded = 0",
        "COALESCE(tier,'X') != 'X'",
        "application_window_json IS NOT NULL",
        "json_extract(application_window_json, '$.end_date') IS NOT NULL",
        "json_extract(application_window_json, '$.end_date') >= ?",
        "json_extract(application_window_json, '$.end_date') <= ?",
    ]
    params: list[Any] = [today_iso, horizon_iso]
    if prefecture:
        where.append(
            "(prefecture = ? OR authority_level = 'national' OR prefecture IS NULL OR prefecture = '全国')"
        )
        params.append(prefecture)
    if authority_level:
        where.append("authority_level = ?")
        params.append(authority_level)
    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        params.extend(tier)

    sql = (
        "SELECT unified_id, primary_name, tier, authority_level, prefecture, "
        "amount_max_man_yen, official_url, "
        "json_extract(application_window_json, '$.end_date') AS _end_date "
        "FROM programs "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY _end_date ASC, unified_id "
        "LIMIT ?"
    )
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _fetch_deadline_count(
    conn: sqlite3.Connection,
    today_iso: str,
    horizon_iso: str,
    prefecture: str | None,
    authority_level: str | None,
    tier: list[str] | None,
) -> int:
    where: list[str] = [
        "excluded = 0",
        "COALESCE(tier,'X') != 'X'",
        "application_window_json IS NOT NULL",
        "json_extract(application_window_json, '$.end_date') IS NOT NULL",
        "json_extract(application_window_json, '$.end_date') >= ?",
        "json_extract(application_window_json, '$.end_date') <= ?",
    ]
    params: list[Any] = [today_iso, horizon_iso]
    if prefecture:
        where.append(
            "(prefecture = ? OR authority_level = 'national' OR prefecture IS NULL OR prefecture = '全国')"
        )
        params.append(prefecture)
    if authority_level:
        where.append("authority_level = ?")
        params.append(authority_level)
    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        params.extend(tier)

    (total,) = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE " + " AND ".join(where),
        params,
    ).fetchone()
    return int(total)


def run_upcoming_deadlines(
    conn: sqlite3.Connection,
    within_days: int = 30,
    prefecture: str | None = None,
    authority_level: str | None = None,
    tier: list[str] | None = None,
    limit: int = 50,
) -> DeadlinesResponse:
    """Pure function. REST + MCP parity — assumes normalized inputs.

    Date pivot is JST: Fly.io machines run UTC, so date.today() lags 9h
    behind JST between 00:00 and 09:00 JST and would mis-classify
    deadlines like 2026-05-31 17:00 JST as still open at 02:00 JST 6/1.
    """
    today = (datetime.now(UTC) + timedelta(hours=9)).date()
    horizon = today + timedelta(days=within_days)
    today_iso = today.isoformat()
    horizon_iso = horizon.isoformat()

    rows = _fetch_deadline_rows(
        conn,
        today_iso,
        horizon_iso,
        prefecture,
        authority_level,
        tier,
        limit,
    )
    total = _fetch_deadline_count(
        conn, today_iso, horizon_iso, prefecture, authority_level, tier
    )

    results: list[DeadlineEntry] = []
    for r in rows:
        end_iso = r["_end_date"]
        try:
            end_d = date.fromisoformat(end_iso[:10])
        except (ValueError, TypeError):
            continue
        days_remaining = (end_d - today).days
        if days_remaining < 0:
            continue
        results.append(
            DeadlineEntry(
                unified_id=r["unified_id"],
                primary_name=r["primary_name"],
                tier=r["tier"],
                authority_level=r["authority_level"],
                prefecture=r["prefecture"],
                end_date=end_iso[:10],
                days_remaining=days_remaining,
                amount_max_man_yen=r["amount_max_man_yen"],
                application_url=r["official_url"],
            )
        )

    return DeadlinesResponse(
        as_of=today_iso,
        within_days=within_days,
        total=total,
        results=results,
    )


@router.get(
    "/deadlines",
    response_model=DeadlinesResponse,
)
def get_deadlines(
    conn: DbDep,
    ctx: ApiContextDep,
    within_days: Annotated[
        int,
        Query(
            ge=1,
            le=180,
            description=(
                "Only return programs whose end_date falls between today "
                "and today + within_days (inclusive). Default 30."
            ),
        ),
    ] = 30,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "Prefecture filter. Canonical kanji ('東京都'), short ('東京'), "
                "romaji ('Tokyo'), or '全国' / 'national'. Nationwide programs "
                "and prefecture-unassigned rows are always included."
            ),
            max_length=40,
        ),
    ] = None,
    authority_level: Annotated[
        str | None,
        Query(
            description=(
                "Authority level filter. Canonical EN: national / prefecture / "
                "municipality / financial. Also accepts JP (国 / 都道府県 / 市区町村)."
            ),
            max_length=20,
        ),
    ] = None,
    tier: Annotated[
        list[str] | None,
        Query(description="Repeat to OR across tiers (e.g. tier=S&tier=A)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DeadlinesResponse:
    """List upcoming submission deadlines.

    Answers "what's due in the next 30 days for 東京 SMBs?" in one call so
    callers don't stitch together N search_programs requests. Programs
    without a structured end_date are silently excluded — they are not
    "no deadline", they are "we couldn't extract one" and need case-by-case
    lookup via get_program.
    """
    normalized_prefecture = _normalize_prefecture(prefecture)
    normalized_authority = _normalize_authority_level(authority_level)
    result = run_upcoming_deadlines(
        conn,
        within_days=within_days,
        prefecture=normalized_prefecture,
        authority_level=normalized_authority,
        tier=tier,
        limit=limit,
    )
    log_usage(
        conn,
        ctx,
        "calendar.deadlines",
        params={
            "within_days": within_days,
            "prefecture": normalized_prefecture,
            "authority_level": normalized_authority,
            "tier": sorted(tier) if tier else None,
        },
    )
    return result
