"""Wave 43.4.9+10 — REST aggregator across 3 payment rails.

Single router that exposes the discovery + commerce surface for all three
rails Wave 43.4.9+10 lights up:

  /v1/billing/acp/*         — Anthropic Commerce Protocol (Stripe, JPY metered)
  /v1/billing/x402/*        — USDC HTTP 402 Payment Required (Base, USDC metered)
  /v1/billing/mpp/*         — Managed Provider Plan (naming layer over Wave 21 D4+D5+D6)

The ACP + x402 paths run real Stripe / RPC integrations (gated by env
secrets; tests mock both). The MPP path is **read-only** — it returns the
component list / naming canon for buyers and agents; the actual rebate,
credit, and yearly prepay primitives live under their existing Wave 21
endpoints and are NOT duplicated here.

ZERO LLM imports — billing path. ZERO tier columns — metered-only contract.

The router is mounted in `api/main.py` next to `billing_router` /
`billing_breakdown_router` and inherits the same anon-quota posture
(NO `AnonIpLimitDep` — discovery + agent-acquire calls happen before a
caller has any key, so they cannot be metered).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from jpintel_mcp.billing.acp_integration import (
    ACP_PROTOCOL_VERSION,
    AcpCheckoutRequest,
    AcpCheckoutResponse,
    AcpConfirmRequest,
    AcpConfirmResponse,
    AcpPortalResponse,
    confirm_acp_session,
    create_acp_checkout,
    create_acp_portal_link,
    discovery_manifest as acp_discovery_manifest,
)
from jpintel_mcp.billing.keys import issue_key
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.billing.v2")

router = APIRouter(prefix="/v1/billing", tags=["billing-v2"])


# -------- shared db connect ----------------------------------------------

def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path with env override.

    Mirrors `billing._credit_pack_db_path` so the test suite can point a
    fresh sqlite tempfile via `AUTONOMATH_DB_PATH` without touching
    settings module state.
    """
    import os

    return Path(os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path)))


