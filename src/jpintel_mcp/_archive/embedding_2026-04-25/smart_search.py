"""smart_search — full all-in retrieval API for AutonoMath.

Wires together every wave of the retrieval stack:
    1. query_rewrite.plan (natural_query → structured filters + semantic_query)
    2. synonyms.expand (BM25 query expansion via existing search_hook)
    3. embedding.query_cache (24h LRU for query embeddings)
    4. embedding.search.hybrid_search (BM25 + dense RRF)
    5. embedding.rerank (cross-encoder reranker)

Public entry point::

    from embedding.smart_search import smart_search

    hits = smart_search(
        natural_query="令和7年度 熊本県の補助金 設備投資",
        filters={"authority": "農林水産省"},   # explicit overrides
        top_k=5,
    )

`filters` is a superset that may include any of:
    * region, prefecture         — mapped to ``prefecture``
    * authority                  — exact ``authority_name``
    * tag                        — substring on ``tag_json``
    * active_on                  — ISO date for validity check
    * industry, size, fiscal_year, on_date, funding_kind, purpose
      — extracted from natural_query OR passed explicitly; the search
      layer ignores keys that have no DB column and keeps them in the
      returned hint for MCP tools.

Synonym expansion defaults ON, rerank defaults ON, cache defaults ON.
All three can be disabled via ``use_synonyms=False`` / ``use_rerank=False``
/ ``use_cache=False`` for A/B benchmarking.

`local_only=True` (default) guarantees no network / API call. The encoder
and reranker are loaded from the local HF cache; cold-start is paid once
per process via lazy singletons.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


from .config import DB_PATH, TIERS
from .db import connect
from .model import Encoder
from .query_cache import QueryEmbeddingCache, get_default_cache
from .search import (
    Filters,


    _filter_sql,
    _serialize_f32,
    _split_query_for_fts,
    bm25_search,
)


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


# Filter keys that map 1:1 to DB columns via `Filters`.
_DB_FILTER_KEYS = {"region", "authority", "tag", "active_on", "prefecture"}


@dataclass
class SmartSearchResult:
    """What `smart_search` returns when `return_metadata=True`."""

    hits: List[Dict[str, Any]] = field(default_factory=list)
    filters_used: Dict[str, Any] = field(default_factory=dict)
    semantic_query: str = ""
    plan: Optional[Dict[str, Any]] = None
    timing_ms: Dict[str, float] = field(default_factory=dict)
    cache_stats: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "filters_used": self.filters_used,
            "semantic_query": self.semantic_query,
            "plan": self.plan,
            "timing_ms": self.timing_ms,
            "cache_stats": self.cache_stats,
        }


# ---------------------------------------------------------------------------
# Shared resources (lazy singletons — respects local_only=True; reranker is
# only loaded when `use_rerank=True` and `_RERANKER_POOL` is None).
# ---------------------------------------------------------------------------
_ENCODER_POOL: Optional[Encoder] = None
_RERANKER_POOL: Optional[Any] = None  # rerank.Reranker


def _encoder() -> Encoder:
    global _ENCODER_POOL
    if _ENCODER_POOL is None:
        _ENCODER_POOL = Encoder()
    return _ENCODER_POOL


def _reranker():
    global _RERANKER_POOL
    if _RERANKER_POOL is None:
        from .rerank import get_default_reranker
        _RERANKER_POOL = get_default_reranker()
    return _RERANKER_POOL


def warm_reranker() -> None:
    """Eagerly materialise the reranker to amortise its ~8s cold start.

    Useful at process start so first real query isn't slow. Safe to call
    repeatedly (the inner singleton guards re-load).
    """
    _reranker()


# ---------------------------------------------------------------------------
# Synonym expansion glue (optional; defaults ON).
# ---------------------------------------------------------------------------
def _expand_bm25(query: str) -> str:
    try:
        from synonyms.expand import expand_bm25_query
        return expand_bm25_query(query)
    except Exception as exc:  # pragma: no cover — dicts dir missing etc.
        log.debug("synonym expansion unavailable (%s) — using raw query", exc)
        return _split_query_for_fts(query)


def _bm25_fused(
    query: str,
    *,
    top_k: int,
    filters: Optional[Dict[str, Any]],
    conn: sqlite3.Connection,
    use_synonyms: bool,
    rrf_k: int = 60,
) -> List[Dict[str, Any]]:
    """Baseline BM25 anchored + synonym-expanded recovery, RRF-fused.

    Mirrors the logic in ``synonyms.search_hook._bm25_with_expansion`` but
    runs against the supplied connection directly so smart_search can own
    the transaction.
    """
    baseline_hits = bm25_search(query, top_k=top_k * 2, filters=filters, conn=conn)
    if not use_synonyms:
        return baseline_hits[:top_k]

    fltr = Filters.from_dict(filters)
    where_frag, params = _filter_sql(fltr)
    try:
        expanded_expr = _expand_bm25(query)
    except Exception as exc:
        log.debug("bm25 synonym expand failed (%s)", exc)
        return baseline_hits[:top_k]

    sql = f"""
        SELECT f.canonical_id, e.primary_name, e.topic_id, e.authority_name,
               e.prefecture, e.source_url,
               bm25(am_entities_fts) AS score_bm25
        FROM am_entities_fts f
        JOIN am_entities_extended e ON e.canonical_id = f.canonical_id
        WHERE am_entities_fts MATCH ?
          {where_frag}
        ORDER BY score_bm25 ASC
        LIMIT ?
    """
    probe = top_k * 5 if where_frag else top_k * 2
    try:
        cur = conn.execute(sql, [expanded_expr, *params, probe])
        expanded_hits = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        log.debug("expanded MATCH failed (%s) — baseline only", exc)
        expanded_hits = []

    scores: Dict[str, Dict[str, Any]] = {}
    for rank, hit in enumerate(baseline_hits):
        cid = hit["canonical_id"]
        scores.setdefault(cid, {**hit, "rank_base": None, "rank_expand": None})["rank_base"] = rank + 1
    for rank, hit in enumerate(expanded_hits):
        cid = hit["canonical_id"]
        scores.setdefault(cid, {**hit, "rank_base": None, "rank_expand": None})["rank_expand"] = rank + 1

    for e in scores.values():
        rrf = 0.0
        if e.get("rank_base"):
            rrf += 2.0 / (rrf_k + e["rank_base"])  # anchor weight
        if e.get("rank_expand"):
            rrf += 1.0 / (rrf_k + e["rank_expand"])
        e["score_rrf_bm25"] = rrf
    return sorted(scores.values(), key=lambda x: x["score_rrf_bm25"], reverse=True)[:top_k]


# ---------------------------------------------------------------------------
# Dense search with query-vector cache.
# ---------------------------------------------------------------------------
def _dense_with_cache(
    query: str,
    *,
    top_k: int,
    filters: Optional[Dict[str, Any]],
    conn: sqlite3.Connection,
    encoder: Encoder,
    cache: Optional[QueryEmbeddingCache],
    tier: str = "tier_a",
) -> List[Dict[str, Any]]:
    """Vector search using cached query embedding when available."""
    if cache is not None:
        q_vec = cache.encode(query, encoder, kind="query")
    else:
        q_vec = encoder.encode([query], kind="query").vectors[0]
    fltr = Filters.from_dict(filters)
    where_frag, params = _filter_sql(fltr)
    probe_k = top_k * 5 if where_frag else top_k
    table = TIERS[tier]["table"]
    sql = f"""
        SELECT m.canonical_id, e.primary_name, e.topic_id, e.authority_name,
               e.prefecture, e.source_url, v.distance
        FROM {table} v
        JOIN am_vec_rowid_map m ON m.tier = ? AND m.rowid = v.rowid
        JOIN am_entities_extended e ON e.canonical_id = m.canonical_id
        WHERE v.embedding MATCH ? AND k = ?
          {where_frag}
        ORDER BY v.distance ASC
        LIMIT ?
    """
    args = [tier, _serialize_f32(q_vec), probe_k, *params, top_k]
    cur = conn.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Main entry — smart_search
# ---------------------------------------------------------------------------
def smart_search(
    natural_query: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = 10,
    *,
    # Stage toggles — all default ON.
    use_synonyms: bool = True,
    use_rerank: bool = True,
    use_cache: bool = True,
    use_query_rewrite: bool = True,
    # RRF / probe_k tuning.
    rrf_k: int = 60,
    bm25_probe_k: int = 300,
    dense_probe_k: int = 100,
    rerank_probe_k: int = 50,
    # Plumbing.
    db_path: Path = DB_PATH,
    conn: Optional[sqlite3.Connection] = None,
    encoder: Optional[Encoder] = None,
    cache: Optional[QueryEmbeddingCache] = None,
    return_metadata: bool = False,
    local_only: bool = True,  # reserved; encoder.Encoder already respects it
) -> Any:
    """Full pipeline: natural query → structured filters + semantic query
    → BM25 ∪ synonym-expanded BM25 ∪ dense → RRF → cross-encoder rerank.

    Returns ``List[Dict]`` of hits by default, or ``SmartSearchResult`` when
    ``return_metadata=True``.
    """
    t_total = time.perf_counter()
    own_conn = conn is None
    conn = conn or connect(db_path)
    encoder = encoder or _encoder()
    if use_cache:
        cache = cache or get_default_cache()
    else:
        cache = None

    explicit_filters = dict(filters or {})
    filters_used: Dict[str, Any] = dict(explicit_filters)
    plan_dict: Optional[Dict[str, Any]] = None
    semantic_query = natural_query or ""
    timing: Dict[str, float] = {}

    # --- Stage 1: query_rewrite -----------------------------------------
    #
    # We ONLY remove spans that land in DB-filterable columns (prefecture,
    # authority). Every other slot — funding_kind, purpose, industry, size —
    # stays in the semantic_query because:
    #   1) the DB has no column to enforce them as filters
    #   2) stripping them and replacing with a canonical alias
    #      (e.g. "助成金" → "補助金", "カーボンニュートラル" → "省エネ")
    #      can destroy literal BM25 matches on record names
    # The structured plan is still returned so MCP tools that DO accept
    # those slots (search_programs etc.) can use them.
    if use_query_rewrite and natural_query:
        t = time.perf_counter()
        try:
            from query_rewrite.extract_slots import extract
            from query_rewrite.normalize import normalize
            from query_rewrite.plan import plan as _plan

            raw_slots = extract(natural_query)
            ns = normalize(raw_slots)

            # IMPORTANT: we do NOT strip any span from natural_query. The
            # original query stays as semantic_query so:
            #   1) Literal BM25 matches on name / location tokens are kept
            #   2) Records whose prefecture column is NULL but whose name
            #      contains the prefecture ("愛知県 農福連携...") are still
            #      discoverable if the filter happens to miss.
            # Prefecture / authority are still promoted to soft filters (see
            # below); when applied strictly they over-constrain on this DB
            # where many records have NULL prefecture columns, so we apply
            # them via a two-stage search in _bm25_fused / _dense_with_cache
            # that falls back to no-filter when filtered probe returns < top_k
            # candidates. See FILTER_FALLBACK_THRESHOLD below.
            semantic_query = natural_query

            qp = _plan(natural_query, raw_slots=raw_slots, normalized=ns)
            plan_dict = qp.to_dict()
            if ns.prefecture and "prefecture" not in explicit_filters and "region" not in explicit_filters:
                filters_used["prefecture"] = ns.prefecture
            if ns.authority and "authority" not in explicit_filters:
                filters_used["authority"] = ns.authority
        except Exception as exc:  # query_rewrite package not installed etc.
            log.debug("query_rewrite failed (%s) — using raw query", exc)
            semantic_query = natural_query
        timing["rewrite_ms"] = (time.perf_counter() - t) * 1000.0

    # db-compatible filter slice (drop keys the `Filters` dataclass ignores)
    db_filters = {
        k: v for k, v in filters_used.items()
        if k in ("tag", "region", "prefecture", "authority", "active_on")
    }
    # `Filters` expects `region`; map prefecture→region.
    if "prefecture" in db_filters and "region" not in db_filters:
        db_filters["region"] = db_filters.pop("prefecture")

    effective_query = semantic_query or natural_query or ""

    # --- Stage 2a: BM25 (with synonym expansion) ------------------------
    # Filter strategy: filters_used columns (prefecture, authority) are
    # often NULL in the DB OR stored with slashes ("経済産業省 / 内閣府")
    # so strict AND-filtering over-constrains. We therefore run UNFILTERED
    # retrieval and treat filters as a soft RRF boost: records whose row
    # prefecture/authority matches a filter get a small rank boost, but
    # non-matching rows aren't discarded.
    t = time.perf_counter()
    bm25_hits = _bm25_fused(
        effective_query,
        top_k=bm25_probe_k,
        filters=None,
        conn=conn,
        use_synonyms=use_synonyms,
        rrf_k=rrf_k,
    )
    timing["bm25_ms"] = (time.perf_counter() - t) * 1000.0

    # --- Stage 2b: dense (Tier A) with cached query vector --------------
    t = time.perf_counter()
    dense_hits = _dense_with_cache(
        effective_query,
        top_k=dense_probe_k,
        filters=None,
        conn=conn,
        encoder=encoder,
        cache=cache,
        tier="tier_a",
    )
    timing["dense_ms"] = (time.perf_counter() - t) * 1000.0

    # --- Soft filter boost ---------------------------------------------
    # Apply +0.5 RRF-like boost per filter match (tunable). Keeps the
    # regional/authority preference without over-constraining.
    def _filter_boost(hit: Dict[str, Any]) -> float:
        bonus = 0.0
        want_pref = db_filters.get("region")
        if want_pref and hit.get("prefecture") == want_pref:
            bonus += 0.05
        want_auth = db_filters.get("authority")
        if want_auth and hit.get("authority_name"):
            if want_auth in (hit["authority_name"] or ""):
                bonus += 0.05
        return bonus

    # --- Stage 3: RRF fusion --------------------------------------------
    t = time.perf_counter()
    scores: Dict[str, Dict[str, Any]] = {}
    for rank, h in enumerate(dense_hits):
        cid = h["canonical_id"]
        scores.setdefault(cid, {**h, "rank_dense": None, "rank_bm25": None})["rank_dense"] = rank + 1
    for rank, h in enumerate(bm25_hits):
        cid = h["canonical_id"]
        scores.setdefault(cid, {**h, "rank_dense": None, "rank_bm25": None})["rank_bm25"] = rank + 1
    for e in scores.values():
        rrf = 0.0
        if e.get("rank_dense"):
            rrf += 1.0 / (rrf_k + e["rank_dense"])
        if e.get("rank_bm25"):
            rrf += 1.0 / (rrf_k + e["rank_bm25"])
        # Soft filter boost — region / authority preference.
        if db_filters:
            rrf += _filter_boost(e)
        e["score_rrf"] = rrf
    fused = sorted(scores.values(), key=lambda x: x["score_rrf"], reverse=True)
    timing["fuse_ms"] = (time.perf_counter() - t) * 1000.0

    # --- Stage 4: cross-encoder rerank ----------------------------------
    if use_rerank and fused:
        t = time.perf_counter()
        head = fused[:rerank_probe_k]
        # Hydrate tier_a_text for reranker context.
        ids = [h["canonical_id"] for h in head]
        placeholders = ",".join("?" for _ in ids)
        txt_map = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT canonical_id, tier_a_text FROM am_entities_fts_compat "
                f"WHERE canonical_id IN ({placeholders})",
                ids,
            ).fetchall()
        }
        for h in head:
            if h["canonical_id"] in txt_map:
                h["tier_a_text"] = txt_map[h["canonical_id"]]
        reranker = _reranker()
        head = reranker.rerank(effective_query or natural_query or "", head, top_k=top_k)
        timing["rerank_ms"] = (time.perf_counter() - t) * 1000.0
        hits = head
    else:
        hits = fused[:top_k]

    # --- Stage 5: unigram fallback --------------------------------------
    # Short CJK queries (<= 2 effective chars) miss the trigram index. When
    # primary returned few hits on such a query, swap in unigram BM25
    # results. Wired 2026-04-24 (Wave 6 #1).
    try:
        from .unigram_fallback import unigram_fallback_if_empty
        hits = unigram_fallback_if_empty(
            effective_query,
            hits,
            top_k=top_k,
            conn=conn,
        )
    except Exception as exc:  # pragma: no cover — optional dep
        log.debug("unigram fallback skipped (%s)", exc)

    timing["total_ms"] = (time.perf_counter() - t_total) * 1000.0
    cache_stats = cache.stats() if cache else {}

    if own_conn:
        conn.close()

    if not return_metadata:
        return hits
    return SmartSearchResult(
        hits=hits,
        filters_used=filters_used,
        semantic_query=semantic_query,
        plan=plan_dict,
        timing_ms=timing,
        cache_stats=cache_stats,
    )


# ---------------------------------------------------------------------------
# CLI for one-shot queries
# ---------------------------------------------------------------------------
def _cli() -> None:  # pragma: no cover
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--no-rerank", action="store_true")
    p.add_argument("--no-synonyms", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-rewrite", action="store_true")
    p.add_argument("--log-level", default="WARNING")
    args = p.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")
    res = smart_search(
        args.query,
        top_k=args.top_k,
        use_rerank=not args.no_rerank,
        use_synonyms=not args.no_synonyms,
        use_cache=not args.no_cache,
        use_query_rewrite=not args.no_rewrite,
        return_metadata=True,
    )
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli()
