#!/usr/bin/env python3
"""Populate `am_id_bridge` between UNI-* and matrix-resident namespaces.

Why this exists:
    `jpi_adoption_records.program_id` carries jpintel-namespace UNI-* IDs
    (e.g. "UNI-442fcccdd0"). `am_compat_matrix.program_a_id` /
    `program_b_id` carry matrix-resident IDs in the form
    "<kind>:<topic>:<index>:<hash>" (e.g.
    "certification:09_certification_programs:000000:4bc7304a58",
    "program:04_program_documents:000113:0985623897").

    W22-6 launch audit (2026-05-04) found that the existing
    `entity_id_map` (6,339 rows, all 'exact_name'/'exact'/'name_normalized'
    matches into the `program:*` kind only) leaves the top-15 most-adopted
    UNI program_ids essentially unmapped against the certification /
    tax_measure / loan partitions of the matrix. Exclusion-rule and
    complementary-combo evaluation therefore returned 100% "matrix
    unmapped".

    This populator fills `am_id_bridge` with three layers:

      1. **exact**  -- mirror of `entity_id_map` (1.0 confidence).
                       Both directions (UNI -> matrix-id and the reverse)
                       are written so a single PRIMARY-KEY lookup on
                       (id_a) covers either side.
      2. **fuzzy_name** -- For every UNI-* id appearing in
                       `jpi_adoption_records.program_id` we resolve the
                       primary_name from `jpi_programs.primary_name` and
                       fuzzy-match it against `am_entities.primary_name`
                       restricted to record_kind in
                       {program, certification, tax_measure, loan}. We
                       use rapidfuzz token_set_ratio + WRatio with
                       threshold 0.85; only candidates that actually
                       appear as `program_a_id` or `program_b_id` in
                       `am_compat_matrix` are retained (no point
                       bridging to a node the matrix never references).
      3. **derived_keyword** -- reserved for future use; not produced by
                       this script (kept for the bridge_kind enum).

    bridge_kind = 'manual' is reserved for hand-curated overrides,
    handled out-of-band by the operator.

Algorithm: pure rapidfuzz (Jaro-Winkler-style scoring via WRatio) +
SQL aggregation. NO LLM call. Deterministic given fixed input.

Idempotent: INSERT OR REPLACE keyed on (id_a, id_b). Safe to re-run on
every Fly boot. Typical wall time ~30s on the production 9.4 GB
autonomath.db.

Usage:
    .venv/bin/python scripts/etl/build_id_bridge.py
    .venv/bin/python scripts/etl/build_id_bridge.py --threshold 0.90
    .venv/bin/python scripts/etl/build_id_bridge.py --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

try:
    from rapidfuzz import fuzz, process
except ImportError:
    sys.stderr.write("ERROR: rapidfuzz not installed. Run: pip install rapidfuzz\n")
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

# Matrix-eligible record kinds. These are the only kinds that ever appear
# as program_a_id / program_b_id in am_compat_matrix, so fuzzy matching
# against any other kind is wasted work.
MATRIX_KINDS = ("program", "certification", "tax_measure", "loan")


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
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_id_bridge';"
    ).fetchone()
    if row is None:
        sys.stderr.write(
            "ERROR: am_id_bridge table missing. Apply "
            "scripts/migrations/159_am_id_bridge.sql first.\n"
        )
        sys.exit(3)


def load_matrix_ids(conn: sqlite3.Connection) -> set[str]:
    """Return the set of all program_a_id / program_b_id values
    referenced by am_compat_matrix. Only matrix-resident IDs are kept
    in the fuzzy candidate pool."""
    sys.stderr.write("[1/5] Loading am_compat_matrix id population...\n")
    ids: set[str] = set()
    cur = conn.execute(
        "SELECT program_a_id FROM am_compat_matrix UNION SELECT program_b_id FROM am_compat_matrix;"
    )
    for row in cur:
        ids.add(row[0])
    sys.stderr.write(f"      matrix carries {len(ids):,} distinct ids\n")
    return ids


def load_matrix_candidates(
    conn: sqlite3.Connection, matrix_ids: set[str]
) -> dict[str, list[tuple[str, str]]]:
    """Return per-record_kind list of (canonical_id, name_or_alias) for
    every am_entities row that is matrix-resident. Includes both
    primary_name AND every am_alias row for that entity, so short-form
    abbreviations like "ものづくり補助金" can match the long-form
    "ものづくり・商業・サービス生産性向上促進補助金"."""
    sys.stderr.write("[2/5] Loading matrix-resident am_entities + aliases...\n")
    out: dict[str, list[tuple[str, str]]] = {k: [] for k in MATRIX_KINDS}
    placeholders = ",".join("?" for _ in MATRIX_KINDS)
    cur = conn.execute(
        f"SELECT canonical_id, record_kind, primary_name "
        f"FROM am_entities WHERE record_kind IN ({placeholders});",
        MATRIX_KINDS,
    )
    canonical_kinds: dict[str, str] = {}
    skipped = 0
    for row in cur:
        cid = row["canonical_id"]
        if cid not in matrix_ids:
            skipped += 1
            continue
        canonical_kinds[cid] = row["record_kind"]
        out[row["record_kind"]].append((cid, row["primary_name"]))

    # Pull aliases ONLY for matrix-resident canonical_ids (huge speedup).
    # alias_kind in {'canonical','abbreviation','kana','legacy','partial'}
    # are the Japanese-text variants likely to match an UNI primary_name.
    # 'english' is excluded because UNI primary_names are Japanese.
    cur = conn.execute(
        """
        SELECT canonical_id, alias
          FROM am_alias
         WHERE entity_table = 'am_entities'
           AND alias_kind IN
                ('canonical', 'abbreviation', 'kana', 'legacy', 'partial')
        """
    )
    alias_added = 0
    for row in cur:
        cid = row["canonical_id"]
        kind = canonical_kinds.get(cid)
        if kind is None:
            continue  # alias for non-matrix entity
        out[kind].append((cid, row["alias"]))
        alias_added += 1

    for kind, rows in out.items():
        sys.stderr.write(f"      kind={kind}: {len(rows):,} candidates (incl aliases)\n")
    sys.stderr.write(
        f"      added {alias_added:,} alias rows; "
        f"skipped {skipped:,} non-matrix entities of matching kind\n"
    )
    return out


def load_uni_population(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return distinct (UNI_id, primary_name) pairs for every UNI-* id
    that appears in jpi_adoption_records.program_id. We scope the
    fuzzy work to UNI ids that actually drive matrix lookups."""
    sys.stderr.write("[3/5] Loading UNI- population from adoption records...\n")
    cur = conn.execute(
        """
        SELECT DISTINCT a.program_id AS uni_id, p.primary_name
          FROM jpi_adoption_records a
          JOIN jpi_programs p ON p.unified_id = a.program_id
         WHERE a.program_id LIKE 'UNI-%'
        """
    )
    rows: list[tuple[str, str]] = [
        (r["uni_id"], r["primary_name"]) for r in cur if r["primary_name"]
    ]
    sys.stderr.write(f"      {len(rows):,} UNI- ids with primary_name in adoption set\n")
    return rows


