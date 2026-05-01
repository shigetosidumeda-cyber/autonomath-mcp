#!/usr/bin/env python3
"""Stripe usage backfill cron — heal NULL stripe_synced_at rows (R2 fix).

Why this exists
---------------
The hot path in ``billing/stripe_usage.py:report_usage_async`` spawns a
``threading.Thread(daemon=True)`` to POST every metered request to Stripe.
That thread is fire-and-forget by design — we never block the customer's
request on Stripe — but it has one failure mode that is structurally
revenue-leaking: a SIGTERM during a Fly.io rolling deploy lands between
the local ``usage_events`` INSERT (durable) and the Stripe POST (in-flight,
killed). The local row stays with ``stripe_synced_at IS NULL`` forever and
Stripe never sees the request. Money lost.

``stripe_reconcile.py`` (sibling cron) detects this drift via a daily diff
but only emits a Sentry alert — it does NOT auto-heal. This cron is the
auto-heal. Every 30 min it scans for unsynced metered rows and enqueues
them onto the existing durable ``bg_task_queue`` for the worker to retry.
The worker (``api/_bg_task_worker.py:_handle_stripe_usage_sync``) already
knows how to dispatch ``stripe_usage_sync`` rows — we just need somebody
to enqueue them on a schedule.

Idempotency
-----------
Safe to re-run on the same window for two layered reasons:
  1. ``bg_task_queue`` enqueue uses ``dedup_key='stripe_backfill:{usage_event_id}'``.
     ON CONFLICT DO NOTHING means a second run that sees the same unsynced
     row simply re-uses the existing queue row.
  2. Stripe-side idempotency uses the original
     ``usage_events.billing_idempotency_key`` when present, otherwise falls
     back to ``usage_{usage_event_id}``. This preserves deduplication for
     requests that already posted to Stripe but failed before local sync was
     marked complete.

Window
------
The cron sweeps every currently unsynced metered row, not just a recent
lookback window. That prevents a 72h+ scheduler outage from turning old
``stripe_synced_at IS NULL`` rows into permanent revenue loss. The
``--window-hours`` flag remains in the report for operator context; the
work bound is the ``--max-events`` cap.

Rate limit
----------
At most 1000 events per run by default. With a 30-min cadence that gives
48,000 events/day max throughput, two orders of magnitude above any
realistic post-launch backlog. Excess rolls into the next run.

Cron schedule
-------------
GitHub Actions ``cron: '*/30 * * * *'`` running ``flyctl ssh console`` —
or a Fly.io scheduled machine. See README at the bottom of this docstring.

Usage::

    python scripts/cron/stripe_usage_backfill.py            # real run
    python scripts/cron/stripe_usage_backfill.py --dry-run  # log + count only
    python scripts/cron/stripe_usage_backfill.py --window-hours 168  # report window only
    python scripts/cron/stripe_usage_backfill.py --max-events 500

Required env vars
-----------------
None new. Inherits ``JPINTEL_DB_PATH`` (default ``./data/jpintel.db``) and
``SENTRY_DSN`` / ``JPINTEL_ENV`` from the existing API/cron secrets.

Recommended cron config
-----------------------
GitHub Actions::

    name: stripe-usage-backfill
    on:
      schedule:
        - cron: "*/30 * * * *"   # every 30 min
      workflow_dispatch: {}
    jobs:
      backfill:
        runs-on: ubuntu-latest
        timeout-minutes: 5
        steps:
          - name: Install flyctl
            uses: superfly/flyctl-actions/setup-flyctl@master
          - name: Run backfill on Fly machine
            env:
              FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
            run: |
              flyctl ssh console -a autonomath-api -C \\
                "/app/.venv/bin/python /app/scripts/cron/stripe_usage_backfill.py"

Fly.io scheduled machine (alternative)::

    fly machines run --schedule '*/30 * * * *' \\
       --name stripe-usage-backfill \\
       --image registry.fly.io/autonomath-api:latest \\
       /app/.venv/bin/python /app/scripts/cron/stripe_usage_backfill.py

No Anthropic / OpenAI / SDK calls. Pure SQL + bg_task_queue enqueue. The
existing async worker handles the Stripe POST.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api._bg_task_queue import enqueue  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat, safe_capture_message  # noqa: E402

logger = logging.getLogger("autonomath.cron.stripe_usage_backfill")

# Report window default: 72h. The scanner itself has no lower time bound;
# it orders unsynced rows by id and caps work with _DEFAULT_MAX_EVENTS.
_DEFAULT_WINDOW_HOURS = 72

# Per-run cap: 1000 rows. At ¥3/req that is ¥3,000 of usage healed per run;
# at 30-min cadence that absorbs 48,000 events/day — 2 OOM above any realistic
# backlog. Higher caps risk a single long-running cron crowding out other
# bg_task_queue work behind the SQLite writer lock.
_DEFAULT_MAX_EVENTS = 1000

# A worker crash after claim_next() can leave a task in processing forever.
# Backfill treats a processing row as reclaimable once it has been untouched
# for this long.
_STALE_PROCESSING_AFTER = timedelta(minutes=30)


def _row_value(row: Any, name: str, index: int) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


def _parse_iso_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _processing_is_stale(updated_at: Any, *, now: datetime | None = None) -> bool:
    parsed = _parse_iso_utc(updated_at)
    if parsed is None:
        return True
    return (now or datetime.now(UTC)) - parsed >= _STALE_PROCESSING_AFTER


# ---------------------------------------------------------------------------
# Scan: find unsynced metered rows joined to api_keys for the sub id.
# ---------------------------------------------------------------------------


def _select_unsynced(
    conn: sqlite3.Connection,
    *,
    max_events: int,
) -> list[dict[str, Any]]:
    """Return up to `max_events` unsynced metered events with sub_id resolved.

    JOINs ``api_keys`` to recover ``stripe_subscription_id``. Rows whose
    api_key has NULL ``stripe_subscription_id`` (anonymous tier, free quota)
    are filtered out — they are not billable and never should have hit the
    Stripe sync path. Rows whose api_key was deleted between INSERT and
    backfill (unlikely but possible after a key revocation race) are also
    filtered out via the INNER JOIN.

    Status filter ``< 400 OR IS NULL`` matches the policy in
    ``billing/stripe_usage.py``: 4xx/5xx requests are not billed. NULL
    status is treated as success because a few code paths log usage before
    setting status (e.g. streaming responses); rejecting them would
    under-bill.

    The ``stripe_synced_at IS NULL`` predicate is index-backed by the
    partial index ``idx_usage_events_stripe_sync``, so the scan stays O(K)
    in unsynced rows regardless of total table size.
    """
    select_sql = """
        SELECT ue.id           AS usage_event_id,
               ak.stripe_subscription_id AS subscription_id,
               COALESCE(ue.quantity, 1) AS quantity,
               ue.billing_idempotency_key AS billing_idempotency_key
          FROM usage_events ue
          JOIN api_keys ak ON ak.key_hash = ue.key_hash
         WHERE ue.metered = 1
           AND (ue.status IS NULL OR ue.status < 400)
           AND ue.stripe_synced_at IS NULL
           AND ak.stripe_subscription_id IS NOT NULL
           AND ak.stripe_subscription_id != ''
         ORDER BY ue.id ASC
         LIMIT ?
    """
    try:
        cur = conn.execute(select_sql, (max_events,))
    except sqlite3.OperationalError as exc:
        if "billing_idempotency_key" not in str(exc):
            raise
        cur = conn.execute(
            select_sql.replace(
                "ue.billing_idempotency_key AS billing_idempotency_key",
                "NULL AS billing_idempotency_key",
            ),
            (max_events,),
        )
    rows: list[dict[str, Any]] = []
    for row in cur.fetchall():
        rows.append({
            "usage_event_id": int(row[0]),
            "subscription_id": str(row[1]),
            "quantity": int(row[2]),
            "billing_idempotency_key": row[3] if row[3] else None,
        })
    return rows


# ---------------------------------------------------------------------------
# Enqueue: push each unsynced row onto bg_task_queue with a stable dedup key.
# ---------------------------------------------------------------------------


def _enqueue_one(
    conn: sqlite3.Connection,
    *,
    usage_event_id: int,
    subscription_id: str,
    quantity: int,
    billing_idempotency_key: str | None = None,
) -> tuple[bool, int | None]:
    """Enqueue a `stripe_usage_sync` task for one usage_event row.

    Returns ``(was_new, task_id)``. ``was_new`` is True iff the enqueue
    inserted a new row (False on dedup_key conflict — the queue already
    knows about this usage_event from a previous cron run).

    Implementation note: ``enqueue()`` returns the row id whether the row
    was newly inserted or pre-existing (ON CONFLICT path), so we cannot
    distinguish those two outcomes from the return alone. We pre-check by
    SELECT'ing the dedup_key first. The race window between SELECT and
    INSERT is harmless (ON CONFLICT DO NOTHING absorbs it) but the counter
    in the report would wobble; the pre-check keeps the breadcrumb honest.
    """
    dedup_key = f"stripe_backfill:{usage_event_id}"
    payload = {
        "subscription_id": subscription_id,
        "usage_event_id": usage_event_id,
        "quantity": quantity,
    }
    if billing_idempotency_key:
        payload["idempotency_key"] = billing_idempotency_key
    existing = conn.execute(
        "SELECT id, status, updated_at FROM bg_task_queue WHERE dedup_key = ?",
        (dedup_key,),
    ).fetchone()
    if existing is not None:
        existing_id = int(_row_value(existing, "id", 0))
        existing_status = _row_value(existing, "status", 1)
        existing_updated_at = _row_value(existing, "updated_at", 2)
        if (
            existing_status == "done"
            or existing_status == "failed"
            or (
            existing_status == "processing"
            and _processing_is_stale(existing_updated_at)
            )
        ):
            conn.execute(
                "UPDATE bg_task_queue "
                "SET status = 'pending', attempts = 0, last_error = NULL, "
                "payload_json = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "next_attempt_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    existing_id,
                ),
            )
            return True, existing_id
        return False, existing_id

    task_id = enqueue(
        conn,
        kind="stripe_usage_sync",
        payload=payload,
        dedup_key=dedup_key,
    )
    return True, task_id


def _select_recoverable_widget_overage_tasks(
    conn: sqlite3.Connection,
    *,
    max_tasks: int,
) -> list[dict[str, Any]]:
    """Return stuck widget overage queue rows that need another worker pass."""
    rows = conn.execute(
        """
        SELECT id, status, updated_at, dedup_key, payload_json
          FROM bg_task_queue
         WHERE kind = 'stripe_usage_sync'
           AND dedup_key LIKE 'widget_overage:%'
           AND status IN ('failed', 'processing')
         ORDER BY id ASC
         LIMIT ?
        """,
        (max_tasks,),
    ).fetchall()
    recoverable: list[dict[str, Any]] = []
    for row in rows:
        status = str(_row_value(row, "status", 1))
        updated_at = _row_value(row, "updated_at", 2)
        if status == "failed" or (
            status == "processing" and _processing_is_stale(updated_at)
        ):
            recoverable.append(
                {
                    "id": int(_row_value(row, "id", 0)),
                    "dedup_key": _row_value(row, "dedup_key", 3),
                    "payload_json": _row_value(row, "payload_json", 4),
                }
            )
    return recoverable


def _payload_with_widget_idempotency(task: dict[str, Any]) -> str | None:
    dedup_key = str(task.get("dedup_key") or "")
    if not dedup_key.startswith("widget_overage:"):
        return None
    idempotency_key = dedup_key.removeprefix("widget_overage:")
    try:
        payload = json.loads(str(task.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["idempotency_key"] = idempotency_key
    payload["quantity"] = 1
    return json.dumps(payload, ensure_ascii=False, default=str)


def _requeue_existing_task(conn: sqlite3.Connection, task: dict[str, Any]) -> None:
    payload_json = _payload_with_widget_idempotency(task)
    task_id = int(task["id"])
    payload_clause = "payload_json = ?, " if payload_json is not None else ""
    params: tuple[Any, ...] = (
        (payload_json, task_id) if payload_json is not None else (task_id,)
    )
    conn.execute(
        "UPDATE bg_task_queue "
        "SET status = 'pending', attempts = 0, last_error = NULL, "
        f"{payload_clause}"
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "next_attempt_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        params,
    )


# ---------------------------------------------------------------------------
# Main backfill pass.
# ---------------------------------------------------------------------------


def backfill(
    *,
    window_hours: int = _DEFAULT_WINDOW_HOURS,
    max_events: int = _DEFAULT_MAX_EVENTS,
    dry_run: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Single backfill pass. Returns a counter report.

    The report shape mirrors ``stripe_reconcile``'s style for grep'ability:
    operators tail both crons' Sentry breadcrumbs together and a consistent
    schema makes the dashboard one-shot. Keys:

      * ``run_id``          — UTC ISO timestamp at start of run
      * ``window``          — {from, to} ISO range scanned
      * ``scanned``         — rows returned by the SELECT
      * ``enqueued``        — rows that were NEW in bg_task_queue this run
      * ``already_queued``  — rows whose dedup_key already existed
      * ``errors``          — exceptions thrown during enqueue (best effort)
      * ``dry_run``         — bool
      * ``max_events``      — cap applied to the scan
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    since_iso = since.isoformat()
    until_iso = now.isoformat()

    conn = connect(db_path) if db_path else connect()
    enqueued = 0
    already_queued = 0
    widget_overage_requeued = 0
    errors = 0
    try:
        rows = _select_unsynced(conn, max_events=max_events)
        scanned = len(rows)
        widget_overage_tasks = _select_recoverable_widget_overage_tasks(
            conn,
            max_tasks=max_events,
        )

        if dry_run:
            # Don't enqueue; just count what WOULD have been new.
            for r in rows:
                dedup_key = f"stripe_backfill:{r['usage_event_id']}"
                existing = conn.execute(
                    "SELECT id FROM bg_task_queue WHERE dedup_key = ?",
                    (dedup_key,),
                ).fetchone()
                if existing is None:
                    enqueued += 1
                else:
                    already_queued += 1
            widget_overage_requeued = len(widget_overage_tasks)
        else:
            # Real run: enqueue inside a single tx so a crash mid-loop
            # doesn't half-fill the queue. The ON CONFLICT DO NOTHING
            # contract makes this safe to retry as a whole.
            conn.execute("BEGIN")
            try:
                for r in rows:
                    try:
                        was_new, _ = _enqueue_one(
                            conn,
                            usage_event_id=r["usage_event_id"],
                            subscription_id=r["subscription_id"],
                            quantity=r["quantity"],
                            billing_idempotency_key=r.get("billing_idempotency_key"),
                        )
                        if was_new:
                            enqueued += 1
                        else:
                            already_queued += 1
                    except Exception:
                        errors += 1
                        logger.warning(
                            "backfill enqueue failed event_id=%s sub=%s",
                            r["usage_event_id"],
                            r["subscription_id"],
                            exc_info=True,
                        )
                for task in widget_overage_tasks:
                    _requeue_existing_task(conn, task)
                    widget_overage_requeued += 1
                conn.execute("COMMIT")
            except Exception:
                with contextlib.suppress(Exception):  # pragma: no cover — defensive
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()

    report: dict[str, Any] = {
        "run_id": now.isoformat(),
        "window": {"from": since_iso, "to": until_iso},
        "scanned": scanned,
        "enqueued": enqueued,
        "already_queued": already_queued,
        "widget_overage_requeued": widget_overage_requeued,
        "errors": errors,
        "dry_run": dry_run,
        "max_events": max_events,
    }

    # Sentry breadcrumb — always emitted (info level), so an operator can
    # see "ran, found N, enqueued K" even when nothing went wrong. Only
    # error-level alerts during true failure (errors > 0) so the operator
    # inbox stays low-volume.
    if not dry_run:
        safe_capture_message(
            f"stripe_usage_backfill: scanned={scanned} enqueued={enqueued} "
            f"already_queued={already_queued} "
            f"widget_overage_requeued={widget_overage_requeued} errors={errors}",
            level="error" if errors > 0 else "info",
            scanned=str(scanned),
            enqueued=str(enqueued),
            already_queued=str(already_queued),
            widget_overage_requeued=str(widget_overage_requeued),
            errors=str(errors),
            window_hours=str(window_hours),
        )

    logger.info(
        "stripe_usage_backfill done scanned=%d enqueued=%d already_queued=%d "
        "widget_overage_requeued=%d errors=%d dry_run=%s",
        scanned,
        enqueued,
        already_queued,
        widget_overage_requeued,
        errors,
        dry_run,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Backfill unsynced Stripe usage_events via bg_task_queue.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be enqueued; do not write to bg_task_queue.",
    )
    p.add_argument(
        "--window-hours",
        type=int,
        default=_DEFAULT_WINDOW_HOURS,
        help=f"Lookback window (default {_DEFAULT_WINDOW_HOURS}h).",
    )
    p.add_argument(
        "--max-events",
        type=int,
        default=_DEFAULT_MAX_EVENTS,
        help=f"Cap rows enqueued per run (default {_DEFAULT_MAX_EVENTS}).",
    )
    p.add_argument(
        "--db",
        default=None,
        help="Override DB path (default: settings.db_path).",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with heartbeat("stripe_usage_backfill") as hb:
        report = backfill(
            window_hours=args.window_hours,
            max_events=args.max_events,
            dry_run=args.dry_run,
            db_path=args.db,
        )
        hb["rows_processed"] = int(report.get("enqueued", 0) or 0)
        hb["rows_skipped"] = int(report.get("already_queued", 0) or 0)
        hb["metadata"] = {
            "scanned": report.get("scanned"),
            "errors": report.get("errors"),
            "dry_run": bool(args.dry_run),
        }

    # Emit JSON to stdout for grep / jq pipelines.
    import json
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Exit non-zero only on enqueue exceptions, so cron schedulers (GH
    # Actions, Fly cron) retry. Empty windows are normal — exit 0.
    return 1 if report["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
