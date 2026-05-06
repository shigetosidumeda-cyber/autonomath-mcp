"""Wave 17 noise-duplicate consolidation for programs table.

Scope:
    Detect and merge "noise" duplicates in jpintel.db `programs` table —
    rows that share (primary_name, prefecture, source_url) and therefore
    represent the same upstream program ingested twice (or more).

Out of scope:
    * Legitimate per-prefecture variants (same name, different prefecture)
      are kept as-is — these are 47 県別 programs that should stay split.
    * Ambiguous duplicates (same name+pref, different source_url) are
      written to data/duplicate_review_queue.jsonl for manual triage and
      NOT auto-merged.

Algorithm:
    1. For each (primary_name, prefecture, source_url) cluster of size > 1:
       - Pick the "winner" row by tier priority (S > A > B > C > X) then
         latest source_fetched_at, then lexicographically smallest
         unified_id (deterministic tie-break).
       - For all losers: set excluded=1, exclusion_reason='duplicate_merged'.
       - On the winner: set merged_from = JSON array of loser unified_ids.
    2. Refresh programs_fts via the existing rebuild script to drop
       merged-out rows from the search index.
    3. Run inside a single transaction so failure rolls back cleanly.

Coordinates with Wave 18 (tier_x quarantine) on the literal exclusion_reason
value 'duplicate_merged' — keep this string in sync.

Usage:
    python scripts/dedup_programs_wave17.py --dry-run   # report only
    python scripts/dedup_programs_wave17.py --apply     # mutate DB
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jpintel.db"
REVIEW_QUEUE_PATH = Path(__file__).resolve().parent.parent / "data" / "duplicate_review_queue.jsonl"
EXCLUSION_REASON = "duplicate_merged"  # Wave 18 coordination

TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4, None: 5, "": 5}


def winner_key(row: dict) -> tuple:
    """Sort key for picking the survivor; lower wins."""
    return (
        TIER_RANK.get(row.get("tier"), 99),
        # negate timestamp so newer wins (string sort works for ISO-8601)
        -ord(row.get("source_fetched_at", "")[:1] or "\x00"),
        # primary tie-break: latest fetched_at (descending → invert via reverse)
        # Use reverse=False with negated indicator below
        row.get("source_fetched_at") or "",
        row.get("unified_id", ""),
    )


def pick_winner(rows: list[dict]) -> dict:
    """Pick survivor: highest tier, latest source_fetched_at, smallest uid."""

    def key(r: dict) -> tuple:
        tier_rank = TIER_RANK.get(r.get("tier"), 99)
        # Higher fetched_at is better → invert by using negative comparison
        # Trick: pair (tier_rank, -fetched_lex_ord) won't work for strings.
        # Use a tuple with a reversed string sort: easiest is to sort and pick.
        return (tier_rank, r.get("source_fetched_at") or "", r.get("unified_id", ""))

    # Lower tier_rank = better. Newer fetched_at = better. Smaller uid = better.
    # Sort: tier ascending, fetched_at descending, uid ascending.
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            TIER_RANK.get(r.get("tier"), 99),
            # We want newest first — Python sort is stable; multi-pass:
        ),
    )
    # Tie-break with multiple stable sorts (cleaner than custom cmp).
    sorted_rows.sort(key=lambda r: r.get("unified_id") or "")  # uid ascending
    sorted_rows.sort(
        key=lambda r: r.get("source_fetched_at") or "", reverse=True
    )  # fetched_at descending
    sorted_rows.sort(key=lambda r: TIER_RANK.get(r.get("tier"), 99))  # tier ascending
    return sorted_rows[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually mutate DB")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report counts without mutating (default)",
    )
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        args.dry_run = True

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Verify merged_from column exists
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(programs)").fetchall()]
    if "merged_from" not in cols:
        print(
            "ERROR: programs.merged_from column missing — apply migration 074 first.",
            file=sys.stderr,
        )
        return 1

    print(f"DB: {DB_PATH}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    # ---- Step 1: classify duplicates ----
    rows = conn.execute(
        """
        SELECT unified_id, primary_name, prefecture, source_url,
               tier, source_fetched_at
        FROM programs
        WHERE excluded = 0
          AND primary_name IN (
              SELECT primary_name FROM programs
              WHERE excluded = 0
              GROUP BY primary_name
              HAVING COUNT(*) > 1
          )
        """
    ).fetchall()

    by_name = defaultdict(list)
    for r in rows:
        by_name[r["primary_name"]].append(dict(r))

    name_collision_groups = len(by_name)
    name_collision_extra_rows = sum(len(v) - 1 for v in by_name.values())

    # noise: same name + same pref + same url
    noise_clusters = defaultdict(list)
    # ambiguous: same name + same pref + diff url
    pref_groups = defaultdict(list)
    for name, group in by_name.items():
        for r in group:
            pref_groups[(name, r.get("prefecture") or "")].append(r)
    for (name, pref), prows in pref_groups.items():
        if len(prows) <= 1:
            continue
        url_clusters = defaultdict(list)
        for r in prows:
            url_clusters[r.get("source_url") or ""].append(r)
        # noise per (name, pref, url) where cluster size > 1
        for url, urows in url_clusters.items():
            if len(urows) > 1:
                noise_clusters[(name, pref, url)].extend(urows)
        # ambiguous if multiple url clusters within same (name, pref)
        if len(url_clusters) > 1:
            # Already covered above; record for review queue.
            pass

    noise_groups = len(noise_clusters)
    noise_extra_rows = sum(len(v) - 1 for v in noise_clusters.values())

    # ambiguous list
    ambiguous_records = []
    for (name, pref), prows in pref_groups.items():
        url_set = {r.get("source_url") or "" for r in prows}
        if len(url_set) > 1 and len(prows) > 1:
            ambiguous_records.append(
                {
                    "primary_name": name,
                    "prefecture": pref,
                    "uids": sorted(r["unified_id"] for r in prows),
                    "prefectures": [r.get("prefecture") for r in prows],
                    "source_urls": sorted({r.get("source_url") or "" for r in prows}),
                    "tiers": sorted({r.get("tier") for r in prows if r.get("tier")}),
                    "verdict_needed": "manual",
                }
            )

    ambiguous_groups = len(ambiguous_records)
    ambiguous_extra = sum(len(r["uids"]) - 1 for r in ambiguous_records)

    # legit: same name with multiple distinct prefectures (per-pref variants)
    legit_groups = 0
    for name, group in by_name.items():
        prefs = {r.get("prefecture") or "" for r in group}
        if len(prefs) > 1:
            legit_groups += 1

    print()
    print(f"  name_collision_groups:    {name_collision_groups}")
    print(f"  name_collision_extra:     {name_collision_extra_rows}")
    print(f"  noise_groups (auto-merge): {noise_groups}")
    print(f"  noise_extra_rows (drop):   {noise_extra_rows}")
    print(f"  ambiguous_groups (manual): {ambiguous_groups}")
    print(f"  ambiguous_extra_rows:      {ambiguous_extra}")
    print(f"  legitimate_per_pref_groups: {legit_groups}")

    # ---- Step 2: write review queue (always, even on dry-run) ----
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_QUEUE_PATH.open("w", encoding="utf-8") as fp:
        for rec in ambiguous_records:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  review_queue: {REVIEW_QUEUE_PATH} ({ambiguous_groups} entries)")

    if not args.apply:
        print("\nDRY-RUN — no DB mutation. Re-run with --apply to merge noise.")
        conn.close()
        return 0

    # ---- Step 3: merge noise ----
    merged_count = 0
    losers_count = 0
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        for (name, pref, url), nrows in noise_clusters.items():
            winner = pick_winner(nrows)
            losers = [r for r in nrows if r["unified_id"] != winner["unified_id"]]
            loser_uids = sorted(r["unified_id"] for r in losers)
            # mark losers
            cur.executemany(
                "UPDATE programs SET excluded=1, exclusion_reason=? "
                "WHERE unified_id=? AND excluded=0",
                [(EXCLUSION_REASON, uid) for uid in loser_uids],
            )
            losers_count += len(loser_uids)
            # write merged_from on winner (merge with existing if any)
            existing = cur.execute(
                "SELECT merged_from FROM programs WHERE unified_id=?",
                (winner["unified_id"],),
            ).fetchone()
            existing_uids: list[str] = []
            if existing and existing[0]:
                try:
                    parsed = json.loads(existing[0])
                    if isinstance(parsed, list):
                        existing_uids = [str(x) for x in parsed]
                except json.JSONDecodeError:
                    pass
            combined = sorted(set(existing_uids) | set(loser_uids))
            cur.execute(
                "UPDATE programs SET merged_from=? WHERE unified_id=?",
                (json.dumps(combined, ensure_ascii=False), winner["unified_id"]),
            )
            merged_count += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: rollback due to {exc!r}", file=sys.stderr)
        conn.close()
        return 2

    print(f"\n  merged_winners: {merged_count}")
    print(f"  loser_rows_excluded: {losers_count}")

    # ---- Step 4: post-state verification ----
    post = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE excluded=1 AND exclusion_reason=?",
        (EXCLUSION_REASON,),
    ).fetchone()[0]
    remaining = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT 1 FROM programs WHERE excluded=0
          GROUP BY primary_name, COALESCE(prefecture,''), COALESCE(source_url,'')
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    print(f"  rows now flagged duplicate_merged: {post}")
    print(f"  remaining noise clusters (should be 0): {remaining}")

    conn.close()
    print("\nDONE — remember to rebuild programs_fts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
