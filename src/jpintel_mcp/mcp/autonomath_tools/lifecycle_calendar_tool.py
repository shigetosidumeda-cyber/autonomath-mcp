"""unified_lifecycle_calendar — O4 lifecycle calendar MCP tool (2026-04-25).

Merges 4 sunset / lifecycle sources into ONE month / half-year bucketed
calendar so an agent can ask "今後 6 ヶ月で何が切れるか" in 1 RPC instead
of orchestrating 4 separate tools.

Schema sources (autonomath.db, all read-only):

  am_tax_rule.effective_until           — 35 row, 57 filled (live, 一次資料)
                                          → kind = ``tax_sunset``
  am_amendment_snapshot.effective_*     — 14,596 row, 4 filled (effective_until)
                                          + 140 filled (effective_from). NOTE:
                                          eligibility_hash never changes between
                                          v1/v2 → time-series is FAKE per
                                          CLAUDE.md, so the snapshot surface is
                                          marked honestly with a ``data_quality``
                                          warning. We restrict to ISO YYYY-MM-DD
                                          dates only — non-ISO strings like
                                          "2032年頃（期間満了順次）" are dropped.
                                          → kind = ``program_sunset`` /
                                                  ``amendment_snapshot``
  am_application_round.application_close_date
                                        — 1,256 row, 394 filled (status='open'
                                          subset; 54 future / 17 within 60d).
                                          → kind = ``application_close``
  am_law_article.last_amended           — 28,048 row, 360 filled, 101 ISO
                                          parseable. Surface as forward-looking
                                          law cliff event (kind=``law_amendment``).

Severity ladder (deterministic, no LLM):

  critical  — sunset ≤ 30 days from today (cliff imminent)
  warning   — sunset 31..90 days from today
  info      — sunset > 90 days OR past-tense law amendment

Window cap: end_date - start_date ≤ 366 days. Caller asking for 5 years of
events must paginate by year — the tool refuses larger windows to keep p95
latency bounded and prevent pathological queries that would emit thousands
of rows in one envelope.

Memory alignment (verified before write):
  - feedback_no_fake_data            → ISO date filter on snapshot.effective_*
                                       drops the corrupt time-series strings;
                                       coverage caveat surfaced honestly.
  - feedback_autonomath_no_api_use   → pure SQL UNION ALL, no Anthropic calls.
  - feedback_zero_touch_solo         → ¥3/req metered only, no tier SKU.
  - feedback_completion_gate_minimal → 3 mandatory test cases, not 40+.
  - O4 design doc                    → analysis_wave18/_o4_lifecycle_2026-04-25.md
                                       §6.1 unified_lifecycle_calendar(start, end, kinds)

Env gate: ``AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED`` (default "1"). Set "0"
to omit this tool from the MCP surface (rollback only — canonical launch
state has it on).
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.lifecycle_calendar")

# Env-gated registration. Default is "1" (on); flip to "0" for rollback.
_ENABLED = os.environ.get("AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED", "1") == "1"

# Window cap. 1 year max so p95 latency stays bounded — agents must
# paginate by year for multi-year sweeps.
_MAX_WINDOW_DAYS = 366

# Severity thresholds (days from today, forward-looking only).
_CRITICAL_DAYS = 30
_WARNING_DAYS = 90

# Half-fiscal-year boundaries (Japanese 会計年度: Apr 1 .. Mar 31).
# H1 = 4/1..9/30, H2 = 10/1..3/31.
_H1_START_MONTH = 4
_H2_START_MONTH = 10

_DISCLAIMER = (
    "本 calendar は am_tax_rule (57 sunsets) + am_amendment_snapshot "
    "(4 ISO sunsets / 14,592 corrupt time-series 除外済) + am_application_round "
    "(394 close dates) + am_law_article (101 parseable last_amended) を "
    "merge した結果です。am_amendment_snapshot は eligibility_hash が v1/v2 "
    "間で不変 (time-series fake per CLAUDE.md) のため、ISO YYYY-MM-DD 形式の "
    "effective_until のみ採用しています。最終判断は一次資料 (source_url) と "
    "専門家確認を優先してください。"
)


# ---------------------------------------------------------------------------
# Date helpers.
# ---------------------------------------------------------------------------


def _parse_iso_date(s: str | None) -> datetime.date | None:
    """Parse YYYY-MM-DD strictly. Returns None on any non-ISO input."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s.strip())
    except (TypeError, ValueError):
        return None


def _today_jst() -> datetime.date:
    """JST today (autonomath canonical timezone for sunset calendars)."""
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=9)).date()


