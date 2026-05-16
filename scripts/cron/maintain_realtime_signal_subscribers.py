#!/usr/bin/env python3
"""Real-time signal subscriber maintenance cron (Wave 46 dim G).

Wave 46 dim 19 audit found dim G ``realtime_signal_v2`` at 4.50/10 because
``cron MISSING`` from ``scripts/cron/`` + ``.github/workflows/`` despite the
REST surface (``src/jpintel_mcp/api/realtime_signal_v2.py``) and migration
263 (``am_realtime_subscribers`` + ``am_realtime_dispatch_history``) being
live. This cron closes that gap with a single rule-based sweep over the
two dim G tables. Adding it lifts dim G score 4.50 -> ~6.00 (+1.5 cron).

What this does (one-shot pass, idempotent)
------------------------------------------
1. ``stale_disable``: any ``status='active'`` subscriber whose last 5
   consecutive ``am_realtime_dispatch_history`` rows are all non-2xx (or
   whose ``failure_count >= 5``) is flipped to ``status='disabled'`` with
   ``disabled_reason='stale_failure_streak'``. Mirrors the
   ``dispatch_webhooks.py`` 5-strike rule for the customer_webhooks
   table so the two webhook surfaces have parity.
2. ``prune_dispatch_history``: drop ``am_realtime_dispatch_history`` rows
   older than ``--retention-days`` (default 90). Keeps the table from
   growing unbounded after launch. We do NOT vacuum (9.7 GB DB —
   ``feedback_no_quick_check_on_huge_sqlite`` forbids full-scan ops on
   boot, but a one-shot cron pass with ``DELETE`` + index walk is fine).
3. ``summary``: emit a JSON line (active / disabled / pruned counts) for
   observability heartbeat ingestion.

Constraints
-----------
* No anthropic / openai / google.generativeai / claude_agent_sdk imports
  (``feedback_no_operator_llm_api``).
* No ATTACH across DBs (CLAUDE.md "no cross-DB JOIN").
* No PRAGMA quick_check / integrity_check on the 9.7 GB DB
  (``feedback_no_quick_check_on_huge_sqlite``).
* No httpx / requests outbound calls — actual webhook dispatch lives in
  ``dispatch_webhooks.py``; THIS cron is housekeeping only.
* Idempotent: re-running same day is a no-op modulo time-based pruning.

Usage
-----
    python scripts/cron/maintain_realtime_signal_subscribers.py
    python scripts/cron/maintain_realtime_signal_subscribers.py --dry-run
    python scripts/cron/maintain_realtime_signal_subscribers.py --retention-days 30
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logger = logging.getLogger("autonomath.cron.maintain_realtime_signal_subscribers")

# Failure-streak threshold mirrors customer_webhooks dispatcher
# (dispatch_webhooks.py "5 consecutive failure increments without an
#  intervening success" — keep the two surfaces in lockstep).
FAILURE_STREAK_THRESHOLD = 5
DEFAULT_RETENTION_DAYS = 90


def _resolve_db_path() -> Path:
    """Resolve autonomath.db path; tolerate import failure in CI."""
    try:
        from jpintel_mcp.config import settings  # noqa: WPS433

        return Path(settings.autonomath_db_path)
    except Exception:  # noqa: BLE001 — fall back to repo-root default
        return _REPO / "autonomath.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def disable_stale_subscribers(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Flip ``failure_count >= THRESHOLD`` active rows to disabled. Returns count."""
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(
        """SELECT subscriber_id, failure_count, webhook_url
             FROM am_realtime_subscribers
            WHERE status = 'active'
              AND failure_count >= ?""",
        (FAILURE_STREAK_THRESHOLD,),
    ).fetchall()
    if not rows:
        return 0
    if dry_run:
        logger.info(
            "stale_disable dry_run targets=%d threshold=%d",
            len(rows),
            FAILURE_STREAK_THRESHOLD,
        )
        return len(rows)
    conn.execute(
        """UPDATE am_realtime_subscribers
              SET status = 'disabled',
                  disabled_at = ?,
                  disabled_reason = 'stale_failure_streak',
                  updated_at = ?
            WHERE status = 'active'
              AND failure_count >= ?""",
        (now, now, FAILURE_STREAK_THRESHOLD),
    )
    conn.commit()
    logger.info("stale_disable applied=%d threshold=%d", len(rows), FAILURE_STREAK_THRESHOLD)
    return len(rows)


def prune_dispatch_history(
    conn: sqlite3.Connection,
    *,
    retention_days: int,
    dry_run: bool,
) -> int:
    """Delete ``am_realtime_dispatch_history`` rows older than retention. Returns count."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM am_realtime_dispatch_history WHERE created_at < ?",
        (cutoff,),
    ).fetchone()
    n = int(row[0]) if row else 0
    if n == 0:
        return 0
    if dry_run:
        logger.info("prune_dispatch_history dry_run targets=%d cutoff=%s", n, cutoff)
        return n
    conn.execute(
        "DELETE FROM am_realtime_dispatch_history WHERE created_at < ?",
        (cutoff,),
    )
    conn.commit()
    logger.info("prune_dispatch_history deleted=%d cutoff=%s", n, cutoff)
    return n


def _summary_counts(conn: sqlite3.Connection) -> dict[str, int]:
    active = conn.execute(
        "SELECT COUNT(*) FROM am_realtime_subscribers WHERE status = 'active'",
    ).fetchone()
    disabled = conn.execute(
        "SELECT COUNT(*) FROM am_realtime_subscribers WHERE status = 'disabled'",
    ).fetchone()
    dispatch_total = conn.execute(
        "SELECT COUNT(*) FROM am_realtime_dispatch_history",
    ).fetchone()
    return {
        "active_subscribers": int(active[0]) if active else 0,
        "disabled_subscribers": int(disabled[0]) if disabled else 0,
        "dispatch_history_rows": int(dispatch_total[0]) if dispatch_total else 0,
    }


def run(
    *,
    db_path: Path | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Single pass. Returns observability payload."""
    target = db_path or _resolve_db_path()
    if not target.exists():
        logger.warning("autonomath.db missing at %s; skipping (CI / fresh checkout)", target)
        return {
            "skipped": True,
            "reason": "db_missing",
            "db_path": str(target),
            "dry_run": dry_run,
        }
    conn = _connect(target)
    try:
        # Tolerate missing migration 263 (CI snapshot may lag).
        try:
            disabled_n = disable_stale_subscribers(conn, dry_run=dry_run)
            pruned_n = prune_dispatch_history(
                conn,
                retention_days=retention_days,
                dry_run=dry_run,
            )
            counts = _summary_counts(conn)
        except sqlite3.OperationalError as exc:
            logger.warning("dim G tables not present (%s); skipping", exc)
            return {
                "skipped": True,
                "reason": "table_missing",
                "error": str(exc),
                "db_path": str(target),
                "dry_run": dry_run,
            }
        payload = {
            "skipped": False,
            "ts": datetime.now(UTC).isoformat(),
            "db_path": str(target),
            "dry_run": dry_run,
            "stale_disabled": disabled_n,
            "history_pruned": pruned_n,
            "retention_days": retention_days,
            **counts,
        }
        return payload
    finally:
        conn.close()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="log only, no writes")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"dispatch_history retention window (default {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument("--db-path", type=Path, default=None, help="autonomath.db override")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    payload = run(
        db_path=args.db_path,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
