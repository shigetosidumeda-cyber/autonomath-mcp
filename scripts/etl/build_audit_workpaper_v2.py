#!/usr/bin/env python3
"""Wave 46 dim 19 D-final — am_audit_workpaper snapshot builder ETL.

Purpose
-------
Walks a configurable cohort of 法人 × FY tuples and runs the same 5-source
composer used by ``src/jpintel_mcp/api/audit_workpaper_v2.py``
(``_build_workpaper`` in that module). The resulting envelope is upserted
into ``am_audit_workpaper`` (migration 289) so the lighter ¥3/req cohort
read endpoint and dashboards can scan a denormalized cache without paying
the 5-fan-out live compose cost.

Cohort selection (default)
--------------------------
* All ``jpi_houjin_master`` rows that had at least one
  ``jpi_adoption_records`` row in the FY window (i.e. active recipients).
* Current FY (= current_year if month >= 4 else current_year - 1) AND the
  previous FY. Two-FY window per 法人.
* Caps: ``--limit-houjin`` (default 20000), ``--max-rows`` (default 40000).

Constraints
-----------
* **NO LLM API.** No anthropic / openai / google.generativeai import. The
  compose is purely deterministic SQL projection (mirrors the 5 source
  tables exactly the way ``api/audit_workpaper_v2.py::_build_workpaper``
  does).
* **Idempotent upsert** via ``INSERT … ON CONFLICT (houjin_bangou,
  fiscal_year) DO UPDATE``. Re-running on the same dataset produces zero
  net changes once steady state is reached.
* **Run-log** on ``am_audit_workpaper_run_log`` (one row per ETL
  invocation).

Usage
-----
    .venv/bin/python scripts/etl/build_audit_workpaper_v2.py
    .venv/bin/python scripts/etl/build_audit_workpaper_v2.py --dry-run
    .venv/bin/python scripts/etl/build_audit_workpaper_v2.py \
        --only 1234567890123,7000020131008 --fiscal-year 2025
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("autonomath.etl.build_audit_workpaper_v2")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _current_fy() -> int:
    now = datetime.now(UTC)
    return now.year if now.month >= 4 else now.year - 1


def _fy_window(fiscal_year: int) -> tuple[str, str]:
    return f"{fiscal_year:04d}-04-01", f"{fiscal_year + 1:04d}-04-01"


def _open_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"autonomath.db missing at {path}")
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO am_audit_workpaper_run_log (started_at) VALUES (?)",
        (_now_iso(),),
    )
    return int(cur.lastrowid)


def _finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    scanned: int,
    upserted: int,
    skipped: int,
    errors: int,
    error_text: str | None,
) -> None:
    conn.execute(
        """UPDATE am_audit_workpaper_run_log
              SET finished_at = ?, houjin_scanned = ?,
                  workpapers_upserted = ?, workpapers_skipped = ?,
                  errors_count = ?, error_text = ?
            WHERE run_id = ?""",
        (_now_iso(), scanned, upserted, skipped, errors, error_text, run_id),
    )


def _candidate_houjin(
    conn: sqlite3.Connection, fy_start: str, fy_stop: str, limit: int
) -> list[str]:
    """Active 法人 = had ≥1 jpi_adoption_records row in FY window.

    Wave 48 tick#6 schema-drift patch: actual table uses
    ``houjin_bangou`` (not ``applicant_houjin_bangou``) and
    ``announced_at`` (not ``award_date`` / ``announce_date``).
    """
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT houjin_bangou AS hb
              FROM jpi_adoption_records
             WHERE houjin_bangou IS NOT NULL
               AND announced_at >= ?
               AND announced_at < ?
             ORDER BY hb
             LIMIT ?
            """,
            (fy_start, fy_stop, limit),
        ).fetchall()
        return [r["hb"] for r in rows if r["hb"]]
    except sqlite3.Error as exc:
        logger.warning("candidate lookup failed: %s", exc)
        return []


