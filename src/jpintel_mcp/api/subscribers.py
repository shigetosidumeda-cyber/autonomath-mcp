"""Newsletter / launch-updates subscription endpoints.

Public endpoints (no auth) for pre-launch email capture.

Flow:
  - POST /v1/subscribers            body { email, source? } -> { subscribed: true }
  - GET  /v1/subscribers/unsubscribe?token=...              -> plain HTML page

Privacy posture:
  - Duplicate signup returns the same success shape as a first signup so we
    never leak "this email is already subscribed" to an attacker enumerating
    addresses.
  - Rate-limit is a minimal per-IP in-memory counter (10 requests / hour per
    IP). Cross-process enforcement is intentionally out of scope for MVP.
  - Unsubscribe token is HMAC-SHA256(email, api_key_salt) so no DB lookup is
    needed to verify and nobody can forge one without the salt.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import sqlite3
import time
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/subscribers", tags=["subscribers"])


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per-IP)
# ---------------------------------------------------------------------------

_RATE_WINDOW_SECONDS = 3600
_RATE_MAX_PER_WINDOW = 10
_rate_hits: dict[str, deque[float]] = {}
_rate_lock = Lock()


def _rate_limit_check(ip: str) -> bool:
    """Return True if under the limit and record the hit. False if over."""
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_hits.setdefault(ip, deque())
        # drop expired
        cutoff = now - _RATE_WINDOW_SECONDS
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RATE_MAX_PER_WINDOW:
            return False
        bucket.append(now)
        return True


def _reset_rate_limit_state() -> None:
    """Test helper: clear the in-memory rate-limit bucket."""
    with _rate_lock:
        _rate_hits.clear()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Unsubscribe token (HMAC, no DB needed to verify)
# ---------------------------------------------------------------------------


def make_unsubscribe_token(email: str) -> str:
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        email.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_unsubscribe_token(email: str, token: str) -> bool:
    expected = make_unsubscribe_token(email)
    return hmac.compare_digest(expected, token)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    email: EmailStr
    source: str | None = Field(default=None, max_length=64)


class SubscribeResponse(BaseModel):
    subscribed: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscribe(
    payload: SubscribeRequest,
    request: Request,
    conn: DbDep,
) -> SubscribeResponse:
    ip = _client_ip(request)
    if not _rate_limit_check(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"rate limit exceeded ({_RATE_MAX_PER_WINDOW}/hour)",
        )

    email_norm = payload.email.strip().lower()
    source = (payload.source or "").strip()[:64] or None
    now = datetime.now(UTC).isoformat()

    with contextlib.suppress(sqlite3.IntegrityError):
        # Duplicate email — idempotent success, no leak.
        conn.execute(
            "INSERT INTO subscribers(email, source, created_at) VALUES (?, ?, ?)",
            (email_norm, source, now),
        )

    return SubscribeResponse(subscribed=True)


_UNSUB_HTML_OK = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsubscribed — AutonoMath</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", sans-serif;
         max-width: 560px; margin: 80px auto; padding: 0 20px; color: #111; line-height: 1.7; }
  h1 { font-size: 24px; margin: 0 0 12px; }
  p { color: #555; }
  a { color: #1e3a8a; }
</style>
</head>
<body>
  <h1>登録を解除しました / Unsubscribed.</h1>
  <p>今後 AutonoMath からメールを送ることはありません。</p>
  <p>You will no longer receive emails from AutonoMath.</p>
  <p><a href="/">&larr; Home</a></p>
</body>
</html>
"""

_UNSUB_HTML_BAD = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Invalid link — AutonoMath</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", sans-serif;
         max-width: 560px; margin: 80px auto; padding: 0 20px; color: #111; line-height: 1.7; }
  h1 { font-size: 24px; margin: 0 0 12px; }
  p { color: #555; }
  a { color: #1e3a8a; }
</style>
</head>
<body>
  <h1>リンクが無効です / Invalid link.</h1>
  <p>この解除リンクは期限切れか、改ざんされている可能性があります。</p>
  <p>This unsubscribe link is invalid or has been tampered with.</p>
  <p><a href="/">&larr; Home</a></p>
</body>
</html>
"""


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    conn: DbDep,
    token: Annotated[str, Query(min_length=16, max_length=128)],
    email: Annotated[str, Query(min_length=3, max_length=320)],
) -> HTMLResponse:
    email_norm = email.strip().lower()
    if not _verify_unsubscribe_token(email_norm, token):
        return HTMLResponse(_UNSUB_HTML_BAD, status_code=status.HTTP_400_BAD_REQUEST)

    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE subscribers SET unsubscribed_at = ? WHERE email = ? AND unsubscribed_at IS NULL",
        (now, email_norm),
    )
    # Always return OK even if email was never subscribed — avoids enumeration.
    return HTMLResponse(_UNSUB_HTML_OK, status_code=status.HTTP_200_OK)
