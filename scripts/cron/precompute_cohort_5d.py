#!/usr/bin/env python3
"""Wave 33 Axis 2a: pre-compute 5-axis cohort × eligible-program mapping.

Builds am_cohort_5d rows for (houjin × jsic_major × employee_band ×
prefecture_code × program-eligibility-chain) cells. Daily refresh.

Strategy: 60% budget on synthetic band cells (no houjin, just the band
tuple), 40% on real top-N houjin anchors by total_adoptions desc. Per
cell evaluation = top-N programs filtered by tier IN (S,A,B,C) + pref
optional, ranked tier ASC then amount_max DESC.

Constraints (CLAUDE.md + memory):
* NO LLM SDK import.
* NO PRAGMA quick_check / integrity_check / VACUUM on the 9.7GB DB.
* INSERT OR REPLACE on the unique tuple — idempotent.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.precompute_cohort_5d")

DEFAULT_BUDGET = 1000
DEFAULT_WORKERS = 4
DEFAULT_TOP_PROGRAMS_PER_COHORT = 20

JSIC_MAJORS: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRST")
EMPLOYEE_BANDS: tuple[str, ...] = ("1-9", "10-99", "100-999", "1000+")
PREFECTURE_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 48))

PREF_NAME_BY_CODE: dict[str, str] = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県",
    "05": "秋田県", "06": "山形県", "07": "福島県", "08": "茨城県",
    "09": "栃木県", "10": "群馬県", "11": "埼玉県", "12": "千葉県",
    "13": "東京都", "14": "神奈川県", "15": "新潟県", "16": "富山県",
    "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県",
    "25": "滋賀県", "26": "京都府", "27": "大阪府", "28": "兵庫県",
    "29": "奈良県", "30": "和歌山県", "31": "鳥取県", "32": "島根県",
    "33": "岡山県", "34": "広島県", "35": "山口県", "36": "徳島県",
    "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県",
    "45": "宮崎県", "46": "鹿児島県", "47": "沖縄県",
}


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.precompute_cohort_5d")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _open_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_cohort_5d (
              cohort_id              INTEGER PRIMARY KEY AUTOINCREMENT,
              houjin_bangou          TEXT,
              jsic_major             TEXT NOT NULL,
              employee_band          TEXT NOT NULL,
              prefecture_code        TEXT,
              eligible_program_ids   TEXT NOT NULL DEFAULT '[]',
              eligible_count         INTEGER NOT NULL DEFAULT 0,
              last_refreshed_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cohort_5d_jbp "
        "ON am_cohort_5d(jsic_major, employee_band, prefecture_code)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cohort_5d_refresh "
        "ON am_cohort_5d(last_refreshed_at)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cohort_5d_tuple "
        "ON am_cohort_5d("
        "COALESCE(houjin_bangou, '_synthetic'),"
        "jsic_major,"
        "employee_band,"
        "COALESCE(prefecture_code, '_nationwide'))"
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _eligible_programs_for_cell(
    conn: sqlite3.Connection,
    *,
    jsic_major: str,
    prefecture_code: str | None,
    limit: int,
) -> list[str]:
    if not _table_exists(conn, "jpi_programs"):
        return []
    pref_name = PREF_NAME_BY_CODE.get(prefecture_code) if prefecture_code else None
    sql = (
        "SELECT unified_id FROM jpi_programs "
        "WHERE COALESCE(excluded, 0) = 0 "
        "  AND tier IN ('S','A','B','C') "
    )
    params: list[Any] = []
    if pref_name is not None:
        sql += "  AND (prefecture IS NULL OR prefecture = '' OR prefecture = ?) "
        params.append(pref_name)
    sql += (
        " ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
        "                    WHEN 'B' THEN 2 ELSE 3 END, "
        "          amount_max_man_yen DESC NULLS LAST "
        " LIMIT ?"
    )
    params.append(int(limit))
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(r["unified_id"]) for r in rows]


def _synthetic_cells(budget: int) -> list[tuple[None, str, str, str | None]]:
    cells: list[tuple[None, str, str, str | None]] = []
    for jsic in JSIC_MAJORS:
        for band in EMPLOYEE_BANDS:
            cells.append((None, jsic, band, None))
    for band in EMPLOYEE_BANDS:
        for jsic in JSIC_MAJORS:
            for pref in PREFECTURE_CODES:
                cells.append((None, jsic, band, pref))
    return cells[:budget]


def _band_from_adoptions(adoptions: int) -> str:
    if adoptions >= 50:
        return "1000+"
    if adoptions >= 10:
        return "100-999"
    if adoptions >= 2:
        return "10-99"
    return "1-9"


def _real_houjin_anchors(
    conn: sqlite3.Connection,
    limit: int,
) -> list[tuple[str, str, str, str | None]]:
    rows: list[tuple[str, str, str, str | None]] = []
    if not _table_exists(conn, "houjin_master"):
        return rows
    try:
        cur = conn.execute(
            "SELECT houjin_bangou, jsic_major, prefecture, total_adoptions "
            "FROM houjin_master "
            "WHERE jsic_major IS NOT NULL AND houjin_bangou IS NOT NULL "
            "ORDER BY total_adoptions DESC, last_updated_nta DESC "
            "LIMIT ?",
            (int(limit),),
        )
    except sqlite3.OperationalError:
        return rows
    name_to_code = {v: k for k, v in PREF_NAME_BY_CODE.items()}
    for r in cur:
        bangou = str(r["houjin_bangou"]).zfill(13) if r["houjin_bangou"] else None
        if not bangou or len(bangou) != 13:
            continue
        jsic = (r["jsic_major"] or "").strip()
        if jsic not in JSIC_MAJORS:
            continue
        adopts = int(r["total_adoptions"] or 0)
        band = _band_from_adoptions(adopts)
        pref_name = (r["prefecture"] or "").strip()
        pref_code = name_to_code.get(pref_name)
        rows.append((bangou, jsic, band, pref_code))
    return rows


def _evaluate_one(
    db_path: Path,
    cell: tuple[str | None, str, str, str | None],
    top_n: int,
) -> tuple[tuple[str | None, str, str, str | None], list[str]] | None:
    conn = _open_ro(db_path)
    try:
        _, jsic, _, pref = cell
        ids = _eligible_programs_for_cell(
            conn, jsic_major=jsic, prefecture_code=pref, limit=top_n
        )
        return cell, ids
    except sqlite3.Error as exc:
        logger.warning("evaluate_one_failed cell=%s err=%s", cell, exc)
        return None
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def precompute(
    *,
    budget: int = DEFAULT_BUDGET,
    workers: int = DEFAULT_WORKERS,
    top_n: int = DEFAULT_TOP_PROGRAMS_PER_COHORT,
    dry_run: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    db_path = _autonomath_db_path()
    if not db_path.exists():
        logger.warning("autonomath.db not found at %s", db_path)
        return {"status": "missing_db", "db_path": str(db_path)}

    write_conn = _open_rw(db_path)
    _ensure_table(write_conn)

    synth_budget = max(1, int(budget * 0.6))
    anchor_budget = max(1, budget - synth_budget)
    synthetic = _synthetic_cells(synth_budget)
    anchors: list[tuple[str | None, str, str, str | None]] = list(
        _real_houjin_anchors(write_conn, anchor_budget)
    )

    all_cells: list[tuple[str | None, str, str, str | None]] = []
    all_cells.extend(synthetic)
    all_cells.extend(anchors)

    logger.info(
        "precompute_start budget=%d synthetic=%d anchors=%d workers=%d top_n=%d dry_run=%s",
        budget, len(synthetic), len(anchors), workers, top_n, dry_run,
    )

    inserted = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_evaluate_one, db_path, c, top_n) for c in all_cells]
        for fut in as_completed(futures):
            outcome = fut.result()
            if outcome is None:
                errors += 1
                continue
            cell, ids = outcome
            if dry_run:
                skipped += 1
                continue
            bangou, jsic, band, pref = cell
            ids_json = json.dumps(ids, separators=(",", ":"), ensure_ascii=False)
            try:
                write_conn.execute(
                    "INSERT OR REPLACE INTO am_cohort_5d "
                    "(houjin_bangou, jsic_major, employee_band, prefecture_code, "
                    " eligible_program_ids, eligible_count, last_refreshed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                    (bangou, jsic, band, pref, ids_json, len(ids)),
                )
                inserted += 1
            except sqlite3.Error as exc:
                logger.warning("insert_failed cell=%s err=%s", cell, exc)
                errors += 1

    elapsed = time.perf_counter() - t0
    summary = {
        "status": "ok" if errors == 0 else "partial",
        "inserted": inserted, "skipped": skipped, "errors": errors,
        "elapsed_s": round(elapsed, 3),
        "budget": budget, "workers": workers, "top_n_per_cell": top_n,
        "db_path": str(db_path), "dry_run": dry_run,
    }
    logger.info("precompute_done %s", summary)
    with contextlib.suppress(Exception):
        write_conn.close()
    return summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_PROGRAMS_PER_COHORT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    summary = precompute(
        budget=args.budget, workers=args.workers,
        top_n=args.top_n, dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("status") in {"ok", "partial", "missing_db"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
