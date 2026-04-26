"""Wave 14 Agent #5 — Hot query caching layer.

Two-layer cache for repeatable read-only MCP tool queries.

Design
------
L1: in-process LRU (OrderedDict under RLock), default cap 100, TTL 60 s.
L2: SQLite in-memory temp table (``:memory:``), cap 1000, TTL 3600 s.

Key
---
Every key is::

    sha256(tool || "\0" || json.dumps(params, sort_keys, default=str)
           || "\0" || db_fingerprint)

Where ``db_fingerprint`` is derived from ``PRAGMA schema_version`` on the
primary DB. schema_version only bumps on DDL so WAL-write churn from the
ingest worker does NOT invalidate the cache.

Invalidation
------------
1. Schema bump — automatic (key diverges).
2. Explicit — ``invalidate_all()`` called by the ingest worker when it
   finishes a batch. Bumps an in-process counter mixed into the fingerprint.
3. TTL — epoch check on every probe.

Usage
-----
Tool-level decorators::

    from cache import cached, invalidate_all

    @cached(ttl=86400, layer='l1')
    def enum_values(name: str) -> list[str]: ...

    @cached(ttl=3600, layer='l2')
    def search_tax_rules(scope: str) -> list[dict]: ...

Prometheus
----------
Hits/misses route through ``_record_cache_event`` which mutates two
defaultdict counters attached to the Wave 13 ``_REGISTRY`` instance.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
_L1_MAX = int(os.environ.get("AUTONOMATH_CACHE_L1_MAX", "100"))
_L2_MAX = int(os.environ.get("AUTONOMATH_CACHE_L2_MAX", "1000"))
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DB = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
)

# -----------------------------------------------------------------------------
# Fingerprint  (schema_version + explicit bump counter)
# -----------------------------------------------------------------------------
_fingerprint_lock = threading.Lock()
_fingerprint_bump = 0  # bumped by invalidate_all()
_fingerprint_cache: Dict[str, Tuple[float, str]] = {}
_FINGERPRINT_TTL_S = 2.0  # re-read PRAGMA at most every 2 s


def _db_schema_version(db_path: str) -> int:
    # cheap read-only probe
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        return int(c.execute("PRAGMA schema_version").fetchone()[0])
    finally:
        c.close()


def db_fingerprint(db_path: Optional[str] = None) -> str:
    """Return a short string fingerprint of the DB state.

    Combines PRAGMA schema_version (DDL-only bump) and the process-local
    invalidation counter so that both automatic DDL and explicit
    ``invalidate_all()`` calls produce a fresh fingerprint.
    """
    path = db_path or _DEFAULT_DB
    now = time.time()
    with _fingerprint_lock:
        cached = _fingerprint_cache.get(path)
        if cached and (now - cached[0]) < _FINGERPRINT_TTL_S:
            schema_v = cached[1]
        else:
            try:
                schema_v = str(_db_schema_version(path))
            except Exception:
                schema_v = "err"
            _fingerprint_cache[path] = (now, schema_v)
        return f"{schema_v}:{_fingerprint_bump}"


def invalidate_all() -> None:
    """Bump the fingerprint counter. Next lookups will see fresh keys and
    old entries age out via TTL / LRU eviction."""
    global _fingerprint_bump
    with _fingerprint_lock:
        _fingerprint_bump += 1
        _fingerprint_cache.clear()
    with _l1_lock:
        _l1.clear()
    _l2_clear()


# -----------------------------------------------------------------------------
# Prometheus hook  (monkey-patch on Wave 13 registry if present)
# -----------------------------------------------------------------------------
_cache_hits: Dict[Tuple[str, str], int] = defaultdict(int)
_cache_misses: Dict[str, int] = defaultdict(int)
_metric_lock = threading.Lock()


def _record_cache_event(tool: str, hit: bool, layer: str = "l1") -> None:
    with _metric_lock:
        if hit:
            _cache_hits[(tool, layer)] += 1
        else:
            _cache_misses[tool] += 1
    # attach to Wave 13 registry if importable
    try:
        from api import prometheus_metrics as _pm  # type: ignore

        reg = _pm.get_registry()
        if not hasattr(reg, "cache_hits_total"):
            reg.cache_hits_total = defaultdict(int)
            reg.cache_misses_total = defaultdict(int)
        with reg.lock:
            if hit:
                reg.cache_hits_total[(tool, layer)] += 1
            else:
                reg.cache_misses_total[tool] += 1
    except Exception:
        # api.prometheus_metrics not importable in some test contexts — ok
        pass


def get_metrics_snapshot() -> Dict[str, Any]:
    """Expose counters for tests / debug."""
    with _metric_lock:
        return {
            "hits": dict(_cache_hits),
            "misses": dict(_cache_misses),
        }


def _reset_metrics() -> None:
    with _metric_lock:
        _cache_hits.clear()
        _cache_misses.clear()


# -----------------------------------------------------------------------------
# Key canonicalisation
# -----------------------------------------------------------------------------
def _canonicalize(tool: str, args: tuple, kwargs: dict, db_fp: str) -> str:
    # turn args / kwargs into a deterministic JSON payload
    payload = {
        "args": list(args),
        "kwargs": kwargs,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    raw = f"{tool}\0{blob}\0{db_fp}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# -----------------------------------------------------------------------------
# L1: in-process LRU
# -----------------------------------------------------------------------------
_l1_lock = threading.RLock()
_l1: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()  # key -> (expires_at, value)


def _l1_get(key: str) -> Tuple[bool, Any]:
    with _l1_lock:
        entry = _l1.get(key)
        if entry is None:
            return False, None
        expires_at, value = entry
        if expires_at < time.time():
            _l1.pop(key, None)
            return False, None
        _l1.move_to_end(key)  # LRU touch
        return True, value


def _l1_put(key: str, value: Any, ttl: float) -> None:
    with _l1_lock:
        _l1[key] = (time.time() + ttl, value)
        _l1.move_to_end(key)
        while len(_l1) > _L1_MAX:
            _l1.popitem(last=False)


# -----------------------------------------------------------------------------
# L2: in-memory SQLite temp store
# -----------------------------------------------------------------------------
_l2_lock = threading.Lock()
_l2_conn: Optional[sqlite3.Connection] = None


def _l2_ensure() -> sqlite3.Connection:
    global _l2_conn
    if _l2_conn is None:
        _l2_conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=2.0)
        _l2_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                expires_at REAL NOT NULL,
                last_access REAL NOT NULL,
                value_json TEXT NOT NULL
            )
            """
        )
        _l2_conn.execute("CREATE INDEX IF NOT EXISTS ix_kv_access ON kv_cache(last_access)")
    return _l2_conn


