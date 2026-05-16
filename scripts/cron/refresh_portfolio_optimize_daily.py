#!/usr/bin/env python3
"""Daily precompute of am_portfolio_optimize (Wave 34 Axis 4a).

Folds (法人 x 11,601 programs x 8 業法 x 23 業種 x eligibility chain)
into a per-houjin TOP 8 store so the API/MCP read path is a single
SELECT. NO LLM. Pure SQL + Python rule engine.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("refresh_portfolio_optimize_daily")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_TOP_N = 8
DEFAULT_MAX_HOUJIN = 100_000

WEIGHT_ELIGIBILITY_PASS = 25
WEIGHT_AMOUNT_BAND_FIT = 20
WEIGHT_JSIC_ALIGNMENT = 15
WEIGHT_REGION_MATCH = 15
WEIGHT_COMPAT_WITH_OTHERS = 10
WEIGHT_APPLICATION_WINDOW = 10
WEIGHT_FRESHNESS = 5


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    sql_path = _REPO / "scripts" / "migrations" / "235_am_portfolio_optimize.sql"
    if sql_path.exists():
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())


def _cohort_houjin(conn: sqlite3.Connection, max_houjin: int) -> list[str]:
    rows: list[str] = []
    try:
        for row in conn.execute(
            "SELECT houjin_bangou FROM jpi_adoption_records "
            "WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> '' "
            "GROUP BY houjin_bangou ORDER BY COUNT(*) DESC LIMIT ?",
            (max_houjin,),
        ):
            rows.append(str(row[0]))
    except sqlite3.Error as exc:
        LOG.warning("jpi_adoption_records walk failed (%s)", exc)
    if rows:
        return rows
    try:
        for row in conn.execute(
            "SELECT canonical_id FROM am_entities "
            "WHERE record_kind = 'corporate_entity' "
            "ORDER BY canonical_id LIMIT ?",
            (max_houjin,),
        ):
            rows.append(str(row[0]))
    except sqlite3.Error as exc:
        LOG.warning("am_entities walk failed: %s", exc)
    return rows


def _candidate_programs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    try:
        return list(
            conn.execute(
                "SELECT program_unified_id, primary_name, tier, "
                "       prefecture, jsic_major, jsic_middle, "
                "       amount_min_yen, amount_max_yen "
                "FROM jpi_programs "
                "WHERE COALESCE(excluded, 0) = 0 "
                "  AND tier IN ('S','A','B','C') "
                "ORDER BY tier, program_unified_id"
            )
        )
    except sqlite3.Error as exc:
        LOG.warning("jpi_programs walk failed: %s", exc)
        try:
            return list(
                conn.execute(
                    "SELECT canonical_id AS program_unified_id, primary_name, "
                    "       'B' AS tier, NULL AS prefecture, NULL AS jsic_major, "
                    "       NULL AS jsic_middle, NULL AS amount_min_yen, "
                    "       NULL AS amount_max_yen "
                    "FROM am_entities WHERE record_kind = 'program' LIMIT 200"
                )
            )
        except sqlite3.Error as fallback_exc:
            LOG.warning("am_entities program fallback failed: %s", fallback_exc)
            return []


def _eligibility_pass(conn: sqlite3.Connection, houjin_bangou: str, program_id: str) -> float:
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "       SUM(CASE WHEN gate_outcome = 'pass' THEN 1 ELSE 0 END) AS passed "
            "FROM am_program_eligibility_predicate "
            "WHERE program_unified_id = ? AND houjin_bangou = ?",
            (program_id, houjin_bangou),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    if row is None or not row["total"]:
        return 0.5
    return float(row["passed"] or 0) / float(row["total"])


def _amount_band_fit(conn: sqlite3.Connection, houjin_bangou: str, program: sqlite3.Row) -> float:
    amount_min = program["amount_min_yen"]
    amount_max = program["amount_max_yen"]
    if amount_min is None and amount_max is None:
        return 0.5
    try:
        adopted = conn.execute(
            "SELECT COUNT(*) AS hits FROM jpi_adoption_records "
            "WHERE houjin_bangou = ? "
            "  AND amount_yen BETWEEN COALESCE(?, 0) AND COALESCE(?, 999999999999)",
            (houjin_bangou, amount_min, amount_max),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    hits = adopted["hits"] if adopted else 0
    if hits and hits > 0:
        return 1.0
    try:
        history = conn.execute(
            "SELECT COUNT(*) AS hits FROM jpi_adoption_records WHERE houjin_bangou = ?",
            (houjin_bangou,),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    if history and history["hits"] > 0:
        return 0.5
    return 0.3


def _jsic_alignment(houjin_jsic: tuple[str | None, str | None], program: sqlite3.Row) -> float:
    program_major = program["jsic_major"]
    if program_major is None or houjin_jsic[0] is None:
        return 0.4
    if program_major != houjin_jsic[0]:
        return 0.0
    program_middle = program["jsic_middle"]
    if program_middle is None or houjin_jsic[1] is None:
        return 0.7
    return 1.0 if program_middle == houjin_jsic[1] else 0.7


def _region_match(houjin_pref: str | None, program: sqlite3.Row) -> float:
    program_pref = program["prefecture"]
    if program_pref is None or program_pref == "" or program_pref == "zenkoku":
        return 1.0
    if houjin_pref is None:
        return 0.5
    return 1.0 if program_pref == houjin_pref else 0.0


def _compat_with_others(conn: sqlite3.Connection, program_id: str) -> float:
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_compat_matrix "
            "WHERE program_a_unified_id = ? AND compat_status = 'compatible'",
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    n = row["n"] if row else 0
    if n >= 5:
        return 1.0
    if n >= 1:
        return 0.5
    return 0.0


def _application_window(conn: sqlite3.Connection, program_id: str) -> float:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        row = conn.execute(
            "SELECT MAX(application_close_date) AS max_close, COUNT(*) AS n "
            "FROM am_application_round WHERE program_unified_id = ?",
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    if row is None or (row["n"] or 0) == 0:
        return 0.5
    if row["max_close"] is None:
        return 0.5
    return 1.0 if row["max_close"] >= today else 0.0


def _freshness(conn: sqlite3.Connection, program_id: str) -> float:
    try:
        row = conn.execute(
            "SELECT MAX(diff_at) AS latest FROM am_amendment_diff WHERE program_unified_id = ?",
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return 0.5
    latest = row["latest"] if row else None
    if latest is None:
        return 0.5
    try:
        diff_days = (datetime.now(UTC) - datetime.fromisoformat(latest.replace("Z", "+00:00"))).days
    except (ValueError, TypeError):
        return 0.5
    if diff_days <= 90:
        return 1.0
    if diff_days <= 365:
        return 0.5
    return 0.3


def _houjin_jsic(
    conn: sqlite3.Connection, houjin_bangou: str
) -> tuple[str | None, str | None, str | None]:
    for table in ("jpi_houjin_master", "houjin_master"):
        try:
            row = conn.execute(
                f"SELECT jsic_major, jsic_middle, prefecture FROM {table} WHERE houjin_bangou = ?",
                (houjin_bangou,),
            ).fetchone()
        except sqlite3.Error:
            continue
        if row is not None:
            return (row["jsic_major"], row["jsic_middle"], row["prefecture"])
    return (None, None, None)


def _score_pair(conn, houjin_bangou, houjin_axes, program):
    elig = _eligibility_pass(conn, houjin_bangou, program["program_unified_id"])
    amount = _amount_band_fit(conn, houjin_bangou, program)
    jsic = _jsic_alignment((houjin_axes[0], houjin_axes[1]), program)
    region = _region_match(houjin_axes[2], program)
    compat = _compat_with_others(conn, program["program_unified_id"])
    window = _application_window(conn, program["program_unified_id"])
    freshness = _freshness(conn, program["program_unified_id"])
    composite = int(
        round(
            WEIGHT_ELIGIBILITY_PASS * elig
            + WEIGHT_AMOUNT_BAND_FIT * amount
            + WEIGHT_JSIC_ALIGNMENT * jsic
            + WEIGHT_REGION_MATCH * region
            + WEIGHT_COMPAT_WITH_OTHERS * compat
            + WEIGHT_APPLICATION_WINDOW * window
            + WEIGHT_FRESHNESS * freshness
        )
    )
    composite = max(0, min(100, composite))
    return {
        "elig": elig,
        "amount": amount,
        "jsic": jsic,
        "region": region,
        "compat": compat,
        "window": window,
        "freshness": freshness,
        "score": float(composite),
    }


def refresh(db_path, *, dry_run=False, max_houjin=DEFAULT_MAX_HOUJIN, top_n=DEFAULT_TOP_N):
    refresh_id = f"po_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info("refresh_portfolio_optimize_daily start id=%s db=%s", refresh_id, db_path)
    conn = _connect(db_path)
    _ensure_tables(conn)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_portfolio_optimize_refresh_log "
            "(refresh_id, started_at, houjin_count) VALUES (?, ?, 0)",
            (refresh_id, started_at),
        )
        conn.commit()

    houjin_list = _cohort_houjin(conn, max_houjin)
    LOG.info("cohort houjin=%d", len(houjin_list))
    programs = _candidate_programs(conn)
    LOG.info("candidate programs=%d", len(programs))

    pairs_written = 0
    skipped = 0
    t0 = time.time()

    for hi, houjin in enumerate(houjin_list):
        axes = _houjin_jsic(conn, houjin)
        scored = []
        for prog in programs:
            scores = _score_pair(conn, houjin, axes, prog)
            scored.append((int(scores["score"]), scores, prog))
        scored.sort(key=lambda t: (-t[0], t[2]["tier"] or "Z", t[2]["program_unified_id"]))
        top = scored[:top_n]
        if not top:
            skipped += 1
            continue
        if dry_run:
            pairs_written += len(top)
            if hi < 3:
                LOG.info(
                    "dry-run houjin=%s top=%s",
                    houjin,
                    [(t[0], t[2]["program_unified_id"]) for t in top],
                )
            continue
        conn.execute("DELETE FROM am_portfolio_optimize WHERE houjin_bangou = ?", (houjin,))
        for rank, (score, parts, prog) in enumerate(top, start=1):
            reason_json = json.dumps({"signals": parts}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO am_portfolio_optimize "
                "(houjin_bangou, rank, program_unified_id, program_primary_name, "
                " score_0_100, eligibility_pass_score, amount_band_fit_score, "
                " jsic_alignment_score, region_match_score, compat_with_others_score, "
                " application_window_score, freshness_score, reason_json, tier, "
                " program_amount_max_yen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    houjin,
                    rank,
                    prog["program_unified_id"],
                    prog["primary_name"],
                    score,
                    parts["elig"],
                    parts["amount"],
                    parts["jsic"],
                    parts["region"],
                    parts["compat"],
                    parts["window"],
                    parts["freshness"],
                    reason_json,
                    prog["tier"],
                    prog["amount_max_yen"],
                ),
            )
            pairs_written += 1
        if (hi + 1) % 1000 == 0:
            conn.commit()
            LOG.info(
                "progress houjin=%d/%d pairs=%d elapsed=%.1fs",
                hi + 1,
                len(houjin_list),
                pairs_written,
                time.time() - t0,
            )

    if not dry_run:
        conn.commit()
        conn.execute(
            "UPDATE am_portfolio_optimize_refresh_log SET finished_at = ?, "
            "  houjin_count = ?, program_pairs_written = ?, skipped_no_data = ? "
            "WHERE refresh_id = ?",
            (
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
                len(houjin_list),
                pairs_written,
                skipped,
                refresh_id,
            ),
        )
        conn.commit()

    conn.close()
    LOG.info(
        "refresh_portfolio_optimize_daily done houjin=%d pairs=%d skipped=%d elapsed=%.1fs",
        len(houjin_list),
        pairs_written,
        skipped,
        time.time() - t0,
    )
    return {"houjin": len(houjin_list), "pairs": pairs_written, "skipped": skipped}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-houjin", type=int, default=DEFAULT_MAX_HOUJIN)
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = refresh(
        args.autonomath_db, dry_run=args.dry_run, max_houjin=args.max_houjin, top_n=args.top_n
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
