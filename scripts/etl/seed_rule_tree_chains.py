"""Seed 3 canonical rule-tree CHAINS for Dim M (Wave 47).

Populates ``am_rule_tree_chain`` + ``am_rule_tree_version_history``
(mig 273) with the 3 production-grade decision pipelines that compose
the 5 Dim K trees seeded by ``seed_rule_tree_definitions.py``
(PR #152, mig 271).

Chains seeded
-------------
1.  ``subsidy_eligibility_then_gyouhou_v1``  — 補助金 → 業法 fence
2.  ``investment_then_adoption_then_dd_v1``  — 投資 → 採択 → DD 結合
3.  ``full_kyc_compliance_pipeline_v1``      — 5 トリー全結合 KYC pipeline

Each chain encodes the *order* of trees (later trees consume earlier
trees' classification + extracted facts via ``carry_keys``). Production
agents call ``composed_tools.eval_rule_chain`` once for ¥3/req instead
of N separate ¥3/req per-tree calls.

Source discipline
-----------------
Pure-deterministic Python INSERT — references existing ``am_rule_trees``
(mig 271) rows by ``tree_id`` only (no SQL FK by design — chains
survive tree-row retirement, replayable via the version history).

No LLM API import — Dim M (like Dim K) is fully deterministic per
``feedback_rule_tree_branching``.

Usage
-----
    python scripts/etl/seed_rule_tree_chains.py            # apply
    python scripts/etl/seed_rule_tree_chains.py --dry-run  # print plan
    python scripts/etl/seed_rule_tree_chains.py --db PATH  # custom db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("seed_rule_tree_chains")


# ---------------------------------------------------------------------------
# Chain catalogue (3 canonical chains over Dim K's 5 trees)
# ---------------------------------------------------------------------------


SEED_CHAINS: list[dict[str, Any]] = [
    {
        "chain_id": "subsidy_eligibility_then_gyouhou_v1",
        "domain": "subsidy_pipeline",
        "description": "補助金適格性 → 業法 fence 結合 (2 段)",
        "source_doc_id": "chain:subsidy_then_gyouhou_baseline",
        "ordered_tree_ids": [
            {
                "tree_id": "subsidy_eligibility_v1",
                "version_pin": None,
                "carry_keys": ["entity_size", "prefecture_jis"],
            },
            {
                "tree_id": "gyouhou_fence_check_v1",
                "version_pin": None,
                "carry_keys": [],
            },
        ],
    },
    {
        "chain_id": "investment_then_adoption_then_dd_v1",
        "domain": "investment_pipeline",
        "description": "投資条件 → 採択スコア → DD (3 段)",
        "source_doc_id": "chain:invest_adopt_dd_baseline",
        "ordered_tree_ids": [
            {
                "tree_id": "investment_condition_check_v1",
                "version_pin": None,
                "carry_keys": ["capital_jpy", "headcount"],
            },
            {
                "tree_id": "adoption_score_threshold_v1",
                "version_pin": None,
                "carry_keys": ["composite_score"],
            },
            {
                "tree_id": "due_diligence_v1",
                "version_pin": None,
                "carry_keys": [],
            },
        ],
    },
    {
        "chain_id": "full_kyc_compliance_pipeline_v1",
        "domain": "kyc_compliance",
        "description": "5 トリー全結合 KYC compliance pipeline",
        "source_doc_id": "chain:full_kyc_baseline",
        "ordered_tree_ids": [
            {
                "tree_id": "subsidy_eligibility_v1",
                "version_pin": None,
                "carry_keys": ["entity_size"],
            },
            {
                "tree_id": "gyouhou_fence_check_v1",
                "version_pin": None,
                "carry_keys": ["licence_status"],
            },
            {
                "tree_id": "investment_condition_check_v1",
                "version_pin": None,
                "carry_keys": ["capital_jpy"],
            },
            {
                "tree_id": "adoption_score_threshold_v1",
                "version_pin": None,
                "carry_keys": ["composite_score"],
            },
            {
                "tree_id": "due_diligence_v1",
                "version_pin": None,
                "carry_keys": [],
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _seed_history_for_existing_trees(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Back-fill am_rule_tree_version_history for any am_rule_trees rows.

    The first time mig 273 is applied, the history table is empty; for
    every committed row in am_rule_trees we insert a matching history
    row so the audit trail starts at the actual current state.
    """
    if not _table_exists(conn, "am_rule_trees"):
        LOG.warning("am_rule_trees missing — skip history back-fill (mig 271 not yet applied)")
        return 0
    rows = conn.execute(
        "SELECT tree_id, version, tree_def_json FROM am_rule_trees "
        "WHERE status='committed' ORDER BY tree_id, version"
    ).fetchall()
    inserted = 0
    for tree_id, version, tree_def_json in rows:
        existing = conn.execute(
            "SELECT 1 FROM am_rule_tree_version_history WHERE tree_id=? AND version_seq=?",
            (tree_id, version),
        ).fetchone()
        if existing:
            continue
        # Re-canonicalise so the hash is stable regardless of original
        # JSON formatting that came out of mig 271's ETL.
        try:
            payload = json.loads(tree_def_json)
        except json.JSONDecodeError:
            payload = {"_raw": tree_def_json}
        h = _canonical_hash(payload)
        if dry_run:
            LOG.info(
                "DRY-RUN would back-fill history tree_id=%s v%d hash=%s...",
                tree_id,
                version,
                h[:12],
            )
            inserted += 1
            continue
        conn.execute(
            "INSERT INTO am_rule_tree_version_history "
            "(tree_id, version_seq, definition_hash, change_note, changed_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                tree_id,
                version,
                h,
                "initial back-fill from mig 271 committed state",
                "etl:seed_rule_tree_chains.py",
            ),
        )
        inserted += 1
    return inserted


