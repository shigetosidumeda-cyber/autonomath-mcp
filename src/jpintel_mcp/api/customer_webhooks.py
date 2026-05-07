"""Customer-side outbound webhooks (¥3/req metered, HMAC required).

Distinct from `alerts.py` (FREE retention webhooks for am_amendment_snapshot
fan-out). This surface covers structured product events:

  * ``program.created``        — new program ingested into `programs` table
  * ``program.amended``        — am_amendment_diff row appeared
  * ``enforcement.added``      — new row in enforcement_cases
  * ``tax_ruleset.amended``    — tax_rulesets row updated
  * ``invoice_registrant.matched`` — invoice_registrants row matched
                                     a customer-side filter (future-facing;
                                     dispatcher honours the event_types
                                     list even if the matcher is not yet
                                     populated for it).

Endpoints (all require X-API-Key / Authorization: Bearer):

  POST   /v1/me/webhooks              — register a new webhook (returns
                                        secret_hmac ONCE).
  GET    /v1/me/webhooks              — list (secret reduced to last4).
  DELETE /v1/me/webhooks/{id}         — soft-delete (status='disabled').
  POST   /v1/me/webhooks/{id}/test    — synthesise a test delivery (does
                                        not bill, does not increment
                                        failure_count).

Auth: ``ApiContextDep`` (require_key). Anonymous tier rejected with 401 —
there is nothing to attach a webhook to. This matches /v1/me/cap and
/v1/me/alerts/* posture.

Pricing (project_autonomath_business_model — immutable):
  * Subscription is FREE. Test deliveries are FREE.
  * Each cron-driven SUCCESSFUL delivery (HTTP 2xx) is metered ¥3/req via
    Stripe usage_records — same unit price as a synchronous API call.
    The dispatcher (scripts/cron/dispatch_webhooks.py) emits the
    usage_event AFTER the 2xx is observed; failed deliveries are NOT
    billed.

Auto-disable (anti-runaway-billing):
  After 5 consecutive failures the row flips status='disabled' so the
  dispatcher stops attempting further deliveries. The customer receives an
  email if `email_schedule.email` is on file. They re-activate by DELETE +
  re-register (intentional friction — verifying the endpoint is healthy
  before re-arming is the customer's responsibility).

Solo + zero-touch: every action is self-serve via this router. No admin
escalation, no support ticket flow.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_log import log_event
from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
    require_metered_api_key,
)

logger = logging.getLogger("jpintel.customer_webhooks")

router = APIRouter(prefix="/v1/me/webhooks", tags=["customer_webhooks"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Allowed event types. Must stay in sync with scripts/cron/dispatch_webhooks.py
# (which dispatches by event_type). New event types REQUIRE adding to both
# this set and the dispatcher's source-table mapping.
EVENT_TYPES: tuple[str, ...] = (
    "program.created",
    "program.amended",
    "enforcement.added",
    "tax_ruleset.amended",
    "invoice_registrant.matched",
)

# Per-customer webhook count cap (defensive: prevent a single customer from
# abusing the surface to fan out thousands of test deliveries).
MAX_WEBHOOKS_PER_KEY = 10

# Test-delivery rate cap: 5 / minute / webhook_id. POST /v1/me/webhooks/{id}/test
# is a self-serve health check; in-process sliding window is enough at
# MVP scale.
_TEST_RATE_MAX = 5
_TEST_RATE_WINDOW_S = 60
_test_hits: dict[int, list[float]] = {}

# httpx timeout matches scripts/cron/dispatch_webhooks.py so the dashboard
# test-delivery and the cron see identical behaviour.
_HTTPX_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


# ---------------------------------------------------------------------------
# URL safety (mirrors api/alerts.py — separate copy on purpose so the two
# surfaces can drift their security posture independently if needed)
# ---------------------------------------------------------------------------


def _is_internal_host(host: str) -> bool:
    """Return True for RFC1918 / loopback / link-local / IPv6 ULA literals."""
    if not host:
        return True
    h = host.strip("[]").lower()
    if h == "localhost":
        return True
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
        return False


def _validate_webhook_url(url: str) -> None:
    """Raise HTTPException(400) on unsafe URLs. https-only, no internal hosts."""
    if len(url) > 2048:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "url too long (max 2048 chars)",
        )
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"url is not a valid URL: {exc}",
        ) from exc
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "url must use https:// (http and others are blocked)",
        )
    if not parsed.netloc or not parsed.hostname:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "url must include a host",
        )
    if _is_internal_host(parsed.hostname):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "url host resolves to a private/internal address",
        )


# ---------------------------------------------------------------------------
# Secret generation + HMAC signing
# ---------------------------------------------------------------------------


def generate_secret() -> str:
    """Issue a fresh HMAC shared secret. 32 bytes urlsafe = 256 bits entropy.

    Prefixed `whsec_` (Stripe convention) for human readability in customer
    config files. The prefix is part of the signing input only by virtue of
    being part of the raw secret string passed to hmac.new().
    """
    return "whsec_" + secrets.token_urlsafe(32)


def compute_signature(secret: str, payload_bytes: bytes) -> str:
    """Return ``hmac-sha256={hex}`` for the webhook signature headers.

    Header format mirrors Stripe / GitHub conventions:
        X-Jpcite-Signature: hmac-sha256=<64 hex chars>

    Customer verifies by recomputing HMAC over the raw request body with
    their stored secret. Constant-time comparison via hmac.compare_digest.
    """
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"hmac-sha256={sig}"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


EventTypeLiteral = Literal[
    "program.created",
    "program.amended",
    "enforcement.added",
    "tax_ruleset.amended",
    "invoice_registrant.matched",
]


class RegisterRequest(BaseModel):
    url: Annotated[str, Field(max_length=2048)]
    event_types: Annotated[list[EventTypeLiteral], Field(min_length=1, max_length=len(EVENT_TYPES))]


class WebhookResponse(BaseModel):
    id: int
    url: str
    event_types: list[str]
    status: str
    failure_count: int
    last_delivery_at: str | None
    created_at: str
    # secret_hmac is only ever populated on the POST /v1/me/webhooks
    # response. GET / list returns NULL here; clients should display
    # secret_last4 instead.
    secret_hmac: str | None = None
    secret_last4: str


class DeleteResponse(BaseModel):
    ok: bool
    id: int


class TestDeliveryResponse(BaseModel):
    ok: bool
    status_code: int | None
    error: str | None
    signature: str
    sent_at: str


class DeliveryRow(BaseModel):
    id: int
    event_type: str
    event_id: str
    status_code: int | None
    attempt_count: int
    delivered_at: str | None
    error: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: dict[str, Any], *, include_secret: str | None = None) -> WebhookResponse:
    secret_full = row.get("secret_hmac") or ""
    return WebhookResponse(
        id=row["id"],
        url=row["url"],
        event_types=json.loads(row["event_types_json"] or "[]"),
        status=row["status"],
        failure_count=row["failure_count"],
        last_delivery_at=row["last_delivery_at"],
        created_at=row["created_at"],
        secret_hmac=include_secret,
        secret_last4=secret_full[-4:] if secret_full else "????",
    )


def _check_test_rate_fallback(webhook_id: int) -> bool:
    """Return False when this webhook_id has hit 5 test deliveries / min."""
    now = time.monotonic()
    cutoff = now - _TEST_RATE_WINDOW_S
    bucket = _test_hits.setdefault(webhook_id, [])
    # Drop expired entries.
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= _TEST_RATE_MAX:
        return False
    bucket.append(now)
    return True


def _check_test_rate(
    webhook_id: int,
    conn: sqlite3.Connection | None = None,
    *,
    ip: str | None = None,
) -> bool:
    """Return False when this webhook_id has hit 5 test deliveries / min."""
    if conn is None:
        return _check_test_rate_fallback(webhook_id)

    started_transaction = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        started_transaction = True
        conn.execute(
            "DELETE FROM customer_webhooks_test_hits "
            "WHERE webhook_id = ? AND hit_at < datetime('now', ?)",
            (webhook_id, f"-{_TEST_RATE_WINDOW_S} seconds"),
        )
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM customer_webhooks_test_hits "
            "WHERE webhook_id = ? AND hit_at >= datetime('now', ?)",
            (webhook_id, f"-{_TEST_RATE_WINDOW_S} seconds"),
        ).fetchone()
        if count >= _TEST_RATE_MAX:
            conn.execute("COMMIT")
            return False
        conn.execute(
            "INSERT INTO customer_webhooks_test_hits(webhook_id, hit_at, ip) "
            "VALUES (?, datetime('now'), ?)",
            (webhook_id, ip),
        )
        conn.execute("COMMIT")
        return True
    except sqlite3.OperationalError as exc:
        if started_transaction:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
        if "customer_webhooks_test_hits" not in str(exc):
            raise
        return _check_test_rate_fallback(webhook_id)
    except Exception:
        if started_transaction:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_webhook(
    payload: RegisterRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> WebhookResponse:
    """Register a new outbound webhook.

    The response carries the full ``secret_hmac`` exactly once. Subsequent
    GET / list calls return only ``secret_last4``. The customer MUST persist
    the secret on their side at this moment — we cannot retrieve it later
    (parity with raw API key issuance via /signup).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "webhooks require an authenticated API key",
        )
    require_metered_api_key(ctx, "customer webhooks")

    _validate_webhook_url(payload.url)

    # Cap the total number of webhooks per key. 10 is generous for solo/SMB
    # customers and prevents a runaway test-loop from accumulating thousands
    # of disabled rows.
    (n_active,) = conn.execute(
        "SELECT COUNT(*) FROM customer_webhooks WHERE api_key_hash = ? AND status = 'active'",
        (ctx.key_hash,),
    ).fetchone()
    if n_active >= MAX_WEBHOOKS_PER_KEY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"webhook count cap reached ({MAX_WEBHOOKS_PER_KEY} active per key) — "
            "delete an existing webhook before registering a new one.",
        )

    # event_types_json: store the literal list. Pydantic validated it
    # against EventTypeLiteral so unknown values 422'd already.
    event_types_json = json.dumps(payload.event_types, ensure_ascii=False)

    secret = generate_secret()
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO customer_webhooks(
                api_key_hash, url, event_types_json, secret_hmac,
                status, failure_count, created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'active', 0, ?, ?)""",
        (ctx.key_hash, payload.url, event_types_json, secret, now, now),
    )
    new_id = cur.lastrowid
    if new_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "failed to register webhook",
        )

    row = conn.execute(
        "SELECT id, url, event_types_json, secret_hmac, status, failure_count, "
        "last_delivery_at, created_at FROM customer_webhooks WHERE id = ?",
        (new_id,),
    ).fetchone()

    # Audit log: tracking webhook registration helps with support / abuse
    # forensics. log_event swallows table-missing errors so a partial-migration
    # state cannot break the hot path.
    try:
        log_event(
            conn,
            event_type="webhook_register",
            key_hash=ctx.key_hash,
            customer_id=ctx.customer_id,
            request=None,
            webhook_id=new_id,
            url_host=urlparse(payload.url).hostname,
            event_types=list(payload.event_types),
        )
    except Exception:  # pragma: no cover — audit must not block hot path
        logger.warning("webhook_register audit failed", exc_info=True)

    return _row_to_response(dict(row), include_secret=secret)


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(
    ctx: ApiContextDep,
    conn: DbDep,
) -> list[WebhookResponse]:
    """List the calling key's webhooks (active + disabled, newest first).

    Disabled rows are intentionally surfaced (unlike alerts.py which hides
    inactive subs). For webhooks the operator must see WHY auto-disable
    fired and decide whether to re-register.

    ``secret_hmac`` is NEVER returned here — only ``secret_last4`` is.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "webhooks require an authenticated API key",
        )
    rows = conn.execute(
        "SELECT id, url, event_types_json, secret_hmac, status, failure_count, "
        "last_delivery_at, created_at FROM customer_webhooks "
        "WHERE api_key_hash = ? ORDER BY id DESC",
        (ctx.key_hash,),
    ).fetchall()
    return [_row_to_response(dict(r)) for r in rows]


