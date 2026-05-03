"""Self-serve dashboard endpoints.

Backs the static dashboard at `site/dashboard.html`. The design is
`research/admin_dashboard_design.md` (accepted). W2 MVP scope:

  - POST /v1/session              paste an API key -> HMAC-signed cookie
  - GET  /v1/me                   tier + key_hash_prefix + customer_id + created_at
  - GET  /v1/me/usage?days=30     daily call counts from usage_events
  - POST /v1/me/rotate-key        revoke current key, issue new one (returned once)
  - POST /v1/me/billing-portal    Stripe Customer Portal redirect URL
  - POST /v1/session/logout       clear cookie

Session is a stateless, HMAC-signed cookie (no server-side table). Payload
is pipe-delimited then base64-encoded:

    base64("<key_hash>|<tier>|<exp_iso>|<hex_signature>")

where `signature = hmac(api_key_salt, key_hash + tier + exp_iso)` in sha256.
Tier is carried in the cookie so /v1/me does not hit the DB for tier on
every request; this matches the design doc's `{kh, tier, exp}` payload.

Rate limiting /v1/session: 5 attempts / IP / hour. Implemented as a
process-local `dict[str, deque[float]]` — cross-process gap noted below
(fly.io runs a single app process per machine in MVP).

Rate limiting /v1/me/billing-portal: 1 request / key / minute. Same
process-local pattern. The global RateLimitMiddleware allows 10 req/sec on
paid keys, which is not tight enough to protect Stripe's API quota when the
endpoint is hammered. P1 hardening from audit a000834c952c34822.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import logging
import sqlite3
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta, timezone
from threading import Lock
from typing import Annotated

import stripe
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_log import log_event
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    generate_api_key,
    hash_api_key,
    hash_api_key_bcrypt,
    verify_api_key_bcrypt,
)
from jpintel_mcp.billing.keys import (
    ChildKeyError,
    issue_child_key,
    list_children,
    revoke_child_by_id,
)
from jpintel_mcp.config import settings
from jpintel_mcp.email import get_client as _get_email_client

router = APIRouter(tags=["me"])

logger = logging.getLogger("jpintel.me")

SESSION_COOKIE_NAME = "am_session"
SESSION_TTL_DAYS = 7

# CSRF double-submit cookie pattern (Wave 16 P1).
#   - On `/v1/session` (and rotation) we set `am_csrf` alongside `am_session`.
#   - The CSRF cookie is HMAC-signed against the session key_hash so a
#     stolen session cookie alone cannot synthesise a valid CSRF token
#     (the salt is server-side only).
#   - State-changing session-cookie POSTs (billing-portal, rotate-key,
#     cap, logout) require `X-CSRF-Token` header == cookie value.
#   - The CSRF cookie is intentionally NOT httponly so client JS can
#     read it and echo it back in the header (this is the standard
#     double-submit shape — exposing the token to JS is fine because
#     the only attack we are defending against is a cross-origin POST,
#     which cannot read cookies from our origin).
#   - X-API-Key / Authorization: Bearer authenticated requests (no
#     session cookie) bypass the CSRF check entirely — bearer tokens
#     are not implicitly attached by browsers, so CSRF does not apply.
CSRF_COOKIE_NAME = "am_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


# ---------------------------------------------------------------------------
# Session cookie: encode / decode / sign / verify
# ---------------------------------------------------------------------------


def _sign(key_hash: str, tier: str, exp_iso: str) -> str:
    msg = f"{key_hash}{tier}{exp_iso}".encode()
    return hmac.new(settings.api_key_salt.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _make_cookie(key_hash: str, tier: str, exp_iso: str) -> str:
    sig = _sign(key_hash, tier, exp_iso)
    raw = f"{key_hash}|{tier}|{exp_iso}|{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cookie(cookie_value: str) -> tuple[str, str, str, str]:
    """Return (key_hash, tier, exp_iso, signature). Raises on malformed input."""
    # pad for urlsafe_b64decode
    padding = "=" * (-len(cookie_value) % 4)
    raw = base64.urlsafe_b64decode(cookie_value + padding).decode("ascii")
    parts = raw.split("|")
    if len(parts) != 4:
        raise ValueError("malformed session cookie")
    key_hash, tier, exp_iso, sig = parts
    return key_hash, tier, exp_iso, sig


def _verify_cookie(cookie_value: str) -> tuple[str, str]:
    """Verify a session cookie. Returns (key_hash, tier) or raises 401."""
    try:
        key_hash, tier, exp_iso, sig = _decode_cookie(cookie_value)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session") from None

    expected = _sign(key_hash, tier, exp_iso)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session signature")

    try:
        exp = datetime.fromisoformat(exp_iso)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session exp") from None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if datetime.now(UTC) >= exp:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")

    return key_hash, tier


# ---------------------------------------------------------------------------
# Rate limit for /v1/session
# ---------------------------------------------------------------------------
# NOTE: process-local only. A fly.io single-process app is fine for MVP; once
# we scale to multi-process, swap this for a DB-backed bucket (e.g. reuse the
# `usage_events` table with a sentinel endpoint name, per the design doc).

_SESSION_RATE_MAX = 5
_SESSION_RATE_WINDOW_SECONDS = 3600
_session_hits: dict[str, deque[float]] = defaultdict(deque)
_session_hits_lock = Lock()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _session_rate_check(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - _SESSION_RATE_WINDOW_SECONDS
    with _session_hits_lock:
        bucket = _session_hits[ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _SESSION_RATE_MAX:
            return False
        bucket.append(now)
        return True


def _reset_session_rate_limit_state() -> None:
    """Test helper: clear the session rate-limit bucket."""
    with _session_hits_lock:
        _session_hits.clear()


# ---------------------------------------------------------------------------
# Rate limit for /v1/me/billing-portal (P1 hardening, audit a000834c952c34822)
# ---------------------------------------------------------------------------
# Each Stripe Customer Portal session creation is a real Stripe API call, so
# a malicious caller hammering this endpoint can exhaust our Stripe quota.
# 1 req / key / minute is plenty for a real human flipping into the dashboard
# (the resulting hosted URL is reusable for ~hours), and starves any abuse.

_BILLING_PORTAL_RATE_MAX = 1
_BILLING_PORTAL_RATE_WINDOW_SECONDS = 60
_billing_portal_hits: dict[str, deque[float]] = defaultdict(deque)
_billing_portal_hits_lock = Lock()


def _billing_portal_rate_check(key_hash: str) -> bool:
    now = time.monotonic()
    cutoff = now - _BILLING_PORTAL_RATE_WINDOW_SECONDS
    with _billing_portal_hits_lock:
        bucket = _billing_portal_hits[key_hash]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _BILLING_PORTAL_RATE_MAX:
            return False
        bucket.append(now)
        return True


def _reset_billing_portal_rate_limit_state() -> None:
    """Test helper: clear the billing-portal rate-limit bucket."""
    with _billing_portal_hits_lock:
        _billing_portal_hits.clear()


# ---------------------------------------------------------------------------
# current_me dep
# ---------------------------------------------------------------------------


def current_me(
    request: Request,
    conn: DbDep,
    am_session: Annotated[str | None, Cookie()] = None,
) -> tuple[str, str]:
    """Return (key_hash, tier) from session cookie or API-key headers, or 401.

    P0-2 (audit a4298e454aab2aa43): after HMAC verification, also check
    `api_keys.revoked_at` so a session cookie bound to a key that has since
    been rotated/revoked stops working immediately. Without this, the cookie
    stays valid for its full 7-day TTL even after the underlying key was
    revoked — that means an attacker who exfiltrated the cookie keeps a
    7-day window even after the legitimate user rotates their key.
    """
    # FastAPI's Cookie() alias uses the parameter name, but allow override via
    # raw header lookup in case the browser sends an unusual casing.
    cookie = am_session or request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        key_hash, tier = _verify_cookie(cookie)
    else:
        raw = request.headers.get("x-api-key")
        if not raw:
            auth = request.headers.get("authorization")
            if auth:
                parts = auth.split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    raw = parts[1].strip()
        if not raw:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session")
        key_hash = hash_api_key(raw)
        row = conn.execute(
            "SELECT tier, revoked_at, key_hash_bcrypt FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if not row or row["revoked_at"] is not None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
        row_keys = row.keys() if hasattr(row, "keys") else ()
        stored_bcrypt = row["key_hash_bcrypt"] if "key_hash_bcrypt" in row_keys else None
        if stored_bcrypt and not verify_api_key_bcrypt(raw, stored_bcrypt):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
        return key_hash, row["tier"]
    row = conn.execute(
        "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if not row or row["revoked_at"] is not None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "subsystem_unavailable",
                "message": "session expired (key rotated)",
            },
        )
    return key_hash, tier


CurrentMeDep = Annotated[tuple[str, str], Depends(current_me)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SessionRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)


class SessionResponse(BaseModel):
    tier: str
    key_hash_prefix: str


class MeResponse(BaseModel):
    tier: str
    key_hash_prefix: str
    customer_id: str | None
    created_at: str | None
    # Stripe subscription state cache (migration 052). Backs the dashboard
    # dunning banner. Values are populated by the Stripe webhook handler in
    # src/jpintel_mcp/api/billing.py and read straight from api_keys here —
    # no live Stripe call on the /v1/me hot path.
    #
    #   subscription_status:
    #     One of 'active' | 'trialing' | 'past_due' | 'canceled' | 'unpaid'
    #             | 'incomplete' | 'incomplete_expired' | 'no_subscription'
    #             | 'anonymous'.
    #     'anonymous' is a synthetic value reserved for callers without a
    #     valid session cookie (currently 401s before reaching here, but the
    #     field is documented so future anon-friendly variants are explicit).
    #     'no_subscription' covers the legacy / free path where api_keys
    #     never received a webhook write.
    #   subscription_current_period_end:
    #     ISO 8601 datetime (Z-suffixed UTC) or null. Lets the dashboard
    #     show "次回請求 YYYY-MM-DD" without parsing Stripe directly.
    #   subscription_cancel_at_period_end:
    #     bool. True iff the customer scheduled a cancellation at period end.
    subscription_status: str
    subscription_current_period_end: str | None
    subscription_cancel_at_period_end: bool


class UsageDay(BaseModel):
    date: str
    calls: int


class UsageByClientTag(BaseModel):
    """Per-client_tag aggregate row (税理士 顧問先 attribution).

    Migration 085: surfaced by GET /v1/me/usage?group_by=client_tag and
    GET /v1/me/usage.csv?group_by=client_tag. `client_tag=None` is the
    catch-all bucket for requests that did not pass X-Client-Tag.
    """

    client_tag: str | None
    calls: int
    yen: int


class UsageByChildResponse(BaseModel):
    """Per-child aggregate row (migration 086 SaaS B2B fan-out).

    Surfaced by GET /v1/me/usage/by-child?period=YYYY-MM. Each row carries
    the child's id + label + key_hash_prefix + month-to-date metered call
    count and ¥3-priced subtotal. The parent's own row is included with
    label='(parent)' so the dashboard can render a complete fan-out summary.
    """

    id: int | None
    label: str | None
    key_hash_prefix: str
    is_parent: bool
    calls: int
    yen: int


class ChildKeyIssueRequest(BaseModel):
    """Body for POST /v1/me/keys/children (migration 086).

    `label` is free-text, ≤64 chars, alphanumeric + spaces + a few
    punctuation marks (server-validated). Required at issuance — there
    is no way to issue a child key without a label so the dashboard
    fan-out summary always has a human identifier to render.
    """

    label: str = Field(
        min_length=1,
        max_length=64,
        description="Free-text human identifier (e.g. 'prod', 'customer_acme').",
    )


class ChildKeyIssueResponse(BaseModel):
    """Response for POST /v1/me/keys/children — raw key returned ONCE."""

    api_key: str
    id: int | None
    label: str
    key_hash_prefix: str


class ChildKeyListEntry(BaseModel):
    id: int | None
    label: str | None
    key_hash_prefix: str
    created_at: str | None
    revoked_at: str | None
    last_used_at: str | None


class RotateKeyResponse(BaseModel):
    api_key: str
    tier: str


class BillingPortalResponse(BaseModel):
    url: str


class CapRequest(BaseModel):
    """Body for POST /v1/me/cap.

    `monthly_cap_yen=None` -> remove the cap (uncapped, default).
    `monthly_cap_yen=N>0`  -> hard cap at ¥N billable spend per JST calendar
                              month. ¥3/req unit price unchanged; the cap is
                              client-side budget control, not a discount.
    """

    monthly_cap_yen: int | None = Field(
        default=None,
        ge=0,
        description=(
            "JPY budget cap for the calendar month. NULL means no user-set cap. "
            "Once reached, requests return 503 with cap_reached=true until JST 月初."
        ),
    )


class CapResponse(BaseModel):
    ok: bool
    monthly_cap_yen: int | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csrf_token_for(key_hash: str) -> str:
    """Return the CSRF token bound to a session key_hash.

    Deterministic HMAC over the api_key_salt + key_hash so the same
    session always emits the same CSRF token. Refreshed on rotation
    automatically because key_hash changes.
    """
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        f"csrf|{key_hash}".encode(),
        hashlib.sha256,
    ).hexdigest()


def require_csrf(
    request: Request,
    am_csrf: Annotated[str | None, Cookie()] = None,
) -> None:
    """403 unless `X-CSRF-Token` header matches the `am_csrf` cookie.

    Double-submit cookie pattern. The browser will only attach the cookie
    on same-origin or whitelisted-cross-origin requests; an attacker page
    on evil.example cannot read the cookie nor forge the header. Bearer
    /api-key authenticated requests (no session cookie path) MUST NOT
    invoke this dep — they have nothing to verify.

    Constant-time comparison via hmac.compare_digest.
    """
    if not request.cookies.get(SESSION_COOKIE_NAME):
        raw = request.headers.get("x-api-key")
        auth = request.headers.get("authorization")
        if raw or (auth and auth.lower().startswith("bearer ")):
            return

    cookie_val = am_csrf or request.cookies.get(CSRF_COOKIE_NAME)
    header_val = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_val or not header_val:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "csrf_missing",
                "message": "CSRF token missing (cookie + X-CSRF-Token header required).",
            },
        )
    if not hmac.compare_digest(cookie_val, header_val):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "csrf_mismatch",
                "message": "CSRF token mismatch.",
            },
        )


CsrfDep = Annotated[None, Depends(require_csrf)]


def _set_session_cookie(request: Request, response: Response, key_hash: str, tier: str) -> None:
    exp = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
    exp_iso = exp.isoformat()
    cookie = _make_cookie(key_hash, tier, exp_iso)
    # Secure flag only makes sense over HTTPS — a browser silently drops
    # a Secure cookie from an http:// response. For tests and local dev we
    # fall back to non-secure; production always runs behind fly.io HTTPS.
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )
    # Companion CSRF cookie (NOT httponly so JS can read + echo it as
    # the X-CSRF-Token header). HMAC-bound to the session key_hash so
    # rotation refreshes both cookies in lockstep. Same TTL as session.
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=_csrf_token_for(key_hash),
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=False,
        secure=is_https,
        samesite="lax",
        path="/",
    )


def _origin_from_request(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer:
        # strip path, keep scheme+host
        try:
            from urllib.parse import urlparse

            u = urlparse(referer)
            if u.scheme and u.netloc:
                return f"{u.scheme}://{u.netloc}"
        except Exception:
            pass
    # last resort — derive from request URL
    return f"{request.url.scheme}://{request.url.netloc}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/v1/session", response_model=SessionResponse)
def create_session(
    payload: SessionRequest,
    request: Request,
    response: Response,
    conn: DbDep,
) -> SessionResponse:
    ip = _client_ip(request)
    if not _session_rate_check(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"session rate limit exceeded ({_SESSION_RATE_MAX}/hour)",
        )

    key_hash = hash_api_key(payload.api_key)
    row = conn.execute(
        "SELECT tier, customer_id, revoked_at FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None or row["revoked_at"]:
        # Audit-log the failed login (P1, audit a4298e454aab2aa43). Use the
        # hash so an attacker probing valid prefixes leaves a forensic trail
        # without us ever persisting their attempted raw key.
        log_event(
            conn,
            event_type="login_failed",
            key_hash=key_hash,
            customer_id=row["customer_id"] if row else None,
            request=request,
            reason="revoked" if (row and row["revoked_at"]) else "not_found",
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    tier = row["tier"]
    _set_session_cookie(request, response, key_hash, tier)
    log_event(
        conn,
        event_type="login",
        key_hash=key_hash,
        customer_id=row["customer_id"],
        request=request,
        tier=tier,
    )
    return SessionResponse(tier=tier, key_hash_prefix=key_hash[:8])


@router.get("/v1/me", response_model=MeResponse)
def get_me(me: CurrentMeDep, conn: DbDep) -> MeResponse:
    key_hash, tier = me
    # customer_id + created_at + cached subscription state still need a DB
    # read; the "no DB tier fetch" rule in the spec is about tier specifically
    # (tier comes from the cookie). All four subscription_* columns were
    # added by migration 052 — they are write-through cached by the Stripe
    # webhook handler so we never call Stripe live on this hot path.
    row = conn.execute(
        """SELECT customer_id, created_at,
                  stripe_subscription_status,
                  stripe_subscription_current_period_end,
                  stripe_subscription_cancel_at_period_end
             FROM api_keys WHERE key_hash = ?""",
        (key_hash,),
    ).fetchone()
    customer_id = row["customer_id"] if row else None
    created_at = row["created_at"] if row else None
    # NULL stripe_subscription_status -> 'no_subscription'. This covers the
    # legacy/free-tier path where api_keys never had a Stripe webhook write
    # (e.g. operator-issued free key, or pre-migration-052 row).
    raw_status = row["stripe_subscription_status"] if row else None
    subscription_status = raw_status or "no_subscription"
    # current_period_end is stored as epoch seconds; surface ISO 8601 UTC.
    cpe_epoch = row["stripe_subscription_current_period_end"] if row else None
    if cpe_epoch is None:
        subscription_current_period_end = None
    else:
        subscription_current_period_end = (
            datetime.fromtimestamp(int(cpe_epoch), tz=UTC).isoformat().replace("+00:00", "Z")
        )
    cancel_flag = row["stripe_subscription_cancel_at_period_end"] if row else None
    subscription_cancel_at_period_end = bool(cancel_flag) if cancel_flag else False
    return MeResponse(
        tier=tier,
        key_hash_prefix=key_hash[:8],
        customer_id=customer_id,
        created_at=created_at,
        subscription_status=subscription_status,
        subscription_current_period_end=subscription_current_period_end,
        subscription_cancel_at_period_end=subscription_cancel_at_period_end,
    )


# Pure metered ¥3/req 税別 (memory: project_autonomath_business_model).
# Mirrors the constant in middleware/customer_cap.py — duplicated here so
# the per-tag / per-child aggregates can render the same ¥ figure as the
# cap layer reports. Tax-inclusive value (¥3.30) is added by Stripe at
# invoice render time, not by this dashboard.
_USAGE_UNIT_PRICE_YEN: int = 3


def _resolve_tree_key_hashes(conn, key_hash: str) -> list[str]:
    """Return every key_hash in the tree containing `key_hash`.

    Migration 086: the dashboard caller's session is bound to the parent
    key (children never log in via /v1/session — the only way to act on
    a child key is to use it directly). For a parent caller we expand
    to parent + every child. For a child caller we still expand to the
    full tree (defensive — the child should not normally hold a session
    anyway, but if they do they should see the same fan-out totals as
    the parent would).
    """
    row = conn.execute(
        "SELECT id, parent_key_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return [key_hash]
    rk = row.keys() if hasattr(row, "keys") else []
    own_id = row["id"] if "id" in rk else None
    parent_key_id = row["parent_key_id"] if "parent_key_id" in rk else None
    root = parent_key_id if parent_key_id is not None else own_id
    if root is None:
        return [key_hash]
    rows = conn.execute(
        "SELECT key_hash FROM api_keys " "WHERE id = ? OR parent_key_id = ?",
        (root, root),
    ).fetchall()
    hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in rows]
    if key_hash not in hashes:
        hashes.append(key_hash)
    return hashes


def _aggregate_by_client_tag(
    conn, tree_hashes: list[str], start_iso: str
) -> list[UsageByClientTag]:
    """SUM usage_events grouped by client_tag for the given tree + window.

    Returns rows ordered by descending call count so the dashboard
    surfaces the highest-spend 顧問先 first. NULL client_tag is included
    as the catch-all (un-tagged) bucket.
    """
    if not tree_hashes:
        return []
    placeholders = ",".join("?" * len(tree_hashes))
    rows = conn.execute(
        f"""SELECT client_tag,
                   COUNT(*) AS n,
                   COALESCE(SUM(COALESCE(quantity, 1)), 0) AS units
              FROM usage_events
             WHERE key_hash IN ({placeholders})
               AND ts >= ?
          GROUP BY client_tag
          ORDER BY units DESC, n DESC""",  # noqa: S608 — placeholders only
        (*tree_hashes, start_iso),
    ).fetchall()
    out: list[UsageByClientTag] = []
    for r in rows:
        rk = r.keys() if hasattr(r, "keys") else []
        tag = r["client_tag"] if "client_tag" in rk else None
        n = int(r["units"] if "units" in rk else r["n"] if "n" in rk else 0)
        out.append(
            UsageByClientTag(
                client_tag=tag,
                calls=n,
                yen=n * _USAGE_UNIT_PRICE_YEN,
            )
        )
    return out


@router.get("/v1/me/usage")
def get_me_usage(
    me: CurrentMeDep,
    conn: DbDep,
    days: int = 30,
    group_by: str | None = None,
) -> list[UsageDay] | list[UsageByClientTag]:
    """Per-day OR per-client_tag usage aggregate.

    Default (``group_by`` absent) returns the legacy daily series — one
    row per UTC date with the call count, contiguous (gaps filled with
    zeros) so dashboards can plot directly. ``days`` clamped 1..90.

    ``group_by=client_tag`` (migration 085) returns one row per distinct
    ``X-Client-Tag`` value within the same window, sorted by descending
    call count. ``client_tag=None`` is the catch-all bucket for requests
    that did not pass the header. Aggregation runs across the full
    parent/child tree (migration 086) so a parent caller sees totals for
    all children.
    """
    if days < 1:
        days = 1
    if days > 90:
        days = 90

    key_hash, _tier = me
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_iso = start.isoformat()

    if group_by == "client_tag":
        tree_hashes = _resolve_tree_key_hashes(conn, key_hash)
        return _aggregate_by_client_tag(conn, tree_hashes, start_iso)

    if group_by is not None and group_by != "":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_group_by",
                "allowed": ["client_tag"],
                "got": group_by,
            },
        )

    tree_hashes = _resolve_tree_key_hashes(conn, key_hash)
    placeholders = ",".join("?" * len(tree_hashes))
    rows = conn.execute(
        f"""SELECT substr(ts, 1, 10) AS d,
                   COALESCE(SUM(COALESCE(quantity, 1)), 0) AS n
             FROM usage_events
            WHERE key_hash IN ({placeholders}) AND ts >= ?
         GROUP BY d
         ORDER BY d ASC""",  # noqa: S608 — placeholders only
        (*tree_hashes, start_iso),
    ).fetchall()

    by_date: dict[str, int] = {r["d"]: r["n"] for r in rows}
    # Fill gaps so the caller gets a full contiguous series.
    out: list[UsageDay] = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        out.append(UsageDay(date=d, calls=by_date.get(d, 0)))
    return out


def _csv_escape(value: object) -> str:
    """Minimal RFC 4180 escape — quote if comma / quote / newline present."""
    s = "" if value is None else str(value)
    if any(ch in s for ch in (",", '"', "\n", "\r")):
        s = '"' + s.replace('"', '""') + '"'
    return s


@router.get("/v1/me/usage.csv")
def get_me_usage_csv(
    me: CurrentMeDep,
    conn: DbDep,
    days: int = 30,
    group_by: str | None = None,
) -> Response:
    """CSV export of per-tag aggregate (migration 085).

    Currently only ``group_by=client_tag`` is supported. The format is
    a stable header + one row per tag, NULL tags rendered as empty.
    Designed for Excel / Google Sheets ingestion by 税理士 offices that
    need to forward per-顧問先 line items into their internal billing.
    """
    if group_by != "client_tag":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_group_by",
                "allowed": ["client_tag"],
                "got": group_by,
                "message": ("/v1/me/usage.csv currently only supports " "group_by=client_tag"),
            },
        )
    if days < 1:
        days = 1
    if days > 90:
        days = 90

    key_hash, _tier = me
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_iso = start.isoformat()
    tree_hashes = _resolve_tree_key_hashes(conn, key_hash)
    aggregates = _aggregate_by_client_tag(conn, tree_hashes, start_iso)

    lines = ["client_tag,calls,yen_excl_tax"]
    for row in aggregates:
        lines.append(
            ",".join(
                [
                    _csv_escape(row.client_tag if row.client_tag else ""),
                    _csv_escape(row.calls),
                    _csv_escape(row.yen),
                ]
            )
        )
    body = "\r\n".join(lines) + "\r\n"
    filename = f"autonomath_usage_by_client_tag_{today.isoformat()}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------------------
# Key-rotation security notification (P1 from audit a4298e454aab2aa43)
# ---------------------------------------------------------------------------
# A rotation without an out-of-band notice is indistinguishable from an
# attacker who exfiltrated a session cookie and silently rotated the
# legitimate user's key. Email gives the customer an audit trail with the
# IP / User-Agent / key suffixes the harness saw at rotation time.


def _lookup_subscriber_email(conn, key_hash: str) -> str | None:
    """Best-effort lookup of the email associated with a rotating api_key.

    The canonical source is `email_schedule.email`, which `billing.keys.
    issue_key()` populates on issuance for every key (including free-tier
    keys that never see Stripe). The `subscribers` table is not viable here
    because it carries no `customer_id` link to api_keys — it is fed by
    Postmark webhook / opt-in flows, not by the issuance pipeline.

    Returns None when no email is on record (e.g. legacy keys issued before
    the email_schedule wiring landed). Callers MUST treat None as "skip the
    send" — never raise.
    """
    try:
        row = conn.execute(
            "SELECT email FROM email_schedule WHERE api_key_id = ? " "ORDER BY id ASC LIMIT 1",
            (key_hash,),
        ).fetchone()
    except Exception:  # pragma: no cover — defensive
        return None
    if row is None:
        return None
    email = row["email"] if hasattr(row, "keys") else row[0]
    return email or None


def _send_key_rotated_safe(
    *,
    to: str | None,
    old_suffix: str,
    new_suffix: str,
    ip: str,
    user_agent: str,
    ts_jst: str,
) -> None:
    """Fire-and-forget rotation notice. NEVER raises into the caller.

    Mirrors the contract of `_send_dunning_safe` / `_send_welcome_safe` in
    api/billing.py: a Postmark outage during rotation must NOT 500 the
    /v1/me/rotate-key response — the rotation itself has already committed
    by the time this fires (BackgroundTasks run after the response is sent).
    Failures are logged + Sentry-captured if the SDK is loaded.
    """
    if not to:
        return
    try:
        _get_email_client().send_key_rotated(
            to=to,
            old_suffix=old_suffix,
            new_suffix=new_suffix,
            ip=ip,
            user_agent=user_agent,
            ts_jst=ts_jst,
        )
    except Exception as exc:
        try:
            import sentry_sdk  # type: ignore[import-not-found]

            sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover — no Sentry installed
            pass
        logger.warning(
            "key_rotated email failed old=%s new=%s",
            old_suffix,
            new_suffix,
            exc_info=True,
        )


@router.post("/v1/me/rotate-key", response_model=RotateKeyResponse)
def rotate_key(
    me: CurrentMeDep,
    _csrf: CsrfDep,
    conn: DbDep,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> RotateKeyResponse:
    """Revoke the current key and issue a new one in a single atomic txn.

    P0 fixes from audit a4298e454aab2aa43:
      - P0-1: BEGIN IMMEDIATE / COMMIT around the revoke + insert. Without
        this the connection runs in autocommit (db.session.connect uses
        isolation_level=None), so a crash between the UPDATE and the INSERT
        leaves the customer with neither a working old key nor a new key.
        BEGIN IMMEDIATE acquires the writer lock up-front, which also serves
        as the lock for the concurrent-rotation race (only one writer at
        a time; the loser gets SQLITE_BUSY and bubbles up as 5xx).
      - P0-3: carry forward `monthly_cap_yen` so the customer's spend cap
        is not silently reset to NULL (unlimited) on rotation. Also migrate
        any `alert_subscriptions` rows from old key_hash to new — otherwise
        the customer's amendment alerts go silent on rotation.
      - Bonus: re-issue the session cookie bound to the NEW key_hash so the
        dashboard stays logged in. With P0-2 in place, the OLD cookie now
        401s on next /v1/me, so without this the user gets bounced to
        /login the moment they rotate.
    """
    key_hash, _tier_cookie = me
    now = datetime.now(UTC).isoformat()
    new_raw, new_hash = generate_api_key()

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT tier, customer_id, stripe_subscription_id, "
            "monthly_cap_yen, parent_key_id, revoked_at "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row is None or row["revoked_at"]:
            conn.execute("ROLLBACK")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "key not found or revoked")
        if row["parent_key_id"] is not None:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "child_key_forbidden",
                    "message": "Child API keys cannot rotate parent credentials.",
                },
            )

        tier = row["tier"]
        customer_id = row["customer_id"]
        sub_id = row["stripe_subscription_id"]
        monthly_cap_yen = row["monthly_cap_yen"]

        conn.execute(
            "UPDATE api_keys SET revoked_at = ? " "WHERE key_hash = ? AND revoked_at IS NULL",
            (now, key_hash),
        )

        # bcrypt dual-path (Wave 16 P1, migration 073). Rotation issues a
        # bcrypt hash for the NEW key alongside the legacy HMAC. Compute
        # OUTSIDE the SQL call so the ~100ms cost is paid before the writer
        # lock release; the BEGIN IMMEDIATE above already serialized writes.
        new_bcrypt_hash = hash_api_key_bcrypt(new_raw)
        conn.execute(
            """INSERT INTO api_keys(
                   key_hash, customer_id, tier, stripe_subscription_id,
                   created_at, monthly_cap_yen, key_hash_bcrypt
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (new_hash, customer_id, tier, sub_id, now, monthly_cap_yen, new_bcrypt_hash),
        )

        # Migrate alert subscriptions to the new key_hash so amendment
        # alerts keep firing. The table is migration-038-only so guard
        # against environments where it does not yet exist (some test DBs
        # build from schema.sql, which doesn't carry the alert table).
        try:
            conn.execute(
                "UPDATE alert_subscriptions SET api_key_hash = ? " "WHERE api_key_hash = ?",
                (new_hash, key_hash),
            )
        except sqlite3.OperationalError as e:  # pragma: no cover
            if "no such table" not in str(e).lower():
                raise

        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise

    # Re-issue the session cookie bound to the NEW key_hash. Without this
    # the OLD cookie 401s on next /v1/me (P0-2 revocation check) and the
    # dashboard bounces the user to login immediately after rotation.
    _set_session_cookie(request, response, new_hash, tier)

    # P1 audit-log the rotation (audit a4298e454aab2aa43). Done OUTSIDE the
    # transaction so a write failure cannot leave the user with no working
    # key — the rotation already committed above. log_event swallows
    # exceptions for the same reason.
    log_event(
        conn,
        event_type="key_rotate",
        key_hash=key_hash,
        key_hash_new=new_hash,
        customer_id=customer_id,
        request=request,
        tier=tier,
    )

    # P1 (audit a4298e454aab2aa43): out-of-band rotation security notice.
    # P0 (bg-task-durability, 2026-04-25): enqueue into the durable
    # bg_task_queue (migration 060) instead of FastAPI BackgroundTasks so
    # a process restart between commit and email send cannot drop the
    # notice. The rotation has already committed by this point, so a
    # missing email is far better than a failed rotation. Wrapped in
    # try/except — never fail rotation due to enqueue.
    try:
        subscriber_email = _lookup_subscriber_email(conn, key_hash)
        if subscriber_email:
            jst = timezone(timedelta(hours=9))
            ts_jst = datetime.now(UTC).astimezone(jst).strftime("%Y-%m-%d %H:%M JST")
            ip = _client_ip(request)
            # Real-browser User-Agent strings can run 200+ chars. Truncate
            # so a hostile UA cannot pad the email body unbounded — the
            # audit trail benefits from a fixed shape.
            ua_raw = request.headers.get("user-agent") or "unknown"
            user_agent = ua_raw[:256]
            from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

            _bg_enqueue(
                conn,
                kind="key_rotated_email",
                payload={
                    "to": subscriber_email,
                    "old_suffix": key_hash[-4:],
                    "new_suffix": new_hash[-4:],
                    "ip": ip,
                    "user_agent": user_agent,
                    "ts_jst": ts_jst,
                },
                # dedup on (old_hash, new_hash): a duplicated rotate that
                # somehow re-issues the same pair must not double-mail.
                dedup_key=f"key_rotated:{key_hash}:{new_hash}",
            )
    except Exception:  # pragma: no cover — never fail rotation on email
        logger.warning("key_rotated email scheduling failed", exc_info=True)

    return RotateKeyResponse(api_key=new_raw, tier=tier)


