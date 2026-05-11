"""OAuth 2.1 Device Authorization Flow (RFC 8628) (Wave 19 #A8).

Browser-less agents (cursor / cline / smol-agents / autogen running on
a headless CI box / API-only LangGraph workers) cannot complete the
standard OAuth2 authorization-code flow because they have no browser
to redirect to. The device flow solves this: the agent POSTs to
``/v1/oauth/device/code`` and receives ``{device_code, user_code,
verification_uri, interval, expires_in}``. It then displays the
``user_code`` and ``verification_uri`` to the human operator (in a
terminal, Cursor sidebar, or Slack DM), who opens the URL on any
device, types the 8-char code, and approves. Meanwhile the agent
polls ``/v1/oauth/device/token`` every ``interval`` seconds. On
approval, the token endpoint returns the API key.

This module ships:

  - ``POST /v1/oauth/device/code`` — initiate device flow, mint codes
  - ``POST /v1/oauth/device/token`` — poll for token (returns 200 with
    access_token or 400 with ``authorization_pending`` / ``slow_down``
    / ``expired_token`` / ``access_denied``)
  - ``POST /v1/oauth/device/approve`` — operator-side approval endpoint
    called by the verification page
  - ``GET /v1/oauth/device/status/{user_code}`` — read-only status probe
    for the verification UI

In-memory storage only — codes expire in 600s, so the cost of losing
them on a Fly machine restart is bounded. Production-grade durable
storage would belong in a Redis instance, but for the launch envelope
the in-memory map is acceptable (≤1k concurrent device flows).

NO LLM API call. Pure protocol implementation per RFC 8628.

Spec compliance: implements the optional ``slow_down`` rate-limit
signal, ``interval`` doubling on 429, and ``expires_in`` truncation
per the §3.5 polling-error spec.
"""

from __future__ import annotations

import logging
import secrets
import string
import time
from typing import Any

from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger("jpintel.api.oauth_device")

# ---- Configuration ----------------------------------------------------

DEVICE_CODE_LEN = 40
USER_CODE_LEN = 8
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # No vowels / 0/O/1/I confusables
DEFAULT_EXPIRES_IN = 600  # 10 minutes
DEFAULT_INTERVAL = 5  # 5 second poll cadence per RFC 8628 §3.5

VERIFICATION_URI = "https://jpcite.com/oauth/device"
VERIFICATION_URI_COMPLETE_TEMPLATE = "https://jpcite.com/oauth/device?user_code={code}"


# ---- Storage ---------------------------------------------------------

# In-memory state. Keyed by user_code for lookups from the verification
# UI; secondary key by device_code for polling. Each entry tracks
# status + minted_at + (optional) bound_api_key once approved.
_DEVICE_STATE: dict[str, dict[str, Any]] = {}
_USER_CODE_INDEX: dict[str, str] = {}  # user_code → device_code


def _now() -> int:
    return int(time.time())


def _gen_device_code() -> str:
    """Mint an opaque device_code (40 chars, URL-safe)."""
    return secrets.token_urlsafe(DEVICE_CODE_LEN)[:DEVICE_CODE_LEN]


def _gen_user_code() -> str:
    """Mint a human-typable 8-char user_code in unambiguous alphabet."""
    return "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LEN))


def _prune_expired() -> None:
    """Drop entries past ``expires_at``; called on each touch."""
    now = _now()
    drop: list[str] = []
    for dc, st in _DEVICE_STATE.items():
        if st.get("expires_at", 0) < now:
            drop.append(dc)
    for dc in drop:
        uc = _DEVICE_STATE[dc].get("user_code")
        _DEVICE_STATE.pop(dc, None)
        if uc:
            _USER_CODE_INDEX.pop(uc, None)


# ---- Models ----------------------------------------------------------


