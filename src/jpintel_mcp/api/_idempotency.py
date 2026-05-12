"""Lightweight Idempotency-Key helper (Wave 43.3.1 — AX Resilience cell 1).

Companion to ``middleware/idempotency.py`` (which is the heavyweight HTTP
middleware backed by ``am_idempotency_cache``). This module is the small,
**dep-free** building block that resilience-layer call sites — MCP tools,
cron jobs, ETL workers, the chaos test bench — can use to deduplicate
retries WITHOUT booting the FastAPI stack or touching SQLite.

Shape mirrors ``_degradation.py`` / ``_failover.py`` / ``_replay_token.py``
landed in Wave 43.3.4..9: pure stdlib, ``__all__`` exports, contextvar /
process-local state, no third-party deps. NO LLM call. Importable from
anywhere under ``src/``.

Contract::

    from jpintel_mcp.api._idempotency import (
        IdempotencyKey, idempotency_store, store_or_replay,
    )

    key = IdempotencyKey.from_request_header(request_headers.get("Idempotency-Key"))
    hit, value = store_or_replay(
        key=key,
        body_fingerprint=fp,
        compute=lambda: expensive_call(),
    )

The default in-memory store is a process-local dict with a 24h TTL, hard
capped at 10,000 entries (LRU eviction) so a runaway client cannot DoS
us. Plug in a different ``IdempotencyStore`` for SQLite / Redis backing.

Header format follows the Stripe / RFC draft "The Idempotency-Key HTTP
Header Field" (draft-ietf-httpapi-idempotency-key-header) — opaque
client-supplied token, max 255 chars, ASCII printable.
"""

from __future__ import annotations

import hashlib
import logging
import re
import string
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 24h TTL per spec, matching the middleware. Override per-call via
# ``store_or_replay(ttl_seconds=...)`` for low-stakes use cases.
DEFAULT_TTL_SECONDS: int = 24 * 3600

# Cap on the in-memory store so a flood of distinct keys cannot OOM the
# process. 10k @ ~256B mean → ~2.5 MB worst case which is fine for Fly's
# 1 GB machine size budget.
DEFAULT_MAX_ENTRIES: int = 10_000

# Header normalisation — clients sometimes send "idempotency_key" or
# "Idempotency-Key"; the resilience helper accepts both spellings.
_HEADER_VARIANTS: tuple[str, ...] = (
    "idempotency-key",
    "idempotency_key",
    "x-idempotency-key",
)

# Allowed character class for a key (printable ASCII minus whitespace).
_KEY_VALID_RE = re.compile(r"^[!-~]+$")

# Max length per draft spec. Anything longer is almost certainly a client
# bug (some SDKs accidentally serialise a JSON body into the header).
_MAX_KEY_LENGTH: int = 255

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyKey:
    """Normalised, validated idempotency key.

    Holds the raw header value plus a short stable hash used for store
    keying. ``raw`` is kept around for logging / debug; downstream code
    should always use ``cache_id`` as the lookup token.
    """

    raw: str
    cache_id: str

    @classmethod
    def from_request_header(cls, value: str | None) -> IdempotencyKey | None:
        """Build from a raw header string. Returns None if absent / invalid."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if len(stripped) > _MAX_KEY_LENGTH:
            logger.warning("idempotency.key_too_long len=%s", len(stripped))
            return None
        if not _KEY_VALID_RE.match(stripped):
            logger.warning("idempotency.key_invalid_chars")
            return None
        cache_id = hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:32]
        return cls(raw=stripped, cache_id=cache_id)

    @classmethod
    def from_headers(cls, headers: dict[str, str] | None) -> IdempotencyKey | None:
        """Convenience: scan a mapping for any known header variant."""
        if not headers:
            return None
        lower = {k.lower(): v for k, v in headers.items()}
        for variant in _HEADER_VARIANTS:
            if variant in lower:
                return cls.from_request_header(lower[variant])
        return None


@dataclass(frozen=True)
class _Entry:
    """Internal store entry: cached value + body fingerprint + expiry."""

    value: Any
    body_fingerprint: str
    stored_at: float
    expires_at: float


# ---------------------------------------------------------------------------
# Store protocol + default in-memory backend
# ---------------------------------------------------------------------------


class IdempotencyStore(Protocol):
    """Minimal storage contract — backed by dict / SQLite / Redis."""

    def get(self, cache_id: str) -> _Entry | None: ...

    def set(self, cache_id: str, entry: _Entry) -> None: ...

    def evict_expired(self) -> int: ...

    def __len__(self) -> int: ...


class _InMemoryStore:
    """Process-local OrderedDict with LRU eviction + TTL.

    Thread-safe via a single lock. Latency-cheap (<1 µs per op at 10k
    entries) — fast enough that we don't bother with a lock-free design.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._data: OrderedDict[str, _Entry] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def get(self, cache_id: str) -> _Entry | None:
        with self._lock:
            entry = self._data.get(cache_id)
            if entry is None:
                return None
            if entry.expires_at <= time.time():
                self._data.pop(cache_id, None)
                return None
            # LRU touch — move to end so it's the last to be evicted.
            self._data.move_to_end(cache_id)
            return entry

    def set(self, cache_id: str, entry: _Entry) -> None:
        with self._lock:
            self._data[cache_id] = entry
            self._data.move_to_end(cache_id)
            # Evict oldest entries past the cap.
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def evict_expired(self) -> int:
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._data.items() if v.expires_at <= now]
            for k in stale:
                self._data.pop(k, None)
            return len(stale)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


