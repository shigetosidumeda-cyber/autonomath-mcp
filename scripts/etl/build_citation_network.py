"""build_citation_network — populate ``am_citation_network`` (Wave 24 §163).

Cross-corpus citation edges:

  citing_kind='law'            am_law_article.text_full regex extracts
                               cited 法令名（XX年法律第NN号）/（昭和NN年
                               法律第NN号）style parentheticals and resolves
                               to am_law.canonical_id by name suffix match.

  citing_kind='tsutatsu'       nta_tsutatsu_index.code -> law_canonical_id
                               (single edge per row, the law the tsutatsu
                               applies to). citation_count = 1.

  citing_kind='court_decision' jpi_court_decisions.related_law_ids_json
                               JSON-parsed; keep entries that resolve in
                               am_law.canonical_id.

Per `feedback_no_operator_llm_api` and `feedback_autonomath_no_api_use`,
this script is pure regex + SQL — NO LLM API calls.

Usage
-----
    .venv/bin/python scripts/etl/build_citation_network.py \\
        --db autonomath.db [--limit-articles N]

Outputs a final report:

    edges_total=R distinct_laws=K
    top inbound (most-cited): [(law, count), ...]
    top outbound (most-citing): [(law, count), ...]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger("build_citation_network")

# Match parentheticals of the form （昭和|平成|令和|明治|大正NN年法律第NN号）.
# These are the canonical attribution marker for inline law citations in
# Japanese statutes.  We capture the whole parenthetical so we can also
# inspect the immediately-preceding law-name suffix.
_ERA_PAREN_RE = re.compile(
    r"[（(]\s*(明治|大正|昭和|平成|令和)[一-鿿\d〇一二三四五六七八九十百]+?年法律第[一-鿿\d〇一二三四五六七八九十百]+?号\s*[）)]"
)

# Match law-name suffixes immediately preceding an era paren.  We only
# look at the last ~40 chars before the open-paren — citations name the
# specific law just before the era marker.
_LAW_NAME_TAIL_RE = re.compile(
    r"([一-鿿぀-ゟ゠-ヿA-Za-z0-9・ー]{2,40}?(?:法|令|条例|規則|規程|通則|準則))[（(]"
)


def _build_law_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {law_display_name: canonical_id} including short_name."""
    cur = conn.execute("SELECT canonical_id, canonical_name, short_name FROM am_law")
    out: dict[str, str] = {}
    for cid, name, short in cur:
        if name:
            out[name] = cid
        if short and short not in out:
            out[short] = cid
    return out


def _resolve_name(name: str, lookup: dict[str, str]) -> str | None:
    """Resolve a raw law-name string to canonical_id with relaxed matching."""
    if not name:
        return None
    if name in lookup:
        return lookup[name]
    # Try suffix match: cited names sometimes have a leading clause
    # (e.g. "情報処理の促進に関する法律" -> matches longest registered
    # name ending with the same chars).
    for full, cid in lookup.items():
        if name.endswith(full) or full.endswith(name):
            return cid
    return None


def _extract_law_citations(text: str, lookup: dict[str, str]) -> Counter[str]:
    """Return Counter of canonical_id occurrences in ``text``."""
    if not text:
        return Counter()
    out: Counter[str] = Counter()
    # Iterate era-parens, look back for the immediately-preceding law name.
    for m in _ERA_PAREN_RE.finditer(text):
        start = max(0, m.start() - 40)
        window = text[start : m.start() + 1]  # include the open-paren char
        # Find the LAST law-name-tail in the window.
        candidates = list(_LAW_NAME_TAIL_RE.finditer(window))
        if not candidates:
            continue
        raw_name = candidates[-1].group(1)
        cid = _resolve_name(raw_name, lookup)
        if cid is not None:
            out[cid] += 1
    return out


