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
from datetime import UTC, datetime, timedelta
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
    # `key_last4` is captured at issuance so dunning / rotation notices
    # can render a key-fragment without retaining the raw key. Last-4 is
    # NOT a credential — it identifies, not authenticates.
    key_last4 = raw[-4:] if raw else None
    conn.execute(
        """INSERT INTO api_keys(
               key_hash, customer_id, tier, stripe_subscription_id,
               created_at, key_hash_bcrypt, key_last4
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            key_hash,
            customer_id,
            tier,
            stripe_subscription_id,
            now,
            bcrypt_hash,
            key_last4,
        ),
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


def issue_trial_key(
    conn: sqlite3.Connection,
    *,
    trial_email: str,
    duration_days: int = 14,
    request_cap: int = 200,
) -> tuple[str, str]:
    """Issue a tier='trial' API key from the email-only signup flow.

    Mirrors `issue_key` but skips the Stripe linkage entirely — trial keys
    have NO `customer_id`, NO `stripe_subscription_id`, NO Stripe usage
    records ever recorded against them. Returns (raw_key, key_hash) so the
    caller can:
      - hand the raw_key to the magic-link landing page (one-time reveal,
        same posture as success.html for paid keys);
      - persist the key_hash on the trial_signups row for forensic pairing.

    The trial state is bound on the api_keys row itself (not in a sidecar
    table) so the existing require_key / quota / cap middleware sees it
    naturally:

      - tier='trial' is treated as non-metered by `_enforce_quota` and
        `ApiContext.metered` (those check `tier == 'paid'` for metered
        flag); no Stripe usage_records are produced.
      - `monthly_cap_yen = request_cap * 3` (¥600 by default for 200
        requests at ¥3/req) gives the existing CustomerCapMiddleware a
        hard cap so a trial caller cannot somehow accrue billable spend
        even if a future code path tried to bill them.
      - `trial_expires_at` is set 14 days out; the daily
        `scripts/cron/expire_trials.py` revokes any tier='trial' row
        whose `trial_expires_at <= now()` OR `trial_requests_used >=
        request_cap` so the key dies hard at the deadline.

    Onboarding emails: we DO NOT call `enqueue_onboarding_sequence` here
    because the existing D+0 / D+1 / ... templates assume a paid Stripe
    customer. The trial sequence (welcome + day-11 nudge) is fired from
    `api/signup.py` after this function returns, using the new
    `onboarding-trial-day-0` / `onboarding-trial-day-11` templates.

    bcrypt dual-path: same as `issue_key`. Trial keys carry both the
    HMAC PRIMARY KEY hash AND a bcrypt hash so an exfil cannot brute
    them faster than legacy keys.
    """
    raw, key_hash = generate_api_key()
    bcrypt_hash = hash_api_key_bcrypt(raw)
    now = datetime.now(UTC)
    started_at = now.isoformat()
    expires_at = (now + timedelta(days=duration_days)).isoformat()
    cap_yen = max(0, int(request_cap) * 3)
    conn.execute(
        """INSERT INTO api_keys(
               key_hash, customer_id, tier, stripe_subscription_id,
               created_at, key_hash_bcrypt, monthly_cap_yen,
               trial_email, trial_started_at, trial_expires_at,
               trial_requests_used
           ) VALUES (?, NULL, 'trial', NULL, ?, ?, ?, ?, ?, ?, 0)""",
        (key_hash, started_at, bcrypt_hash, cap_yen,
         trial_email, started_at, expires_at),
    )

    # Structured event for weekly digest + SLO panel. Tier carries 'trial'
    # so the funnel dashboard can split out conversion to paid.
    try:
        _event_log.info(
            json.dumps(
                {
                    "event": "key.issued",
                    "tier": "trial",
                    "key_hash_prefix": key_hash[:8],
                    "has_subscription": False,
                    "has_email": True,
                    "issued_at": started_at,
                    "trial_expires_at": expires_at,
                }
            )
        )
    except Exception:
        pass
    return raw, key_hash


def revoke_key(conn: sqlite3.Connection, key_hash: str) -> bool:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ? AND revoked_at IS NULL",
        (now, key_hash),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Migration 086: Sub-API-key parent/child fan-out (SaaS B2B)
# ---------------------------------------------------------------------------
# A SaaS partner wiring AutonoMath into their own multi-tenant product can
# issue up to 1,000 child keys per parent. Children inherit the parent's
# tier, monthly_cap_yen, and stripe_subscription_id — Stripe sees ONE
# subscription regardless of how many children fan out. The cap is
# enforced at TREE scope (parent + all siblings) so a partner cannot
# bypass the cap by spreading traffic across child keys.

# Anti-abuse cap on the parent->children fan-out. 1,000 is the documented
# upper bound; the constant is module-level so tests can monkeypatch it
# down to e.g. 5 for fast suite runs.
MAX_CHILDREN_PER_PARENT = 1000

# Free-text label upper bound. Prevents pathological multi-MB labels from
# blowing up dashboards and CSV exports. 64 chars is comfortable for human
# identifiers like "customer_acme_prod_apac".
MAX_LABEL_LEN = 64


class ChildKeyError(ValueError):
    """Raised when a child-key issuance / revoke violates a constraint.

    Distinct from generic ValueError so callers (REST handlers) can map
    it to a 4xx envelope rather than a 500. Carries an `error_code` so
    the canonical error envelope can surface a machine-readable code.
    """

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _validate_label(label: str | None) -> str:
    """Return the cleaned label, or raise ChildKeyError on invalid input.

    Rules:
      * non-empty after strip()
      * length <= MAX_LABEL_LEN
      * must NOT contain newlines or control chars (so it survives CSV
        export without escaping nightmares)
    """
    if not label:
        raise ChildKeyError("label is required", "label_missing")
    cleaned = label.strip()
    if not cleaned:
        raise ChildKeyError("label is required", "label_missing")
    if len(cleaned) > MAX_LABEL_LEN:
        raise ChildKeyError(
            f"label exceeds {MAX_LABEL_LEN} chars", "label_too_long"
        )
    if any(ch in cleaned for ch in ("\n", "\r", "\t", "\0")):
        raise ChildKeyError(
            "label must not contain control characters", "label_invalid"
        )
    return cleaned


def issue_child_key(
    conn: sqlite3.Connection,
    *,
    parent_key_hash: str,
    label: str,
) -> tuple[str, str]:
    """Issue a child API key under an existing parent. Returns (raw, key_hash).

    The child inherits the parent's tier, monthly_cap_yen, and
    stripe_subscription_id verbatim — Stripe sees only the parent
    subscription; child keys are invisible to Stripe billing.

    Constraints enforced server-side:
      * parent must exist + not be revoked
      * parent must NOT itself be a child (no grandchildren — flat tree)
      * label must validate (see _validate_label)
      * parent must have < MAX_CHILDREN_PER_PARENT active children

    Raises ChildKeyError on any constraint violation; the REST layer
    maps the error_code into the canonical 4xx envelope.
    """
    cleaned_label = _validate_label(label)

    parent = conn.execute(
        "SELECT id, customer_id, tier, stripe_subscription_id, "
        "monthly_cap_yen, parent_key_id, revoked_at "
        "FROM api_keys WHERE key_hash = ?",
        (parent_key_hash,),
    ).fetchone()
    if parent is None:
        raise ChildKeyError("parent key not found", "parent_not_found")
    if parent["revoked_at"]:
        raise ChildKeyError("parent key revoked", "parent_revoked")

    parent_keys = parent.keys() if hasattr(parent, "keys") else []
    parent_id = parent["id"] if "id" in parent_keys else None
    parent_parent = parent["parent_key_id"] if "parent_key_id" in parent_keys else None
    if parent_parent is not None:
        # The parent is itself a child — flat tree only, refuse to nest.
        raise ChildKeyError(
            "child keys cannot spawn grandchildren", "nesting_forbidden"
        )
    if parent_id is None:
        # Legacy parent row that pre-dates migration 086 — backfill its
        # id from rowid so the FK + tree-aggregation query both work.
        conn.execute(
            "UPDATE api_keys SET id = rowid WHERE key_hash = ? AND id IS NULL",
            (parent_key_hash,),
        )
        parent = conn.execute(
            "SELECT id FROM api_keys WHERE key_hash = ?",
            (parent_key_hash,),
        ).fetchone()
        parent_id = parent["id"]

    # Anti-abuse: count NON-revoked children only — a revoked sibling
    # frees up a slot for a fresh child. Active siblings consume slots.
    (active_children,) = conn.execute(
        "SELECT COUNT(*) FROM api_keys "
        "WHERE parent_key_id = ? AND revoked_at IS NULL",
        (parent_id,),
    ).fetchone()
    if int(active_children) >= MAX_CHILDREN_PER_PARENT:
        raise ChildKeyError(
            f"parent already has {MAX_CHILDREN_PER_PARENT} active children",
            "child_cap_exceeded",
        )

    raw, key_hash = generate_api_key()
    bcrypt_hash = hash_api_key_bcrypt(raw)
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO api_keys(
               key_hash, customer_id, tier, stripe_subscription_id,
               created_at, key_hash_bcrypt, monthly_cap_yen,
               parent_key_id, label
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            key_hash,
            parent["customer_id"],
            parent["tier"],
            parent["stripe_subscription_id"],
            now,
            bcrypt_hash,
            parent["monthly_cap_yen"],
            parent_id,
            cleaned_label,
        ),
    )
    # Mirror rowid into id so any future FK / tree-aggregation query
    # against this child row resolves correctly.
    conn.execute(
        "UPDATE api_keys SET id = ? WHERE rowid = ? AND id IS NULL",
        (cur.lastrowid, cur.lastrowid),
    )

    # Structured event for weekly digest + SLO panel. Mirrors the issue_key
    # event channel so dashboards can split out fan-out volume.
    try:
        _event_log.info(
            json.dumps(
                {
                    "event": "key.issued",
                    "tier": parent["tier"],
                    "key_hash_prefix": key_hash[:8],
                    "has_subscription": bool(parent["stripe_subscription_id"]),
                    "has_email": False,
                    "issued_at": now,
                    "is_child": True,
                    "parent_key_hash_prefix": parent_key_hash[:8],
                    "label": cleaned_label,
                }
            )
        )
    except Exception:
        pass

    return raw, key_hash


def list_children(
    conn: sqlite3.Connection,
    *,
    parent_key_hash: str,
    include_revoked: bool = False,
) -> list[dict]:
    """Return rows for every child of `parent_key_hash`.

    Each dict contains: id, label, key_hash_prefix (first 8 chars only —
    raw keys are NEVER returned post-issuance), created_at, revoked_at,
    last_used_at. Sorted ASC by id so dashboards render in issuance
    order.

    Returns empty list when parent_key_hash is unknown or has no children
    (NEVER raises — the read path is harmless).
    """
    parent = conn.execute(
        "SELECT id FROM api_keys WHERE key_hash = ?",
        (parent_key_hash,),
    ).fetchone()
    if parent is None:
        return []
    parent_keys = parent.keys() if hasattr(parent, "keys") else []
    parent_id = parent["id"] if "id" in parent_keys else None
    if parent_id is None:
        return []

    sql = (
        "SELECT id, key_hash, label, created_at, revoked_at, last_used_at "
        "FROM api_keys WHERE parent_key_id = ? "
    )
    params: list[object] = [parent_id]
    if not include_revoked:
        sql += "AND revoked_at IS NULL "
    sql += "ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()

    out: list[dict] = []
    for r in rows:
        rk = r.keys() if hasattr(r, "keys") else []
        out.append(
            {
                "id": r["id"] if "id" in rk else None,
                "label": r["label"] if "label" in rk else None,
                "key_hash_prefix": (r["key_hash"] or "")[:8],
                "created_at": r["created_at"] if "created_at" in rk else None,
                "revoked_at": r["revoked_at"] if "revoked_at" in rk else None,
                "last_used_at": r["last_used_at"] if "last_used_at" in rk else None,
            }
        )
    return out


def revoke_child_by_id(
    conn: sqlite3.Connection,
    *,
    parent_key_hash: str,
    child_id: int,
) -> bool:
    """Revoke a single child by its api_keys.id, scoped to the given parent.

    The parent_key_hash gate is critical: without it any caller could
    revoke any child by guessing rowids. We resolve the parent's id
    from its key_hash and require the child's parent_key_id to match,
    so a stolen child id alone is insufficient.

    Returns True if a row was actually revoked. False if the child was
    already revoked, doesn't exist, or doesn't belong to this parent.
    """
    parent = conn.execute(
        "SELECT id FROM api_keys WHERE key_hash = ?",
        (parent_key_hash,),
    ).fetchone()
    if parent is None:
        return False
    parent_keys = parent.keys() if hasattr(parent, "keys") else []
    parent_id = parent["id"] if "id" in parent_keys else None
    if parent_id is None:
        return False
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE api_keys SET revoked_at = ? "
        "WHERE id = ? AND parent_key_id = ? AND revoked_at IS NULL",
        (now, child_id, parent_id),
    )
    return cur.rowcount > 0


def revoke_key_tree(
    conn: sqlite3.Connection, parent_key_hash: str
) -> int:
    """Cascade-revoke a parent + every active child below it.

    Returns the total number of rows flipped to revoked_at. Used by
    Stripe webhook on subscription.deleted (parent dies → all children
    die together) so a SaaS partner cannot continue serving traffic
    against children of a canceled subscription.

    Idempotent: rows already revoked are not touched (UPDATE ... WHERE
    revoked_at IS NULL).
    """
    parent = conn.execute(
        "SELECT id FROM api_keys WHERE key_hash = ?",
        (parent_key_hash,),
    ).fetchone()
    if parent is None:
        return 0
    parent_keys = parent.keys() if hasattr(parent, "keys") else []
    parent_id = parent["id"] if "id" in parent_keys else None
    now = datetime.now(UTC).isoformat()
    total = 0
    if parent_id is not None:
        cur = conn.execute(
            "UPDATE api_keys SET revoked_at = ? "
            "WHERE parent_key_id = ? AND revoked_at IS NULL",
            (now, parent_id),
        )
        total += cur.rowcount
    cur = conn.execute(
        "UPDATE api_keys SET revoked_at = ? "
        "WHERE key_hash = ? AND revoked_at IS NULL",
        (now, parent_key_hash),
    )
    total += cur.rowcount
    return total


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
    "ChildKeyError",
    "MAX_CHILDREN_PER_PARENT",
    "MAX_LABEL_LEN",
    "generate_api_key",
    "hash_api_key",
    "issue_child_key",
    "issue_key",
    "issue_trial_key",
    "list_children",
    "resolve_tier_from_price",
    "revoke_child_by_id",
    "revoke_key",
    "revoke_key_tree",
    "revoke_subscription",
    "update_subscription_status",
    "update_subscription_status_by_id",
    "update_tier_by_subscription",
]