@router.delete("/{webhook_id}", response_model=DeleteResponse)
def delete_webhook(
    webhook_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeleteResponse:
    """Soft-delete (status='disabled'). Row stays for audit; deliveries stop.

    404 when the id is not owned by this key — same posture as alerts.py
    (callers cannot probe other keys' id-space).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "webhooks require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id, status FROM customer_webhooks WHERE id = ? AND api_key_hash = ?",
        (webhook_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhook not found")
    if row["status"] == "disabled":
        # Idempotent: already deleted/disabled — return ok=True so the
        # dashboard can re-fire the action without erroring.
        return DeleteResponse(ok=True, id=webhook_id)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE customer_webhooks SET status='disabled', updated_at=?, "
        "disabled_at=?, disabled_reason='deleted_by_customer' "
        "WHERE id = ? AND api_key_hash = ?",
        (now, now, webhook_id, ctx.key_hash),
    )
    try:
        log_event(
            conn,
            event_type="webhook_delete",
            key_hash=ctx.key_hash,
            customer_id=ctx.customer_id,
            request=None,
            webhook_id=webhook_id,
        )
    except Exception:  # pragma: no cover
        logger.warning("webhook_delete audit failed", exc_info=True)
    return DeleteResponse(ok=True, id=webhook_id)


@router.post("/{webhook_id}/test", response_model=TestDeliveryResponse)
def test_delivery(
    webhook_id: int,
    request: Request,
    ctx: ApiContextDep,
    conn: DbDep,
) -> TestDeliveryResponse:
    """Synthesise a test POST against the registered URL.

    Cost: FREE. Does not increment ``failure_count`` (the customer is
    actively testing; a 500 here is informative, not a runaway-billing
    signal). Does not appear in ``webhook_deliveries`` (test traffic must
    not pollute the customer's audit trail).

    Rate-limited to 5 / minute / webhook_id. The cap is generous enough
    for normal "save → test → tweak → test" iteration but stops a
    customer from accidentally hammering their downstream during config.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "webhooks require an authenticated API key",
        )

    row = conn.execute(
        "SELECT id, url, secret_hmac, status FROM customer_webhooks "
        "WHERE id = ? AND api_key_hash = ?",
        (webhook_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhook not found")
    if row["status"] != "active":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "webhook is disabled — re-register before testing",
        )

    client_ip = request.client.host if request.client else None
    if not _check_test_rate(webhook_id, conn, ip=client_ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"test rate limit exceeded ({_TEST_RATE_MAX}/minute per webhook)",
            headers={"Retry-After": str(_TEST_RATE_WINDOW_S)},
        )

    now_iso = datetime.now(UTC).isoformat()
    test_payload = {
        "event_type": "test.ping",
        "timestamp": now_iso,
        "data": {
            "webhook_id": webhook_id,
            "message": (
                "This is a test delivery from jpcite (jpcite-webhook/1.0). "
                "If you see this, your endpoint received the POST. "
                "本サービスは公開情報の集約であり税務助言・法律相談ではありません (§52)."
            ),
        },
    }
    payload_bytes = json.dumps(test_payload, ensure_ascii=False).encode("utf-8")
    signature = compute_signature(row["secret_hmac"], payload_bytes)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jpcite-webhook/1.0",
        "X-Jpcite-Signature": signature,
        "X-Jpcite-Event": "test.ping",
        "X-Jpcite-Webhook-Id": str(webhook_id),
        # Backward-compatible aliases for customers who integrated before
        # the public jpcite header names were introduced.
        "X-Zeimu-Signature": signature,
        "X-Zeimu-Event": "test.ping",
        "X-Zeimu-Webhook-Id": str(webhook_id),
    }

    status_code: int | None = None
    error: str | None = None
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            r = client.post(row["url"], content=payload_bytes, headers=headers)
            status_code = r.status_code
            if r.status_code >= 300:
                # Capture a SHORT body excerpt for debugging (most webhook
                # consumers return JSON < 1KB on errors). Truncate hard.
                body_excerpt = (r.text or "")[:256]
                error = (
                    f"http_{r.status_code}: {body_excerpt}"
                    if body_excerpt
                    else f"http_{r.status_code}"
                )
    except httpx.TimeoutException:
        error = "timeout"
    except httpx.HTTPError as exc:
        error = f"transport_error: {exc!r}"[:256]
    except Exception as exc:  # pragma: no cover — defensive
        error = f"unexpected: {exc!r}"[:256]

    ok = status_code is not None and 200 <= status_code < 300
    return TestDeliveryResponse(
        ok=ok,
        status_code=status_code,
        error=error,
        signature=signature,
        sent_at=now_iso,
    )


@router.get("/{webhook_id}/deliveries", response_model=list[DeliveryRow])
def list_deliveries(
    webhook_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
    limit: int = 10,
) -> list[DeliveryRow]:
    """Return the most recent webhook_deliveries rows for the dashboard.

    Default 10 (max 100). Owner-scoped: the join on customer_webhooks
    ensures a caller cannot read another key's delivery log by passing a
    foreign id.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "webhooks require an authenticated API key",
        )
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    # Owner check first — same 404 posture as DELETE.
    owner = conn.execute(
        "SELECT id FROM customer_webhooks WHERE id = ? AND api_key_hash = ?",
        (webhook_id, ctx.key_hash),
    ).fetchone()
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhook not found")

    rows = conn.execute(
        """SELECT id, event_type, event_id, status_code, attempt_count,
                  delivered_at, error, created_at
             FROM webhook_deliveries
            WHERE webhook_id = ?
         ORDER BY created_at DESC, id DESC
            LIMIT ?""",
        (webhook_id, limit),
    ).fetchall()
    return [
        DeliveryRow(
            id=r["id"],
            event_type=r["event_type"],
            event_id=r["event_id"],
            status_code=r["status_code"],
            attempt_count=r["attempt_count"],
            delivered_at=r["delivered_at"],
            error=r["error"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


__all__ = [
    "EVENT_TYPES",
    "MAX_WEBHOOKS_PER_KEY",
    "compute_signature",
    "generate_secret",
    "router",
]
