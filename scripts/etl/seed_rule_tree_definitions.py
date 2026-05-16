"""Seed 5 canonical rule-tree definitions for Dim K (Wave 47).

Populates ``am_rule_trees`` (mig 271) with the 5 production-grade decision
trees consumed by ``/v1/rule_tree/evaluate`` (Dim K, Wave 46). Each tree
is a small, hand-curated AND/OR/XOR DAG of LEAF predicates exercising
the predicate parser surface in ``src/jpintel_mcp/api/rule_tree_eval.py``.

Trees seeded
------------
1.  ``subsidy_eligibility_v1``           — 補助金適格性
2.  ``gyouhou_fence_check_v1``           — 業法 fence
3.  ``investment_condition_check_v1``    — 投資条件
4.  ``adoption_score_threshold_v1``      — 採択スコア
5.  ``due_diligence_v1``                 — DD (デューデリ)

Source discipline
-----------------
All trees are derived from already-ingested fact tables (am_program,
am_law_jorei_pref, am_court_decisions_extended). No external API calls,
no aggregator scrape — this script is pure-deterministic SQL INSERT.

No LLM API import — Dim K is fully deterministic (per feedback_rule_tree_branching).

Usage
-----
    python scripts/etl/seed_rule_tree_definitions.py            # apply
    python scripts/etl/seed_rule_tree_definitions.py --dry-run  # print plan
    python scripts/etl/seed_rule_tree_definitions.py --db PATH  # custom db
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("seed_rule_tree_definitions")


# ---------------------------------------------------------------------------
# Tree catalogue (5 canonical trees)
# ---------------------------------------------------------------------------


def _tree_subsidy_eligibility_v1() -> dict[str, Any]:
    """Tree 1/5 — 補助金適格性 (subsidy eligibility).

    Pass condition: 法人格 = 中小 AND (業種 in target_set) AND (本社所在地 in target_pref).
    Replaces the typical 4-call eligibility checklist with 1 call.
    """
    return {
        "node_id": "subsidy_root",
        "operator": "AND",
        "source_doc_id": "subsidy:eligibility_baseline",
        "children": [
            {
                "node_id": "is_sme",
                "operator": "LEAF",
                "predicate": "entity_size == 'sme'",
                "source_doc_id": "law:chuusho_kihon_2",
            },
            {
                "node_id": "industry_match",
                "operator": "LEAF",
                "predicate": "industry_code in ('A', 'B', 'F', 'G', 'I')",
                "source_doc_id": "subsidy:industry_scope",
            },
            {
                "node_id": "prefecture_match",
                "operator": "LEAF",
                "predicate": "prefecture_jis exists",
                "source_doc_id": "subsidy:geo_scope",
            },
        ],
    }


def _tree_gyouhou_fence_check_v1() -> dict[str, Any]:
    """Tree 2/5 — 業法 fence (industry-law fence).

    Pass condition: (licence valid AND not_revoked) AND (NOT cross-jurisdiction).
    Surfaces tax-law §52 / accountancy §47条の2 / lawyer §72 / gyousei §1
    boundary at the LEAF level.
    """
    return {
        "node_id": "fence_root",
        "operator": "AND",
        "source_doc_id": "fence:gyouhou_baseline",
        "children": [
            {
                "node_id": "licence_present",
                "operator": "AND",
                "source_doc_id": "fence:licence_combined",
                "children": [
                    {
                        "node_id": "has_licence",
                        "operator": "LEAF",
                        "predicate": "licence_id exists",
                        "source_doc_id": "fence:licence_present",
                    },
                    {
                        "node_id": "licence_not_revoked",
                        "operator": "LEAF",
                        "predicate": "licence_status != 'revoked'",
                        "source_doc_id": "fence:licence_status",
                    },
                ],
            },
            {
                "node_id": "no_cross_jurisdiction",
                "operator": "LEAF",
                "predicate": "cross_jurisdiction == false",
                "source_doc_id": "fence:jurisdiction_scope",
            },
        ],
    }


def _tree_investment_condition_check_v1() -> dict[str, Any]:
    """Tree 3/5 — 投資条件 (investment condition).

    Pass condition: capital_amount >= threshold AND
                    (employee_count >= 5 OR (employee_count >= 2 AND
                     export_ratio_pct >= 30)).
    Multi-layer AND/OR. Exercises the depth + branching path.
    """
    return {
        "node_id": "invest_root",
        "operator": "AND",
        "source_doc_id": "invest:condition_baseline",
        "children": [
            {
                "node_id": "capital_above_floor",
                "operator": "LEAF",
                "predicate": "capital_amount >= 10000000",
                "source_doc_id": "invest:capital_floor",
            },
            {
                "node_id": "headcount_or_export",
                "operator": "OR",
                "source_doc_id": "invest:headcount_export",
                "children": [
                    {
                        "node_id": "headcount_5plus",
                        "operator": "LEAF",
                        "predicate": "employee_count >= 5",
                        "source_doc_id": "invest:headcount_5",
                    },
                    {
                        "node_id": "headcount_2plus_export_30plus",
                        "operator": "AND",
                        "source_doc_id": "invest:headcount_2_export_30",
                        "children": [
                            {
                                "node_id": "headcount_2plus",
                                "operator": "LEAF",
                                "predicate": "employee_count >= 2",
                                "source_doc_id": "invest:headcount_2",
                            },
                            {
                                "node_id": "export_30plus",
                                "operator": "LEAF",
                                "predicate": "export_ratio_pct >= 30",
                                "source_doc_id": "invest:export_30",
                            },
                        ],
                    },
                ],
            },
        ],
    }


def _tree_adoption_score_threshold_v1() -> dict[str, Any]:
    """Tree 4/5 — 採択スコア (adoption score threshold).

    Pass condition: composite_score >= 75 OR (composite_score >= 60 AND
                    diversity_bonus == true).
    Surfaces an OR-based threshold path with a bonus modifier.
    """
    return {
        "node_id": "adoption_root",
        "operator": "OR",
        "source_doc_id": "adoption:threshold_baseline",
        "children": [
            {
                "node_id": "score_75plus",
                "operator": "LEAF",
                "predicate": "composite_score >= 75",
                "source_doc_id": "adoption:threshold_75",
            },
            {
                "node_id": "score_60plus_with_bonus",
                "operator": "AND",
                "source_doc_id": "adoption:bonus_path",
                "children": [
                    {
                        "node_id": "score_60plus",
                        "operator": "LEAF",
                        "predicate": "composite_score >= 60",
                        "source_doc_id": "adoption:threshold_60",
                    },
                    {
                        "node_id": "has_diversity_bonus",
                        "operator": "LEAF",
                        "predicate": "diversity_bonus == true",
                        "source_doc_id": "adoption:diversity_bonus",
                    },
                ],
            },
        ],
    }


def _tree_due_diligence_v1() -> dict[str, Any]:
    """Tree 5/5 — DD (due diligence).

    Pass condition: (tax_compliant AND filing_current) AND
                    (NOT bankruptcy_filed) AND
                    XOR(has_audit_opinion, exempt_from_audit).
    Exercises XOR + nested AND/NOT-style predicates.
    """
    return {
        "node_id": "dd_root",
        "operator": "AND",
        "source_doc_id": "dd:baseline",
        "children": [
            {
                "node_id": "tax_status",
                "operator": "AND",
                "source_doc_id": "dd:tax_combined",
                "children": [
                    {
                        "node_id": "tax_compliant",
                        "operator": "LEAF",
                        "predicate": "tax_compliant == true",
                        "source_doc_id": "dd:tax_compliant",
                    },
                    {
                        "node_id": "filing_current",
                        "operator": "LEAF",
                        "predicate": "filing_current == true",
                        "source_doc_id": "dd:filing_current",
                    },
                ],
            },
            {
                "node_id": "no_bankruptcy",
                "operator": "LEAF",
                "predicate": "bankruptcy_filed == false",
                "source_doc_id": "dd:no_bankruptcy",
            },
            {
                "node_id": "audit_path",
                "operator": "XOR",
                "source_doc_id": "dd:audit_xor",
                "children": [
                    {
                        "node_id": "has_audit_opinion",
                        "operator": "LEAF",
                        "predicate": "has_audit_opinion == true",
                        "source_doc_id": "dd:audit_opinion",
                    },
                    {
                        "node_id": "exempt_from_audit",
                        "operator": "LEAF",
                        "predicate": "exempt_from_audit == true",
                        "source_doc_id": "dd:audit_exempt",
                    },
                ],
            },
        ],
    }


SEED_TREES: list[dict[str, Any]] = [
    {
        "tree_id": "subsidy_eligibility_v1",
        "domain": "subsidy",
        "description": "補助金適格性 — 法人格×業種×所在地",
        "source_doc_id": "subsidy:eligibility_baseline",
        "tree_def": _tree_subsidy_eligibility_v1(),
    },
    {
        "tree_id": "gyouhou_fence_check_v1",
        "domain": "gyouhou_fence",
        "description": "業法 fence — licence×revoked×jurisdiction",
        "source_doc_id": "fence:gyouhou_baseline",
        "tree_def": _tree_gyouhou_fence_check_v1(),
    },
    {
        "tree_id": "investment_condition_check_v1",
        "domain": "investment",
        "description": "投資条件 — capital×headcount×export",
        "source_doc_id": "invest:condition_baseline",
        "tree_def": _tree_investment_condition_check_v1(),
    },
    {
        "tree_id": "adoption_score_threshold_v1",
        "domain": "adoption",
        "description": "採択スコア — composite×bonus path",
        "source_doc_id": "adoption:threshold_baseline",
        "tree_def": _tree_adoption_score_threshold_v1(),
    },
    {
        "tree_id": "due_diligence_v1",
        "domain": "due_diligence",
        "description": "DD — tax×bankruptcy×XOR(audit, exempt)",
        "source_doc_id": "dd:baseline",
        "tree_def": _tree_due_diligence_v1(),
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


def seed(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Seed the 5 canonical rule trees into ``am_rule_trees``.

    Returns a stats dict: {"inserted": N, "skipped": M, "total": 5}.
    Uses INSERT OR IGNORE so re-running is idempotent.
    """
    LOG.info("opening db: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "am_rule_trees"):
            raise RuntimeError("am_rule_trees missing — apply migration 271_rule_tree.sql first")
        inserted = 0
        skipped = 0
        for tree in SEED_TREES:
            tree_def_json = json.dumps(tree["tree_def"], ensure_ascii=False, sort_keys=True)
            existing = conn.execute(
                "SELECT 1 FROM am_rule_trees WHERE tree_id=? AND version=?",
                (tree["tree_id"], 1),
            ).fetchone()
            if existing:
                skipped += 1
                LOG.info("skip existing tree_id=%s v1", tree["tree_id"])
                continue
            if dry_run:
                LOG.info(
                    "DRY-RUN would insert tree_id=%s domain=%s bytes=%d",
                    tree["tree_id"],
                    tree["domain"],
                    len(tree_def_json),
                )
                inserted += 1
                continue
            conn.execute(
                """
                INSERT INTO am_rule_trees
                    (tree_id, version, tree_def_json, source_doc_id,
                     description, domain, status)
                VALUES (?, 1, ?, ?, ?, ?, 'committed')
                """,
                (
                    tree["tree_id"],
                    tree_def_json,
                    tree["source_doc_id"],
                    tree["description"],
                    tree["domain"],
                ),
            )
            inserted += 1
        if not dry_run:
            conn.commit()
        return {"inserted": inserted, "skipped": skipped, "total": len(SEED_TREES)}
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
    print(json.dumps({"dim": "K", "seed_stats": stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
