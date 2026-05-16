"""Replay token helper (Wave 43.3.5 — AX Resilience cell 5).

Why this exists
---------------
Customer agents (Claude, ChatGPT, Cursor, etc.) routinely re-issue the
SAME logical request when a tool call timeout / SSE drop / 5xx makes
the original outcome ambiguous. Without a replay token, the customer
either:

  (a) re-bills for the same logical work (¥3 charged twice for what
      the customer perceives as one call), or
  (b) we deduplicate on (api_key_hash, request_hash) — but the
      request_hash is brittle (any kwarg whitespace difference busts
      it) and we cannot tell the customer they were charged once.

A replay token is the explicit contract: the customer mints a token
on first call (`X-Replay-Token: <opaque>`), and any 2nd / 3rd / Nth
call within the 24h TTL with the same token returns the cached
response WITHOUT re-billing.

Design
------
- Token is HMAC-signed with `settings.audit_seal_secret` (already in
  the secret namespace; reusing it keeps the secret count down).
- The "token" itself is the customer-provided opaque string; the
  *cache key* is HMAC(secret, customer_token || api_key_hash). This
  means a customer cannot guess another customer's token (HMAC), and
  the same token used by two different customers is two distinct
  cache rows (suffixed by api_key_hash).
- TTL = 24h. After expiry the cache row is purged by the hourly
  `dlq_drain.py` cleanup sweep (piggy-back).
- Response body is stored as JSON text. Binary responses (CSV export
  etc.) are NOT eligible for replay caching — the helper returns
  None for those and the route falls through to the normal billing
  path.

Storage
-------
A side table `am_replay_cache` (created lazily on first use; this
module owns the CREATE TABLE so it does not need its own migration
file — keeps the cell 5 footprint tiny and lets us evolve the schema
without a destructive ALTER).

Cost note
---------
Token validation is in-process — no Anthropic / external calls.
Cache writes happen inside the response middleware so the route
handler does not wait on the write.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac as _hmac
import json
import logging
import os
import sqlite3  # noqa: TC003 — sqlite3.Error caught at runtime
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("jpintel.replay_token")

# 24h TTL. Customer re-issues within this window get the cached
# response WITHOUT re-billing. Tunable via env var so chaos / soak
# tests can drop it without recompiling.
_DEFAULT_TTL_SECONDS = int(os.environ.get("REPLAY_TOKEN_TTL_SECONDS", str(24 * 3600)))

# Maximum body size we will cache (bytes). Larger responses fall
# through. Conservative bound prevents the cache from blowing through
# SQLite's 1GB row limit + keeps drain sweep cheap.
_MAX_CACHED_BODY_BYTES = int(os.environ.get("REPLAY_TOKEN_MAX_BODY_BYTES", str(256 * 1024)))

# The token itself must be at least this long. Rejects accidental
# empty strings + brute-force friendly short tokens.
_MIN_TOKEN_LEN = 16
# Hard cap so a malicious actor cannot push a 10MB header. Matches
# the X-Replay-Token contract advertised in the OpenAPI spec.
_MAX_TOKEN_LEN = 256

_REPLAY_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS am_replay_cache (
    cache_key       TEXT PRIMARY KEY,                       -- HMAC(secret, token||api_key_hash)
    api_key_hash    TEXT NOT NULL,
    request_path    TEXT NOT NULL,
    request_method  TEXT NOT NULL,
    response_body   TEXT NOT NULL,                          -- JSON
    response_status INTEGER NOT NULL DEFAULT 200,
    response_headers TEXT,                                  -- JSON {header: value}
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at      TEXT NOT NULL,
    hit_count       INTEGER NOT NULL DEFAULT 0
                    CHECK (hit_count >= 0)
);
CREATE INDEX IF NOT EXISTS idx_replay_cache_expires
    ON am_replay_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_replay_cache_api_key_hash
    ON am_replay_cache(api_key_hash);
"""


def _now_iso() -> str:
    """ISO 8601 millisecond UTC stamp matching the SQLite default."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _expires_iso(ttl_seconds: int) -> str:
    """ISO 8601 millisecond expiry stamp `ttl_seconds` from now."""
    when = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _secret() -> bytes:
    """Resolve the HMAC secret. Reuses audit_seal_secret namespace."""
    # Late import to avoid a hard dependency at module load (tests
    # may stub `settings` before importing this module).
    try:
        from jpintel_mcp.config import settings  # noqa: PLC0415

        secret = getattr(settings, "audit_seal_secret", None)
    except (ImportError, AttributeError):
        secret = None
    if not secret:
        secret = os.environ.get("AUDIT_SEAL_SECRET") or os.environ.get("REPLAY_TOKEN_SECRET")
    if not secret:
        # Development-only fallback. In production the secret MUST be
        # set; the absence is logged but does not crash the request
        # path — the cache simply becomes a no-op (returns None).
        logger.warning(
            "replay_token: no AUDIT_SEAL_SECRET / REPLAY_TOKEN_SECRET set; cache is no-op"
        )
        return b""
    return secret.encode("utf-8") if isinstance(secret, str) else secret


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create am_replay_cache + indexes if missing. Idempotent."""
    conn.executescript(_REPLAY_CACHE_DDL)