def _bucket_key(d: datetime.date, granularity: str) -> str:
    """Return the bucket label for date ``d`` at ``granularity``.

    granularity='month'      → "YYYY-MM"
    granularity='half_year'  → "YYYY-H1" / "YYYY-H2" (Japanese 会計年度).
                                H1 = 4/1..9/30, H2 = 10/1..3/31; the
                                Jan-Mar tail belongs to FY-1 H2.
    """
    if granularity == "month":
        return f"{d.year:04d}-{d.month:02d}"
    # half_year — fiscal year half. Jan/Feb/Mar = previous fiscal year H2.
    if d.month >= _H2_START_MONTH:  # Oct/Nov/Dec
        return f"{d.year:04d}-H2"
    if d.month >= _H1_START_MONTH:  # Apr..Sep
        return f"{d.year:04d}-H1"
    # Jan/Feb/Mar belong to (year-1) H2.
    return f"{d.year - 1:04d}-H2"


def _severity_for_sunset(d: datetime.date, today: datetime.date) -> str:
    """Forward-looking severity. Past-tense events return 'info'."""
    delta = (d - today).days
    if delta < 0:
        return "info"
    if delta <= _CRITICAL_DAYS:
        return "critical"
    if delta <= _WARNING_DAYS:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# Source queries. Each returns a list of dicts shaped like the public event
# record so the merger can simply concat + sort.
# ---------------------------------------------------------------------------


def _query_tax_sunsets(
    conn: sqlite3.Connection,
    start: datetime.date,
    end: datetime.date,
) -> list[dict[str, Any]]:
    """am_tax_rule.effective_until (live, 一次資料-backed)."""
    sql = """
        SELECT
            r.tax_measure_entity_id AS entity_id,
            r.rule_type,
            r.effective_until,
            r.source_url,
            m.primary_name
          FROM am_tax_rule r
          JOIN am_entities m
            ON m.canonical_id = r.tax_measure_entity_id
         WHERE r.effective_until IS NOT NULL
           AND r.effective_until BETWEEN ? AND ?
    """
    out: list[dict[str, Any]] = []
    for row in conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall():
        d = _parse_iso_date(row["effective_until"])
        if d is None:
            continue
        out.append({
            "kind": "tax_sunset",
            "entity_id": row["entity_id"],
            "title": row["primary_name"],
            "date": d.isoformat(),
            "rule_type": row["rule_type"],
            "source_url": row["source_url"],
        })
    return out


def _query_program_sunsets(
    conn: sqlite3.Connection,
    start: datetime.date,
    end: datetime.date,
) -> list[dict[str, Any]]:
    """am_amendment_snapshot.effective_until — ISO YYYY-MM-DD only.

    Per CLAUDE.md, am_amendment_snapshot is corrupt time-series (eligibility
    hash never changes). Of 14,596 rows, only 4 carry a non-NULL
    effective_until and not all are ISO-formatted. We restrict to strict
    ISO date strings — non-ISO ("2032年頃（期間満了順次）" / "2026-03") are
    dropped; we cannot honestly assign a calendar bucket to those.
    """
    sql = """
        SELECT
            s.entity_id,
            s.effective_until,
            s.source_url,
            e.primary_name
          FROM am_amendment_snapshot s
          LEFT JOIN am_entities e
            ON e.canonical_id = s.entity_id
         WHERE s.effective_until IS NOT NULL
    """
    out: list[dict[str, Any]] = []
    for row in conn.execute(sql).fetchall():
        d = _parse_iso_date(row["effective_until"])
        if d is None:
            continue
        if not (start <= d <= end):
            continue
        out.append({
            "kind": "program_sunset",
            "entity_id": row["entity_id"],
            "title": row["primary_name"] or row["entity_id"],
            "date": d.isoformat(),
            "source_url": row["source_url"],
        })
    return out


def _query_amendment_snapshots(
    conn: sqlite3.Connection,
    start: datetime.date,
    end: datetime.date,
) -> list[dict[str, Any]]:
    """am_amendment_snapshot.effective_from — ISO YYYY-MM-DD only.

    Forward-looking program effective dates (140 filled, mostly ISO).
    Honestly surfaced under the "amendment_snapshot" kind separately
    from "program_sunset" so consumers know whether the date is a START
    or an END.
    """
    sql = """
        SELECT
            s.entity_id,
            s.effective_from,
            s.source_url,
            e.primary_name
          FROM am_amendment_snapshot s
          LEFT JOIN am_entities e
            ON e.canonical_id = s.entity_id
         WHERE s.effective_from IS NOT NULL
    """
    out: list[dict[str, Any]] = []
    for row in conn.execute(sql).fetchall():
        d = _parse_iso_date(row["effective_from"])
        if d is None:
            continue
        if not (start <= d <= end):
            continue
        out.append({
            "kind": "amendment_snapshot",
            "entity_id": row["entity_id"],
            "title": row["primary_name"] or row["entity_id"],
            "date": d.isoformat(),
            "source_url": row["source_url"],
        })
    return out


