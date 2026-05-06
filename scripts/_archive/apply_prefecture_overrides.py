"""Apply prefecture walker overrides to the programs table.

Reads data/autonomath/prefecture_overrides.json (written by prefecture_walker.py)
and UPDATEs programs.prefecture for rows where prefecture IS NULL and the
override confidence is at or above --min-confidence (default 0.90).

Safe to re-run. Does not touch rows that already have a prefecture set.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from jpintel_mcp.config import settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(settings.db_path))
    ap.add_argument(
        "--overrides",
        default=str(
            Path(__file__).resolve().parents[1]
            / "data"
            / "autonomath"
            / "prefecture_overrides.json"
        ),
    )
    ap.add_argument("--min-confidence", type=float, default=0.90)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    overrides_path = Path(args.overrides)
    if not overrides_path.exists():
        print(f"overrides file not found: {overrides_path}", file=sys.stderr)
        return 1

    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    print(f"loaded {len(overrides)} overrides from {overrides_path}")

    eligible = [
        (uid, o["prefecture"], o.get("source", ""), o.get("confidence", 0.0))
        for uid, o in overrides.items()
        if o.get("confidence", 0.0) >= args.min_confidence and o.get("prefecture")
    ]
    print(f"{len(eligible)} eligible at confidence >= {args.min_confidence}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        (before_null,) = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE prefecture IS NULL"
        ).fetchone()

        applied = 0
        skipped_nonnull = 0
        by_source: dict[str, int] = {}
        for uid, pref, source, _conf in eligible:
            row = conn.execute(
                "SELECT prefecture FROM programs WHERE unified_id = ?", (uid,)
            ).fetchone()
            if row is None:
                continue
            if row["prefecture"] is not None:
                skipped_nonnull += 1
                continue
            if args.dry_run:
                applied += 1
            else:
                conn.execute(
                    "UPDATE programs SET prefecture = ? WHERE unified_id = ?",
                    (pref, uid),
                )
                applied += 1
            by_source[source] = by_source.get(source, 0) + 1

        if not args.dry_run:
            conn.commit()

        (after_null,) = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE prefecture IS NULL"
        ).fetchone()
        (total,) = conn.execute("SELECT COUNT(*) FROM programs").fetchone()

        print()
        print(f"before null: {before_null} / {total} ({before_null / total:.1%})")
        print(f"applied:     {applied}")
        print(f"skipped (already had prefecture): {skipped_nonnull}")
        print(f"after null:  {after_null} / {total} ({after_null / total:.1%})")
        print()
        print("by source:")
        for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {src:30s} {n}")
        if args.dry_run:
            print("\n[DRY RUN — no changes committed]")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