# ---------------------------------------------------------------------------
# Child API keys (migration 086 — sub-API-key SaaS B2B fan-out)
# ---------------------------------------------------------------------------
#
# A parent paid key can issue up to MAX_CHILDREN_PER_PARENT (1,000) child
# keys, one per 顧問先 (税理士 fan-out cohort #2 in CLAUDE.md). Each child
# inherits the parent's tier, monthly_cap_yen, and stripe_subscription_id
# verbatim — Stripe sees only the parent subscription, so no separate
# Checkout / cancel flow is needed for children.
#
# Constraints (enforced server-side by billing/keys.py helpers):
#   * Children CANNOT spawn grandchildren (flat tree only).
#   * A revoked parent kills all live children via revoke_key_tree
#     (invoked by the Stripe webhook on subscription.deleted).
#   * Children themselves cannot rotate the parent key, set caps, or open
#     the billing portal — those routes already 403 child-key callers.
#
# CSRF gating: issuance + revoke are state-changing session-cookie POSTs
# so they require the X-CSRF-Token header (double-submit cookie pattern).
# The list endpoint is read-only and skips CSRF.
#
# Authentication shape: every endpoint uses CurrentMeDep, which means the
# CALLER's session must be the parent's session (children never log in
# via /v1/session in the dashboard fan-out flow). A child key holder
# trying to list/issue/revoke would fail at the parent_key_id check
# inside the helpers (parent_id resolution, list returns []).


