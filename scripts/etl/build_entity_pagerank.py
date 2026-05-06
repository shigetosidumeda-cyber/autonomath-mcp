#!/usr/bin/env python3
"""Populate `am_entity_pagerank` for every `am_entities.canonical_id`.

Why this exists:
    W22-9 shipped `am_entity_density_score` (mig 158) — a six-axis
    z-normalized rollup. Density is a LOCAL signal: it counts how many
    edges / facts / aliases each entity has, but ignores how
    *important* the neighbors are. PageRank closes that gap. It
    propagates centrality iteratively over the directed `am_relation`
    graph so an entity wired to other high-centrality entities scores
    higher than an entity wired to the same number of leaf entities.

    Used by relevance ranking, audit-pack curation, and customer-LLM
    search re-ranking. Read path is one PRIMARY-KEY lookup per entity.

Algorithm:
    1. Build a directed graph from every am_relation row where
       target_entity_id IS NOT NULL. Multi-edges between the same
       (source, target) pair collapse to a single edge.
    2. Add every am_entities.canonical_id as a node so isolated
       entities still receive the baseline (1-alpha)/N score.
    3. networkx.pagerank(graph, alpha=0.85) — power iteration to
       convergence. Pure non-LLM algorithm.

Reporting (printed to stdout at end):
    * Per-record_kind top 20 high-centrality entities.
    * Pearson correlation between pagerank_score and W22-9
      density_score across all entities also present in
      am_entity_density_score.

Non-LLM: networkx PageRank algorithm + SQL aggregation.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import time
from pathlib import Path

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.stderr.write(f"ERROR: autonomath.db not found at {path}\n")
        sys.exit(2)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -400000;")  # 400 MB page cache
    conn.execute("PRAGMA mmap_size  = 8589934592;")  # 8 GB
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_entity_pagerank';"
    ).fetchone()
    if row is None:
        sys.stderr.write(
            "ERROR: am_entity_pagerank table missing. Apply "
            "scripts/migrations/162_am_entity_pagerank.sql first.\n"
        )
        sys.exit(3)


def build_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Build directed graph from am_entities + am_relation."""
    g: nx.DiGraph = nx.DiGraph()

    sys.stderr.write("[1/3] Loading am_entities (canonical_id)…\n")
    t0 = time.time()
    n_nodes = 0
    cur = conn.execute("SELECT canonical_id FROM am_entities;")
    for (cid,) in cur:
        g.add_node(cid)
        n_nodes += 1
    sys.stderr.write(f"   added {n_nodes:,} nodes ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[2/3] Loading am_relation edges (target_entity_id NOT NULL)…\n")
    t0 = time.time()
    cur = conn.execute(
        "SELECT source_entity_id, target_entity_id FROM am_relation "
        "WHERE target_entity_id IS NOT NULL;"
    )
    n_edges_raw = 0
    for src, tgt in cur:
        n_edges_raw += 1
        # add_edge collapses parallel edges between same (src, tgt) pair.
        if g.has_node(src) and g.has_node(tgt):
            g.add_edge(src, tgt)
    sys.stderr.write(
        f"   processed {n_edges_raw:,} raw edges → "
        f"{g.number_of_edges():,} unique directed edges "
        f"({time.time() - t0:.1f}s)\n"
    )
    return g


def compute_pagerank(g: nx.DiGraph, alpha: float = 0.85) -> dict[str, float]:
    sys.stderr.write(f"[3/3] networkx.pagerank(alpha={alpha})…\n")
    t0 = time.time()
    pr = nx.pagerank(g, alpha=alpha)
    sys.stderr.write(f"   pagerank converged on {len(pr):,} nodes ({time.time() - t0:.1f}s)\n")
    return pr


