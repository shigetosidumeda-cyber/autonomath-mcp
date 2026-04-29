"""Customer self-cap middleware (P3-W, dd_v8_09).

Enforces a customer-set monthly spend cap (`api_keys.monthly_cap_yen`) by
short-circuiting the request before it reaches the router when month-to-date
billable spend has already reached the cap.

Pricing posture (immutable):
    * AutonoMath is pure metered ¥3/req 税別 — see CLAUDE.md and memory
      `project_autonomath_business_model`. The cap does NOT change the unit
      price: it is a client-side budget control that customers set
      themselves via POST /v1/me/cap.
    * `monthly_cap_yen IS NULL` -> uncapped (default).
    * `monthly_cap_yen IS NOT NULL` -> request returns 503 with
      `cap_reached: true` once month-to-date billable spend reaches the cap.

Spend computation:
    Month-to-date billable spend = COUNT(usage_events row) * UNIT_PRICE_YEN,
    where the row is in the current JST calendar month and represents a
    successful metered call (status<400 AND metered=1). Failed calls (4xx /
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
    The 50 req/月 free anon quota is enforced separately by AnonIpLimitDep
    on each anon-accepting router, and never produces a Stripe usage record.

Cache:
    A simple process-local dict-of-(key_hash -> (cap, count, expires_at))
    with 5 min TTL. Aggregating usage_events for every request would be a
    SELECT COUNT(*) per request per authenticated key — fine on a small
    DB but redundant work. The cache is invalidated on POST /v1/me/cap so
    a customer who changes their cap sees the new value on the next call.

Cross-process note:
    Multiple uvicorn workers each have their own cache; a request hitting
    worker A may see a slightly stale count from worker B for up to 5 min.
    The over-shoot is bounded by `5min * QPS * ¥3` per worker, which at
    typical metered traffic (sub-1 QPS for a single key) is well under ¥1k
    for a customer who set ¥5k cap — acceptable for a soft trust signal.
    A multi-process Redis cache would tighten this, deferred until QPS
    scaling actually warrants it.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

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


# Cache entry layout: (cap_yen, count_in_month, expires_monotonic).
# cap_yen=None means "no cap"; we still cache so we don't re-read api_keys
# on every request for an uncapped customer.
_CapCacheEntry = tuple[int | None, int, float]
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


def _reset_cap_cache_state() -> None:
    """Test helper: clear cache."""
    invalidate_cap_cache(None)


def _jst_month_start(now: datetime | None = None) -> datetime:
    """Return YYYY-MM-01T00:00:00+09:00 for the current JST month."""
    now = now or datetime.now(_JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now_jst = now.astimezone(_JST)
    return now_jst.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


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
    """Return (cap_yen, count_metered_success_this_month, tier).

    Anonymous keys (key_hash==None) never reach this function. The COUNT only
    bills metered & successful (status<400) rows so 4xx/5xx don't burn cap.

    Migration 086: when the caller's row carries a non-NULL parent_key_id,
    we walk to the parent's row and read the parent's `monthly_cap_yen`,
    then aggregate the COUNT across every key in the tree (parent + all
    siblings + the caller). This means a SaaS partner's 1,000 child keys
    share ONE cap — children are invisible to Stripe and cannot escape
    their share of the parent's quota by spreading traffic.
    """
    row = conn.execute(
        "SELECT tier, monthly_cap_yen, id, parent_key_id "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return (None, 0, None)
    tier = row["tier"]
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
        (count,) = conn.execute(
            """SELECT COUNT(*)
                 FROM usage_events
                WHERE key_hash = ?
                  AND ts >= ?
                  AND metered = 1
                  AND status < 400""",
            (key_hash, month_start_utc_iso),
        ).fetchone()
    else:
        # Tree scope: parent + every child whose parent_key_id == root.
        tree_rows = conn.execute(
            "SELECT key_hash FROM api_keys "
            "WHERE id = ? OR parent_key_id = ?",
            (root, root),
        ).fetchall()
        tree_hashes = [
            r["key_hash"] if hasattr(r, "keys") else r[0] for r in tree_rows
        ]
        if not tree_hashes:
            tree_hashes = [key_hash]
        placeholders = ",".join("?" * len(tree_hashes))
        (count,) = conn.execute(
            f"""SELECT COUNT(*)
                  FROM usage_events
                 WHERE key_hash IN ({placeholders})
                   AND ts >= ?
                   AND metered = 1
                   AND status < 400""",  # noqa: S608 — placeholders only
            (*tree_hashes, month_start_utc_iso),
        ).fetchone()
    return (cap, int(count), tier)


def _cap_status(
    conn: sqlite3.Connection, key_hash: str
) -> tuple[int | None, int, str | None]:
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
            cap, count, _expires = entry
            # tier was never cached (only cap+count); re-read on miss to keep
            # the entry small. For the hot path we don't need tier.
            return cap, count, None

    cap, count, tier = _read_cap_and_count(conn, key_hash)
    with _cap_cache_lock:
        _cap_cache[key_hash] = (cap, count, now + _CACHE_TTL_S)
    return cap, count, tier


def _build_cap_reached_body(
    cap_yen: int, month_to_date_yen: int
) -> dict[str, Any]:
    return {
        "error": {
            "code": "monthly_cap_reached",
            "cap_reached": True,
            "cap_yen": cap_yen,
            "month_to_date_yen": month_to_date_yen,
            "resets_at": _jst_next_month_start_iso(),
            "message": (
                f"月次上限 ¥{cap_yen} に達しました。"
                f"翌月 1 日 00:00 JST にリセットされます。"
            ),
        }
    }


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

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
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
            or path in {"/healthz", "/readyz", "/v1/openapi.json"}
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
            return await call_next(request)

        # Read cap + count; fail-open on any DB error so a broken cache or
        # locked DB cannot self-DoS the API.
        try:
            conn = connect()
        except Exception:
            logger.exception("cap_middleware_connect_failed")
            return await call_next(request)
        try:
            cap_yen, count, _tier = _cap_status(conn, key_hash)
        except Exception:
            logger.exception("cap_middleware_read_failed")
            return await call_next(request)
        finally:
            with contextlib.suppress(Exception):  # pragma: no cover
                conn.close()

        if cap_yen is None:
            # Uncapped customer (the 90% case). No further work.
            return await call_next(request)

        month_to_date_yen = count * _UNIT_PRICE_YEN
        if month_to_date_yen < cap_yen:
            return await call_next(request)

        # Cap reached. 503 + spec body, no usage_events row created.
        retry_after_s = max(
            1,
            int(
                (
                    datetime.fromisoformat(_jst_next_month_start_iso())
                    - datetime.now(_JST)
                ).total_seconds()
            ),
        )
        body = _build_cap_reached_body(
            cap_yen=cap_yen, month_to_date_yen=month_to_date_yen
        )
        return JSONResponse(
            status_code=503,
            content=body,
            headers={"Retry-After": str(retry_after_s)},
        )


__all__ = [
    "CustomerCapMiddleware",
    "invalidate_cap_cache",
]
