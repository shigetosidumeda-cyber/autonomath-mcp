#!/usr/bin/env python3
"""Wave 43.1.4: weekly aggregate over am_program_agriculture (mig 251). NO LLM."""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from jpintel_mcp._jpcite_env_bridge import get_flag

logger = logging.getLogger("jpcite.cron.aggregate_program_agriculture_weekly")
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
_VALID_AGRI_TYPES = frozenset({"耕種", "畜産", "林業", "漁業", "6次産業", "一般"})
_KW_AGRI_TYPE = (
    ("漁業", ("漁業", "水産", "養殖", "漁船", "定置網", "漁協")),
    ("林業", ("林業", "森林", "造林", "間伐", "木材", "森林組合")),
    ("畜産", ("畜産", "酪農", "肉牛", "乳牛", "養豚", "養鶏")),
    ("6次産業", ("6次", "六次", "農商工連携", "農泊")),
    ("耕種", ("水稲", "稲作", "畑作", "野菜", "果樹", "花き", "麦", "大豆", "茶")),
)


def _configure_logging(verbose=False):
    root = logging.getLogger("jpcite.cron.aggregate_program_agriculture_weekly")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr); sh.setFormatter(fmt); root.addHandler(sh)


def _db_path():
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _open_rw(db_path):
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
        conn.execute("PRAGMA busy_timeout=300000")
    return conn


def _table_exists(conn, name):
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1", (name,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _classify_agri_type(text):
    t = text or ""
    for label, keywords in _KW_AGRI_TYPE:
        if any(k in t for k in keywords): return label
    return "一般"


def _reclassify(conn):
    if not _table_exists(conn, "am_program_agriculture"): return 0
    touched = 0
    rows = conn.execute("SELECT program_agri_id, title, agriculture_type FROM am_program_agriculture").fetchall()
    for r in rows:
        new = _classify_agri_type(r["title"] or "")
        if new not in _VALID_AGRI_TYPES: new = "一般"
        if new != r["agriculture_type"]:
            try:
                conn.execute("UPDATE am_program_agriculture SET agriculture_type = ?, refreshed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE program_agri_id = ?", (new, r["program_agri_id"]))
                touched += 1
            except sqlite3.Error:
                pass
    return touched


def _annotate_passed(conn):
    if not _table_exists(conn, "am_program_agriculture"): return 0
    today = date.today().isoformat()
    rows = conn.execute("SELECT program_agri_id, deadline, notes FROM am_program_agriculture WHERE deadline IS NOT NULL AND deadline < ?", (today,)).fetchall()
    touched = 0
    for r in rows:
        notes = r["notes"] or ""
        if "deadline_passed" in notes: continue
        new_notes = (notes + " | deadline_passed").strip(" |")
        try:
            conn.execute("UPDATE am_program_agriculture SET notes = ? WHERE program_agri_id = ?", (new_notes[:1000], r["program_agri_id"]))
            touched += 1
        except sqlite3.Error:
            pass
    return touched


def _build_argparser():
    p = argparse.ArgumentParser(description="Weekly aggregate over am_program_agriculture (NO ML, NO LLM).")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv=None):
    args = _build_argparser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    started_at = datetime.now(UTC).isoformat()
    db_path = _db_path()
    if args.dry_run:
        logger.info("[dry-run] would open %s", db_path); return 0
    if not db_path.exists():
        logger.error("autonomath.db missing at %s — run migration 251 first", db_path); return 2
    conn = _open_rw(db_path)
    try:
        reclassed = _reclassify(conn); passed = _annotate_passed(conn)
        with contextlib.suppress(sqlite3.Error):
            conn.execute("INSERT INTO am_program_agriculture_ingest_log (started_at, finished_at, rows_seen, rows_upserted, rows_skipped, source_kind, error_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started_at, datetime.now(UTC).isoformat(), reclassed + passed, reclassed, passed, "cron_weekly", None))
        result = {"reclassified": reclassed, "deadline_passed_marked": passed}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        with contextlib.suppress(Exception):
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