def _query_application_closes(
    conn: sqlite3.Connection,
    start: datetime.date,
    end: datetime.date,
) -> list[dict[str, Any]]:
    """am_application_round.application_close_date.

    Includes status IN ('open','upcoming') so callers see both live windows
    and not-yet-opened rounds; status='closed' rounds are excluded (they
    represent past events with already-known outcome).
    """
    sql = """
        SELECT
            ar.round_id,
            ar.program_entity_id AS entity_id,
            ar.round_label,
            ar.application_close_date,
            ar.status,
            ar.source_url,
            e.primary_name
          FROM am_application_round ar
          LEFT JOIN am_entities e
            ON e.canonical_id = ar.program_entity_id
         WHERE ar.application_close_date IS NOT NULL
           AND ar.application_close_date BETWEEN ? AND ?
           AND ar.status IN ('open', 'upcoming')
    """
    out: list[dict[str, Any]] = []
    for row in conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall():
        d = _parse_iso_date(row["application_close_date"])
        if d is None:
            continue
        title = row["primary_name"] or row["entity_id"]
        if row["round_label"]:
            title = f"{title} ({row['round_label']})"
        out.append({
            "kind": "application_close",
            "entity_id": row["entity_id"],
            "title": title,
            "date": d.isoformat(),
            "round_id": row["round_id"],
            "status": row["status"],
            "source_url": row["source_url"],
        })
    return out


def _query_law_amendments(
    conn: sqlite3.Connection,
    start: datetime.date,
    end: datetime.date,
) -> list[dict[str, Any]]:
    """am_law_article.last_amended — ISO YYYY-MM-DD only.

    Only 101 of 28,048 rows have ISO-parseable last_amended; the rest carry
    raw 平9課消2-5 / 令5課消2-9 改正履歴 strings that need a separate
    parser (out of scope for this tool — see O4 design doc §1).
    """
    sql = """
        SELECT
            la.article_id,
            la.law_canonical_id,
            la.article_number,
            la.last_amended,
            la.source_url,
            e.primary_name AS law_name
          FROM am_law_article la
          LEFT JOIN am_entities e
            ON e.canonical_id = la.law_canonical_id
         WHERE la.last_amended IS NOT NULL
           AND la.last_amended GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
           AND la.last_amended BETWEEN ? AND ?
    """
    out: list[dict[str, Any]] = []
    for row in conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall():
        d = _parse_iso_date(row["last_amended"])
        if d is None:
            continue
        title_parts = [
            row["law_name"] or row["law_canonical_id"] or "(法令名不明)",
            row["article_number"] or "",
        ]
        title = " ".join(p for p in title_parts if p).strip()
        out.append({
            "kind": "law_amendment",
            "entity_id": row["law_canonical_id"] or f"law_article:{row['article_id']}",
            "title": title,
            "date": d.isoformat(),
            "article_id": row["article_id"],
            "source_url": row["source_url"],
        })
    return out


# ---------------------------------------------------------------------------
# Pure-Python core. Split from the @mcp.tool wrapper so tests can call it
# without going through the response sanitizer.
# ---------------------------------------------------------------------------