def fuzzy_bridge(
    uni_rows: list[tuple[str, str]],
    candidates: dict[str, list[tuple[str, str]]],
    threshold: float,
) -> list[tuple[str, str, str, float]]:
    """Yield (uni_id, am_id, bridge_kind='fuzzy_name', confidence)
    tuples for every (uni_id, am_entity) pair scoring >= threshold via
    rapidfuzz.WRatio (a Jaro-Winkler/token-set blend)."""
    sys.stderr.write(
        f"[4/5] Fuzzy matching ({len(uni_rows):,} UNI x "
        f"{sum(len(v) for v in candidates.values()):,} matrix candidates) "
        f"threshold={threshold:.2f}...\n"
    )
    t0 = time.time()
    edges: list[tuple[str, str, str, float]] = []
    threshold_pct = threshold * 100.0

    # Build a single flat candidate list with index -> (am_id, kind).
    flat_names: list[str] = []
    flat_meta: list[tuple[str, str]] = []  # (am_id, record_kind)
    for kind, rows in candidates.items():
        for cid, name in rows:
            flat_names.append(name)
            flat_meta.append((cid, kind))

    for i, (uni_id, uni_name) in enumerate(uni_rows):
        # process.extract returns top matches; we keep ALL above threshold.
        # score_cutoff prunes the pool inside C, not in Python.
        results = process.extract(
            uni_name,
            flat_names,
            scorer=fuzz.WRatio,
            score_cutoff=threshold_pct,
            limit=50,  # plenty of slack; matrix has ~50k pool
        )
        for _matched_name, score, idx in results:
            am_id, _kind = flat_meta[idx]
            edges.append((uni_id, am_id, "fuzzy_name", score / 100.0))

        if (i + 1) % 1000 == 0:
            sys.stderr.write(
                f"      progress {i + 1:,}/{len(uni_rows):,} "
                f"({(i + 1) * 100 / len(uni_rows):.1f}%) "
                f"elapsed {time.time() - t0:.1f}s\n"
            )

    sys.stderr.write(f"      generated {len(edges):,} fuzzy edges in {time.time() - t0:.1f}s\n")
    return edges


def exact_bridge_from_eim(
    conn: sqlite3.Connection,
) -> list[tuple[str, str, str, float]]:
    """Mirror entity_id_map into am_id_bridge as bridge_kind='exact'."""
    sys.stderr.write("[*] Loading exact bridge from entity_id_map...\n")
    cur = conn.execute("SELECT jpi_unified_id, am_canonical_id, confidence FROM entity_id_map;")
    edges: list[tuple[str, str, str, float]] = []
    for row in cur:
        # Confidence in entity_id_map can exceed 1.0 in legacy rows; clamp.
        conf = float(row["confidence"])
        if conf > 1.0:
            conf = 1.0
        if conf < 0.0:
            conf = 0.0
        edges.append((row["jpi_unified_id"], row["am_canonical_id"], "exact", conf))
    sys.stderr.write(f"      {len(edges):,} exact edges loaded\n")
    return edges


