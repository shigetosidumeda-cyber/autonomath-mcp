#!/usr/bin/env python3
"""Wave 33 Axis 2b: pre-compute 4-axis program-risk score into am_program_risk_4d.

What it does
------------
For every (program × 業法 fence × enforcement pattern × revocation reason)
cell where evidence exists in the corpora, write one row to
``am_program_risk_4d`` carrying a 0-100 weighted score + evidence JSON.

Inputs (autonomath.db only — no cross-DB ATTACH)
------------------------------------------------
* ``jpi_programs`` (~11,601 rows) — primary metadata.
* ``am_enforcement_detail`` (22,258 rows) — enforcement signal.
* ``nta_tsutatsu_index`` (3,221 rows) — 通達 reference → revocation reason.

Weighted score (per cell)
-------------------------
::

    score = round(
        0.5 * gyouhou_severity_0_100
      + 0.3 * enforcement_signal_0_100
      + 0.2 * tsutatsu_signal_0_100
    )

* gyouhou_severity: lookup table per 業法 (税理士法 §52 = 80,
  公認会計士法 §47条の2 = 70, 弁護士法 §72 = 90, 行政書士法 §1 = 60,
  司法書士法 §3 = 70, 社労士法 §27 = 60, 弁理士法 §75 = 65,
  宅建業法 §47 = 55, 'none' = 0).
* enforcement_signal: 100 * (related_enforcement_rows /
  max(1, all_enforcement_rows_for_authority)). Bounded to [0, 100].
* tsutatsu_signal: 100 if the program references a 通達 code in
  ``nta_tsutatsu_index``, 50 if only a parent_code matches, 0 otherwise.

Sensible defaults — if a cell has no enforcement evidence the score
collapses to the gyouhou_severity baseline (the boundary still matters
even without a concrete violation log).

Constraints (CLAUDE.md + memory)
--------------------------------
* NO LLM call — pure SQLite + standard library.
* NO ``PRAGMA quick_check`` / ``integrity_check`` / ``VACUUM`` on the
  9.7GB autonomath.db.
* Idempotent — INSERT OR REPLACE on the 4-tuple unique constraint.

Usage
-----
    python scripts/cron/precompute_program_risk_4d.py            # full run
    python scripts/cron/precompute_program_risk_4d.py --budget 5000
    python scripts/cron/precompute_program_risk_4d.py --dry-run
    python scripts/cron/precompute_program_risk_4d.py --program-limit 100
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
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.precompute_program_risk_4d")

DEFAULT_BUDGET = 5000
DEFAULT_PROGRAM_LIMIT = 1000

# 業法 enum ↔ severity baseline. Mirror of mig 232 CHECK constraint.
GYOUHOU_SEVERITY: dict[str, int] = {
    "none": 0,
    "zeirishi_52": 80,
    "kaikei_47no2": 70,
    "gyouseishoshi_1": 60,
    "bengoshi_72": 90,
    "shihoushoshi_3": 70,
    "sharoushi_27": 60,
    "benrishi_75": 65,
    "takkengyou_47": 55,
}

# Keyword → gyouhou map. Pure-substring detector (the same approach the
# existing ``_business_law_detector`` module uses for the runtime path).
GYOUHOU_KEYWORDS: dict[str, tuple[str, ...]] = {
    "zeirishi_52": ("税務", "申告", "税理士", "確定申告", "決算", "税制"),
    "kaikei_47no2": ("会計監査", "公認会計士", "監査", "財務諸表"),
    "gyouseishoshi_1": ("申請書面", "許認可", "行政書士", "申請手続"),
    "bengoshi_72": ("法律相談", "示談", "弁護士", "訴訟"),
    "shihoushoshi_3": ("登記", "司法書士", "成年後見"),
    "sharoushi_27": ("社会保険", "労務", "社労士", "36協定", "就業規則"),
    "benrishi_75": ("特許", "意匠", "弁理士", "商標"),
    "takkengyou_47": ("宅地建物", "宅建", "不動産取引", "重要事項説明"),
}


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.precompute_program_risk_4d")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #


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


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_program_risk_4d (
              id                     INTEGER PRIMARY KEY AUTOINCREMENT,
              program_id             TEXT NOT NULL,
              gyouhou_id             TEXT NOT NULL DEFAULT 'none',
              enforcement_pattern_id INTEGER,
              revocation_reason_id   INTEGER,
              risk_score_0_100       INTEGER NOT NULL DEFAULT 0,
              evidence_json          TEXT NOT NULL DEFAULT '{}',
              last_refreshed_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_program_risk_4d_program_score "
        "ON am_program_risk_4d(program_id, risk_score_0_100 DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_program_risk_4d_gyouhou "
        "ON am_program_risk_4d(gyouhou_id, risk_score_0_100 DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_program_risk_4d_refresh "
        "ON am_program_risk_4d(last_refreshed_at)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_program_risk_4d_tuple "
        "ON am_program_risk_4d("
        "program_id, gyouhou_id, "
        "COALESCE(enforcement_pattern_id, -1), "
        "COALESCE(revocation_reason_id, -1))"
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


# --------------------------------------------------------------------------- #
# Signal computation
# --------------------------------------------------------------------------- #


def _detect_gyouhou(primary_name: str) -> list[str]:
    """Return the set of gyouhou ids whose keywords appear in primary_name."""
    if not primary_name:
        return ["none"]
    hits: list[str] = []
    for gid, kws in GYOUHOU_KEYWORDS.items():
        if any(kw in primary_name for kw in kws):
            hits.append(gid)
    return hits or ["none"]


def _enforcement_pattern_index(
    conn: sqlite3.Connection,
) -> dict[tuple[str | None, str | None], int]:
    """Build a deterministic surrogate id per (enforcement_kind, issuing_authority).

    Used as enforcement_pattern_id on the precompute row. Returns the
    in-memory mapping (cron lifetime only — schema 232 stores the id as
    INTEGER so any future stable-id migration can backfill).
    """
    idx: dict[tuple[str | None, str | None], int] = {}
    if not _table_exists(conn, "am_enforcement_detail"):
        return idx
    try:
        rows = conn.execute(
            "SELECT DISTINCT enforcement_kind, issuing_authority "
            "FROM am_enforcement_detail "
            "ORDER BY enforcement_kind, issuing_authority"
        ).fetchall()
    except sqlite3.OperationalError:
        return idx
    for i, r in enumerate(rows, start=1):
        idx[(r["enforcement_kind"], r["issuing_authority"])] = i
    return idx


def _tsutatsu_code_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Mapping from nta_tsutatsu_index.code → surrogate id."""
    idx: dict[str, int] = {}
    if not _table_exists(conn, "nta_tsutatsu_index"):
        return idx
    try:
        rows = conn.execute(
            "SELECT code FROM nta_tsutatsu_index ORDER BY code"
        ).fetchall()
    except sqlite3.OperationalError:
        return idx
    for i, r in enumerate(rows, start=1):
        idx[str(r["code"])] = i
    return idx


