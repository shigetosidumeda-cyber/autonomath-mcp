"""Reconcile programs_fts with programs.

Cleans drift between programs and programs_fts so search results obey the
canonical filter (tier IN ('S','A','B','C') AND excluded=0). Runs in three
phases:

  1. Delete FTS rows for tier='X' or excluded=1 programs (leaked quarantine).
  2. Insert FTS rows for searchable programs missing from FTS (lost during
     legacy ingest paths that forgot to write to programs_fts).
  3. Delete FTS rows whose unified_id no longer exists in programs (orphans).

Idempotent. Safe to run repeatedly.

History
-------
2026-04-25 first run: -2,031 leaked + 293 added + 21 orphans removed → exact
parity (11,547 fts == 11,547 searchable).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "jpintel.db"


def reconcile(db_path: Path, dry_run: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        before = conn.execute("SELECT COUNT(*) FROM programs_fts").fetchone()[0]

        leaked = conn.execute(
            """SELECT COUNT(*) FROM programs_fts f
               JOIN programs p ON f.unified_id = p.unified_id
               WHERE p.tier='X' OR p.excluded=1"""
        ).fetchone()[0]

        missing = conn.execute(
            """SELECT COUNT(*) FROM programs p
               WHERE p.tier IN ('S','A','B','C') AND p.excluded=0
                 AND NOT EXISTS (SELECT 1 FROM programs_fts f
                                 WHERE f.unified_id = p.unified_id)"""
        ).fetchone()[0]

        orphans = conn.execute(
            """SELECT COUNT(*) FROM programs_fts f
               WHERE NOT EXISTS (SELECT 1 FROM programs p
                                 WHERE p.unified_id = f.unified_id)"""
        ).fetchone()[0]

        if dry_run:
            return {
                "before": before,
                "leaked": leaked,
                "missing": missing,
                "orphans": orphans,
                "after": before,
            }

        with conn:
            conn.execute(
                """DELETE FROM programs_fts
                   WHERE unified_id IN (
                       SELECT unified_id FROM programs
                       WHERE tier='X' OR excluded=1
                   )"""
            )
            conn.execute(
                """INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text)
                   SELECT unified_id,
                          primary_name,
                          COALESCE(aliases_json, ''),
                          COALESCE(primary_name, '') || ' '
                              || COALESCE(authority_name, '') || ' '
                              || COALESCE(prefecture, '') || ' '
                              || COALESCE(municipality, '')
                   FROM programs
                   WHERE tier IN ('S','A','B','C') AND excluded=0
                     AND NOT EXISTS (SELECT 1 FROM programs_fts f
                                     WHERE f.unified_id = programs.unified_id)"""
            )
            conn.execute(
                """DELETE FROM programs_fts
                   WHERE unified_id NOT IN (SELECT unified_id FROM programs)"""
            )

        after = conn.execute("SELECT COUNT(*) FROM programs_fts").fetchone()[0]
        return {
            "before": before,
            "leaked": leaked,
            "missing": missing,
            "orphans": orphans,
            "after": after,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"[error] DB not found: {args.db}", file=sys.stderr)
        return 1

    stats = reconcile(args.db, dry_run=args.dry_run)
    verb = "would adjust" if args.dry_run else "adjusted"
    print(f"programs_fts {verb}:")
    print(f"  before:  {stats['before']:,}")
    print(f"  leaked:  -{stats['leaked']:,}  (tier=X or excluded=1)")
    print(f"  missing: +{stats['missing']:,}  (searchable rows not indexed)")
    print(f"  orphans: -{stats['orphans']:,}  (FTS rows whose program is gone)")
    if not args.dry_run:
        print(f"  after:   {stats['after']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
