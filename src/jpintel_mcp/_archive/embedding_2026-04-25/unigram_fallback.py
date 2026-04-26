"""Unigram FTS5 fallback for smart_search (Wave 6 #1, 2026-04-24).

Rationale:
  * smart_search routes all BM25 traffic through am_entities_fts (trigram).
  * For 1-2 char queries ('認定','農業','DX','税制') trigram finds 0 rows.
  * Wave 5 #5 built am_entities_fts_uni (unigram companion), Wave 6 #1
    populated it. This module wires it into smart_search as a MINIMAL
    fallback so existing behavior is untouched for >=3-char queries.

Integration contract (zero-impact):
  * smart_search.py is NOT modified. Callers opt in by wrapping through
    `smart_search_with_unigram_fallback` OR by manually importing
    `unigram_fallback_if_empty` and calling it on their own result list.
  * Fallback only fires when:
      1. query is <= 2 effective chars (needs_unigram(query) is True), AND
      2. the primary smart_search returned < threshold hits (default 5).
  * When it fires, results are a plain BM25-ordered list from fts_uni;
    we deliberately skip rerank because the reranker expects tier_a_text
    and multi-char phrases, not single-char tokens.

Public API:
    from embedding.unigram_fallback import smart_search_with_unigram_fallback
    hits = smart_search_with_unigram_fallback(query, top_k=10)
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional




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

from jpintel_mcp.mcp.autonomath_tools.unigram_search import (
    needs_unigram,
    unigram_search,
)


FALLBACK_THRESHOLD = 5  # if primary returned fewer than this, try fallback
_REPO_ROOT = Path(__file__).resolve().parents[3]
DB_DEFAULT = Path(os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
))


def unigram_fallback_if_empty(
    query: str,
    primary_hits: List[Dict[str, Any]],
    *,
    top_k: int = 10,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Path = DB_DEFAULT,
    threshold: int = FALLBACK_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Return primary_hits unchanged, OR unigram results, depending on
    (a) whether the query is short enough to need unigram and
    (b) whether primary came back short.

    Never merges — this is a dispatch fallback, not a fusion layer. If you
    need fusion the caller should RRF over the two lists themselves.
    """
    if not query or not needs_unigram(query):
        return primary_hits
    if len(primary_hits) >= threshold:
        return primary_hits
    try:
        hits = unigram_search(
            query,
            top_k=top_k,
            conn=conn,
            db_path=str(db_path),
        )
    except sqlite3.OperationalError as exc:  # fts_uni not yet populated
        log.debug("unigram fallback unavailable (%s) — keeping primary", exc)
        return primary_hits
    log.info("unigram fallback fired: query=%r primary=%d fallback=%d",
             query, len(primary_hits), len(hits))
    return hits


def smart_search_with_unigram_fallback(
    natural_query: str,
    *,
    top_k: int = 10,
    threshold: int = FALLBACK_THRESHOLD,
    db_path: Path = DB_DEFAULT,
    **smart_kwargs: Any,
) -> List[Dict[str, Any]]:
    """Call smart_search; if it returns < threshold hits on a short query,
    replace the result with unigram BM25 hits.

    All **smart_kwargs are forwarded to smart_search (use_rerank etc.).
    """
    from .smart_search import smart_search
    primary = smart_search(natural_query, top_k=top_k, **smart_kwargs)
    # smart_search returns List when return_metadata=False (default).
    if not isinstance(primary, list):
        # metadata mode: pull the hits, patch them back in.
        primary_hits = getattr(primary, "hits", []) or []
        patched = unigram_fallback_if_empty(
            natural_query, primary_hits,
            top_k=top_k, db_path=db_path, threshold=threshold,
        )
        if patched is not primary_hits:
            try:
                primary.hits = patched
            except Exception:  # pragma: no cover -- frozen dataclass etc.
                pass
        return primary  # type: ignore[return-value]
    return unigram_fallback_if_empty(
        natural_query, primary,
        top_k=top_k, db_path=db_path, threshold=threshold,
    )


# Optional: a small helper that smart_search._bm25_fused can call directly.
# Kept separate so we never import embedding.smart_search at module load time.
def bm25_fused_with_unigram(
    effective_query: str,
    baseline_hits: List[Dict[str, Any]],
    *,
    top_k: int,
    conn: sqlite3.Connection,
    threshold: int = FALLBACK_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Drop-in replacement for the tail of `_bm25_fused`:
    returns baseline unless the query is short AND baseline is thin, in which
    case returns unigram BM25 hits (top_k) instead."""
    return unigram_fallback_if_empty(
        effective_query,
        baseline_hits,
        top_k=top_k,
        conn=conn,
        threshold=threshold,
    )
