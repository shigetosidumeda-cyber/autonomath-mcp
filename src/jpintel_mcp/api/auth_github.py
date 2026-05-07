"""GitHub OAuth sign-in flow — ``/v1/auth/github/{start,callback}``.

Mirrors the Google OAuth pattern in ``api/integrations.py`` but is a
pre-authentication sign-in surface (callers do NOT need an API key to
initiate). Scopes are limited to ``read:user user:email`` so we only
read the GitHub-side identity (login + email) and never write back to
the user's GitHub account.

Operator setup (production secrets already deployed 2026-05-07):

* ``GITHUB_OAUTH_CLIENT_ID``  / ``GITHUB_OAUTH_CLIENT_SECRET`` env vars
  (Fly secrets — deployed). Without both, ``/v1/auth/github/start``
  returns 503 with the same shape as Google's unconfigured branch.
* GitHub OAuth App "Authorization callback URL" =
  ``https://api.jpcite.com/v1/auth/github/callback``
  (override per env via ``JPINTEL_API_BASE_URL``).

Flow:

1. ``GET /v1/auth/github/start`` — issues a one-time ``state`` nonce,
   stores it in ``integration_sync_log`` (UNIQUE provider+idempotency_key
   guards replay), and 302-redirects to GitHub's authorize page. Returns
   ``200 {authorize_url, state, expires_in}`` for callers that prefer
   JSON (``Accept: application/json``) over a browser redirect.
2. ``GET /v1/auth/github/callback`` — exchanges ``code`` for an access
   token at ``https://github.com/login/oauth/access_token``, fetches
   ``GET /user`` + ``GET /user/emails`` from GitHub's REST API, deletes
   the one-shot state row, and 302-redirects to the dashboard with a
   short-lived ``github_login`` query param OR returns 200 JSON with the
   GitHub identity payload.

Storage:

* The ``state`` nonce + IP is stored in ``integration_sync_log`` with
  provider=``'github_oauth_state'`` (the column has no CHECK constraint
  on ``provider``, free text). ``api_key_hash`` is a synthetic
  ``"anon:<nonce-prefix>"`` so the NOT NULL constraint passes — the
  pre-auth sign-in does not yet have a real api_key_hash.
* The exchanged GitHub token is **NOT** persisted at this stage. Sign-in
  identity flows downstream into the dashboard / signup linker; long-
  lived persistence (refresh into ``integration_accounts``) requires a
  separate migration to extend the ``provider`` CHECK constraint and is
  out of scope for the router-register step.

Per project memory (Solo + zero-touch): there is no human approval
loop — the customer self-completes the consent on github.com and we
read back identity, that's it.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.parse
import urllib.request
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 — FastAPI Depends needs runtime import

logger = logging.getLogger("jpintel.auth.github")

router = APIRouter(prefix="/v1/auth/github", tags=["auth"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# GitHub OAuth endpoints (web application flow). Documented at
# https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
_GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
_GITHUB_USER = "https://api.github.com/user"
_GITHUB_USER_EMAILS = "https://api.github.com/user/emails"

# Limited to identity read-only. We never request ``repo`` / ``write:*``
# / ``admin:*`` so even a token leak cannot mutate the user's GitHub.
_GITHUB_SCOPES = "read:user user:email"

# Synthetic hash prefix so the NOT NULL ``api_key_hash`` column on
# ``integration_sync_log`` accepts the pre-auth state row. The real
# api_key_hash is unknown at OAuth-start time (sign-in flow runs before
# any /v1/me/keys exists for the caller).
_ANON_HASH_PREFIX = "anon:gh_oauth:"


def _redirect_uri() -> str:
    """Resolve the GitHub OAuth callback URL.

    Honours ``JPINTEL_API_BASE_URL`` so dev / staging / prod each point
    at their own callback. Default is the production apex.
    """
    base = os.environ.get("JPINTEL_API_BASE_URL", "https://api.jpcite.com").rstrip("/")
    return f"{base}/v1/auth/github/callback"


def _dashboard_url() -> str:
    """Resolve the post-callback redirect target."""
    return os.environ.get("JPINTEL_DASHBOARD_URL", "https://jpcite.com/dashboard.html")


def _client_id_or_503() -> str:
    cid = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip()
    if not cid:
        # 503 (not 500) so the dashboard renders "operator must finish
        # setup" instead of an opaque traceback. Mirrors Google's
        # unconfigured branch.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GitHub OAuth not configured (operator must set GITHUB_OAUTH_CLIENT_ID)",
        )
    return cid


def _client_secret_or_503() -> str:
    cs = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip()
    if not cs:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GitHub OAuth not configured (operator must set GITHUB_OAUTH_CLIENT_SECRET)",
        )
    return cs


# ---------------------------------------------------------------------------
# /v1/auth/github/start — issue state nonce, redirect to GitHub authorize
# ---------------------------------------------------------------------------


@router.get(
    "/start",
    summary="Begin GitHub OAuth sign-in",
    description=(
        "Generates a one-time ``state`` nonce + stores it server-side, "
        "then issues a redirect to GitHub's ``/login/oauth/authorize``. "
        "Caller pass ``Accept: application/json`` to receive the URL as "
        "JSON instead of a 302 (e.g. dashboard JS that wants to render "
        "the link in a button). Requires no API key — this is the "
        "pre-auth sign-in surface."
    ),
)
async def github_oauth_start(
    request: Request,
    db: DbDep,
    accept: Annotated[str | None, Query(alias="format")] = None,
) -> Response:
    client_id = _client_id_or_503()

    # 32-byte state nonce; 256 bits is well above the 128-bit floor in
    # GitHub's OAuth guide and survives URL-encoding without truncation.
    nonce = secrets.token_urlsafe(32)
    anon_hash = f"{_ANON_HASH_PREFIX}{nonce[:16]}"

    db.execute(
        """
        INSERT INTO integration_sync_log
            (api_key_hash, provider, idempotency_key, status, result_count)
        VALUES (?, 'github_oauth_state', ?, 'pending', 0)
        """,
        (anon_hash, nonce),
    )
    db.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "scope": _GITHUB_SCOPES,
        "state": nonce,
        "allow_signup": "true",
    }
    authorize_url = f"{_GITHUB_AUTHORIZE}?{urllib.parse.urlencode(params)}"

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
# /v1/auth/github/callback — exchange code, fetch identity
# ---------------------------------------------------------------------------


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """POST to GitHub's token endpoint and return the parsed JSON.

    GitHub returns ``application/x-www-form-urlencoded`` by default; we
    set ``Accept: application/json`` so the response is parseable JSON.
    """
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _redirect_uri(),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _GITHUB_TOKEN,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "jpcite-oauth/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint
        return cast("dict[str, Any]", _parse_json_payload(resp.read()))


def _fetch_identity(access_token: str) -> dict[str, Any]:
    """Pull ``GET /user`` + ``GET /user/emails`` for the signed-in user."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "jpcite-oauth/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    user_req = urllib.request.Request(_GITHUB_USER, headers=headers)
    with urllib.request.urlopen(user_req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint
        user = _parse_json_payload(resp.read())
    if not isinstance(user, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "github /user returned non-object")

    emails: list[dict[str, Any]] = []
    try:
        emails_req = urllib.request.Request(_GITHUB_USER_EMAILS, headers=headers)
        with urllib.request.urlopen(emails_req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint
            payload = _parse_json_payload(resp.read())
            if isinstance(payload, list):
                emails = [e for e in payload if isinstance(e, dict)]
    except Exception:  # noqa: BLE001 — emails scope optional
        logger.warning("github_oauth.user_emails.fetch_failed", exc_info=True)

    primary = next(
        (e.get("email") for e in emails if e.get("primary") and e.get("verified")),
        None,
    )
    return {
        "login": user.get("login"),
        "id": user.get("id"),
        "name": user.get("name"),
        "avatar_url": user.get("avatar_url"),
        "email": primary or user.get("email"),
        "emails": [{"email": e.get("email"), "verified": bool(e.get("verified"))} for e in emails],
    }


def _parse_json_payload(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("github_oauth.json_decode_failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "github returned a non-JSON payload",
        ) from exc


@router.get(
    "/callback",
    summary="GitHub OAuth callback",
    description=(
        "GitHub redirects here after the user grants consent. Exchanges "
        "the ``code`` for a short-lived access token, fetches the "
        "GitHub identity (login + email), discards the access token "
        "(no persistence), and redirects to the dashboard with the "
        "GitHub login as a query param. JSON-mode (``?format=json``) "
        "returns the identity payload directly."
    ),
)
async def github_oauth_callback(
    request: Request,
    db: DbDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    error: Annotated[str | None, Query()] = None,
    format: Annotated[str | None, Query()] = None,  # noqa: A002 — public query param
) -> Response:
    if error:
        # User clicked "Cancel" on GitHub's consent screen, OR GitHub
        # rejected the OAuth app config. Either way, surface a 400 with
        # the upstream reason verbatim so the operator can debug without
        # a server-side log dive.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"github oauth error: {error}",
        )

    client_id = _client_id_or_503()
    client_secret = _client_secret_or_503()

    # Validate state nonce against the row planted in /start. The row's
    # synthetic api_key_hash MUST start with the nonce-prefix so a
    # cross-flow replay (Google state injected into GitHub callback)
    # cannot pass.
    state_row = db.execute(
        "SELECT api_key_hash FROM integration_sync_log "
        "WHERE provider = 'github_oauth_state' AND idempotency_key = ?",
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

    # Exchange code for access token.
    try:
        tok = _exchange_code(code, client_id, client_secret)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("github_oauth.exchange_failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"github token exchange failed: {type(exc).__name__}",
        ) from exc

    if isinstance(tok, dict) and tok.get("error"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"github oauth: {tok.get('error')} ({tok.get('error_description', '')})",
        )

    access_token = (tok or {}).get("access_token") if isinstance(tok, dict) else None
    if not access_token or not isinstance(access_token, str):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "github did not return access_token",
        )

    try:
        identity = _fetch_identity(access_token)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("github_oauth.identity_fetch_failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"github identity fetch failed: {type(exc).__name__}",
        ) from exc

    # Drop the one-shot state row so the same nonce cannot replay.
    db.execute(
        "DELETE FROM integration_sync_log "
        "WHERE provider = 'github_oauth_state' AND idempotency_key = ?",
        (state,),
    )
    db.commit()

    # JSON-mode for SDK / dashboard JS callers.
    accept_header = (request.headers.get("accept") or "").lower()
    wants_json = (format or "").lower() == "json" or "application/json" in accept_header
    if wants_json:
        return JSONResponse(
            content={
                "ok": True,
                "provider": "github",
                "identity": identity,
                "scopes": _GITHUB_SCOPES,
            }
        )

    # Default: redirect to dashboard with the GitHub login (no token,
    # no PII beyond the public username) so the front-end can prompt
    # for next-step linking against an existing api_key or sign-up.
    login = identity.get("login") or ""
    redirect_target = f"{_dashboard_url()}#github_login={urllib.parse.quote(str(login), safe='')}"
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)


__all__ = ["router"]
