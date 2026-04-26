#!/usr/bin/env python3
# Phase B of entity reconciliation.
# Maps remaining unmatched jpi_programs.unified_id <-> am_entities.canonical_id
# using Jaro-Winkler with prefecture-aware filtering.
#
# Phase A (exact name match) ran inline as SQL — see migration 033.
#
# Thresholds:
#   >= 0.95  auto-link (confidence = JW score)
#   >= 0.85  auto-link IF prefecture matches OR jpi prefecture is null
#   <  0.85  skip (review queue)

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "autonomath.db"

THRESHOLD_HIGH = 0.95
THRESHOLD_MID = 0.85


def extract_prefecture_from_name(name: str) -> str | None:
    if not name:
        return None
    pref_suffixes = ("都", "道", "府", "県")
    for end_pos in (3, 4, 5, 6):
        if len(name) >= end_pos and name[end_pos - 1] in pref_suffixes:
            candidate = name[:end_pos]
            if any(candidate.endswith(s) for s in pref_suffixes):
                return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = all unmatched")
    args = ap.parse_args()

    try:
        from rapidfuzz import distance, process
    except ImportError:
        print("rapidfuzz not installed. .venv/bin/pip install rapidfuzz", file=sys.stderr)
        return 2

    con = sqlite3.connect(DB)
    cur = con.cursor()

    cur.execute(
        "SELECT jp.unified_id, jp.primary_name, jp.prefecture FROM jpi_programs jp "
        "WHERE NOT EXISTS (SELECT 1 FROM entity_id_map eim WHERE eim.jpi_unified_id=jp.unified_id) "
        "AND jp.primary_name IS NOT NULL"
    )
    unmatched = cur.fetchall()
    if args.limit > 0:
        unmatched = unmatched[: args.limit]

    cur.execute(
        "SELECT canonical_id, primary_name FROM am_entities "
        "WHERE record_kind='program' AND primary_name IS NOT NULL"
    )
    am_progs = cur.fetchall()
    am_names = [a[1] for a in am_progs]
    am_id_by_name = {a[1]: a[0] for a in am_progs}

    print(f"unmatched jpi = {len(unmatched)}, am pool = {len(am_progs)}")

    high_inserts: list[tuple[str, str, str, float]] = []
    mid_inserts: list[tuple[str, str, str, float]] = []
    rejected_pref: int = 0
    skipped_low: int = 0

    t0 = time.time()
    for j_id, j_name, j_pref in unmatched:
        best = process.extractOne(
            j_name, am_names, scorer=distance.JaroWinkler.normalized_similarity
        )
        if not best:
            skipped_low += 1
            continue
        a_name, sim, _ = best
        a_id = am_id_by_name[a_name]

        if sim >= THRESHOLD_HIGH:
            high_inserts.append((j_id, a_id, "fuzzy_jw_high", float(sim)))
        elif sim >= THRESHOLD_MID:
            a_pref = extract_prefecture_from_name(a_name)
            if not j_pref or not a_pref or j_pref == a_pref:
                mid_inserts.append((j_id, a_id, "fuzzy_jw_mid", float(sim)))
            else:
                rejected_pref += 1
        else:
            skipped_low += 1

    elapsed = time.time() - t0
    print(f"matched in {elapsed:.1f}s")
    print(f"  high (>= {THRESHOLD_HIGH}): {len(high_inserts)}")
    print(f"  mid  (>= {THRESHOLD_MID}, prefecture-aware): {len(mid_inserts)}")
    print(f"  rejected (prefecture mismatch): {rejected_pref}")
    print(f"  skipped (< {THRESHOLD_MID} or no candidate): {skipped_low}")

    if args.dry_run:
        print("[dry-run] no inserts")
        return 0

    cur.executemany(
        "INSERT OR IGNORE INTO entity_id_map(jpi_unified_id, am_canonical_id, match_method, confidence) "
        "VALUES (?, ?, ?, ?)",
        high_inserts + mid_inserts,
    )
    con.commit()
    cur.execute("SELECT COUNT(*) FROM entity_id_map")
    print(f"\nentity_id_map total now: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
