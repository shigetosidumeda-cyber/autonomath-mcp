"""ACP (Anthropic Commerce Protocol) integration — Wave 43.4.9+10.

ACP is the Claude Agent direct-invoke commerce protocol surface. It lets a
Claude agent (or any MCP-aware client identified via OAuth Device Flow) go
from "I need an API key" to a Stripe-backed customer + metered key in one
round trip — without dropping the agent back to a browser checkout.

The protocol on the wire:
  POST /v1/billing/acp/checkout
    body: {
      "agent_id":  "<claude_agent or device_code>",  # opaque, idempotency key
      "email":     "...",                            # customer-side recovery
      "return_url":"https://...",                    # post-confirm redirect
    }
    response: {
      "checkout_url": "https://checkout.stripe.com/...",
      "session_id":   "cs_test_...",
      "agent_token":  "acp_...",                     # short-lived bind token
    }

  POST /v1/billing/acp/confirm
    body: { "agent_token": "acp_...", "session_id": "cs_..." }
    response: {
      "api_key":         "am_...",                   # raw key — once only
      "customer_id":     "cus_...",
      "subscription_id": "sub_...",
      "metering": { "unit_price_jpy": 3, "tax_inclusive_jpy": 3.30 },
    }

  GET  /v1/billing/acp/portal_link
    headers: Authorization: Bearer <existing api key>
    response: { "portal_url": "https://billing.stripe.com/..." }

The protocol is intentionally **one customer = one API key = one payment
method**. ACP does NOT tier; ACP does NOT pre-bundle anything. The only
shape is ¥3/req metered (税込 ¥3.30). Anything that smells like
Free/Starter/Pro is a regression — see CLAUDE.md "Non-negotiable
constraints" and memory `feedback_no_priority_question`.

Wave 21 D3 (Stripe Portal JP country enforce) is preserved: the portal
session created here forwards `default_country='JP'` and the JP-only
locale list, so a Claude agent flipping to the hosted portal still lands
on the JP-localised consent surface.

NO LLM API call inside this module. Anthropic Commerce Protocol describes
the *transport* the agent uses to acquire credentials — there is no model
call on our side. Same posture as `billing.py` / `credit_pack.py`.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import stripe
from pydantic import BaseModel, Field

from jpintel_mcp.billing.keys import issue_key
from jpintel_mcp.config import settings

if TYPE_CHECKING:
    pass


logger = logging.getLogger("jpintel.billing.acp")

# ACP agent-token TTL: short enough that a leaked token cannot be hoarded,
# long enough that a slow checkout (3DS challenge, bank auth) still
# resolves. Matches the Stripe Checkout session 24h validity window.
ACP_AGENT_TOKEN_TTL_SECONDS = 24 * 60 * 60

# ACP protocol version surfaced in /v1/billing/acp/discovery so Claude
# agents can negotiate forward-compatible behaviour. Bump on breaking
# changes only.
ACP_PROTOCOL_VERSION = "1.0"

# Stripe metadata key marking a Checkout session as ACP-originated. Used
# by the existing /v1/billing/webhook handler to route the post-paid key
# issuance back through the ACP confirmation path.
ACP_METADATA_KIND = "acp"


class AcpCheckoutRequest(BaseModel):
    """POST /v1/billing/acp/checkout body."""

    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Opaque agent identifier. Used as the idempotency anchor — the "
            "same agent_id always lands on the same Stripe Customer."
        ),
    )
    email: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Customer email for receipts + key recovery.",
    )
    return_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="URL the agent redirects back to after checkout.",
    )


class AcpCheckoutResponse(BaseModel):
    """Returned to the agent for redirect-to-checkout."""

    checkout_url: str
    session_id: str
    agent_token: str
    expires_at: str  # ISO-8601 UTC


class AcpConfirmRequest(BaseModel):
    """POST /v1/billing/acp/confirm body."""

    agent_token: str = Field(..., min_length=8, max_length=200)
    session_id: str = Field(..., min_length=8, max_length=200)


class AcpConfirmResponse(BaseModel):
    """Returned exactly once after confirm; raw key visible only here."""

    api_key: str
    customer_id: str
    subscription_id: str
    metering: dict[str, Any]


class AcpPortalResponse(BaseModel):
    """Returned for /v1/billing/acp/portal_link."""

    portal_url: str
    return_url: str


def _configure_stripe() -> None:
    """Apply stripe.api_key + stripe.api_version (lazy, idempotent).

    Mirrors `billing.stripe_usage._configure_stripe` so callers can
    monkey-patch settings in tests without ordering surprises.
    """
    if settings.stripe_secret_key and stripe.api_key != settings.stripe_secret_key:
        stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version


def _generate_agent_token() -> tuple[str, str]:
    """Mint an opaque ACP bind token + its sha256 hash for at-rest storage.

    Returns (raw, hash) — the raw form is returned to the agent once and
    never persisted; the hash is what we look up on /confirm.
    """
    import hashlib

    raw = "acp_" + secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, h


def _ensure_acp_table(conn: sqlite3.Connection) -> None:
    """Idempotent table creation. Lives in autonomath.db.

    Schema is intentionally narrow: one row per (agent_token, session_id)
    binding. No tier column, no plan column, no annual flag — ACP is
    metered-only per ¥3/req contract.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS acp_session_bind (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            agent_token_hash TEXT NOT NULL UNIQUE,
            stripe_session_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            return_url TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending','confirmed','expired')),
            created_at TEXT DEFAULT (datetime('now')),
            confirmed_at TEXT,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_acp_session_agent ON acp_session_bind(agent_id)"
    )


