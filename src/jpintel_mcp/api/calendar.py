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

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
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

    as_of: str = Field(description="Today's ISO date (UTC). Makes days_remaining reproducible.")
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
    total = _fetch_deadline_count(conn, today_iso, horizon_iso, prefecture, authority_level, tier)

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
        strict_metering=True,
        params={
            "within_days": within_days,
            "prefecture": normalized_prefecture,
            "authority_level": normalized_authority,
            "tier": sorted(tier) if tier else None,
        },
    )
    return result


# ---------------------------------------------------------------------------
# GET /v1/calendar/deadlines.ics — RFC 5545 iCalendar feed
# ---------------------------------------------------------------------------
#
# Surfaces every future `am_application_round` row (autonomath.db) that maps
# back via `entity_id_map` to a `programs` row (jpintel.db) the calling key
# is authorised to see. Output is a RAW ICS body (NOT the universal envelope)
# at `text/calendar; charset=utf-8`. One billable unit per call.
#
# Cross-DB walk: autonomath.db is a separate SQLite file from jpintel.db, so
# we open a second read-only connection to autonomath.db for the round + map
# query and join programs in Python on `unified_id`. CLAUDE.md non-negotiable:
# no ATTACH / cross-DB JOIN.

# Hard cap. ICS clients that re-fetch hourly should never page-thrash on a
# multi-thousand-event feed; 500 is the empirical sweet-spot for Apple
# Calendar / Google Calendar import latency.
_ICS_HARD_CAP = 500


def _ics_escape(text: str) -> str:
    """RFC 5545 §3.3.11 escape for TEXT values: ``\\``, ``;``, ``,``, newlines."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _date_basic(d: date) -> str:
    """Format as ``YYYYMMDD`` for ``DTSTART;VALUE=DATE`` / ``DTEND;VALUE=DATE``."""
    return d.strftime("%Y%m%d")


def _fmt_dtstamp_utc(d: datetime) -> str:
    """Format as ``YYYYMMDDTHHMMSSZ`` for ``DTSTAMP`` (always UTC per §3.8.7.2)."""
    return d.strftime("%Y%m%dT%H%M%SZ")


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _fetch_rounds_and_map(
    today_iso: str,
    horizon_iso: str,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Read autonomath.db: future-within-horizon rounds + jpi→am map.

    Returns:
      * rounds: list of dicts with keys ``program_entity_id``,
        ``application_close_date``, ``application_open_date``, ``source_url``,
        ``round_label``, ``round_id``.
      * am_to_jpi: ``{am_canonical_id: [jpi_unified_id, ...]}``.

    The autonomath module's connection layer caches per-thread; tests
    purge the module to force a fresh import after monkeypatching
    ``AUTONOMATH_DB_PATH``. We import lazily inside the request scope so
    the freshly-set env var is honoured.
    """
    # Import inside the function so test monkeypatches that purge
    # `jpintel_mcp.mcp.autonomath_tools.db` from sys.modules force a
    # fresh module load (and a fresh `AUTONOMATH_DB_PATH` evaluation)
    # on the next call.
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    am_conn = connect_autonomath()

    rounds_sql = (
        "SELECT round_id, program_entity_id, round_label, "
        "application_open_date, application_close_date, source_url, status "
        "FROM am_application_round "
        "WHERE application_close_date IS NOT NULL "
        "  AND application_close_date >= ? "
        "  AND application_close_date <= ? "
        "  AND COALESCE(status, 'open') != 'closed' "
        "ORDER BY application_close_date ASC, round_id ASC"
    )
    rounds = [dict(r) for r in am_conn.execute(rounds_sql, (today_iso, horizon_iso)).fetchall()]

    map_sql = "SELECT jpi_unified_id, am_canonical_id FROM entity_id_map"
    am_to_jpi: dict[str, list[str]] = {}
    for r in am_conn.execute(map_sql).fetchall():
        am_to_jpi.setdefault(r["am_canonical_id"], []).append(r["jpi_unified_id"])

    return rounds, am_to_jpi