_DEFAULT_STORE: _InMemoryStore = _InMemoryStore()


def idempotency_store() -> IdempotencyStore:
    """Return the process-wide default store (singleton)."""
    return _DEFAULT_STORE


# ---------------------------------------------------------------------------
# Public API — the verb call sites actually use
# ---------------------------------------------------------------------------


def body_fingerprint(body: bytes | str | dict[str, Any] | None) -> str:
    """Stable sha256 hex of the body — used to detect key-reuse collisions.

    Accepts bytes / str / dict / None. Dict is JSON-serialised with sorted
    keys so two semantically-equal dicts hash identically.
    """
    import json

    if body is None:
        return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    if isinstance(body, bytes):
        raw = body
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class StoreResult:
    """Outcome of ``store_or_replay``.

    * ``hit=True`` → ``value`` is the cached result, ``compute`` was NOT
      called.
    * ``hit=False`` → ``value`` is the freshly-computed result, store was
      updated.
    * ``conflict=True`` → same key seen previously with a DIFFERENT body
      fingerprint. ``value`` is the previously-stored payload (caller
      typically wants to return a 409 here, not the cached result).
    """

    hit: bool
    value: Any
    conflict: bool = False
    stored_at: float = 0.0
    expires_at: float = 0.0


def store_or_replay(
    key: IdempotencyKey,
    body_fingerprint_value: str,
    compute: Callable[[], T],
    *,
    store: IdempotencyStore | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> StoreResult:
    """Replay-or-compute primitive.

    1. Look up ``key.cache_id`` in the store.
    2. Hit + matching fingerprint → return cached value (``hit=True``).
    3. Hit + DIFFERENT fingerprint → return ``conflict=True`` with the
       prior value (caller decides what to do — usually 409).
    4. Miss → call ``compute()``, store the result, return ``hit=False``.

    Exceptions from ``compute()`` are NOT cached — a transient error
    should not lock the client out for 24 hours.
    """
    # ``is None`` check, not truthy fallback — ``_InMemoryStore`` defines
    # ``__len__`` so an empty store would otherwise be falsy and silently
    # route to ``_DEFAULT_STORE`` (classic Python gotcha).
    backend = _DEFAULT_STORE if store is None else store
    entry = backend.get(key.cache_id)
    if entry is not None:
        if entry.body_fingerprint != body_fingerprint_value:
            logger.warning(
                "idempotency.collision cache_id=%s prev_fp=%s new_fp=%s",
                key.cache_id,
                entry.body_fingerprint[:12],
                body_fingerprint_value[:12],
            )
            return StoreResult(
                hit=False,
                value=entry.value,
                conflict=True,
                stored_at=entry.stored_at,
                expires_at=entry.expires_at,
            )
        return StoreResult(
            hit=True,
            value=entry.value,
            stored_at=entry.stored_at,
            expires_at=entry.expires_at,
        )

    now = time.time()
    value = compute()
    new_entry = _Entry(
        value=value,
        body_fingerprint=body_fingerprint_value,
        stored_at=now,
        expires_at=now + ttl_seconds,
    )
    backend.set(key.cache_id, new_entry)
    return StoreResult(
        hit=False,
        value=value,
        stored_at=new_entry.stored_at,
        expires_at=new_entry.expires_at,
    )


def reset_default_store() -> None:
    """Test helper — drop every entry in the process-wide store."""
    _DEFAULT_STORE._data.clear()


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_SECONDS",
    "IdempotencyKey",
    "IdempotencyStore",
    "StoreResult",
    "body_fingerprint",
    "idempotency_store",
    "reset_default_store",
    "store_or_replay",
]


# Silence pyflakes — ``string`` is imported because future extensions
# (key generation helpers) use it; unused imports are flagged by ruff.
_ = string.ascii_letters
