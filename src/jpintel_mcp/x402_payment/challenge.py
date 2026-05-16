"""402 challenge factory + scaffolding-grade payment verifier.

Public surface
--------------
``generate_402_response(request, billing_hint) -> X402Challenge``
    Build a fresh challenge envelope. ``request`` may be any object
    exposing ``url`` (str), ``path`` (str), or ``resource_url`` (str)
    — the factory does **not** depend on FastAPI / Starlette.
``verify_payment(payment_proof, *, expected_challenge_nonce,
                 expected_amount_yen) -> bool``
    Signature-shape verifier. Returns True iff the proof's nonce
    matches, its amount equals the challenge price, its signature is
    non-empty, and its payment_method is in the canonical enum. No
    chain RPC is performed.

Non-goals (memory: feedback_agent_x402_protocol):
* No outbound HTTP to Coinbase / Stripe / facilitator.
* No real signature verification — that lives at the edge.
* No LLM imports.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from jpintel_mcp.x402_payment.models import (
    DEFAULT_CHALLENGE_TTL_SEC,
    MAX_PRICE_YEN,
    MIN_PRICE_YEN,
    X402Challenge,
    X402PaymentMethod,
    X402PaymentProof,
)

#: Default accepted methods. Order matters — agents try first-funded.
DEFAULT_ACCEPTED_METHODS: tuple[X402PaymentMethod, ...] = (
    X402PaymentMethod.USDC_BASE,
    X402PaymentMethod.WALLET_BALANCE,
    X402PaymentMethod.STRIPE_ACS,
    X402PaymentMethod.USDC_POLYGON,
)


def _extract_resource_url(request: Any) -> str:
    """Best-effort extraction of a resource URL from request-like input.

    Accepts anything with one of these attributes (in priority order):

    * ``resource_url`` (str)
    * ``url`` (str or ``str(url)``-able)
    * ``path`` (str)

    Falls back to ``str(request)`` only if all attribute probes fail
    — in which case the caller almost certainly passed a bare string.
    """
    if isinstance(request, str):
        return request
    for attr in ("resource_url", "url", "path"):
        value = getattr(request, attr, None)
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return str(request)


def _fresh_nonce() -> str:
    """Generate a fresh urlsafe nonce well above the 8-char floor."""
    return secrets.token_urlsafe(16)


def generate_402_response(
    request: Any,
    billing_hint: dict[str, Any] | None = None,
    *,
    accepted_methods: tuple[X402PaymentMethod, ...] | None = None,
    now_unix: int | None = None,
) -> X402Challenge:
    """Build a fresh 402 challenge envelope.

    Parameters
    ----------
    request:
        Object whose URL we want to challenge. Anything with a
        ``resource_url`` / ``url`` / ``path`` attribute works; a bare
        string is also accepted.
    billing_hint:
        Optional dict carrying ``price_yen`` (int) and / or
        ``ttl_seconds`` (int). Missing values fall back to the
        canonical ¥3/req rate and ``DEFAULT_CHALLENGE_TTL_SEC``.
    accepted_methods:
        Override the default ordered list of accepted payment rails.
    now_unix:
        Test-only hook to pin the clock.

    Returns
    -------
    X402Challenge
        A frozen Pydantic envelope ready to be serialised to JSON.
    """
    hint = dict(billing_hint or {})
    raw_price = hint.get("price_yen", 3)
    if not isinstance(raw_price, int) or isinstance(raw_price, bool):
        raise ValueError(f"billing_hint.price_yen must be int, got {type(raw_price)!r}")
    if raw_price < MIN_PRICE_YEN or raw_price > MAX_PRICE_YEN:
        raise ValueError(
            f"billing_hint.price_yen out of range "
            f"[{MIN_PRICE_YEN}, {MAX_PRICE_YEN}]: {raw_price}"
        )

    raw_ttl = hint.get("ttl_seconds", DEFAULT_CHALLENGE_TTL_SEC)
    if not isinstance(raw_ttl, int) or isinstance(raw_ttl, bool) or raw_ttl <= 0:
        raise ValueError(
            f"billing_hint.ttl_seconds must be a positive int, got {raw_ttl!r}"
        )

    methods = accepted_methods if accepted_methods is not None else DEFAULT_ACCEPTED_METHODS
    if not methods:
        raise ValueError("accepted_methods must not be empty")

    now = now_unix if now_unix is not None else int(time.time())

    return X402Challenge(
        resource_url=_extract_resource_url(request),
        price_yen=raw_price,
        accepted_payment_methods=tuple(methods),
        expires_at=now + raw_ttl,
        challenge_nonce=_fresh_nonce(),
    )


def verify_payment(
    payment_proof: X402PaymentProof,
    *,
    expected_challenge_nonce: str | None = None,
    expected_amount_yen: int | None = None,
) -> bool:
    """Scaffolding-grade payment proof verifier.

    Returns True iff:

    * proof's ``challenge_nonce`` equals ``expected_challenge_nonce``
      (when provided),
    * proof's ``amount_yen`` equals ``expected_amount_yen``
      (when provided),
    * proof's ``signature`` is non-empty (envelope contract),
    * proof's ``payment_method`` is a canonical enum member
      (Pydantic enforces this; we re-check defensively).

    This is intentionally NOT a real signature verifier — the real
    verifier lives at the Cloudflare Pages edge (Wave 48 contract).
    Calling code MUST not treat a True return as proof of settlement;
    it only proves the envelope is well-formed.
    """
    if not isinstance(payment_proof, X402PaymentProof):
        return False
    if not payment_proof.signature or not payment_proof.signature.strip():
        return False
    if payment_proof.payment_method not in X402PaymentMethod:
        return False
    if (
        expected_challenge_nonce is not None
        and payment_proof.challenge_nonce != expected_challenge_nonce
    ):
        return False
    return not (expected_amount_yen is not None and payment_proof.amount_yen != expected_amount_yen)


__all__ = [
    "DEFAULT_ACCEPTED_METHODS",
    "generate_402_response",
    "verify_payment",
]