def seed(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Seed the 3 canonical rule-tree chains + version-history back-fill.

    Returns stats: {"chains_inserted": N, "chains_skipped": M,
    "history_backfilled": K, "total_chains": 3}.
    """
    LOG.info("opening db: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "am_rule_tree_chain"):
            raise RuntimeError(
                "am_rule_tree_chain missing — apply migration 273_rule_tree_v2_chain.sql first"
            )
        history_backfilled = _seed_history_for_existing_trees(conn, dry_run=dry_run)

        chains_inserted = 0
        chains_skipped = 0
        for chain in SEED_CHAINS:
            ordered_json = json.dumps(chain["ordered_tree_ids"], ensure_ascii=False, sort_keys=True)
            existing = conn.execute(
                "SELECT 1 FROM am_rule_tree_chain WHERE chain_id=?",
                (chain["chain_id"],),
            ).fetchone()
            if existing:
                chains_skipped += 1
                LOG.info("skip existing chain_id=%s", chain["chain_id"])
                continue
            if dry_run:
                LOG.info(
                    "DRY-RUN would insert chain_id=%s domain=%s steps=%d",
                    chain["chain_id"],
                    chain["domain"],
                    len(chain["ordered_tree_ids"]),
                )
                chains_inserted += 1
                continue
            conn.execute(
                """
                INSERT INTO am_rule_tree_chain
                    (chain_id, description, domain, ordered_tree_ids,
                     source_doc_id, status)
                VALUES (?, ?, ?, ?, ?, 'committed')
                """,
                (
                    chain["chain_id"],
                    chain["description"],
                    chain["domain"],
                    ordered_json,
                    chain["source_doc_id"],
                ),
            )
            chains_inserted += 1
        if not dry_run:
            conn.commit()
        return {
            "chains_inserted": chains_inserted,
            "chains_skipped": chains_skipped,
            "history_backfilled": history_backfilled,
            "total_chains": len(SEED_CHAINS),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.db.exists():
        LOG.error("db not found: %s", args.db)
        return 2

    stats = seed(args.db, dry_run=args.dry_run)
    print(json.dumps({"dim": "M", "seed_stats": stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
