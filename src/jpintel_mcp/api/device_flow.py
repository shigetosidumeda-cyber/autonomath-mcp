"""OAuth 2.0 Device Authorization Grant (RFC 8628) for MCP / CLI clients.

Eliminates config-editing friction: instead of the user copying an API key
and editing `claude_desktop_config.json`, the MCP server opens a device
code, shows a short URL + human-readable user_code, polls until the user
finishes Stripe Checkout on that URL, and stores the issued API key in
the OS keychain automatically.

Endpoints (mounted under /v1/device/*; this router is NOT wired into
main.py from this module — main.py owns the include_router call):

    POST /v1/device/authorize  -> mint (device_code, user_code)
    POST /v1/device/token      -> client poll; RFC 8628 error codes
    POST /v1/device/complete   -> called by /go page on Stripe success

RFC 8628 compliance notes:
    - `interval` tells the client the min poll interval (seconds). We send 5.
    - `authorization_pending` = code still pending; client keeps polling.
    - `slow_down` = client is polling faster than `interval` + fudge;
      client MUST add 5s to its interval.
    - `expired_token` = code timed out; client must restart `/authorize`.
    - `access_denied` = user explicitly denied.

Security:
    - device_code is 64 hex chars (32 bytes from os.urandom via secrets).
    - user_code avoids ambiguous chars (0/O, 1/I/L).
    - /token is rate limited to 10 polls/min per device_code.
    - /complete verifies the Stripe session server-side, then marks
      activated. Client never reports "I paid" unilaterally.
    - Origin check on /complete: must come from the configured site host
      (jpcite.com) — CSRF mitigation.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import stripe
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import DbDep, hash_api_key, hash_api_key_bcrypt
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.device_flow")

# NOTE: main.py owns the include_router wiring. Expose `router` here so
# main.py can do `from jpintel_mcp.api.device_flow import router as device_router`.
router = APIRouter(prefix="/v1/device", tags=["device"])


# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #

# Device code lives 15 min per RFC 8628 recommendation.
DEVICE_CODE_TTL_SECONDS = 15 * 60

# Default polling interval sent to clients. Clients should respect this.
DEFAULT_POLL_INTERVAL_SECONDS = 5

# Poll rate cap per device_code (slow_down trigger). 10/min matches the
# RFC's expected "slow_down adds 5s" adversary model.
MAX_POLLS_PER_MINUTE = 10

# user_code alphabet — no ambiguous chars (0/O, 1/I/L).
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_USER_CODE_LENGTH = 8  # 8 chars + one dash → "ABCD-1234"

# Host for verification URIs. Uses the canonical site host; overridable via
# env if deployed under a different domain.
_SITE_BASE = "https://jpcite.com"

# Grant type value required by RFC 8628.
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

# Allowed Origin hosts for /complete (CSRF mitigation).
_ALLOWED_COMPLETE_ORIGINS = frozenset(
    {
        "https://jpcite.com",
        "https://www.jpcite.com",
    }
)

_SESSION_METADATA_DEVICE_CODE = "device_code"
_SESSION_METADATA_USER_CODE = "user_code"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _generate_device_code() -> str:
    """64 hex chars (32 random bytes). Opaque, never user-typed."""
    return secrets.token_hex(32)


def _generate_user_code() -> str:
    """Short human-typeable code, e.g. 'ABCD-1234'.

    Caller is responsible for UNIQUE retry on collision (DB constraint will
    raise; we retry a handful of times). 8 chars over a 32-symbol alphabet
    = 32^8 ≈ 10^12 — comfortably collision-free within a 15 min window.
    """
    chars = [secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_LENGTH)]
    return "".join(chars[:4]) + "-" + "".join(chars[4:])


def _fingerprint(raw: str | None) -> str | None:
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _stripe_ready() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stripe not configured",
        )
    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version


def _expire_stale(conn: sqlite3.Connection) -> None:
    """Mark any pending rows whose expires_at < now as 'expired'.

    Called inline from /token so no cron is strictly required. Bounded by
    the 15-min window × request rate; SQLite handles this comfortably
    without a dedicated index seek for a small table. The idx_device_codes_expires
    index keeps it fast as the table grows.
    """
    now = _now_utc_iso()
    try:
        conn.execute(
            "UPDATE device_codes SET status='expired' WHERE status='pending' AND expires_at < ?",
            (now,),
        )
    except sqlite3.Error:
        # Fail-open: a broken sweep must not break the poll path.
        logger.warning("device_codes sweep failed", exc_info=True)


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _line_item_data(line_items: Any) -> list[Any]:
    if line_items is None:
        return []
    if isinstance(line_items, list):
        return line_items
    data = _obj_get(line_items, "data")
    if isinstance(data, list):
        return data
    return []


def _price_ids_from_line_items(line_items: Any) -> set[str]:
    price_ids: set[str] = set()
    for item in _line_item_data(line_items):
        price = _obj_get(item, "price")
        price_id = price if isinstance(price, str) else _obj_get(price, "id")
        if price_id:
            price_ids.add(str(price_id))
    return price_ids


def _checkout_session_price_ids(session_id: str, session: Any) -> set[str]:
    """Return Checkout line-item price ids from an expanded session.

    `Session.retrieve(..., expand=["line_items"])` is the normal path. The
    fallback keeps the verification robust if Stripe omits the expansion.
    """
    price_ids = _price_ids_from_line_items(_obj_get(session, "line_items"))
    if price_ids:
        return price_ids
    line_items = stripe.checkout.Session.list_line_items(session_id, limit=100)
    return _price_ids_from_line_items(line_items)


def _expected_livemode() -> bool:
    return settings.env == "prod"


def _require_checkout_session_for_device(
    *,
    session_id: str,
    session: Any,
    expected_device_code: str,
    expected_user_code: str,
) -> tuple[str, str]:
    """Validate the Stripe Checkout session before any paid key is issued."""
    if _obj_get(session, "id", session_id) != session_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "checkout session id mismatch",
        )

    if _obj_get(session, "status") != "complete":
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "checkout session not complete",
        )

    if _obj_get(session, "mode") != "subscription":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "checkout session is not a subscription",
        )

    actual_livemode = _obj_get(session, "livemode")
    if not isinstance(actual_livemode, bool) or actual_livemode != _expected_livemode():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "checkout session livemode mismatch",
        )

    metadata = _as_dict(_obj_get(session, "metadata"))
    metadata_device_code = str(metadata.get(_SESSION_METADATA_DEVICE_CODE) or "")
    metadata_user_code = str(metadata.get(_SESSION_METADATA_USER_CODE) or "")
    if not (
        secrets.compare_digest(metadata_device_code, expected_device_code)
        and secrets.compare_digest(metadata_user_code, expected_user_code)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "checkout session metadata mismatch",
        )

    expected_price = settings.stripe_price_per_request
    if not expected_price:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "billing not configured",
        )
    price_ids = _checkout_session_price_ids(session_id, session)
    if price_ids != {expected_price}:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "checkout session price mismatch",
        )

    if _obj_get(session, "payment_status") not in ("paid", "no_payment_required"):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"checkout session not paid (status={_obj_get(session, 'payment_status')})",
        )

    customer_id = _obj_get(session, "customer")
    sub_id = _obj_get(session, "subscription")
    if not customer_id or not sub_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "checkout session missing customer or subscription",
        )
    return str(customer_id), str(sub_id)


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class AuthorizeRequest(BaseModel):
    client_id: str = Field(default="jpcite-mcp")
    scope: str | None = Field(
        default="api:read api:metered",
        description="Space-delimited scopes. Defaults to 'api:read api:metered'.",
    )


class AuthorizeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class TokenRequest(BaseModel):
    grant_type: str
    device_code: str
    client_id: str = Field(default="jpcite-mcp")


class TokenSuccess(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    scope: str | None = None


class CompleteRequest(BaseModel):
    user_code: str
    stripe_checkout_session_id: str


class CompleteResponse(BaseModel):
    ok: bool


# --------------------------------------------------------------------------- #
# POST /v1/device/authorize
# --------------------------------------------------------------------------- #


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize(
    payload: AuthorizeRequest,
    conn: DbDep,
    user_agent: Annotated[str | None, Header(alias="user-agent")] = None,
) -> AuthorizeResponse:
    """Mint a fresh (device_code, user_code) pair (RFC 8628 §3.1)."""
    fingerprint = _fingerprint(user_agent)
    created = datetime.now(UTC)
    expires = created + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)
    created_iso = created.isoformat()
    expires_iso = expires.isoformat()

    scope = payload.scope or "api:read api:metered"

    # Retry a handful of times on user_code collision. 32^8 ≈ 10^12 means
    # practical collision odds are astronomically low, but a loop is
    # cheap insurance against a freak coincidence.
    last_err: Exception | None = None
    for _attempt in range(5):
        device_code = _generate_device_code()
        user_code = _generate_user_code()
        verification_uri = f"{_SITE_BASE}/go"
        verification_uri_complete = f"{_SITE_BASE}/go/{user_code}"
        try:
            conn.execute(
                """INSERT INTO device_codes(
                    device_code, user_code, status, client_fingerprint, scope,
                    created_at, expires_at, poll_interval_sec,
                    verification_uri, verification_uri_complete
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    device_code,
                    user_code,
                    fingerprint,
                    scope,
                    created_iso,
                    expires_iso,
                    DEFAULT_POLL_INTERVAL_SECONDS,
                    verification_uri,
                    verification_uri_complete,
                ),
            )
            logger.info(
                "device_code_minted user_code=%s fingerprint=%s",
                user_code,
                (fingerprint or "-")[:8],
            )
            return AuthorizeResponse(
                device_code=device_code,
                user_code=user_code,
                verification_uri=verification_uri,
                verification_uri_complete=verification_uri_complete,
                expires_in=DEVICE_CODE_TTL_SECONDS,
                interval=DEFAULT_POLL_INTERVAL_SECONDS,
            )
        except sqlite3.IntegrityError as exc:
            last_err = exc
            continue

    # Defensive: if we somehow collided 5 times, surface a clean 503.
    logger.error("device_code_mint_collision last_err=%s", last_err)
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "could not mint device code; please retry",
    )


