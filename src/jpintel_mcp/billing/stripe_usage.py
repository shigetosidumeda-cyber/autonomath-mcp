"""Fire-and-forget Stripe usage reporter (legacy metered / usage_records).

Pure metered billing (¥3/req 税別 / ¥3.30 税込). Every successful request for
a `paid` tier key spawns a daemon thread that:

  1. Looks up the subscription_item_id for the caller's Stripe subscription
     (cached in-process via functools.lru_cache — Stripe subs are immutable
     in `items[0].id` for the subscription's lifetime in our single-price
     model, so a per-process cache is safe).
  2. POSTs quantity=1 to /v1/subscription_items/{si}/usage_records with
     `action=increment` and `timestamp=now`.

API-version pinning: legacy metered prices can only be read / written under
`Stripe-Version: 2024-11-20.acacia`. Under `2025-03-31.basil`+ Stripe
requires a Meter object (`rak_billing_meter_write` permission we do not
hold). The pin is applied at module import time via
`stripe.api_version = settings.stripe_api_version`.

Failure policy: this is fire-and-forget. Any exception inside the thread
(HTTP error, Stripe outage, stale cache, revoked subscription) is swallowed
after a WARN log. The request path MUST NOT block on Stripe or fail the
customer's call because we could not report usage — Stripe retries on
usage_records are not supported (legacy metered is idempotent only when the
caller supplies `idempotency_key`, which is derived from the local
usage_events row id so duplicate calls for the same logical request collide
and Stripe deduplicates server-side).
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from functools import lru_cache

import stripe

from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.billing.usage")


def _configure_stripe() -> None:
    """Set `stripe.api_key` + `stripe.api_version` if not already set.

    Called lazily from each report so test monkeypatches of `settings`
    take effect. No-op if no secret key configured (usage reporting is
    optional — deps.log_usage still writes to `usage_events` for the
    audit trail even when Stripe is not reachable).
    """
    if settings.stripe_secret_key and stripe.api_key != settings.stripe_secret_key:
        stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version


@lru_cache(maxsize=4096)
def _get_subscription_item_id(subscription_id: str) -> str | None:
    """Return the first subscription_item.id for a subscription.

    Our billing model has exactly one metered Price per subscription
    (lookup_key=per_request_v3), so items[0] is unambiguous. Result is
    cached for the process lifetime — Stripe sub items are stable for a
    given subscription in our single-price setup, and a process restart
    on deploy is frequent enough that a TTL is not needed.

    Returns None on any error; the caller logs and skips.
    """
    if not subscription_id:
        return None
    _configure_stripe()
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        items = sub.get("items", {}).get("data", []) if isinstance(sub, dict) else None
        if items is None and hasattr(sub, "items"):
            items = sub["items"]["data"]
        if not items:
            return None
        return items[0]["id"]
    except Exception:
        logger.warning("sub_item lookup failed sub=%s", subscription_id, exc_info=True)
        return None


def _mark_synced(usage_event_id: int, stripe_record_id: str) -> None:
    """Update usage_events row with Stripe record id + sync timestamp.

    Opens its own short-lived connection because we are running in a
    daemon thread and cannot share the request connection. Failures here
    are non-fatal: the row simply remains unmarked and the next
    reconciliation pass treats it as unsynced (stripe_synced_at IS NULL,
    indexed for fast scan).
    """
    try:
        from jpintel_mcp.db.session import connect

        conn = connect()
        try:
            conn.execute(
                "UPDATE usage_events SET stripe_record_id = ?, stripe_synced_at = ? "
                "WHERE id = ?",
                (
                    stripe_record_id,
                    datetime.now(UTC).isoformat(),
                    usage_event_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "usage_events sync mark failed event_id=%s record=%s",
            usage_event_id,
            stripe_record_id,
            exc_info=True,
        )


def _report_sync(
    subscription_id: str,
    quantity: int = 1,
    usage_event_id: int | None = None,
) -> None:
    """Synchronous inner body — always called from a daemon thread.

    On success, if `usage_event_id` was supplied, the local
    `usage_events` row is updated with `stripe_record_id` + `stripe_synced_at`.
    On failure, the row is left NULL so a future reconciliation pass can
    retry (audit a37f6226fe319dc40).
    """
    if not settings.stripe_secret_key:
        return
    si_id = _get_subscription_item_id(subscription_id)
    if not si_id:
        return
    _configure_stripe()
    # Idempotency key MUST be stable per logical request so the inline
    # `log_usage` and the deferred `_record_usage_async` paths cannot
    # double-bill (audit P0-1, 2026-04-26). The local `usage_events` row id
    # is monotonic and unique per request — same request → same row id →
    # same idempotency_key → Stripe server-side dedup. When the row id is
    # unavailable (legacy callers, sqlite write failure), fall back to
    # (subscription_id, second-truncated timestamp): two reports in the
    # same second collide intentionally — better a missed unit than a
    # double-charge.
    if usage_event_id is not None:
        idem_key = f"usage_{usage_event_id}"
    else:
        idem_key = f"usage_{subscription_id}_{int(datetime.now(UTC).timestamp())}"
    try:
        record = stripe.SubscriptionItem.create_usage_record(  # type: ignore[attr-defined]  # legacy API, pinned to stripe-api-version 2024-11-20.acacia where usage_records still exists
            si_id,
            quantity=quantity,
            timestamp=int(datetime.now(UTC).timestamp()),
            action="increment",
            idempotency_key=idem_key,
        )
    except Exception:
        logger.warning(
            "usage_record POST failed sub=%s si=%s", subscription_id, si_id, exc_info=True
        )
        return
    if usage_event_id is None:
        return
    record_id = None
    try:
        record_id = record.get("id") if isinstance(record, dict) else getattr(record, "id", None)
    except Exception:
        record_id = None
    if record_id:
        _mark_synced(usage_event_id, record_id)


def report_usage_async(
    subscription_id: str | None,
    quantity: int = 1,
    usage_event_id: int | None = None,
) -> None:
    """Spawn a daemon thread to report 1 unit of usage to Stripe.

    Called from `deps.log_usage` on successful metered requests. Never
    raises; never blocks. Safe to call with `subscription_id=None` (no-op).

    `usage_event_id` is the autoincrement id of the just-inserted
    `usage_events` row. If supplied, the worker writes back
    `stripe_record_id` + `stripe_synced_at` on Stripe success so a Fly
    volume DR scenario can reconcile remaining NULL rows from the Stripe
    ledger (audit a37f6226fe319dc40).
    """
    if not subscription_id:
        return
    t = threading.Thread(
        target=_report_sync,
        args=(subscription_id, quantity, usage_event_id),
        daemon=True,
        name="stripe-usage",
    )
    t.start()


__all__ = ["report_usage_async"]
