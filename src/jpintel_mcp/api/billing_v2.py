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

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jpintel_mcp.api.deps import ApiContextDep  # noqa: TC001 (FastAPI dependency alias)
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
)
from jpintel_mcp.billing.acp_integration import (
    discovery_manifest as acp_discovery_manifest,
)
from jpintel_mcp.billing.keys import issue_trial_key
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect as connect_jpintel

logger = logging.getLogger("jpintel.billing.v2")

router = APIRouter(prefix="/v1/billing", tags=["billing-v2"])

_X402_ORIGIN_SECRET_ENV = "JPCITE_X402_ORIGIN_SECRET"
_X402_ORIGIN_SECRET_HEADER = "X-JPCITE-X402-Origin-Secret"
_X402_QUOTE_SECRET_ENV = "JPCITE_X402_QUOTE_SECRET"
_X402_ADDRESS_ENV = "JPCITE_X402_ADDRESS"
_X402_CHAIN_ID = "8453"
_X402_USDC_BASE = "0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913".lower()


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
    # Kept optional for wire compatibility; ignored for security. The Stripe
    # customer is derived from the authenticated API key.
    customer_id: str | None = Field(default=None, min_length=4, max_length=120)
    return_url: str | None = Field(default=None, max_length=500)


@router.post(
    "/acp/portal_link",
    response_model=AcpPortalResponse,
    summary="Mint Stripe portal link bound to JP locale (Wave 21 D3)",
)
async def acp_portal_link(body: AcpPortalRequest, ctx: ApiContextDep) -> AcpPortalResponse:
    """Mint a Stripe portal session for the authenticated Stripe customer."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="stripe_not_configured")
    if ctx.key_hash is None:
        raise HTTPException(status_code=401, detail="auth_required")
    if not ctx.customer_id:
        raise HTTPException(status_code=402, detail="stripe_customer_required")
    try:
        return create_acp_portal_link(customer_id=ctx.customer_id, return_url=body.return_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -------- x402 origin-side bridge ----------------------------------------


class X402IssueKeyRequest(BaseModel):
    """Payload from `functions/x402_handler.ts` after USDC settlement verify."""

    tx_hash: str = Field(..., min_length=66, max_length=66)
    quote_id: str = Field(..., min_length=10, max_length=1024)
    agent_id: str = Field(..., min_length=1, max_length=200)


class X402IssueKeyResponse(BaseModel):
    api_key: str
    expires_at: str
    metering: dict[str, Any]


def _require_x402_origin_auth(header_value: str | None) -> None:
    expected = os.environ.get(_X402_ORIGIN_SECRET_ENV, "").strip()
    if not expected:
        logger.error("x402 issue_key blocked: %s is unset", _X402_ORIGIN_SECRET_ENV)
        raise HTTPException(status_code=503, detail="x402_origin_unavailable")
    if not header_value or not secrets.compare_digest(header_value, expected):
        raise HTTPException(status_code=403, detail="x402_origin_auth_failed")


def _normalize_evm_address(value: Any) -> str:
    raw = str(value or "").lower()
    if len(raw) == 42 and raw.startswith("0x") and all(c in "0123456789abcdef" for c in raw[2:]):
        return raw
    return ""


# -------- strict x402 quote payload model --------------------------------
#
# R2 P1-2 audit hardening (2026-05-13): the inner JSON-decoded payload of
# `quote_id` is now parsed through a Pydantic v2 model that rejects
# whitespace-padded numerics, oversized integers, leading-zero strings, and
# any extra / missing keys. The edge (`functions/x402_handler.ts`, owned by
# A5/D7) emits a single shape with exactly 8 keys — `v, u, r, p, a, e, c, t`
# — and the prior `int(str(payload.get(...)))` parse path silently accepted
# `" 1 "`, `"-1"`, `"007"`, and `2**128`. Strict typing closes that surface.
#
# Wire naming note: the audit brief documents the protocol-version key as
# `n` (nonce). The edge ships it as `v` (version), and the edge is the
# write-side authority (see top-of-file DO NOT EDIT pin). We keep the
# wire-level key `v` and enforce the brief's `int (≥0, ≤2**63-1)` constraint
# on it; the semantic role (small monotonic protocol marker) is identical.

# Maximum signed 64-bit positive integer — matches the brief's constraint
# and a typical underlying storage bound.
_X402_INT64_MAX = 2**63 - 1
# Cap on micro-USDC amount — 10**12 micro-USDC == 1_000_000 USDC.
_X402_AMOUNT_MAX = 10**12
_X402_EVM_HEX_REGEX = r"^0x[0-9a-fA-F]{40}$"


def _strict_digit_string_to_int(value: Any) -> int:
    """Validator helper: accept an int OR a strict-digit JSON string.

    The edge `functions/x402_handler.ts` emits `u` as `String(microUsdc)`
    (the QuoteIdPayload TypeScript interface declares `u: string`). The
    audit brief mandates that `u` is logically an integer. We bridge that
    by:
      - accepting `int` values verbatim (`bool` is explicitly rejected even
        though it is an `int` subclass in Python);
      - accepting a `str` only if it matches `^[1-9][0-9]*$` (no leading
        zeros, no signs, no whitespace, no scientific notation, no empty).

    Anything else raises `ValueError`, which Pydantic surfaces as a
    `ValidationError` that `_decode_quote_payload` maps to 422
    `invalid_quote_id`. Note that the `_X402_AMOUNT_MAX` (`10**12`) and
    `ge=1` bounds on the `u` field still apply on top of this coercion.
    """
    if isinstance(value, bool):
        # `bool` is an `int` subclass in Python; explicitly reject so a
        # quote with `"u": true` cannot slip through as `1`.
        raise ValueError("u_must_not_be_bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # Strict-digit only — no leading/trailing whitespace, no signs,
        # no leading zeros (rejects "007"), no empty string, no Unicode
        # digit shenanigans (rejects "٣" U+0663 ARABIC-INDIC DIGIT THREE).
        if not value or not value.isascii() or not value.isdigit():
            raise ValueError("u_must_be_strict_digits")
        if len(value) > 1 and value[0] == "0":
            raise ValueError("u_must_not_have_leading_zero")
        return int(value)
    raise ValueError("u_must_be_int_or_digit_string")


class X402QuotePayload(BaseModel):
    """Strictly-typed inner payload decoded from the x402 `quote_id`.

    The edge signs the base64url-encoded JSON of this exact shape. Any
    deviation — extra keys, missing keys, whitespace inside numerics,
    leading-zero strings, oversize ints, negative ints — must yield a
    422 from `_verify_x402_quote`.

    `model_config.extra = "forbid"` rejects extra keys; Pydantic v2 rejects
    missing keys by default; `strict=True` blocks the silent `int(" 1 ")`
    coercion path that the legacy code allowed. `u` keeps a digit-string
    bridge via `_strict_digit_string_to_int` because the edge emits it as
    `String(microUsdc)` — see field validator below.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    v: int = Field(ge=0, le=_X402_INT64_MAX)
    a: str = Field(min_length=1, max_length=64)
    p: str = Field(pattern=_X402_EVM_HEX_REGEX)
    r: str = Field(pattern=_X402_EVM_HEX_REGEX)
    t: str = Field(pattern=_X402_EVM_HEX_REGEX)
    c: Literal["8453"]
    u: int = Field(ge=1, le=_X402_AMOUNT_MAX)
    e: int = Field(ge=0, le=_X402_INT64_MAX)

    @field_validator("u", mode="before")
    @classmethod
    def _coerce_u_from_digit_string(cls, value: Any) -> int:
        """Bridge edge's `String(microUsdc)` wire form to a strict int.

        Pydantic v2 with `strict=True` rejects `"3000"` for an `int` field
        by default. The edge declares `u: string`, so we explicitly accept
        a `[1-9][0-9]*` digit string (no signs, no whitespace, no leading
        zeros) here, and reject everything else.
        """
        return _strict_digit_string_to_int(value)


