"""Real-time signal webhook subscriber surface (Wave 43.2.7 Dim G).

Distinct from `customer_webhooks.py` (per api_key webhook tree) AND
`customer_watches` (mig 088, per houjin/program/law target). This is the
broad subscription model — fire on ANY kokkai_bill / amendment /
enforcement_municipality matching a JSON filter envelope.

Endpoints (require X-API-Key):
  POST   /v1/realtime/subscribe              register a new subscription
  GET    /v1/realtime/subscribe              list calling key's subscriptions
  DELETE /v1/realtime/subscribe/{id}         soft-delete (status='disabled')
  GET    /v1/realtime/dispatch_history       paginated dispatch history

Pricing: registration / list / delete FREE; each 2xx delivery ¥3/req metered
by scripts/cron/dispatch_webhooks.py extension. NO LLM call anywhere.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from jpintel_mcp.api.deps import (  # noqa: TC001 — runtime for FastAPI Depends
    ApiContextDep,
    DbDep,
)

logger = logging.getLogger("jpintel.realtime_signal_v2")

router = APIRouter(prefix="/v1/realtime", tags=["realtime_signal"])

TARGET_KINDS: tuple[str, ...] = (
    "kokkai_bill",
    "amendment",
    "enforcement_municipality",
    "program_created",
    "tax_treaty_amended",
    "court_decision_added",
    "pubcomment_announcement",
    "other",
)

MAX_SUBSCRIPTIONS_PER_KEY = 50
_URL_MAX_LEN = 512
_FILTER_JSON_MAX_LEN = 4096
_SIGNATURE_SECRET_BYTES = 32


def _is_internal_host(host: str) -> bool:
    if not host or host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        )
    except ValueError:
        return False


def _validate_webhook_url(url: str) -> tuple[str, str]:
    if not url or len(url) > _URL_MAX_LEN:
        raise HTTPException(status_code=400, detail="webhook_url length out of range")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"webhook_url unparseable: {exc!s}") from exc
    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="webhook_url must use https://")
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        raise HTTPException(status_code=400, detail="webhook_url missing host")
    if _is_internal_host(host):
        raise HTTPException(status_code=400, detail="webhook_url targets internal host")
    return url, host


class SubscribeRequest(BaseModel):
    target_kind: Literal[
        "kokkai_bill", "amendment", "enforcement_municipality",
        "program_created", "tax_treaty_amended", "court_decision_added",
        "pubcomment_announcement", "other",
    ]
    filter_json: dict[str, Any] = Field(default_factory=dict)
    webhook_url: str

    @field_validator("filter_json")
    @classmethod
    def _bounded_filter(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > _FILTER_JSON_MAX_LEN:
            raise ValueError("filter_json exceeds max length")
        return v


class SubscriberResponse(BaseModel):
    subscriber_id: int
    target_kind: str
    filter_json: dict[str, Any]
    webhook_url: str
    status: str
    failure_count: int
    last_delivery_at: str | None
    last_signal_at: str | None
    created_at: str
    updated_at: str
    signature_secret: str | None = Field(
        default=None,
        description="HMAC secret. Returned ONLY on registration; null on list.",
    )


class DispatchHistoryItem(BaseModel):
    dispatch_id: int
    subscriber_id: int
    target_kind: str
    signal_id: str
    status_code: int | None
    attempt_count: int
    error: str | None
    delivered_at: str | None
    billed: bool
    created_at: str


class DispatchHistoryResponse(BaseModel):
    items: list[DispatchHistoryItem]
    total: int
    next_cursor: int | None


class SubscribeListResponse(BaseModel):
    items: list[SubscriberResponse]
    total: int


class DeleteResponse(BaseModel):
    subscriber_id: int
    status: Literal["disabled"]


def _resolve_am_conn(jp_conn: sqlite3.Connection) -> sqlite3.Connection:
    from jpintel_mcp.config import settings

    am_path = settings.autonomath_db_path
    conn = sqlite3.connect(str(am_path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_under_cap(am_conn: sqlite3.Connection, key_hash: str) -> None:
    row = am_conn.execute(
        "SELECT COUNT(*) FROM am_realtime_subscribers WHERE api_key_hash = ? AND status = 'active'",
        (key_hash,),
    ).fetchone()
    count = int(row[0]) if row else 0
    if count >= MAX_SUBSCRIPTIONS_PER_KEY:
        raise HTTPException(
            status_code=409,
            detail=f"active subscription cap ({MAX_SUBSCRIPTIONS_PER_KEY}) reached",
        )


def _row_to_subscriber(row: sqlite3.Row, include_secret: bool = False) -> SubscriberResponse:
    try:
        filter_obj = json.loads(row["filter_json"] or "{}")
    except json.JSONDecodeError:
        filter_obj = {}
    return SubscriberResponse(
        subscriber_id=int(row["subscriber_id"]),
        target_kind=row["target_kind"],
        filter_json=filter_obj,
        webhook_url=row["webhook_url"],
        status=row["status"],
        failure_count=int(row["failure_count"] or 0),
        last_delivery_at=row["last_delivery_at"],
        last_signal_at=row["last_signal_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        signature_secret=row["signature_secret"] if include_secret else None,
    )


@router.post(
    "/subscribe",
    response_model=SubscriberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    body: SubscribeRequest,
    api_ctx: Annotated[Any, ApiContextDep],
    jp_conn: Annotated[sqlite3.Connection, DbDep],
) -> SubscriberResponse:
    """Register a new real-time signal subscription. FREE. Returns secret ONCE."""
    key_hash = getattr(api_ctx, "api_key_hash", None) or getattr(api_ctx, "key_hash", None)
    if not key_hash:
        raise HTTPException(status_code=401, detail="api_key required")

    _validate_webhook_url(body.webhook_url)

    am_conn = _resolve_am_conn(jp_conn)
    try:
        _ensure_under_cap(am_conn, str(key_hash))
        secret_hex = secrets.token_hex(_SIGNATURE_SECRET_BYTES)
        now = datetime.now(UTC).isoformat()
        cur = am_conn.execute(
            """INSERT INTO am_realtime_subscribers(
                    api_key_hash, target_kind, filter_json, webhook_url,
                    signature_secret, status, failure_count, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(key_hash), body.target_kind,
                json.dumps(body.filter_json, ensure_ascii=False),
                body.webhook_url, secret_hex, "active", 0, now, now,
            ),
        )
        am_conn.commit()
        new_id = int(cur.lastrowid or 0)
        row = am_conn.execute(
            "SELECT * FROM am_realtime_subscribers WHERE subscriber_id = ?",
            (new_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="subscriber row not found after insert")
        logger.info(
            "realtime_signal.subscribe key=%s kind=%s id=%s",
            str(key_hash)[:12] + "…", body.target_kind, new_id,
        )
        return _row_to_subscriber(row, include_secret=True)
    finally:
        am_conn.close()


@router.get("/subscribe", response_model=SubscribeListResponse)
async def list_subscriptions(
    api_ctx: Annotated[Any, ApiContextDep],
    jp_conn: Annotated[sqlite3.Connection, DbDep],
) -> SubscribeListResponse:
    """List the calling key's active subscriptions. FREE."""
    key_hash = getattr(api_ctx, "api_key_hash", None) or getattr(api_ctx, "key_hash", None)
    if not key_hash:
        raise HTTPException(status_code=401, detail="api_key required")

    am_conn = _resolve_am_conn(jp_conn)
    try:
        rows = am_conn.execute(
            """SELECT * FROM am_realtime_subscribers
                WHERE api_key_hash = ?
             ORDER BY created_at DESC""",
            (str(key_hash),),
        ).fetchall()
        items = [_row_to_subscriber(r, include_secret=False) for r in rows]
        return SubscribeListResponse(items=items, total=len(items))
    finally:
        am_conn.close()


@router.delete(
    "/subscribe/{subscriber_id}",
    response_model=DeleteResponse,
)
async def delete_subscription(
    subscriber_id: int,
    api_ctx: Annotated[Any, ApiContextDep],
    jp_conn: Annotated[sqlite3.Connection, DbDep],
) -> DeleteResponse:
    """Soft-delete (status='disabled'). FREE. Idempotent."""
    key_hash = getattr(api_ctx, "api_key_hash", None) or getattr(api_ctx, "key_hash", None)
    if not key_hash:
        raise HTTPException(status_code=401, detail="api_key required")

    am_conn = _resolve_am_conn(jp_conn)
    try:
        row = am_conn.execute(
            "SELECT subscriber_id, status FROM am_realtime_subscribers "
            "WHERE subscriber_id = ? AND api_key_hash = ?",
            (subscriber_id, str(key_hash)),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="subscription not found")
        now = datetime.now(UTC).isoformat()
        am_conn.execute(
            """UPDATE am_realtime_subscribers
                  SET status = 'disabled', disabled_at = ?, disabled_reason = 'user_delete',
                      updated_at = ?
                WHERE subscriber_id = ? AND api_key_hash = ?""",
            (now, now, subscriber_id, str(key_hash)),
        )
        am_conn.commit()
        return DeleteResponse(subscriber_id=subscriber_id, status="disabled")
    finally:
        am_conn.close()


@router.get("/dispatch_history", response_model=DispatchHistoryResponse)
async def get_dispatch_history(
    api_ctx: Annotated[Any, ApiContextDep],
    jp_conn: Annotated[sqlite3.Connection, DbDep],
    subscriber_id: int | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> DispatchHistoryResponse:
    """Paginated dispatch history scoped to the calling key. FREE."""
    key_hash = getattr(api_ctx, "api_key_hash", None) or getattr(api_ctx, "key_hash", None)
    if not key_hash:
        raise HTTPException(status_code=401, detail="api_key required")
    limit = max(1, min(200, int(limit)))

    am_conn = _resolve_am_conn(jp_conn)
    try:
        sub_rows = am_conn.execute(
            "SELECT subscriber_id FROM am_realtime_subscribers WHERE api_key_hash = ?",
            (str(key_hash),),
        ).fetchall()
        sub_ids = [int(r[0]) for r in sub_rows]
        if not sub_ids:
            return DispatchHistoryResponse(items=[], total=0, next_cursor=None)
        if subscriber_id is not None:
            if subscriber_id not in sub_ids:
                raise HTTPException(status_code=404, detail="subscription not found")
            sub_ids = [subscriber_id]

        placeholders = ",".join(["?"] * len(sub_ids))
        cursor_pred = "AND dispatch_id < ?" if cursor is not None else ""
        params: list[Any] = list(sub_ids)
        if cursor is not None:
            params.append(int(cursor))
        params.append(limit + 1)

        rows = am_conn.execute(
            f"""SELECT dispatch_id, subscriber_id, target_kind, signal_id,
                       status_code, attempt_count, error, delivered_at, billed,
                       created_at
                  FROM am_realtime_dispatch_history
                 WHERE subscriber_id IN ({placeholders})
                   {cursor_pred}
              ORDER BY dispatch_id DESC
                 LIMIT ?""",
            params,
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            DispatchHistoryItem(
                dispatch_id=int(r["dispatch_id"]),
                subscriber_id=int(r["subscriber_id"]),
                target_kind=r["target_kind"],
                signal_id=r["signal_id"],
                status_code=int(r["status_code"]) if r["status_code"] is not None else None,
                attempt_count=int(r["attempt_count"] or 1),
                error=r["error"],
                delivered_at=r["delivered_at"],
                billed=bool(r["billed"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
        total_row = am_conn.execute(
            f"SELECT COUNT(*) FROM am_realtime_dispatch_history WHERE subscriber_id IN ({placeholders})",
            sub_ids,
        ).fetchone()
        total = int(total_row[0]) if total_row else len(items)
        next_cursor = int(items[-1].dispatch_id) if has_more and items else None
        return DispatchHistoryResponse(items=items, total=total, next_cursor=next_cursor)
    finally:
        am_conn.close()
