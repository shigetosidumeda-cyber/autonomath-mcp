"""Interrupt / resume session helper — opaque continuation tokens.

Wave 18 AX Orchestration pillar adds first-class "interrupt then resume"
semantics to long-running list / search endpoints. Pattern:

  1. Caller hits ``GET /v1/programs?q=...&limit=50`` and receives a JSON
     body containing ``items: [...]`` and ``continuation_token: "<opaque>"``.
  2. If the caller is interrupted (rate-limit 429, network blip, agent
     scheduler preempt, customer-cap 503), they keep the token and resume
     later with ``GET /v1/programs?continuation_token=<opaque>`` — server
     decodes the token, restores the cursor, and returns the next page
     without re-walking the offset.

This module is the canonical encoder + decoder. Tokens are HMAC-signed so
the server can prove the cursor was minted here (a tampered token 401s
with ``code=continuation_token_invalid``). The HMAC secret is reused from
``API_KEY_SALT`` (same boot-gate-enforced ≥32 char value); no new secret
material is added to the Fly inventory.

Three field aliases are accepted on input to bridge legacy SDK habits:

  - ``continuation_token`` — canonical (Wave 18 AX spec)
  - ``resume_token``       — legacy alias, accepted but not advertised
  - ``session_token``      — Anthropic Messages API parlance, accepted

The output side always emits ``continuation_token`` so SDK regen stays
single-source. This module deliberately does NOT mint a DB row — the
idempotency_cache (migration 087) handles the heavier "replay this exact
POST" case; this is the lightweight "remember my cursor" case.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import time
from hashlib import sha256
from typing import Any

# Default 24h validity. Tokens beyond TTL decode but the helper surfaces
# an ``expired`` flag so the caller can decide between a 410 Gone and a
# fresh-query fall-through.
TOKEN_TTL_SECONDS_DEFAULT = 24 * 60 * 60


def _secret() -> bytes:
    """Return the HMAC secret. Reuses ``API_KEY_SALT`` (boot-gate enforced)."""
    salt = os.getenv("API_KEY_SALT", "") or ""
    # An empty salt in tests / CI is fine — the HMAC still verifies
    # tokens minted in the same process. Production boot gate refuses to
    # start with <32-char salt, so this branch is unreachable in prod.
    return salt.encode("utf-8") or b"jpcite-continuation-fallback-do-not-use-in-prod"


def encode_continuation_token(
    *,
    cursor: dict[str, Any],
    ttl_seconds: int = TOKEN_TTL_SECONDS_DEFAULT,
) -> str:
    """Mint an opaque, HMAC-signed continuation token.

    ``cursor`` is a small JSON-serialisable dict — e.g. ``{"offset": 50,
    "q": "ものづくり", "tier": "S"}``. Caller is responsible for keeping it
    compact (< 256 bytes); the encoder does not compress.

    Returns ``"<b64-payload>.<b64-sig>"`` so legacy parsers that split on
    ``.`` keep working.
    """
    expires_at = int(time.time()) + max(1, ttl_seconds)
    payload = json.dumps(
        {"cursor": cursor, "expires_at": expires_at},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    sig = hmac.new(_secret(), payload, sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        + "."
        + base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    )


class ContinuationTokenError(ValueError):
    """Raised when a continuation_token / resume_token / session_token is
    malformed, signature-invalid, or expired."""


def _b64dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def decode_continuation_token(token: str | None) -> dict[str, Any]:
    """Verify + decode a token. Returns the original ``cursor`` dict.

    Accepts the canonical ``continuation_token`` plus the ``resume_token``
    and ``session_token`` aliases (callers pass the raw string regardless
    of which header / query param it arrived on).

    Raises ``ContinuationTokenError`` with a short reason code on:
      - missing token (``"missing"``)
      - malformed shape (``"malformed"``)
      - bad signature (``"bad_signature"``)
      - expired (``"expired"``)
    """
    if not token or not token.strip():
        raise ContinuationTokenError("missing")
    if "." not in token:
        raise ContinuationTokenError("malformed")
    payload_b64, sig_b64 = token.rsplit(".", 1)
    try:
        payload = _b64dec(payload_b64)
        sig = _b64dec(sig_b64)
    except Exception as exc:  # noqa: BLE001 — opaque base64 decode failure
        raise ContinuationTokenError("malformed") from exc
    expected = hmac.new(_secret(), payload, sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ContinuationTokenError("bad_signature")
    try:
        body = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — opaque JSON decode failure
        raise ContinuationTokenError("malformed") from exc
    if not isinstance(body, dict) or "cursor" not in body or "expires_at" not in body:
        raise ContinuationTokenError("malformed")
    expires_at = int(body.get("expires_at", 0))
    if expires_at and expires_at < int(time.time()):
        raise ContinuationTokenError("expired")
    cursor = body["cursor"]
    if not isinstance(cursor, dict):
        raise ContinuationTokenError("malformed")
    return cursor


def normalize_token_aliases(
    *,
    continuation_token: str | None = None,
    resume_token: str | None = None,
    session_token: str | None = None,
) -> str | None:
    """Pick the first non-empty value of the three accepted alias names.

    Routes accept all three so the agent SDK does not have to special-case
    a Japanese-public-program endpoint vs. the Messages API or any other
    LLM API parlance.
    """
    for candidate in (continuation_token, resume_token, session_token):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


__all__ = [
    "ContinuationTokenError",
    "TOKEN_TTL_SECONDS_DEFAULT",
    "decode_continuation_token",
    "encode_continuation_token",
    "normalize_token_aliases",
]
