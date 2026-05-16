"""OAuthBridge — URL builder + state-token verifier (NO actual exchange).

Per ``feedback_copilot_scaffold_only_no_llm`` the embed scaffold limits
itself to scaffold + MCP proxy + auth bridge. The "auth bridge" piece is
intentionally **URL-only**:

    * The widget needs to redirect the user to the host SaaS's OAuth
      authorize endpoint with a state token so the host can correlate
      the callback to the originating widget session.
    * The widget does NOT receive the authorization code; the host
      SaaS's existing OAuth callback handler receives it and performs
      the code → access-token exchange against the host's own OAuth
      server (their credentials, their cost).
    * jpcite never holds the host's OAuth client secret. The bridge is
      a pure URL builder + state-token mint + state-token verifier —
      nothing that touches a refresh token.

This keeps the scaffold compliant with the dim S "LLM-0" rule by
construction: there is no place inside the bridge where an inference
hop could be smuggled in, because there is no outbound HTTP call at all.

State tokens
------------
:class:`OAuthBridge` mints state tokens via :mod:`secrets.token_urlsafe`
(48 bytes → ~64 character urlsafe-base64 string). The token is opaque
to the host SaaS; only :meth:`OAuthBridge.verify_state` can confirm
authenticity, by re-deriving an HMAC-SHA256 over the issuer + nonce and
comparing in constant time.

Token shape: ``"<nonce>.<hmac>"`` where:

    * ``nonce`` = ``secrets.token_urlsafe(32)`` (~43 chars)
    * ``hmac``  = ``base64url(hmac_sha256(secret, host_saas_id + ":" + nonce))``

Why this layout: a stateless verifier is friendlier to a fly.io
serverless redeploy than a server-side state ledger, and the HMAC
binding prevents a stolen nonce from being replayed against a different
host_saas_id. Tokens carry no TTL on their own — the caller is expected
to fold a TTL prefix in (e.g. ``f"{int(time.time()) // 60}|{nonce}"``)
if it needs one; the bridge stays minimal so its security review surface
is small.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from urllib.parse import urlencode

#: Length of the nonce portion of a state token, in bytes pre-encoding.
#: 32 bytes → 256 bits, comfortably above the 128-bit "collision-
#: improbable across the lifetime of the system" threshold.
_NONCE_BYTES: Final[int] = 32

#: Separator between nonce and HMAC inside the state-token string.
#: Period chosen for urlsafe-base64 compatibility — neither half ever
#: contains a period naturally.
_STATE_SEP: Final[str] = "."


@dataclass(frozen=True, slots=True)
class _ParsedToken:
    """Internal record returned by :func:`_split_token`."""

    nonce: str
    hmac_hex: str


def _split_token(token: str) -> _ParsedToken | None:
    """Split a ``nonce.hmac`` state token into its two halves.

    Returns ``None`` on any structural malformation so the caller can
    return a uniform "invalid" outcome without exception-handling
    branching.
    """
    parts = token.split(_STATE_SEP)
    if len(parts) != 2:
        return None
    nonce, hmac_hex = parts
    if not nonce or not hmac_hex:
        return None
    return _ParsedToken(nonce=nonce, hmac_hex=hmac_hex)


class OAuthBridge:
    """Build authorize URLs and verify state tokens for one host SaaS.

    The bridge holds:

    * An ``hmac_secret`` (per-deployment shared secret used to bind
      state tokens to the deployment). NEVER one of the host SaaS's
      OAuth credentials — only used to MAC nonces.

    The bridge does NOT:

    * Perform any HTTP request.
    * Receive or hold any access token.
    * Call any LLM SDK.

    Parameters
    ----------
    hmac_secret:
        Per-deployment shared secret for state-token HMAC. At least 32
        bytes recommended. The bridge encodes via UTF-8 so the secret
        may be any unicode string; high-entropy bytes (e.g. from a Fly
        secret) are still strongly preferred.
    """

    __slots__ = ("_secret",)

    def __init__(self, hmac_secret: str | bytes) -> None:
        secret_bytes = (
            hmac_secret.encode("utf-8") if isinstance(hmac_secret, str) else hmac_secret
        )
        if len(secret_bytes) < 16:
            raise ValueError(
                "hmac_secret must be at least 16 bytes (use a Fly secret, "
                "not a hard-coded short literal)"
            )
        self._secret = secret_bytes

    def mint_state(self, host_saas_id: str) -> str:
        """Mint a new state token bound to ``host_saas_id``.

        The nonce is cryptographically random; the HMAC binds it to the
        host so the same token cannot be replayed against a different
        host SaaS in the callback URL.
        """
        if not host_saas_id:
            raise ValueError("host_saas_id must be non-empty")
        nonce = secrets.token_urlsafe(_NONCE_BYTES)
        digest = self._hmac(host_saas_id, nonce)
        return f"{nonce}{_STATE_SEP}{digest}"

    def verify_state(self, host_saas_id: str, token: str) -> bool:
        """Verify a state token against ``host_saas_id``.

        Returns ``True`` iff the token's structure and HMAC are valid.
        Constant-time comparison via :func:`hmac.compare_digest` so the
        verify path does not leak the secret to a timing attacker.
        """
        if not host_saas_id or not token:
            return False
        parsed = _split_token(token)
        if parsed is None:
            return False
        expected = self._hmac(host_saas_id, parsed.nonce)
        return hmac.compare_digest(parsed.hmac_hex, expected)

    def build_authorize_url(
        self,
        *,
        authorize_endpoint: str,
        client_id: str,
        redirect_uri: str,
        state: str,
        scopes: tuple[str, ...] = (),
    ) -> str:
        """Build the URL the widget redirects the user's browser to.

        Parameters
        ----------
        authorize_endpoint:
            Host SaaS's OAuth authorize endpoint, e.g.
            ``"https://accounts.freee.co.jp/public_api/authorize"``. MUST
            start with ``https://``.
        client_id:
            Host SaaS's OAuth client_id (their own, not jpcite's).
        redirect_uri:
            Host SaaS's OAuth callback URL — must match the one
            registered with the host's OAuth provider.
        state:
            The state token, ideally one returned by :meth:`mint_state`.
        scopes:
            Tuple of OAuth scopes. Concatenated with a space, the
            conventional OAuth 2.0 separator.

        Returns
        -------
        str
            Fully-formed authorize URL ready for browser redirect.
        """
        if not authorize_endpoint.startswith("https://"):
            raise ValueError(
                f"authorize_endpoint must start with 'https://'; got {authorize_endpoint!r}"
            )
        if not redirect_uri.startswith("https://"):
            raise ValueError(
                f"redirect_uri must start with 'https://'; got {redirect_uri!r}"
            )
        if not client_id:
            raise ValueError("client_id must be non-empty")
        if not state:
            raise ValueError("state must be non-empty (mint via mint_state())")

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if scopes:
            params["scope"] = " ".join(scopes)

        return f"{authorize_endpoint}?{urlencode(params, doseq=False, safe='/:')}"

    def _hmac(self, host_saas_id: str, nonce: str) -> str:
        """Compute the HMAC-SHA256 hex digest for ``host_saas_id + nonce``.

        Internal helper — exposed only via :meth:`mint_state` and
        :meth:`verify_state`. The string formatting binds the host_saas_id
        and nonce with a literal ``":"`` so a smuggled colon in either
        half cannot collide with another (host_saas_id, nonce) pair.
        """
        msg = f"{host_saas_id}:{nonce}".encode()
        return hmac.new(self._secret, msg, sha256).hexdigest()


__all__ = ["OAuthBridge"]
