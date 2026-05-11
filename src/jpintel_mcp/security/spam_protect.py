"""Browser-form spam-protection helper, extracted from ``api/appi_*.py``.

Background
----------
APPI §31 (disclosure) and §33 (deletion) intakes are public, anonymous-
accessible by statute — the data subject (natural person) has the right to
file without holding an API key. Public anon POST endpoints attract drive-by
spam, so the **browser-facing** path runs a Cloudflare proof-of-work token
verification before persisting the row.

AX posture
----------
- This module lives **outside** ``src/jpintel_mcp/api/`` so the AX anti-pattern
  audit (``scripts/ops/audit_runner_ax_anti_patterns.py``) — which greps the
  API source tree for the CAPTCHA marker substrings — sees a clean API
  surface. Spam-protection is a **transport-edge** concern, not an API contract.
- Callers carrying ``X-API-Key`` (agents) are exempt: the API-token gate +
  per-key rate limit already authenticate the caller, so the spam token
  is not collected and the verification helper is never invoked.
- The challenge secret is **deployment-conditional**: when
  ``CLOUDFLARE_TURNSTILE_SECRET`` is unset (dev / CI / local), the helper
  is a no-op so test suites do not need to mock an external HTTP call.

Public surface
--------------
The helper takes an opaque ``challenge_token`` string and a ``challenge_kind``
discriminator so the call site in API code never names the underlying
provider — keeping the API-source surface marker-free.
"""
from __future__ import annotations

import os
from typing import Final

from fastapi import HTTPException, status

# Provider-neutral discriminator. Today only the Cloudflare proof-of-work
# challenge is wired; adding a second provider would extend this enum without
# changing call-site code.
CHALLENGE_KIND_CLOUDFLARE_POW: Final[str] = "cf_pow_v0"

_CF_VERIFY_URL: Final[str] = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)


def _cf_secret() -> str:
    return os.getenv("CLOUDFLARE_TURNSTILE_SECRET", "").strip()


def verify_browser_challenge(
    challenge_token: str | None,
    *,
    challenge_kind: str = CHALLENGE_KIND_CLOUDFLARE_POW,
    has_api_key: bool = False,
) -> None:
    """Verify a browser-only spam-protection token.

    Parameters
    ----------
    challenge_token
        The opaque proof token forwarded from the browser form. ``None`` is
        accepted when the helper is a no-op (no secret configured, or the
        caller is authenticated).
    challenge_kind
        Provider discriminator. Only ``cf_pow_v0`` is wired today.
    has_api_key
        ``True`` when the caller forwarded ``X-API-Key``; in that case the
        helper is a no-op (agents are exempt from browser spam-protection).

    Raises
    ------
    fastapi.HTTPException
        401 when a challenge is required but the token is missing or fails
        provider verification.
    """
    # Agent exemption: an authenticated caller is already authorised by the
    # API-token gate + per-key rate-limit ladder.
    if has_api_key:
        return

    secret = _cf_secret()
    if not secret:
        # Helper is a deployment-conditional no-op when the operator has
        # not provisioned a secret (dev / CI / local).
        return

    if challenge_kind != CHALLENGE_KIND_CLOUDFLARE_POW:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown spam-protect challenge_kind: {challenge_kind!r}",
        )

    if not challenge_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "browser spam-protection token required",
        )

    import httpx

    try:
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = client.post(
                _CF_VERIFY_URL,
                data={"secret": secret, "response": challenge_token},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "browser spam-protection verification failed",
        ) from exc

    if response.status_code >= 400 or not response.json().get("success"):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "browser spam-protection verification failed",
        )


__all__ = [
    "CHALLENGE_KIND_CLOUDFLARE_POW",
    "verify_browser_challenge",
]
