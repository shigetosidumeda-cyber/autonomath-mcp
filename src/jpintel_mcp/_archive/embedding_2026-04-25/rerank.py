"""Stage 3 cross-encoder reranker for the AutonoMath hybrid search cascade.

Cascade:
    Stage 1: BM25 (FTS5) top 300 + dense (sqlite-vec) top 100 — parallel
    Stage 2: RRF fusion → top 50
    Stage 3: cross-encoder rerank → top 5   <-- THIS MODULE

Model choice (constrained by 500 MB cap per task spec):
    PRIMARY  = hotchpotch/japanese-reranker-cross-encoder-xsmall-v1  (428 MB)
    FALLBACK = cross-encoder/mmarco-mMiniLMv2-L12-H384-v1            (470 MB)

`cl-nagoya/ruri-reranker-small` (spec default) is ~700 MB safetensors so it
does not fit the cap; `ruri-reranker-large` is ~1.3 GB. The hotchpotch xsmall
is a Japanese-specialized cross-encoder trained on JSNLI / MS-MARCO-ja and
fits the budget with room to spare.

The reranker takes the RRF-fused top 50 candidates from `hybrid_search` and
returns them re-ordered by cross-encoder relevance score, keeping only top_k.
Input rows keep all original columns and gain a new `score_rerank` (logit).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence




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


# Candidate models in priority order.  First one that loads is used.
PRIMARY_MODEL = "hotchpotch/japanese-reranker-cross-encoder-xsmall-v1"
FALLBACK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
STUB_MODEL = "stub-identity-rerank"


def _rerank_text(candidate: Dict[str, Any]) -> str:
    """Build the document side of the (query, doc) pair.

    We concatenate the most informative surface fields available on the row.
    `hybrid_search` returns primary_name + authority_name + prefecture — those
    alone are short (often <60 chars).  If the caller attached a longer excerpt
    under `source_excerpt` / `tier_a_text` we prefer that.
    """
    for key in ("source_excerpt", "tier_a_text", "snippet"):
        v = candidate.get(key)
        if isinstance(v, str) and v.strip():
            return v[:1024]
    parts = [
        candidate.get("primary_name") or "",
        candidate.get("authority_name") or "",
        candidate.get("prefecture") or "",
        candidate.get("topic_id") or "",
    ]
    return " | ".join(p for p in parts if p).strip() or "(no text)"


@dataclass
class RerankStats:
    model_name: str
    is_stub: bool
    load_ms: float
    load_mem_mb: Optional[float]  # RSS delta in MB (None if psutil unavailable)
    last_batch_size: int = 0
    last_latency_ms: float = 0.0
    cumulative_calls: int = 0
    cumulative_pairs: int = 0


class Reranker:
    """Cross-encoder reranker with lazy loading and graceful stub fallback.

    Usage::

        r = Reranker()
        top5 = r.rerank(query, candidates, top_k=5)

    `candidates` is the list returned by `hybrid_search(probe_k=50)`.  Each
    returned row is the same dict with an added `score_rerank` float.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        *,
        device: str = "cpu",
        max_length: int = 512,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self._ce = None              # sentence_transformers.CrossEncoder handle
        self.is_stub = False
        self.stats = self._load()

    # ------------------------------------------------------------------
    def _rss_mb(self) -> Optional[float]:
        try:
            import resource
            # macOS returns bytes, Linux returns KB.  Scale accordingly.
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            import sys as _sys
            return rss / (1024 * 1024) if _sys.platform == "darwin" else rss / 1024
        except Exception:
            return None

    def _try_load(self, name: str):
        from sentence_transformers import CrossEncoder
        log.info("loading cross-encoder model=%s device=%s", name, self.device)
        return CrossEncoder(name, device=self.device, max_length=self.max_length)

    def _load(self) -> RerankStats:
        rss_before = self._rss_mb()
        t0 = time.perf_counter()
        tried: List[str] = []
        order: List[str]
        if self.model_name:
            order = [self.model_name, FALLBACK_MODEL]
        else:
            order = [PRIMARY_MODEL, FALLBACK_MODEL]
        # Deduplicate while preserving order.
        seen = set()
        order = [n for n in order if not (n in seen or seen.add(n))]

        for name in order:
            try:
                self._ce = self._try_load(name)
                self.model_name = name
                self.is_stub = False
                break
            except Exception as exc:
                tried.append(f"{name}: {type(exc).__name__}: {exc}")
                log.warning("reranker load failed: %s", tried[-1])

        if self._ce is None:
            log.warning(
                "all reranker candidates failed; using identity-stub. tried=%s",
                tried,
            )
            self._ce = None
            self.is_stub = True
            self.model_name = STUB_MODEL

        load_ms = (time.perf_counter() - t0) * 1000.0
        rss_after = self._rss_mb()
        delta = (
            (rss_after - rss_before)
            if (rss_before is not None and rss_after is not None)
            else None
        )
        return RerankStats(
            model_name=self.model_name,
            is_stub=self.is_stub,
            load_ms=load_ms,
            load_mem_mb=delta,
        )

    # ------------------------------------------------------------------
    def rerank(
        self,
        query: str,
        candidates: Sequence[Dict[str, Any]],
        *,
        top_k: int = 5,
        batch_size: int = 16,
    ) -> List[Dict[str, Any]]:
        """Score (query, candidate_text) pairs and return top_k in score order.

        Each candidate dict is returned with an extra ``score_rerank`` key.
        When the stub is active, ``score_rerank`` mirrors any existing
        ``score_rrf`` (or 0.0) so the input ordering is preserved.
        """
        if not candidates:
            return []
        t0 = time.perf_counter()
        texts = [_rerank_text(c) for c in candidates]
        if self.is_stub:
            scored = []
            for c in candidates:
                c2 = dict(c)
                c2["score_rerank"] = float(c.get("score_rrf") or 0.0)
                scored.append(c2)
            scored.sort(key=lambda x: x["score_rerank"], reverse=True)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            self._update_stats(len(candidates), latency_ms)
            return scored[:top_k]

        pairs = [(query, t) for t in texts]
        scores = self._ce.predict(
            pairs,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        scored = []
        for c, s in zip(candidates, scores):
            c2 = dict(c)
            c2["score_rerank"] = float(s)
            scored.append(c2)
        scored.sort(key=lambda x: x["score_rerank"], reverse=True)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._update_stats(len(candidates), latency_ms)
        return scored[:top_k]

    def _update_stats(self, batch_size: int, latency_ms: float) -> None:
        self.stats.last_batch_size = batch_size
        self.stats.last_latency_ms = latency_ms
        self.stats.cumulative_calls += 1
        self.stats.cumulative_pairs += batch_size


# ---------------------------------------------------------------------------
# Module-level convenience cache
# ---------------------------------------------------------------------------
_DEFAULT: Optional[Reranker] = None


def get_default_reranker() -> Reranker:
    """Return a lazily-instantiated shared Reranker.  Thread-safe-ish: tests
    that need an isolated instance should construct Reranker() directly."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Reranker()
    return _DEFAULT
