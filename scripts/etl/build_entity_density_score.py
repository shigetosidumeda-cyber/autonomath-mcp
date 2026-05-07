#!/usr/bin/env python3
"""Populate `am_entity_density_score` for every `am_entities.canonical_id`.

Why this exists:
    Single-lookup density signal answering "how richly is this entity
    wired into the autonomath knowledge graph?". Used by relevance
    ranking, audit-pack curation, and customer-LLM search re-ranking
    so the read path is one PRIMARY-KEY lookup per entity.

Axes (per canonical_id):
    * verification_count  -- distinct am_entity_source rows
                             (independent source corroborations)
    * edge_count          -- am_relation appearances as
                             source_entity_id OR target_entity_id
    * fact_count          -- am_entity_facts rows
    * alias_count         -- am_alias rows where entity_table='am_entities'
    * adoption_count      -- inbound am_relation edges originating from
                             record_kind='adoption' entities
    * enforcement_count   -- am_enforcement_detail.entity_id matches

density_score formula:
    Each axis is z-normalized over the full population:
        z(x) = (x - mean(x)) / stddev(x)
    Final score:
        density_score =
            z(verification) + z(edge) + z(fact)
          + z(alias)        + z(adoption)
          - z(enforcement)             # NEGATIVE weight (sinks bad actors)

density_rank:
    Dense rank over density_score DESC (1 = highest density entity).

Reporting (printed to stdout at end):
    * Per-record_kind top 10 high-density entities
    * Density-score histogram (10 buckets across observed range)

Non-LLM: pure SQL aggregation + Python statistics. No external services.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
import time
from pathlib import Path

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
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_entity_density_score';"
    ).fetchone()
    if row is None:
        sys.stderr.write(
            "ERROR: am_entity_density_score table missing. Apply "
            "scripts/migrations/158_am_entity_density_score.sql first.\n"
        )
        sys.exit(3)


def compute_axis_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Return per-entity counts for all six axes plus record_kind.

    Result shape:
        {
          canonical_id: {
            "record_kind": str,
            "verification_count": int,
            "edge_count": int,
            "fact_count": int,
            "alias_count": int,
            "adoption_count": int,
            "enforcement_count": int,
          },
          ...
        }
    """
    out: dict[str, dict[str, int]] = {}

    sys.stderr.write("[1/7] Loading am_entities (canonical_id, record_kind)…\n")
    t0 = time.time()
    cur = conn.execute("SELECT canonical_id, record_kind FROM am_entities;")
    for row in cur:
        out[row["canonical_id"]] = {
            "record_kind": row["record_kind"],
            "verification_count": 0,
            "edge_count": 0,
            "fact_count": 0,
            "alias_count": 0,
            "adoption_count": 0,
            "enforcement_count": 0,
        }
    sys.stderr.write(f"   loaded {len(out):,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[2/7] Aggregating verification_count (am_entity_source)…\n")
    t0 = time.time()
    cur = conn.execute(
        "SELECT entity_id, COUNT(DISTINCT source_id) AS c FROM am_entity_source GROUP BY entity_id;"
    )
    seen = 0
    for row in cur:
        rec = out.get(row["entity_id"])
        if rec is not None:
            rec["verification_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[3/7] Aggregating edge_count (am_relation src + tgt)…\n")
    t0 = time.time()
    cur = conn.execute(
        "SELECT entity_id, COUNT(*) AS c FROM ("
        "  SELECT source_entity_id AS entity_id FROM am_relation"
        "  UNION ALL"
        "  SELECT target_entity_id AS entity_id FROM am_relation "
        "    WHERE target_entity_id IS NOT NULL"
        ") GROUP BY entity_id;"
    )
    seen = 0
    for row in cur:
        rec = out.get(row["entity_id"])
        if rec is not None:
            rec["edge_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[4/7] Aggregating fact_count (am_entity_facts)…\n")
    t0 = time.time()
    cur = conn.execute("SELECT entity_id, COUNT(*) AS c FROM am_entity_facts GROUP BY entity_id;")
    seen = 0
    for row in cur:
        rec = out.get(row["entity_id"])
        if rec is not None:
            rec["fact_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[5/7] Aggregating alias_count (am_alias)…\n")
    t0 = time.time()
    cur = conn.execute(
        "SELECT canonical_id, COUNT(*) AS c FROM am_alias "
        "WHERE entity_table='am_entities' GROUP BY canonical_id;"
    )
    seen = 0
    for row in cur:
        rec = out.get(row["canonical_id"])
        if rec is not None:
            rec["alias_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write(
        "[6/7] Aggregating adoption_count (inbound edges from record_kind='adoption')…\n"
    )
    t0 = time.time()
    cur = conn.execute(
        "SELECT r.target_entity_id AS entity_id, COUNT(*) AS c "
        "FROM am_relation r "
        "JOIN am_entities src ON src.canonical_id = r.source_entity_id "
        "WHERE src.record_kind = 'adoption' "
        "  AND r.target_entity_id IS NOT NULL "
        "GROUP BY r.target_entity_id;"
    )
    seen = 0
    for row in cur:
        rec = out.get(row["entity_id"])
        if rec is not None:
            rec["adoption_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    sys.stderr.write("[7/7] Aggregating enforcement_count (am_enforcement_detail)…\n")
    t0 = time.time()
    cur = conn.execute(
        "SELECT entity_id, COUNT(*) AS c FROM am_enforcement_detail GROUP BY entity_id;"
    )
    seen = 0
    for row in cur:
        rec = out.get(row["entity_id"])
        if rec is not None:
            rec["enforcement_count"] = row["c"]
            seen += 1
    sys.stderr.write(f"   matched {seen:,} entities ({time.time() - t0:.1f}s)\n")

    return out


def zscore_normalizers(
    counts: dict[str, dict[str, int]],
    axes: list[str],
) -> dict[str, tuple[float, float]]:
    """Return {axis: (mean, stddev)} for each axis across the population."""
    norm: dict[str, tuple[float, float]] = {}
    for axis in axes:
        values = [r[axis] for r in counts.values()]
        mu = statistics.fmean(values)
        sigma = statistics.pstdev(values)
        if sigma == 0.0:
            sigma = 1.0  # avoid div0; flat axis contributes 0 z everywhere
        norm[axis] = (mu, sigma)
    return norm


def populate_table(
    conn: sqlite3.Connection,
    counts: dict[str, dict[str, int]],
    norm: dict[str, tuple[float, float]],
    batch: int = 5000,
) -> int:
    sys.stderr.write("[populate] computing density_score for every entity…\n")
    t0 = time.time()

    pos_axes = (
        "verification_count",
        "edge_count",
        "fact_count",
        "alias_count",
        "adoption_count",
    )
    neg_axes = ("enforcement_count",)

    rows: list[tuple] = []
    for canonical_id, rec in counts.items():
        score = 0.0
        for axis in pos_axes:
            mu, sigma = norm[axis]
            score += (rec[axis] - mu) / sigma
        for axis in neg_axes:
            mu, sigma = norm[axis]
            score -= (rec[axis] - mu) / sigma
        rows.append(
            (
                canonical_id,
                rec["record_kind"],
                rec["verification_count"],
                rec["edge_count"],
                rec["fact_count"],
                rec["alias_count"],
                rec["adoption_count"],
                rec["enforcement_count"],
                score,
            )
        )

    # Rank: dense_rank over density_score DESC.
    # Sort once, assign rank with tie handling.
    rows.sort(key=lambda r: r[8], reverse=True)
    ranked: list[tuple] = []
    last_score = None
    rank = 0
    for dense, r in enumerate(rows, start=1):
        if r[8] != last_score:
            rank = dense
            last_score = r[8]
        ranked.append(r + (rank,))

    sys.stderr.write(f"   computed scores ({time.time() - t0:.1f}s)\n")
    t0 = time.time()

    conn.execute("BEGIN;")
    conn.execute("DELETE FROM am_entity_density_score;")
    sql = (
        "INSERT INTO am_entity_density_score("
        "  entity_id, record_kind, verification_count, edge_count, "
        "  fact_count, alias_count, adoption_count, enforcement_count, "
        "  density_score, density_rank, last_updated"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'));"
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


def report(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 78)
    print("am_entity_density_score — population summary")
    print("=" * 78)
    total = conn.execute("SELECT COUNT(*) FROM am_entity_density_score;").fetchone()[0]
    print(f"total entities scored: {total:,}")

    rng = conn.execute(
        "SELECT MIN(density_score), MAX(density_score), "
        "AVG(density_score) FROM am_entity_density_score;"
    ).fetchone()
    print(f"density_score range: min={rng[0]:.3f}  max={rng[1]:.3f}  mean={rng[2]:.3f}")

    print()
    print("-" * 78)
    print("Top 10 high-density entities by record_kind")
    print("-" * 78)
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT record_kind FROM am_entity_density_score "
            "WHERE record_kind IS NOT NULL ORDER BY record_kind;"
        )
    ]
    for kind in kinds:
        print()
        print(f"[{kind}]")
        cur = conn.execute(
            "SELECT d.entity_id, e.primary_name, d.density_score, "
            "       d.verification_count, d.edge_count, d.fact_count, "
            "       d.alias_count, d.adoption_count, d.enforcement_count "
            "FROM am_entity_density_score d "
            "LEFT JOIN am_entities e ON e.canonical_id = d.entity_id "
            "WHERE d.record_kind = ? "
            "ORDER BY d.density_score DESC LIMIT 10;",
            (kind,),
        )
        print(
            f"  {'rank':>4}  {'score':>8}  {'ver':>4} {'edge':>5} {'fact':>5} "
            f"{'ali':>4} {'adopt':>5} {'enf':>4}  name (id)"
        )
        for i, row in enumerate(cur, 1):
            name = (row["primary_name"] or "")[:50]
            print(
                f"  {i:>4}  {row['density_score']:>8.3f}  "
                f"{row['verification_count']:>4} {row['edge_count']:>5} "
                f"{row['fact_count']:>5} {row['alias_count']:>4} "
                f"{row['adoption_count']:>5} {row['enforcement_count']:>4}  "
                f"{name}  ({row['entity_id'][:30]})"
            )

    print()
    print("-" * 78)
    print("Density-score histogram (10 equal-width buckets across full range)")
    print("-" * 78)
    lo, hi = float(rng[0]), float(rng[1])
    if hi == lo:
        print(f"  flat distribution: every entity scored {lo:.3f}")
        return
    n_buckets = 10
    width = (hi - lo) / n_buckets
    buckets = [0] * n_buckets
    cur = conn.execute("SELECT density_score FROM am_entity_density_score;")
    for (s,) in cur:
        if s is None:
            continue
        idx = int((s - lo) / width)
        if idx >= n_buckets:
            idx = n_buckets - 1
        buckets[idx] += 1
    max_count = max(buckets) or 1
    for i, c in enumerate(buckets):
        b_lo = lo + i * width
        b_hi = b_lo + width
        bar = "#" * int(60 * c / max_count)
        print(f"  [{b_lo:>+8.3f} .. {b_hi:>+8.3f})  {c:>7,}  {bar}")

    print()
    print("-" * 78)
    print("Per-kind population coverage (count, mean score)")
    print("-" * 78)
    cur = conn.execute(
        "SELECT record_kind, COUNT(*), AVG(density_score) "
        "FROM am_entity_density_score GROUP BY record_kind "
        "ORDER BY COUNT(*) DESC;"
    )
    print(f"  {'record_kind':<22} {'n':>10}  {'avg_score':>10}")
    for row in cur:
        print(f"  {(row[0] or 'NULL'):<22} {row[1]:>10,}  {row[2]:>+10.3f}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--report-only", action="store_true", help="skip recompute, just print report")
    args = p.parse_args()

    conn = open_db(args.db)
    ensure_table(conn)

    if not args.report_only:
        counts = compute_axis_counts(conn)
        axes = (
            "verification_count",
            "edge_count",
            "fact_count",
            "alias_count",
            "adoption_count",
            "enforcement_count",
        )
        norm = zscore_normalizers(counts, list(axes))
        sys.stderr.write("[normalizers] mean / stddev per axis:\n")
        for a in axes:
            mu, sigma = norm[a]
            sys.stderr.write(f"   {a:<22} mu={mu:>10.3f}  sigma={sigma:>10.3f}\n")
        populate_table(conn, counts, norm)

    report(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