def _unified_lifecycle_calendar_impl(
    start_date: str,
    end_date: str,
    granularity: str = "month",
) -> dict[str, Any]:
    """Pure-Python core. Tests call this directly.

    Returns either the canonical envelope or an error envelope. Never
    raises.
    """
    today = _today_jst()

    # ---- arg validation ----
    if granularity not in ("month", "half_year"):
        return make_error(
            code="invalid_enum",
            message=f"granularity must be 'month' or 'half_year' (got {granularity!r}).",
            field="granularity",
            hint="Pass 'month' for YYYY-MM buckets or 'half_year' for fiscal-year halves.",
        )

    start = _parse_iso_date(start_date)
    if start is None:
        return make_error(
            code="invalid_date_format",
            message=f"start_date must be ISO YYYY-MM-DD (got {start_date!r}).",
            field="start_date",
            hint="Pass a date like '2026-05-01'.",
        )
    end = _parse_iso_date(end_date)
    if end is None:
        return make_error(
            code="invalid_date_format",
            message=f"end_date must be ISO YYYY-MM-DD (got {end_date!r}).",
            field="end_date",
            hint="Pass a date like '2027-04-30'.",
        )
    if end < start:
        return make_error(
            code="out_of_range",
            message=f"end_date ({end_date}) must be >= start_date ({start_date}).",
            field="end_date",
        )

    window_days = (end - start).days
    if window_days > _MAX_WINDOW_DAYS:
        return make_error(
            code="out_of_range",
            message=(
                f"window {window_days}d exceeds 1-year cap "
                f"({_MAX_WINDOW_DAYS}d). Paginate by year."
            ),
            field="end_date",
            hint=(
                "Restrict to <= 1 year. For multi-year sweeps, call this "
                "tool once per year (start..start+365d, then +1y, ...)."
            ),
        )

    # ---- DB open ----
    try:
        conn = connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["list_tax_sunset_alerts"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["list_tax_sunset_alerts"],
        )

    # ---- gather events from all 4 sources ----
    events: list[dict[str, Any]] = []
    sources_used: list[str] = []
    try:
        tax = _query_tax_sunsets(conn, start, end)
        events.extend(tax)
        sources_used.append(f"am_tax_rule:{len(tax)}")

        prog = _query_program_sunsets(conn, start, end)
        events.extend(prog)
        sources_used.append(f"am_amendment_snapshot.effective_until:{len(prog)}")

        amend = _query_amendment_snapshots(conn, start, end)
        events.extend(amend)
        sources_used.append(f"am_amendment_snapshot.effective_from:{len(amend)}")

        rounds = _query_application_closes(conn, start, end)
        events.extend(rounds)
        sources_used.append(f"am_application_round:{len(rounds)}")

        laws = _query_law_amendments(conn, start, end)
        events.extend(laws)
        sources_used.append(f"am_law_article:{len(laws)}")
    except sqlite3.Error as exc:
        logger.exception("unified_lifecycle_calendar query failed")
        return make_error(
            code="db_unavailable",
            message=f"lifecycle calendar query failed: {exc}",
            retry_with=["list_tax_sunset_alerts"],
        )

    # ---- enrich events with severity + sort ----
    for ev in events:
        d = datetime.date.fromisoformat(ev["date"])
        ev["severity"] = _severity_for_sunset(d, today)

    events.sort(key=lambda e: (e["date"], e["kind"], e["entity_id"]))

    # ---- bucket ----
    buckets: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        d = datetime.date.fromisoformat(ev["date"])
        key = _bucket_key(d, granularity)
        buckets.setdefault(key, []).append(ev)

    calendar = [
        {"period": k, "events": buckets[k]}
        for k in sorted(buckets.keys())
    ]

    severity_counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for ev in events:
        severity_counts[ev["severity"]] = severity_counts.get(ev["severity"], 0) + 1

    out: dict[str, Any] = {
        "calendar": calendar,
        "total_events": len(events),
        "severity_counts": severity_counts,
        "window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "granularity": granularity,
            "window_days": window_days,
        },
        "data_as_of": today.isoformat(),
        "sources_used": sources_used,
        "data_quality": {
            "amendment_snapshot_caveat": (
                "am_amendment_snapshot は CLAUDE.md 記載の通り "
                "eligibility_hash 不変 (time-series fake)。"
                "ISO YYYY-MM-DD effective_* のみ採用、非 ISO 文字列は "
                "calendar に出ません。"
            ),
            "law_amendment_coverage": (
                "am_law_article.last_amended は 28,048 行中 ISO parseable "
                "は 101 行のみ。残りは raw 改正履歴 string で別 parser "
                "が必要 (本 tool 範囲外)。"
            ),
        },
        "_disclaimer": _DISCLAIMER,
        # Envelope keys for tolerant consumers.
        "total": len(events),
        "limit": len(events),
        "offset": 0,
        "results": events,
    }

    if not events:
        err = make_error(
            code="no_matching_records",
            message=(
                f"no lifecycle events between {start.isoformat()} "
                f"and {end.isoformat()}."
            ),
            hint=(
                "Try widening the window (up to 1 year) or ensure today's "
                "JST date falls before the cliff dates of interest."
            ),
            retry_with=["list_tax_sunset_alerts", "list_open_programs"],
        )
        out["error"] = err["error"]

    return out


# ---------------------------------------------------------------------------
# MCP tool registration. Env-gated.
# ---------------------------------------------------------------------------