def _child_key_error_to_http(exc: ChildKeyError) -> HTTPException:
    """Map a ChildKeyError into a canonical 4xx HTTPException.

    The helper layer raises distinct error_code values
    (label_invalid / label_too_long / label_missing /
    parent_not_found / parent_revoked / nesting_forbidden /
    child_cap_exceeded). 422 covers user-supplied label problems;
    409 covers parent-state problems (already revoked, nested,
    over-cap); 404 covers a missing parent. The wire shape mirrors
    the rotate-key / billing-portal child_key_forbidden envelope so
    clients can dispatch on `detail.error` uniformly.
    """
    code = getattr(exc, "error_code", "child_key_invalid")
    label_codes = {"label_missing", "label_invalid", "label_too_long"}
    state_codes = {"parent_revoked", "nesting_forbidden", "child_cap_exceeded"}
    if code in label_codes:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif code == "parent_not_found":
        http_status = status.HTTP_404_NOT_FOUND
    elif code in state_codes:
        http_status = status.HTTP_409_CONFLICT
    else:  # pragma: no cover — defensive fallback
        http_status = status.HTTP_400_BAD_REQUEST
    return HTTPException(
        status_code=http_status,
        detail={
            "error": code,
            "message": str(exc),
        },
    )


@router.post(
    "/v1/me/keys/children",
    response_model=ChildKeyIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_child_key_route(
    payload: ChildKeyIssueRequest,
    me: CurrentMeDep,
    _csrf: CsrfDep,
    conn: DbDep,
    request: Request,
) -> ChildKeyIssueResponse:
    """Issue a new child API key under the caller's parent key.

    Wires the `issue_child_key` helper (billing/keys.py, migration 086)
    into the REST surface. The raw child key is returned ONCE in the
    response body; subsequent reads only ever surface the
    `key_hash_prefix` (first 8 chars) for identification.

    Constraints enforced upstream:
      * Caller must be the parent (children cannot spawn grandchildren —
        the helper rejects with `nesting_forbidden`).
      * Per-parent cap is MAX_CHILDREN_PER_PARENT (1,000) NON-revoked
        children — `child_cap_exceeded` once exhausted. Revoked siblings
        free up slots.
      * Label is required, ≤64 chars, no control characters.
    """
    parent_hash, _tier = me
    try:
        raw, key_hash = issue_child_key(
            conn,
            parent_key_hash=parent_hash,
            label=payload.label,
        )
        conn.commit()
    except ChildKeyError as exc:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise _child_key_error_to_http(exc) from None

    # Look up the new child's id so the response carries it (caller uses
    # the id later to revoke). The list_children read is bounded by the
    # parent's child set — small (≤1,000).
    child_id: int | None = None
    row = conn.execute(
        "SELECT id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is not None:
        rk = row.keys() if hasattr(row, "keys") else []
        child_id = row["id"] if "id" in rk else None

    log_event(
        conn,
        event_type="child_key_issue",
        key_hash=parent_hash,
        request=request,
        child_key_hash_prefix=key_hash[:8],
        child_id=child_id,
        label=payload.label,
    )

    return ChildKeyIssueResponse(
        api_key=raw,
        id=child_id,
        label=payload.label,
        key_hash_prefix=key_hash[:8],
    )


@router.get(
    "/v1/me/keys/children",
    response_model=list[ChildKeyListEntry],
)
def list_child_keys_route(
    me: CurrentMeDep,
    conn: DbDep,
    include_revoked: bool = False,
) -> list[ChildKeyListEntry]:
    """List every child key under the caller's parent key.

    `include_revoked=true` flips on the historic view (revoked rows
    included alongside live ones, sorted by issuance order). Default
    surfaces live children only — matches the dashboard fan-out summary
    use case. Read-only, no CSRF required.

    Returns an empty list when the caller has no children, OR when the
    caller is themselves a child (the helper resolves to the caller's
    parent_key_id; a child-as-caller has no children of its own).
    """
    parent_hash, _tier = me
    rows = list_children(
        conn,
        parent_key_hash=parent_hash,
        include_revoked=include_revoked,
    )
    return [
        ChildKeyListEntry(
            id=row.get("id"),
            label=row.get("label"),
            key_hash_prefix=row.get("key_hash_prefix") or "",
            created_at=row.get("created_at"),
            revoked_at=row.get("revoked_at"),
            last_used_at=row.get("last_used_at"),
        )
        for row in rows
    ]


@router.delete("/v1/me/keys/children/{child_id}")
def revoke_child_key_route(
    child_id: int,
    me: CurrentMeDep,
    _csrf: CsrfDep,
    conn: DbDep,
    request: Request,
) -> dict[str, object]:
    """Revoke a single child key by id, scoped to the caller's parent.

    The parent_key_hash gate inside the helper is critical: without it
    a stolen child id alone would let any caller revoke any child
    (rowids are guessable). Returns `{"revoked": true}` when a row was
    flipped, or 404 with `child_not_found` when the id is unknown to
    this parent (already revoked, never existed, or belongs to a
    different parent).
    """
    parent_hash, _tier = me
    ok = revoke_child_by_id(
        conn,
        parent_key_hash=parent_hash,
        child_id=int(child_id),
    )
    conn.commit()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "child_not_found",
                "message": ("child key not found, already revoked, or not owned " "by this parent"),
            },
        )
    log_event(
        conn,
        event_type="child_key_revoke",
        key_hash=parent_hash,
        request=request,
        child_id=int(child_id),
    )
    return {"revoked": True, "child_id": int(child_id)}


