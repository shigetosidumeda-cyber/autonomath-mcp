"""Daily predictive watch ETL for Dim T (Wave 47).

Materialises the daily predictive notification queue on top of the
storage layer added by ``scripts/migrations/280_predictive_service.sql``.

Three watch types are evaluated in a single pass (per
``feedback_predictive_service_design.md``):

  * ``houjin``    -> scan ``am_amendment_diff`` rows whose ``entity_id``
                     matches a watched 法人番号.
  * ``program``   -> scan ``am_amendment_diff`` rows whose
                     ``entity_id`` resolves to a watched
                     ``programs.unified_id`` AND the program_window
                     deadline gate is still open (i.e. the predictive
                     fire is actionable, not retrospective).
  * ``amendment`` -> scan ``am_amendment_diff`` rows whose source
                     references a watched ``laws.law_id``.

For every ``(watch_id, source_diff_id)`` pair NOT already in
``am_predictive_alert_log`` (dedup'd by ``uq_am_predictive_alert_dedup``),
we INSERT one alert row with ``delivery_status='pending'`` and a JSON
payload. A side pass flips stale ``'pending'`` rows older than the
watch's ``notify_window_hours`` to ``'expired'`` — this is the 24h
TTL purge.

LLM-0 discipline (per ``feedback_no_operator_llm_api.md`` /
``feedback_predictive_service_design.md``): no Anthropic / OpenAI SDK
imported anywhere here. The payload is purely structural metadata
(diff_id, watch_target, fired_at) — no natural-language summary.

¥3/req billing posture: this ETL only enqueues. The dispatcher
(``scripts/cron/dispatch_predictive_alerts.py``, Dim T runtime layer)
posts to subscriber webhooks; ONLY rows that flip to
``delivery_status='delivered'`` ever emit a Stripe usage_record.

Usage
-----
    python scripts/etl/build_predictive_watch_v2.py                    # apply
    python scripts/etl/build_predictive_watch_v2.py --dry-run          # plan
    python scripts/etl/build_predictive_watch_v2.py --db PATH          # custom db
    python scripts/etl/build_predictive_watch_v2.py --since-hours 48   # backfill window

JSON output (final stdout line)::

    {
      "dim": "T",
      "wave": 47,
      "dry_run": <bool>,
      "queued": <int>,            # new 'pending' rows inserted
      "expired": <int>,           # 'pending' rows flipped to 'expired' by TTL purge
      "by_type": {                # queued count per watch_type
        "houjin": <int>,
        "program": <int>,
        "amendment": <int>
      }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("build_predictive_watch_v2")

_WATCH_TYPES: tuple[str, ...] = ("houjin", "program", "amendment")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dim T predictive watch ETL (daily)")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help="Only scan am_amendment_diff rows whose detected_at is within this window.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _purge_stale_pending(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Flip 'pending' rows older than the watch's notify_window_hours to 'expired'.

    Implements the 24h (configurable) TTL purge required by
    ``feedback_predictive_service_design``. A row is considered stale
    when ``fired_at + notify_window_hours < now``. We use SQLite's
    ``datetime(..., '+N hours')`` to compute the deadline server-side.
    """
    rows = conn.execute(
        """
        SELECT a.alert_id, a.fired_at, s.notify_window_hours
          FROM am_predictive_alert_log a
          JOIN am_predictive_watch_subscription s ON s.watch_id = a.watch_id
         WHERE a.delivery_status = 'pending'
           AND datetime(a.fired_at, '+' || s.notify_window_hours || ' hours') < datetime('now')
        """
    ).fetchall()
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    conn.executemany(
        "UPDATE am_predictive_alert_log SET delivery_status='expired' WHERE alert_id=?",
        [(r[0],) for r in rows],
    )
    return len(rows)


