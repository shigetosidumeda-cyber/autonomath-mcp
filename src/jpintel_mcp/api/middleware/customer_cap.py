"""Customer self-cap middleware (P3-W, dd_v8_09).

Enforces a customer-set monthly spend cap (`api_keys.monthly_cap_yen`) by
short-circuiting the request before it reaches the router when the next
billable unit would exceed the cap.

Pricing posture (immutable):
    * AutonoMath is pure metered ¥3/req 税別 — see CLAUDE.md and memory
      `project_autonomath_business_model`. The cap does NOT change the unit
      price: it is a client-side budget control that customers set
      themselves via POST /v1/me/cap.
    * `monthly_cap_yen IS NULL` -> uncapped (default).
    * `monthly_cap_yen IS NOT NULL` -> request returns 503 with
      `cap_reached: true` once serving the next billable unit would exceed
      the cap.

Spend computation:
    Month-to-date billable spend = SUM(usage_events.quantity) * UNIT_PRICE_YEN,
    where the row is in the current JST calendar month and represents a
    successful metered call ((status IS NULL OR status<400) AND metered=1).
    Failed calls (4xx /
    5xx) are not billed and do not count toward the cap. This mirrors the
    "do not bill failures" rule already enforced in deps.log_usage().

When cap is reached:
    * Return 503 with the spec-mandated body (cap_reached: true,
      cap_yen, month_to_date_yen, resets_at, message).
    * **Do NOT log a usage_events row** for the rejected request — Stripe
      usage_records would otherwise be reported asynchronously and bill
      the customer for a request we never served. The router/handler is
      not invoked at all, so log_usage is never called.

Anonymous tier:
    Requests with no X-API-Key / Authorization: Bearer header are skipped.
    The 3 req/日 free anon quota is enforced separately by AnonIpLimitDep
    on each anon-accepting router, and never produces a Stripe usage record.

Cache:
    A simple process-local dict-of-(key_hash -> (cap, count, expires_at))
    with 5 min TTL. Aggregating usage_events for every request would be a
    SELECT COUNT(*) per request per authenticated key — fine on a small
    DB but redundant work. The cache is invalidated on POST /v1/me/cap so
    a customer who changes their cap sees the new value on the next call.

Final billing guard:
    The request-time middleware is a UX gate. deps.log_usage() performs the
    authoritative no-overcharge check again immediately before writing a
    successful metered usage_events row and reporting Stripe usage, under
    SQLite's writer lock. If a burst races the request-time gate, the later
    request is served but not billed rather than exceeding the customer cap.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    import sqlite3

    from fastapi import Request
    from starlette.responses import Response

logger = logging.getLogger("jpintel.cap")

# Pure metered ¥3/req 税別 (memory: project_autonomath_business_model).
# 税込 ¥3.30, but the cap is computed against the pre-tax line item because
# Stripe usage_records carry the pre-tax unit price; JCT is added at invoice
# render time. A customer who sets ¥5,000 cap will be billed up to ¥5,500
# 税込 worst case; that matches the dashboard hint ("税抜").
_UNIT_PRICE_YEN: int = 3

# 5 min TTL on the per-key cache. Long enough to amortise the COUNT(*) over
# bursty traffic, short enough that a customer who lowers their cap via
# POST /v1/me/cap sees the change quickly even without explicit invalidation.
_CACHE_TTL_S: float = 300.0

# JST = UTC+9, fixed offset.
_JST = timezone(timedelta(hours=9))


# Cache entry layout:
# (cap_yen, billable_units_in_month, expires_monotonic, tree_group_id).
# cap_yen=None means "no cap"; we still cache so we don't re-read api_keys
# on every request for an uncapped customer.
_CapCacheEntry = tuple[int | None, int, float, str]
_cap_cache: dict[str, _CapCacheEntry] = {}
_cap_cache_lock = threading.Lock()


def invalidate_cap_cache(key_hash: str | None = None) -> None:
    """Drop a single key's cache entry (or the whole cache if key_hash is None).

    Called by POST /v1/me/cap so a cap change takes effect immediately
    rather than after the 5-minute TTL.
    """
    with _cap_cache_lock:
        if key_hash is None:
            _cap_cache.clear()
            return
        _cap_cache.pop(key_hash, None)


def _cap_cache_scope(conn: sqlite3.Connection, key_hash: str) -> tuple[str, list[str]]:
    """Return a stable cache group id and every key hash in that billing tree."""
    row = conn.execute(
        "SELECT id, parent_key_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return f"key:{key_hash}", [key_hash]
    row_keys = row.keys() if hasattr(row, "keys") else []
    own_id = row["id"] if "id" in row_keys else None
    parent_key_id = row["parent_key_id"] if "parent_key_id" in row_keys else None
    root = parent_key_id if parent_key_id is not None else own_id
    if root is None:
        return f"key:{key_hash}", [key_hash]
    rows = conn.execute(
        "SELECT key_hash FROM api_keys WHERE id = ? OR parent_key_id = ?",
        (root, root),
    ).fetchall()
    hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in rows]
    if key_hash not in hashes:
        hashes.append(key_hash)
    return f"tree:{root}", hashes


def invalidate_cap_cache_for_tree(conn: sqlite3.Connection, key_hash: str | None = None) -> None:
    """Drop cached cap entries for every key sharing the caller's cap."""
    if key_hash is None:
        invalidate_cap_cache(None)
        return
    try:
        group_id, hashes = _cap_cache_scope(conn, key_hash)
    except Exception:
        invalidate_cap_cache(key_hash)
        return
    with _cap_cache_lock:
        for kh in hashes:
            _cap_cache.pop(kh, None)
        for kh, entry in list(_cap_cache.items()):
            if entry[3] == group_id:
                _cap_cache.pop(kh, None)