def validate_token(token: str | None) -> tuple[bool, str | None]:
    """Return (ok, reason_if_invalid). Surface-facing validation only."""
    if token is None:
        return False, "no token"
    if not isinstance(token, str):
        return False, "token not str"
    if len(token) < _MIN_TOKEN_LEN:
        return False, f"token shorter than {_MIN_TOKEN_LEN}"
    if len(token) > _MAX_TOKEN_LEN:
        return False, f"token longer than {_MAX_TOKEN_LEN}"
    # Tokens must be opaque (no whitespace / non-printable). Accept
    # base64 / hex / Crockford / UUID-with-dashes shapes.
    for ch in token:
        if not (ch.isalnum() or ch in "-_.~"):
            return False, "token contains non-opaque char"
    return True, None


def compute_cache_key(token: str, api_key_hash: str) -> str:
    """HMAC(secret, token||api_key_hash). Hex-encoded SHA-256."""
    secret = _secret()
    if not secret:
        # Without a secret we use a non-keyed SHA-256 so the helper
        # remains side-effect-free; this is a degraded mode and the
        # cache should be treated as best-effort.
        msg = f"{token}||{api_key_hash}".encode()
        return hashlib.sha256(msg).hexdigest()
    msg = f"{token}||{api_key_hash}".encode()
    return _hmac.new(secret, msg, hashlib.sha256).hexdigest()


def lookup(
    conn: sqlite3.Connection,
    token: str,
    api_key_hash: str,
    *,
    request_path: str,
    request_method: str,
) -> dict[str, Any] | None:
    """Return the cached response if a valid unexpired entry exists.

    The returned dict carries `body` (parsed JSON), `status`,
    `headers` (dict), and `cached_at`. The caller is responsible for
    converting these into the framework's response type and for
    setting any "X-Replay-Cache-Hit: 1" header. The lookup also
    increments `hit_count` so an operator can later spot tokens being
    abused.

    Returns None if any of:
      - token invalid (length, charset)
      - cache row missing
      - cache row expired
      - cache row's (path, method) does not match the current request
    """
    ok, _reason = validate_token(token)
    if not ok:
        return None
    ensure_schema(conn)
    key = compute_cache_key(token, api_key_hash)
    cur = conn.execute(
        """
        SELECT cache_key, response_body, response_status, response_headers,
               request_path, request_method, expires_at, hit_count
        FROM am_replay_cache
        WHERE cache_key = ?
        """,
        (key,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    # Tuple-or-Row column access (sqlite3.Row supports both indices
    # and names; tests may pass plain tuples).
    if isinstance(row, sqlite3.Row):
        body = row["response_body"]
        status = int(row["response_status"])
        headers_text = row["response_headers"]
        cached_path = row["request_path"]
        cached_method = row["request_method"]
        expires_at = row["expires_at"]
        hit_count = int(row["hit_count"])
    else:
        (_ck, body, status, headers_text, cached_path, cached_method, expires_at, hit_count) = row
        status = int(status)
        hit_count = int(hit_count)

    if expires_at <= _now_iso():
        return None
    if cached_path != request_path or cached_method.upper() != request_method.upper():
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    try:
        headers = json.loads(headers_text) if headers_text else {}
    except json.JSONDecodeError:
        headers = {}
    # Best-effort hit-counter bump. Failures here must not block the
    # response so we swallow them.
    with contextlib.suppress(sqlite3.Error):
        conn.execute(
            "UPDATE am_replay_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (key,),
        )
    return {
        "body": parsed,
        "status": status,
        "headers": headers,
        "hit_count": hit_count + 1,
    }


def store(
    conn: sqlite3.Connection,
    token: str,
    api_key_hash: str,
    *,
    request_path: str,
    request_method: str,
    response_body: dict[str, Any] | list[Any] | str,
    response_status: int = 200,
    response_headers: dict[str, str] | None = None,
    ttl_seconds: int | None = None,
) -> bool:
    """Store a fresh cache entry. Returns True on success.

    Best-effort: any DB error returns False and the response flows
    through unchanged (i.e. the customer is billed normally on the
    next call). Body size > _MAX_CACHED_BODY_BYTES is rejected.
    """
    ok, _reason = validate_token(token)
    if not ok:
        return False
    ensure_schema(conn)
    try:
        body_text = (
            response_body
            if isinstance(response_body, str)
            else json.dumps(response_body, ensure_ascii=False, default=str)
        )
    except (TypeError, ValueError):
        return False
    if len(body_text.encode("utf-8")) > _MAX_CACHED_BODY_BYTES:
        return False
    key = compute_cache_key(token, api_key_hash)
    ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
    headers_text = json.dumps(response_headers, ensure_ascii=False) if response_headers else None
    try:
        conn.execute(
            """
            INSERT INTO am_replay_cache
                (cache_key, api_key_hash, request_path, request_method,
                 response_body, response_status, response_headers,
                 created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(cache_key) DO UPDATE SET
                response_body = excluded.response_body,
                response_status = excluded.response_status,
                response_headers = excluded.response_headers,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at
            """,
            (
                key,
                api_key_hash,
                request_path,
                request_method.upper(),
                body_text,
                int(response_status),
                headers_text,
                _now_iso(),
                _expires_iso(ttl),
            ),
        )
        return True
    except sqlite3.Error as exc:
        logger.warning("replay_token store failed: %s", exc)
        return False


def purge_expired(conn: sqlite3.Connection) -> int:
    """Delete expired cache rows. Returns count purged."""
    ensure_schema(conn)
    cur = conn.execute(
        "DELETE FROM am_replay_cache WHERE expires_at < ?",
        (_now_iso(),),
    )
    return cur.rowcount or 0


# Re-export for `from _replay_token import *` (tests friendly).
__all__ = [
    "compute_cache_key",
    "ensure_schema",
    "lookup",
    "purge_expired",
    "store",
    "validate_token",
]
