"""LRU + TTL cache for query-embedding vectors.

Frequent queries ("補助金 中小", "税制 R7" etc) re-encode on every request,
which dominates wall time on a warm pipeline (40-60 ms per encode on CPU).
This cache keys by (normalised query + model_name + kind) and returns the
cached 384d float32 numpy vector, TTL 24h, LRU cap 2048.

Design notes
------------
* Thread-safe: underlying dict guarded by a lock. Negligible contention
  since we only hit it from the search path.
* Model-aware: model name is part of the key so stub vs real coexist.
* Cache misses call ``Encoder.encode`` directly; the cache never fabricates.
* Serialisable: .stats() returns {hits, misses, size} so the benchmark can
  report cache behaviour.

Usage::

    cache = QueryEmbeddingCache()
    vec = cache.encode("補助金", encoder)
"""
from __future__ import annotations

import logging
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from .model import Encoder




# --- AUTO: SCHEMA_GUARD_BLOCK (Wave 10 infra hardening) ---
import sys as _sg_sys
from pathlib import Path as _sg_Path
_sg_sys.path.insert(0, str(_sg_Path(__file__).resolve().parent.parent))
try:
    from scripts.schema_guard import assert_am_entities_schema as _sg_check
except Exception:  # pragma: no cover - schema_guard must exist in prod
    _sg_check = None
if __name__ == "__main__" and _sg_check is not None:
    _sg_check("/tmp/autonomath_infra_2026-04-24/autonomath.db")
# --- END SCHEMA_GUARD_BLOCK ---

log = logging.getLogger(__name__)


DEFAULT_TTL_SECONDS = 24 * 3600      # 24 hours
DEFAULT_MAX_ENTRIES = 2048


def _normalise_key(query: str) -> str:
    """Key normaliser: NFKC + lowercase + strip.

    Not exact — two queries that differ only by full/half width punctuation
    or trailing whitespace should share a cache entry. Semantic rewrites
    (synonym expansion, slot extraction) apply AFTER cache lookup so they
    don't affect keying here.
    """
    if not query:
        return ""
    return unicodedata.normalize("NFKC", query).strip().lower()


@dataclass
class _Entry:
    vector: np.ndarray
    inserted_at: float
    model_name: str
    kind: str


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    expiries: int = 0
    evictions: int = 0
    size: int = 0

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class QueryEmbeddingCache:
    """LRU + TTL cache keyed by (normalised_query, model_name, kind).

    ``encode`` transparently caches; ``encode_raw`` forces a cache miss.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: "OrderedDict[tuple, _Entry]" = OrderedDict()
        self._lock = threading.Lock()
        self._stats = CacheStats()

    # ------------------------------------------------------------------
    def _key(self, query: str, *, model_name: str, kind: str) -> tuple:
        return (_normalise_key(query), model_name, kind)

    def _fresh(self, entry: _Entry) -> bool:
        return (time.time() - entry.inserted_at) < self.ttl_seconds

    def _evict_if_needed(self) -> None:
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)  # LRU: drop oldest
            self._stats.evictions += 1

    # ------------------------------------------------------------------
    def encode(
        self,
        query: str,
        encoder: Encoder,
        *,
        kind: str = "query",
    ) -> np.ndarray:
        """Return the encoded vector for ``query``, caching on miss."""
        if not query:
            from .config import EMBED_DIM
            return np.zeros((EMBED_DIM,), dtype=np.float32)
        model_name = encoder.model_name
        key = self._key(query, model_name=model_name, kind=kind)
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and self._fresh(entry):
                self._store.move_to_end(key)  # LRU refresh
                self._stats.hits += 1
                return entry.vector
            if entry is not None:
                # Expired — drop and miss.
                del self._store[key]
                self._stats.expiries += 1
            self._stats.misses += 1
        # Encode outside the lock (expensive).
        result = encoder.encode([query], kind=kind)
        vec = result.vectors[0]
        with self._lock:
            self._store[key] = _Entry(
                vector=vec,
                inserted_at=time.time(),
                model_name=model_name,
                kind=kind,
            )
            self._store.move_to_end(key)
            self._stats.size = len(self._store)
            self._evict_if_needed()
            self._stats.size = len(self._store)
        return vec

    def warm(
        self,
        queries: list,
        encoder: Encoder,
        *,
        kind: str = "query",
    ) -> int:
        """Bulk-warm for a list of queries. Returns count encoded."""
        n = 0
        for q in queries:
            self.encode(q, encoder, kind=kind)
            n += 1
        return n

    def stats(self) -> Dict[str, float]:
        with self._lock:
            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "expiries": self._stats.expiries,
                "evictions": self._stats.evictions,
                "size": self._stats.size,
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hit_rate": self._stats.hit_rate(),
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._stats = CacheStats()


# ---------------------------------------------------------------------------
# Shared default cache — smart_search pulls from here.
# ---------------------------------------------------------------------------
_DEFAULT: Optional[QueryEmbeddingCache] = None


def get_default_cache() -> QueryEmbeddingCache:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = QueryEmbeddingCache()
    return _DEFAULT


# ---------------------------------------------------------------------------
# Pre-warm set: common agri / SME queries observed in gold_200.
# ---------------------------------------------------------------------------
COMMON_QUERIES = (
    "補助金",
    "補助金 中小",
    "補助金 中小企業",
    "税制 R7",
    "税制優遇",
    "融資",
    "助成金",
    "事業承継",
    "設備投資",
    "DX",
    "省エネ",
    "新規就農",
    "施設園芸",
    "畜産",
    "スマート農業",
    "六次産業化",
    "事業再構築",
    "ものづくり補助金",
    "IT導入補助金",
    "持続化補助金",
    "創業",
    "雇用",
    "輸出",
    "海外展開",
    "販路開拓",
)
