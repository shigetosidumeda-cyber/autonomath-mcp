#!/usr/bin/env python3
"""Wave 46 Dim B — legal_chain_v2 5-layer chain materializer (idempotent backfill).

Walks the existing `am_legal_chain` rows + `programs` anchors (jpintel.db)
and ensures each anchor's 5 layers (budget / law / cabinet / enforcement /
case) are addressable from `legal_chain_v2` REST + MCP surface.

Source discipline (memory `feedback_no_fake_data` / CLAUDE.md aggregator-ban)
---------------------------------------------------------------------------
* Anchor: `programs.unified_id` (S/A/B/C tier rows only — quarantine
  `tier='X'` excluded per CLAUDE.md gotcha).
* Layer source: `am_legal_chain` rows already populated via prior
  per-source ETL (budget.go.jp / e-Gov / cabinet decision PDFs /
  enforcement_cases / case_studies). This script does NOT fetch — it
  reconciles existing data and prints a coverage report.

Constraints
-----------
* NO LLM call (memory `feedback_no_operator_llm_api`).
* NO `claude_agent_sdk` / `anthropic` / `openai` / `google.generativeai`.
* NO `PRAGMA quick_check` / `integrity_check` on 9.7 GB autonomath.db
  (memory `feedback_no_quick_check_on_huge_sqlite`).
* Idempotent — UPSERT into `am_legal_chain_run_log` only; no schema
  mutation, no DML on `am_legal_chain` itself (that table is the
  authoritative store — this script reads and reports).
* CLAUDE.md "no cross-DB JOIN" — opens both DBs as separate connections.

Usage
-----
    python scripts/etl/build_legal_chain_v2.py --dry-run
    python scripts/etl/build_legal_chain_v2.py --max-anchors 200
    python scripts/etl/build_legal_chain_v2.py            # full reconciliation

Exit codes
----------
* 0 — reconciliation completed, coverage report printed.
* 2 — autonomath.db unavailable (boot-time path drift).
* 3 — jpintel.db unavailable.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sqlite3
import sys
import time
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

logger = logging.getLogger("etl.build_legal_chain_v2")

_LAYERS: tuple[str, ...] = ("budget", "law", "cabinet", "enforcement", "case")


def _connect_ro(path: pathlib.Path) -> sqlite3.Connection | None:
    if not path.exists():
        logger.warning("build_legal_chain_v2: DB missing at %s", path)
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _coverage_per_layer(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {layer_name: row_count} from am_legal_chain (read-only)."""
    cov: dict[str, int] = dict.fromkeys(_LAYERS, 0)
    try:
        rows = conn.execute(
            "SELECT layer, COUNT(*) AS n FROM am_legal_chain GROUP BY layer"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_legal_chain query failed: %s", exc)
        return cov
    for r in rows:
        layer = str(r["layer"]) if r["layer"] else ""
        if layer in cov:
            cov[layer] = int(r["n"])
    return cov


def _anchor_count(conn: sqlite3.Connection, max_anchors: int | None) -> int:
    """Count S/A/B/C tier programs serving as legal_chain anchors."""
    sql = "SELECT COUNT(*) FROM programs WHERE tier IN ('S','A','B','C') AND excluded = 0"
    try:
        n = int(conn.execute(sql).fetchone()[0])
    except sqlite3.Error as exc:
        logger.warning("anchor count failed: %s", exc)
        return 0
    if max_anchors is not None and n > max_anchors:
        return max_anchors
    return n


def _log_run(conn: sqlite3.Connection, dry_run: bool, payload: dict) -> None:
    if dry_run:
        logger.info("dry-run: would log run payload=%s", json.dumps(payload, ensure_ascii=False))
        return
    try:
        conn.execute(
            "INSERT INTO am_legal_chain_run_log "
            "(started_at, finished_at, anchors_seen, rows_seen, error_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                payload["started_at"],
                payload["finished_at"],
                payload["anchors_seen"],
                payload["rows_seen"],
                payload.get("error_text"),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("run_log insert failed (table may not exist yet): %s", exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only; no DML")
    ap.add_argument("--max-anchors", type=int, default=None, help="cap anchor scan")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    started_at = datetime.now(UTC).isoformat()
    t0 = time.time()

    jp = _connect_ro(JPINTEL_DB)
    if jp is None:
        logger.error("jpintel.db unavailable — exit 3")
        return 3
    am = _connect_ro(AUTONOMATH_DB)
    if am is None:
        logger.error("autonomath.db unavailable — exit 2")
        jp.close()
        return 2

    anchors = _anchor_count(jp, args.max_anchors)
    coverage = _coverage_per_layer(am)
    total_rows = sum(coverage.values())

    elapsed = time.time() - t0
    finished_at = datetime.now(UTC).isoformat()

    payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "anchors_seen": anchors,
        "rows_seen": total_rows,
        "coverage_per_layer": coverage,
        "elapsed_sec": round(elapsed, 3),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    jp.close()
    # Reopen autonomath rw only when not dry-run (to write run_log)
    if not args.dry_run:
        am.close()
        try:
            am_rw = sqlite3.connect(str(AUTONOMATH_DB))
        except sqlite3.Error as exc:
            logger.warning("autonomath rw open failed: %s", exc)
            return 0
        _log_run(am_rw, dry_run=False, payload=payload)
        am_rw.close()
    else:
        am.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
