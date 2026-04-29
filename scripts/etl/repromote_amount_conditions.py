#!/usr/bin/env python3
"""Re-promote adoption.amount_granted_yen facts into am_amount_condition with
template_default = 0 (honest), distinguishable from the quarantined
template-default rows that migration 078 flagged with template_default = 1.

Background:
    Phantom-moat audit (2026-04-29) found 27,233 / 35,713 (76%) rows in
    am_amount_condition were promoted from a single broken ETL pass that
    filled `fixed_yen` with the program-ceiling template default
    (¥500,000 for jizokuka_ippan; ¥2,000,000 for jizokuka_souzou).

    Migration 078 added the `template_default` column and flagged those
    rows = 1 in-place (quarantine, not delete — preserves audit trail).
    This script writes a parallel set of rows from the ground-truth
    am_entity_facts table so consumers filtering `template_default = 0`
    see the honest promoted set.

Read source:
    am_entity_facts WHERE field_name = 'adoption.amount_granted_yen'
    (215,337 rows on autonomath.db @ 2026-04-29; covers 215,233 distinct
    entities; per-fact provenance via am_entity_facts.id).

    The script is READ-ONLY on am_entity_facts. No DELETE / UPDATE / INSERT
    is performed against the source table.

Write target:
    am_amount_condition (entity_id, condition_label='granted',
    source_field='adoption.amount_granted_yen.repromoted_v2', ...)

    A distinct `source_field` is required because the existing UNIQUE
    INDEX `uq_am_amount_condition (entity_id, condition_label,
    source_field)` is already populated for ~27k entity_ids by the
    quarantined v1 promotion. Re-using the same source_field would
    raise UNIQUE-constraint violations on every insert. The
    `.repromoted_v2` suffix makes the lineage explicit and lets future
    audits separate v1 (broken) from v2 (re-read from facts).

NULL handling:
    am_entity_facts.field_value_numeric is NOT NULL on every observed
    row for this field today (215,337 / 215,337). The script still
    propagates NULL faithfully when present (INSERT ... fixed_yen=NULL),
    matching the spec requirement that "INSERT ... with REAL value
    (NULL where source had NULL)".

Idempotency:
    The composite UNIQUE index `(entity_id, condition_label,
    source_field)` makes `INSERT OR IGNORE` a per-row no-op on re-runs.
    Running the script twice in a row is safe; the second run reports
    inserted=0.

Honest projection (printed at end of run):
    The script prints a value-distribution summary so the operator can
    confirm whether the source `am_entity_facts` carries genuinely
    varied per-record amounts or — as the audit suspects — also clusters
    around a tiny set of program-ceiling buckets. If the source itself
    is bucketed, the re-promoted rows will be flagged in a follow-up
    pass; this script promotes verbatim.

Usage:
    python3 scripts/etl/repromote_amount_conditions.py --dry-run
    python3 scripts/etl/repromote_amount_conditions.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

SOURCE_FIELD_NEW = "adoption.amount_granted_yen.repromoted_v2"
CONDITION_LABEL = "granted"
SOURCE_FIELD_NAME = "adoption.amount_granted_yen"

# Batch size for executemany — keeps memory bounded on the 215k-row read.
BATCH_SIZE = 5_000

# Program-ceiling template-default buckets discovered by the
# 2026-04-29 phantom-moat audit. Rows where field_value_numeric falls
# in this set are program-ceiling defaults (not real per-record
# granted amounts) — am_entity_facts.field_value_numeric has only 11
# distinct values across all 215,337 facts, each one matching a known
# jizokuka / IT subsidy ceiling. We propagate the quarantine flag onto
# re-promoted rows so the honest filter `template_default = 0` shrinks
# the table to genuinely varied values (~0 today; this set acts as a
# placeholder for when the upstream PDF parser starts capturing
# per-record amounts and those amounts diverge from ceilings).
TEMPLATE_DEFAULT_BUCKETS: frozenset[int] = frozenset(
    {
        500_000,    # jizokuka_ippan ceiling (26,008 quarantined v1 rows)
        2_000_000,  # jizokuka_souzou ceiling (1,225 quarantined v1 rows)
        3_500_000,  # IT 補助金 デジタル化基盤 ceiling
        4_500_000,  # ものづくり 一般型 ceiling
        12_500_000, # IT 補助金 通常枠 ceiling
        15_000_000, # ものづくり 回復型 ceiling
        30_000_000, # 事業承継引継ぎ ceiling
        70_000_000, # ものづくり グローバル展開型 ceiling
        90_000_000, # 事業再構築 ceiling
        100_000_000, # 事業再構築 大規模賃金引上枠 ceiling
        1_500_000,  # jizokuka_ippan 賃金引上枠 ceiling
    }
)


def is_template_default(value_yen: float | None) -> int:
    """Return 1 if the value is a known program-ceiling template default,
    else 0. NULL → 0 (honest unknown, not a known bucket)."""
    if value_yen is None:
        return 0
    return 1 if int(value_yen) in TEMPLATE_DEFAULT_BUCKETS else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Re-promote adoption.amount_granted_yen facts into "
            "am_amount_condition with template_default=0 (idempotent)."
        )
    )
    p.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB))),
        help=f"Path to autonomath.db (default: {DEFAULT_DB}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read source + simulate inserts; report counts only, do not "
            "write. Mutually exclusive with --apply."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Execute the inserts (default behaviour if neither flag is set is --dry-run).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit source rows scanned (debug only). None = all.",
    )
    args = p.parse_args()
    if args.dry_run and args.apply:
        p.error("--dry-run and --apply are mutually exclusive")
    if not args.dry_run and not args.apply:
        # Default to dry-run for safety.
        args.dry_run = True
    return args


def fetch_source_facts(
    conn: sqlite3.Connection, limit: int | None
) -> list[tuple[str, float | None, int]]:
    """Return [(entity_id, field_value_numeric, fact_id), ...] from
    am_entity_facts where field_name='adoption.amount_granted_yen'.

    Read-only query. No state mutation on am_entity_facts."""
    sql = (
        "SELECT entity_id, field_value_numeric, id "
        "FROM am_entity_facts "
        "WHERE field_name = ? "
        "ORDER BY id"
    )
    params: list[object] = [SOURCE_FIELD_NAME]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cur = conn.execute(sql, params)
    return cur.fetchall()


def insert_batch(
    conn: sqlite3.Connection,
    batch: list[tuple[str, float | None, int]],
) -> int:
    """INSERT OR IGNORE a batch into am_amount_condition. Returns rows
    actually inserted (computed via changes()).

    Each row carries:
        entity_id        from source fact
        condition_label  'granted'
        fixed_yen        REAL → INTEGER cast (or NULL pass-through)
        source_field     'adoption.amount_granted_yen.repromoted_v2'
        evidence_fact_id source fact id (provenance)
        template_default 1 if value is a known program-ceiling bucket,
                         else 0 (NULL → 0 = honest unknown)
    """
    rows = [
        (
            entity_id,
            CONDITION_LABEL,
            int(value) if value is not None else None,
            SOURCE_FIELD_NEW,
            fact_id,
            is_template_default(value),
        )
        for entity_id, value, fact_id in batch
    ]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO am_amount_condition "
        "(entity_id, condition_label, fixed_yen, source_field, "
        " evidence_fact_id, template_default) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    after = conn.total_changes
    return after - before


def summarise_value_distribution(
    rows: list[tuple[str, float | None, int]],
) -> Counter:
    """Distribution of fixed_yen values across the source — proxy for
    detecting whether the source itself is bucket-defaulted."""
    return Counter(
        ("NULL" if value is None else int(value)) for _, value, _ in rows
    )


def main() -> int:
    args = parse_args()
    db_path: Path = args.db
    if not db_path.exists():
        print(f"FATAL: db not found at {db_path}", file=sys.stderr)
        return 2

    print(f"[repromote] db={db_path}")
    print(f"[repromote] mode={'apply' if args.apply else 'dry-run'}")
    print(f"[repromote] target source_field={SOURCE_FIELD_NEW}")

    conn = sqlite3.connect(str(db_path))
    try:
        # Verify migration 078 has landed (template_default column exists).
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(am_amount_condition)").fetchall()
        }
        if "template_default" not in cols:
            print(
                "FATAL: am_amount_condition.template_default missing — "
                "apply migrations/078_amount_condition_quarantine.sql first.",
                file=sys.stderr,
            )
            return 3

        # Pre-flight counts.
        (existing_repromoted,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition WHERE source_field = ?",
            [SOURCE_FIELD_NEW],
        ).fetchone()
        (quarantined,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition "
            "WHERE template_default = 1"
        ).fetchone()
        (honest_existing,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition "
            "WHERE template_default = 0"
        ).fetchone()
        print(
            f"[repromote] before: existing_repromoted_rows={existing_repromoted} "
            f"quarantined={quarantined} honest_existing={honest_existing}"
        )

        rows = fetch_source_facts(conn, args.limit)
        print(f"[repromote] source rows fetched: {len(rows):,}")

        dist = summarise_value_distribution(rows)
        print("[repromote] source value distribution (top 10):")
        for value, count in dist.most_common(10):
            print(f"           {value!r:>20}  {count:,}")

        if args.dry_run:
            # Simulate insert count: row whose (entity_id, 'granted',
            # SOURCE_FIELD_NEW) is not yet present would insert.
            existing_keys = {
                row[0]
                for row in conn.execute(
                    "SELECT entity_id FROM am_amount_condition "
                    "WHERE condition_label = ? AND source_field = ?",
                    [CONDITION_LABEL, SOURCE_FIELD_NEW],
                ).fetchall()
            }
            simulate_inserts = sum(
                1 for entity_id, _, _ in rows if entity_id not in existing_keys
            )
            # Project final flag distribution.
            simulate_template_default_1 = sum(
                1
                for entity_id, value, _ in rows
                if entity_id not in existing_keys and is_template_default(value) == 1
            )
            simulate_template_default_0 = simulate_inserts - simulate_template_default_1
            projected_honest_total = honest_existing + simulate_template_default_0
            print(
                f"[repromote] DRY-RUN would INSERT={simulate_inserts:,} "
                f"(existing={len(existing_keys):,}, "
                f"skipped_by_unique={len(rows) - simulate_inserts:,})"
            )
            print(
                f"[repromote]   of which template_default=0: "
                f"{simulate_template_default_0:,}"
            )
            print(
                f"[repromote]   of which template_default=1: "
                f"{simulate_template_default_1:,} "
                f"(known program-ceiling buckets — quarantined on insert)"
            )
            print(
                f"[repromote] PROJECTED honest total after apply "
                f"(template_default=0): {projected_honest_total:,}"
            )
            return 0

        # Apply path.
        inserted = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            inserted += insert_batch(conn, batch)
        conn.commit()

        (final_repromoted,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition WHERE source_field = ?",
            [SOURCE_FIELD_NEW],
        ).fetchone()
        (final_honest,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition WHERE template_default = 0"
        ).fetchone()
        (final_total,) = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition"
        ).fetchone()

        print(f"[repromote] APPLIED inserted={inserted:,}")
        print(
            f"[repromote] after: repromoted_rows={final_repromoted:,} "
            f"honest_total={final_honest:,} table_total={final_total:,}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
