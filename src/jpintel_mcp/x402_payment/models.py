"""Pydantic models for the Wave 51 x402 payment scaffolding.

This module mirrors the canonical x402 protocol shape described in
``feedback_agent_x402_protocol`` (Coinbase HTTP-native micropayments
over USDC) for **scaffolding purposes only**. It does NOT issue any
on-chain RPC, does NOT call Stripe, and does NOT store customer
payment data — it only defines the wire envelope so downstream
middleware / routers / tools share one Pydantic contract.

The matching middleware that wires this envelope to FastAPI lives at
``src/jpintel_mcp/api/x402_payment.py`` (Wave 48 landed). This package
is the **router-agnostic** scaffolding layer added in Wave 51 so MCP
tools, ETL probes, and offline CLI scripts can construct + verify
x402 challenges without depending on the FastAPI router internals.

Non-negotiable constraints (memory: feedback_agent_x402_protocol +
feedback_no_operator_llm_api):

* No outbound HTTP to Coinbase / Stripe / facilitator.
* No actual on-chain settlement — verify is signature-shape only.
* No LLM imports anywhere on the request path.
* The envelope is the contract — never break field names.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Default challenge TTL in seconds. Mirrors the Wave 48 router default.
DEFAULT_CHALLENGE_TTL_SEC: Final[int] = 3600

#: Minimum price unit in yen. ¥3 = canonical jpcite metered rate.
MIN_PRICE_YEN: Final[int] = 1

#: Maximum price per single challenge. Defensive ceiling — anything
#: above this should be split into multiple calls.
MAX_PRICE_YEN: Final[int] = 1_000_000


class X402PaymentMethod(StrEnum):
    """Canonical payment methods accepted by the x402 scaffolding.

    Four parallel rails per ``feedback_agent_monetization_3_payment_rails``:

    * ``usdc_base``      — USDC on Base (Coinbase), the canonical x402 rail
    * ``usdc_polygon``   — USDC on Polygon, alt L2 fallback
    * ``stripe_acs``     — Stripe Agentic Commerce Protocol (Flow A)
    * ``wallet_balance`` — internal Credit Wallet balance (yen-denominated)
    """

    USDC_BASE = "usdc_base"
    USDC_POLYGON = "usdc_polygon"
    STRIPE_ACS = "stripe_acs"
    WALLET_BALANCE = "wallet_balance"


class X402Challenge(BaseModel):
    """An HTTP 402 challenge envelope.

    Issued by ``generate_402_response`` and consumed by client agents
    that then resubmit with a verifiable payment proof. The envelope is
    intentionally minimal and machine-readable — agents should not need
    human-readable copy to act on it.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    resource_url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description=(
            "The URL the agent attempted to access. Echo it back verbatim "
            "so the agent can route the proof to the same resource."
        ),
    )
    price_yen: int = Field(
        ...,
        ge=MIN_PRICE_YEN,
        le=MAX_PRICE_YEN,
        description=(
            "Price in JPY (¥). jpcite is metered ¥3/req canonical; "
            "single-shot composed calls may price higher per the outcome "
            "contract (¥300-¥900 band)."
        ),
    )
    accepted_payment_methods: tuple[X402PaymentMethod, ...] = Field(
        ...,
        min_length=1,
        max_length=4,
        description=(
            "Ordered list of accepted payment rails. Agents SHOULD try "
            "the first rail they have funded; servers MAY prioritise "
            "rails by lowest cost-to-serve."
        ),
    )
    expires_at: int = Field(
        ...,
        gt=0,
        description=(
            "Unix epoch seconds at which the challenge expires. After "
            "this point the agent must re-fetch a fresh challenge."
        ),
    )
    challenge_nonce: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description=(
            "Server-chosen nonce included in the signed proof. Used to "
            "bind proof to one challenge so replay across challenges "
            "cannot occur."
        ),
    )

    @field_validator("resource_url")
    @classmethod
    def _must_be_http_or_https_or_relative(cls, value: str) -> str:
        """Accept https://, http:// (dev only) or path-relative URLs."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("resource_url must not be empty")
        if stripped.startswith(("https://", "http://", "/")):
            return stripped
        raise ValueError(
            "resource_url must start with https://, http://, or / "
            "(absolute path)"
        )

    @field_validator("accepted_payment_methods")
    @classmethod
    def _no_duplicate_methods(
        cls,
        value: tuple[X402PaymentMethod, ...],
    ) -> tuple[X402PaymentMethod, ...]:
        if len(set(value)) != len(value):
            raise ValueError("accepted_payment_methods must not contain duplicates")
        return value

    def is_expired(self, *, now_unix: int | None = None) -> bool:
        """Return True if ``now_unix`` is past ``expires_at``."""
        current = now_unix if now_unix is not None else int(time.time())
        return current >= self.expires_at


class X402PaymentProof(BaseModel):
    """A payment proof submitted by an agent after a 402 challenge.

    Scaffolding-grade: this module only verifies the proof's shape
    (envelope present + nonce matches + signature non-empty). It does
    NOT contact a chain RPC. A real production verifier lives at the
    Cloudflare Pages edge (``functions/x402_handler.ts``) per the Wave
    48 contract; this package is the **scaffolding** verifier used by
    tests / dev / scaffolding tools.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    challenge_nonce: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Echo of the nonce from the matching X402Challenge.",
    )
    payment_method: X402PaymentMethod = Field(
        ...,
        description="The rail used to fund the payment.",
    )
    payer_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Opaque payer identifier — chain address, Stripe customer "
            "id, or internal customer_id depending on payment_method."
        ),
    )
    amount_yen: int = Field(
        ...,
        ge=MIN_PRICE_YEN,
        le=MAX_PRICE_YEN,
        description=(
            "Amount actually paid in JPY. Must equal the X402Challenge "
            "price_yen to verify."
        ),
    )
    signature: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description=(
            "Provider-specific signature / transaction hash / receipt. "
            "Scaffolding verifier checks non-emptiness only."
        ),
    )


__all__ = [
    "DEFAULT_CHALLENGE_TTL_SEC",
    "MAX_PRICE_YEN",
    "MIN_PRICE_YEN",
    "X402Challenge",
    "X402PaymentMethod",
    "X402PaymentProof",
]
