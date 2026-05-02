"""AutonoMath search API: vector, BM25, hybrid (RRF fusion).

All search functions return a list of dicts::

    {
        "canonical_id": "...",
        "primary_name": "...",
        "topic_id": "...",
        "authority_name": "...",
        "prefecture": "...",
        "source_url": "...",
        "distance": 0.12,      # vector distance (lower=closer)
        "score_bm25": -2.1,    # fts5 rank (lower=better)
        "score_rrf": 0.034,    # only in hybrid
    }

Filters supported: tag (list), region (str/list), authority (str/list),
active_on (ISO date).
"""
from __future__ import annotations

import logging
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import DB_PATH, TIERS
from .db import connect
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


# ---------------------------------------------------------------------------
@dataclass
class Filters:
    tag: Optional[List[str]] = None
    region: Optional[List[str]] = None
    authority: Optional[List[str]] = None
    active_on: Optional[str] = None  # ISO date

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "Filters":
        if not d:
            return cls()
        norm = {}
        for k, v in d.items():
            if v is None:
                continue
            if isinstance(v, str):
                norm[k] = [v]
            elif isinstance(v, (list, tuple)):
                norm[k] = list(v)
            else:
                norm[k] = v
        return cls(**{k: norm.get(k) for k in ("tag", "region", "authority", "active_on")})


def _filter_sql(filters: Filters) -> tuple[str, list]:
    """Return (WHERE fragment, params) — joins against am_entities.

    Fragment is always prefixed with "AND" or empty if no filters.
    """
    frags: list[str] = []
    params: list = []

    if filters.region:
        placeholders = ",".join("?" for _ in filters.region)
        frags.append(f"e.prefecture IN ({placeholders})")
        params.extend(filters.region)

    if filters.authority:
        placeholders = ",".join("?" for _ in filters.authority)
        frags.append(f"e.authority_name IN ({placeholders})")
        params.extend(filters.authority)

    if filters.tag:
        # tag_json is a JSON array; use LIKE for portability (no json_each loop).
        for t in filters.tag:
            frags.append("e.tag_json LIKE ?")
            params.append(f'%"{t}"%')

    if filters.active_on:
        frags.append("(e.active_from IS NULL OR e.active_from <= ?)")
        params.append(filters.active_on)
        frags.append("(e.active_to IS NULL OR e.active_to >= ?)")
        params.append(filters.active_on)

    if not frags:
        return "", []
    return "AND " + " AND ".join(frags), params


def _serialize_f32(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype=np.float32).ravel()
    return struct.pack(f"{len(arr)}f", *arr)