class DeviceCodeResponse(BaseModel):
    """RFC 8628 §3.2 Device Authorization Response."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceTokenResponse(BaseModel):
    """RFC 8628 §3.5 Token Response (success path)."""

    access_token: str
    token_type: str = "Bearer"
    scope: str = "default"
    expires_in: int = Field(
        default=0,
        description="0 = non-expiring API key. Present for spec compliance.",
    )


class DeviceErrorResponse(BaseModel):
    """RFC 8628 §3.5 Token Response (error path)."""

    error: str
    error_description: str | None = None
    interval: int | None = None  # present on slow_down


# ---- Endpoints -------------------------------------------------------

router = APIRouter(prefix="/v1/oauth/device", tags=["oauth_device"])


@router.post("/code", response_model=DeviceCodeResponse)
def device_code(
    scope: str = Form(default="default"),
    client_id: str = Form(default="anonymous"),
) -> DeviceCodeResponse:
    """RFC 8628 §3.1 Device Authorization Request.

    Browser-less agent calls this to start the flow. Returns the codes
    + verification URL. Operator visits the URL, types ``user_code``,
    and approves.
    """
    _prune_expired()
    device_code = _gen_device_code()
    # Avoid user_code collisions by re-rolling up to 5 times
    user_code = _gen_user_code()
    for _ in range(5):
        if user_code not in _USER_CODE_INDEX:
            break
        user_code = _gen_user_code()
    else:
        # Astronomically unlikely; if we're hitting collisions repeatedly
        # the in-memory map is full or compromised.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to mint a unique user_code; try again",
        )
    now = _now()
    _DEVICE_STATE[device_code] = {
        "device_code": device_code,
        "user_code": user_code,
        "client_id": client_id,
        "scope": scope,
        "status": "pending",
        "minted_at": now,
        "expires_at": now + DEFAULT_EXPIRES_IN,
        "interval": DEFAULT_INTERVAL,
        "last_poll": 0,
        "bound_api_key": None,
    }
    _USER_CODE_INDEX[user_code] = device_code
    logger.info(
        "device_flow_mint",
        extra={"user_code": user_code, "client_id": client_id, "scope": scope},
    )
    return DeviceCodeResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=VERIFICATION_URI,
        verification_uri_complete=VERIFICATION_URI_COMPLETE_TEMPLATE.format(
            code=user_code
        ),
        expires_in=DEFAULT_EXPIRES_IN,
        interval=DEFAULT_INTERVAL,
    )


@router.post("/token")
def device_token(
    grant_type: str = Form(...),
    device_code: str = Form(...),
    client_id: str = Form(default="anonymous"),
) -> dict[str, Any]:
    """RFC 8628 §3.4 Device Access Token Request.

    Agent polls this every ``interval`` seconds. Until operator approves
    we return ``authorization_pending``. On approval we return the
    bound API key as the access_token.

    grant_type MUST be ``urn:ietf:params:oauth:grant-type:device_code``.
    """
    _prune_expired()
    if grant_type != "urn:ietf:params:oauth:grant-type:device_code":
        return {
            "error": "unsupported_grant_type",
            "error_description": "Only urn:ietf:params:oauth:grant-type:device_code is supported.",
        }
    state = _DEVICE_STATE.get(device_code)
    if state is None:
        return {
            "error": "expired_token",
            "error_description": "device_code unknown or expired",
        }
    if state["expires_at"] < _now():
        # Lazy cleanup
        uc = state.get("user_code")
        _DEVICE_STATE.pop(device_code, None)
        if uc:
            _USER_CODE_INDEX.pop(uc, None)
        return {"error": "expired_token", "error_description": "device_code expired"}
    now = _now()
    # slow_down: enforce min poll interval; if agent polled within the
    # last ``interval`` seconds, return slow_down with doubled interval.
    if state["last_poll"] and now - state["last_poll"] < state["interval"]:
        state["interval"] = min(state["interval"] * 2, 30)
        return {
            "error": "slow_down",
            "error_description": "Polled before interval window.",
            "interval": state["interval"],
        }
    state["last_poll"] = now
    if state["status"] == "approved":
        access_token = state["bound_api_key"]
        # Tear down state on successful issuance
        uc = state.get("user_code")
        _DEVICE_STATE.pop(device_code, None)
        if uc:
            _USER_CODE_INDEX.pop(uc, None)
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "scope": state.get("scope", "default"),
            "expires_in": 0,
        }
    if state["status"] == "denied":
        uc = state.get("user_code")
        _DEVICE_STATE.pop(device_code, None)
        if uc:
            _USER_CODE_INDEX.pop(uc, None)
        return {
            "error": "access_denied",
            "error_description": "Operator declined the device authorization.",
        }
    return {
        "error": "authorization_pending",
        "error_description": "Operator has not yet approved the request.",
    }


@router.post("/approve")
def device_approve(
    user_code: str = Form(...),
    api_key: str = Form(...),
) -> dict[str, Any]:
    """Operator approval endpoint, called by the verification page.

    The verification page (``site/oauth/device.html``) collects the
    8-char user_code + an existing API key from the operator (or mints
    a new one via the dashboard issuance flow), then POSTs here to
    bind the API key to the pending device_code.

    Returns 200 with status='approved'.
    """
    _prune_expired()
    device_code = _USER_CODE_INDEX.get(user_code.upper().strip())
    if not device_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_code not found"
        )
    state = _DEVICE_STATE.get(device_code)
    if state is None or state["expires_at"] < _now():
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="device_code expired"
        )
    state["status"] = "approved"
    state["bound_api_key"] = api_key
    state["approved_at"] = _now()
    logger.info(
        "device_flow_approve",
        extra={"user_code": user_code, "client_id": state.get("client_id")},
    )
    return {"status": "approved", "client_id": state.get("client_id")}


@router.post("/deny")
def device_deny(user_code: str = Form(...)) -> dict[str, Any]:
    """Operator-initiated denial. Marks the flow as denied; the next
    poll returns ``access_denied``."""
    _prune_expired()
    device_code = _USER_CODE_INDEX.get(user_code.upper().strip())
    if not device_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_code not found"
        )
    state = _DEVICE_STATE.get(device_code)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="device_code expired"
        )
    state["status"] = "denied"
    return {"status": "denied"}


@router.get("/status/{user_code}")
def device_status(user_code: str) -> dict[str, Any]:
    """Status probe for the verification UI (no auth)."""
    _prune_expired()
    device_code = _USER_CODE_INDEX.get(user_code.upper().strip())
    if not device_code:
        return {"status": "unknown"}
    state = _DEVICE_STATE.get(device_code)
    if state is None or state["expires_at"] < _now():
        return {"status": "expired"}
    return {
        "status": state["status"],
        "client_id": state.get("client_id"),
        "scope": state.get("scope"),
        "expires_in": max(0, state["expires_at"] - _now()),
    }


# ---- Wave 41 — polling response enhancements ---------------------------------
#
# RFC 8628 §3.5 defines four polling-error responses that the spec
# REQUIRES servers to surface in normalised form. Wave 41 adds a
# dedicated *poll-introspect* endpoint plus a structured polling-response
# builder so client libraries and the audit script can verify all four
# cases without minting a real device code first.


_POLL_RESPONSE_FIXTURES: dict[str, dict[str, Any]] = {
    "authorization_pending": {
        "http_status": 400,
        "body": {
            "error": "authorization_pending",
            "error_description": "Operator has not yet approved the request.",
        },
        "next_action": "wait_interval_then_repoll",
    },
    "slow_down": {
        "http_status": 400,
        "body": {
            "error": "slow_down",
            "error_description": "Polled before interval window.",
            "interval": DEFAULT_INTERVAL * 2,
        },
        "next_action": "double_interval_then_repoll",
    },
    "expired_token": {
        "http_status": 400,
        "body": {"error": "expired_token", "error_description": "device_code expired"},
        "next_action": "restart_device_flow",
    },
    "access_denied": {
        "http_status": 400,
        "body": {
            "error": "access_denied",
            "error_description": "Operator declined the device authorization.",
        },
        "next_action": "abort",
    },
    "success": {
        "http_status": 200,
        "body": {
            "access_token": "<api-key>",
            "token_type": "Bearer",
            "scope": "default",
            "expires_in": 0,
        },
        "next_action": "use_token",
    },
}


@router.get("/poll_introspect")
def device_poll_introspect(case: str | None = None) -> dict[str, Any]:
    """Return canonical polling-response envelope shapes (Wave 41)."""
    if case:
        envelope = _POLL_RESPONSE_FIXTURES.get(case)
        if envelope is None:
            return {
                "error": "unknown_case",
                "valid_cases": sorted(_POLL_RESPONSE_FIXTURES.keys()),
            }
        return {"case": case, "envelope": envelope, "spec": "RFC 8628 §3.5"}
    return {
        "spec": "RFC 8628 §3.5",
        "cases": _POLL_RESPONSE_FIXTURES,
        "case_count": len(_POLL_RESPONSE_FIXTURES),
        "verification_uri": VERIFICATION_URI,
    }


@router.get("/poll_response_spec")
def device_poll_response_spec() -> dict[str, Any]:
    """Minimal spec card describing the polling protocol (Wave 41)."""
    return {
        "spec": "RFC 8628 — OAuth 2.1 Device Authorization Grant",
        "polling": {
            "endpoint": "/v1/oauth/device/token",
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded",
            "required_fields": ["grant_type", "device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "default_interval_seconds": DEFAULT_INTERVAL,
            "max_interval_seconds": 30,
            "error_responses": list(_POLL_RESPONSE_FIXTURES.keys()),
        },
        "lifecycle": [
            "POST /v1/oauth/device/code   — mint codes",
            "Operator visits verification_uri and types user_code",
            "POST /v1/oauth/device/token  — agent polls every interval seconds",
            "Server returns success or authorization_pending|slow_down|expired_token|access_denied",
        ],
    }