@router.post("/v1/me/cap", response_model=CapResponse)
def set_monthly_cap(
    payload: CapRequest,
    ctx: ApiContextDep,
    conn: DbDep,
    request: Request,
) -> CapResponse:
    """Set the customer's self-serve monthly spend cap (P3-W).

    Authenticated via require_key (X-API-Key header or Authorization: Bearer).
    Anonymous callers (no key) cannot set a cap because the anonymous tier is
    already gated by the 3 req/日 free quota — there is nothing to cap.

    The unit price stays ¥3/req (immutable per
    project_autonomath_business_model). `monthly_cap_yen` is purely a client
    budget control: at cap-reached the middleware returns 503 with
    `cap_reached: true` and Stripe usage is NOT recorded for the rejected
    request, so the cap is hard.
    """
    if ctx.key_hash is None:
        # Anonymous tier — refuse. Anon callers have a 3/day free quota and
        # never produce a Stripe usage record, so there is no cap to set.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "monthly cap requires an authenticated API key",
        )
    # Capture the prior cap so the audit log records the transition, not
    # just the new value (P1, audit a4298e454aab2aa43).
    prior_row = conn.execute(
        "SELECT monthly_cap_yen, customer_id FROM api_keys WHERE key_hash = ?",
        (ctx.key_hash,),
    ).fetchone()
    prior_cap = prior_row["monthly_cap_yen"] if prior_row else None
    customer_id = prior_row["customer_id"] if prior_row else None
    conn.execute(
        "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
        (payload.monthly_cap_yen, ctx.key_hash),
    )
    log_event(
        conn,
        event_type="cap_change",
        key_hash=ctx.key_hash,
        customer_id=customer_id,
        request=request,
        prior_cap_yen=prior_cap,
        new_cap_yen=payload.monthly_cap_yen,
    )
    # Invalidate the middleware cache so the new cap takes effect on the very
    # next request rather than waiting for the 5-minute TTL to expire.
    try:
        from jpintel_mcp.api.middleware import invalidate_cap_cache_for_tree

        invalidate_cap_cache_for_tree(conn, ctx.key_hash)
    except Exception:  # pragma: no cover — cache miss is harmless
        pass
    return CapResponse(ok=True, monthly_cap_yen=payload.monthly_cap_yen)