def _decode_quote_payload(encoded: str) -> X402QuotePayload:
    """Decode and strictly validate the inner 8-key quote payload.

    Raises HTTPException(422, invalid_quote_id) on any decode or schema
    failure — base64, JSON, top-level shape, missing/extra keys, type
    coercion, range bounds, or regex mismatches.
    """
    try:
        padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_quote_id") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="invalid_quote_id")
    try:
        return X402QuotePayload.model_validate(parsed)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_quote_id") from exc


def _verify_x402_quote(body: X402IssueKeyRequest) -> dict[str, Any]:
    if not (
        body.tx_hash.startswith("0x")
        and len(body.tx_hash) == 66
        and all(c in "0123456789abcdefABCDEF" for c in body.tx_hash[2:])
    ):
        raise HTTPException(status_code=422, detail="invalid_tx_hash")

    quote_secret = os.environ.get(_X402_QUOTE_SECRET_ENV, "").strip()
    recipient = _normalize_evm_address(os.environ.get(_X402_ADDRESS_ENV, ""))
    if not quote_secret or not recipient:
        raise HTTPException(status_code=503, detail="x402_origin_unavailable")

    parts = body.quote_id.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=422, detail="invalid_quote_id")
    expected_sig = hmac.new(
        quote_secret.encode("utf-8"),
        parts[0].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(parts[1], expected_sig):
        raise HTTPException(status_code=422, detail="invalid_quote_id")

    payload = _decode_quote_payload(parts[0])

    # The schema already guarantees these are well-shaped EVM hex strings —
    # we just lowercase to match `_X402_USDC_BASE` (which is `.lower()`-ed
    # at module import) and the env-derived recipient (normalized through
    # `_normalize_evm_address`, also lowercase).
    payer = payload.p.lower()
    token = payload.t.lower()
    signed_recipient = payload.r.lower()
    agent_id = payload.a

    if (
        payload.v != 1
        or payload.c != _X402_CHAIN_ID
        or token != _X402_USDC_BASE
        or signed_recipient != recipient
        or agent_id != body.agent_id.strip()[:200]
    ):
        raise HTTPException(status_code=422, detail="invalid_quote_id")
    if payload.e < int(time.time()):
        raise HTTPException(status_code=422, detail="expired_quote_id")

    return {
        "agent_id": agent_id,
        "payer_address": payer,
        "amount_usdc_micro": payload.u,
        "expires_at_unix": payload.e,
    }


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
    include_in_schema=False,
)
async def x402_issue_key(
    body: X402IssueKeyRequest,
    x402_origin_secret: str | None = Header(
        default=None,
        alias=_X402_ORIGIN_SECRET_HEADER,
    ),
) -> X402IssueKeyResponse:
    """Bridge from CF Pages x402 handler to the metered key issuance path.

    Called by the edge after `functions/x402_handler.ts` verifies the USDC
    transaction on Base. The edge has already confirmed:
      - tx_hash settled with status==0x1
      - tx_hash not previously redeemed (KV nonce cache)
      - quote_id signature valid + not expired
    The origin still requires a shared edge/origin secret before a short-lived
    one-request bearer can be minted. x402 must never create a reusable paid
    key without a Stripe subscription. Re-entry on the same tx_hash returns
    409 so the raw key is never revealed twice and concurrent calls cannot
    mint duplicates.
    """
    from datetime import UTC, datetime, timedelta

    _require_x402_origin_auth(x402_origin_secret)
    quote = _verify_x402_quote(body)

    with connect_jpintel() as conn:
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
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO x402_tx_bind (tx_hash, agent_id, quote_id, api_key_hash)
                VALUES (?, ?, ?, NULL)
                """,
                (body.tx_hash, quote["agent_id"], body.quote_id),
            )
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            existing = conn.execute(
                "SELECT api_key_hash FROM x402_tx_bind WHERE tx_hash = ?",
                (body.tx_hash,),
            ).fetchone()
            if existing and existing["api_key_hash"]:
                # The raw key was already revealed once on the first call.
                raise HTTPException(status_code=409, detail="tx_already_redeemed") from exc
            # A concurrent origin request reserved the transaction but has
            # not completed key issuance yet. Do not mint a second key.
            raise HTTPException(status_code=409, detail="tx_redemption_in_progress") from exc

        customer_id = f"x402_{quote['agent_id'][:50]}"
        try:
            raw_key, key_hash = issue_trial_key(
                conn,
                trial_email=f"{customer_id}@x402.local",
                duration_days=1,
                request_cap=1,
            )
            conn.execute(
                """
                UPDATE x402_tx_bind
                SET api_key_hash = ?
                WHERE tx_hash = ? AND api_key_hash IS NULL
                """,
                (key_hash, body.tx_hash),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    expires_at = datetime.now(UTC) + timedelta(days=1)
    return X402IssueKeyResponse(
        api_key=raw_key,
        expires_at=expires_at.isoformat(),
        metering={
            "unit_price_jpy": 3,
            "approx_unit_price_usdc": "0.02",
            "model": "x402_one_request",
            "request_cap": 1,
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
