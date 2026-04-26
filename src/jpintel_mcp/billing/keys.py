"""API key issuance + Stripe-linked lifecycle.

Self-serve flow:
  1. Customer subscribes via Stripe Checkout / Customer Portal
  2. webhook.invoice.paid -> create api_keys row
  3. Customer retrieves raw key via /billing/key/rotate (returns once, only to
     authenticated Stripe customer_id via Stripe session token)

We never store raw keys. SHA256-HMAC with salt.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jpintel_mcp.api.deps import generate_api_key, hash_api_key, hash_api_key_bcrypt

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger("jpintel.billing.keys")

# Per-event structured log channel. Used by weekly digest + SLO conformance
# for "new keys issued / 24h" panel (B2 in observability_dashboard.md).
# Carries no PII: only key_hash 8-char prefix (already canonical in
# api/logging_config.bind_api_key_context) plus tier + sub presence flag.
_event_log = logging.getLogger("autonomath.keys")


def resolve_tier_from_price(price_id: str) -> str:
    from jpintel_mcp.config import settings

    if price_id and price_id == settings.stripe_price_per_request:
        return "paid"
    return "free"


def issue_key(
    conn: sqlite3.Connection,
    customer_id: str,
    tier: str,
    stripe_subscription_id: str | None = None,
    customer_email: str | None = None,
) -> str:
    """Create a new API key, return the raw key ONCE.

    Existing keys for this customer are kept active so rotation is safe — the
    caller can revoke old ones explicitly.

    When `customer_email` is supplied we also enqueue the D+3 / D+7 / D+14 /
    D+30 onboarding sequence into `email_schedule`. The enqueue is wrapped in
    a best-effort try/except so any scheduler bug cannot 500 the Stripe
    webhook — the welcome mail fires independently and is the only mail the
    customer actually needs to receive before their first invoice.
    """
    raw, key_hash = generate_api_key()
    # bcrypt dual-path (Wave 16 P1, migration 073). New keys carry BOTH the
    # legacy HMAC `key_hash` (PRIMARY KEY → O(log n) lookup) and a bcrypt
    # `key_hash_bcrypt` for defense-in-depth against an exfiltrated DB.
    # Verify path in api/deps.require_key checks bcrypt when present and
    # falls through to legacy HMAC-only when NULL.
    bcrypt_hash = hash_api_key_bcrypt(raw)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO api_keys(
               key_hash, customer_id, tier, stripe_subscription_id,
               created_at, key_hash_bcrypt
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (key_hash, customer_id, tier, stripe_subscription_id, now, bcrypt_hash),
    )

    if customer_email:
        # Import locally so a circular import between billing.keys and
        # email.scheduler cannot happen (scheduler imports onboarding which
        # imports postmark which imports config — billing.keys is outside
        # that cycle by design).
        try:
            from jpintel_mcp.email.scheduler import enqueue_onboarding_sequence

            enqueue_onboarding_sequence(
                conn,
                api_key_id=key_hash,
                email=customer_email,
            )
        except Exception:
            # Never let a scheduler enqueue failure kill key issuance —
            # the welcome mail is still sent by the caller regardless.
            logger.warning(
                "enqueue_onboarding_sequence failed sub=%s",
                stripe_subscription_id,
                exc_info=True,
            )

    # Structured event for weekly digest + SLO panel. NEVER raises into
    # the webhook handler — telemetry is best-effort. No raw key, no
    # email; key_hash prefix matches the contextvar binding format.
    try:
        _event_log.info(
            json.dumps(
                {
                    "event": "key.issued",
                    "tier": tier,
                    "key_hash_prefix": key_hash[:8],
                    "has_subscription": bool(stripe_subscription_id),
                    "has_email": bool(customer_email),
                    "issued_at": now,
                }
            )
        )
    except Exception:
        pass
    return raw


def revoke_key(conn: sqlite3.Connection, key_hash: str) -> bool:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ? AND revoked_at IS NULL",
        (now, key_hash),
    )
    return cur.rowcount > 0


def revoke_subscription(conn: sqlite3.Connection, stripe_subscription_id: str) -> int:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """UPDATE api_keys SET revoked_at = ?
           WHERE stripe_subscription_id = ? AND revoked_at IS NULL""",
        (now, stripe_subscription_id),
    )
    return cur.rowcount


def update_tier_by_subscription(
    conn: sqlite3.Connection, stripe_subscription_id: str, tier: str
) -> int:
    cur = conn.execute(
        "UPDATE api_keys SET tier = ? WHERE stripe_subscription_id = ? AND revoked_at IS NULL",
        (tier, stripe_subscription_id),
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Stripe subscription state cache (migration 052)
# ---------------------------------------------------------------------------
# These functions write to the api_keys.stripe_subscription_* columns added
# by migration 052. They are called from the Stripe webhook handler in
# api/billing.py on subscription.created / .updated / .deleted /
# invoice.payment_failed / invoice.paid so that /v1/me can return the cached
# state without calling Stripe live on every dashboard load.


def update_subscription_status(
    conn: sqlite3.Connection,
    stripe_subscription_id: str,
    *,
    status: str,
    current_period_end: int | None = None,
    cancel_at_period_end: bool | None = None,
) -> int:
    """Write the cached subscription state for a subscription_id.

    Updates ALL non-revoked api_keys rows that share the subscription
    (revoked rows are intentionally skipped — a refunded / canceled key
    should not have its dunning state mutated).

    Returns the number of rows affected. 0 is normal during the brief
    window between Checkout completion and the webhook that issues the key
    (Stripe sometimes delivers `subscription.updated` immediately after
    `subscription.created` if Tax recalculates).

    `current_period_end` and `cancel_at_period_end` are optional because
    `invoice.payment_failed` / `invoice.paid` only carry the status; the
    period end + cancel flag come from `subscription.created` / `.updated`
    payloads.
    """
    now_epoch = int(datetime.now(UTC).timestamp())
    sets: list[str] = [
        "stripe_subscription_status = ?",
        "stripe_subscription_status_at = ?",
    ]
    params: list[object] = [status, now_epoch]
    if current_period_end is not None:
        sets.append("stripe_subscription_current_period_end = ?")
        params.append(int(current_period_end))
    if cancel_at_period_end is not None:
        sets.append("stripe_subscription_cancel_at_period_end = ?")
        params.append(1 if cancel_at_period_end else 0)
    params.append(stripe_subscription_id)
    cur = conn.execute(
        f"UPDATE api_keys SET {', '.join(sets)} "  # noqa: S608 — column list is static
        f"WHERE stripe_subscription_id = ? AND revoked_at IS NULL",
        params,
    )
    return cur.rowcount


def update_subscription_status_by_id(
    conn: sqlite3.Connection,
    stripe_subscription_id: str,
    status: str,
) -> int:
    """Convenience wrapper: status-only update (no period_end / cancel_flag).

    Used from invoice.payment_failed where the payload does not carry the
    full Subscription object.
    """
    return update_subscription_status(
        conn, stripe_subscription_id, status=status
    )


__all__ = [
    "generate_api_key",
    "hash_api_key",
    "issue_key",
    "revoke_key",
    "revoke_subscription",
    "update_subscription_status",
    "update_subscription_status_by_id",
    "update_tier_by_subscription",
    "resolve_tier_from_price",
]