def _reset_cap_cache_state() -> None:
    """Test helper: clear cache."""
    invalidate_cap_cache(None)


def _jst_month_start(now: datetime | None = None) -> datetime:
    """Return YYYY-MM-01T00:00:00+09:00 for the current JST month."""
    now = now or datetime.now(_JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now_jst = now.astimezone(_JST)
    return now_jst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _jst_next_month_start_iso(now: datetime | None = None) -> str:
    """ISO8601 timestamp of the next JST 月初 (when the cap resets)."""
    start = _jst_month_start(now)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return nxt.isoformat()


def _extract_raw_key(request: Request) -> str | None:
    """Return the raw API key from headers, or None for anonymous."""
    raw = request.headers.get("x-api-key")
    if raw:
        return raw.strip() or None
    auth = request.headers.get("authorization")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip() or None
    return None


def _read_cap_and_count(
    conn: sqlite3.Connection, key_hash: str
) -> tuple[int | None, int, str | None]:
    """Return (cap_yen, billable_units_metered_success_this_month, tier).

    Anonymous keys (key_hash==None) never reach this function. The SUM only
    bills metered & successful (status<400) units so 4xx/5xx don't burn cap.

    Migration 086: when the caller's row carries a non-NULL parent_key_id,
    we walk to the parent's row and read the parent's `monthly_cap_yen`,
    then aggregate the COUNT across every key in the tree (parent + all
    siblings + the caller). This means a SaaS partner's 1,000 child keys
    share ONE cap — children are invisible to Stripe and cannot escape
    their share of the parent's quota by spreading traffic.
    """
    row = conn.execute(
        "SELECT tier, monthly_cap_yen, id, parent_key_id, revoked_at "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return (None, 0, None)
    tier = row["tier"]
    if row["revoked_at"] is not None or tier != "paid":
        return (None, 0, tier)
    row_keys = row.keys() if hasattr(row, "keys") else []
    parent_key_id = row["parent_key_id"] if "parent_key_id" in row_keys else None
    own_id = row["id"] if "id" in row_keys else None

    # Resolve the cap source: child rows inherit the parent's cap, parent
    # rows carry their own. Legacy rows (no id column) keep single-row
    # scope.
    if parent_key_id is not None:
        # Child key — read cap from the parent row.
        prow = conn.execute(
            "SELECT monthly_cap_yen FROM api_keys WHERE id = ?",
            (parent_key_id,),
        ).fetchone()
        cap = prow["monthly_cap_yen"] if prow else row["monthly_cap_yen"]
        root = parent_key_id
    else:
        cap = row["monthly_cap_yen"]
        root = own_id

    # Aggregate usage in the current JST calendar month. usage_events.ts is
    # an ISO8601 UTC string; we compare against the JST month boundary
    # converted to UTC. The query uses idx_usage_key_ts (key_hash, ts).
    month_start_jst = _jst_month_start()
    month_start_utc_iso = month_start_jst.astimezone(UTC).isoformat()

    if root is None:
        # Legacy row (pre-086 schema) — single-key scope.
        (units,) = conn.execute(
            """SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0)
                 FROM usage_events
                WHERE key_hash = ?
                  AND ts >= ?
                  AND metered = 1
                  AND (status IS NULL OR status < 400)""",
            (key_hash, month_start_utc_iso),
        ).fetchone()
    else:
        # Tree scope: parent + every child whose parent_key_id == root.
        tree_rows = conn.execute(
            "SELECT key_hash FROM api_keys WHERE id = ? OR parent_key_id = ?",
            (root, root),
        ).fetchall()
        tree_hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in tree_rows]
        if not tree_hashes:
            tree_hashes = [key_hash]
        placeholders = ",".join("?" * len(tree_hashes))
        (units,) = conn.execute(
            f"""SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0)
                  FROM usage_events
                 WHERE key_hash IN ({placeholders})
                   AND ts >= ?
                   AND metered = 1
                   AND (status IS NULL OR status < 400)""",  # noqa: S608 — placeholders only
            (*tree_hashes, month_start_utc_iso),
        ).fetchone()
    return (cap, int(units or 0), tier)


def _cap_status(conn: sqlite3.Connection, key_hash: str) -> tuple[int | None, int, str | None]:
    """Cached version of _read_cap_and_count.

    Returns (cap_yen, count_metered_success, tier) — same shape, with a
    5-min TTL keyed by key_hash. We cache every authenticated key's row,
    even uncapped ones, because the 90% case is "no cap" and avoiding the
    DB round-trip in that path is the whole point.
    """
    now = time.monotonic()
    with _cap_cache_lock:
        entry = _cap_cache.get(key_hash)
        if entry is not None and entry[2] > now:
            cap, count, _expires, _group_id = entry
            # A key can be revoked while this cache is warm. Re-read just
            # credential status so stale cache cannot mask auth with a cap 503.
            row = conn.execute(
                "SELECT tier, revoked_at FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None or row["tier"] != "paid":
                _cap_cache.pop(key_hash, None)
                return None, 0, row["tier"] if row is not None else None
            return cap, count, None

    cap, count, tier = _read_cap_and_count(conn, key_hash)
    try:
        group_id, hashes = _cap_cache_scope(conn, key_hash)
    except Exception:
        group_id, hashes = f"key:{key_hash}", [key_hash]
    expires = now + _CACHE_TTL_S
    with _cap_cache_lock:
        for kh in hashes:
            _cap_cache[kh] = (cap, count, expires, group_id)
    return cap, count, tier


def _build_cap_reached_body(
    cap_yen: int,
    month_to_date_yen: int,
    *,
    projected_yen: int | None = None,
    projected_units: int | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": "monthly_cap_reached",
        "cap_reached": True,
        "cap_yen": cap_yen,
        "month_to_date_yen": month_to_date_yen,
        "resets_at": _jst_next_month_start_iso(),
        "message": (
            f"月次上限 ¥{cap_yen} を超えるため、このリクエストは実行されません。"
            f"翌月 1 日 00:00 JST にリセットされます。"
        ),
    }
    if projected_yen is not None:
        error["projected_yen"] = projected_yen
    if projected_units is not None:
        error["projected_units"] = projected_units
    return {"error": error}


def _retry_after_seconds() -> int:
    return max(
        1,
        int(
            (
                datetime.fromisoformat(_jst_next_month_start_iso()) - datetime.now(_JST)
            ).total_seconds()
        ),
    )


def _cap_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "cap_unavailable",
            "cap_reached": True,
            "message": "コスト上限の確認が一時的に利用できません。課金保護のため、このリクエストは処理されませんでした。",
            "retry_after_seconds": 60,
        },
        headers={"Retry-After": "60"},
    )