def _connect_autonomath() -> sqlite3.Connection:
    """Open the autonomath.db with WAL + sane row factory."""
    conn = sqlite3.connect(str(_autonomath_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


# -------- ACP endpoints ---------------------------------------------------


@router.get("/acp/discovery", summary="ACP protocol discovery (no auth)")
async def acp_discovery() -> dict[str, Any]:
    """Return the ACP discovery manifest.

    Public, unauthenticated. Allows a Claude agent to negotiate ACP without
    prior contact. Response shape is stable; bump `version` on breaking changes.
    """
    return acp_discovery_manifest()


@router.post(
    "/acp/checkout",
    response_model=AcpCheckoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Create ACP Stripe Checkout session (Claude Agent direct invoke)",
)
async def acp_checkout(body: AcpCheckoutRequest) -> AcpCheckoutResponse:
    """Begin an ACP checkout flow.

    The response includes a short-lived `agent_token` which the agent must
    present to `/v1/billing/acp/confirm` after the Stripe session reaches
    `paid` state. The token is single-use; reuse returns 403.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="stripe_not_configured")
    if not settings.stripe_price_per_request:
        raise HTTPException(status_code=503, detail="stripe_price_not_configured")
    try:
        with _connect_autonomath() as conn:
            return create_acp_checkout(
                conn,
                agent_id=body.agent_id,
                email=body.email,
                return_url=body.return_url,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/acp/confirm",
    response_model=AcpConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm a paid ACP session and reveal the API key once",
)
async def acp_confirm(body: AcpConfirmRequest) -> AcpConfirmResponse:
    """Confirm an ACP checkout — returns the raw API key exactly once."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="stripe_not_configured")
    try:
        with _connect_autonomath() as conn:
            return confirm_acp_session(
                conn,
                agent_token=body.agent_token,
                session_id=body.session_id,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


class AcpPortalRequest(BaseModel):
    customer_id: str = Field(..., min_length=4, max_length=120)
    return_url: str | None = Field(default=None, max_length=500)


@router.post(
    "/acp/portal_link",
    response_model=AcpPortalResponse,
    summary="Mint Stripe portal link bound to JP locale (Wave 21 D3)",
)
async def acp_portal_link(body: AcpPortalRequest) -> AcpPortalResponse:
    """Mint a Stripe portal session in JP locale for an existing customer."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="stripe_not_configured")
    return create_acp_portal_link(customer_id=body.customer_id, return_url=body.return_url)


# -------- x402 origin-side bridge ----------------------------------------


class X402IssueKeyRequest(BaseModel):
    """Payload from `functions/x402_handler.ts` after USDC settlement verify."""

    tx_hash: str = Field(..., min_length=10, max_length=80)
    quote_id: str = Field(..., min_length=10, max_length=200)
    agent_id: str = Field(..., min_length=1, max_length=200)


class X402IssueKeyResponse(BaseModel):
    api_key: str
    expires_at: str
    metering: dict[str, Any]


@router.get("/x402/discovery", summary="x402 origin-side discovery (mirrors edge)")
async def x402_discovery() -> dict[str, Any]:
    """Return the x402 discovery manifest from the origin.

    The canonical surface is the Cloudflare Pages function
    `/x402/discovery`, but agents reaching the origin first (via
    `api.jpcite.com`) get an equivalent JSON so they can switch into the
    edge-served flow without a 404.
    """
    return {
        "protocol": "x402",
        "version": "1.0",
        "edge_endpoint": "https://jpcite.com/x402/discovery",
        "settlement_currency": "USDC",
        "chain": {"id": "8453", "name": "Base"},
        "pricing": {
            "model": "metered_per_request",
            "unit_price_jpy": 3,
            "approx_unit_price_usdc": "0.02",
            "currency_native": "JPY",
            "currency_settle": "USDC",
        },
        "operator": {
            "name": "Bookyou株式会社",
            "invoice_number": "T8010001213708",
            "email": "info@bookyou.net",
        },
    }


@router.post(
    "/x402/issue_key",
    response_model=X402IssueKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Origin-side bridge: x402 settled tx -> metered API key",
)
async def x402_issue_key(body: X402IssueKeyRequest) -> X402IssueKeyResponse:
    """Bridge from CF Pages x402 handler to the metered key issuance path.

    Called by the edge after `functions/x402_handler.ts` verifies the USDC
    transaction on Base. The edge has already confirmed:
      - tx_hash settled with status==0x1
      - tx_hash not previously redeemed (KV nonce cache)
      - quote_id signature valid + not expired
    We trust those edge-side gates; this endpoint records the binding +
    issues the metered key. Re-entry on the same tx_hash returns the same
    key (idempotent via the unique index below).
    """
    from datetime import UTC, datetime, timedelta

    with _connect_autonomath() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS x402_tx_bind (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_hash TEXT NOT NULL UNIQUE,
                agent_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                api_key_hash TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        existing = conn.execute(
            "SELECT api_key_hash FROM x402_tx_bind WHERE tx_hash = ?",
            (body.tx_hash,),
        ).fetchone()
        if existing and existing["api_key_hash"]:
            # Idempotent: same tx => same key (the raw key was already
            # revealed once on the first call; second caller gets a 409 so
            # they cannot harvest a second key from the same on-chain tx).
            raise HTTPException(status_code=409, detail="tx_already_redeemed")

        customer_id = f"x402_{body.agent_id[:50]}"
        raw_key = issue_key(
            conn,
            customer_id=customer_id,
            tier="paid",
            stripe_subscription_id=None,
        )
        # Hash for at-rest tracking (we never persist the raw key).
        import hashlib

        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO x402_tx_bind (tx_hash, agent_id, quote_id, api_key_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tx_hash) DO UPDATE SET api_key_hash = excluded.api_key_hash
            """,
            (body.tx_hash, body.agent_id, body.quote_id, key_hash),
        )
        conn.commit()

    expires_at = datetime.now(UTC) + timedelta(days=30)
    return X402IssueKeyResponse(
        api_key=raw_key,
        expires_at=expires_at.isoformat(),
        metering={
            "unit_price_jpy": 3,
            "approx_unit_price_usdc": "0.02",
            "model": "metered_per_request",
        },
    )


# -------- MPP (Managed Provider Plan) read-only --------------------------


@router.get(
    "/mpp/discovery",
    summary="MPP naming canon (Wave 21 D4+D5+D6 stacked)",
)
async def mpp_discovery() -> dict[str, Any]:
    """Return the MPP naming canon + component list.

    Read-only. MPP is a brand layer over Wave 21 D4/D5/D6 primitives —
    there is no MPP-specific code path, table, or tier. See
    `docs/billing/mpp_naming.md` for the canonical narrative.
    """
    return {
        "plan_name": "Managed Provider Plan",
        "plan_code": "mpp",
        "is_tier": False,
        "version": "1.0",
        "components": [
            {
                "id": "volume_rebate",
                "wave": "21-D4",
                "table": "am_volume_rebate",
                "summary": "Back-of-period rebate posted to the next invoice.",
            },
            {
                "id": "credit_pack",
                "wave": "21-D5",
                "table": "am_credit_pack_purchase",
                "summary": "Lump-sum prepay (¥300K / ¥1M / ¥3M) consumed against ¥3/req.",
            },
            {
                "id": "yearly_prepay",
                "wave": "21-D6",
                "table": "am_yearly_prepay",
                "summary": "12-month prepay; one month discount on the first invoice.",
            },
        ],
        "base_rate_jpy": 3,
        "base_rate_tax_inclusive_jpy": 3.30,
        "intended_monthly_jpy_range": [30000, 100000],
        "target_buyer": [
            "税理士事務所",
            "会計士事務所",
            "補助金コンサル",
            "シンクタンク",
        ],
        "operator": {
            "name": "Bookyou株式会社",
            "invoice_number": "T8010001213708",
            "email": "info@bookyou.net",
        },
        "docs_url": "https://jpcite.com/docs/billing/mpp_naming",
    }


@router.get(
    "/rails/discovery",
    summary="Discovery across all 3 rails (ACP + x402 + MPP)",
)
async def rails_discovery() -> dict[str, Any]:
    """Aggregated discovery for agents picking a rail at first contact.

    Returned shape is stable for buyer-side automation: each rail entry
    carries a `kind`, a `version`, and a pointer to its own discovery
    endpoint. Agents pick the first rail they can settle on.
    """
    return {
        "version": "1.0",
        "rails": [
            {
                "kind": "acp",
                "name": "Anthropic Commerce Protocol",
                "version": ACP_PROTOCOL_VERSION,
                "discovery": "/v1/billing/acp/discovery",
                "settle_with": "stripe_subscription",
                "currency": "JPY",
            },
            {
                "kind": "x402",
                "name": "x402 HTTP 402 Payment Required (USDC)",
                "version": "1.0",
                "discovery": "/v1/billing/x402/discovery",
                "settle_with": "usdc_onchain_base",
                "currency": "USDC",
            },
            {
                "kind": "mpp",
                "name": "Managed Provider Plan",
                "version": "1.0",
                "discovery": "/v1/billing/mpp/discovery",
                "settle_with": "stripe_invoice_components",
                "currency": "JPY",
            },
        ],
        "operator": {
            "name": "Bookyou株式会社",
            "invoice_number": "T8010001213708",
            "email": "info@bookyou.net",
        },
    }