def _compose_one(conn: sqlite3.Connection, houjin_id: str, fiscal_year: int) -> dict | None:
    """Mirrors api/audit_workpaper_v2.py::_build_workpaper.

    Returns None when the 法人 is unknown in jpi_houjin_master.
    """
    fy_start, fy_stop = _fy_window(fiscal_year)
    fy_end = f"{fiscal_year + 1:04d}-03-31"

    # Wave 48 tick#6 schema-drift patch: real jpi_houjin_master has no
    # `jsic_major` column. Drop it from the projection.
    try:
        meta_row = conn.execute(
            """SELECT houjin_bangou, normalized_name, address_normalized,
                      prefecture, municipality, corporation_type,
                      total_adoptions, total_received_yen
                 FROM jpi_houjin_master
                WHERE houjin_bangou = ? LIMIT 1""",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if meta_row is None:
        return None
    meta = {
        "houjin_bangou": meta_row["houjin_bangou"],
        "name": meta_row["normalized_name"],
        "address": meta_row["address_normalized"],
        "prefecture": meta_row["prefecture"],
        "municipality": meta_row["municipality"],
        "corporation_type": meta_row["corporation_type"],
        "jsic_major": None,
        "total_adoptions": meta_row["total_adoptions"],
        "total_received_yen": meta_row["total_received_yen"],
    }

    # Wave 48 tick#6 patch: real jpi_adoption_records uses
    # houjin_bangou / announced_at / amount_granted_yen / program_name_raw
    # / company_name_raw. The legacy field aliases are preserved in the
    # output envelope so downstream readers don't break.
    adoptions: list[dict] = []
    try:
        rows = conn.execute(
            """SELECT program_id, program_name_raw, company_name_raw, announced_at,
                      amount_granted_yen
                FROM jpi_adoption_records
                WHERE houjin_bangou = ?
                  AND announced_at >= ?
                  AND announced_at < ?
                ORDER BY announced_at DESC LIMIT 50""",
            (houjin_id, fy_start, fy_stop),
        ).fetchall()
        for r in rows:
            adoptions.append(
                {
                    "program_id": r["program_id"],
                    "program_name": r["program_name_raw"],
                    "applicant_name": r["company_name_raw"],
                    "award_date": r["announced_at"],
                    "amount_yen": r["amount_granted_yen"],
                    "fiscal_year": fiscal_year,
                    "announce_date": r["announced_at"],
                }
            )
    except sqlite3.Error:
        pass

    # Wave 48 tick#6 patch: real am_enforcement_detail uses
    # enforcement_id / issuance_date / reason_summary.
    enforcement: list[dict] = []
    try:
        rows = conn.execute(
            """SELECT enforcement_id, enforcement_kind, issuance_date, amount_yen,
                      reason_summary, source_url
                 FROM am_enforcement_detail
                WHERE houjin_bangou = ?
                  AND issuance_date BETWEEN ? AND ?
                ORDER BY issuance_date DESC LIMIT 30""",
            (houjin_id, fy_start, fy_end),
        ).fetchall()
        for r in rows:
            enforcement.append(
                {
                    "detail_id": r["enforcement_id"],
                    "enforcement_kind": r["enforcement_kind"],
                    "enforcement_date": r["issuance_date"],
                    "amount_yen": r["amount_yen"],
                    "summary": r["reason_summary"],
                    "source_url": r["source_url"],
                }
            )
    except sqlite3.Error:
        pass

    jurisdiction: dict = {
        "registered_prefecture": meta_row["prefecture"],
        "invoice_prefecture": None,
        "operational_top_prefecture": None,
        "mismatch": False,
    }
    try:
        inv = conn.execute(
            "SELECT prefecture FROM jpi_invoice_registrants "
            "WHERE houjin_bangou = ? ORDER BY registered_date DESC LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if inv:
            jurisdiction["invoice_prefecture"] = inv["prefecture"]
        op = conn.execute(
            "SELECT prefecture FROM jpi_adoption_records "
            "WHERE houjin_bangou = ? AND prefecture IS NOT NULL "
            "GROUP BY prefecture ORDER BY COUNT(*) DESC LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if op:
            jurisdiction["operational_top_prefecture"] = op["prefecture"]
    except sqlite3.Error:
        pass
    seen = {v for v in jurisdiction.values() if isinstance(v, str)}
    jurisdiction["mismatch"] = len(seen) > 1

    amendment_alerts: list[dict] = []
    active_pids = [a["program_id"] for a in adoptions if isinstance(a.get("program_id"), str)]
    if active_pids:
        try:
            placeholders = ",".join("?" * len(active_pids))
            amendment_alerts = [
                dict(r)
                for r in conn.execute(
                    f"""SELECT entity_id, field_name, prev_value, new_value,
                               detected_at, source_url
                         FROM am_amendment_diff
                        WHERE entity_id IN ({placeholders})
                          AND detected_at >= ?
                          AND detected_at < ?
                        ORDER BY detected_at DESC LIMIT 60""",
                    (*active_pids, fy_start, fy_stop),
                ).fetchall()
            ]
        except sqlite3.Error:
            pass

    flags: list[str] = []
    if enforcement:
        flags.append(f"FY内 行政処分 {len(enforcement)} 件 — 監査調書の重大記載項目候補。")
    if jurisdiction["mismatch"]:
        flags.append("登録/適格/操業 都道府県の3軸不一致 — 課税地・連結納税のヒアリング推奨。")
    if amendment_alerts:
        flags.append(
            f"FY内 当該採択先制度の改正イベント {len(amendment_alerts)} 件 — 適用要件再評価。"
        )
    if not adoptions:
        flags.append("FY内 採択 0 件 — 補助金収益認識の対象なし (前 FY 継続性は別途確認)。")

    return {
        "client_houjin_bangou": houjin_id,
        "fiscal_year": fiscal_year,
        "fy_window": {"start": fy_start, "end": fy_end},
        "houjin_meta": meta,
        "fy_adoptions": adoptions,
        "fy_enforcement": enforcement,
        "jurisdiction_breakdown": jurisdiction,
        "amendment_alerts": amendment_alerts,
        "counts": {
            "fy_adoption_count": len(adoptions),
            "fy_enforcement_count": len(enforcement),
            "fy_amendment_alert_count": len(amendment_alerts),
            "mismatch": jurisdiction["mismatch"],
        },
        "auditor_flags": flags,
    }


def _upsert(conn: sqlite3.Connection, envelope: dict) -> None:
    j = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """INSERT INTO am_audit_workpaper
            (houjin_bangou, fiscal_year, fy_start, fy_end,
             fy_adoption_count, fy_enforcement_count, fy_amendment_alert_count,
             jurisdiction_mismatch, auditor_flag_count,
             snapshot_json, snapshot_bytes, composed_at, composer_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(houjin_bangou, fiscal_year) DO UPDATE SET
             fy_start = excluded.fy_start,
             fy_end = excluded.fy_end,
             fy_adoption_count = excluded.fy_adoption_count,
             fy_enforcement_count = excluded.fy_enforcement_count,
             fy_amendment_alert_count = excluded.fy_amendment_alert_count,
             jurisdiction_mismatch = excluded.jurisdiction_mismatch,
             auditor_flag_count = excluded.auditor_flag_count,
             snapshot_json = excluded.snapshot_json,
             snapshot_bytes = excluded.snapshot_bytes,
             composed_at = excluded.composed_at,
             composer_version = excluded.composer_version""",
        (
            envelope["client_houjin_bangou"],
            envelope["fiscal_year"],
            envelope["fy_window"]["start"],
            envelope["fy_window"]["end"],
            envelope["counts"]["fy_adoption_count"],
            envelope["counts"]["fy_enforcement_count"],
            envelope["counts"]["fy_amendment_alert_count"],
            1 if envelope["counts"]["mismatch"] else 0,
            len(envelope["auditor_flags"]),
            j,
            len(j.encode("utf-8")),
            _now_iso(),
            "audit_workpaper_v2",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build am_audit_workpaper snapshot cache.")
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--fiscal-year", type=int, default=None, help="Single FY override.")
    ap.add_argument("--only", type=str, default=None, help="CSV of houjin_bangou.")
    ap.add_argument("--limit-houjin", type=int, default=20000)
    ap.add_argument("--max-rows", type=int, default=40000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    t0 = time.perf_counter()

    conn = _open_rw(args.db)
    run_id = _start_run(conn) if not args.dry_run else -1
    fys = [args.fiscal_year] if args.fiscal_year else [_current_fy(), _current_fy() - 1]

    scanned = upserted = skipped = errors = 0
    error_text: str | None = None

    try:
        if args.only:
            cohort = [h.strip() for h in args.only.split(",") if h.strip()]
        else:
            cohort_all: list[str] = []
            for fy in fys:
                fy_start, fy_stop = _fy_window(fy)
                cohort_all.extend(_candidate_houjin(conn, fy_start, fy_stop, args.limit_houjin))
            cohort = sorted(set(cohort_all))[: args.limit_houjin]
        logger.info("cohort size = %d, fys = %s", len(cohort), fys)

        for hb in cohort:
            for fy in fys:
                if upserted + skipped >= args.max_rows:
                    break
                scanned += 1
                try:
                    env = _compose_one(conn, hb, fy)
                except sqlite3.Error as exc:
                    errors += 1
                    error_text = str(exc)
                    continue
                if env is None:
                    skipped += 1
                    continue
                if args.dry_run:
                    upserted += 1
                    continue
                try:
                    _upsert(conn, env)
                    upserted += 1
                except sqlite3.Error as exc:
                    errors += 1
                    error_text = str(exc)
    finally:
        if run_id > 0:
            _finish_run(conn, run_id, scanned, upserted, skipped, errors, error_text)
        conn.close()

    logger.info(
        "done in %.1fs: scanned=%d upserted=%d skipped=%d errors=%d",
        time.perf_counter() - t0,
        scanned,
        upserted,
        skipped,
        errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
