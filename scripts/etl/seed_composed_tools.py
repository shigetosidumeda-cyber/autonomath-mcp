"""Seed 4 canonical composed-tool definitions for Dim P (Wave 47).

Populates ``am_composed_tool_catalog`` (mig 276) with the 4 production-grade
composed tools that wrap atomic-tool chains into single metered calls:
  1. ``ultimate_due_diligence_kit``    — DD カバー全方位
  2. ``construction_total_dd``         — 建設業 (JSIC D) 一気通貫 DD
  3. ``welfare_total_dd``              — 介護・福祉 (JSIC P 一部) 一気通貫 DD
  4. ``tourism_total_dd``              — 観光 (JSIC M 一部) 一気通貫 DD

Each composition references atomic MCP tools by name (the dispatcher
resolves them at call time); chain length 4-7 per composition.

Source discipline
-----------------
All chains reference already-shipped atomic tool surfaces; no new tools
are introduced by the seed. The chain is a manifest only — execution
order is interpreted by the dispatcher, no LLM call is involved
(feedback_no_operator_llm_api).

Usage
-----
    python scripts/etl/seed_composed_tools.py            # apply
    python scripts/etl/seed_composed_tools.py --dry-run  # print plan
    python scripts/etl/seed_composed_tools.py --db PATH  # custom db
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
LOG = logging.getLogger("seed_composed_tools")


# ---------------------------------------------------------------------------
# Composition catalogue (4 canonical composed tools)
# ---------------------------------------------------------------------------


def _chain_ultimate_due_diligence_kit() -> dict[str, Any]:
    """Composition 1/4 — ultimate_due_diligence_kit.

    Cross-industry DD covering identity, enforcement, invoice compliance,
    adoption history, and amendment lineage. Replaces a 7-call walk with
    one metered call.
    """
    return {
        "tool_id": "ultimate_due_diligence_kit",
        "version": 1,
        "atomic_chain": [
            {"step": 1, "tool": "match_due_diligence_questions", "phase": "intake"},
            {"step": 2, "tool": "cross_check_jurisdiction", "phase": "identity"},
            {"step": 3, "tool": "check_enforcement_am", "phase": "compliance"},
            {"step": 4, "tool": "get_annotations", "phase": "annotations"},
            {"step": 5, "tool": "get_provenance", "phase": "provenance"},
            {"step": 6, "tool": "track_amendment_lineage_am", "phase": "amendment"},
            {"step": 7, "tool": "bundle_application_kit", "phase": "package"},
        ],
        "savings_factor": 7,
    }


def _chain_construction_total_dd() -> dict[str, Any]:
    """Composition 2/4 — construction_total_dd (JSIC D 建設業).

    Construction-vertical DD: industry pack + program eligibility +
    enforcement + adoption stats + tax chain. 5 calls → 1.
    """
    return {
        "tool_id": "construction_total_dd",
        "version": 1,
        "atomic_chain": [
            {"step": 1, "tool": "pack_construction", "phase": "industry"},
            {"step": 2, "tool": "apply_eligibility_chain_am", "phase": "eligibility"},
            {"step": 3, "tool": "check_enforcement_am", "phase": "compliance"},
            {"step": 4, "tool": "search_acceptance_stats_am", "phase": "adoption"},
            {"step": 5, "tool": "get_am_tax_rule", "phase": "tax"},
        ],
        "savings_factor": 5,
    }


def _chain_welfare_total_dd() -> dict[str, Any]:
    """Composition 3/4 — welfare_total_dd (介護・福祉 JSIC P 一部).

    Welfare-vertical DD: program lifecycle + eligibility + adoption stats
    + mutual plans (社会福祉法人 mutual insurance). 4 calls → 1.
    """
    return {
        "tool_id": "welfare_total_dd",
        "version": 1,
        "atomic_chain": [
            {"step": 1, "tool": "program_lifecycle", "phase": "lifecycle"},
            {"step": 2, "tool": "apply_eligibility_chain_am", "phase": "eligibility"},
            {"step": 3, "tool": "search_acceptance_stats_am", "phase": "adoption"},
            {"step": 4, "tool": "search_mutual_plans_am", "phase": "mutual"},
        ],
        "savings_factor": 4,
    }


def _chain_tourism_total_dd() -> dict[str, Any]:
    """Composition 4/4 — tourism_total_dd (観光 JSIC M 一部).

    Tourism-vertical DD: open programs + GX program search + adoption
    stats + region-program coverage + amendment lineage. 5 calls → 1.
    """
    return {
        "tool_id": "tourism_total_dd",
        "version": 1,
        "atomic_chain": [
            {"step": 1, "tool": "list_open_programs", "phase": "open"},
            {"step": 2, "tool": "search_gx_programs_am", "phase": "gx"},
            {"step": 3, "tool": "search_acceptance_stats_am", "phase": "adoption"},
            {"step": 4, "tool": "find_complementary_programs_am", "phase": "complementary"},
            {"step": 5, "tool": "track_amendment_lineage_am", "phase": "amendment"},
        ],
        "savings_factor": 5,
    }


SEED_COMPOSED_TOOLS: list[dict[str, Any]] = [
    {
        "tool_id": "ultimate_due_diligence_kit",
        "domain": "due_diligence",
        "description": "全方位 DD — identity×enforcement×provenance×amendment",
        "source_doc_id": "dim_p:dd_baseline",
        "chain": _chain_ultimate_due_diligence_kit(),
    },
    {
        "tool_id": "construction_total_dd",
        "domain": "construction",
        "description": "建設業 (JSIC D) 一気通貫 DD — industry×eligibility×tax",
        "source_doc_id": "dim_p:construction_baseline",
        "chain": _chain_construction_total_dd(),
    },
    {
        "tool_id": "welfare_total_dd",
        "domain": "welfare",
        "description": "介護・福祉 (JSIC P 一部) 一気通貫 DD — lifecycle×mutual",
        "source_doc_id": "dim_p:welfare_baseline",
        "chain": _chain_welfare_total_dd(),
    },
    {
        "tool_id": "tourism_total_dd",
        "domain": "tourism",
        "description": "観光 (JSIC M 一部) 一気通貫 DD — open×gx×adoption",
        "source_doc_id": "dim_p:tourism_baseline",
        "chain": _chain_tourism_total_dd(),
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
    """Seed the 4 canonical composed tools into ``am_composed_tool_catalog``.

    Returns a stats dict: {"inserted": N, "skipped": M, "total": 4}.
    Uses an explicit existence probe so re-running is idempotent.
    """
    LOG.info("opening db: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "am_composed_tool_catalog"):
            raise RuntimeError(
                "am_composed_tool_catalog missing — apply migration "
                "276_composable_tools.sql first"
            )
        inserted = 0
        skipped = 0
        for tool in SEED_COMPOSED_TOOLS:
            chain_json = json.dumps(
                tool["chain"], ensure_ascii=False, sort_keys=True
            )
            existing = conn.execute(
                "SELECT 1 FROM am_composed_tool_catalog "
                "WHERE tool_id=? AND version=?",
                (tool["tool_id"], 1),
            ).fetchone()
            if existing:
                skipped += 1
                LOG.info("skip existing tool_id=%s v1", tool["tool_id"])
                continue
            if dry_run:
                LOG.info(
                    "DRY-RUN would insert tool_id=%s domain=%s bytes=%d",
                    tool["tool_id"],
                    tool["domain"],
                    len(chain_json),
                )
                inserted += 1
                continue
            conn.execute(
                """
                INSERT INTO am_composed_tool_catalog
                    (tool_id, version, atomic_tool_chain, source_doc_id,
                     description, domain, status)
                VALUES (?, 1, ?, ?, ?, ?, 'committed')
                """,
                (
                    tool["tool_id"],
                    chain_json,
                    tool["source_doc_id"],
                    tool["description"],
                    tool["domain"],
                ),
            )
            inserted += 1
        if not dry_run:
            conn.commit()
        return {
            "inserted": inserted,
            "skipped": skipped,
            "total": len(SEED_COMPOSED_TOOLS),
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
    print(json.dumps({"dim": "P", "seed_stats": stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
