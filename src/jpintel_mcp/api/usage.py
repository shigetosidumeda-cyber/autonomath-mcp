"""GET /v1/usage — anonymous + paid quota probe (Wave 17 P1).

Mirrors the MCP `get_usage_status` tool over HTTP so any LLM caller (or its
human-in-the-loop) can check the current period's quota state *without
consuming the slot itself*. The handler is intentionally NOT mounted with
``AnonIpLimitDep``: a probe of "how many calls do I have left" must be free
to call repeatedly — otherwise the tool itself burns the runway it's trying
to report on (audit a-wave-17-mcp-ux).

Posture:
  - Anonymous (no X-API-Key / Bearer): READ-ONLY lookup against the
    anon_rate_limit table for this IP+fingerprint hash. Never increments.
    Returns ``tier="anonymous"``, ``limit=settings.anon_rate_limit_per_day``,
    ``remaining = limit - call_count`` (clamped at 0), ``reset_at`` =
    next JST 翌日 00:00 ISO8601 (gotchas: anon resets are JST, NOT UTC).
  - Authenticated (paid): SUM(quantity) from usage_events for the current
    UTC calendar month + key_hash. Returns ``tier="paid"`` with
    ``limit=null`` (no upper cap on metered ¥3/req) and
    ``reset_at`` = first day of next UTC month (gotchas: authed counters
    use UTC, NOT JST — bucket boundary differs from anon by 9 hours).
  - Authenticated (free / dunning demote): like paid but with
    ``settings.rate_limit_free_per_day`` as ``limit`` and reset_at
    next UTC midnight.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from jpintel_mcp.api.anon_limit import (
    UPGRADE_URL_BASE,
    _client_ip,
    _jst_day_bucket,
    _jst_next_day_iso,
    hash_ip,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep  # noqa: TC001
from jpintel_mcp.config import settings

router = APIRouter(tags=["usage"])

# JST = UTC+9 fixed offset (no DST). Mirrors api/anon_limit.py — kept local so
# this module stays import-side-effect free of anon_limit's private helpers
# beyond the explicit re-exports above.
_JST = timezone(timedelta(hours=9))


class UsageStatus(BaseModel):
    """Single shape covers anonymous + paid + free (dunning) tiers.

    `limit` and `remaining` are nullable so the metered ("paid") tier can
    return both as None. Customers pay ¥3/req for successful metered
    requests and can set a hard monthly budget cap with `/v1/me/cap`.
    The dashboard (`/v1/me/dashboard`) is the right surface for "how much
    will this cost me this month", not /v1/usage.
    """

    tier: str  # "anonymous" | "paid" | "free"
    limit: int | None
    remaining: int | None
    used: int
    reset_at: str
    reset_timezone: str  # "JST" for anonymous, "UTC" for authed
    upgrade_url: str | None = None
    note: str | None = None


def _utc_next_month_iso(now: datetime | None = None) -> str:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if now.month == 12:
        nxt = now.replace(
            year=now.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        nxt = now.replace(
            month=now.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return nxt.isoformat()


def _utc_next_midnight_iso(now: datetime | None = None) -> str:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


def _utc_month_start_iso() -> str:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _anonymous_status(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """READ-ONLY anon quota lookup — never increments the counter.

    Same hashing logic (`hash_ip` with request) as the live enforce path,
    so the `used` count we return matches what the next protected call
    would see. If the row is absent (caller has not made any anon call
    today) we report used=0 and full remaining.
    """
    limit = settings.anon_rate_limit_per_day
    ip = _client_ip(request)
    ip_h = hash_ip(ip, request)
    day_bucket = _jst_day_bucket()
    used = 0
    try:
        row = conn.execute(
            "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
            (ip_h, day_bucket),
        ).fetchone()
    except sqlite3.OperationalError:
        # Schema missing — treat as fresh bucket. /v1/usage must never 500.
        row = None
    if row is not None:
        try:
            used = int(row["call_count"] if hasattr(row, "keys") else row[0])
        except (TypeError, ValueError):
            used = 0
    remaining = max(0, limit - used)
    return {
        "tier": "anonymous",
        "limit": limit,
        "remaining": remaining,
        "used": used,
        "reset_at": _jst_next_day_iso(),
        "reset_timezone": "JST",
        "upgrade_url": UPGRADE_URL_BASE,
        "note": (
            f"匿名 tier は IP+fingerprint 単位で {limit} req/日。"
            "JST 翌日 00:00 にリセット。X-API-Key で paid (¥3/req) に切替可能。"
        ),
    }


def _paid_status(conn: sqlite3.Connection, key_hash: str) -> dict[str, Any]:
    """Metered ("paid") tier — month-to-date billed units, no upper cap."""
    (used,) = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) FROM usage_events "
        "WHERE key_hash = ? AND ts >= ? "
        "AND metered = 1 AND status < 400",
        (key_hash, _utc_month_start_iso()),
    ).fetchone()
    return {
        "tier": "paid",
        "limit": None,
        "remaining": None,
        "used": int(used),
        "reset_at": _utc_next_month_iso(),
        "reset_timezone": "UTC",
        "upgrade_url": None,
        "note": (
            "Paid tier は metered ¥3/req 税別 (税込 ¥3.30)。"
            "月次集計は UTC 月初 00:00 リセット。"
            "Detailed breakdown: GET /v1/me/dashboard."
        ),
    }


def _free_authed_status(conn: sqlite3.Connection, key_hash: str) -> dict[str, Any]:
    """Dunning-demote tier — daily cap, UTC midnight reset."""
    daily_limit = settings.rate_limit_free_per_day
    bucket = datetime.now(UTC).strftime("%Y-%m-%d")
    (used,) = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) "
        "FROM usage_events WHERE key_hash = ? AND ts >= ?",
        (key_hash, bucket),
    ).fetchone()
    used_int = int(used)
    return {
        "tier": "free",
        "limit": daily_limit,
        "remaining": max(0, daily_limit - used_int),
        "used": used_int,
        "reset_at": _utc_next_midnight_iso(),
        "reset_timezone": "UTC",
        "upgrade_url": UPGRADE_URL_BASE,
        "note": (
            f"Free (dunning) tier — daily cap {daily_limit} req。"
            "UTC 翌日 00:00 リセット。請求情報を更新すると paid tier に復帰。"
        ),
    }


@router.get("/v1/usage", response_model=UsageStatus)
def get_usage(
    request: Request,
    ctx: ApiContextDep,
    conn: DbDep,
) -> UsageStatus:
    """Probe the caller's current quota state without consuming a slot.

    The handler is *not* attached to ``AnonIpLimitDep`` so anonymous
    callers can call it freely — the whole point of the tool is to
    avoid burning the bucket while checking it.
    """
    if ctx.key_hash is None:
        # Anonymous — IP+fingerprint based.
        return UsageStatus(**_anonymous_status(request, conn))
    if ctx.tier == "paid":
        return UsageStatus(**_paid_status(conn, ctx.key_hash))
    # Default: dunning-demote / "free" authed tier.
    return UsageStatus(**_free_authed_status(conn, ctx.key_hash))


__all__ = ["get_usage", "router", "UsageStatus"]
