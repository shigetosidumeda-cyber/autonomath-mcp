"""Durable background-task worker (companion to `_bg_task_queue.py`).

Wired into the FastAPI lifespan in `api/main.py`: on startup we spawn
`run_worker_loop()` as an asyncio task, on shutdown we set `stop_event`
and `await` the cancellation. The worker polls every 2s, claims one task
at a time, dispatches by `kind`, and never lets a handler exception kill
the loop — exceptions go to logger + Sentry + `mark_failed` for retry.

Why one task at a time, not a pool: SQLite serializes writes anyway, and
the dispatchers that matter (Postmark welcome, Stripe API refresh) are
seconds-class IO. Going parallel would just queue behind the SQLite writer
lock without lower wall-clock latency. If a future bottleneck appears,
swap claim_next() for a batched claim and run handlers in `asyncio.gather`.

Design contract:
  * Handlers MUST NOT raise into the worker. They either return cleanly
    (mark_done) or raise (mark_failed schedules retry). The worker catches
    every exception class and converts to `mark_failed`.
  * Handlers MUST be idempotent on retry. Welcome / key_rotated / dunning
    emails: Postmark is idempotent on (alias + recipient + body) within
    the day, so a duplicate fires twice into Postmark but Postmark drops
    the second copy. Stripe status refresh: pure read + DB write, safe
    to repeat.
  * Each handler invocation gets its OWN short-lived DB connection so a
    worker exception cannot leak a half-open transaction across iterations.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from jpintel_mcp.api._bg_task_queue import (
    claim_next,
    mark_done,
    mark_failed,
)
from jpintel_mcp.db.session import connect as _db_connect

logger = logging.getLogger("jpintel.bg_task_worker")

POLL_INTERVAL_S = 2.0


# ---------------------------------------------------------------------------
# Sentry forwarding (best-effort; same shape as api/billing.py)
# ---------------------------------------------------------------------------
try:
    import sentry_sdk as _sentry_sdk  # noqa: TC003
    _SENTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SENTRY_AVAILABLE = False


def _capture(exc: BaseException) -> None:
    if _SENTRY_AVAILABLE:
        try:
            _sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover
            logger.debug("sentry_capture_failed", exc_info=True)


# ---------------------------------------------------------------------------
# Handlers — one per `kind`. Imports are lazy so a circular-import in the
# billing module doesn't cascade into worker startup.
# ---------------------------------------------------------------------------


def _handle_welcome_email(payload: dict[str, Any]) -> None:
    """Send the D+0 welcome mail (key_last4 only — raw key never leaves
    success.html).

    Payload contract: {"to": str | None, "key_last4": str, "tier": str}.
    Backward-compat: a queued in-flight row from the pre-fix code may
    still carry "raw_key" in plaintext — accept it, derive key_last4
    locally, and never log the raw value (P1, audit 2026-04-26).

    Mirrors the inline `_send_welcome_safe` body — but the OUTER caller
    (`billing.webhook`) used to swallow exceptions; here we re-raise so
    the queue can schedule a retry. The email module's transport layer
    is non-raising on test/no-token paths, so a raise here means a real
    Postmark API failure (transient → worth retrying).
    """
    to = payload.get("to")
    tier = payload.get("tier") or "paid"
    if not to:
        return  # nothing to send

    key_last4 = payload.get("key_last4")
    if not key_last4:
        legacy_raw = payload.get("raw_key") or ""
        key_last4 = legacy_raw[-4:] if legacy_raw else "????"

    from jpintel_mcp.email import get_client as _get_email_client
    _get_email_client().send_welcome(
        to=to,
        key_last4=key_last4,
        tier=tier,
    )


def _handle_key_rotated_email(payload: dict[str, Any]) -> None:
    """Send the rotation security notice (key_last4 + ip + UA + ts_jst).

    Payload: {"to", "old_suffix", "new_suffix", "ip", "user_agent", "ts_jst"}.
    """
    to = payload.get("to")
    if not to:
        return
    from jpintel_mcp.email import get_client as _get_email_client
    _get_email_client().send_key_rotated(
        to=to,
        old_suffix=payload.get("old_suffix") or "????",
        new_suffix=payload.get("new_suffix") or "????",
        ip=payload.get("ip") or "unknown",
        user_agent=payload.get("user_agent") or "unknown",
        ts_jst=payload.get("ts_jst") or "",
    )


def _handle_stripe_status_refresh(payload: dict[str, Any]) -> None:
    """Live-fetch a Stripe subscription and refresh the local cache.

    Payload: {"sub_id": str}. Mirrors
    `billing._refresh_subscription_status_from_stripe_bg` but uses our
    own short-lived connection.
    """
    sub_id = payload.get("sub_id")
    if not sub_id:
        return
    from jpintel_mcp.api.billing import _refresh_subscription_status_from_stripe
    conn = _db_connect()
    try:
        _refresh_subscription_status_from_stripe(conn, sub_id)
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def _handle_dunning_email(payload: dict[str, Any]) -> None:
    """Send the past-due dunning notice with key_last4 + portal URL.

    Payload: {"to", "sub_id", "attempt_count", "next_retry_epoch"}.
    """
    to = payload.get("to")
    if not to:
        return
    from jpintel_mcp.api.billing import _send_dunning_safe
    conn = _db_connect()
    try:
        _send_dunning_safe(
            conn=conn,
            to=to,
            sub_id=payload.get("sub_id"),
            attempt_count=int(payload.get("attempt_count") or 1),
            next_retry_epoch=payload.get("next_retry_epoch"),
        )
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def _handle_stripe_usage_sync(payload: dict[str, Any]) -> None:
    """Reconcile a usage_events row that was inserted before Stripe sync.

    Payload: {"subscription_id": str, "quantity": int,
              "usage_event_id": int}.

    Only used when a stripe_usage daemon thread legitimately failed and we
    want to retry through the queue. The default hot-path stays the
    threading.Thread fire-and-forget in `billing/stripe_usage.py` because
    the local usage_events row is durable on its own — Stripe-side reconciliation
    can also run from `scripts/cron/` without going through this queue.
    """
    sub_id = payload.get("subscription_id")
    if not sub_id:
        return
    from jpintel_mcp.billing.stripe_usage import _report_sync
    _report_sync(
        sub_id,
        quantity=int(payload.get("quantity") or 1),
        usage_event_id=payload.get("usage_event_id"),
    )


# Single source of truth for kind → handler.
_HANDLERS = {
    "welcome_email": _handle_welcome_email,
    "key_rotated_email": _handle_key_rotated_email,
    "stripe_status_refresh": _handle_stripe_status_refresh,
    "dunning_email": _handle_dunning_email,
    "stripe_usage_sync": _handle_stripe_usage_sync,
}


def _dispatch_one(task_row: Any) -> tuple[bool, str | None]:
    """Run a handler for one claimed row.

    Returns `(success, error_short)`. `error_short` is None on success,
    else the exception's short repr capped at 256 chars.
    """
    kind = task_row["kind"]
    payload_str = task_row["payload_json"]
    try:
        payload = json.loads(payload_str)
    except Exception as exc:
        return False, f"payload_json invalid: {exc!r}"[:256]

    handler = _HANDLERS.get(kind)
    if handler is None:
        return False, f"unknown kind: {kind}"

    try:
        handler(payload)
        return True, None
    except Exception as exc:
        _capture(exc)
        logger.warning(
            "bg_task_handler_failed kind=%s id=%s",
            kind,
            task_row["id"],
            exc_info=True,
        )
        return False, repr(exc)[:256]


async def run_worker_loop(stop_event: asyncio.Event) -> None:
    """Main worker loop. Cancels cleanly on `stop_event.set()`.

    Each iteration:
      1. Open a fresh DB connection (cheap; SQLite local file).
      2. claim_next() — atomic SELECT + UPDATE inside BEGIN IMMEDIATE.
      3. If a row was claimed, dispatch via _dispatch_one.
      4. Mark done or schedule retry. Close connection.
      5. Sleep POLL_INTERVAL_S, OR until stop_event.set() — whichever first.
    """
    logger.info("bg_task_worker_started poll_interval_s=%s", POLL_INTERVAL_S)
    while not stop_event.is_set():
        try:
            conn = _db_connect()
            try:
                row = claim_next(conn)
            finally:
                # Close after the claim transaction so the worker doesn't
                # hold a connection idle while sleeping. The dispatcher
                # opens its own short-lived conn for handler-side DB I/O.
                try:
                    conn.close()
                except Exception:  # pragma: no cover
                    pass

            if row is not None:
                ok, err = _dispatch_one(row)
                conn2 = _db_connect()
                try:
                    if ok:
                        mark_done(conn2, int(row["id"]))
                    else:
                        mark_failed(conn2, int(row["id"]), err or "unknown")
                finally:
                    try:
                        conn2.close()
                    except Exception:  # pragma: no cover
                        pass
                # Loop tight on a hit so a backlog drains quickly.
                continue

        except asyncio.CancelledError:  # pragma: no cover
            logger.info("bg_task_worker_cancelled")
            raise
        except Exception as exc:
            # Last-line defence: never let a worker-level bug kill the loop.
            # Sleep the full interval so a tight failure loop doesn't
            # hammer the DB / logs.
            _capture(exc)
            logger.exception("bg_task_worker_iteration_error")

        # Sleep with cancellation responsiveness.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
        except asyncio.TimeoutError:
            pass

    logger.info("bg_task_worker_stopped")


__all__ = ["run_worker_loop", "POLL_INTERVAL_S"]
