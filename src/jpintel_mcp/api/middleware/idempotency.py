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
the same arbitrary key. Including the body prevents replaying the wrong
response; a second collision sentinel rejects the same key with a different
payload before it can run as a separate metered request.

Storage
-------
SQLite table `am_idempotency_cache(cache_key, response_blob, expires_at)`,
migration 087 (target_db: jpintel). Eviction:
  * Lazy on read (middleware skips entries with expires_at <= now).
  * Daily cron sweep (`scripts/cron/idempotency_cache_sweep.py`, future).

Scope
-----
Only allowlisted data-query POST requests are eligible. GET / DELETE /
OPTIONS, credential issuance, billing, login, webhooks, and admin paths pass
through. POST requests without `Idempotency-Key` pass through (the header is
opt-in).

¥0 metering
-----------
The replay path bypasses every billing surface — no `usage_events` row, no
Stripe usage_record. We achieve this by returning the cached response
directly from the middleware before the router dispatches, mirroring how
the customer-cap 503 path skips billing.

Sensitive POSTs are intentionally excluded so raw API keys, session cookies,
Stripe redirects, webhooks, and user comments are never replayed from this
generic cache.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request

logger = logging.getLogger("jpintel.idempotency")

# 24h TTL per spec.
_CACHE_TTL_HOURS = 24
_PENDING_PREFIX = "__pending__:"
_PENDING_TTL_SECONDS = 3600
_PENDING_WAIT_SECONDS = 15

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

# Only pure data-query POST endpoints are cacheable. This keeps the generic
# replay layer away from raw-key issuance, session cookies, Stripe redirects,
# webhooks, dashboard mutations, and one-shot user submissions.
_CACHEABLE_EXACT: frozenset[str] = frozenset(
    {
        "/v1/programs/batch",
        "/v1/programs/prescreen",
        "/v1/exclusions/check",
        "/v1/funding_stack/check",
        "/v1/tax_rulesets/evaluate",
        "/v1/court-decisions/by-statute",
        "/v1/evidence/packets/query",
        "/v1/am/validate",
        "/v1/audit/batch_evaluate",
        "/v1/audit/workpaper",
        "/v1/am/dd_batch",
        "/v1/am/dd_export",
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
        "/v1/openapi.agent.json",
    }
)


def _is_bypass_path(path: str) -> bool:
    if path not in _CACHEABLE_EXACT:
        return True
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


def _raw_api_key_for(request: Request) -> str:
    raw = request.headers.get("x-api-key", "").strip()
    if raw:
        return raw
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _raw_api_key_present(request: Request) -> bool:
    return bool(_raw_api_key_for(request))


def _row_value(row: object, name: str, index: int) -> object:
    try:
        return row[name]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return row[index]  # type: ignore[index]


def _iso_is_past(value: object, *, now: datetime | None = None) -> bool:
    if not value:
        return False
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) <= (now or datetime.now(UTC))