def _scan_one_type(
    conn: sqlite3.Connection,
    *,
    watch_type: str,
    since_hours: int,
) -> list[tuple[int, int, str, str]]:
    """Return candidate (watch_id, diff_id, watch_target, detected_at) tuples.

    The matching predicate depends on watch_type:
      * houjin    -> am_amendment_diff.entity_id = watch_target
      * program   -> am_amendment_diff.entity_id = watch_target (program unified_id is opaque here)
      * amendment -> am_amendment_diff.entity_id LIKE watch_target || '%'
    """
    # All 3 types compare entity_id; the ``LIKE`` variant for amendment
    # lets a single law_id watch match any sub-article diff under it.
    # If am_amendment_diff doesn't exist on this DB, return empty.
    if not _has_table(conn, "am_amendment_diff") or not _has_table(
        conn, "am_predictive_watch_subscription"
    ):
        return []

    if watch_type == "amendment":
        match_predicate = "d.entity_id LIKE w.watch_target || '%'"
    else:
        match_predicate = "d.entity_id = w.watch_target"

    sql = f"""
        SELECT w.watch_id, d.diff_id, w.watch_target, d.detected_at
          FROM v_predictive_watch_active w
          JOIN am_amendment_diff d
            ON {match_predicate}
         WHERE w.watch_type = ?
           AND datetime(d.detected_at) >= datetime('now', '-' || ? || ' hours')
           AND NOT EXISTS (
                 SELECT 1 FROM am_predictive_alert_log a
                  WHERE a.watch_id = w.watch_id
                    AND a.source_diff_id = d.diff_id
               )
        """
    return conn.execute(sql, (watch_type, since_hours)).fetchall()


def _queue_alerts(
    conn: sqlite3.Connection,
    *,
    rows: list[tuple[int, int, str, str]],
    watch_type: str,
    dry_run: bool,
) -> int:
    if not rows:
        return 0
    payloads = []
    for watch_id, diff_id, watch_target, detected_at in rows:
        payload = json.dumps(
            {
                "watch_type": watch_type,
                "watch_target": watch_target,
                "source_diff_id": diff_id,
                "detected_at": detected_at,
            },
            ensure_ascii=False,
        )
        payloads.append((watch_id, diff_id, payload))
    if dry_run:
        return len(payloads)
    conn.executemany(
        """
        INSERT INTO am_predictive_alert_log (watch_id, source_diff_id, payload, delivery_status)
        VALUES (?, ?, ?, 'pending')
        ON CONFLICT(watch_id, source_diff_id) WHERE source_diff_id IS NOT NULL DO NOTHING
        """,
        payloads,
    )
    # Stamp last_fired_at on the corresponding subscription rows.
    watch_ids = {r[0] for r in rows}
    conn.executemany(
        "UPDATE am_predictive_watch_subscription "
        "SET last_fired_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
        "    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE watch_id = ?",
        [(wid,) for wid in watch_ids],
    )
    return len(payloads)


def build(
    *,
    db_path: Path,
    dry_run: bool,
    since_hours: int,
) -> dict:
    conn = _connect(db_path)
    try:
        by_type: dict[str, int] = {}
        total_queued = 0
        for wt in _WATCH_TYPES:
            rows = _scan_one_type(conn, watch_type=wt, since_hours=since_hours)
            n = _queue_alerts(conn, rows=rows, watch_type=wt, dry_run=dry_run)
            by_type[wt] = n
            total_queued += n
        expired = _purge_stale_pending(conn, dry_run=dry_run)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return {
        "dim": "T",
        "wave": 47,
        "dry_run": dry_run,
        "queued": total_queued,
        "expired": expired,
        "by_type": by_type,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db_path = Path(args.db)
    if not db_path.exists():
        if args.dry_run:
            # Wave 49 G3 cron hydrate fix: a dry-run plan must succeed even
            # when the operator DB has not been hydrated yet (CI runner,
            # Fly cold start, etc.). The script is read-only in this mode,
            # so emit a placeholder report and exit 0.
            LOG.warning("DB not found (dry-run): %s", db_path)
            print(
                json.dumps(
                    {
                        "dim": "T",
                        "wave": 47,
                        "dry_run": True,
                        "db_not_found_dry_run": True,
                        "db": str(db_path),
                        "queued": 0,
                        "expired": 0,
                        "by_type": {wt: 0 for wt in _WATCH_TYPES},
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        LOG.error("DB not found: %s", db_path)
        print(
            json.dumps(
                {"dim": "T", "wave": 47, "error": "db_not_found", "db": str(db_path)},
                ensure_ascii=False,
            )
        )
        return 2
    report = build(
        db_path=db_path,
        dry_run=args.dry_run,
        since_hours=args.since_hours,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
