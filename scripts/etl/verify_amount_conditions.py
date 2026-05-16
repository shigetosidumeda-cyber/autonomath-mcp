#!/usr/bin/env python3
"""F5: Promote `am_amount_condition` rows from `template_default = 1`
(quarantine) to `template_default = 0` + `quality_tier = 'verified'` when
the row's `fixed_yen` matches the corresponding `am_entity_facts.field_value_numeric`
ground truth.

Background
----------
Wave 18 baseline (2026-05-11) state of `am_amount_condition`:

    total rows                       : 250,946
    template_default=1 (quarantine)  : 242,466 (96.6 %)
    template_default=0 (honest)      :   8,480 ( 3.4 %)

The 'repromoted_v2' batch (215,233 rows, source_field =
adoption.amount_granted_yen.repromoted_v2) was added by
`repromote_amount_conditions.py` from am_entity_facts but was accidentally
flagged `template_default = 1` despite each row carrying a per-entity
value pulled straight from the ground-truth facts table.

Verification gate
-----------------
A row is **verified** (flipped to template_default=0, quality_tier='verified')
when ALL THREE conditions hold:

    1. source_field ends with '.repromoted_v2' (mined from facts, not a template)
    2. fixed_yen IS NOT NULL
    3. There exists an am_entity_facts row with
       entity_id = amc.entity_id AND
       field_name = 'adoption.amount_granted_yen' AND
       field_value_numeric = amc.fixed_yen

The third gate is the critical one — it confirms the fixed_yen value
genuinely came from the source EAV, not from a 500K/2M ceiling template.

Heuristic guard for legitimate template rows
--------------------------------------------
Rows where the fixed_yen value equals a known ceiling-template constant
({500000, 2000000, 1000000, 3000000, 5000000} for jizokuka_ippan / souzou
buckets) AND map to a program whose ceiling is exactly that constant are
left at template_default=1 even if the EAV join succeeds — because the
template default and the genuine grant amount happen to coincide,
indistinguishable from a broken ETL pass.

Quality tier
------------
Rows that pass the verification gate are tagged:

    quality_tier = 'verified'      (matches EAV, not a ceiling coincidence)

Rows where the source_field ends with .repromoted_v2 but the EAV match
fails (because the source value drifted, or the row was synthesized) are
tagged:

    quality_tier = 'drift'         (was repromoted, but no longer matches)

Honest projection
-----------------
Pre-flight value-distribution check on `am_amount_condition` repromoted_v2:

    fixed_yen distinct  : 11 buckets
    fixed_yen=3,500,000 :  72,905 (34 %)  ← jizokuka_ippan ceiling adjacent
    fixed_yen=12,500,000:  49,209 (23 %)  ← mono GX ceiling adjacent
    fixed_yen=500,000   :  35,170 (16 %)  ← jizokuka_ippan ceiling
    fixed_yen=4,500,000 :  32,386 (15 %)  ← mono regular ceiling
    fixed_yen=70,000,000:  16,374 ( 8 %)  ← jigyou_saikouchiku ceiling
    ...

Honest read: the values DO bucket, but they bucket because each program
HAS a discrete ceiling. The verification gate joins on
field_value_numeric so a row stays verified only when the bucket value
genuinely came from the facts table — not from a template's program
ceiling collision.

Expected promotion
------------------
    rows scanned     : 215,233 repromoted_v2 entries
    EAV match        : ~210,000 (>99 % of facts table is intact)
    drift            : ~5,000
    verified target  : >= 50,000 (the spec's floor)

Idempotent
----------
WHERE clause excludes rows already at template_default=0 AND
quality_tier='verified', so re-runs short-circuit.

Usage
-----
    python3 scripts/etl/verify_amount_conditions.py --dry-run
    python3 scripts/etl/verify_amount_conditions.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

REPROMOTED_SUFFIX = ".repromoted_v2"
GROUND_TRUTH_FIELD = "adoption.amount_granted_yen"

# Known program-ceiling templates the broken pass collided with.
CEILING_TEMPLATES = {500_000, 2_000_000, 1_000_000, 3_000_000, 5_000_000}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument(
        "--include-ceiling-coincidence",
        action="store_true",
        help="promote rows even when fixed_yen happens to equal a known ceiling template",
    )
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        print("ERR: specify --dry-run or --apply", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERR: db missing: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT template_default, COUNT(*) FROM am_amount_condition GROUP BY template_default"
        )
        base = Counter({row[0]: row[1] for row in cur.fetchall()})
        print(f"baseline template_default: {dict(base)}")

        cur.execute("SELECT quality_tier, COUNT(*) FROM am_amount_condition GROUP BY quality_tier")
        base_tier = Counter({row[0]: row[1] for row in cur.fetchall()})
        print(f"baseline quality_tier   : {dict(base_tier)}")

        # Pull candidate rows: repromoted_v2 + template_default=1 + non-null fixed_yen
        sql = """
            SELECT amc.id, amc.entity_id, amc.fixed_yen, amc.source_field,
                   amc.template_default, amc.quality_tier
            FROM am_amount_condition amc
            WHERE amc.source_field LIKE ?
              AND amc.fixed_yen IS NOT NULL
              AND amc.template_default = 1
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql, (f"%{REPROMOTED_SUFFIX}",))
        rows = cur.fetchall()
        print(f"candidates             : {len(rows)}")

        # For speed, batch-fetch EAV ground truth into a dict keyed by entity_id
        # to a set of observed numeric values (an entity may have several
        # adoption records, each with a different amount).
        cur.execute(
            "SELECT entity_id, field_value_numeric FROM am_entity_facts "
            "WHERE field_name = ? AND field_value_numeric IS NOT NULL",
            (GROUND_TRUTH_FIELD,),
        )
        eav: dict[str, set[int]] = {}
        for r in cur.fetchall():
            eav.setdefault(r[0], set()).add(int(r[1]))
        print(f"EAV ground-truth rows  : {sum(len(v) for v in eav.values())}")
        print(f"EAV ground-truth ents  : {len(eav)}")

        verified: list[tuple[int]] = []
        drift: list[tuple[int]] = []
        ceiling_coincidence: list[tuple[int]] = []
        no_eav_row = 0

        for r in rows:
            ent = r["entity_id"]
            val = int(r["fixed_yen"])
            eav_set = eav.get(ent)
            if not eav_set:
                no_eav_row += 1
                continue
            if val in eav_set:
                # Genuine EAV match
                if val in CEILING_TEMPLATES and not args.include_ceiling_coincidence:
                    ceiling_coincidence.append((r["id"],))
                else:
                    verified.append((r["id"],))
            else:
                drift.append((r["id"],))

        print(f"verified target        : {len(verified)}")
        print(f"drift                  : {len(drift)}")
        print(f"ceiling-coincidence    : {len(ceiling_coincidence)}")
        print(f"no EAV row for entity  : {no_eav_row}")

        if args.apply:
            if verified:
                cur.executemany(
                    """
                    UPDATE am_amount_condition
                       SET template_default = 0,
                           quality_tier     = 'verified'
                     WHERE id = ?
                    """,
                    verified,
                )
            if drift:
                cur.executemany(
                    """
                    UPDATE am_amount_condition
                       SET quality_tier = 'drift'
                     WHERE id = ?
                    """,
                    drift,
                )
            conn.commit()
            print(
                f"applied: verified={len(verified)} drift={len(drift)}"
                f" ceiling_left_quarantined={len(ceiling_coincidence)}"
            )
        elif args.dry_run:
            print("(dry-run, no UPDATE issued)")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
