"""Fire-and-forget Stripe usage reporter (legacy metered / usage_records).

Pure metered billing (¥3/req 税別 / ¥3.30 税込). Every successful request for
a `paid` tier key spawns a daemon thread that:

  1. Looks up the metered subscription_item_id for the caller's Stripe
     subscription (cached in-process via functools.lru_cache). In the
     normal API subscription there is one metered item; widget subscriptions
     can also have a fixed monthly base item plus a metered overage item, so
     item selection must never assume `items[0]`.
  2. POSTs the local usage_events `quantity` to
     /v1/subscription_items/{si}/usage_records with `action=increment` and
     `timestamp=now`.

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
from typing import Any

from jpintel_mcp._lazy_stripe import stripe
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.billing.usage")


class UsageReportError(RuntimeError):
    """Raised when a durable Stripe usage sync did not complete."""


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


def _stripe_value(obj: Any, key: str, default: Any = None) -> Any:
    """Read a key from dict-like Stripe objects and plain dict test doubles."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, default)


def _stripe_path(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        cur = _stripe_value(cur, key)
        if cur is None:
            return None
    return cur


def _is_metered_item(item: Any) -> bool:
    usage_type = _stripe_path(item, "price", "recurring", "usage_type")
    if usage_type is None:
        usage_type = _stripe_path(item, "plan", "usage_type")
    return bool(usage_type == "metered")


def _metadata_text(metadata: Any) -> str:
    if not metadata:
        return ""
    if not isinstance(metadata, dict):
        try:
            metadata = dict(metadata)
        except Exception:
            return ""
    return " ".join(f"{k} {v}" for k, v in metadata.items()).lower()


def _looks_like_overage_item(item: Any) -> bool:
    price = _stripe_value(item, "price") or {}
    haystack = " ".join(
        str(part or "")
        for part in (
            _stripe_value(item, "id"),
            _stripe_value(item, "metadata"),
            _stripe_value(price, "id"),
            _stripe_value(price, "lookup_key"),
            _stripe_value(price, "nickname"),
            _metadata_text(_stripe_value(price, "metadata")),
        )
    ).lower()
    return "overage" in haystack


def _select_subscription_item(items: list[Any]) -> Any | None:
    """Pick the Stripe item that accepts usage_records.

    Multiple-item widget subscriptions have a licensed base item and a
    metered overage item. The core API has one metered item. If a legacy
    test double omits recurring.usage_type but only supplies a single item,
    keep the old single-item behavior; with multiple non-metered/unknown
    items, fail closed instead of charging the first line.
    """
    metered_items = [item for item in items if _is_metered_item(item)]
    if metered_items:
        for item in metered_items:
            if _looks_like_overage_item(item):
                return item
        return metered_items[0]
    if len(items) == 1:
        return items[0]
    return None


@lru_cache(maxsize=4096)
def _get_subscription_item_id(subscription_id: str) -> str | None:
    """Return the metered subscription_item.id for a subscription.

    Core API subscriptions have exactly one metered Price
    (lookup_key=per_request_v3). Widget subscriptions can have a fixed base
    item plus a metered overage item; select by `recurring.usage_type` and
    prefer an item labelled "overage" when present. Result is cached for the
    process lifetime; on Stripe POST failure the cache is cleared so a stale
    item id can heal on the next backfill attempt.

    Returns None on any error; the caller logs and skips.
    """
    if not subscription_id:
        return None
    _configure_stripe()
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        items = _stripe_path(sub, "items", "data") or []
        if not items:
            return None
        selected = _select_subscription_item(list(items))
        if selected is None:
            logger.warning(
                "sub_item lookup found no metered item sub=%s items=%d",
                subscription_id,
                len(items),
            )
            return None
        item_id = _stripe_value(selected, "id")
        return str(item_id) if item_id else None
    except Exception:
        logger.warning("sub_item lookup failed sub=%s", subscription_id, exc_info=True)
        return None


def _clear_subscription_item_cache() -> None:
    cache_clear = getattr(_get_subscription_item_id, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


def _mark_synced(usage_event_id: int, stripe_record_id: str) -> bool:
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
                "UPDATE usage_events SET stripe_record_id = ?, stripe_synced_at = ? WHERE id = ?",
                (
                    stripe_record_id,
                    datetime.now(UTC).isoformat(),
                    usage_event_id,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "usage_events sync mark failed event_id=%s record=%s",
            usage_event_id,
            stripe_record_id,
            exc_info=True,
        )
        return False


def _report_sync(
    subscription_id: str,
    quantity: int = 1,
    usage_event_id: int | None = None,
    *,
    idempotency_key: str | None = None,
    raise_on_failure: bool = False,
) -> bool:
    """Synchronous inner body — always called from a daemon thread.

    On success, if `usage_event_id` was supplied, the local
    `usage_events` row is updated with `stripe_record_id` + `stripe_synced_at`.
    On failure, the row is left NULL so a future reconciliation pass can
    retry (audit a37f6226fe319dc40).
    """
    if not settings.stripe_secret_key:
        if raise_on_failure:
            raise UsageReportError("stripe secret key is not configured")
        return False
    si_id = _get_subscription_item_id(subscription_id)
    if not si_id:
        _clear_subscription_item_cache()
        if raise_on_failure:
            raise UsageReportError(f"metered subscription item not found for {subscription_id}")
        return False
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
    if idempotency_key is not None:
        idem_key = idempotency_key
    elif usage_event_id is not None:
        idem_key = f"usage_{usage_event_id}"
    else:
        idem_key = f"usage_{subscription_id}_{int(datetime.now(UTC).timestamp())}"
    try:
        record = stripe.SubscriptionItem.create_usage_record(  # legacy API, pinned to stripe-api-version 2024-11-20.acacia where usage_records still exists
            si_id,
            quantity=quantity,
            timestamp=int(datetime.now(UTC).timestamp()),
            action="increment",
            idempotency_key=idem_key,
        )
    except Exception as err:
        logger.warning(
            "usage_record POST failed sub=%s si=%s", subscription_id, si_id, exc_info=True
        )
        _clear_subscription_item_cache()
        if raise_on_failure:
            raise UsageReportError("stripe usage_record POST failed") from err
        return False
    if usage_event_id is None:
        return True
    record_id = None
    try:
        record_id = record.get("id") if isinstance(record, dict) else getattr(record, "id", None)
    except Exception:
        record_id = None
    if record_id and _mark_synced(usage_event_id, record_id):
        return True
    if raise_on_failure:
        raise UsageReportError("stripe usage_record created but local sync mark failed")
    return False


def report_usage_async(
    subscription_id: str | None,
    quantity: int = 1,
    usage_event_id: int | None = None,
    idempotency_key: str | None = None,
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
        kwargs={"idempotency_key": idempotency_key},
        daemon=True,
        name="stripe-usage",
    )
    t.start()


__all__ = ["report_usage_async", "UsageReportError"]
