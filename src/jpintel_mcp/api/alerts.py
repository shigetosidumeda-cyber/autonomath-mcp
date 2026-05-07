"""Tier 3 amendment alert subscriptions (v8 P5-ι++ / dd_v8_08 H/I).

Endpoints under /v1/me/alerts:
  - POST   /v1/me/alerts/subscribe                 create a subscription
  - GET    /v1/me/alerts/subscriptions             list active subscriptions
  - DELETE /v1/me/alerts/subscriptions/{id}        deactivate a subscription

Why a separate router (not part of me.py):
  - me.py is the dashboard-cookie surface (CurrentMeDep). Alert subscriptions
    are managed by the API key itself (X-API-Key) so MCP tools / CI scripts
    can wire them in without touching the browser flow.
  - Keeps me.py from growing unbounded; B3 owns dashboard, A6 owns me.

Authentication:
  Authenticated via require_key (ApiContextDep). Anonymous tier rejected with
  401 — there is no key to attach the subscription to. This matches the
  /v1/me/cap posture.

Cost posture:
  Subscriptions are FREE (no ¥3/req surcharge). project_autonomath_business_model
  keeps the unit price immutable; the alert fan-out cost is ours to absorb as a
  retention feature.

Webhook security:
  - HTTPS scheme required at create-time.
  - Internal/RFC1918/loopback hosts blocked at create-time (127.0.0.1, 10.*,
    172.16-31.*, 192.168.*, ::1, fc00::/7). The cron re-validates at fire-time
    in case DNS resolves to a private IP after the fact.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)

router = APIRouter(prefix="/v1/me/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Constants — kept in module scope so the cron can reuse FilterType / Severity
# without circular imports.
# ---------------------------------------------------------------------------

FILTER_TYPES: tuple[str, ...] = ("tool", "law_id", "program_id", "industry_jsic", "all")
SEVERITIES: tuple[str, ...] = ("critical", "important", "info")
# severity ordering for >= comparisons in the cron. Higher = more urgent.
SEVERITY_RANK: dict[str, int] = {"info": 0, "important": 1, "critical": 2}


# ---------------------------------------------------------------------------
# Webhook URL validation
# ---------------------------------------------------------------------------


def _is_internal_host(host: str) -> bool:
    """Return True when `host` resolves (or already is) an internal IP.

    Blocks RFC1918 (10/8, 172.16/12, 192.168/16), loopback (127/8 + ::1),
    link-local (169.254/16 + fe80::/10), and unique-local IPv6 (fc00::/7).
    Public DNS names are accepted (resolution at create-time would be a
    network round-trip we do not want; cron re-validates at fire-time).

    A pure literal-IP guard (no DNS) is enough at create-time because
    `https://10.0.0.5/hook` is a clear footgun and `https://internal.corp/`
    requires DNS to be wrong; the cron handles the DNS rebinding edge case.
    """
    if not host:
        return True
    # Strip an IPv6 literal's brackets (urlparse leaves them in `hostname`
    # as lower-case unbracketed, but be defensive in case of upstream
    # changes).
    h = host.strip("[]").lower()
    # Reject obviously private literals first.
    try:
        ip = ipaddress.ip_address(h)
        return (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        # Not a literal IP — defer to DNS-time check in the cron.
        return False


def _validate_webhook_url(url: str) -> None:
    """Raise HTTPException(400) when `url` is unsafe to fan out to.

    Rules:
      * scheme must be https (no http, no scheme-less, no file://).
      * netloc must be present (not just `https://`).
      * host must not be an internal/loopback/private IP literal.
      * length cap 2048 chars (stops abusive blob URIs).
    """
    if len(url) > 2048:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "webhook_url too long (max 2048 chars)",
        )
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"webhook_url is not a valid URL: {exc}",
        ) from exc
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "webhook_url must use https:// (http and others are blocked)",
        )
    if not parsed.netloc or not parsed.hostname:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "webhook_url must include a host",
        )
    if _is_internal_host(parsed.hostname):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "webhook_url host resolves to a private/internal address",
        )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    filter_type: Literal["tool", "law_id", "program_id", "industry_jsic", "all"]
    filter_value: Annotated[str | None, Field(default=None, max_length=256)] = None
    min_severity: Literal["critical", "important", "info"] = "important"
    webhook_url: Annotated[str | None, Field(default=None, max_length=2048)] = None
    email: EmailStr | None = None


class SubscriptionResponse(BaseModel):
    id: int
    filter_type: str
    filter_value: str | None
    min_severity: str
    webhook_url: str | None
    email: str | None
    active: bool
    created_at: str
    updated_at: str
    last_triggered: str | None


class DeactivateResponse(BaseModel):
    ok: bool
    id: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _row_to_response(row: dict[str, Any]) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=row["id"],
        filter_type=row["filter_type"],
        filter_value=row["filter_value"],
        min_severity=row["min_severity"],
        webhook_url=row["webhook_url"],
        email=row["email"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_triggered=row["last_triggered"],
    )


@router.post(
    "/subscribe",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    payload: SubscribeRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> SubscriptionResponse:
    """Create a new alert subscription on the calling key.

    At least one delivery channel is required: webhook_url OR email. A
    subscription with neither is meaningless (the cron has nowhere to send).

    `filter_value` is required for every filter_type EXCEPT 'all'. For 'all'
    it is silently ignored (we set NULL on disk for clarity).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "alert subscriptions require an authenticated API key",
        )

    if not payload.webhook_url and not payload.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "at least one of webhook_url or email is required",
        )

    if payload.filter_type != "all" and not payload.filter_value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"filter_value is required when filter_type='{payload.filter_type}'",
        )

    if payload.webhook_url:
        _validate_webhook_url(payload.webhook_url)

    # Normalise: filter_value=NULL when filter_type='all' (no semantics).
    filter_value = None if payload.filter_type == "all" else payload.filter_value

    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO alert_subscriptions(
                api_key_hash, filter_type, filter_value, min_severity,
                webhook_url, email, active, created_at, updated_at
           ) VALUES (?,?,?,?,?,?,1,?,?)""",
        (
            ctx.key_hash,
            payload.filter_type,
            filter_value,
            payload.min_severity,
            payload.webhook_url,
            payload.email,
            now,
            now,
        ),
    )
    sub_id = cur.lastrowid
    if sub_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "failed to create subscription",
        )

    row = conn.execute(
        "SELECT * FROM alert_subscriptions WHERE id = ?",
        (sub_id,),
    ).fetchone()
    return _row_to_response(dict(row))


@router.get(
    "/subscriptions",
    response_model=list[SubscriptionResponse],
)
def list_subscriptions(
    ctx: ApiContextDep,
    conn: DbDep,
) -> list[SubscriptionResponse]:
    """List the calling key's active alert subscriptions."""
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "alert subscriptions require an authenticated API key",
        )
    rows = conn.execute(
        """SELECT id, api_key_hash, filter_type, filter_value, min_severity,
                  webhook_url, email, active, created_at, updated_at, last_triggered
             FROM alert_subscriptions
            WHERE api_key_hash = ? AND active = 1
         ORDER BY id ASC""",
        (ctx.key_hash,),
    ).fetchall()
    return [_row_to_response(dict(r)) for r in rows]


@router.delete(
    "/subscriptions/{sub_id}",
    response_model=DeactivateResponse,
)
def deactivate_subscription(
    sub_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeactivateResponse:
    """Deactivate (soft-delete) the subscription.

    The row stays on disk with active=0 so audit trails remain intact. A
    re-subscribe creates a fresh row rather than reviving the old one — this
    keeps `created_at` semantically honest.

    404 when the id does not belong to this key OR when it is already
    inactive (so callers cannot probe the id-space of other keys).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "alert subscriptions require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id FROM alert_subscriptions WHERE id = ? AND api_key_hash = ? AND active = 1",
        (sub_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "subscription not found",
        )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE alert_subscriptions SET active = 0, updated_at = ? "
        "WHERE id = ? AND api_key_hash = ?",
        (now, sub_id, ctx.key_hash),
    )
    return DeactivateResponse(ok=True, id=sub_id)


__all__ = [
    "FILTER_TYPES",
    "SEVERITIES",
    "SEVERITY_RANK",
    "router",
]