def _fetch_programs(
    conn: sqlite3.Connection,
    unified_ids: list[str],
    tier: list[str] | None,
    prefecture: str | None,
    authority_level: str | None,
) -> dict[str, dict[str, Any]]:
    """Read jpintel.db: hydrate ``programs`` rows for the given unified_ids.

    Filters out tier='X' / excluded=1 unconditionally. ``prefecture`` is the
    inclusive filter pattern: keep rows where prefecture matches OR the
    program is national-fallback (authority_level='国' OR prefecture IS NULL).
    """
    if not unified_ids:
        return {}

    where: list[str] = [
        "excluded = 0",
        "COALESCE(tier, 'X') != 'X'",
        f"unified_id IN ({','.join('?' * len(unified_ids))})",
    ]
    params: list[Any] = list(unified_ids)
    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        params.extend(tier)
    if prefecture:
        # Tokyo + national-fallback (authority_level='国' OR prefecture IS NULL).
        # Mirrors the existing /deadlines logic but uses '国' (jp canonical)
        # because the seeded fixture uses '国' for authority_level.
        where.append("(prefecture = ? OR prefecture IS NULL OR authority_level = '国')")
        params.append(prefecture)
    if authority_level:
        where.append("authority_level = ?")
        params.append(authority_level)

    sql = (
        "SELECT unified_id, primary_name, tier, authority_level, prefecture, "
        "amount_max_man_yen, official_url "
        "FROM programs "
        "WHERE " + " AND ".join(where)
    )
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql, params).fetchall():
        out[row["unified_id"]] = dict(row)
    return out


def _render_ics_body(
    *,
    events: list[dict[str, Any]],
    today_iso: str,
    horizon_iso: str,
    limit_hit: bool,
) -> str:
    """Build the RFC 5545 body. CRLF line endings (RFC mandate, §3.1).

    Each VEVENT carries:
      * ``UID:<unified_id>-<round_id>@jpcite.com`` (stable across re-renders)
      * ``DTSTAMP`` (now, UTC)
      * ``DTSTART;VALUE=DATE`` (close_date)
      * ``DTEND;VALUE=DATE`` (close_date + 1d — RFC 5545 §3.6.1: DTEND is
        exclusive for VALUE=DATE, so a one-day all-day event sets DTEND
        to the next day).
      * ``SUMMARY`` (escaped primary_name + ` 締切`)
      * ``URL`` (source_url, the round's first-party URL)
    """
    crlf = "\r\n"
    now_utc_stamp = _fmt_dtstamp_utc(datetime.now(UTC))

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Bookyou//jpcite calendar.deadlines.ics//JA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:jpcite deadlines",
        f"X-AS-OF:{today_iso}",
        f"X-HORIZON:{horizon_iso}",
    ]
    if limit_hit:
        # Calendar-level marker that tests can grep + that operators can
        # surface in dashboard "did this feed clip?" probes.
        lines.append(f"X-LIMIT-HIT:{_ICS_HARD_CAP}")

    for ev in events:
        uid = ev["uid"]
        summary = _ics_escape(ev["summary"])
        dtstart = _date_basic(ev["start"])
        dtend = _date_basic(ev["end"])
        url = ev.get("url") or ""
        block = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc_stamp}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            f"SUMMARY:{summary}",
        ]
        if url:
            # URL is a URI value; per §3.3.13 it is NOT TEXT-escaped,
            # but we still strip CR/LF defensively.
            block.append(f"URL:{url.replace(chr(13), '').replace(chr(10), '')}")
        block.append("END:VEVENT")
        lines.extend(block)

    lines.append("END:VCALENDAR")
    return crlf.join(lines) + crlf