def _enforcement_signal(
    conn: sqlite3.Connection,
    program_name: str,
) -> tuple[int, list[int]]:
    """Heuristic enforcement-related count vs. authority-corpus volume.

    The current schema does not carry a hard program_id ↔ enforcement_row
    FK; we approximate via target_name fuzzy substring on the program
    primary_name (e.g. a 制度 named "IT導入補助金" matches reason_summary
    referencing 'IT導入補助金' or 'IT補助' textually).
    """
    if not program_name or not _table_exists(conn, "am_enforcement_detail"):
        return 0, []
    # Bound the substring search so a single-character program name
    # (corpus noise) does not pull the entire enforcement corpus.
    if len(program_name) < 3:
        return 0, []
    like_pat = f"%{program_name[:20]}%"
    try:
        rows = conn.execute(
            "SELECT enforcement_id FROM am_enforcement_detail "
            "WHERE reason_summary LIKE ? OR target_name LIKE ? "
            "LIMIT 50",
            (like_pat, like_pat),
        ).fetchall()
    except sqlite3.OperationalError:
        return 0, []
    if not rows:
        return 0, []
    related = [int(r["enforcement_id"]) for r in rows]
    # Bound signal at 100 — saturating after 50 hits is intentional.
    raw = min(len(related) * 2, 100)
    return raw, related


