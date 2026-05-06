"""Onboarding-mail scheduler.

Powers the D+1 / D+3 / D+7 / D+14 / D+30 activation sequence from
`onboarding.py`. D+0 is deliberately OUT of scope: it is fired
synchronously from `api/billing.py::_send_welcome_safe` at key issuance
time because the TemplateModel carries the one-time raw API key (which
must never be persisted into `email_schedule` — rows in that table only
hold the hash). Wiring D+0 into the cron here would guarantee a
double-send. See `onboarding.py::send_day0_welcome` for the direct path.

Two responsibilities, one module:

    1. `enqueue_onboarding_sequence()` — called at key issuance time
       (`billing/keys.issue_key`) to insert the four `email_schedule` rows
       whose `send_at` timestamps are relative to the issuance moment.
    2. `run_due()` — the cron-side dispatcher. Selects rows whose
       `send_at <= now()` AND `sent_at IS NULL`, resolves the current
       `usage_count` from `usage_events`, fires the right `send_dayN` helper,
       and marks the row as sent (or increments `attempts` on failure).

Why this shape
--------------
* The scheduler does NOT decide WHICH template to use from wallclock math —
  the `kind` column is the source of truth, so a backfill / replay after
  an outage dispatches the template the customer was originally supposed
  to receive (not whatever cohort they now fall into).
* Idempotent by construction. `UNIQUE(api_key_id, kind)` on the table means
  a Stripe `invoice.paid` retry inserting the 4 rows again raises
  `IntegrityError` per row — we swallow that and leave existing rows intact.
  `run_due()` only touches rows whose `sent_at IS NULL`, so a rerun of the
  cron after a crash (even mid-loop) cannot double-send.
* Never raises on send failure. The send helpers in `onboarding.py` already
  return error dicts instead of raising; we inspect the response and update
  `sent_at` only when the response does not look like a failure.
* The D+14 skip rule (`usage_count > 0`) is enforced inside
  `send_day14_inactive_reminder` itself — the scheduler does NOT second-guess
  it. When the helper returns `{"skipped": True, "reason": "active"}` we
  STILL mark the row as `sent_at`, so the row stops being picked. Leaving
  it NULL would re-fire the same skip on every cron run forever.

Entry points
------------
* `python -m jpintel_mcp.email.scheduler`    — one-shot cron-friendly CLI.
* `scripts/send_scheduled_emails.py`         — identical behaviour, kept as a
  thin shim so existing ops runbooks keep working.

Time handling
-------------
All timestamps are ISO-8601 in UTC. Comparisons use string lexicographic
order (`send_at <= :now_iso`) which is safe with zero-padded ISO-8601. Tests
inject a frozen `now` so freezegun is not a dependency.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jpintel_mcp.db.session import connect
from jpintel_mcp.email.onboarding import (
    TEMPLATE_DAY1,
    TEMPLATE_DAY3,
    TEMPLATE_DAY7,
    TEMPLATE_DAY14,
    TEMPLATE_DAY30,
    send_day1_quick_win,
    send_day3_activation,
    send_day7_value,
    send_day14_inactive_reminder,
    send_day30_feedback,
)

if TYPE_CHECKING:
    from jpintel_mcp.email.postmark import PostmarkClient

logger = logging.getLogger("jpintel.email.scheduler")

# ---------------------------------------------------------------------------
# Kind ↔ Postmark alias ↔ send helper table
# ---------------------------------------------------------------------------

# Delay, in days, from `now` at which each kind fires. Kept here (not in
# config) because these are copy-calibrated: the D+3 copy literally says
# "はじめの3日" and moving it to D+5 would break the narrative. If a
# downstream deploy needs a different cadence, clone the module.
#
# D+0 is intentionally NOT in this map — see module docstring. D+1 is the
# first cron-fired mail; using `days=1` means the cron that runs within
# 24h of key issuance picks it up once the clock has crossed that offset.
_KIND_OFFSETS_DAYS: dict[str, int] = {
    "day1": 1,
    "day3": 3,
    "day7": 7,
    "day14": 14,
    "day30": 30,
}

_KIND_TEMPLATE_ALIAS: dict[str, str] = {
    "day1": TEMPLATE_DAY1,
    "day3": TEMPLATE_DAY3,
    "day7": TEMPLATE_DAY7,
    "day14": TEMPLATE_DAY14,
    "day30": TEMPLATE_DAY30,
}

SendFn = Callable[..., dict[str, Any]]

_KIND_SEND_FN: dict[str, SendFn] = {
    "day1": send_day1_quick_win,
    "day3": send_day3_activation,
    "day7": send_day7_value,
    "day14": send_day14_inactive_reminder,
    "day30": send_day30_feedback,
}

ALL_KINDS: tuple[str, ...] = ("day1", "day3", "day7", "day14", "day30")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    """ISO-8601 UTC, always with explicit offset so lex order == chronological."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue_onboarding_sequence(
    conn: sqlite3.Connection,
    *,
    api_key_id: str,
    email: str,
    now: datetime | None = None,
) -> list[str]:
    """Insert the schedule rows for a freshly-issued API key.

    One row per kind in `ALL_KINDS` (currently D+1 / D+3 / D+7 / D+14 /
    D+30). D+0 is NOT enqueued — it goes out synchronously from the
    billing webhook because the body carries the raw API key.

    Called from `issue_key()` at signup time. Idempotent: if rows already
    exist for `(api_key_id, kind)` the UNIQUE constraint fires and we skip
    that kind silently, returning only the `kind`s actually inserted.

    `api_key_id` is the row's PK in `api_keys` (which is `key_hash`).
    `email` is captured *at enqueue time* — rotating Stripe customer_email
    later does NOT re-route the remaining activation mails; the customer
    signed up with this address and the activation copy references their
    original key.
    """
    ts = now or _utcnow()
    created_at = _iso(ts)
    inserted: list[str] = []
    for kind in ALL_KINDS:
        send_at = _iso(ts + timedelta(days=_KIND_OFFSETS_DAYS[kind]))
        try:
            conn.execute(
                """INSERT INTO email_schedule
                       (api_key_id, email, kind, send_at, created_at)
                   VALUES (?,?,?,?,?)""",
                (api_key_id, email, kind, send_at, created_at),
            )
            inserted.append(kind)
        except sqlite3.IntegrityError:
            # Stripe replay → 4 rows already in place. Leave them.
            logger.debug(
                "email_schedule.duplicate api_key=%s kind=%s",
                api_key_id[:12] if api_key_id else "?",
                kind,
            )
    return inserted


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _default_usage_count(conn: sqlite3.Connection, api_key_id: str) -> int:
    """Live usage count for the customer's key. Used by D+3 / D+7 / D+14 copy.

    We count ANY `usage_events` row — not just 2xx — because the copy asks
    "まだお試しいただけていません" and a 401 on a bad curl still means
    the customer has actively started poking the API.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
        (api_key_id,),
    ).fetchone()
    if row is None:
        return 0
    # conn.row_factory may or may not be Row; handle tuple too.
    try:
        return int(row[0])
    except (TypeError, ValueError, IndexError):
        return 0


def _resolve_tier(conn: sqlite3.Connection, api_key_id: str) -> str:
    row = conn.execute(
        "SELECT tier FROM api_keys WHERE key_hash = ?",
        (api_key_id,),
    ).fetchone()
    if row is None:
        return "free"
    try:
        return row[0] or "free"
    except (TypeError, IndexError):
        return "free"


def _is_unsubscribed(conn: sqlite3.Connection, email: str) -> bool:
    """Honor BOTH suppression sources before dispatching an activation mail.

    P2.6.4 (2026-04-25): two paths can suppress an address now:

      1. `email_unsubscribes` (master list — migration 072) — populated by
         self-serve `POST /v1/email/unsubscribe` and the Postmark
         bounce/spam webhook. Authoritative across ALL marketing/activation
         streams (特電法 §3 opt-out master record).
      2. `subscribers.unsubscribed_at` (legacy newsletter list) — kept for
         backward compat with the older Postmark webhook flow that wrote
         here directly.

    Either flag set -> skip the send. We still mark the schedule row as
    `sent_at` when we skip (see `run_due()`) so the cron does not re-pick
    it forever.
    """
    # Master list — fastest path, indexed PK lookup.
    try:
        from jpintel_mcp.email.unsubscribe import is_unsubscribed as _master_check

        if _master_check(conn, email):
            return True
    except Exception:  # pragma: no cover — defensive against import order
        logger.debug("email.scheduler.master_check_failed", exc_info=True)

    row = conn.execute(
        "SELECT unsubscribed_at FROM subscribers WHERE email = ?",
        (email,),
    ).fetchone()
    if row is None:
        return False
    try:
        return row[0] is not None
    except (TypeError, IndexError):
        return False


def _looks_like_failure(resp: dict[str, Any]) -> bool:
    """True when the Postmark helper returned an error-shaped dict.

    Test-mode stubs return `{"skipped": True, "reason": "test_mode"}` — those
    are NOT failures. The D+14 active-skip returns `{"skipped": True,
    "reason": "active"}` which is also NOT a failure (it's an intended
    no-op; the row should still be marked sent so cron stops picking it).
    Real failures have an `"error"` key set by `postmark.PostmarkClient._send`.
    """
    return "error" in resp


def _derive_key_last4(api_key_id: str) -> str:
    """Last 4 chars of the KEY HASH — we never have the raw key at cron time.

    The live templates treat `key_last4` as a visual breadcrumb so the
    customer can tell WHICH key this email refers to when they have several.
    We substitute the tail of the hash string; stable per-key and not
    reversible back to the raw key. The D+0 welcome is the only place the
    raw-key tail gets emailed, and only that one time.
    """
    if not api_key_id:
        return "????"
    return api_key_id[-4:]


# ---------------------------------------------------------------------------
# run_due — the actual cron body
# ---------------------------------------------------------------------------


def run_due(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    client: PostmarkClient | None = None,
    usage_count_fn: Callable[[sqlite3.Connection, str], int] | None = None,
) -> dict[str, Any]:
    """Dispatch every row whose `send_at <= now AND sent_at IS NULL`.

    Returns a small dict summary keyed by kind: counts of
    `{"sent", "skipped", "failed", "suppressed"}` for logging / tests.

    The function is deliberately single-threaded and per-row — the expected
    daily batch size is in the tens, not thousands. If that changes, the
    SELECT + UPDATE loop is trivially parallelisable; Postmark's server-token
    already handles concurrent sends.
    """
    ts = now or _utcnow()
    now_iso = _iso(ts)
    usage_fn = usage_count_fn or _default_usage_count

    rows = conn.execute(
        """SELECT id, api_key_id, email, kind, send_at, attempts
             FROM email_schedule
            WHERE sent_at IS NULL AND send_at <= ?
            ORDER BY send_at ASC, id ASC""",
        (now_iso,),
    ).fetchall()

    summary: dict[str, Any] = {
        "picked": len(rows),
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "suppressed": 0,
        "by_kind": {k: {"sent": 0, "skipped": 0, "failed": 0, "suppressed": 0} for k in ALL_KINDS},
    }

    for row in rows:
        # Compatibility with both Row and plain-tuple cursors.
        try:
            row_id = row["id"]
            api_key_id = row["api_key_id"]
            email = row["email"]
            kind = row["kind"]
        except (TypeError, IndexError, KeyError):
            row_id, api_key_id, email, kind = row[0], row[1], row[2], row[3]

        send_fn = _KIND_SEND_FN.get(kind)
        if send_fn is None:
            # Unknown kind — mark as skipped so it stops being picked but
            # record the error for operator triage.
            logger.warning("email_schedule.unknown_kind id=%d kind=%s", row_id, kind)
            conn.execute(
                """UPDATE email_schedule
                      SET sent_at = ?,
                          attempts = COALESCE(attempts, 0) + 1,
                          last_error = ?
                    WHERE id = ?""",
                (now_iso, f"unknown kind {kind!r}", row_id),
            )
            summary["skipped"] += 1
            continue

        # Honor unsubscribes / hard bounces / spam complaints — mark sent so
        # the row stops being picked, bump attempts so the audit trail shows
        # the dispatcher saw the row.
        if _is_unsubscribed(conn, email):
            conn.execute(
                """UPDATE email_schedule
                      SET sent_at = ?,
                          attempts = COALESCE(attempts, 0) + 1,
                          last_error = ?
                    WHERE id = ?""",
                (now_iso, "suppressed (unsubscribed)", row_id),
            )
            summary["suppressed"] += 1
            summary["by_kind"][kind]["suppressed"] += 1
            logger.info("email_schedule.suppressed id=%d kind=%s", row_id, kind)
            continue

        tier = _resolve_tier(conn, api_key_id)
        try:
            usage_count = int(usage_fn(conn, api_key_id))
        except Exception:  # pragma: no cover — defensive
            logger.warning("email_schedule.usage_lookup_failed id=%d", row_id, exc_info=True)
            usage_count = 0

        key_last4 = _derive_key_last4(api_key_id)

        try:
            resp = send_fn(
                to=email,
                api_key_last4=key_last4,
                tier=tier,
                usage_count=usage_count,
                client=client,
            )
        except Exception as exc:  # pragma: no cover — the helpers promise not to raise
            logger.warning(
                "email_schedule.send_raised id=%d kind=%s err=%s",
                row_id,
                kind,
                exc,
            )
            conn.execute(
                """UPDATE email_schedule
                      SET attempts = COALESCE(attempts, 0) + 1,
                          last_error = ?
                    WHERE id = ?""",
                (str(exc)[:500], row_id),
            )
            summary["failed"] += 1
            summary["by_kind"][kind]["failed"] += 1
            continue

        if _looks_like_failure(resp):
            err = json.dumps(resp, ensure_ascii=False)[:500]
            conn.execute(
                """UPDATE email_schedule
                      SET attempts = COALESCE(attempts, 0) + 1,
                          last_error = ?
                    WHERE id = ?""",
                (err, row_id),
            )
            summary["failed"] += 1
            summary["by_kind"][kind]["failed"] += 1
            logger.warning(
                "email_schedule.send_failed id=%d kind=%s resp=%s",
                row_id,
                kind,
                err,
            )
            continue

        # Success path: mark sent. Clear last_error so a prior transient
        # failure does not linger in the row forever.
        conn.execute(
            """UPDATE email_schedule
                  SET sent_at = ?,
                      attempts = COALESCE(attempts, 0) + 1,
                      last_error = NULL
                WHERE id = ?""",
            (now_iso, row_id),
        )

        if resp.get("skipped") and resp.get("reason") == "active":
            # D+14 intentional skip (usage_count > 0). Count separately so
            # observability sees the rule firing.
            summary["skipped"] += 1
            summary["by_kind"][kind]["skipped"] += 1
            logger.info("email_schedule.skipped_active id=%d kind=%s", row_id, kind)
        elif resp.get("skipped"):
            # Test-mode no-op — for cron summary purposes, count as sent so
            # ops dashboards do not panic during dry-runs.
            summary["sent"] += 1
            summary["by_kind"][kind]["sent"] += 1
        else:
            summary["sent"] += 1
            summary["by_kind"][kind]["sent"] += 1

    return summary


# ---------------------------------------------------------------------------
# CLI entry: python -m jpintel_mcp.email.scheduler
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m jpintel_mcp.email.scheduler",
        description="Dispatch due onboarding emails from email_schedule.",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to SQLite DB (default: JPINTEL_DB_PATH or ./data/jpintel.db).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report due rows but do not call Postmark or mutate rows.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    args = _build_cli_parser().parse_args(argv)

    conn = connect(args.db)
    try:
        if args.dry_run:
            ts = _utcnow()
            rows = conn.execute(
                """SELECT id, api_key_id, email, kind, send_at
                     FROM email_schedule
                    WHERE sent_at IS NULL AND send_at <= ?
                    ORDER BY send_at ASC, id ASC""",
                (_iso(ts),),
            ).fetchall()
            logger.info("dry_run due_rows=%d now=%s", len(rows), _iso(ts))
            for r in rows:
                logger.info(
                    "due id=%s kind=%s email=%s send_at=%s",
                    r[0],
                    r[3],
                    r[2],
                    r[4],
                )
            return 0

        summary = run_due(conn)
        logger.info("run_due_summary %s", json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ALL_KINDS",
    "enqueue_onboarding_sequence",
    "run_due",
    "main",
]