@router.post("/v1/me/billing-portal", response_model=BillingPortalResponse)
def billing_portal(
    me: CurrentMeDep,
    _csrf: CsrfDep,
    conn: DbDep,
    request: Request,
) -> BillingPortalResponse:
    key_hash, _tier = me
    # P1 hardening (audit a000834c952c34822): per-key 1/min cap. The global
    # RateLimitMiddleware (10 req/sec on paid keys) is too lenient to protect
    # the Stripe API from a hammering caller.
    if not _billing_portal_rate_check(key_hash):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "billing portal rate limit exceeded (1/minute)",
        )
    row = conn.execute(
        "SELECT customer_id, parent_key_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row and row["parent_key_id"] is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "child_key_forbidden",
                "message": "Child API keys cannot open the billing portal.",
            },
        )
    customer_id = row["customer_id"] if row else None
    if not customer_id:
        # Per CLAUDE.md non-negotiable: ¥3/req metered only, no tiers, no
        # "upgrade" path. An anonymous-tier / pre-billing key has no Stripe
        # customer_id yet — it gets created automatically on first metered
        # usage. Return 404 with a structured envelope explicitly avoiding
        # "upgrade" / "tier" wording (which would imply a SKU change).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "no_customer",
                "message": (
                    "Stripe カスタマーが未作成です。¥3/req の従量課金は使用後に"
                    "自動作成されます。"
                ),
            },
        )

    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe not configured")
    stripe.api_key = settings.stripe_secret_key

    return_url = f"{_origin_from_request(request)}/dashboard"
    portal_kwargs: dict[str, object] = {
        "customer": customer_id,
        "return_url": return_url,
    }
    if settings.stripe_billing_portal_config_id:
        portal_kwargs["configuration_id"] = settings.stripe_billing_portal_config_id
    # P1 hardening (audit a000834c952c34822): never leak Stripe error
    # messages — they can include customer_id, internal request_id, and
    # other detail that is useless to the caller and noisy to log scrapers.
    # Log full exception via logger.exception, return canonical envelope.
    try:
        session = stripe.billing_portal.Session.create(**portal_kwargs)  # type: ignore[arg-type]
    except stripe.StripeError:
        logger.exception(
            "stripe_billing_portal_create_failed key_hash_prefix=%s",
            key_hash[:8],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "subsystem_unavailable",
                "message": "Billing service temporarily unavailable. Please try again.",
            },
        ) from None
    # P1 audit-log the portal open (audit a4298e454aab2aa43). Stripe-side
    # session id captured in metadata so an incident-response query can
    # cross-reference Stripe Dashboard.
    log_event(
        conn,
        event_type="billing_portal",
        key_hash=key_hash,
        customer_id=customer_id,
        request=request,
        stripe_session_id=getattr(session, "id", None),
    )
    return BillingPortalResponse(url=session.url)


@router.post("/v1/session/logout")
def logout(_csrf: CsrfDep) -> Response:
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    resp.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
    return resp


__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "SESSION_COOKIE_NAME",
    "SESSION_TTL_DAYS",
    "current_me",
    "require_csrf",
    "router",
]
