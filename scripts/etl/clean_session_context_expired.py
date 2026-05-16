"""Daily TTL purge for the Dim L session-context audit layer (Wave 47).

Backs up the in-process LRU primitive at ``src/jpintel_mcp/api/session_context.py``
with a server-side cleanup pass over the optional persistence tables added by
``scripts/migrations/272_session_context.sql``.

Scope
-----
1. Mark every ``am_session_context`` row whose ``expires_at`` is in the past
   (TTL = 24h, per ``feedback_session_context_design``) as ``status='expired'``.
2. Delete ``am_session_context`` rows whose ``status`` is ``expired`` or
   ``closed`` and were created more than 7 days ago.
3. Delete every ``am_session_step_log`` row whose ``session_id`` no longer
   exists in ``am_session_context`` (orphan rows after step #2) OR whose
   ``created_at`` is older than 7 days.

The REST surface ``/v1/session/{open,step,close}`` is NOT touched — those
handlers continue to rely on the in-process LRU primitive. This script is a
detached audit/cleanup pass meant for the operator-side daemon only.

No LLM API import — Dim L cleanup is pure SQL + Python stdlib (per
``feedback_no_operator_llm_api``).

Usage
-----
    python scripts/etl/clean_session_context_expired.py             # apply
    python scripts/etl/clean_session_context_expired.py --dry-run   # plan only
    python scripts/etl/clean_session_context_expired.py --db PATH   # custom db

JSON output (final line, stdout)
--------------------------------
    {
      "dim": "L",
      "wave": 47,
      "dry_run": <bool>,
      "purge_stats": {
        "expired_marked":    <int>,   # status='open' -> 'expired'
        "context_deleted":   <int>,
        "step_log_orphan_deleted": <int>,
        "step_log_aged_deleted":   <int>,
        "alive_remaining":   <int>
      }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("clean_session_context_expired")

# Hard window: keep closed/expired rows for 7 days for forensics. Then drop.
_RETENTION_SECONDS = 7 * 24 * 60 * 60


def _now_epoch() -> int:
    return int(time.time())


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Best-effort guard: don't blow up if migration 272 not yet applied."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name IN "
        "('am_session_context', 'am_session_step_log')"
    ).fetchall()
    found = {r[0] for r in rows}
    missing = {"am_session_context", "am_session_step_log"} - found
    if missing:
        raise RuntimeError(
            f"migration 272_session_context not applied: missing tables {sorted(missing)}"
        )


def _mark_expired(conn: sqlite3.Connection, *, now: int, dry_run: bool) -> int:
    """Flip status='open' rows past their TTL to status='expired'."""
    sql_count = "SELECT COUNT(*) FROM am_session_context WHERE status = 'open' AND expires_at < ?"
    n = conn.execute(sql_count, (now,)).fetchone()[0]
    if dry_run or n == 0:
        return int(n)
    conn.execute(
        "UPDATE am_session_context SET status = 'expired' WHERE status = 'open' AND expires_at < ?",
        (now,),
    )
    return int(n)


def _delete_aged_context(conn: sqlite3.Connection, *, now: int, dry_run: bool) -> int:
    """Drop expired/closed rows older than the 7-day forensic window."""
    cutoff = now - _RETENTION_SECONDS
    # `expires_at` is epoch; `closed_at` is epoch; pick the maximum of the two
    # boundary timestamps as the "row age" (creation+TTL elapsed window).
    sql_count = (
        "SELECT COUNT(*) FROM am_session_context "
        "WHERE status IN ('expired', 'closed') "
        "AND COALESCE(closed_at, expires_at) < ?"
    )
    n = conn.execute(sql_count, (cutoff,)).fetchone()[0]
    if dry_run or n == 0:
        return int(n)
    conn.execute(
        "DELETE FROM am_session_context "
        "WHERE status IN ('expired', 'closed') "
        "AND COALESCE(closed_at, expires_at) < ?",
        (cutoff,),
    )
    return int(n)


def _delete_orphan_step_log(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Drop step-log rows whose parent session_id no longer exists."""
    sql_count = (
        "SELECT COUNT(*) FROM am_session_step_log s "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM am_session_context c WHERE c.session_id = s.session_id"
        ")"
    )
    n = conn.execute(sql_count).fetchone()[0]
    if dry_run or n == 0:
        return int(n)
    conn.execute(
        "DELETE FROM am_session_step_log "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM am_session_context c "
        "  WHERE c.session_id = am_session_step_log.session_id"
        ")"
    )
    return int(n)


def _delete_aged_step_log(conn: sqlite3.Connection, *, now: int, dry_run: bool) -> int:
    """Drop step-log rows older than the 7-day forensic window."""
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%fZ", time.gmtime(now - _RETENTION_SECONDS))
    sql_count = "SELECT COUNT(*) FROM am_session_step_log WHERE created_at < ?"
    n = conn.execute(sql_count, (cutoff_iso,)).fetchone()[0]
    if dry_run or n == 0:
        return int(n)
    conn.execute(
        "DELETE FROM am_session_step_log WHERE created_at < ?",
        (cutoff_iso,),
    )
    return int(n)


def _alive_remaining(conn: sqlite3.Connection, *, now: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM am_session_context WHERE status = 'open' AND expires_at >= ?",
            (now,),
        ).fetchone()[0]
    )


def run(db_path: Path, *, dry_run: bool) -> dict:
    """Apply the 4-step purge against ``db_path``. Returns the stats dict."""
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_tables(conn)
        now = _now_epoch()
        expired_marked = _mark_expired(conn, now=now, dry_run=dry_run)
        context_deleted = _delete_aged_context(conn, now=now, dry_run=dry_run)
        orphan_deleted = _delete_orphan_step_log(conn, dry_run=dry_run)
        aged_step_deleted = _delete_aged_step_log(conn, now=now, dry_run=dry_run)
        if not dry_run:
            conn.commit()
        alive = _alive_remaining(conn, now=now)
    finally:
        conn.close()
    return {
        "dim": "L",
        "wave": 47,
        "dry_run": bool(dry_run),
        "purge_stats": {
            "expired_marked": int(expired_marked),
            "context_deleted": int(context_deleted),
            "step_log_orphan_deleted": int(orphan_deleted),
            "step_log_aged_deleted": int(aged_step_deleted),
            "alive_remaining": int(alive),
        },
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="clean_session_context_expired",
        description="Dim L (session_context) 24h TTL purge + 7d forensic window.",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB path (default: {DEFAULT_DB_PATH}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without modifying the DB.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.db.exists():
        if args.dry_run:
            # Wave 49 G3 cron hydrate fix: a dry-run plan must succeed even
            # when the operator DB has not been hydrated yet. The script is
            # read-only in this mode, so emit a placeholder payload and exit 0.
            LOG.warning("DB not found (dry-run): %s", args.db)
            print(
                json.dumps(
                    {
                        "dim": "L",
                        "wave": 47,
                        "dry_run": True,
                        "db_not_found_dry_run": True,
                        "db": str(args.db),
                        "purge_stats": {
                            "expired_marked": 0,
                            "context_deleted": 0,
                            "step_log_orphan_deleted": 0,
                            "step_log_aged_deleted": 0,
                            "alive_remaining": 0,
                        },
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        LOG.error("DB not found: %s", args.db)
        return 2
    payload = run(args.db, dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
