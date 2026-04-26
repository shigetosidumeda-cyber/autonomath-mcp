#!/usr/bin/env python3
"""Rebuild am_entities_fts (trigram) and am_entities_fts_uni (unicode61) from
am_entities. V4 Phase 6 deliverable (task #78).

Why this script exists
----------------------
Per the 2026-04-25 N2 audit (analysis_wave18/_n2_fts_vec_audit_2026-04-25.md):

* `am_entities_fts` covers 402,600 / 503,930 rows = 79.9 %
* `am_entities_fts_uni` covers 388,972 / 503,930 rows = 77.2 %
* No INSERT/UPDATE/DELETE triggers exist on `am_entities` to keep these
  in sync, so every post-V4 ingest (gbiz +79,876 corporate_entity rows,
  examiner_feedback +annotations, enforcement +21k) silently skips FTS.
* Customer-facing impact: `mcp/autonomath_tools/tools.py` MATCH calls
  miss ~101k entities, including the 80k post-V4 corporate_entity rows.

This script wipes both FTS tables and reinserts every row from am_entities.
Both FTS tables share identical schema (canonical_id UNINDEXED,
record_kind UNINDEXED, primary_name, raw_json), so we read am_entities
once and write to both inside the same transaction.

Read-only on every other table. Safe to interrupt mid-run — the next
invocation will redo the whole rebuild idempotently. Recommended pattern:
take an APFS clone backup of autonomath.db first; rollback = mv backup back.

Performance
-----------
Cost driver = pulling 503k raw_json blobs (avg ~2 KB) and trigram-tokenising
them. Single-threaded, ~30-90 min on M-class hardware per the audit.
We commit every BATCH rows to keep WAL bounded.

Usage
-----
    .venv/bin/python scripts/rebuild_am_entities_fts.py            # both FTS tables
    .venv/bin/python scripts/rebuild_am_entities_fts.py --only tri # trigram only
    .venv/bin/python scripts/rebuild_am_entities_fts.py --only uni # unicode61 only
    .venv/bin/python scripts/rebuild_am_entities_fts.py --dry-run  # verify deltas, no writes
    .venv/bin/python scripts/rebuild_am_entities_fts.py --batch 5000

Env knobs
---------
    AUTONOMATH_DB_PATH    override DB path (default: ./autonomath.db)
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", REPO_ROOT / "autonomath.db"))

log = logging.getLogger("rebuild_am_entities_fts")


FTS_TABLES = {
    "tri": ("am_entities_fts", "trigram"),
    "uni": ("am_entities_fts_uni", "unicode61 remove_diacritics 2"),
}


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _audit_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return current row counts for am_entities + the two FTS tables."""
    out: dict[str, int] = {}
    out["am_entities"] = conn.execute(
        "SELECT COUNT(*) FROM am_entities"
    ).fetchone()[0]
    for table, _ in FTS_TABLES.values():
        try:
            out[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 — whitelist
            ).fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = -1  # missing table
    return out


def _rebuild_one(
    conn: sqlite3.Connection, table: str, batch: int
) -> int:
    """Wipe `table`, then bulk INSERT every row from am_entities. Returns count.

    We DELETE rather than DROP+CREATE because the audit confirmed no
    triggers depend on these FTS tables, and DELETE preserves the
    column definitions / tokenize choice authoritative in sqlite_master.
    """
    log.info("[%s] DELETE existing FTS rows", table)
    t0 = time.perf_counter()
    conn.execute(f"DELETE FROM {table}")  # noqa: S608 — whitelist
    conn.commit()
    log.info(
        "[%s] DELETE done in %.1fs", table, time.perf_counter() - t0
    )

    log.info("[%s] streaming am_entities and bulk-inserting", table)
    t0 = time.perf_counter()
    cur = conn.execute(
        "SELECT canonical_id, record_kind, primary_name, raw_json "
        "FROM am_entities ORDER BY rowid"
    )
    inserted = 0
    pending: list[tuple[str, str, str, str]] = []
    insert_sql = (
        f"INSERT INTO {table} "  # noqa: S608 — whitelist
        "(canonical_id, record_kind, primary_name, raw_json) "
        "VALUES (?, ?, ?, ?)"
    )
    for row in cur:
        pending.append(
            (row[0], row[1] or "", row[2] or "", row[3] or "")
        )
        if len(pending) >= batch:
            conn.executemany(insert_sql, pending)
            conn.commit()
            inserted += len(pending)
            pending = []
            if inserted % (batch * 10) == 0:
                rate = inserted / (time.perf_counter() - t0)
                log.info(
                    "[%s] inserted=%d rate=%.0f rows/s elapsed=%.1fs",
                    table, inserted, rate, time.perf_counter() - t0,
                )
    if pending:
        conn.executemany(insert_sql, pending)
        conn.commit()
        inserted += len(pending)

    dt = time.perf_counter() - t0
    log.info(
        "[%s] insert done rows=%d elapsed=%.1fs avg=%.0f rows/s",
        table, inserted, dt, inserted / dt if dt > 0 else 0,
    )
    return inserted


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to autonomath.db (default: {DEFAULT_DB})",
    )
    p.add_argument(
        "--only",
        choices=("tri", "uni", "both"),
        default="both",
        help="Which FTS table(s) to rebuild",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print before-counts, do not modify the DB",
    )
    p.add_argument(
        "--batch",
        type=int,
        default=2000,
        help="INSERT batch size per commit (default: 2000)",
    )
    args = p.parse_args(argv)

    if not args.db.is_file():
        log.error("DB not found: %s", args.db)
        return 2

    log.info("DB: %s", args.db)
    log.info("only=%s dry_run=%s batch=%d", args.only, args.dry_run, args.batch)

    conn = sqlite3.connect(str(args.db), timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000")
    # WAL stays the global default (autonomath.db is already in WAL mode).
    try:
        before = _audit_counts(conn)
        log.info("before: %s", before)
        if args.dry_run:
            for k, (table, _tok) in FTS_TABLES.items():
                if args.only in (k, "both"):
                    delta = before["am_entities"] - before.get(table, 0)
                    log.info(
                        "would_rebuild table=%s parent=%d current=%d delta=%d",
                        table, before["am_entities"], before.get(table, 0), delta,
                    )
            return 0

        targets = (
            list(FTS_TABLES.items())
            if args.only == "both"
            else [(args.only, FTS_TABLES[args.only])]
        )
        for _key, (table, tokenizer) in targets:
            log.info(
                "rebuilding table=%s tokenize=%s parent_rows=%d",
                table, tokenizer, before["am_entities"],
            )
            _rebuild_one(conn, table, args.batch)

        after = _audit_counts(conn)
        log.info("after: %s", after)
        for _key, (table, _tok) in targets:
            if after.get(table) != after["am_entities"]:
                log.warning(
                    "mismatch table=%s parent=%d fts=%d delta=%d",
                    table, after["am_entities"],
                    after.get(table, 0),
                    after["am_entities"] - after.get(table, 0),
                )
            else:
                log.info(
                    "parity table=%s rows=%d", table, after.get(table, 0)
                )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
