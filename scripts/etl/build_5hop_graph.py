"""build_5hop_graph — populate ``am_5hop_graph`` mat-view (Wave 24 §152).

Walks the heterogeneous KG 5 hops deep from a seed entity and writes
``(start_entity_id, hop, end_entity_id, path, edge_kinds)`` rows so the
``traverse_graph_5hop`` MCP tool is O(1) lookup at request time.

Edge sources (by hop position, in priority order):

  hop 1  program -> law           am_relation rel='references_law'
  hop 2  law -> 通達              nta_tsutatsu_index.law_canonical_id ==
                                  hop-1 target  (rel='applies_to_law')
  hop 3  通達 -> 裁決              FTS5 keyword overlap on
                                  nta_tsutatsu_index.title vs
                                  nta_saiketsu_fts.fulltext
                                  (rel='derived_keyword')
  hop 4  裁決 -> 判例 / 裁決'      court_decisions has 0 rows in this
                                  snapshot, so we pivot to
                                  same-tax_type sibling saiketsu via
                                  nta_saiketsu_fts overlap
                                  (rel='derived_keyword')
  hop 5  判例/裁決' -> ...         continue same-tax_type pivot

Per-hop fan-out cap = 5 to keep the row budget bounded
(5^5 = 3,125 max paths per seed, before dedup). Cycle suppression via
``end_entity_id IN visited`` check before INSERT.

Per `feedback_no_operator_llm_api` and `feedback_autonomath_no_api_use`,
this script is pure SQL — NO LLM API calls, NO subagent fan-out.

Usage
-----
    .venv/bin/python scripts/etl/build_5hop_graph.py \\
        --db autonomath.db --tier S --limit 100

Outputs a summary line:

    seeds=N rows_written=R hop_dist={1: ..., 2: ..., ...}

Idempotent: ``INSERT OR IGNORE`` against the
``(start_entity_id, end_entity_id, hop)`` PRIMARY KEY.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("build_5hop_graph")

# Per-hop fan-out cap. 5^5 = 3,125 max raw paths per seed before dedup.
_FANOUT = 5

# Hard ceiling on paths inserted per seed to defend against pathological
# hubs (e.g. 'law:hojokin-nado-ni' → 709 references_law in-edges).
_MAX_PATHS_PER_SEED = 1000

# FTS keyword extraction: take 1-2 longest 2+-char tokens from a title
# string. We avoid building a heavyweight tokenizer here — for the seed
# substrate (法令名 / 通達タイトル) splitting on punctuation + length
# rank works well in practice for derived edges.
_KW_MIN_LEN = 2
_KW_MAX_PICK = 2


def _extract_keywords(text: str | None) -> list[str]:
    """Return up to _KW_MAX_PICK longest 2+-char tokens for FTS MATCH."""
    if not text:
        return []
    # Split on common punctuation + whitespace; keep CJK runs intact.
    seps = "\t\n\r ,.;:()（）「」『』【】[]{}/／\\・|—-–_=+*&^%$#@!?'\""
    tmp = text
    for s in seps:
        tmp = tmp.replace(s, "")
    parts = [p.strip() for p in tmp.split("") if p.strip()]
    parts = [p for p in parts if len(p) >= _KW_MIN_LEN]
    parts.sort(key=len, reverse=True)
    return parts[:_KW_MAX_PICK]


def _fts_match_safe(conn: sqlite3.Connection, table: str, kw: str, limit: int) -> list[int]:
    """Run an FTS5 MATCH that is robust to special-character keywords.

    Wraps the keyword in double quotes so FTS treats it as a phrase.
    Silently returns [] if MATCH raises (FTS5 syntax error from the kw).
    """
    if not kw or len(kw) < _KW_MIN_LEN:
        return []
    safe = '"' + kw.replace('"', '""') + '"'
    try:
        cur = conn.execute(
            f"SELECT rowid FROM {table} WHERE {table} MATCH ? LIMIT ?",
            (safe, limit),
        )
        return [r[0] for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


def _hop1_program_to_law(conn: sqlite3.Connection, seed: str) -> list[dict]:
    """program -> law via am_relation rel='references_law'."""
    cur = conn.execute(
        """
        SELECT target_entity_id, confidence
          FROM am_relation
         WHERE source_entity_id = ?
           AND relation_type   = 'references_law'
           AND target_entity_id IS NOT NULL
         ORDER BY confidence DESC
         LIMIT ?
        """,
        (seed, _FANOUT),
    )
    return [
        {"end": row[0], "edge": "references_law", "conf": row[1] or 0.0} for row in cur.fetchall()
    ]


def _hop2_law_to_tsutatsu(conn: sqlite3.Connection, law_canonical_id: str) -> list[dict]:
    """law -> 通達.

    Strategy 1: literal law_canonical_id match in nta_tsutatsu_index
                (rel='applies_to_law').
    Strategy 2: FTS keyword overlap fallback (rel='derived_keyword').
    """
    out: list[dict] = []
    cur = conn.execute(
        "SELECT code FROM nta_tsutatsu_index WHERE law_canonical_id = ? LIMIT ?",
        (law_canonical_id, _FANOUT),
    )
    for (code,) in cur.fetchall():
        out.append({"end": f"tsutatsu:{code}", "edge": "applies_to_law", "conf": 0.95})
    if out:
        return out
    # Fallback: LIKE pivot on title. Strip 'law:' prefix; take leading
    # token as needle. nta_tsutatsu_index has no FTS (only 3,221 rows
    # across 3 distinct law_canonical_id values), so a LIKE scan is
    # acceptable.
    needle = law_canonical_id.split(":")[-1].split("_")[0]
    if needle and len(needle) >= 2:
        cur = conn.execute(
            "SELECT code FROM nta_tsutatsu_index WHERE title LIKE ? OR body_excerpt LIKE ? LIMIT ?",
            (f"%{needle}%", f"%{needle}%", _FANOUT),
        )
        for (code,) in cur.fetchall():
            out.append({"end": f"tsutatsu:{code}", "edge": "derived_keyword", "conf": 0.5})
    return out


def _hop3_tsutatsu_to_saiketsu(conn: sqlite3.Connection, tsutatsu_id: str) -> list[dict]:
    """通達 -> 裁決 via FTS keyword overlap on title."""
    code = tsutatsu_id.split(":", 1)[1] if ":" in tsutatsu_id else tsutatsu_id
    cur = conn.execute(
        "SELECT title FROM nta_tsutatsu_index WHERE code = ? LIMIT 1",
        (code,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return []
    out: list[dict] = []
    for kw in _extract_keywords(row[0]):
        rowids = _fts_match_safe(conn, "nta_saiketsu_fts", kw, _FANOUT)
        for rid in rowids:
            cur2 = conn.execute(
                "SELECT volume_no, case_no FROM nta_saiketsu WHERE id = ?",
                (rid,),
            )
            r2 = cur2.fetchone()
            if r2:
                out.append(
                    {
                        "end": f"saiketsu:{r2[0]}-{r2[1]}",
                        "edge": "derived_keyword",
                        "conf": 0.4,
                    }
                )
            if len(out) >= _FANOUT:
                return out
    return out


def _hop4_5_saiketsu_pivot(conn: sqlite3.Connection, saiketsu_id: str) -> list[dict]:
    """裁決 -> 判例 / 同 tax_type 兄弟裁決.

    court_decisions has 0 rows in this snapshot, so we pivot on
    same-tax_type sibling saiketsu via FTS keyword overlap on title.
    The hop is labelled 'derived_keyword' regardless.
    """
    parts = saiketsu_id.split(":", 1)[1].split("-", 1) if ":" in saiketsu_id else []
    if len(parts) != 2:
        return []
    try:
        vol = int(parts[0])
    except ValueError:
        return []
    cur = conn.execute(
        "SELECT id, title, tax_type FROM nta_saiketsu WHERE volume_no = ? AND case_no = ?",
        (vol, parts[1]),
    )
    row = cur.fetchone()
    if not row:
        return []
    src_id, title, tax_type = row
    out: list[dict] = []
    for kw in _extract_keywords(title):
        rowids = _fts_match_safe(conn, "nta_saiketsu_fts", kw, _FANOUT * 2)
        for rid in rowids:
            if rid == src_id:
                continue
            cur2 = conn.execute(
                "SELECT volume_no, case_no FROM nta_saiketsu "
                "WHERE id = ? AND (? IS NULL OR tax_type = ?)",
                (rid, tax_type, tax_type),
            )
            r2 = cur2.fetchone()
            if r2:
                out.append(
                    {
                        "end": f"saiketsu:{r2[0]}-{r2[1]}",
                        "edge": "derived_keyword",
                        "conf": 0.3,
                    }
                )
            if len(out) >= _FANOUT:
                return out
    return out


def _walk_one_seed(conn: sqlite3.Connection, seed: str) -> list[tuple]:
    """BFS 5 hops from seed, return list of rows for am_5hop_graph insert.

    Each row is (start_entity_id, hop, end_entity_id, path_json,
    edge_kinds_json).
    """
    rows: list[tuple] = []
    visited: set[str] = {seed}

    # frontier[h] = list of (current_node, path_so_far, edge_kinds_so_far)
    frontier: list[tuple[str, list[str], list[str]]] = [(seed, [], [])]

    for hop in range(1, 6):
        if not frontier:
            break
        next_frontier: list[tuple[str, list[str], list[str]]] = []
        for node, path, edges in frontier:
            if hop == 1:
                neighbors = _hop1_program_to_law(conn, node)
            elif hop == 2:
                neighbors = _hop2_law_to_tsutatsu(conn, node)
            elif hop == 3:
                neighbors = _hop3_tsutatsu_to_saiketsu(conn, node)
            else:  # 4, 5
                neighbors = _hop4_5_saiketsu_pivot(conn, node)

            for nb in neighbors:
                end = nb["end"]
                if end in visited:
                    continue
                visited.add(end)
                new_edges = edges + [nb["edge"]]
                rows.append(
                    (
                        seed,
                        hop,
                        end,
                        json.dumps(path, ensure_ascii=False),
                        json.dumps(new_edges, ensure_ascii=False),
                    )
                )
                next_frontier.append((end, path + [end], new_edges))
                if len(rows) >= _MAX_PATHS_PER_SEED:
                    return rows
        frontier = next_frontier
    return rows


def _select_seeds(conn: sqlite3.Connection, tier_filter: str, limit: int) -> list[str]:
    """Pick top-N program canonical_ids for the requested tier(s).

    Filter on jpi_programs.tier IN (...) AND excluded=0, ranked by
    coverage_score DESC NULLS LAST. Return canonical_id from
    entity_id_map (am_canonical_id), so the seed format matches the
    am_relation source_entity_id index.
    """
    tiers = [t.strip() for t in tier_filter.split(",") if t.strip()]
    placeholders = ",".join("?" * len(tiers))
    cur = conn.execute(
        f"""
        SELECT m.am_canonical_id
          FROM jpi_programs  p
          JOIN entity_id_map m ON m.jpi_unified_id = p.unified_id
         WHERE p.tier IN ({placeholders})
           AND p.excluded = 0
         ORDER BY p.coverage_score DESC NULLS LAST,
                  p.unified_id
         LIMIT ?
        """,
        (*tiers, limit),
    )
    return [r[0] for r in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent.parent.parent / "autonomath.db"),
        help="Path to autonomath.db",
    )
    parser.add_argument("--tier", default="S,A", help="Tier filter, comma-separated (default: S,A)")
    parser.add_argument("--limit", type=int, default=100, help="Max number of seed programs")
    parser.add_argument("--verbose", action="store_true", help="Per-seed progress logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    seeds = _select_seeds(conn, args.tier, args.limit)
    logger.info("selected %d seeds (tier=%s)", len(seeds), args.tier)

    total_rows = 0
    hop_dist: dict[int, int] = defaultdict(int)

    for i, seed in enumerate(seeds, 1):
        try:
            rows = _walk_one_seed(conn, seed)
        except Exception as e:  # noqa: BLE001 — best-effort per seed
            logger.warning("seed=%s walk failed: %s", seed, e)
            continue
        if not rows:
            if args.verbose:
                logger.debug("seed %d/%d %s: 0 rows", i, len(seeds), seed)
            continue
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO am_5hop_graph "
                "(start_entity_id, hop, end_entity_id, path, edge_kinds) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        for r in rows:
            hop_dist[r[1]] += 1
        total_rows += len(rows)
        if args.verbose:
            logger.debug("seed %d/%d %s: +%d rows", i, len(seeds), seed, len(rows))

    conn.close()
    print(
        f"seeds={len(seeds)} rows_written={total_rows} hop_dist="
        + json.dumps(dict(sorted(hop_dist.items())))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