# --------------------------------------------------------------------------- #
# POST /v1/device/token
# --------------------------------------------------------------------------- #


def _token_error(code: str, status_code: int = 400) -> HTTPException:
    """RFC 8628 error response shape: {'error': '<code>'}.

    RFC uses 400 for the polling errors. access_denied / expired_token /
    authorization_pending / slow_down all share that status.
    """
    return HTTPException(status_code=status_code, detail={"error": code})


@router.post("/token", response_model=TokenSuccess)
def token(payload: TokenRequest, conn: DbDep) -> TokenSuccess:
    """Device-flow poll endpoint (RFC 8628 §3.4).

    Success → {access_token, token_type, scope} + 200.
    Pending → authorization_pending (400).
    Polling too fast → slow_down (400).
    Expired → expired_token (400).
    Denied → access_denied (400).
    Invalid grant_type / device_code → invalid_grant (400).
    """
    if payload.grant_type != _GRANT_TYPE:
        raise _token_error("unsupported_grant_type")

    # Opportunistic sweep so /token alone is enough to drive state transitions.
    _expire_stale(conn)

    row = conn.execute(
        """SELECT device_code, user_code, status, scope, expires_at,
                  poll_interval_sec, last_polled_at, activated_at, linked_api_key_id
           FROM device_codes WHERE device_code = ?""",
        (payload.device_code,),
    ).fetchone()
    if row is None:
        raise _token_error("invalid_grant")

    # Rate limit: reject if polled > MAX_POLLS_PER_MINUTE in the last 60s.
    # We approximate by checking last_polled_at alone; a bucket table would
    # be stricter but unnecessary for 10/min.
    now = datetime.now(UTC)
    last_polled = row["last_polled_at"]
    if last_polled:
        try:
            last_dt = datetime.fromisoformat(last_polled)
            interval_sec = int(row["poll_interval_sec"] or DEFAULT_POLL_INTERVAL_SECONDS)
            min_gap_sec = max(1, 60 // MAX_POLLS_PER_MINUTE)
            if (now - last_dt).total_seconds() < min_gap_sec:
                # Slow_down also bumps the recorded interval per RFC 8628.
                conn.execute(
                    "UPDATE device_codes SET last_polled_at = ?, poll_interval_sec = ? "
                    "WHERE device_code = ?",
                    (now.isoformat(), interval_sec + 5, payload.device_code),
                )
                raise _token_error("slow_down")
        except (TypeError, ValueError):
            # Bad stored timestamp → ignore rate check; don't break the poll.
            pass

    # Record the poll timestamp (best-effort; keep going on failure).
    try:
        conn.execute(
            "UPDATE device_codes SET last_polled_at = ? WHERE device_code = ?",
            (now.isoformat(), payload.device_code),
        )
    except sqlite3.Error:
        logger.warning("device_code_poll_ts_write_failed", exc_info=True)

    state = row["status"]
    if state == "expired":
        raise _token_error("expired_token")
    if state == "denied":
        raise _token_error("access_denied")
    if state == "pending":
        raise _token_error("authorization_pending")

    if state != "activated":
        # Defensive: unknown state. Surface as invalid_grant so the client
        # restarts cleanly instead of poll-looping.
        raise _token_error("invalid_grant")

    # activated → hand back the raw api_key that /complete stashed in
    # device_codes.raw_pickup. We clear the column on first read so the
    # raw key cannot be retrieved a second time. api_keys itself stores
    # only the hash (existing design; see api/deps.hash_api_key) — the
    # pickup column is the single-use transport.
    raw_pickup_row = conn.execute(
        "SELECT raw_pickup FROM device_codes WHERE device_code = ?",
        (payload.device_code,),
    ).fetchone()
    raw_pickup = raw_pickup_row["raw_pickup"] if raw_pickup_row else None
    if not raw_pickup:
        # Activated but pickup already consumed (double-poll race). Treat
        # as authorization_pending so the client retries — the next poll
        # will then see status='activated' AND raw_pickup=NULL and return
        # invalid_grant, which correctly tells the client "this code is
        # done; stored token is canonical".
        raise _token_error("invalid_grant")

    conn.execute(
        "UPDATE device_codes SET raw_pickup = NULL, raw_pickup_consumed_at = ? "
        "WHERE device_code = ?",
        (datetime.now(UTC).isoformat(), payload.device_code),
    )

    return TokenSuccess(access_token=raw_pickup, scope=row["scope"])


# --------------------------------------------------------------------------- #
# POST /v1/device/complete
# --------------------------------------------------------------------------- #


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in _ALLOWED_COMPLETE_ORIGINS


@router.post("/complete", response_model=CompleteResponse)
def complete(
    payload: CompleteRequest,
    request: Request,
    conn: DbDep,
    origin: Annotated[str | None, Header(alias="origin")] = None,
) -> CompleteResponse:
    """Called by /go after Stripe Checkout succeeds.

    1. Verifies the Stripe session is complete, subscription-mode,
       environment-matched, priced correctly, metadata-bound to this device
       code, and paid (or metered — no_payment_required).
    2. Marks device_code activated.
    3. Issues an api_keys row prefixed 'am_device_' and links it.
    4. Stashes the raw key in the in-process pickup map so the MCP's
       next /token poll picks it up.
    """
    # CSRF mitigation: Origin must match the configured site host. This
    # is belt-and-braces alongside the Stripe session verification; a
    # browser cross-origin fetch would be blocked anyway by our CORS
    # config (see main.py), but mirrors the explicit allowlist here.
    if not _origin_allowed(origin):
        logger.warning("device_complete_bad_origin origin=%r", origin)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "origin not allowed",
        )

    row = conn.execute(
        """SELECT device_code, user_code, status, scope, stripe_checkout_session_id
           FROM device_codes WHERE user_code = ?""",
        (payload.user_code,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_code not found")

    if row["status"] == "activated":
        if row["stripe_checkout_session_id"] != payload.stripe_checkout_session_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "device_code already activated with a different checkout session",
            )
        # Idempotent: a retry after a flaky network should not re-issue.
        return CompleteResponse(ok=True)
    if row["status"] == "expired":
        raise HTTPException(
            status.HTTP_410_GONE,
            "device_code expired; restart the device flow",
        )
    if row["status"] == "denied":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "device_code already denied",
        )

    reused = conn.execute(
        """SELECT user_code FROM device_codes
           WHERE stripe_checkout_session_id = ? AND user_code != ?
           LIMIT 1""",
        (payload.stripe_checkout_session_id, payload.user_code),
    ).fetchone()
    if reused is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "checkout session already used for another device code",
        )

    # Verify the Stripe session server-side.
    _stripe_ready()
    try:
        session = stripe.checkout.Session.retrieve(
            payload.stripe_checkout_session_id,
            expand=["line_items"],
        )
    except Exception as exc:
        logger.warning(
            "device_complete_stripe_retrieve_failed session=%s err=%s",
            payload.stripe_checkout_session_id,
            exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "could not verify Stripe session",
        ) from exc

    customer_id, sub_id = _require_checkout_session_for_device(
        session_id=payload.stripe_checkout_session_id,
        session=session,
        expected_device_code=row["device_code"],
        expected_user_code=payload.user_code,
    )

    # Issue a device-flow API key. Prefix 'am_device_' so support can
    # distinguish at a glance from regular Checkout-issued keys ('am_').
    # Store both legacy HMAC and bcrypt hashes so require_key() treats the
    # key like any other newly issued credential.
    raw_suffix = secrets.token_urlsafe(24)
    raw_key = f"am_device_{raw_suffix}"
    key_hash = hash_api_key(raw_key)
    bcrypt_hash = hash_api_key_bcrypt(raw_key)
    now = _now_utc_iso()
    txn_started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            txn_started = True

        fresh = conn.execute(
            """SELECT device_code, status, stripe_checkout_session_id
               FROM device_codes WHERE user_code = ?""",
            (payload.user_code,),
        ).fetchone()
        if fresh is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user_code not found")
        if fresh["status"] == "activated":
            if fresh["stripe_checkout_session_id"] != payload.stripe_checkout_session_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "device_code already activated with a different checkout session",
                )
            if txn_started:
                conn.execute("COMMIT")
                txn_started = False
            return CompleteResponse(ok=True)
        if fresh["status"] == "expired":
            raise HTTPException(
                status.HTTP_410_GONE,
                "device_code expired; restart the device flow",
            )
        if fresh["status"] == "denied":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "device_code already denied",
            )

        reused = conn.execute(
            """SELECT user_code FROM device_codes
               WHERE stripe_checkout_session_id = ? AND user_code != ?
               LIMIT 1""",
            (payload.stripe_checkout_session_id, payload.user_code),
        ).fetchone()
        if reused is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "checkout session already used for another device code",
            )

        conn.execute(
            """INSERT INTO api_keys(
                   key_hash, customer_id, tier, stripe_subscription_id,
                   created_at, key_hash_bcrypt, key_last4
               ) VALUES (?, ?, 'paid', ?, ?, ?, ?)""",
            (key_hash, customer_id, sub_id, now, bcrypt_hash, raw_key[-4:]),
        )
        cur = conn.execute(
            """UPDATE device_codes
               SET status='activated', activated_at=?,
                   linked_api_key_id=?, stripe_checkout_session_id=?, stripe_customer_id=?,
                   raw_pickup=?
               WHERE user_code=? AND status='pending'""",
            (
                now,
                key_hash,
                payload.stripe_checkout_session_id,
                customer_id,
                raw_key,
                payload.user_code,
            ),
        )
        if cur.rowcount != 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "device_code state changed during activation",
            )
        if txn_started:
            conn.execute("COMMIT")
            txn_started = False
    except Exception:
        if txn_started:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        raise

    logger.info(
        "device_flow_activated user_code=%s customer=%s sub=%s key_prefix=%s",
        payload.user_code,
        customer_id,
        sub_id,
        raw_key[:12],
    )
    return CompleteResponse(ok=True)


# Export list so `from jpintel_mcp.api.device_flow import router` is the
# canonical import path (main.py uses `from ... import router as device_router`).
__all__ = ["router"]