def _tsutatsu_signal(
    conn: sqlite3.Connection,
    program_name: str,
    tsutatsu_index: dict[str, int],
) -> tuple[int, list[str]]:
    """100 if program references any 通達 by title substring, else 0."""
    if not program_name or not _table_exists(conn, "nta_tsutatsu_index"):
        return 0, []
    if len(program_name) < 3:
        return 0, []
    like_pat = f"%{program_name[:20]}%"
    try:
        rows = conn.execute(
            "SELECT code FROM nta_tsutatsu_index "
            "WHERE title LIKE ? OR body_excerpt LIKE ? "
            "LIMIT 20",
            (like_pat, like_pat),
        ).fetchall()
    except sqlite3.OperationalError:
        return 0, []
    if not rows:
        return 0, []
    codes = [str(r["code"]) for r in rows]
    return 100, codes


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def precompute(
    *,
    budget: int = DEFAULT_BUDGET,
    program_limit: int = DEFAULT_PROGRAM_LIMIT,
    dry_run: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    db_path = _autonomath_db_path()

    if not db_path.exists():
        msg = f"autonomath.db not found at {db_path}"
        logger.warning(msg)
        return {"status": "missing_db", "db_path": str(db_path)}

    conn = _open_rw(db_path)
    _ensure_table(conn)

    if not _table_exists(conn, "jpi_programs"):
        logger.warning("jpi_programs missing — nothing to score")
        return {"status": "no_programs_table"}

    enf_pat_idx = _enforcement_pattern_index(conn)
    tsu_idx = _tsutatsu_code_index(conn)
    logger.info(
        "precompute_start budget=%d program_limit=%d patterns=%d tsutatsu=%d dry_run=%s",
        budget,
        program_limit,
        len(enf_pat_idx),
        len(tsu_idx),
        dry_run,
    )

    programs = conn.execute(
        "SELECT unified_id, primary_name FROM jpi_programs "
        "WHERE COALESCE(excluded, 0) = 0 AND tier IN ('S','A','B','C') "
        "ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
        "                    WHEN 'B' THEN 2 ELSE 3 END "
        "LIMIT ?",
        (int(program_limit),),
    ).fetchall()

    inserted = 0
    errors = 0
    rows_emitted = 0

    for prow in programs:
        if rows_emitted >= budget:
            break
        program_id = str(prow["unified_id"])
        primary_name = str(prow["primary_name"] or "")
        gyouhous = _detect_gyouhou(primary_name)
        enf_score, enf_ids = _enforcement_signal(conn, primary_name)
        tsu_score, tsu_codes = _tsutatsu_signal(conn, primary_name, tsu_idx)

        # Determine the enforcement_pattern_id surrogate (first hit's pattern).
        enforcement_pattern_id: int | None = None
        if enf_ids:
            try:
                first = conn.execute(
                    "SELECT enforcement_kind, issuing_authority "
                    "FROM am_enforcement_detail WHERE enforcement_id = ?",
                    (enf_ids[0],),
                ).fetchone()
                if first:
                    enforcement_pattern_id = enf_pat_idx.get(
                        (first["enforcement_kind"], first["issuing_authority"])
                    )
            except sqlite3.OperationalError:
                enforcement_pattern_id = None

        revocation_reason_id = tsu_idx.get(tsu_codes[0]) if tsu_codes else None

        for gid in gyouhous:
            if rows_emitted >= budget:
                break
            base = GYOUHOU_SEVERITY.get(gid, 0)
            score = round(0.5 * base + 0.3 * enf_score + 0.2 * tsu_score)
            score = max(0, min(100, score))
            evidence = {
                "enforcement_ids": enf_ids[:10],
                "tsutatsu_codes": tsu_codes[:5],
                "weights": {"gyouhou": 0.5, "enforcement": 0.3, "tsutatsu": 0.2},
                "gyouhou_severity_baseline": base,
            }
            if dry_run:
                rows_emitted += 1
                continue
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO am_program_risk_4d "
                    "(program_id, gyouhou_id, enforcement_pattern_id, "
                    " revocation_reason_id, risk_score_0_100, evidence_json, "
                    " last_refreshed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                    (
                        program_id,
                        gid,
                        enforcement_pattern_id,
                        revocation_reason_id,
                        score,
                        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                inserted += 1
                rows_emitted += 1
            except sqlite3.Error as exc:
                logger.warning("insert_failed program=%s gid=%s err=%s", program_id, gid, exc)
                errors += 1

    elapsed = time.perf_counter() - t0
    summary = {
        "status": "ok" if errors == 0 else "partial",
        "inserted": inserted,
        "rows_emitted": rows_emitted,
        "errors": errors,
        "elapsed_s": round(elapsed, 3),
        "budget": budget,
        "program_limit": program_limit,
        "db_path": str(db_path),
        "dry_run": dry_run,
    }
    logger.info("precompute_done %s", summary)
    with contextlib.suppress(Exception):
        conn.close()
    return summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    p.add_argument("--program-limit", type=int, default=DEFAULT_PROGRAM_LIMIT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    summary = precompute(
        budget=args.budget,
        program_limit=args.program_limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("status") in {"ok", "partial", "missing_db", "no_programs_table"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
