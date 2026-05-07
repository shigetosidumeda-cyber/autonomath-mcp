#!/usr/bin/env python3
"""Populate ``am_entity_appearance_count`` from ``v_houjin_appearances``.

Wave 24+ cross-table entity-resolution rollup (2026-05-05). Migration 153
created the view + the physical mirror; this script materialises the view
into the table so downstream callers (``entity_id_map`` enricher,
``/api/v1/houjin/{bangou}`` aggregator, customer narrative) can JOIN
without paying the seven-table UNION cost on every request.

Why
---
The view is correct-by-construction but expensive: every read scans
~166k jpi_houjin_master + 87k corporate am_entities + the smaller
mirrors. For top-N "which 法人 appears in the most surfaces" queries that
the customer-facing /houjin/360 narrative needs, materialising once per
ETL cycle is ~4 orders of magnitude cheaper than recomputing on demand.

What this does
--------------
1. Reads every row from ``v_houjin_appearances``.
2. Replaces the contents of ``am_entity_appearance_count`` (DELETE then
   bulk INSERT inside one transaction). Idempotent — safe to re-run.
3. Logs one summary line: ``rows=N max_count=M top1=...``.

This is NON-LLM. Pure SQL + Python normalisation. Per-row cost is bounded
by the number of distinct 13-digit houjin_bangou (~166k today), so the
script finishes in <60s on the production Fly box.

Usage
-----
    python3.13 scripts/etl/populate_entity_appearance_count.py \
        --db autonomath.db
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger("jpintel.populate_entity_appearance_count")


def _configure_logging() -> None:
    root = logging.getLogger("jpintel.populate_entity_appearance_count")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def populate(db_path: Path) -> dict[str, int]:
    """Refresh ``am_entity_appearance_count`` from ``v_houjin_appearances``.

    Returns a small dict with ``rows`` / ``max_count`` for caller logging.
    """
    started = time.monotonic()
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        # The view does the heavy UNION + DISTINCT + GROUP BY work.
        rows = conn.execute(
            "SELECT houjin_bangou, table_count, tables_json FROM v_houjin_appearances"
        ).fetchall()
        with conn:
            conn.execute("DELETE FROM am_entity_appearance_count;")
            conn.executemany(
                "INSERT INTO am_entity_appearance_count"
                "(houjin_bangou, appearance_count, tables_json, computed_at)"
                " VALUES (?,?,?,?)",
                ((b, c, j, now_iso) for (b, c, j) in rows),
            )
        max_count = max((c for _, c, _ in rows), default=0)
        elapsed = round(time.monotonic() - started, 2)
        _LOG.info(
            "populated rows=%d max_count=%d elapsed_s=%s db=%s",
            len(rows),
            max_count,
            elapsed,
            db_path.name,
        )
        return {"rows": len(rows), "max_count": max_count}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--db",
        default="autonomath.db",
        help="Path to autonomath.db (default: ./autonomath.db).",
    )
    args = p.parse_args(argv)
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        _LOG.error("db_not_found path=%s", db_path)
        return 2
    populate(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