def write_bridge(
    conn: sqlite3.Connection,
    edges: Iterable[tuple[str, str, str, float]],
    dry_run: bool,
) -> int:
    """Write edges via INSERT OR REPLACE. Returns count written."""
    if dry_run:
        sys.stderr.write("[dry-run] skipping writes\n")
        return 0

    sys.stderr.write("[5/5] Writing am_id_bridge...\n")
    n = 0
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR REPLACE INTO am_id_bridge
            (id_a, id_b, bridge_kind, confidence)
        VALUES (?, ?, ?, ?)
        """,
        edges,
    )
    n = cur.rowcount
    conn.commit()
    sys.stderr.write(f"      wrote {n:,} rows\n")
    return n


def report(conn: sqlite3.Connection) -> None:
    """Print bridge_kind histogram + samples + W22-6 top-15 verification."""
    sys.stderr.write("\n=== am_id_bridge report ===\n")

    # Per-kind counts
    cur = conn.execute(
        "SELECT bridge_kind, COUNT(*) AS n FROM am_id_bridge GROUP BY bridge_kind ORDER BY n DESC;"
    )
    sys.stderr.write("bridge_kind histogram:\n")
    total = 0
    for row in cur:
        sys.stderr.write(f"  {row['bridge_kind']:18s} {row['n']:>10,}\n")
        total += row["n"]
    sys.stderr.write(f"  {'TOTAL':18s} {total:>10,}\n\n")

    # Sample 5 of each kind
    for kind in ("exact", "fuzzy_name"):
        sys.stderr.write(f"sample bridge_kind={kind}:\n")
        cur = conn.execute(
            "SELECT id_a, id_b, confidence FROM am_id_bridge WHERE bridge_kind = ? LIMIT 5;",
            (kind,),
        )
        for row in cur:
            sys.stderr.write(
                f"  {row['id_a']:30s} -> {row['id_b']:60s} conf={row['confidence']:.3f}\n"
            )
        sys.stderr.write("\n")

    # W22-6 verification: top 15 (UNI-A, UNI-B) combos must now be
    # matrix-mappable through the bridge.
    sys.stderr.write("W22-6 top-15 combo matrix-mappability check:\n")
    cur = conn.execute(
        """
        WITH top15 AS (
            SELECT a1.program_id AS uni_a, a2.program_id AS uni_b,
                   COUNT(*) AS n
              FROM jpi_adoption_records a1
              JOIN jpi_adoption_records a2
                ON a1.houjin_bangou = a2.houjin_bangou
               AND a1.program_id < a2.program_id
             WHERE a1.program_id LIKE 'UNI-%'
               AND a2.program_id LIKE 'UNI-%'
             GROUP BY a1.program_id, a2.program_id
             ORDER BY n DESC
             LIMIT 15
        )
        SELECT t.uni_a, t.uni_b, t.n,
               EXISTS (
                 SELECT 1
                   FROM am_id_bridge ba
                   JOIN am_id_bridge bb
                     ON ba.id_a = t.uni_a
                    AND bb.id_a = t.uni_b
                   JOIN am_compat_matrix m
                     ON (m.program_a_id = ba.id_b AND m.program_b_id = bb.id_b)
                     OR (m.program_a_id = bb.id_b AND m.program_b_id = ba.id_b)
               ) AS matrix_mappable
          FROM top15 t;
        """
    )
    mapped = 0
    rows = list(cur)
    for row in rows:
        flag = "OK" if row["matrix_mappable"] else "--"
        if row["matrix_mappable"]:
            mapped += 1
        sys.stderr.write(f"  [{flag}] {row['uni_a']} x {row['uni_b']} co-adopt={row['n']:,}\n")
    sys.stderr.write(
        f"\n  -> {mapped}/{len(rows)} top combos now matrix-mappable via am_id_bridge\n"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Path to autonomath.db (default: ./autonomath.db)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="rapidfuzz WRatio threshold (0..1, default 0.85)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute edges and report but do not write to am_id_bridge",
    )
    args = p.parse_args()

    if not (0.0 < args.threshold <= 1.0):
        sys.stderr.write("ERROR: --threshold must be in (0, 1]\n")
        return 2

    conn = open_db(args.db)
    try:
        ensure_table(conn)
        matrix_ids = load_matrix_ids(conn)
        candidates = load_matrix_candidates(conn, matrix_ids)
        uni_rows = load_uni_population(conn)

        edges_exact = exact_bridge_from_eim(conn)
        edges_fuzzy = fuzzy_bridge(uni_rows, candidates, args.threshold)

        # Dedup: if (id_a,id_b) appears in both exact and fuzzy, exact wins.
        seen: dict[tuple[str, str], tuple[str, str, str, float]] = {}
        for edge in edges_exact:
            seen[(edge[0], edge[1])] = edge
        for edge in edges_fuzzy:
            key = (edge[0], edge[1])
            if key not in seen:
                seen[key] = edge

        all_edges = list(seen.values())
        sys.stderr.write(f"\n      total unique edges (exact+fuzzy): {len(all_edges):,}\n")
        write_bridge(conn, all_edges, args.dry_run)
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