def _coerce_units(units: int) -> int:
    try:
        units = int(units)
    except (TypeError, ValueError):
        units = 1
    return max(1, units)


def projected_monthly_cap_response(
    conn: sqlite3.Connection,
    key_hash: str | None,
    projected_units: int,
) -> JSONResponse | None:
    """Return a 503 response if a known multi-unit charge would exceed cap.

    The middleware can only price the default one-unit request. Batch/export
    handlers call this after they know the exact `log_usage(quantity=N)` value,
    before they create a Stripe-billable usage row.
    """
    if key_hash is None:
        return None
    units = _coerce_units(projected_units)
    cap_yen, count, _tier = _read_cap_and_count(conn, key_hash)
    if cap_yen is None:
        return None
    month_to_date_yen = count * _UNIT_PRICE_YEN
    projected_yen = month_to_date_yen + (units * _UNIT_PRICE_YEN)
    if projected_yen <= cap_yen:
        return None
    body = _build_cap_reached_body(
        cap_yen=cap_yen,
        month_to_date_yen=month_to_date_yen,
        projected_yen=projected_yen,
        projected_units=units,
    )
    return JSONResponse(
        status_code=503,
        content=body,
        headers={"Retry-After": str(_retry_after_seconds())},
    )


def note_cap_usage(key_hash: str | None, quantity: int = 1) -> None:
    """Pessimistically advance the in-process cap cache after billing.

    `usage_events` is sometimes written in FastAPI background tasks. Without
    this cache bump, a burst of successful requests inside the 5-minute TTL can
    keep seeing the pre-burst count and overshoot a customer-set cap.
    """
    if key_hash is None:
        return
    units = _coerce_units(quantity)
    now = time.monotonic()
    with _cap_cache_lock:
        entry = _cap_cache.get(key_hash)
        if entry is None:
            return
        cap, count, expires, group_id = entry
        if expires <= now:
            return
        for kh, cached in list(_cap_cache.items()):
            cached_cap, cached_count, cached_expires, cached_group = cached
            if cached_group != group_id or cached_expires <= now:
                continue
            _cap_cache[kh] = (
                cached_cap,
                cached_count + units,
                cached_expires,
                cached_group,
            )


