#!/usr/bin/env python3
"""法令改正アラート (Compliance Alerts) daily cron.

Runs once a day at 08:00 JST and:

  * For `plan='paid'` verified subscribers: scans rows across
    `programs`, `laws`, `tax_rulesets`, `enforcement_cases`,
    `court_decisions`, `invoice_registrants` whose `updated_at` is within
    the last 24h, intersects with each subscriber's areas_of_interest /
    industry / prefecture filter, and — if ≥1 match — sends a single
    digest email to that subscriber.
  * On the 1st of the month (JST): for `plan='free'` verified
    subscribers, emits a monthly digest covering the prior calendar
    month's changes.

Idempotency: before sending, the cron checks
`compliance_notification_log` for an existing row with the same
`subscriber_id` and `date(sent_at) = today (JST)`. If one exists we skip
the send. `--force` overrides this guard.

Installation (DO NOT run from this script; documented only):

    # crontab — macOS / linux
    0 8 * * * cd /path/to/jpintel-mcp && .venv/bin/python scripts/compliance_cron.py

    # launchd (macOS) — see docs/compliance_alerts_runbook.md

Usage:

    python scripts/compliance_cron.py            # real run
    python scripts/compliance_cron.py --dry-run  # log would-send, no emails, no DB writes
    python scripts/compliance_cron.py --force    # re-send even if already logged today
    python scripts/compliance_cron.py --mode=digest  # force monthly digest path

Dependencies come from the repo: the script uses `jpintel_mcp.db.connect`
for the DB handle and `jpintel_mcp.email.compliance_templates` for the
body composition. It does NOT call any LLM — per-customer email bodies
are pure Jinja2 over structured DB rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

# Allow running as `python scripts/compliance_cron.py` without install
# by pushing repo src/ onto sys.path when the package isn't importable.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.email.compliance_templates import (  # noqa: E402
    Change,
    compose_alert_email,
)
from jpintel_mcp.utils.slug import program_static_url  # noqa: E402

logger = logging.getLogger("jpintel.compliance_cron")

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Source table metadata — one row per queryable table.
# ---------------------------------------------------------------------------
#
# `area`  : the area_of_interest code this table maps to. Subscribers who
#           include this area in their JSON array will receive rows from
#           this table.
# `sql`   : SELECT statement returning columns
#             (unified_id, title, summary, source_url, updated_at, prefecture?)
#           — prefecture is optional; rows without it match every subscriber
#           regardless of their prefecture filter.
# `fallback_time_col` : column to use as the "changed at" anchor when the
#           table has no `updated_at` (enforcement_cases only). We sort by
#           this and compare against the window via `fetched_at` since
#           the underlying "disclosed_date" is a date not a timestamp.
@dataclass
class _TableSpec:
    area: str
    table: str
    sql_24h: str
    sql_month: str
    has_prefecture: bool = False
    has_industry: bool = False


# Query templates share a common shape. The `since` parameter is the ISO
# timestamp lower bound (exclusive would be safer but practically
# inclusive at 24h granularity is harmless). `until` is the upper bound
# for monthly digest (prior-month-end); for the 24h case we pass None.

_TABLES: list[_TableSpec] = [
    _TableSpec(
        area="subsidy",
        table="programs",
        sql_24h=(
            "SELECT unified_id, primary_name AS title, "
            "       COALESCE(program_kind,'') AS summary, "
            "       COALESCE(source_url,'') AS source_url, "
            "       updated_at, prefecture "
            "FROM programs "
            "WHERE excluded = 0 "
            "  AND tier IN ('S','A','B','C') "
            "  AND updated_at >= ? "
            "ORDER BY updated_at DESC LIMIT 200"
        ),
        sql_month=(
            "SELECT unified_id, primary_name AS title, "
            "       COALESCE(program_kind,'') AS summary, "
            "       COALESCE(source_url,'') AS source_url, "
            "       updated_at, prefecture "
            "FROM programs "
            "WHERE excluded = 0 "
            "  AND tier IN ('S','A','B','C') "
            "  AND updated_at >= ? AND updated_at < ? "
            "ORDER BY updated_at DESC LIMIT 500"
        ),
        has_prefecture=True,
    ),
    _TableSpec(
        area="invoice",
        table="tax_rulesets",
        # tax_rulesets covers invoice + tax + e-bookkeeping. We fan this
        # single-table query out onto THREE area buckets in the runtime
        # glue below so a subscriber interested only in "ebook" still
        # gets the 電子帳簿保存法 rulesets from this table.
        sql_24h=(
            "SELECT unified_id, ruleset_name AS title, "
            "       COALESCE(eligibility_conditions,'') AS summary, "
            "       source_url, updated_at, "
            "       tax_category, ruleset_kind "
            "FROM tax_rulesets "
            "WHERE updated_at >= ? "
            "ORDER BY updated_at DESC LIMIT 200"
        ),
        sql_month=(
            "SELECT unified_id, ruleset_name AS title, "
            "       COALESCE(eligibility_conditions,'') AS summary, "
            "       source_url, updated_at, "
            "       tax_category, ruleset_kind "
            "FROM tax_rulesets "
            "WHERE updated_at >= ? AND updated_at < ? "
            "ORDER BY updated_at DESC LIMIT 500"
        ),
    ),
    _TableSpec(
        area="court",
        table="court_decisions",
        sql_24h=(
            "SELECT unified_id, case_name AS title, "
            "       COALESCE(key_ruling, impact_on_business, '') AS summary, "
            "       source_url, updated_at "
            "FROM court_decisions "
            "WHERE updated_at >= ? "
            "ORDER BY updated_at DESC LIMIT 200"
        ),
        sql_month=(
            "SELECT unified_id, case_name AS title, "
            "       COALESCE(key_ruling, impact_on_business, '') AS summary, "
            "       source_url, updated_at "
            "FROM court_decisions "
            "WHERE updated_at >= ? AND updated_at < ? "
            "ORDER BY updated_at DESC LIMIT 500"
        ),
    ),
    _TableSpec(
        area="enforcement",
        table="enforcement_cases",
        # enforcement_cases has no `updated_at` column; we key off
        # fetched_at since that's the only monotonic anchor.
        sql_24h=(
            "SELECT case_id AS unified_id, "
            "       COALESCE(program_name_hint, '(enforcement)') AS title, "
            "       COALESCE(reason_excerpt, '') AS summary, "
            "       source_url, fetched_at AS updated_at, "
            "       prefecture "
            "FROM enforcement_cases "
            "WHERE fetched_at >= ? "
            "ORDER BY fetched_at DESC LIMIT 200"
        ),
        sql_month=(
            "SELECT case_id AS unified_id, "
            "       COALESCE(program_name_hint, '(enforcement)') AS title, "
            "       COALESCE(reason_excerpt, '') AS summary, "
            "       source_url, fetched_at AS updated_at, "
            "       prefecture "
            "FROM enforcement_cases "
            "WHERE fetched_at >= ? AND fetched_at < ? "
            "ORDER BY fetched_at DESC LIMIT 500"
        ),
        has_prefecture=True,
    ),
    _TableSpec(
        area="subsidy",  # laws surface as part of the subsidy / loan context
        table="laws",
        sql_24h=(
            "SELECT unified_id, law_title AS title, "
            "       COALESCE(summary,'') AS summary, "
            "       source_url, updated_at "
            "FROM laws "
            "WHERE updated_at >= ? AND revision_status = 'current' "
            "ORDER BY updated_at DESC LIMIT 200"
        ),
        sql_month=(
            "SELECT unified_id, law_title AS title, "
            "       COALESCE(summary,'') AS summary, "
            "       source_url, updated_at "
            "FROM laws "
            "WHERE updated_at >= ? AND updated_at < ? "
            "  AND revision_status = 'current' "
            "ORDER BY updated_at DESC LIMIT 500"
        ),
    ),
]


# Map internal tax_rulesets row -> area codes based on tax_category /
# ruleset_kind. A single tax_rulesets row can surface under multiple
# areas (invoice + tax_ruleset, etc.). The cron dedupes per (subscriber,
# unified_id).
def _tax_ruleset_areas(row: sqlite3.Row) -> list[str]:
    cat = (row["tax_category"] or "").lower() if "tax_category" in row else ""
    kind = (row["ruleset_kind"] or "").lower() if "ruleset_kind" in row else ""
    areas: list[str] = []
    # インボイス登録 / 適格請求書 rulesets
    if "consumption" in cat or kind in {"registration"}:
        areas.append("invoice")
    # 電子帳簿保存法 — ruleset_kind='preservation' is the canonical anchor
    if kind == "preservation":
        areas.append("ebook")
    # Everything else surfaces as "tax_ruleset"
    if "tax_ruleset" not in areas:
        areas.append("tax_ruleset")
    return areas


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class SubscriberRow:
    id: int
    email: str
    houjin_bangou: str | None
    industry_codes: list[str] = field(default_factory=list)
    areas_of_interest: list[str] = field(default_factory=list)
    prefecture: str | None = None
    plan: str = "free"
    unsubscribe_token: str = ""

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> SubscriberRow:
        return cls(
            id=int(r["id"]),
            email=r["email"],
            houjin_bangou=r["houjin_bangou"],
            industry_codes=_safe_json_list(r["industry_codes_json"]),
            areas_of_interest=_safe_json_list(r["areas_of_interest_json"]),
            prefecture=r["prefecture"],
            plan=r["plan"] or "free",
            unsubscribe_token=r["unsubscribe_token"],
        )


def _safe_json_list(s: Any) -> list[str]:
    if not s:
        return []
    try:
        val = json.loads(s)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _jst_now() -> datetime:
    return datetime.now(JST)


def _fetch_active_subscribers(
    conn: sqlite3.Connection, plan: Literal["free", "paid"]
) -> list[SubscriberRow]:
    rows = conn.execute(
        """SELECT id, email, houjin_bangou, industry_codes_json,
                  areas_of_interest_json, prefecture, plan, unsubscribe_token
             FROM compliance_subscribers
            WHERE canceled_at IS NULL
              AND verified_at IS NOT NULL
              AND plan = ?""",
        (plan,),
    ).fetchall()
    return [SubscriberRow.from_row(r) for r in rows]


def _already_sent_today(conn: sqlite3.Connection, subscriber_id: int, today_jst: str) -> bool:
    """True if the subscriber already got an alert today (JST)."""
    row = conn.execute(
        """SELECT 1 FROM compliance_notification_log
            WHERE subscriber_id = ?
              AND date(sent_at) = ?
            LIMIT 1""",
        (subscriber_id, today_jst),
    ).fetchone()
    return row is not None


def _collect_candidate_changes(
    conn: sqlite3.Connection,
    *,
    since_iso: str,
    until_iso: str | None,
) -> list[Change]:
    """Pull every changed row across the source tables into a flat list.

    The cron filters PER subscriber afterwards (cheaper than running
    custom SQL per subscriber because the cohort is small and the
    source tables are modest in size).
    """
    out: list[Change] = []
    for spec in _TABLES:
        sql = spec.sql_24h if until_iso is None else spec.sql_month
        params: tuple[Any, ...] = (since_iso,) if until_iso is None else (since_iso, until_iso)
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            # Missing table on a fresh volume — skip quietly so the cron
            # still runs end to end. Production DBs have all migrations
            # applied; test DBs often do not.
            logger.warning("cron.table_missing table=%s err=%s", spec.table, exc)
            continue
        for r in rows:
            r["prefecture"] if spec.has_prefecture and "prefecture" in r else None
            updated = r["updated_at"]
            detail_url = _detail_url(
                spec.table,
                r["unified_id"],
                r["title"] if spec.table == "programs" else None,
            )

            areas = _tax_ruleset_areas(r) if spec.table == "tax_rulesets" else [spec.area]

            for area in areas:
                out.append(
                    Change(
                        unified_id=r["unified_id"],
                        table=spec.table,
                        area=area,
                        title=r["title"] or "",
                        summary=(r["summary"] or "")[:240],
                        source_url=r["source_url"] or "",
                        detail_url=detail_url,
                        updated_at=updated or "",
                    )
                )
    return out


def _detail_url(table: str, unified_id: str, primary_name: str | None = None) -> str:
    """Construct the AutonoMath public detail URL for a row.

    Per-program static pages exist at `/programs/{slug}.html`;
    other tables do not have static pages yet, so we point at the docs
    or back to the homepage so the link is never a 404.
    """
    if table == "programs":
        if primary_name and unified_id:
            return program_static_url(primary_name, unified_id, domain="jpcite.com")
        return f"https://jpcite.com/programs/share.html?ids={quote(unified_id, safe='')}"
    if table == "laws":
        return f"https://jpcite.com/docs/laws/{unified_id}"
    if table == "court_decisions":
        return f"https://jpcite.com/docs/court_decisions/{unified_id}"
    if table == "tax_rulesets":
        return f"https://jpcite.com/docs/tax_rulesets/{unified_id}"
    if table == "enforcement_cases":
        return f"https://jpcite.com/docs/enforcement/{unified_id}"
    return ""


# ---------------------------------------------------------------------------
# Per-subscriber filter
# ---------------------------------------------------------------------------


def _filter_for_subscriber(changes: list[Change], sub: SubscriberRow) -> list[Change]:
    """Return the subset of `changes` that this subscriber cares about.

    Filters applied:
        1. Change's `area` must be in subscriber's `areas_of_interest`.
        2. If the subscriber has a `prefecture`, changes that carry a
           prefecture field must match (changes without a prefecture pass
           through — national programs are relevant everywhere).
        3. De-dup by (unified_id, area) — tax_ruleset rows can appear
           under multiple areas; a subscriber who asked for both invoice
           and tax_ruleset should get the row once.

    Industry codes (JSIC) are NOT used as a filter for MVP — none of the
    source tables currently carry JSIC metadata. The column is captured
    for future use (and for operator-side analytics).
    """
    interest = set(sub.areas_of_interest)
    seen: set[tuple[str, str]] = set()
    out: list[Change] = []
    for c in changes:
        if c["area"] not in interest:
            continue
        # prefecture filter
        change_pref = _row_prefecture(c)
        if sub.prefecture and change_pref and change_pref != sub.prefecture:
            continue
        key = (c["unified_id"], c["area"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _row_prefecture(c: Change) -> str | None:
    # Change TypedDict doesn't declare prefecture, but the dict may
    # carry it since _collect_candidate_changes constructs dicts via the
    # TypedDict constructor which accepts extra keys.
    return c.get("prefecture")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Send path
# ---------------------------------------------------------------------------


def _send_email(
    *,
    sub: SubscriberRow,
    subject: str,
    html: str,
    text: str,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """Send one email. Returns (delivered, error)."""
    if dry_run:
        logger.info(
            "cron.dry_run.send to=%s subject=%s",
            _redact_email(sub.email),
            subject,
        )
        return True, None
    try:
        from jpintel_mcp.config import settings
        from jpintel_mcp.email.postmark import (
            POSTMARK_BASE_URL,
            STREAM_BROADCAST,
            get_client,
        )

        client = get_client()
        if client.test_mode:
            logger.info(
                "cron.send.test_mode to=%s subject=%s",
                _redact_email(sub.email),
                subject,
            )
            return True, None

        import httpx

        with httpx.Client(
            base_url=POSTMARK_BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_api_token,
            },
        ) as http:
            payload = {
                "From": settings.postmark_from_transactional,
                "To": sub.email,
                "Subject": subject,
                "HtmlBody": html,
                "TextBody": text,
                "MessageStream": STREAM_BROADCAST,
                "Tag": "compliance-alert",
                "TrackOpens": True,
                "TrackLinks": "HtmlAndText",
            }
            if settings.postmark_from_reply:
                payload["ReplyTo"] = settings.postmark_from_reply
            r = http.post("/email", json=payload)
            if r.status_code >= 400:
                return False, f"postmark {r.status_code}: {r.text[:200]}"
            return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:500]


def _redact_email(addr: str) -> str:
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def _log_notification(
    conn: sqlite3.Connection,
    *,
    subscriber_id: int,
    subject: str,
    changes: list[Change],
    delivered: bool,
    error: str | None,
) -> None:
    conn.execute(
        """INSERT INTO compliance_notification_log
             (subscriber_id, sent_at, subject, changes_json, delivered, error)
           VALUES (?,?,?,?,?,?)""",
        (
            subscriber_id,
            datetime.now(UTC).isoformat(),
            subject,
            json.dumps(
                [
                    {
                        "unified_id": c["unified_id"],
                        "table": c["table"],
                        "summary": c["summary"][:200],
                        "source_url": c["source_url"],
                    }
                    for c in changes
                ],
                ensure_ascii=False,
            ),
            1 if delivered else 0,
            error,
        ),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_realtime(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    """Daily real-time run (paid subs)."""
    since = (now - timedelta(hours=24)).astimezone(UTC).isoformat()
    today_jst = now.astimezone(JST).date().isoformat()
    subs = _fetch_active_subscribers(conn, "paid")
    logger.info("cron.realtime subscribers=%d since=%s", len(subs), since)

    candidates = _collect_candidate_changes(conn, since_iso=since, until_iso=None)
    logger.info("cron.realtime candidate_changes=%d", len(candidates))

    summary: dict[str, Any] = {
        "mode": "realtime",
        "subscribers": len(subs),
        "candidates": len(candidates),
        "sent": 0,
        "skipped_noop": 0,
        "skipped_already_sent": 0,
        "failed": 0,
    }

    for sub in subs:
        if not force and _already_sent_today(conn, sub.id, today_jst):
            summary["skipped_already_sent"] += 1
            continue
        matches = _filter_for_subscriber(candidates, sub)
        if not matches:
            summary["skipped_noop"] += 1
            continue
        composed = compose_alert_email(
            {
                "id": sub.id,
                "email": sub.email,
                "prefecture": sub.prefecture,
                "plan": sub.plan,
                "unsubscribe_token": sub.unsubscribe_token,
                "areas_of_interest": sub.areas_of_interest,
                "industry_codes": sub.industry_codes,
            },
            matches,
            mode="realtime",
        )
        delivered, error = _send_email(
            sub=sub,
            subject=composed["subject"],
            html=composed["html"],
            text=composed["text"],
            dry_run=dry_run,
        )
        if dry_run:
            logger.info(
                "cron.dry_run subscriber=%s matches=%d subject=%s",
                sub.id,
                len(matches),
                composed["subject"],
            )
            summary["sent"] += 1 if delivered else 0
            summary["failed"] += 0 if delivered else 1
            continue
        _log_notification(
            conn,
            subscriber_id=sub.id,
            subject=composed["subject"],
            changes=matches,
            delivered=delivered,
            error=error,
        )
        if delivered:
            conn.execute(
                "UPDATE compliance_subscribers SET "
                "last_notified_at = ?, "
                "notification_count_mtd = COALESCE(notification_count_mtd,0) + 1, "
                "updated_at = ? "
                "WHERE id = ?",
                (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), sub.id),
            )
            summary["sent"] += 1
        else:
            summary["failed"] += 1
            logger.warning("cron.send.failed subscriber=%s err=%s", sub.id, error)
    return summary


def run_digest(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    """Monthly digest (free subs). Covers prior calendar month (JST)."""
    jst_now = now.astimezone(JST)
    # First of this month JST:
    first_of_this = jst_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_of_prev = first_of_this - timedelta(seconds=1)
    first_of_prev = last_of_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = first_of_prev.astimezone(UTC).isoformat()
    until = first_of_this.astimezone(UTC).isoformat()
    ym = first_of_prev.strftime("%Y-%m")
    today_jst = jst_now.date().isoformat()

    subs = _fetch_active_subscribers(conn, "free")
    logger.info(
        "cron.digest subscribers=%d ym=%s window=%s..%s",
        len(subs),
        ym,
        since,
        until,
    )

    candidates = _collect_candidate_changes(conn, since_iso=since, until_iso=until)
    logger.info("cron.digest candidate_changes=%d", len(candidates))

    summary: dict[str, Any] = {
        "mode": "digest",
        "ym": ym,
        "subscribers": len(subs),
        "candidates": len(candidates),
        "sent": 0,
        "skipped_noop": 0,
        "skipped_already_sent": 0,
        "failed": 0,
    }

    for sub in subs:
        if not force and _already_sent_today(conn, sub.id, today_jst):
            summary["skipped_already_sent"] += 1
            continue
        matches = _filter_for_subscriber(candidates, sub)
        if not matches:
            summary["skipped_noop"] += 1
            continue
        composed = compose_alert_email(
            {
                "id": sub.id,
                "email": sub.email,
                "prefecture": sub.prefecture,
                "plan": sub.plan,
                "unsubscribe_token": sub.unsubscribe_token,
                "areas_of_interest": sub.areas_of_interest,
                "industry_codes": sub.industry_codes,
            },
            matches,
            mode="digest",
            period_label=ym,
        )
        delivered, error = _send_email(
            sub=sub,
            subject=composed["subject"],
            html=composed["html"],
            text=composed["text"],
            dry_run=dry_run,
        )
        if dry_run:
            logger.info("cron.dry_run.digest subscriber=%s matches=%d", sub.id, len(matches))
            summary["sent"] += 1 if delivered else 0
            continue
        _log_notification(
            conn,
            subscriber_id=sub.id,
            subject=composed["subject"],
            changes=matches,
            delivered=delivered,
            error=error,
        )
        if delivered:
            conn.execute(
                "UPDATE compliance_subscribers SET "
                "last_notified_at = ?, "
                "notification_count_mtd = COALESCE(notification_count_mtd,0) + 1, "
                "updated_at = ? "
                "WHERE id = ?",
                (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), sub.id),
            )
            summary["sent"] += 1
        else:
            summary["failed"] += 1
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compliance_cron",
        description="Daily + monthly digest cron for 法令改正アラート.",
    )
    p.add_argument("--db", type=Path, default=None, help="SQLite DB path")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be sent; do not send email, do not write logs.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Send even if compliance_notification_log shows a send today.",
    )
    p.add_argument(
        "--mode",
        choices=["auto", "realtime", "digest", "both"],
        default="auto",
        help=(
            "auto = realtime every day + digest on the 1st of the month (JST). "
            "both = run both paths unconditionally. realtime / digest = single path."
        ),
    )
    return p


def _resolve_modes(mode: str, now: datetime) -> list[str]:
    if mode == "realtime":
        return ["realtime"]
    if mode == "digest":
        return ["digest"]
    if mode == "both":
        return ["realtime", "digest"]
    # auto
    jst = now.astimezone(JST)
    if jst.day == 1:
        return ["realtime", "digest"]
    return ["realtime"]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    args = _build_parser().parse_args(argv)
    now = datetime.now(UTC)

    conn = connect(args.db)
    try:
        all_summaries = []
        for m in _resolve_modes(args.mode, now):
            if m == "realtime":
                all_summaries.append(
                    run_realtime(conn, now=now, dry_run=args.dry_run, force=args.force)
                )
            else:
                all_summaries.append(
                    run_digest(conn, now=now, dry_run=args.dry_run, force=args.force)
                )
        logger.info("cron.summary %s", json.dumps(all_summaries, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