def _cached_replay_auth_still_valid(
    conn: sqlite3.Connection, request: Request
) -> bool:
    """Re-check auth before serving a cached response.

    Replays skip the router, so they must not skip revocation / trial-expiry
    gates. The first request still executes through the normal dependency
    stack; this guard only applies to cached responses and pending waits.
    """
    raw = _raw_api_key_for(request)
    if not raw:
        return False
    try:
        from jpintel_mcp.api.deps import hash_api_key

        key_hash = hash_api_key(raw)
        try:
            row = conn.execute(
                "SELECT tier, revoked_at, trial_expires_at "
                "FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT tier, revoked_at FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        if row is None:
            return False
        tier = str(_row_value(row, "tier", 0) or "")
        revoked_at = _row_value(row, "revoked_at", 1)
        if revoked_at:
            return False
        try:
            trial_expires_at = _row_value(row, "trial_expires_at", 2)
        except Exception:
            trial_expires_at = None
        if tier == "trial" and _iso_is_past(trial_expires_at):
            now_iso = datetime.now(UTC).isoformat()
            with contextlib.suppress(sqlite3.Error):
                conn.execute(
                    "UPDATE api_keys SET revoked_at = ? "
                    "WHERE key_hash = ? AND revoked_at IS NULL",
                    (now_iso, key_hash),
                )
            return False
        return True
    except Exception:  # pragma: no cover — defensive fail-closed
        logger.exception("idempotency_replay_auth_check_failed")
        return False


def _auth_failed_response() -> Response:
    return Response(
        content=json.dumps(
            {"detail": "api key revoked or expired"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        status_code=401,
        media_type="application/json",
        headers={"X-Metered": "false", "X-Cost-Yen": "0"},
    )


def _idempotency_error_response(
    *,
    error: str,
    detail: str,
    status_code: int,
    retry_after: str | None = None,
) -> Response:
    headers = {"X-Metered": "false", "X-Cost-Yen": "0"}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return Response(
        content=json.dumps(
            {"error": error, "detail": detail},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        status_code=status_code,
        media_type="application/json",
        headers=headers,
    )


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


def _compute_collision_key(
    api_key_hash: str, endpoint: str, key: str
) -> str:
    """Cache slot keyed only on (api_key_hash, endpoint, idempotency-key).

    The full cache_key is keyed on the BODY too (so a buggy retry with a
    different payload doesn't replay the wrong response). The collision key
    omits the body and stores a sha256(body) fingerprint so that on the next
    request we can detect "same Idempotency-Key + DIFFERENT body" and return
    409 instead of silently treating it as an unrelated request.
    """
    h = hashlib.sha256()
    h.update(b"collision:")
    h.update(api_key_hash.encode("utf-8"))
    h.update(b":")
    h.update(endpoint.encode("utf-8"))
    h.update(b":")
    h.update(key.encode("utf-8"))
    return h.hexdigest()


def _body_fingerprint(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _check_or_record_body_fingerprint(
    conn: sqlite3.Connection, collision_key: str, body_fp: str
) -> tuple[str, str | None]:
    """Return (state, seen_fp): ok, mismatch, busy, or unavailable.

    Implementation note: we store the fingerprint in the same
    ``am_idempotency_cache`` table by repurposing ``response_blob`` to
    hold the literal string ``__bodyfp__:<sha256hex>`` and ``expires_at`` to
    the same TTL. The blob format is mutually exclusive with the cached
    response payloads (which are JSON) and the pending sentinel, so the
    parsers in this module always know which slot they are looking at.
    """
    fp_blob = f"__bodyfp__:{body_fp}"
    expires_at = (datetime.now(UTC) + timedelta(hours=_CACHE_TTL_HOURS)).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT response_blob, expires_at FROM am_idempotency_cache "
            "WHERE cache_key = ?",
            (collision_key,),
        ).fetchone()
        if row is not None:
            try:
                existing = row["response_blob"]
                row_expires_at = row["expires_at"]
            except (IndexError, KeyError, TypeError):
                existing = row[0]
                row_expires_at = row[1]
            expired = False
            try:
                expired = (
                    datetime.fromisoformat(str(row_expires_at).replace("Z", "+00:00"))
                    <= datetime.now(UTC)
                )
            except ValueError:
                expired = True
            existing = str(existing or "")
            if not expired and existing.startswith("__bodyfp__:"):
                seen_fp = existing.split(":", 1)[1]
                conn.execute("COMMIT")
                if seen_fp != body_fp:
                    return "mismatch", seen_fp
                return "ok", None
            conn.execute(
                "DELETE FROM am_idempotency_cache WHERE cache_key = ?",
                (collision_key,),
            )
        conn.execute(
            "INSERT INTO am_idempotency_cache("
            "    cache_key, response_blob, expires_at, created_at"
            ") VALUES (?,?,?,?)",
            (collision_key, fp_blob, expires_at, datetime.now(UTC).isoformat()),
        )
        conn.execute("COMMIT")
        return "ok", None
    except sqlite3.OperationalError as exc:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        if _sqlite_busy(exc):
            logger.warning("idempotency_collision_check_busy")
            return "busy", None
        logger.warning("idempotency_collision_check_unavailable")
        return "unavailable", None
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise


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
    if str(blob).startswith(_PENDING_PREFIX):
        return None
    try:
        if datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) <= datetime.now(UTC):
            return None
    except ValueError:
        return None
    return str(blob)


def _sqlite_busy(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _delete_cached(conn: sqlite3.Connection, cache_key: str) -> None:
    try:
        conn.execute("DELETE FROM am_idempotency_cache WHERE cache_key = ?", (cache_key,))
    except sqlite3.OperationalError:
        return


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


def _claim_or_read_cached(
    conn: sqlite3.Connection, cache_key: str
) -> tuple[str, str | None]:
    """Return hit, pending, busy, unavailable, or owner.

    The pending sentinel closes the concurrent double-billing gap: one
    request owns the live execution; simultaneous replays with the same key
    wait for the cached response instead of dispatching another metered call.
    If SQLite is busy, fail closed as ``busy`` so the middleware can return a
    retryable non-metered response instead of running a second live request.
    """
    now = datetime.now(UTC)
    pending_expires = (now + timedelta(seconds=_PENDING_TTL_SECONDS)).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT response_blob, expires_at FROM am_idempotency_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is not None:
            try:
                blob = row["response_blob"]
                expires_at = row["expires_at"]
            except (IndexError, KeyError, TypeError):
                blob = row[0]
                expires_at = row[1]
            expired = False
            try:
                expired = (
                    datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    <= now
                )
            except ValueError:
                expired = True
            if expired and str(blob).startswith(_PENDING_PREFIX):
                conn.execute(
                    "UPDATE am_idempotency_cache "
                    "SET response_blob = ?, expires_at = ?, created_at = ? "
                    "WHERE cache_key = ?",
                    (
                        _PENDING_PREFIX + str(now.timestamp()),
                        pending_expires,
                        now.isoformat(),
                        cache_key,
                    ),
                )
                conn.execute("COMMIT")
                return "busy", None
            if expired:
                conn.execute(
                    "DELETE FROM am_idempotency_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                row = None
            elif str(blob).startswith(_PENDING_PREFIX):
                conn.execute("COMMIT")
                return "pending", None
            else:
                conn.execute("COMMIT")
                return "hit", str(blob)
        if row is None:
            conn.execute(
                "INSERT INTO am_idempotency_cache("
                "    cache_key, response_blob, expires_at, created_at"
                ") VALUES (?,?,?,?)",
                (
                    cache_key,
                    _PENDING_PREFIX + str(now.timestamp()),
                    pending_expires,
                    now.isoformat(),
                ),
            )
            conn.execute("COMMIT")
            return "owner", None
    except sqlite3.OperationalError as exc:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        if _sqlite_busy(exc):
            logger.warning("idempotency_claim_busy")
            return "busy", None
        logger.warning("idempotency_claim_unavailable")
        return "unavailable", None
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise
    return "owner", None


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

        # Anonymous callers are intentionally not replay-cached. Otherwise a
        # single successful anonymous POST could be replayed indefinitely
        # without touching the daily anonymous quota.
        if not _raw_api_key_present(request):
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
        collision_key = _compute_collision_key(api_key_hash, path, idempotency_key)
        billing_key = "idem_" + hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

        # Connect on demand. For idempotency-enabled paid POSTs, fail closed:
        # dispatching live without the cache DB can create duplicate charges.
        try:
            from jpintel_mcp.db.session import connect

            conn = connect()
        except Exception:  # pragma: no cover — defensive
            logger.exception("idempotency_connect_failed")
            return _idempotency_error_response(
                error="idempotency_cache_unavailable",
                detail="retry later",
                status_code=503,
                retry_after="1",
            )

        # Collision detection: same Idempotency-Key with a DIFFERENT body is
        # a client bug (the spec says a key uniquely names ONE request). We
        # 409 instead of silently dispatching a separate metered call —
        # matches Stripe's `idempotency_key_in_use` 409 contract.
        try:
            body_fp = _body_fingerprint(body)
            collision_state, seen_fp = _check_or_record_body_fingerprint(
                conn, collision_key, body_fp
            )
            if collision_state == "mismatch":
                with contextlib.suppress(Exception):
                    conn.close()
                return _idempotency_error_response(
                    error="idempotency_key_in_use",
                    detail=(
                        "Idempotency-Key was previously seen with a different "
                        "request body. Use a fresh key for a new request."
                    ),
                    status_code=409,
                )
            if collision_state in {"busy", "unavailable"}:
                with contextlib.suppress(Exception):
                    conn.close()
                return _idempotency_error_response(
                    error=(
                        "idempotency_cache_busy"
                        if collision_state == "busy"
                        else "idempotency_cache_unavailable"
                    ),
                    detail="retry later",
                    status_code=503,
                    retry_after="1",
                )
        except Exception:  # pragma: no cover — defensive
            logger.exception("idempotency_collision_check_failed")
            with contextlib.suppress(Exception):
                conn.close()
            return _idempotency_error_response(
                error="idempotency_cache_unavailable",
                detail="retry later",
                status_code=503,
                retry_after="1",
            )

        try:
            cache_state, cached_blob = _claim_or_read_cached(conn, cache_key)
        except Exception:  # pragma: no cover — defensive
            logger.exception("idempotency_claim_failed")
            with contextlib.suppress(Exception):
                conn.close()
            return _idempotency_error_response(
                error="idempotency_cache_unavailable",
                detail="retry later",
                status_code=503,
                retry_after="1",
            )

        if cache_state == "hit" and cached_blob is not None:
            # Replay path — bypass the router entirely. ¥0 (no log_usage).
            if not _cached_replay_auth_still_valid(conn, request):
                with contextlib.suppress(Exception):
                    conn.close()
                return _auth_failed_response()
            try:
                status_code, hdrs, body_bytes = _deserialise_response(
                    cached_blob
                )
            except Exception:  # pragma: no cover — defensive
                logger.exception("idempotency_deserialise_failed")
                with contextlib.suppress(Exception):
                    conn.close()
                return _idempotency_error_response(
                    error="idempotency_cache_unavailable",
                    detail="retry later",
                    status_code=503,
                    retry_after="1",
                )
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

        if cache_state == "busy":
            with contextlib.suppress(Exception):
                conn.close()
            return _idempotency_error_response(
                error="idempotency_cache_busy",
                detail="retry later",
                status_code=503,
                retry_after="1",
            )

        if cache_state == "unavailable":
            with contextlib.suppress(Exception):
                conn.close()
            return _idempotency_error_response(
                error="idempotency_cache_unavailable",
                detail="retry later",
                status_code=503,
                retry_after="1",
            )

        if cache_state == "pending":
            if not _cached_replay_auth_still_valid(conn, request):
                with contextlib.suppress(Exception):
                    conn.close()
                return _auth_failed_response()
            deadline = time.monotonic() + _PENDING_WAIT_SECONDS
            cached_blob = None
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                try:
                    cached_blob = _read_cached(conn, cache_key)
                except Exception:  # pragma: no cover — defensive
                    logger.exception("idempotency_pending_read_failed")
                    cached_blob = None
                if cached_blob is not None:
                    break

            if cached_blob is not None:
                try:
                    status_code, hdrs, body_bytes = _deserialise_response(
                        cached_blob
                    )
                except Exception:  # pragma: no cover — defensive
                    logger.exception("idempotency_pending_deserialise_failed")
                    with contextlib.suppress(Exception):
                        conn.close()
                    return _idempotency_error_response(
                        error="idempotency_cache_unavailable",
                        detail="retry later",
                        status_code=503,
                        retry_after="1",
                    )
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

            with contextlib.suppress(Exception):
                conn.close()
            return Response(
                content=json.dumps(
                    {"error": "idempotency_request_in_progress"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                status_code=409,
                media_type="application/json",
                headers={"X-Metered": "false", "X-Cost-Yen": "0"},
            )

        # Cache miss — run the handler, then capture and cache the response.
        from jpintel_mcp.api.idempotency_context import (
            billing_event_index,
            billing_idempotency_key,
        )

        billing_key_token = billing_idempotency_key.set(billing_key)
        billing_index_token = billing_event_index.set(0)
        try:
            response = await call_next(request)
        except Exception:
            with contextlib.suppress(Exception):
                _delete_cached(conn, cache_key)
            with contextlib.suppress(Exception):
                conn.close()
            raise
        finally:
            billing_event_index.reset(billing_index_token)
            billing_idempotency_key.reset(billing_key_token)

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
                    dict(response.headers.items()),
                    resp_body,
                )
                _write_cached(
                    conn, cache_key, blob, ttl_hours=_CACHE_TTL_HOURS
                )
                # Rebuild a Response so downstream gets a usable body.
                new_resp = Response(
                    content=resp_body,
                    status_code=response.status_code,
                    headers=dict(response.headers.items()),
                    media_type=response.media_type,
                )
                response = new_resp
            except Exception:  # pragma: no cover — defensive
                logger.exception("idempotency_capture_failed")
                with contextlib.suppress(Exception):
                    _delete_cached(conn, cache_key)
        else:
            with contextlib.suppress(Exception):
                _delete_cached(conn, cache_key)
        with contextlib.suppress(Exception):
            conn.close()
        return response


__all__ = [
    "IdempotencyMiddleware",
    "_compute_cache_key",
    "_serialise_response",
    "_deserialise_response",
]
