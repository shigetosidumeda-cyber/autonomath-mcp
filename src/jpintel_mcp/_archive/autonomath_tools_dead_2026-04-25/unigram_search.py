"""Unigram FTS5 search wrapper (Wave 6 #1, 2026-04-24).

Companion to am_entities_fts (trigram). Used when the user types short 1-2
char CJK tokens that trigram cannot index: '認定','農業','DX','税制', etc.

Routing contract:
  * len(query.strip()) == 1 or 2   -> am_entities_fts_uni (unigram + bigram AND)
  * len(query.strip()) >= 3        -> caller should fall back to trigram
    (keep this file narrow — it is NOT a replacement).

Public surface:
  * unigramize(text)                   -> str
  * needs_unigram(query)               -> bool
  * unigram_search(query, top_k, conn) -> List[dict]
  * should_dispatch_unigram(query)     -> bool  (alias of needs_unigram, kept
    to make smart_search fallback logic readable)

BM25 rerank is handled natively by FTS5 `bm25()` + `ORDER BY ASC`.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_DEFAULT = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))

# --- CJK detection (shared with fts_unigram_apply.py) ----------------------


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3040 <= cp <= 0x30FF
        or 0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0xFF00 <= cp <= 0xFFEF
    )


def unigramize(text: str) -> str:
    """Insert space between every CJK/Kana char; keep ASCII runs intact.

    The invariant: apply the same transform on write (populate) and on
    query (search). Otherwise the FTS5 tokens don't line up.
    """
    if not text:
        return text
    out: list[str] = []
    prev_cjk = False
    for ch in text:
        is_cjk = _is_cjk(ch)
        if is_cjk:
            if out and not out[-1].isspace():
                out.append(" ")
            out.append(ch)
            out.append(" ")
            prev_cjk = True
        else:
            if prev_cjk and not ch.isspace() and out and not out[-1].isspace():
                out.append(" ")
            out.append(ch)
            prev_cjk = False
    return " ".join("".join(out).split())


# --- Dispatch decision -----------------------------------------------------


def _effective_length(query: str) -> int:
    """Number of non-space chars. We count CJK *and* ASCII equally — a
    2-char ASCII token 'DX' is exactly the case we want to route to unigram
    because trigram's n=3 rolling window misses it."""
    return sum(1 for ch in (query or "") if not ch.isspace())


def needs_unigram(query: str) -> bool:
    """True if the query is short enough that trigram misses it.

    Rule: <= 2 effective chars. A 3+ char query should still go via trigram
    (higher precision for multi-char phrases).
    """
    if not query:
        return False
    return _effective_length(query) <= 2


# Alias for readability in smart_search dispatch.
should_dispatch_unigram = needs_unigram


# --- Core search -----------------------------------------------------------


def _match_expr(query: str) -> str:
    """Build a SQL MATCH expression from the raw query.

    For 1-char queries: match a single token ('認 定' -> '認').
    For 2-char queries: AND the two unigram tokens (so both must be present
                        in the row — trivially a bigram constraint).
    For ASCII-only short queries (len <= 2): keep as a single literal token
                        (unicode61 treats 'DX' as one token).
    """
    q = (query or "").strip()
    if not q:
        return q
    uni = unigramize(q)
    # If the unigramized form has multiple whitespace-separated tokens, AND
    # them explicitly so FTS5 keeps the conjunction (otherwise it defaults to
    # implicit AND, which is fine, but being explicit avoids parser quirks).
    parts = [p for p in uni.split() if p]
    if len(parts) <= 1:
        return parts[0] if parts else uni
    # Quote each token so FTS5 doesn't treat it as a column filter etc.
    return " AND ".join(f'"{p}"' for p in parts)


def _open(conn: Optional[sqlite3.Connection], db_path: str) -> tuple[sqlite3.Connection, bool]:
    if conn is not None:
        return conn, False
    c = sqlite3.connect(db_path, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.row_factory = sqlite3.Row
    return c, True


def unigram_search(
    query: str,
    *,
    top_k: int = 20,
    conn: Optional[sqlite3.Connection] = None,
    db_path: str = DB_DEFAULT,
    limit_probe: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search am_entities_fts_uni for `query`.

    Returns top_k hits ordered by BM25 ASC (lower is better). Each hit is
    `{canonical_id, record_kind, primary_name, score_bm25}`. `raw_json`
    is not returned by default — callers can re-hydrate from am_entities.
    """
    expr = _match_expr(query)
    if not expr:
        return []
    c, owned = _open(conn, db_path)
    try:
        probe = limit_probe if limit_probe is not None else top_k
        # Join back to am_entities so primary_name is the clean (non-spaced)
        # form. The fts_uni table stores unigramized text for indexing only.
        sql = (
            "SELECT f.canonical_id, f.record_kind, e.primary_name, "
            "       bm25(am_entities_fts_uni) AS score_bm25 "
            "FROM am_entities_fts_uni f "
            "JOIN am_entities e ON e.canonical_id = f.canonical_id "
            "WHERE am_entities_fts_uni MATCH ? "
            "ORDER BY score_bm25 ASC "
            "LIMIT ?"
        )
        cur = c.execute(sql, (expr, probe))
        rows: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            if isinstance(r, sqlite3.Row):
                rows.append(dict(r))
            else:
                rows.append({
                    "canonical_id": r[0],
                    "record_kind": r[1],
                    "primary_name": r[2],
                    "score_bm25": r[3],
                })
        return rows[:top_k]
    finally:
        if owned:
            c.close()


def unigram_hit_count(
    query: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    db_path: str = DB_DEFAULT,
) -> int:
    """COUNT(*) only — faster than pulling rows, used by benchmarks."""
    expr = _match_expr(query)
    if not expr:
        return 0
    c, owned = _open(conn, db_path)
    try:
        cur = c.execute(
            "SELECT COUNT(*) FROM am_entities_fts_uni WHERE am_entities_fts_uni MATCH ?",
            (expr,),
        )
        return int(cur.fetchone()[0])
    finally:
        if owned:
            c.close()


# --- CLI -------------------------------------------------------------------


def _cli() -> None:  # pragma: no cover
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--db", default=DB_DEFAULT)
    args = ap.parse_args()

    if args.count_only:
        print(unigram_hit_count(args.query, db_path=args.db))
        return
    hits = unigram_search(args.query, top_k=args.top_k, db_path=args.db)
    print(json.dumps(
        {
            "query": args.query,
            "needs_unigram": needs_unigram(args.query),
            "match_expr": _match_expr(args.query),
            "hits": hits,
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    ))


if __name__ == "__main__":
    _cli()