def run_deadlines_ics(
    conn: sqlite3.Connection,
    *,
    within_days: int,
    tier: list[str] | None,
    prefecture: str | None,
    authority_level: str | None,
) -> tuple[str, bool, int]:
    """Pure function. Returns (ics_text, limit_hit, n_events).

    Date pivot is JST (UTC+9) — Fly.io machines run UTC, so a naive
    ``date.today()`` would mis-classify a 2026-05-31 17:00 JST deadline as
    open at 02:00 JST 6/1.
    """
    today = (datetime.now(UTC) + timedelta(hours=9)).date()
    horizon = today + timedelta(days=within_days)
    today_iso = today.isoformat()
    horizon_iso = horizon.isoformat()

    rounds, am_to_jpi = _fetch_rounds_and_map(today_iso, horizon_iso)

    # All jpi_unified_ids that the rounds could possibly cite.
    candidate_ids: set[str] = set()
    for r in rounds:
        for jpi in am_to_jpi.get(r["program_entity_id"], []):
            candidate_ids.add(jpi)

    programs = _fetch_programs(
        conn,
        list(candidate_ids),
        tier=tier,
        prefecture=prefecture,
        authority_level=authority_level,
    )

    # Rounds whose program survives the jpintel-side filter become events.
    events: list[dict[str, Any]] = []
    for r in rounds:
        for jpi in am_to_jpi.get(r["program_entity_id"], []):
            prog = programs.get(jpi)
            if prog is None:
                continue
            close_d = _parse_iso_date(r.get("application_close_date"))
            if close_d is None or close_d < today:
                continue
            uid = f"{jpi}-{r['round_id']}@jpcite.com"
            summary = f"{prog['primary_name']} 締切"
            events.append(
                {
                    "uid": uid,
                    "summary": summary,
                    "start": close_d,
                    # All-day event: DTEND is exclusive (§3.6.1) → next day.
                    "end": close_d + timedelta(days=1),
                    "url": r.get("source_url") or prog.get("official_url"),
                    "_unified_id": jpi,
                    "_round_id": r["round_id"],
                }
            )

    # Stable order: earliest-deadline first, then unified_id, then round_id.
    events.sort(
        key=lambda e: (
            e["start"].isoformat(),
            e["_unified_id"],
            e["_round_id"],
        )
    )

    # Hard cap to defend ICS clients that re-fetch hourly.
    limit_hit = len(events) > _ICS_HARD_CAP
    if limit_hit:
        events = events[:_ICS_HARD_CAP]

    body = _render_ics_body(
        events=events,
        today_iso=today_iso,
        horizon_iso=horizon_iso,
        limit_hit=limit_hit,
    )
    return body, limit_hit, len(events)


@router.get(
    "/deadlines.ics",
    # FastAPI infers the response_class for a Response return; we set
    # responses= so OpenAPI advertises text/calendar.
    responses={
        200: {
            "content": {"text/calendar": {}},
            "description": "RFC 5545 iCalendar feed of upcoming deadlines.",
        },
        401: {"description": "X-API-Key missing or invalid."},
    },
)
def get_deadlines_ics(
    conn: DbDep,
    ctx: ApiContextDep,
    within_days: Annotated[
        int,
        Query(
            ge=1,
            le=365,
            description=(
                "Only emit VEVENTs for rounds whose application_close_date "
                "falls between today (JST) and today + within_days "
                "(inclusive). Default 90."
            ),
        ),
    ] = 90,
    tier: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated tier list (e.g. ``S,A,B,C`` or ``S``). "
                "Non-public records are always excluded."
            ),
            max_length=20,
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            description=(
                "Prefecture filter. Canonical kanji ('東京都'), short "
                "('東京'), romaji ('Tokyo'), or '全国' / 'national'. "
                "Nationwide programs and prefecture-unassigned rows are "
                "always included."
            ),
            max_length=40,
        ),
    ] = None,
    authority_level: Annotated[
        str | None,
        Query(
            description=(
                "Authority-level filter. Canonical EN: national / prefecture / "
                "municipality / financial. Also accepts JP (国 / 都道府県 / "
                "市区町村)."
            ),
            max_length=20,
        ),
    ] = None,
) -> Response:
    """Per-account ICS feed of upcoming submission deadlines.

    Output is RFC 5545 (`text/calendar; charset=utf-8`). Each call is one
    billable unit (`endpoint=calendar.deadlines.ics`, quantity=1). Anonymous
    callers receive 401 — the feed is meant to be subscribed-to with a
    persistent X-API-Key.
    """
    # Auth fence — anon callers do not get the feed.
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "calendar.deadlines.ics requires an authenticated API key (X-API-Key).",
        )

    normalized_prefecture = _normalize_prefecture(prefecture)
    normalized_authority = _normalize_authority_level(authority_level)
    # Parse comma-separated tier — tests pass "S,A,B,C" as a single value.
    tier_list: list[str] | None = None
    if tier:
        tier_list = [t.strip() for t in tier.split(",") if t.strip()]
        if not tier_list:
            tier_list = None

    body, _limit_hit, _n_events = run_deadlines_ics(
        conn,
        within_days=within_days,
        tier=tier_list,
        prefecture=normalized_prefecture,
        authority_level=normalized_authority,
    )

    log_usage(
        conn,
        ctx,
        "calendar.deadlines.ics",
        quantity=1,
        strict_metering=True,
        params={
            "within_days": within_days,
            "tier": sorted(tier_list) if tier_list else None,
            "prefecture": normalized_prefecture,
            "authority_level": normalized_authority,
        },
    )

    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="jpcite-deadlines.ics"',
        },
    )
