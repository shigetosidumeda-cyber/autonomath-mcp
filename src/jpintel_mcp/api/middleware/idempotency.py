"""Idempotency-Key 24h replay cache middleware (anti-runaway 三点セット C).

Why this exists
---------------
An LLM agent that POSTs the same `batch_get_programs` payload twice (e.g.
because of a transient network blip + automatic retry) would otherwise be
billed twice. The Stripe API's official mitigation pattern is the
`Idempotency-Key` header — RFC 8594-adjacent — and we adopt the same
contract: when the client supplies `Idempotency-Key: <ulid>`, the FIRST
request executes normally and we cache the response (status + headers +
body) for 24 hours; SUBSEQUENT requests with the same key replay the
cached response with `X-Idempotency-Replayed: true` and are NOT metered.

Cache key
---------
``sha256(api_key_hash + ':' + endpoint_path + ':' + body + ':' + key)``

Including the api_key_hash prevents two distinct customers from colliding on
the same arbitrary key. Including the body prevents a buggy client that
re-uses one Idempotency-Key across different payloads from short-circuiting
into the wrong cached response (the spec is "same key + different body =
fail closed" but we go a step further and treat them as separate cache
slots so the second body executes normally).

Storage
-------
SQLite table `am_idempotency_cache(cache_key, response_blob, expires_at)`,
migration 087 (target_db: jpintel). Eviction:
  * Lazy on read (middleware skips entries with expires_at <= now).
  * Daily cron sweep (`scripts/cron/idempotency_cache_sweep.py`, future).

Scope
-----
Only POST requests are eligible. GET / DELETE / OPTIONS pass through. POST
requests without `Idempotency-Key` pass through (the header is opt-in).

¥0 metering
-----------
The replay path bypasses every billing surface — no `usage_events` row, no
Stripe usage_record. We achieve this by returning the cached response
directly from the middleware before the router dispatches, mirroring how
the customer-cap 503 path skips billing.

Stripe webhook + admin paths
----------------------------
We exclude `/v1/billing/webhook` (Stripe's own deduplication via event_id)
and `/v1/admin/*` (operator surfaces, never customer-facing).
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request

logger = logging.getLogger("jpintel.idempotency")

# 24h TTL per spec.
_CACHE_TTL_HOURS = 24

# Header constants.
_HEADER_KEY = "idempotency-key"
_HEADER_REPLAYED = "X-Idempotency-Replayed"

# Hard cap on the request body size we will hash + cache. A 10MB POST is not
# a realistic shape for any AutonoMath endpoint (the largest is
# batch_get_programs with 50 ulids ≈ a few KB). Anything above the cap is
# bypassed (cache miss falls back to live execution; safer than caching
# arbitrarily large payloads).
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB

# Hop-by-hop / non-cacheable response headers we strip before serialisation.
# Replaying these would either harm correctness (Set-Cookie binding to a
# different session) or leak the original request's identity (X-Request-ID).
_SKIP_RESPONSE_HEADERS: frozenset[str] = frozenset(
    {
        "set-cookie",
        "authorization",
        "x-request-id",
        "x-process-time",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
    }
)

# Path prefixes / exact paths that bypass the cache entirely.
_BYPASS_PATH_PREFIXES: tuple[str, ...] = (
    "/v1/billing/webhook",  # Stripe handles its own dedup via event_id
    "/v1/admin/",  # operator-only, never customer-facing
    "/v1/me/feedback",  # one-shot user comment, dedup by content not key
)

_BYPASS_EXACT: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/openapi.json",
    }
)


def _is_bypass_path(path: str) -> bool:
    if path in _BYPASS_EXACT:
        return True
    return any(path.startswith(p) for p in _BYPASS_PATH_PREFIXES)


def _api_key_hash_for(request: Request) -> str:
    """Return a stable hash of the caller's identity for cache keying.

    Authed key → HMAC-shaped sha256 prefix mirroring `deps.hash_api_key`
    posture (without importing it, to avoid a circular dep on settings load).
    Anonymous → IP-based prefix, so two anon callers can't collide on each
    other's cache slots either. Kept short (16 hex) — collision chance over
    the 24h TTL window at realistic traffic volumes is negligible.
    """
    raw = request.headers.get("x-api-key", "").strip()
    if not raw:
        auth = request.headers.get("authorization", "")
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()
    if raw:
        return "k:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    fly = request.headers.get("fly-client-ip", "").strip()
    if fly:
        return "ip:" + hashlib.sha256(fly.encode("utf-8")).hexdigest()[:32]
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return "ip:" + hashlib.sha256(first.encode("utf-8")).hexdigest()[:32]
    if request.client:
        return "ip:" + hashlib.sha256(
            request.client.host.encode("utf-8")
        ).hexdigest()[:32]
    return "ip:unknown"


def _compute_cache_key(
    api_key_hash: str, endpoint: str, body: bytes, key: str
) -> str:
    h = hashlib.sha256()
    h.update(api_key_hash.encode("utf-8"))
    h.update(b":")
    h.update(endpoint.encode("utf-8"))
    h.update(b":")
    h.update(body)
    h.update(b":")
    h.update(key.encode("utf-8"))
    return h.hexdigest()


def _serialise_response(
    status_code: int, headers: dict[str, str], body: bytes
) -> str:
    payload = {
        "status": status_code,
        "headers": {
            k: v
            for k, v in headers.items()
            if k.lower() not in _SKIP_RESPONSE_HEADERS
        },
        "body_b64": base64.b64encode(body).decode("ascii"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialise_response(blob: str) -> tuple[int, dict[str, str], bytes]:
    payload = json.loads(blob)
    return (
        int(payload["status"]),
        dict(payload.get("headers") or {}),
        base64.b64decode(payload.get("body_b64", "")),
    )


def _read_cached(conn: sqlite3.Connection, cache_key: str) -> str | None:
    """Return the cached blob, or None on miss / expired / table absent."""
    try:
        row = conn.execute(
            "SELECT response_blob, expires_at FROM am_idempotency_cache "
            "WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    except sqlite3.OperationalError:
        # Migration 087 not applied yet — treat as cold miss (handler runs
        # normally; correctness preserved at the cost of replay safety).
        return None
    if row is None:
        return None
    # row may be a sqlite3.Row (named) or a tuple, depending on connection.
    try:
        blob = row["response_blob"]
        expires_at = row["expires_at"]
    except (IndexError, KeyError, TypeError):
        blob = row[0]
        expires_at = row[1]
    if not blob or not expires_at:
        return None
    try:
        if datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) <= datetime.now(UTC):
            return None
    except ValueError:
        return None
    return str(blob)


def _write_cached(
    conn: sqlite3.Connection, cache_key: str, blob: str, *, ttl_hours: int
) -> None:
    expires_at = (
        datetime.now(UTC) + timedelta(hours=ttl_hours)
    ).isoformat()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_idempotency_cache("
            "    cache_key, response_blob, expires_at, created_at"
            ") VALUES (?,?,?,?)",
            (cache_key, blob, expires_at, datetime.now(UTC).isoformat()),
        )
    except sqlite3.OperationalError:
        # Migration not applied; silently drop the write so the request
        # still succeeds — the next caller will see a cache miss.
        logger.warning("idempotency_cache_write_skipped_table_missing")


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Cache + replay POST responses keyed on `Idempotency-Key`.

    Mount order: AFTER CostCapMiddleware (so a replayed response also
    short-circuits the cap path), BEFORE per-route routers (this is a
    middleware, not a dep). The cached body is served WITHOUT triggering
    `log_usage`, so replays are ¥0 metered.
    """

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Callable
    ) -> Response:
        # Only POST requests are eligible.
        if request.method != "POST":
            return await call_next(request)

        path = request.url.path
        if _is_bypass_path(path):
            return await call_next(request)

        idempotency_key = request.headers.get(_HEADER_KEY) or request.headers.get(
            _HEADER_KEY.replace("-", "_")
        )
        if not idempotency_key:
            # Header opt-in only — pass through unchanged.
            return await call_next(request)
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            return await call_next(request)

        # Read body. Starlette consumes the body stream once; we re-inject
        # via `request._receive` so the downstream handler still sees it.
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            # Refuse to cache arbitrarily large payloads — pass through.
            return await call_next(request)

        # Re-inject the buffered body so call_next() sees it.
        async def _receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]

        api_key_hash = _api_key_hash_for(request)
        cache_key = _compute_cache_key(
            api_key_hash, path, body, idempotency_key
        )

        # Connect on demand; fail-open on any DB error.
        try:
            from jpintel_mcp.db.session import connect

            conn = connect()
        except Exception:  # pragma: no cover — defensive
            logger.exception("idempotency_connect_failed")
            return await call_next(request)

        try:
            cached_blob = _read_cached(conn, cache_key)
        except Exception:  # pragma: no cover — defensive
            logger.exception("idempotency_read_failed")
            cached_blob = None

        if cached_blob is not None:
            # Replay path — bypass the router entirely. ¥0 (no log_usage).
            try:
                status_code, hdrs, body_bytes = _deserialise_response(
                    cached_blob
                )
            except Exception:  # pragma: no cover — defensive
                logger.exception("idempotency_deserialise_failed")
                with contextlib.suppress(Exception):
                    conn.close()
                return await call_next(request)
            with contextlib.suppress(Exception):
                conn.close()
            hdrs[_HEADER_REPLAYED] = "true"
            hdrs["X-Metered"] = "false"
            hdrs["X-Cost-Yen"] = "0"
            return Response(
                content=body_bytes,
                status_code=status_code,
                headers=hdrs,
            )

        # Cache miss — run the handler, then capture and cache the response.
        try:
            response = await call_next(request)
        except Exception:
            with contextlib.suppress(Exception):
                conn.close()
            raise

        # Only cache successful (2xx) responses. Caching a 4xx / 5xx would
        # lock the customer into the failure for 24h; live retries are safer.
        if 200 <= response.status_code < 300:
            try:
                # Drain the streaming body so we can serialise + replay it,
                # then re-attach a fresh body iterator.
                resp_body = b""
                async for chunk in response.body_iterator:
                    resp_body += chunk
                blob = _serialise_response(
                    response.status_code,
                    {k: v for k, v in response.headers.items()},
                    resp_body,
                )
                _write_cached(
                    conn, cache_key, blob, ttl_hours=_CACHE_TTL_HOURS
                )
                # Rebuild a Response so downstream gets a usable body.
                new_resp = Response(
                    content=resp_body,
                    status_code=response.status_code,
                    headers={k: v for k, v in response.headers.items()},
                    media_type=response.media_type,
                )
                response = new_resp
            except Exception:  # pragma: no cover — defensive
                logger.exception("idempotency_capture_failed")
        with contextlib.suppress(Exception):
            conn.close()
        return response


__all__ = [
    "IdempotencyMiddleware",
    "_compute_cache_key",
    "_serialise_response",
    "_deserialise_response",
]