def _l2_get(key: str) -> Tuple[bool, Any]:
    with _l2_lock:
        c = _l2_ensure()
        row = c.execute(
            "SELECT expires_at, value_json FROM kv_cache WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return False, None
        expires_at, value_json = row
        if expires_at < time.time():
            c.execute("DELETE FROM kv_cache WHERE key=?", (key,))
            return False, None
        c.execute(
            "UPDATE kv_cache SET last_access=? WHERE key=?",
            (time.time(), key),
        )
        return True, json.loads(value_json)


def _l2_put(key: str, value: Any, ttl: float) -> None:
    with _l2_lock:
        c = _l2_ensure()
        now = time.time()
        c.execute(
            "INSERT OR REPLACE INTO kv_cache(key, expires_at, last_access, value_json) "
            "VALUES(?, ?, ?, ?)",
            (key, now + ttl, now, json.dumps(value, default=str, ensure_ascii=False)),
        )
        # evict LRU if over cap
        n = c.execute("SELECT COUNT(*) FROM kv_cache").fetchone()[0]
        if n > _L2_MAX:
            excess = n - _L2_MAX
            c.execute(
                "DELETE FROM kv_cache WHERE key IN ("
                "  SELECT key FROM kv_cache ORDER BY last_access ASC LIMIT ?"
                ")",
                (excess,),
            )


def _l2_clear() -> None:
    with _l2_lock:
        c = _l2_ensure()
        c.execute("DELETE FROM kv_cache")


def _l2_size() -> int:
    with _l2_lock:
        c = _l2_ensure()
        return int(c.execute("SELECT COUNT(*) FROM kv_cache").fetchone()[0])


# -----------------------------------------------------------------------------
# Decorator
# -----------------------------------------------------------------------------
def cached(
    ttl: float = 60.0,
    layer: str = "l1",
    tool: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Callable:
    """Cache decorator.

    ``layer`` = ``'l1'`` (in-process LRU only) or ``'l2'`` (L1 + SQLite L2).
    """
    if layer not in ("l1", "l2"):
        raise ValueError(f"unsupported cache layer: {layer!r}")

    def decorator(fn: Callable) -> Callable:
        name = tool or f"{fn.__module__}.{fn.__name__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            fp = db_fingerprint(db_path)
            key = _canonicalize(name, args, kwargs, fp)

            hit, value = _l1_get(key)
            if hit:
                _record_cache_event(name, True, "l1")
                return value

            if layer == "l2":
                hit, value = _l2_get(key)
                if hit:
                    # promote to L1 for subsequent faster hits
                    _l1_put(key, value, min(ttl, 60.0))
                    _record_cache_event(name, True, "l2")
                    return value

            _record_cache_event(name, False, "miss")
            value = fn(*args, **kwargs)
            _l1_put(key, value, min(ttl, 60.0))
            if layer == "l2":
                _l2_put(key, value, ttl)
            return value

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapper.cache_name = name  # type: ignore[attr-defined]
        return wrapper

    return decorator


# -----------------------------------------------------------------------------
# Debug helpers for tests
# -----------------------------------------------------------------------------
def _l1_size() -> int:
    with _l1_lock:
        return len(_l1)


def _clear_all_for_tests() -> None:
    """Test-only: wipes both layers + metrics without bumping fingerprint."""
    with _l1_lock:
        _l1.clear()
    _l2_clear()
    _reset_metrics()