# ---------------------------------------------------------------------------
# Vector search (Tier A/B)
# ---------------------------------------------------------------------------
def vector_search(
    query: str,
    *,
    tier: str = "A",
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
    encoder: Optional[Encoder] = None,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Dense vector search.

    `tier` accepts either the short name ('A', 'B:eligibility', 'B:exclusions',
    'B:dealbreakers', 'B:obligations') or the full key ('tier_a',
    'tier_b_eligibility', ...).
    """
    tier_key = _resolve_tier(tier)
    own_conn = conn is None
    conn = conn or connect(db_path)
    encoder = encoder or Encoder()
    try:
        q_vec = encoder.encode([query], kind="query").vectors[0]
        table = TIERS[tier_key]["table"]

        fltr = Filters.from_dict(filters)
        where_frag, params = _filter_sql(fltr)

        # Use an over-fetch factor so that post-filter still leaves top_k.
        probe_k = top_k * 5 if where_frag else top_k
        sql = f"""
            SELECT
                m.canonical_id  AS canonical_id,
                e.primary_name  AS primary_name,
                e.topic_id      AS topic_id,
                e.authority_name AS authority_name,
                e.prefecture    AS prefecture,
                e.source_url    AS source_url,
                v.distance      AS distance
            FROM {table} v
            JOIN am_vec_rowid_map m
              ON m.tier = ? AND m.rowid = v.rowid
            JOIN am_entities_extended e
              ON e.canonical_id = m.canonical_id
            WHERE v.embedding MATCH ?
              AND k = ?
              {where_frag}
            ORDER BY v.distance ASC
            LIMIT ?
        """
        args = [tier_key, _serialize_f32(q_vec), probe_k, *params, top_k]
        cur = conn.execute(sql, args)
        return [dict(row) for row in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()


def _resolve_tier(tier: str) -> str:
    t = tier.strip()
    if t in TIERS:
        return t
    # short form
    if t.upper() == "A":
        return "tier_a"
    if t.upper().startswith("B:"):
        facet = t.split(":", 1)[1].lower()
        key = f"tier_b_{facet}"
        if key in TIERS:
            return key
    raise ValueError(f"unknown tier: {tier}")


# ---------------------------------------------------------------------------
# BM25 search
# ---------------------------------------------------------------------------
# Japanese particles / common stop characters that split conceptual chunks.
_JP_SPLITTERS = "のをがはでとにへやもから、。・「」 　\t\n"


def _split_query_for_fts(query: str) -> str:
    """Split a Japanese query on particles to improve trigram MATCH recall.

    "ものづくり補助金の採択率" → '("ものづくり補助金" OR "採択率")'
    """
    out: List[str] = []
    buf: List[str] = []
    for ch in query:
        if ch in _JP_SPLITTERS:
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    # trigram tokenizer needs >= 3 chars per token; drop shorter ones.
    tokens = [f'"{t}"' for t in out if len(t) >= 3]
    if not tokens:
        return f'"{query}"'
    return " OR ".join(tokens)


def bm25_search(
    query: str,
    *,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect(db_path)
    try:
        fltr = Filters.from_dict(filters)
        where_frag, params = _filter_sql(fltr)
        probe_k = top_k * 5 if where_frag else top_k
        fts_query = _split_query_for_fts(query)
        sql = f"""
            SELECT
                f.canonical_id  AS canonical_id,
                e.primary_name  AS primary_name,
                e.topic_id      AS topic_id,
                e.authority_name AS authority_name,
                e.prefecture    AS prefecture,
                e.source_url    AS source_url,
                bm25(am_entities_fts) AS score_bm25
            FROM am_entities_fts f
            JOIN am_entities_extended e
              ON e.canonical_id = f.canonical_id
            WHERE am_entities_fts MATCH ?
              {where_frag}
            ORDER BY score_bm25 ASC
            LIMIT ?
        """
        try:
            cur = conn.execute(sql, [fts_query, *params, probe_k])
            return [dict(row) for row in cur.fetchall()][:top_k]
        except sqlite3.OperationalError as exc:
            # fts5 syntax errors on unusual punctuation; fall back to LIKE.
            log.debug("fts5 MATCH failed (%s), falling back to LIKE", exc)
            like_sql = f"""
                SELECT
                    f.canonical_id  AS canonical_id,
                    e.primary_name  AS primary_name,
                    e.topic_id      AS topic_id,
                    e.authority_name AS authority_name,
                    e.prefecture    AS prefecture,
                    e.source_url    AS source_url,
                    0.0 AS score_bm25
                FROM am_entities_fts_compat f
                JOIN am_entities_extended e
                  ON e.canonical_id = f.canonical_id
                WHERE f.tier_a_text LIKE ?
                  {where_frag}
                LIMIT ?
            """
            like_q = f"%{query}%"
            cur = conn.execute(like_sql, [like_q, *params, top_k])
            return [dict(row) for row in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()


# ---------------------------------------------------------------------------
# Hybrid search (RRF fusion)
# ---------------------------------------------------------------------------
def hybrid_search(
    query: str,
    *,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = 10,
    rrf_k: int = 60,
    probe_k: int = 50,
    conn: Optional[sqlite3.Connection] = None,
    encoder: Optional[Encoder] = None,
    db_path: Path = DB_PATH,
    use_rerank: bool = False,
    reranker: Optional[Any] = None,
    bm25_probe_k: int = 300,
    dense_probe_k: int = 100,
    rerank_probe_k: int = 50,
) -> List[Dict[str, Any]]:
    """BM25 + dense Tier A with Reciprocal Rank Fusion (k=60).

    When ``use_rerank=True`` runs the full 3-stage cascade:
        BM25 top ``bm25_probe_k`` (default 300)
        dense top ``dense_probe_k`` (default 100)
        RRF fuse → top ``rerank_probe_k`` (default 50)
        cross-encoder rerank → top ``top_k`` (default 10; caller usually 5)

    Without rerank the legacy behaviour is preserved and ``probe_k`` is used
    for both BM25 and dense fan-out so existing callers are unaffected.
    """
    own_conn = conn is None
    conn = conn or connect(db_path)
    encoder = encoder or Encoder()
    try:
        if use_rerank:
            dense_k = dense_probe_k
            bm25_k = bm25_probe_k
            fuse_k = rerank_probe_k
        else:
            dense_k = probe_k
            bm25_k = probe_k
            fuse_k = None  # return top_k directly

        dense = vector_search(
            query,
            tier="A",
            top_k=dense_k,
            filters=filters,
            conn=conn,
            encoder=encoder,
        )
        lexical = bm25_search(
            query,
            top_k=bm25_k,
            filters=filters,
            conn=conn,
        )

        scores: Dict[str, Dict[str, Any]] = {}
        for rank, hit in enumerate(dense):
            cid = hit["canonical_id"]
            entry = scores.setdefault(cid, {**hit, "rank_dense": None, "rank_bm25": None})
            entry["rank_dense"] = rank + 1
            entry["distance"] = hit.get("distance")

        for rank, hit in enumerate(lexical):
            cid = hit["canonical_id"]
            entry = scores.setdefault(cid, {**hit, "rank_dense": None, "rank_bm25": None})
            entry["rank_bm25"] = rank + 1
            entry["score_bm25"] = hit.get("score_bm25")

        # RRF fusion
        for cid, entry in scores.items():
            rrf = 0.0
            if entry.get("rank_dense"):
                rrf += 1.0 / (rrf_k + entry["rank_dense"])
            if entry.get("rank_bm25"):
                rrf += 1.0 / (rrf_k + entry["rank_bm25"])
            entry["score_rrf"] = rrf

        fused = sorted(scores.values(), key=lambda x: x["score_rrf"], reverse=True)

        if not use_rerank:
            return fused[:top_k]

        # Stage 3 — cross-encoder rerank on top `fuse_k` RRF survivors.
        head = fused[:fuse_k]
        # Fetch tier_a_text for the head so the cross-encoder sees the
        # source_excerpt, not just primary_name.  One batched query.
        if head:
            ids = [h["canonical_id"] for h in head]
            placeholders = ",".join("?" for _ in ids)
            txt_sql = (
                f"SELECT canonical_id, tier_a_text FROM am_entities_fts_compat "
                f"WHERE canonical_id IN ({placeholders})"
            )
            texts = {r[0]: r[1] for r in conn.execute(txt_sql, ids).fetchall()}
            for h in head:
                t = texts.get(h["canonical_id"])
                if t:
                    h["tier_a_text"] = t
        if reranker is None:
            from .rerank import get_default_reranker
            reranker = get_default_reranker()
        return reranker.rerank(query, head, top_k=top_k)
    finally:
        if own_conn:
            conn.close()
