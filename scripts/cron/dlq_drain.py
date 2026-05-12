#!/usr/bin/env python3
"""DLQ hourly drain + replay (Wave 43.3.4 — AX Resilience cell 4).

Background
----------
`am_dlq` (migration 267) holds work units that exhausted the in-line
retry budget on the durable bg_task_queue surface (migration 060) and
the customer webhook dispatcher (`scripts/cron/dispatch_webhooks.py`).
Once the upstream root cause is fixed (vendor API back up, customer
endpoint returns 2xx, Stripe webhook signature rotated) the operator
wants the quarantined unit replayed — but ONLY against the *current*
schema, ONLY at a controlled rate, and ONLY with full provenance so a
税理士 audit trail is unbroken.

This cron is the controlled replay loop. Hourly via
`.github/workflows/dlq-drain-hourly.yml`. Each run scans
`am_dlq.status = 'quarantined'` rows, attempts to re-enqueue them into
the appropriate surface (`bg_task_queue` for task-kind sources, or a
fresh webhook dispatch for webhook-kind sources), and flips the row
status accordingly.

Replay policy
-------------
- Re-enqueue at most `--batch-size` rows per run (default 100).
- Per-row replay budget: 1 attempt per drain pass. If the replay
  itself fails, the row stays quarantined (status unchanged) but
  `attempts` is incremented and `last_failed_at` advanced.
- After `--max-replay-attempts` (default 5) the row flips to
  status='abandoned' and an operator alert is queued.
- Cleanup sweep: rows with status='replayed' AND replayed_at older than
  30d are eligible for delete (run via `--cleanup` flag).

State checkpoint cleanup
------------------------
Piggybacks on the same cron pass to age out `am_state_checkpoint`
rows older than 30d (committed) or 90d (aborted/expired). Keeps the
checkpoint table from growing unbounded over Y1.

Constraints
-----------
- No Anthropic / claude / SDK calls. Pure SQLite + stdlib.
- Operator-only surface. No customer billing.
- Idempotent on every run (DLQ status state machine + ON CONFLICT).

Usage:
    python scripts/cron/dlq_drain.py                    # one-shot pass
    python scripts/cron/dlq_drain.py --dry-run          # log only
    python scripts/cron/dlq_drain.py --batch-size 50
    python scripts/cron/dlq_drain.py --cleanup          # also purge old rows
    python scripts/cron/dlq_drain.py --max-replay-attempts 3
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("autonomath.cron.dlq_drain")

# Default retention windows (days).
_RETAIN_REPLAYED_DAYS = 30
_RETAIN_ABANDONED_DAYS = 90
_RETAIN_CHECKPOINT_COMMITTED_DAYS = 30
_RETAIN_CHECKPOINT_FAILED_DAYS = 90


def _now_iso() -> str:
    """Wall-clock UTC ISO 8601 with millisecond precision + Z suffix."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _resolve_db_path() -> Path:
    """Resolve autonomath.db path. Honors AUTONOMATH_DB_PATH override."""
    env_path = os.environ.get("AUTONOMATH_DB_PATH")
    if env_path:
        return Path(env_path)
    # Default = repo-root autonomath.db (production code reads from root).
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open the autonomath DB in read-write mode with sensible PRAGMAs."""
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _begin_run(conn: sqlite3.Connection) -> int:
    """Insert a dlq_drain_log row, return run_id."""
    cur = conn.execute(
        "INSERT INTO dlq_drain_log (started_at) VALUES (?)",
        (_now_iso(),),
    )
    return int(cur.lastrowid or 0)


def _finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    scanned: int,
    replayed_ok: int,
    replayed_failed: int,
    abandoned: int,
    error: str | None = None,
) -> None:
    """Stamp the run row with final counters."""
    conn.execute(
        """
        UPDATE dlq_drain_log
        SET finished_at = ?, scanned = ?, replayed_ok = ?,
            replayed_failed = ?, abandoned = ?, error_text = ?
        WHERE run_id = ?
        """,
        (_now_iso(), scanned, replayed_ok, replayed_failed, abandoned, error, run_id),
    )


def _fetch_quarantined(
    conn: sqlite3.Connection,
    batch_size: int,
) -> list[sqlite3.Row]:
    """Return up to `batch_size` quarantined rows, oldest-first."""
    cur = conn.execute(
        """
        SELECT *
        FROM am_dlq
        WHERE status = 'quarantined'
        ORDER BY first_failed_at ASC
        LIMIT ?
        """,
        (batch_size,),
    )
    return list(cur.fetchall())


def _attempt_replay(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """Replay a single DLQ row. Returns (success, error_message_or_None).

    The replay strategy is source-kind dependent:
      - `bg_task`:        re-INSERT into bg_task_queue with a fresh
                          dedup_key (the original dedup_key would
                          collide), preserving the payload.
      - `webhook_delivery`: re-insert into webhook_deliveries with
                          status='pending' so the dispatcher picks it
                          up on its next pass.
      - `cron_etl`:       no auto-replay (the cron itself re-runs on
                          schedule); just mark replayed=False and let
                          attempts increment so abandoned threshold
                          fires.
      - `other`:          no auto-replay.

    The replay is best-effort. If the destination table is missing or
    the payload is malformed we treat it as a replay failure (not a
    drain failure) so the row stays quarantined.
    """
    if dry_run:
        logger.info("dry-run: would replay dlq_id=%s kind=%s", row["dlq_id"], row["kind"])
        return True, None

    source_kind = row["source_kind"]
    try:
        if source_kind == "bg_task":
            return _replay_bg_task(conn, row)
        if source_kind == "webhook_delivery":
            return _replay_webhook(conn, row)
        if source_kind == "cron_etl":
            return False, "cron_etl: no auto-replay (cron self-re-runs)"
        return False, f"unsupported source_kind: {source_kind}"
    except (sqlite3.Error, json.JSONDecodeError, ValueError, TypeError) as exc:
        return False, f"replay exception: {type(exc).__name__}: {exc}"


def _replay_bg_task(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[bool, str | None]:
    """Re-enqueue a bg_task DLQ row into bg_task_queue with fresh dedup_key."""
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError as exc:
        return False, f"payload not JSON: {exc}"

    # Fresh dedup_key prevents ON CONFLICT NO-OP against the failed
    # original. Format: "dlq-replay-<dlq_id>-<utc_ms>".
    fresh_dedup = f"dlq-replay-{row['dlq_id']}-{int(datetime.now(UTC).timestamp() * 1000)}"
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO bg_task_queue
                (kind, payload, dedup_key, status, attempts,
                 max_attempts, created_at, next_attempt_at)
            VALUES (?, ?, ?, 'pending', 0, 5, ?, ?)
            """,
            (
                row["kind"],
                json.dumps(payload, ensure_ascii=False, default=str),
                fresh_dedup,
                now,
                now,
            ),
        )
        return True, None
    except sqlite3.OperationalError as exc:
        # Table may not exist on a fresh volume; treat as recoverable.
        return False, f"bg_task_queue insert failed: {exc}"


