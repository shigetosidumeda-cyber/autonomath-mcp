"""Wave 51 x402 payment scaffolding (router-agnostic).

Background
----------
The Wave 48 router at ``src/jpintel_mcp/api/x402_payment.py`` wires
HTTP 402 challenges into FastAPI middleware against the
``am_x402_endpoint_config`` SQLite seeds. That router is the
production surface; this package is the **router-agnostic
scaffolding** added in Wave 51 so MCP tools, ETL probes, and
offline CLI scripts can construct + verify x402 challenges WITHOUT
depending on the FastAPI router internals, SQLite seeds, or chain
RPC.

Three rails per ``feedback_agent_monetization_3_payment_rails``:
USDC on Base / Polygon (Coinbase x402 flow), Stripe Agentic
Commerce Protocol (Flow A), plus an internal wallet balance rail
that delegates to ``src/jpintel_mcp/credit_wallet/``.

Non-negotiable
--------------
* No outbound HTTP to Coinbase / Stripe / facilitator at runtime.
* No actual chain RPC — signature shape verification only.
* No LLM imports (CI guard ``tests/test_no_llm_in_production.py``).
* No customer payment data stored — proof envelopes only.

Public surface
--------------
    X402PaymentMethod
        Enum of accepted payment rails.
    X402Challenge
        Frozen Pydantic envelope returned by ``generate_402_response``.
    X402PaymentProof
        Frozen Pydantic envelope consumed by ``verify_payment``.
    generate_402_response(request, billing_hint) -> X402Challenge
        Build a fresh challenge from a request-like object.
    verify_payment(payment_proof, *, ...) -> bool
        Signature-shape verifier (NOT chain settlement).
    DEFAULT_ACCEPTED_METHODS
        Canonical ordered list of accepted methods.
    DEFAULT_CHALLENGE_TTL_SEC
        Module constant — 3600 seconds.
"""

from __future__ import annotations

from jpintel_mcp.x402_payment.challenge import (
    DEFAULT_ACCEPTED_METHODS,
    generate_402_response,
    verify_payment,
)
from jpintel_mcp.x402_payment.models import (
    DEFAULT_CHALLENGE_TTL_SEC,
    MAX_PRICE_YEN,
    MIN_PRICE_YEN,
    X402Challenge,
    X402PaymentMethod,
    X402PaymentProof,
)

__all__ = [
    "DEFAULT_ACCEPTED_METHODS",
    "DEFAULT_CHALLENGE_TTL_SEC",
    "MAX_PRICE_YEN",
    "MIN_PRICE_YEN",
    "X402Challenge",
    "X402PaymentMethod",
    "X402PaymentProof",
    "generate_402_response",
    "verify_payment",
]