def populate_table(
    conn: sqlite3.Connection,
    g: nx.DiGraph,
    pagerank: dict[str, float],
    batch: int = 5000,
) -> int:
    sys.stderr.write("[populate] writing am_entity_pagerank rows…\n")
    t0 = time.time()

    rows: list[tuple] = []
    for cid, score in pagerank.items():
        rows.append(
            (
                cid,
                float(score),
                int(g.in_degree(cid)),
                int(g.out_degree(cid)),
            )
        )

    # Dense rank over pagerank_score DESC.
    rows.sort(key=lambda r: r[1], reverse=True)
    ranked: list[tuple] = []
    last_score = None
    rank = 0
    dense = 0
    for r in rows:
        dense += 1
        if r[1] != last_score:
            rank = dense
            last_score = r[1]
        # final tuple: (entity_id, pagerank_score, pagerank_rank,
        #               in_degree, out_degree)
        ranked.append((r[0], r[1], rank, r[2], r[3]))

    sys.stderr.write(f"   ranked {len(ranked):,} entities ({time.time() - t0:.1f}s)\n")
    t0 = time.time()

    conn.execute("BEGIN;")
    conn.execute("DELETE FROM am_entity_pagerank;")
    sql = (
        "INSERT INTO am_entity_pagerank("
        "  entity_id, pagerank_score, pagerank_rank, "
        "  in_degree, out_degree, last_updated"
        ") VALUES (?,?,?,?,?,datetime('now'));"
    )
    inserted = 0
    chunk: list[tuple] = []
    for r in ranked:
        chunk.append(r)
        if len(chunk) >= batch:
            conn.executemany(sql, chunk)
            inserted += len(chunk)
            chunk.clear()
    if chunk:
        conn.executemany(sql, chunk)
        inserted += len(chunk)
    conn.commit()
    sys.stderr.write(f"   inserted {inserted:,} rows ({time.time() - t0:.1f}s)\n")
    return inserted


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson r between two equal-length sequences."""
    n = len(xs)
    if n == 0:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    den = math.sqrt(den_x * den_y)
    if den == 0.0:
        return float("nan")
    return num / den


def spearman_rank_correlation(xs: list[float], ys: list[float]) -> float:
    """Spearman rho via Pearson r over rank-converted values."""

    def to_ranks(vs: list[float]) -> list[float]:
        order = sorted(range(len(vs)), key=lambda i: vs[i])
        ranks = [0.0] * len(vs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # 1-indexed average rank for ties
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    return pearson_correlation(to_ranks(xs), to_ranks(ys))


def report(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 78)
    print("am_entity_pagerank — population summary")
    print("=" * 78)
    total = conn.execute("SELECT COUNT(*) FROM am_entity_pagerank;").fetchone()[0]
    print(f"total entities scored: {total:,}")

    rng = conn.execute(
        "SELECT MIN(pagerank_score), MAX(pagerank_score), "
        "AVG(pagerank_score), SUM(pagerank_score) "
        "FROM am_entity_pagerank;"
    ).fetchone()
    print(
        f"pagerank_score range: min={rng[0]:.3e}  max={rng[1]:.3e}  "
        f"mean={rng[2]:.3e}  sum={rng[3]:.6f}"
    )

    print()
    print("-" * 78)
    print("Top 20 high-centrality entities by record_kind")
    print("-" * 78)
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT e.record_kind FROM am_entity_pagerank p "
            "JOIN am_entities e ON e.canonical_id = p.entity_id "
            "WHERE e.record_kind IS NOT NULL "
            "ORDER BY e.record_kind;"
        )
    ]
    for kind in kinds:
        print()
        print(f"[{kind}]")
        cur = conn.execute(
            "SELECT p.entity_id, e.primary_name, p.pagerank_score, "
            "       p.pagerank_rank, p.in_degree, p.out_degree "
            "FROM am_entity_pagerank p "
            "JOIN am_entities e ON e.canonical_id = p.entity_id "
            "WHERE e.record_kind = ? "
            "ORDER BY p.pagerank_score DESC LIMIT 20;",
            (kind,),
        )
        print(f"  {'#':>3}  {'global_rank':>11}  {'pagerank':>11}  {'in':>6} {'out':>6}  name (id)")
        for i, row in enumerate(cur, 1):
            name = (row["primary_name"] or "")[:50]
            print(
                f"  {i:>3}  {row['pagerank_rank']:>11}  "
                f"{row['pagerank_score']:>11.3e}  "
                f"{row['in_degree']:>6} {row['out_degree']:>6}  "
                f"{name}  ({row['entity_id'][:30]})"
            )

    print()
    print("-" * 78)
    print("Per-kind population coverage")
    print("-" * 78)
    cur = conn.execute(
        "SELECT e.record_kind, COUNT(*), AVG(p.pagerank_score) "
        "FROM am_entity_pagerank p "
        "JOIN am_entities e ON e.canonical_id = p.entity_id "
        "GROUP BY e.record_kind ORDER BY COUNT(*) DESC;"
    )
    print(f"  {'record_kind':<22} {'n':>10}  {'avg_pagerank':>14}")
    for row in cur:
        print(f"  {(row[0] or 'NULL'):<22} {row[1]:>10,}  {row[2]:>14.3e}")

    print()
    print("-" * 78)
    print("Correlation: PageRank vs W22-9 density_score (mig 158)")
    print("-" * 78)
    has_density = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_entity_density_score';"
    ).fetchone()
    if has_density is None:
        print("  am_entity_density_score table not present — skipping.")
        return
    cur = conn.execute(
        "SELECT p.pagerank_score, d.density_score "
        "FROM am_entity_pagerank p "
        "JOIN am_entity_density_score d ON d.entity_id = p.entity_id;"
    )
    xs: list[float] = []
    ys: list[float] = []
    for pr, dn in cur:
        if pr is None or dn is None:
            continue
        xs.append(float(pr))
        ys.append(float(dn))
    n = len(xs)
    if n < 2:
        print(f"  insufficient overlap ({n} entities) — cannot compute.")
        return
    pearson = pearson_correlation(xs, ys)
    spearman = spearman_rank_correlation(xs, ys)
    print(f"  paired entities       : {n:,}")
    print(f"  Pearson  r (linear)   : {pearson:+.4f}")
    print(f"  Spearman ρ (rank)     : {spearman:+.4f}")
    if abs(pearson) >= 0.9:
        verdict = "near-duplicate signal — pagerank adds little over density"
    elif abs(pearson) >= 0.7:
        verdict = "strongly correlated — overlapping but not identical"
    elif abs(pearson) >= 0.4:
        verdict = "moderately correlated — captures partly different structure"
    elif abs(pearson) >= 0.2:
        verdict = "weakly correlated — pagerank reveals different ordering"
    else:
        verdict = "near-orthogonal — pagerank ranks entities very differently"
    print(f"  verdict               : {verdict}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument(
        "--alpha",
        type=float,
        default=0.85,
        help="PageRank damping factor (default 0.85, the canonical value)",
    )
    p.add_argument(
        "--report-only",
        action="store_true",
        help="skip recompute, just print report",
    )
    args = p.parse_args()

    conn = open_db(args.db)
    ensure_table(conn)

    if not args.report_only:
        g = build_graph(conn)
        pr = compute_pagerank(g, alpha=args.alpha)
        populate_table(conn, g, pr)

    report(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