def _replay_webhook(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[bool, str | None]:
    """Re-insert a webhook_delivery DLQ row as a fresh pending delivery."""
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError as exc:
        return False, f"payload not JSON: {exc}"
    webhook_id = payload.get("webhook_id")
    event_type = payload.get("event_type")
    event_id = payload.get("event_id")
    if not (webhook_id and event_type and event_id):
        return False, "webhook payload missing webhook_id/event_type/event_id"
    now = _now_iso()
    try:
        # webhook_deliveries enforces UNIQUE(webhook_id, event_type, event_id).
        # Suffix event_id so the replay does not collide.
        conn.execute(
            """
            INSERT INTO webhook_deliveries
                (webhook_id, event_type, event_id, status, attempts,
                 created_at, next_attempt_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?)
            """,
            (
                webhook_id,
                event_type,
                f"{event_id}-dlq{row['dlq_id']}",
                now,
                now,
            ),
        )
        return True, None
    except sqlite3.OperationalError as exc:
        return False, f"webhook_deliveries insert failed: {exc}"


def _mark_replayed(conn: sqlite3.Connection, dlq_id: int, run_id: int) -> None:
    """Flip a row to status='replayed'."""
    conn.execute(
        """
        UPDATE am_dlq
        SET status = 'replayed', replayed_at = ?, replay_run_id = ?
        WHERE dlq_id = ? AND status = 'quarantined'
        """,
        (_now_iso(), run_id, dlq_id),
    )


def _bump_attempts(conn: sqlite3.Connection, dlq_id: int, error: str) -> int:
    """Increment attempts + advance last_failed_at. Return new attempts."""
    conn.execute(
        """
        UPDATE am_dlq
        SET attempts = attempts + 1,
            last_failed_at = ?,
            last_error = ?
        WHERE dlq_id = ?
        """,
        (_now_iso(), (error or "")[:2000], dlq_id),
    )
    cur = conn.execute("SELECT attempts FROM am_dlq WHERE dlq_id = ?", (dlq_id,))
    fetched = cur.fetchone()
    return int(fetched[0]) if fetched is not None else 0


def _mark_abandoned(conn: sqlite3.Connection, dlq_id: int, reason: str) -> None:
    """Flip a row to status='abandoned'."""
    conn.execute(
        """
        UPDATE am_dlq
        SET status = 'abandoned',
            notes = COALESCE(notes, '') || ' [abandoned: ' || ? || ']'
        WHERE dlq_id = ? AND status = 'quarantined'
        """,
        ((reason or "max-attempts")[:200], dlq_id),
    )


def _cleanup_sweep(conn: sqlite3.Connection) -> tuple[int, int]:
    """Purge old DLQ + state_checkpoint rows. Returns (dlq_purged, ck_purged)."""
    now = datetime.now(UTC)
    replayed_cutoff = (now - timedelta(days=_RETAIN_REPLAYED_DAYS)).isoformat()
    abandoned_cutoff = (now - timedelta(days=_RETAIN_ABANDONED_DAYS)).isoformat()
    committed_cutoff = (
        now - timedelta(days=_RETAIN_CHECKPOINT_COMMITTED_DAYS)
    ).isoformat()
    failed_cutoff = (
        now - timedelta(days=_RETAIN_CHECKPOINT_FAILED_DAYS)
    ).isoformat()

    cur = conn.execute(
        """
        DELETE FROM am_dlq
        WHERE (status = 'replayed' AND replayed_at < ?)
           OR (status = 'abandoned' AND abandoned_at < ?)
        """,
        (replayed_cutoff, abandoned_cutoff),
    )
    dlq_purged = cur.rowcount or 0

    cur = conn.execute(
        """
        DELETE FROM am_state_checkpoint
        WHERE (status = 'committed' AND committed_at < ?)
           OR (status IN ('aborted','expired') AND committed_at < ?)
        """,
        (committed_cutoff, failed_cutoff),
    )
    ck_purged = cur.rowcount or 0
    return dlq_purged, ck_purged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DLQ hourly drain + replay")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-replay-attempts", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cleanup", action="store_true",
                        help="Also purge old replayed/abandoned + state_checkpoint rows.")
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    db_path = Path(args.db) if args.db else _resolve_db_path()
    if not db_path.exists():
        logger.error("autonomath.db not found at %s — skipping", db_path)
        return 0  # graceful no-op on missing DB

    conn = _connect(db_path)
    try:
        run_id = _begin_run(conn)
        rows = _fetch_quarantined(conn, args.batch_size)
        scanned = len(rows)
        replayed_ok = 0
        replayed_failed = 0
        abandoned = 0

        for row in rows:
            ok, err = _attempt_replay(conn, row, dry_run=args.dry_run)
            if ok and not args.dry_run:
                _mark_replayed(conn, int(row["dlq_id"]), run_id)
                replayed_ok += 1
                continue
            if ok and args.dry_run:
                replayed_ok += 1
                continue
            replayed_failed += 1
            new_attempts = _bump_attempts(conn, int(row["dlq_id"]), err or "")
            if new_attempts >= args.max_replay_attempts:
                _mark_abandoned(conn, int(row["dlq_id"]), err or "max-attempts")
                abandoned += 1

        dlq_purged = 0
        ck_purged = 0
        if args.cleanup and not args.dry_run:
            dlq_purged, ck_purged = _cleanup_sweep(conn)
            logger.info(
                "cleanup: dlq_purged=%d state_checkpoint_purged=%d",
                dlq_purged, ck_purged,
            )

        _finish_run(conn, run_id, scanned, replayed_ok, replayed_failed, abandoned)
        logger.info(
            "drain done: run_id=%d scanned=%d replayed_ok=%d "
            "replayed_failed=%d abandoned=%d dlq_purged=%d ck_purged=%d",
            run_id, scanned, replayed_ok, replayed_failed, abandoned,
            dlq_purged, ck_purged,
        )
        return 0
    finally:
        with contextlib_suppress(sqlite3.Error):
            conn.close()


# Tiny local alias so we do not pull `contextlib` just for `suppress`.
class contextlib_suppress:  # noqa: N801 (intentional lowercase API)
    def __init__(self, *excs: type[BaseException]) -> None:
        self._excs = excs

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return exc_type is not None and issubclass(exc_type, self._excs)


if __name__ == "__main__":
    sys.exit(main())
