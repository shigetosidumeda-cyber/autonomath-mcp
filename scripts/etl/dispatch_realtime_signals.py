"""Wave 47 — Dim G realtime_signal dispatcher (HTTP only, NO LLM).

Walks ``am_realtime_signal_event_log`` for rows with ``delivered_at IS NULL``
and POSTs each event payload to the matching subscriber's ``webhook_url``.

Hard constraints
----------------
* **NO LLM API call.** Pure HTTP POST. No ``anthropic`` / ``openai`` import
  anywhere in this file (guarded by ``tests/test_dim_g_realtime.py``).
* **Idempotent.** Already-delivered rows (``delivered_at IS NOT NULL``) are
  skipped. ``attempt_count`` is incremented on every retry; a row only
  flips to delivered on a 2xx status code.
* **Read-only inside the request.** No mutation of subscriber rows on a
  failure path (apart from ``attempt_count++`` and ``error``).
* **Append-only event log.** Existing event rows are never deleted by this
  script; a separate retention cron handles GC.

Pricing posture
---------------
One 2xx delivery row = one ¥3 billable unit. The reconciliation job (in
``scripts/cron/maintain_realtime_signal_subscribers.py``) sweeps
``delivered_at IS NOT NULL AND status_code BETWEEN 200 AND 299`` and emits
metered events. This dispatcher does NOT itself emit metering events.

Usage
-----
    python scripts/etl/dispatch_realtime_signals.py
    python scripts/etl/dispatch_realtime_signals.py --dry-run
    python scripts/etl/dispatch_realtime_signals.py --db PATH --limit 100

Exit codes
----------
* 0 — dispatcher finished (some events may still be pending; that is OK)
* 1 — hard failure (missing table / db unreadable)
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("dispatch_realtime_signals")

DEFAULT_LIMIT = 200
DEFAULT_TIMEOUT_S = 5.0
_ERROR_MAX_LEN = 256


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _truncate(s: str, n: int = _ERROR_MAX_LEN) -> str:
    return s[:n]


def _http_post(url: str, body: bytes, timeout_s: float) -> tuple[int, str | None]:
    """POST ``body`` (UTF-8 JSON) to ``url``. Returns (status_code, error_str).

    Lives in its own function so the dim G test can monkeypatch the network
    call without touching the rest of the dispatcher logic.
    """
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "jpcite-realtime-signal-dispatcher/1 (+https://jpcite.ai)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - https-only validated upstream
            return int(resp.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), _truncate(f"HTTPError: {exc.reason!s}")
    except urllib.error.URLError as exc:
        return 0, _truncate(f"URLError: {exc.reason!s}")
    except TimeoutError as exc:
        return 0, _truncate(f"Timeout: {exc!s}")
    except Exception as exc:  # noqa: BLE001 - dispatcher MUST NOT crash on per-row failure
        return 0, _truncate(f"{type(exc).__name__}: {exc!s}")


def _select_pending(
    conn: sqlite3.Connection, limit: int
) -> list[tuple[int, int, str, str, str, int]]:
    """Return list of (event_id, subscriber_id, signal_type, payload,
    webhook_url, attempt_count)."""
    sql = """
        SELECT
            e.event_id,
            e.subscriber_id,
            e.signal_type,
            e.payload,
            s.webhook_url,
            e.attempt_count
        FROM am_realtime_signal_event_log e
        JOIN am_realtime_signal_subscriber s
          ON s.subscriber_id = e.subscriber_id
        WHERE e.delivered_at IS NULL
          AND s.enabled = 1
        ORDER BY e.created_at ASC
        LIMIT ?
    """
    return [
        (r[0], r[1], r[2], r[3], r[4], r[5])
        for r in conn.execute(sql, (int(limit),)).fetchall()
    ]


def _mark_delivered(
    conn: sqlite3.Connection,
    event_id: int,
    subscriber_id: int,
    status_code: int,
) -> None:
    conn.execute(
        """
        UPDATE am_realtime_signal_event_log
           SET status_code   = ?,
               delivered_at  = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               error         = NULL
         WHERE event_id = ?
        """,
        (int(status_code), int(event_id)),
    )
    conn.execute(
        """
        UPDATE am_realtime_signal_subscriber
           SET last_signal_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               updated_at     = strftime('%Y-%m-%dT%H:%M:%fZ','now')
         WHERE subscriber_id = ?
        """,
        (int(subscriber_id),),
    )


def _mark_failed(
    conn: sqlite3.Connection,
    event_id: int,
    status_code: int,
    error: str | None,
) -> None:
    conn.execute(
        """
        UPDATE am_realtime_signal_event_log
           SET status_code   = ?,
               attempt_count = attempt_count + 1,
               error         = ?
         WHERE event_id = ?
        """,
        (int(status_code) if status_code else None, error, int(event_id)),
    )


def dispatch(
    db_path: Path,
    *,
    limit: int = DEFAULT_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    dry_run: bool = False,
    post_fn: Any = None,
) -> dict[str, int]:
    """Run one pass of the dispatcher.

    Returns ``{'pending': N, 'delivered': M, 'failed': K, 'skipped': S}``.

    ``post_fn`` is injectable for testing (default: real ``_http_post``).
    """
    post = post_fn if post_fn is not None else _http_post

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "am_realtime_signal_subscriber"):
            raise RuntimeError(
                "am_realtime_signal_subscriber missing — apply migration "
                "286_realtime_signal.sql first"
            )
        if not _table_exists(conn, "am_realtime_signal_event_log"):
            raise RuntimeError(
                "am_realtime_signal_event_log missing — apply migration "
                "286_realtime_signal.sql first"
            )

        pending = _select_pending(conn, limit)
        delivered = 0
        failed = 0
        skipped = 0

        for event_id, subscriber_id, signal_type, payload, webhook_url, attempt_count in pending:
            envelope = {
                "schema": "jpcite.realtime_signal.v1",
                "event_id": int(event_id),
                "subscriber_id": int(subscriber_id),
                "signal_type": signal_type,
                "attempt": int(attempt_count),
                "payload": json.loads(payload) if payload else {},
            }
            body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

            if dry_run:
                skipped += 1
                LOG.debug(
                    "dry-run: would POST event=%d sub=%d type=%s url=%s bytes=%d",
                    event_id, subscriber_id, signal_type, webhook_url, len(body),
                )
                continue

            status, error = post(webhook_url, body, timeout_s)
            if 200 <= status < 300:
                _mark_delivered(conn, event_id, subscriber_id, status)
                delivered += 1
                LOG.info(
                    "delivered event=%d sub=%d type=%s status=%d",
                    event_id, subscriber_id, signal_type, status,
                )
            else:
                _mark_failed(conn, event_id, status, error)
                failed += 1
                LOG.warning(
                    "failed event=%d sub=%d type=%s status=%s error=%s",
                    event_id, subscriber_id, signal_type, status or "—", error or "—",
                )

        if not dry_run:
            conn.commit()

        return {
            "pending": len(pending),
            "delivered": delivered,
            "failed": failed,
            "skipped": skipped,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help="path to autonomath.db (default: repo root)",
    )
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"max events to attempt in one pass (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S,
        help=f"per-request timeout seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would deliver without writing",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        stats = dispatch(
            args.db,
            limit=args.limit,
            timeout_s=args.timeout,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        LOG.error("dispatcher failed: %s", exc)
        return 1

    LOG.info(
        "dispatcher %s: pending=%d delivered=%d failed=%d skipped=%d",
        "dry-run" if args.dry_run else "applied",
        stats["pending"], stats["delivered"], stats["failed"], stats["skipped"],
    )
    # Emit machine-readable summary as the final stdout line for cron/CI.
    print(json.dumps({"dispatcher": "realtime_signal", **stats}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