def populate_law_citations(
    conn: sqlite3.Connection,
    lookup: dict[str, str],
    limit: int | None,
) -> int:
    """Populate citing_kind='law' edges. Returns rows-written count."""
    sql = (
        "SELECT law_canonical_id, text_full FROM am_law_article "
        "WHERE text_full IS NOT NULL AND text_full != ''"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    edges: dict[tuple[str, str], int] = defaultdict(int)
    n_articles = 0
    for citing_id, body in conn.execute(sql):
        n_articles += 1
        if not citing_id:
            continue
        for cited_id, cnt in _extract_law_citations(body, lookup).items():
            if cited_id == citing_id:
                continue  # skip self-cites
            edges[(citing_id, cited_id)] += cnt
        if n_articles % 10000 == 0:
            logger.info("law articles scanned=%d edges=%d", n_articles, len(edges))
    written = 0
    for (citing, cited), cnt in edges.items():
        conn.execute(
            "INSERT INTO am_citation_network "
            "(citing_entity_id, citing_kind, cited_entity_id, cited_kind, citation_count) "
            "VALUES (?, 'law', ?, 'law', ?) "
            "ON CONFLICT(citing_entity_id, cited_entity_id) DO UPDATE SET "
            "citation_count = excluded.citation_count, "
            "computed_at = datetime('now')",
            (citing, cited, cnt),
        )
        written += 1
    conn.commit()
    logger.info("law->law edges written=%d (articles scanned=%d)", written, n_articles)
    return written


def populate_tsutatsu_citations(conn: sqlite3.Connection) -> int:
    """Populate citing_kind='tsutatsu' edges. Returns rows-written count."""
    cur = conn.execute(
        "SELECT code, law_canonical_id FROM nta_tsutatsu_index "
        "WHERE law_canonical_id IS NOT NULL AND law_canonical_id != ''"
    )
    written = 0
    for code, law_cid in cur:
        # Confirm law exists
        if not conn.execute("SELECT 1 FROM am_law WHERE canonical_id=?", (law_cid,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO am_citation_network "
            "(citing_entity_id, citing_kind, cited_entity_id, cited_kind, citation_count) "
            "VALUES (?, 'tsutatsu', ?, 'law', 1) "
            "ON CONFLICT(citing_entity_id, cited_entity_id) DO UPDATE SET "
            "citation_count = excluded.citation_count, "
            "computed_at = datetime('now')",
            (code, law_cid),
        )
        written += 1
    conn.commit()
    logger.info("tsutatsu->law edges written=%d", written)
    return written


def populate_court_citations(conn: sqlite3.Connection) -> int:
    """Populate citing_kind='court_decision' edges. Returns rows-written."""
    # court_decisions in this DB is empty; fall back to jpi_court_decisions
    # which carries 2065 rows.
    has_jpi = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jpi_court_decisions'"
    ).fetchone()
    table = "jpi_court_decisions" if has_jpi else "court_decisions"
    cur = conn.execute(
        f"SELECT unified_id, related_law_ids_json FROM {table} "
        "WHERE related_law_ids_json IS NOT NULL AND related_law_ids_json != '' "
        "AND related_law_ids_json != '[]' AND related_law_ids_json != 'null'"
    )
    written = 0
    for unified_id, raw in cur:
        try:
            ids = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ids, list):
            continue
        per_doc: Counter[str] = Counter()
        for cid in ids:
            if not isinstance(cid, str):
                continue
            if conn.execute("SELECT 1 FROM am_law WHERE canonical_id=?", (cid,)).fetchone():
                per_doc[cid] += 1
        for cited, cnt in per_doc.items():
            conn.execute(
                "INSERT INTO am_citation_network "
                "(citing_entity_id, citing_kind, cited_entity_id, cited_kind, citation_count) "
                "VALUES (?, 'court_decision', ?, 'law', ?) "
                "ON CONFLICT(citing_entity_id, cited_entity_id) DO UPDATE SET "
                "citation_count = excluded.citation_count, "
                "computed_at = datetime('now')",
                (unified_id, cited, cnt),
            )
            written += 1
    conn.commit()
    logger.info("court->law edges written=%d (table=%s)", written, table)
    return written


def report(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM am_citation_network").fetchone()[0]
    distinct = conn.execute(
        "SELECT COUNT(*) FROM ("
        "SELECT cited_entity_id AS e FROM am_citation_network "
        "UNION SELECT citing_entity_id FROM am_citation_network)"
    ).fetchone()[0]
    print(f"\n=== am_citation_network report ===")
    print(f"edges_total={total}  distinct_entities={distinct}")

    # Per-kind edge breakdown
    print("\nedge breakdown by citing_kind:")
    for kind, cnt in conn.execute(
        "SELECT citing_kind, COUNT(*) FROM am_citation_network "
        "GROUP BY citing_kind ORDER BY COUNT(*) DESC"
    ):
        print(f"  {kind}: {cnt}")

    print("\ntop 20 most-cited laws (inbound degree, sum of citation_count):")
    for cid, name, total_cnt, src_cnt in conn.execute(
        "SELECT cn.cited_entity_id, COALESCE(l.canonical_name, '?'), "
        "SUM(cn.citation_count), COUNT(DISTINCT cn.citing_entity_id) "
        "FROM am_citation_network cn "
        "LEFT JOIN am_law l ON l.canonical_id = cn.cited_entity_id "
        "GROUP BY cn.cited_entity_id "
        "ORDER BY SUM(cn.citation_count) DESC LIMIT 20"
    ):
        print(f"  {total_cnt:>6} cites ({src_cnt} sources)  {cid}  {name}")

    print("\ntop 20 most-citing laws (out-degree, distinct cited):")
    for cid, name, deg in conn.execute(
        "SELECT cn.citing_entity_id, COALESCE(l.canonical_name, '?'), "
        "COUNT(DISTINCT cn.cited_entity_id) AS deg "
        "FROM am_citation_network cn "
        "LEFT JOIN am_law l ON l.canonical_id = cn.citing_entity_id "
        "WHERE cn.citing_kind='law' "
        "GROUP BY cn.citing_entity_id "
        "ORDER BY deg DESC LIMIT 20"
    ):
        print(f"  {deg:>4} distinct cited  {cid}  {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="autonomath.db")
    parser.add_argument("--limit-articles", type=int, default=None)
    parser.add_argument(
        "--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        # Sanity: table exists (migration 163 applied)
        if not conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_citation_network'"
        ).fetchone():
            logger.error("am_citation_network missing — apply migration 163 first")
            return 1

        lookup = _build_law_lookup(conn)
        logger.info("law lookup size=%d", len(lookup))

        populate_law_citations(conn, lookup, args.limit_articles)
        populate_tsutatsu_citations(conn)
        populate_court_citations(conn)

        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
