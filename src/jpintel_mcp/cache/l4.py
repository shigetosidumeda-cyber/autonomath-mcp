"""L4 query-result cache helper (v8 P5-ε++ / 4-Layer cache architecture).

Layer recap (see docs/cache_architecture.md for the long form):
    L0 storage    raw SQLite + FTS5 indexes (bytes on disk)
    L1 atomic     single-row lookups (programs, laws, ...)
    L2 composite  joins across tables (program_law_refs, ...)
    L3 reasoner   multi-tool plans built into pc_* materialized views
    L4 cache      hot serialized response blobs keyed by sha256(tool, params)

L4 sits above L3 and short-circuits identical-param queries at the API
boundary. The Zipf-shaped traffic tail (top ~100 distinct param sets per
tool) accounts for ~80% of all calls in steady state — so a tiny on-disk
cache (≤ 1000 rows) lifts margin from 92% → 95% at the Y1 hit-rate target.

Storage:
    Table: l4_query_cache (migration 043_l4_cache.sql)
    Key:   sha256(tool_name + canonical_json(params)) → 64-char hex
    Value: result_json (UTF-8 string), bumped on hit

Read posture:
    Hit  : row exists AND created_at + ttl_seconds > now-utc → return result_json
    Miss : compute(), INSERT OR REPLACE, return computed value
    Stale: row exists but TTL expired → treated as miss; refresh on access

Write-on-read amplification is intentionally minimised: stale rows are NOT
deleted on read; the nightly `sweep_expired()` call (cron path) prunes them.

Thread / process safety:
    The helper opens its own short-lived sqlite3 connection per call (PRAGMA
    busy_timeout=300000 inherited from db.session.connect()). Concurrent
    writers to the same key end up in INSERT OR REPLACE which is atomic.

Constraints:
    * No Anthropic / claude / SDK calls. Pure SQLite + hashlib + json.
    * Key MUST come from canonical_cache_key(); never hand-roll a sha256
      elsewhere — drift between callers means the cache silently misses.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from jpintel_mcp.db.session import connect

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

_LOG = logging.getLogger("jpintel.cache.l4")

# Default TTL: 24h. Tools that depend on amendment-snapshot freshness can
# pass ttl=3600 (1h) per call. Anything below ~60s is wasted cache pressure.
DEFAULT_TTL_SECONDS = 86400


def canonical_params(params: dict[str, Any]) -> str:
    """Serialize params to a deterministic JSON string.

    `sort_keys=True`, no whitespace, default UTF-8. The output is fed into
    the cache_key sha256 — drift here means the cache silently misses, so
    keep the spec stable.
    """
    return json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_cache_key(tool_name: str, params: dict[str, Any]) -> str:
    """Compute the L4 cache_key for (tool_name, params).

    Returns a 64-char lowercase hex sha256 digest. The single source of truth
    for L4 keys — every caller must round-trip through this helper.
    """
    payload = f"{tool_name}\n{canonical_params(params)}".encode()
    return hashlib.sha256(payload).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _open(db_path: Path | None) -> sqlite3.Connection:
    """Open a connection respecting JPINTEL_DB_PATH / settings.db_path."""
    return connect(db_path)


def get_or_compute(
    cache_key: str,
    tool: str,
    params: dict[str, Any],
    compute: Callable[[], Any],
    ttl: int = DEFAULT_TTL_SECONDS,
    db_path: Path | None = None,
) -> Any:
    """Return the cached result for (tool, params), or compute + store it.

    Args:
        cache_key: result of canonical_cache_key(tool, params). Passed in
            explicitly so callers can pre-compute it for logging.
        tool: MCP tool / API endpoint name (e.g. 'search_tax_incentives').
        params: tool input dict — must round-trip through canonical_params().
        compute: zero-arg callable that produces the result on cache miss.
            Should return a JSON-serialisable value (dict / list / str / ...).
        ttl: per-row TTL in seconds. Default 86400 (24h).
        db_path: override JPINTEL_DB_PATH (mainly for tests).

    Returns:
        The cached or freshly-computed value (always a Python object, NOT
        the raw JSON string — JSON encoding/decoding is internal).
    """
    if ttl <= 0:
        # Pathological caller — bypass cache entirely.
        _LOG.debug("l4_bypass_nonpositive_ttl tool=%s ttl=%d", tool, ttl)
        return compute()

    conn = _open(db_path)
    try:
        row = conn.execute(
            """
            SELECT result_json, created_at, ttl_seconds
            FROM l4_query_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

        if row is not None:
            result_json, created_at, ttl_seconds = row[0], row[1], int(row[2])
            if _is_fresh(created_at, ttl_seconds):
                # Hit: bump LRU + counter, return cached value.
                now = _now_iso()
                conn.execute(
                    """
                    UPDATE l4_query_cache
                       SET hit_count = hit_count + 1,
                           last_hit_at = ?
                     WHERE cache_key = ?
                    """,
                    (now, cache_key),
                )
                _LOG.debug("l4_hit tool=%s key=%s", tool, cache_key[:16])
                return json.loads(result_json)
            # Else: row is stale → fall through to compute + replace.
            _LOG.debug("l4_stale tool=%s key=%s", tool, cache_key[:16])

        # Miss path.
        value = compute()
        try:
            payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
        except TypeError as e:
            # Compute returned something we can't serialize. Surface the
            # error to the caller — caching will silently never warm
            # otherwise.
            _LOG.warning("l4_unserialisable tool=%s err=%s", tool, e)
            return value

        now = _now_iso()
        conn.execute(
            """
            INSERT OR REPLACE INTO l4_query_cache
                (cache_key, tool_name, params_json, result_json,
                 hit_count, last_hit_at, ttl_seconds, created_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                cache_key,
                tool,
                canonical_params(params),
                payload,
                now,
                int(ttl),
                now,
            ),
        )
        _LOG.debug("l4_miss_stored tool=%s key=%s ttl=%d", tool, cache_key[:16], ttl)
        return value
    finally:
        conn.close()


def _is_fresh(created_at_iso: str, ttl_seconds: int) -> bool:
    """Return True iff created_at + ttl_seconds is still in the future."""
    try:
        created = datetime.fromisoformat(created_at_iso)
    except ValueError:
        # Bad row — treat as stale (will be overwritten on next miss).
        return False
    if created.tzinfo is None:
        # Legacy rows from datetime('now') (UTC string without tz). Assume UTC.
        created = created.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - created).total_seconds()
    return age < ttl_seconds


def invalidate(cache_key: str, db_path: Path | None = None) -> int:
    """Delete a single cache row by key. Returns rows deleted (0 or 1)."""
    conn = _open(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM l4_query_cache WHERE cache_key = ?",
            (cache_key,),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


def invalidate_tool(tool_name: str, db_path: Path | None = None) -> int:
    """Delete all rows for a given tool. Used after schema or data changes."""
    conn = _open(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM l4_query_cache WHERE tool_name = ?",
            (tool_name,),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


def sweep_expired(db_path: Path | None = None) -> int:
    """Delete rows whose created_at + ttl_seconds is in the past.

    Idempotent. Called by scripts/cron/precompute_refresh.py nightly so the
    cache table size stays bounded.
    """
    conn = _open(db_path)
    try:
        # SQLite has no scalar `now()` but `julianday('now')` works:
        # age (s) = (julianday('now') - julianday(created_at)) * 86400
        cur = conn.execute(
            """
            DELETE FROM l4_query_cache
             WHERE (julianday('now') - julianday(created_at)) * 86400.0
                   >= ttl_seconds
            """
        )
        deleted = cur.rowcount or 0
        if deleted:
            _LOG.info("l4_sweep_expired deleted=%d", deleted)
        return deleted
    finally:
        conn.close()