if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def unified_lifecycle_calendar(
        start_date: Annotated[
            str,
            Field(
                description=(
                    "ウィンドウ開始日 (ISO YYYY-MM-DD)。"
                    "end_date - start_date <= 366 日。"
                ),
                min_length=10,
                max_length=10,
            ),
        ],
        end_date: Annotated[
            str,
            Field(
                description=(
                    "ウィンドウ終了日 (ISO YYYY-MM-DD)。"
                    "1 年超は 422 (out_of_range) を返します。"
                ),
                min_length=10,
                max_length=10,
            ),
        ],
        granularity: Annotated[
            Literal["month", "half_year"],
            Field(
                description=(
                    "Bucket 粒度。'month' = YYYY-MM、'half_year' = "
                    "会計年度半期 (H1=4-9月 / H2=10-3月)。"
                ),
            ),
        ] = "month",
    ) -> dict[str, Any]:
        """[O4-LIFECYCLE-CALENDAR] tax sunset + program sunset + application close + law cliff を月別/半期別 1 コール merge。

        WHAT: 4 source (am_tax_rule.effective_until / am_amendment_snapshot
        .effective_* (ISO のみ) / am_application_round.application_close_date /
        am_law_article.last_amended) を UNION + bucket した event 一覧を返す。
        kind ∈ {tax_sunset, program_sunset, amendment_snapshot,
        application_close, law_amendment}。severity は forward-looking で
        critical (≤30d) / warning (≤90d) / info (それ以外)。

        WHEN:
          - 「2026 年下半期に切れる税制+補助金 申請窓口を 1 画面で」
          - 「半期 (H1/H2) 単位で何が cliff か」(granularity='half_year')
          - 事業計画 / 投資判断 / 監査の sunset カレンダー作成

        WHEN NOT:
          - 税制のみ + 大綱 cliff bucket → list_tax_sunset_alerts
          - 申請可能な program list → list_open_programs / active_programs_at
          - 単一 program の lifecycle 履歴 → 設計中 program_lifecycle (P2)

        RETURNS (envelope):
          {
            calendar: [
              {period: "YYYY-MM"|"YYYY-H1"|"YYYY-H2",
               events: [{kind, entity_id, title, date, severity, ...}]},
              ...
            ],
            total_events: int,
            severity_counts: {critical, warning, info},
            window: {start_date, end_date, granularity, window_days},
            data_as_of: str,                # JST today
            sources_used: [str, ...],       # per-source row counts
            data_quality: {                 # honest caveats
              amendment_snapshot_caveat: str,
              law_amendment_coverage: str,
            },
            _disclaimer: str,
          }

        DATA QUALITY HONESTY: am_amendment_snapshot は CLAUDE.md 記載通り
        eligibility_hash 不変 (time-series fake)。本 tool は ISO YYYY-MM-DD
        の effective_* のみ採用し、非 ISO 文字列を calendar に出さない。
        am_law_article.last_amended も 28,048 中 ISO parseable は 101 行のみ。
        残り (raw 改正履歴 string) は本 tool 範囲外。

        WINDOW CAP: end - start <= 366 日。1 年超は code='out_of_range' で
        422 相当を返す。多年スイープは年単位 pagination が必要。

        CHAIN:
          ← `list_tax_sunset_alerts` で税制のみ深掘り。
          → `get_am_tax_rule(entity_id)` で個別 rule 詳細。
          → `list_open_programs` で kind='application_close' の補助金本体探索。
        """
        return _unified_lifecycle_calendar_impl(
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )


__all__ = [
    "_unified_lifecycle_calendar_impl",
    "_bucket_key",
    "_severity_for_sunset",
    "_parse_iso_date",
    "_MAX_WINDOW_DAYS",
    "_CRITICAL_DAYS",
    "_WARNING_DAYS",
]


# ---------------------------------------------------------------------------
# Self-test harness (not part of MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.lifecycle_calendar_tool
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    today = _today_jst()
    end = today + datetime.timedelta(days=365)
    res = _unified_lifecycle_calendar_impl(
        start_date=today.isoformat(),
        end_date=end.isoformat(),
        granularity="month",
    )
    print(f"total_events={res.get('total_events')}, "
          f"severity={res.get('severity_counts')}")
    print(f"sources_used={res.get('sources_used')}")
    for bucket in res.get("calendar", [])[:3]:
        print(f"\n--- {bucket['period']} ({len(bucket['events'])} events) ---")
        for ev in bucket["events"][:5]:
            pprint.pprint(ev)
