#!/usr/bin/env python3
"""W21-2 zero-source quarantine sweep (2026-05-05).

Wave 21-2 cross-source verification audit found programs whose
`verification_count = 0` after the canonical first-party host
classifier ran. Two passes happen:

1. **Repair (already done in `populate_cross_source_verification.py`):**
   the host classifier is extended to recognise additional first-party
   hosts that had genuine gaps — `g-reiki.net` 例規 hosting, JAXA
   funding, 持続化補助金 official portals, 政府系金融 sites
   (商工中金 / 信金中金 / DBJ), JAバンク全国, plus a small whitelist
   of legacy `<municipality>.jp` hosts. Re-running the populator
   recovers the rows automatically.

2. **Quarantine (this script):** anything *still* zero-source after
   the populator extension cannot be safely surfaced — the citation
   is either missing entirely (`source_url IS NULL`), an aggregator
   (`hojyokin-portal`, `noukaweb`, …), a foundation grant page, a
   crowdfunding page, or a foreign / commercial site. We flip
   `audit_quarantined = 1` with a stable reason label so search
   surfaces (REST, MCP, generated SEO pages, llms.txt) can AND it
   into their existing `excluded = 0 AND tier IN ('S','A','B','C')`
   filter.

Idempotency
-----------
Re-running is a no-op for already-quarantined rows (timestamp is
preserved). Newly-zero rows pick up the flag; rows that recover
verification on a later populate pass are NOT auto-released — that
must be a deliberate downgrade reversal step (see `--release` flag).

Usage
-----
    python scripts/etl/quarantine_zero_source_programs.py --dry-run
    python scripts/etl/quarantine_zero_source_programs.py --apply
    python scripts/etl/quarantine_zero_source_programs.py --release  # un-flag rows that now have v_count >= 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"

QUARANTINE_REASON = "w21_2_zero_source_unrecoverable"

_LOG = logging.getLogger("jpcite.quarantine_zero_source_programs")


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def find_zero_source(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT unified_id, primary_name, source_url, tier,
               authority_level, prefecture, audit_quarantined
          FROM programs
         WHERE verification_count = 0
        """
    ).fetchall()


def find_recovered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows that were quarantined but now have verification_count >= 1."""
    return conn.execute(
        """
        SELECT unified_id, primary_name, verification_count
          FROM programs
         WHERE audit_quarantined = 1
           AND verification_count >= 1
        """
    ).fetchall()


def apply_quarantine(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    reason: str = QUARANTINE_REASON,
) -> int:
    """Flip audit_quarantined=1 for rows that aren't already flagged."""
    now = datetime.now(UTC).isoformat()
    new_flags = [r for r in rows if not r["audit_quarantined"]]
    with conn:
        conn.executemany(
            """
            UPDATE programs
               SET audit_quarantined = 1,
                   audit_quarantined_reason = ?,
                   audit_quarantined_at = ?
             WHERE unified_id = ?
               AND audit_quarantined = 0
            """,
            [(reason, now, r["unified_id"]) for r in new_flags],
        )
    return len(new_flags)


def release_recovered(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
) -> int:
    """Un-flag rows that now have verification_count >= 1."""
    with conn:
        conn.executemany(
            """
            UPDATE programs
               SET audit_quarantined = 0,
                   audit_quarantined_reason = NULL,
                   audit_quarantined_at = NULL
             WHERE unified_id = ?
               AND audit_quarantined = 1
               AND verification_count >= 1
            """,
            [(r["unified_id"],) for r in rows],
        )
    return len(rows)


def distribution(rows: list[sqlite3.Row]) -> dict[str, Any]:
    tier_counter: Counter[str] = Counter()
    auth_counter: Counter[str] = Counter()
    has_url = 0
    for r in rows:
        tier_counter[r["tier"] or "(null)"] += 1
        auth_counter[r["authority_level"] or "(null)"] += 1
        if r["source_url"] and str(r["source_url"]).strip():
            has_url += 1
    return {
        "total_zero_source": len(rows),
        "by_tier": dict(sorted(tier_counter.items())),
        "by_authority_level": dict(sorted(auth_counter.items())),
        "with_source_url": has_url,
        "without_source_url": len(rows) - has_url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=JPINTEL_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument(
        "--release",
        action="store_true",
        help="Un-flag rows that have recovered verification_count >= 1",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reason", default=QUARANTINE_REASON)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with _connect(args.db) as conn:
        zero_rows = find_zero_source(conn)
        dist = distribution(zero_rows)
        recovered_rows = find_recovered(conn) if args.release else []

        flagged = 0
        released = 0
        if args.apply:
            flagged = apply_quarantine(conn, zero_rows, reason=args.reason)
        if args.release:
            released = release_recovered(conn, recovered_rows)

        # Always re-read after writes so the report is post-state honest.
        post_zero = find_zero_source(conn)
        already_flagged = sum(1 for r in post_zero if r["audit_quarantined"])

    result = {
        "mode": ("apply" if args.apply else "release" if args.release else "dry_run"),
        "db": str(args.db),
        "zero_source_distribution": dist,
        "newly_flagged": flagged,
        "released": released,
        "already_flagged_after_run": already_flagged,
        "generated_at": datetime.now(UTC).isoformat(),
        "reason": args.reason,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"mode={result['mode']}")
        print(f"db={result['db']}")
        print(f"zero_source_total={dist['total_zero_source']}")
        print(f"  with_source_url={dist['with_source_url']}")
        print(f"  without_source_url={dist['without_source_url']}")
        print("by_tier:")
        for k, v in dist["by_tier"].items():
            print(f"  {k}: {v}")
        print("by_authority_level:")
        for k, v in dist["by_authority_level"].items():
            print(f"  {k}: {v}")
        print(f"newly_flagged={flagged}")
        print(f"released={released}")
        print(f"already_flagged_after_run={already_flagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
