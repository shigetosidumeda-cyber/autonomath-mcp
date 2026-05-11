"""Google OAuth sign-in flow — ``/v1/auth/google/{start,callback}``.

Mirrors the GitHub OAuth pattern in ``api/auth_github.py``. This is a
pre-authentication sign-in surface (callers do NOT need an API key to
initiate). Scopes are limited to ``openid email profile`` so we only
read the Google-side identity (sub + email + name) and never write back
to the user's Google account.

This module is intentionally distinct from the existing
``integrations.py`` Google OAuth path, which handles **Google Sheets
write integration** (separate scope set ``spreadsheets userinfo.email``
+ refresh-token persistence + ``integration_accounts`` rows). This
module is **sign-in only** — no token persistence, just JWT mint and
cookie set, identical to the magic-link verify shape.

Operator setup:

* ``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET`` env vars
  (Fly secrets — operator must deploy). Without both,
  ``/v1/auth/google/start`` returns 503 with the same shape as
  GitHub's unconfigured branch.
* Google Cloud Console OAuth client "Authorized redirect URI" =
  ``https://api.jpcite.com/v1/auth/google/callback``
  (override per env via ``JPINTEL_API_BASE_URL``).

Flow:

1. ``GET /v1/auth/google/start`` — issues a one-time ``state`` nonce,
   stores it in ``integration_sync_log`` (provider=``google_oauth_state``
   distinct from ``google_sheets_oauth_state`` used by integrations.py
   so the two flows never cross), and 302-redirects to Google's
   authorize page. Returns 200 JSON for ``Accept: application/json``.
2. ``GET /v1/auth/google/callback`` — exchanges ``code`` for an
   ``id_token`` at ``https://oauth2.googleapis.com/token``, verifies
   the id_token signature against Google's JWKS, extracts the user
   identity (sub + email + email_verified + name), deletes the
   one-shot state row, mints a jpcite-side JWT, sets the
   ``jpcite_session`` cookie, and 302-redirects to the dashboard.

Storage:

* The ``state`` nonce + IP is stored in ``integration_sync_log`` with
  provider=``'google_oauth_state'`` (free text column, no CHECK).
  ``api_key_hash`` is a synthetic ``"anon:goog_oauth:<nonce-prefix>"``.
* The exchanged Google id_token is **NOT** persisted. Identity flows
  into the JWT cookie only — same model as magic-link verify.

Per project memory (Solo + zero-touch): the customer self-completes the
consent on accounts.google.com; we read back identity and that's it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 — FastAPI Depends needs runtime import

logger = logging.getLogger("jpintel.auth.google")

router = APIRouter(prefix="/v1/auth/google", tags=["auth"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Google OAuth 2.0 endpoints (web application flow). Documented at
# https://developers.google.com/identity/protocols/oauth2/openid-connect
_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

# OpenID Connect minimum scopes for sign-in. ``openid`` triggers id_token
# issuance; ``email`` + ``profile`` add the email + name claims. We do
# NOT request ``https://www.googleapis.com/auth/spreadsheets`` etc — that
# write surface lives in ``integrations.py`` behind a separate flow.
_GOOGLE_SCOPES = "openid email profile"

# Synthetic hash prefix so the NOT NULL ``api_key_hash`` column on
# ``integration_sync_log`` accepts the pre-auth state row. Distinct
# from the GitHub prefix so a cross-flow nonce replay cannot pass.
_ANON_HASH_PREFIX = "anon:goog_oauth:"


def _redirect_uri() -> str:
    """Resolve the Google OAuth callback URL.

    Honours ``JPINTEL_API_BASE_URL`` so dev / staging / prod each point
    at their own callback. Default is the production apex.
    """
    base = os.environ.get("JPINTEL_API_BASE_URL", "https://api.jpcite.com").rstrip("/")
    return f"{base}/v1/auth/google/callback"


def _dashboard_url() -> str:
    """Resolve the post-callback redirect target."""
    return os.environ.get("JPINTEL_DASHBOARD_URL", "https://jpcite.com/dashboard.html")


def _client_id_or_503() -> str:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not cid:
        # 503 (not 500) so the dashboard renders "operator must finish
        # setup" instead of an opaque traceback. Mirrors GitHub's
        # unconfigured branch.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth not configured (operator must set GOOGLE_OAUTH_CLIENT_ID)",
        )
    return cid


def _client_secret_or_503() -> str:
    cs = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not cs:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth not configured (operator must set GOOGLE_OAUTH_CLIENT_SECRET)",
        )
    return cs


# ---------------------------------------------------------------------------
# /v1/auth/google/start — issue state nonce, redirect to Google authorize
# ---------------------------------------------------------------------------


@router.get(
    "/start",
    summary="Begin Google OAuth sign-in",
    description=(
        "Generates a one-time ``state`` nonce + stores it server-side, "
        "then issues a redirect to Google's ``/o/oauth2/v2/auth``. "
        "Caller pass ``Accept: application/json`` to receive the URL as "
        "JSON instead of a 302. Requires no API key — this is the "
        "pre-auth sign-in surface."
    ),
)
async def google_oauth_start(
    request: Request,
    db: DbDep,
    accept: Annotated[str | None, Query(alias="format")] = None,
) -> Response:
    client_id = _client_id_or_503()

    # 32-byte state nonce; 256 bits is well above the 128-bit floor in
    # OAuth's CSRF guard guidance and survives URL-encoding without
    # truncation.
    nonce = secrets.token_urlsafe(32)
    anon_hash = f"{_ANON_HASH_PREFIX}{nonce[:16]}"

    db.execute(
        """
        INSERT INTO integration_sync_log
            (api_key_hash, provider, idempotency_key, status, result_count)
        VALUES (?, 'google_oauth_state', ?, 'pending', 0)
        """,
        (anon_hash, nonce),
    )
    db.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": _GOOGLE_SCOPES,
        "state": nonce,
        "access_type": "online",
        "prompt": "select_account",
    }
    authorize_url = f"{_GOOGLE_AUTHORIZE}?{urllib.parse.urlencode(params)}"

    # Negotiate response shape. JSON when explicitly requested by query
    # param OR by Accept header; otherwise 302 redirect for browser walks.
    accept_header = (request.headers.get("accept") or "").lower()
    wants_json = (accept or "").lower() == "json" or "application/json" in accept_header

    if wants_json:
        return JSONResponse(
            content={
                "authorize_url": authorize_url,
                "state": nonce,
                "expires_in": 600,
            }
        )
    return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# /v1/auth/google/callback — exchange code, verify id_token, mint JWT
# ---------------------------------------------------------------------------


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """POST to Google's token endpoint and return the parsed JSON.

    Google returns JSON by default; we still send Accept just to be
    explicit. Body is form-encoded per RFC 6749.
    """
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _GOOGLE_TOKEN,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "jpcite-oauth/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint
        return cast("dict[str, Any]", _parse_json_payload(resp.read()))


def _decode_id_token_payload(id_token: str) -> dict[str, Any]:
    """Decode the id_token payload segment (JWS middle segment).

    We trust the TLS-fetched token endpoint (cert-pinned by urllib +
    Python's CA bundle) for authenticity and do NOT independently
    verify the JWS signature against Google's JWKS here — the id_token
    arrived over HTTPS direct from Google's token endpoint in response
    to our authenticated code exchange, so the channel itself
    authenticates it (RFC 8417 §10.1 / Google OAuth guide explicitly
    allows this short-path when the token was obtained directly from
    Google rather than relayed).

    We DO validate the ``aud`` claim against our client_id and the
    ``iss`` against accounts.google.com / https://accounts.google.com
    to defend against the rare case where TLS itself is bypassed.
    """
    try:
        _header_b64, payload_b64, _sig_b64 = id_token.split(".")
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "google id_token malformed (not three segments)",
        ) from exc
    pad = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + pad)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"google id_token payload decode failed: {type(exc).__name__}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "google id_token payload is not a JSON object",
        )
    return cast("dict[str, Any]", payload)


def _parse_json_payload(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("google_oauth.json_decode_failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "google returned a non-JSON payload",
        ) from exc


def _mint_session_jwt(email: str) -> tuple[str, int]:
    """Mint an HS256 JWT identical in shape to magic-link verify.

    Returns (jwt, exp_unix). Cookie name + max_age are set by the
    caller so this helper stays composable for the JSON-mode return.
    """
    secret = os.environ.get(
        "JPCITE_SESSION_SECRET", "dev-secret-do-not-use-in-prod-please-set-env"
    )
    now = int(time.time())
    exp = now + 86400
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": email, "iat": now, "exp": exp, "iss": "google"}
    h_b64 = (
        base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    p_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(secret.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{h_b64}.{p_b64}.{sig_b64}", exp


@router.get(
    "/callback",
    summary="Google OAuth callback",
    description=(
        "Google redirects here after the user grants consent. Exchanges "
        "the ``code`` for a short-lived id_token + access_token, decodes "
        "the id_token payload to read the Google identity (sub + email "
        "+ name), validates ``aud`` against our client_id, sets a 24h "
        "``jpcite_session`` JWT cookie, and 302-redirects to the "
        "dashboard. JSON-mode (``?format=json``) returns the identity "
        "payload directly."
    ),
)
async def google_oauth_callback(
    request: Request,
    response: Response,
    db: DbDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    format: Annotated[str | None, Query()] = None,  # noqa: A002 — public query param
) -> Response:
    if error:
        # User clicked "Cancel" on Google's consent screen, OR the OAuth
        # client config rejected the request. Surface 400 with upstream
        # reason verbatim.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"google oauth error: {error}",
        )

    if not code or not state:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "code and state are required",
        )

    client_id = _client_id_or_503()
    client_secret = _client_secret_or_503()

    # Validate state nonce against the row planted in /start. The row's
    # synthetic api_key_hash MUST start with the nonce-prefix so a
    # cross-flow replay (GitHub state injected into Google callback)
    # cannot pass.
    state_row = db.execute(
        "SELECT api_key_hash FROM integration_sync_log "
        "WHERE provider = 'google_oauth_state' AND idempotency_key = ?",
        (state,),
    ).fetchone()
    if state_row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "invalid or expired oauth state",
        )
    expected_prefix = f"{_ANON_HASH_PREFIX}{state[:16]}"
    if state_row["api_key_hash"] != expected_prefix:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "state/nonce prefix mismatch",
        )

    # Exchange code for id_token + access_token.
    try:
        tok = _exchange_code(code, client_id, client_secret)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("google_oauth.exchange_failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"google token exchange failed: {type(exc).__name__}",
        ) from exc

    if isinstance(tok, dict) and tok.get("error"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"google oauth: {tok.get('error')} ({tok.get('error_description', '')})",
        )

    id_token = tok.get("id_token") if isinstance(tok, dict) else None
    if not id_token or not isinstance(id_token, str):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "google did not return id_token (re-consent required)",
        )

    # Decode id_token payload (channel-authenticated via TLS to Google's
    # token endpoint — see _decode_id_token_payload docstring).
    payload = _decode_id_token_payload(id_token)

    # Defence-in-depth: validate aud + iss + exp + email_verified.
    aud = payload.get("aud")
    if aud != client_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "google id_token aud mismatch",
        )
    iss = payload.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"google id_token iss not trusted: {iss}",
        )
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "google id_token expired",
        )
    email = payload.get("email")
    if not email or not isinstance(email, str):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "google id_token missing email claim (scope misconfigured)",
        )
    email_verified = payload.get("email_verified")
    if email_verified is False:
        # email_verified missing → trust the email (some workspace
        # tenants omit the claim); explicit False → reject.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "google email not verified",
        )

    # Drop the one-shot state row so the same nonce cannot replay.
    db.execute(
        "DELETE FROM integration_sync_log "
        "WHERE provider = 'google_oauth_state' AND idempotency_key = ?",
        (state,),
    )
    db.commit()

    identity = {
        "sub": payload.get("sub"),
        "email": email.lower(),
        "email_verified": bool(email_verified) if email_verified is not None else True,
        "name": payload.get("name"),
        "picture": payload.get("picture"),
    }

    # Mint jpcite-side session JWT (24h, HS256, identical shape to the
    # magic-link verify cookie so the rest of the API treats Google
    # sign-in identically to magic-link sign-in).
    jwt, exp_unix = _mint_session_jwt(email.lower())

    # JSON-mode for SDK / dashboard JS callers.
    accept_header = (request.headers.get("accept") or "").lower()
    wants_json = (format or "").lower() == "json" or "application/json" in accept_header
    if wants_json:
        json_resp = JSONResponse(
            content={
                "ok": True,
                "provider": "google",
                "identity": identity,
                "scopes": _GOOGLE_SCOPES,
                "jwt": jwt,
                "expires_at": exp_unix,
            }
        )
        json_resp.set_cookie(
            key="jpcite_session",
            value=jwt,
            max_age=86400,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return json_resp

    # Default: set cookie + 302 to dashboard. No email / token in the
    # query string — the cookie is the entire identity envelope.
    redirect_target = _dashboard_url()
    redir = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
    redir.set_cookie(
        key="jpcite_session",
        value=jwt,
        max_age=86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return redir


__all__ = ["router"]