def metered_charge_within_cap(
    conn: sqlite3.Connection,
    key_hash: str | None,
    quantity: int = 1,
) -> bool:
    """Return True iff recording this successful metered charge is allowed.

    This is the final billing-side guard used by deps.log_usage() under
    `BEGIN IMMEDIATE`. The middleware's projected check can be stale across
    workers; this check is intentionally fresh and fail-closed by its caller.
    """
    if key_hash is None:
        return True
    units = _coerce_units(quantity)
    cap_yen, count, _tier = _read_cap_and_count(conn, key_hash)
    if cap_yen is None:
        return True
    projected_yen = (count + units) * _UNIT_PRICE_YEN
    return projected_yen <= cap_yen


class CustomerCapMiddleware(BaseHTTPMiddleware):
    """Reject authenticated requests once the customer's monthly cap is hit.

    Skips:
      * Requests without X-API-Key / Authorization: Bearer (anonymous).
      * Requests where the key has no cap set (monthly_cap_yen IS NULL).
      * Requests where month-to-date billable < cap.

    On 503 path:
      * Returns spec body (cap_reached: true, etc.).
      * Does NOT increment usage_events (the router never runs, so
        deps.log_usage is never called).
      * Sets Retry-After to seconds-until-JST-月初.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow control-plane endpoints through, even at cap-reached:
        # the customer must be able to RAISE / REMOVE their cap, manage their
        # subscription, and rotate their key after hitting the cap. Without
        # this carve-out a paid customer who set ¥1 cap would lock themselves
        # out of the dashboard until JST 月初.
        path = request.url.path
        if (
            path.startswith("/v1/me")
            or path.startswith("/v1/session")
            or path.startswith("/v1/billing")
            or path in {"/healthz", "/readyz", "/v1/openapi.json", "/v1/openapi.agent.json"}
        ):
            return await call_next(request)

        raw = _extract_raw_key(request)
        if raw is None:
            # Anonymous — never capped here (the anon-quota dep does that).
            return await call_next(request)

        # Lazy import to avoid module-load cycles between api.deps and this
        # file. deps.py already imports config + db; we don't pull anything
        # additional in the hot path beyond what require_key would.
        try:
            from jpintel_mcp.api.deps import hash_api_key
            from jpintel_mcp.db.session import connect

            key_hash = hash_api_key(raw)
        except Exception:  # pragma: no cover — defensive
            logger.exception("cap_middleware_hash_failed")
            return _cap_unavailable_response()

        # Read cap + count. If this fails, fail closed: serving the request
        # would bypass the customer's own monthly budget guard and can create
        # a billable usage row.
        try:
            conn = connect()
        except Exception:
            logger.exception("cap_middleware_connect_failed")
            return _cap_unavailable_response()
        try:
            cap_yen, count, _tier = _cap_status(conn, key_hash)
        except Exception:
            logger.exception("cap_middleware_read_failed")
            return _cap_unavailable_response()
        finally:
            with contextlib.suppress(Exception):  # pragma: no cover
                conn.close()

        if cap_yen is None:
            # Uncapped customer (the 90% case). No further work.
            return await call_next(request)

        month_to_date_yen = count * _UNIT_PRICE_YEN
        projected_yen = month_to_date_yen + _UNIT_PRICE_YEN
        if projected_yen <= cap_yen:
            return await call_next(request)

        # Cap reached. 503 + spec body, no usage_events row created.
        body = _build_cap_reached_body(
            cap_yen=cap_yen,
            month_to_date_yen=month_to_date_yen,
            projected_yen=projected_yen,
            projected_units=1,
        )
        return JSONResponse(
            status_code=503,
            content=body,
            headers={"Retry-After": str(_retry_after_seconds())},
        )


__all__ = [
    "CustomerCapMiddleware",
    "invalidate_cap_cache",
    "invalidate_cap_cache_for_tree",
    "metered_charge_within_cap",
    "note_cap_usage",
    "projected_monthly_cap_response",
]
