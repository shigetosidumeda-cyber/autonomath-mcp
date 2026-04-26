"""Developer feedback capture (POST /v1/feedback).

Purpose: when a developer hits a weird response or has a naming suggestion,
they can POST a single free-text message + optional rating instead of opening
a GitHub issue. Authed keys get their tier/customer_id attached; anonymous
callers are accepted too (free tier).

Rate-limit posture:
  - 10 entries / day per key_hash (authed) OR per IP hash (anonymous).
  - Counted against the `feedback` table itself — same-day rows > threshold
    trigger 429. This reuses the daily-bucket idea from `deps._enforce_quota`
    so there is no separate in-memory bucket to keep consistent across the
    usage limiter.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)
from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


_RATE_LIMIT_PER_DAY = 10


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _hash_ip(ip: str) -> str:
    """HMAC the raw IP with the API key salt so the DB never stores raw IPs."""
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        ip.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    rating: Annotated[int | None, Field(default=None, ge=1, le=5)] = None
    endpoint: Annotated[str | None, Field(default=None, max_length=256)] = None
    request_id: Annotated[str | None, Field(default=None, max_length=128)] = None


class FeedbackResponse(BaseModel):
    received: bool
    feedback_id: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    payload: FeedbackRequest,
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> FeedbackResponse:
    ip = _client_ip(request)
    ip_hash = _hash_ip(ip)

    # Daily bucket, same "YYYY-MM-DD" prefix trick used elsewhere in the DB.
    bucket = datetime.now(UTC).strftime("%Y-%m-%d")

    # Rate-limit: count same-day rows from either this key_hash (authed) or
    # this ip_hash (anonymous). Using the table itself avoids a parallel
    # in-memory bucket that could drift from persisted state.
    if ctx.key_hash is not None:
        (recent_count,) = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE key_hash = ? AND created_at >= ?",
            (ctx.key_hash, bucket),
        ).fetchone()
    else:
        (recent_count,) = conn.execute(
            "SELECT COUNT(*) FROM feedback "
            "WHERE key_hash IS NULL AND ip_hash = ? AND created_at >= ?",
            (ip_hash, bucket),
        ).fetchone()

    if recent_count >= _RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"feedback rate limit exceeded ({_RATE_LIMIT_PER_DAY}/day)",
        )

    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO feedback(
               key_hash, customer_id, tier, message, rating,
               endpoint, request_id, ip_hash, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            ctx.key_hash,
            ctx.customer_id,
            ctx.tier if ctx.key_hash is not None else None,
            payload.message,
            payload.rating,
            payload.endpoint,
            payload.request_id,
            ip_hash,
            now,
        ),
    )
    feedback_id = cur.lastrowid or 0
    return FeedbackResponse(received=True, feedback_id=feedback_id)