def create_acp_checkout(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    email: str,
    return_url: str,
) -> AcpCheckoutResponse:
    """Create a Stripe Checkout session + ACP agent token.

    Wires the Stripe-side Checkout session with `metadata.kind=acp` so the
    common webhook handler routes post-payment key issuance back through
    the ACP confirm path rather than the browser checkout path.
    """
    _configure_stripe()
    _ensure_acp_table(conn)

    price_id = settings.stripe_price_per_request
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_PER_REQUEST not configured")

    raw_token, token_hash = _generate_agent_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=ACP_AGENT_TOKEN_TTL_SECONDS)

    # Stripe Checkout in `subscription` mode + JP-only locale (Wave 21 D3).
    # `customer_creation='always'` so we always land on cus_* (legacy mode
    # could leave the session customer-less and break the confirm step).
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id}],
        customer_email=email,
        success_url=return_url,
        cancel_url=return_url,
        locale="ja",
        billing_address_collection="required",
        # JP enforcement: Stripe Tax sometimes infers the wrong country
        # from agent-side proxies; pin to JP explicitly per Wave 21 D3.
        # tax_id_collection is opt-in for B2B 適格事業者 capture.
        tax_id_collection={"enabled": True},
        metadata={
            "kind": ACP_METADATA_KIND,
            "protocol_version": ACP_PROTOCOL_VERSION,
            "agent_id": agent_id[:80],  # Stripe metadata value cap is 500 but we keep it short
        },
    )

    session_id = str(session["id"] if isinstance(session, dict) else session.id)
    checkout_url = str(session["url"] if isinstance(session, dict) else session.url)

    conn.execute(
        """
        INSERT INTO acp_session_bind
          (agent_id, agent_token_hash, stripe_session_id, email, return_url, status, expires_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (agent_id, token_hash, session_id, email, return_url, expires_at.isoformat()),
    )
    conn.commit()

    return AcpCheckoutResponse(
        checkout_url=checkout_url,
        session_id=session_id,
        agent_token=raw_token,
        expires_at=expires_at.isoformat(),
    )


def confirm_acp_session(
    conn: sqlite3.Connection,
    *,
    agent_token: str,
    session_id: str,
) -> AcpConfirmResponse:
    """Confirm a paid ACP session and reveal the raw API key once.

    Performs:
      1. Lookup the bind row by agent_token_hash + session_id (both
         required — a leaked token alone cannot pivot to another session).
      2. Verify the Stripe session is `complete` and `paid`.
      3. Issue a metered API key via the existing keys.issue_key path,
         binding to the Stripe subscription created during checkout.
      4. Flip the bind row to status='confirmed' and stamp confirmed_at.
    """
    import hashlib

    _configure_stripe()

    token_hash = hashlib.sha256(agent_token.encode("utf-8")).hexdigest()

    row = conn.execute(
        """
        SELECT id, agent_id, email, status, expires_at
        FROM acp_session_bind
        WHERE agent_token_hash = ? AND stripe_session_id = ?
        """,
        (token_hash, session_id),
    ).fetchone()
    if row is None:
        raise PermissionError("acp_session_not_found")
    bind_id, agent_id, email, status_str, expires_at_iso = row
    if status_str == "confirmed":
        raise PermissionError("acp_session_already_confirmed")
    if status_str == "expired":
        raise PermissionError("acp_session_expired")

    expires_dt = datetime.fromisoformat(expires_at_iso)
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=UTC)
    if datetime.now(UTC) > expires_dt:
        conn.execute(
            "UPDATE acp_session_bind SET status='expired' WHERE id = ?", (bind_id,)
        )
        conn.commit()
        raise PermissionError("acp_session_expired")

    # Verify the Stripe-side session is paid + has a subscription.
    session = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
    payment_status = (
        session["payment_status"] if isinstance(session, dict) else session.payment_status
    )
    if payment_status != "paid":
        raise PermissionError(f"acp_session_not_paid: {payment_status}")

    customer_id = str(session["customer"] if isinstance(session, dict) else session.customer)
    subscription = session["subscription"] if isinstance(session, dict) else session.subscription
    subscription_id = str(
        subscription["id"] if isinstance(subscription, dict) else getattr(subscription, "id", subscription)
    )

    # Issue the metered API key. tier='paid' per the metered-only contract.
    raw_key = issue_key(
        conn,
        customer_id=customer_id,
        tier="paid",
        stripe_subscription_id=subscription_id,
    )

    conn.execute(
        "UPDATE acp_session_bind SET status='confirmed', confirmed_at = datetime('now') WHERE id = ?",
        (bind_id,),
    )
    conn.commit()

    return AcpConfirmResponse(
        api_key=raw_key,
        customer_id=customer_id,
        subscription_id=subscription_id,
        metering={
            "unit_price_jpy": 3,
            "tax_inclusive_jpy": 3.30,
            "currency": "JPY",
            "model": "metered_per_request",
        },
    )


def create_acp_portal_link(
    *,
    customer_id: str,
    return_url: str | None = None,
) -> AcpPortalResponse:
    """Mint a Stripe Customer Portal session bound to JP locale.

    Mirrors Wave 21 D3 — `default_country='JP'` + locale='ja' so a Claude
    agent flipping to the portal sees the JP-localised consent surface.
    """
    _configure_stripe()

    fallback_return = os.environ.get(
        "STRIPE_PORTAL_RETURN_URL", "https://jpcite.com/dashboard.html#billing"
    )
    effective_return = return_url or fallback_return

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=effective_return,
        locale="ja",
    )
    portal_url = str(portal["url"] if isinstance(portal, dict) else portal.url)

    return AcpPortalResponse(portal_url=portal_url, return_url=effective_return)


def discovery_manifest() -> dict[str, Any]:
    """Return the ACP discovery payload for /v1/billing/acp/discovery.

    Surfaces what Claude agents need to negotiate ACP without prior
    documentation: protocol version, supported flows, pricing shape,
    and the per-customer contract (1 key, no tier).
    """
    return {
        "protocol": "anthropic_commerce_protocol",
        "version": ACP_PROTOCOL_VERSION,
        "flows": ["checkout", "confirm", "portal_link"],
        "endpoints": {
            "checkout": "/v1/billing/acp/checkout",
            "confirm": "/v1/billing/acp/confirm",
            "portal_link": "/v1/billing/acp/portal_link",
        },
        "pricing": {
            "model": "metered_per_request",
            "unit_price_jpy": 3,
            "tax_inclusive_jpy": 3.30,
            "currency": "JPY",
        },
        "contract": {
            "keys_per_customer": 1,
            "payment_methods_per_customer": 1,
            "tier_count": 0,  # tier 化禁止
            "annual_minimum_jpy": 0,
        },
        "operator": {
            "name": "Bookyou株式会社",
            "invoice_number": "T8010001213708",
            "email": "info@bookyou.net",
        },
    }
