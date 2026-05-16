#!/usr/bin/env python3
"""Monthly precompute of am_subsidy_30yr_forecast (Wave 34 Axis 4c).

30-year x 12-month Markov chain trajectory per program. NO LLM, pure SQL.
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

LOG = logging.getLogger("forecast_30yr_subsidy_cycle")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_HORIZON_YEARS = 30
DEFAULT_HORIZON_MONTHS = 12

DEFAULT_TRANSITIONS = {
    "active": {"active": 0.70, "paused": 0.20, "renewed": 0.05, "sunset": 0.05},
    "paused": {"active": 0.30, "paused": 0.55, "renewed": 0.10, "sunset": 0.05},
    "renewed": {"active": 0.65, "paused": 0.20, "renewed": 0.10, "sunset": 0.05},
    "sunset": {"active": 0.0, "paused": 0.0, "renewed": 0.0, "sunset": 1.0},
}


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_tables(conn):
    sql_path = _REPO / "scripts" / "migrations" / "237_am_subsidy_30yr_forecast.sql"
    if sql_path.exists():
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())


def _candidate_programs(conn, max_programs):
    sql = (
        "SELECT program_unified_id, tier FROM jpi_programs "
        "WHERE COALESCE(excluded, 0) = 0 AND tier IN ('S','A','B','C') "
        "ORDER BY tier, program_unified_id"
    )
    if max_programs is not None:
        sql += f" LIMIT {int(max_programs)}"
    try:
        return list(conn.execute(sql))
    except sqlite3.Error:
        fallback = (
            "SELECT canonical_id AS program_unified_id, 'B' AS tier "
            "FROM am_entities WHERE record_kind = 'program' "
            f"LIMIT {int(max_programs or 50)}"
        )
        return list(conn.execute(fallback))


def _derive_transitions(conn, program_id):
    try:
        rounds = list(
            conn.execute(
                "SELECT application_open_date, application_close_date "
                "FROM am_application_round WHERE program_unified_id = ? "
                "ORDER BY application_close_date",
                (program_id,),
            )
        )
    except sqlite3.Error:
        return DEFAULT_TRANSITIONS
    if len(rounds) < 3:
        return DEFAULT_TRANSITIONS
    dates = [r["application_close_date"] for r in rounds if r["application_close_date"]]
    if len(dates) < 2:
        return DEFAULT_TRANSITIONS
    try:
        first = datetime.strptime(min(dates), "%Y-%m-%d").replace(tzinfo=UTC)
        last = datetime.strptime(max(dates), "%Y-%m-%d").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return DEFAULT_TRANSITIONS
    span_years = max(0.5, (last - first).days / 365.25)
    rounds_per_year = len(rounds) / span_years
    p_active_active = min(0.92, 0.55 + 0.12 * rounds_per_year)
    try:
        snap_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_amendment_snapshot WHERE entity_id = ?",
            (program_id,),
        ).fetchone()
        snap_density = (snap_row["n"] or 0) / max(1.0, span_years)
    except sqlite3.Error:
        snap_density = 0.0
    p_renewed_paused = min(0.30, 0.05 + 0.04 * snap_density)
    try:
        sun_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_amendment_diff "
            "WHERE program_unified_id = ? AND diff_kind = 'sunset'",
            (program_id,),
        ).fetchone()
        has_sunset = (sun_row["n"] or 0) > 0 if sun_row else False
    except sqlite3.Error:
        has_sunset = False
    p_sunset_active = 0.08 if has_sunset else 0.02
    p_sunset_paused = 0.12 if has_sunset else 0.03
    p_paused_active = max(0.02, 1.0 - p_active_active - p_sunset_active - 0.03)
    p_renewed_active = max(0.0, 1.0 - p_active_active - p_paused_active - p_sunset_active)
    p_active_paused = max(0.1, 0.45 - 0.10 * snap_density)
    p_paused_paused = max(0.0, 1.0 - p_active_paused - p_renewed_paused - p_sunset_paused)
    return {
        "active": {
            "active": p_active_active,
            "paused": p_paused_active,
            "renewed": p_renewed_active,
            "sunset": p_sunset_active,
        },
        "paused": {
            "active": p_active_paused,
            "paused": p_paused_paused,
            "renewed": p_renewed_paused,
            "sunset": p_sunset_paused,
        },
        "renewed": {"active": 0.65, "paused": 0.20, "renewed": 0.10, "sunset": 0.05},
        "sunset": {"active": 0.0, "paused": 0.0, "renewed": 0.0, "sunset": 1.0},
    }


def _initial_state(conn, program_id):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS open_rounds FROM am_application_round "
            "WHERE program_unified_id = ? AND application_close_date >= ?",
            (program_id, today),
        ).fetchone()
    except sqlite3.Error:
        return {"active": 0.5, "paused": 0.4, "renewed": 0.05, "sunset": 0.05}
    open_rounds = (row["open_rounds"] or 0) if row else 0
    if open_rounds > 0:
        return {"active": 0.85, "paused": 0.10, "renewed": 0.03, "sunset": 0.02}
    try:
        recent = conn.execute(
            "SELECT MAX(application_close_date) AS latest FROM am_application_round WHERE program_unified_id = ?",
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return {"active": 0.35, "paused": 0.55, "renewed": 0.05, "sunset": 0.05}
    latest = recent["latest"] if recent else None
    if latest:
        return {"active": 0.20, "paused": 0.70, "renewed": 0.05, "sunset": 0.05}
    return {"active": 0.35, "paused": 0.55, "renewed": 0.05, "sunset": 0.05}


def _step_markov(state, transitions):
    next_state = {"active": 0.0, "paused": 0.0, "renewed": 0.0, "sunset": 0.0}
    for s, p in state.items():
        for s2, prob in transitions.get(s, {}).items():
            next_state[s2] += p * prob
    total = sum(next_state.values())
    if total <= 0:
        return state
    return {k: v / total for k, v in next_state.items()}


def _most_likely(state):
    return max(state.items(), key=lambda kv: kv[1])[0]


def refresh(
    db_path,
    *,
    dry_run=False,
    max_programs=None,
    horizon_years=DEFAULT_HORIZON_YEARS,
    horizon_months=DEFAULT_HORIZON_MONTHS,
):
    refresh_id = f"fc30_{uuid.uuid4().hex[:10]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info(
        "forecast_30yr_subsidy_cycle start id=%s db=%s horizon=%dy x %dm",
        refresh_id,
        db_path,
        horizon_years,
        horizon_months,
    )
    conn = _connect(db_path)
    _ensure_tables(conn)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_subsidy_30yr_forecast_refresh_log "
            "(refresh_id, started_at, programs_processed) VALUES (?, ?, 0)",
            (refresh_id, started_at),
        )
        conn.commit()

    programs = _candidate_programs(conn, max_programs)
    LOG.info("candidate programs=%d", len(programs))

    rows_written = 0
    skipped = 0
    t0 = time.time()
    refreshed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")

    for pi, prog in enumerate(programs):
        program_id = prog["program_unified_id"]
        transitions = _derive_transitions(conn, program_id)
        state = _initial_state(conn, program_id)
        if all(v == 0 for v in state.values()):
            skipped += 1
            continue
        if not dry_run:
            conn.execute(
                "DELETE FROM am_subsidy_30yr_forecast WHERE program_unified_id = ?", (program_id,)
            )
        expected_calls = 0.0
        for year in range(horizon_years):
            for month in range(horizon_months):
                most_likely = _most_likely(state)
                expected_calls += state["active"] + 0.3 * state["renewed"]
                if dry_run:
                    if pi < 1 and year < 3 and month == 0:
                        LOG.info(
                            "dry-run program=%s y=%d m=%d state=%s p_active=%.2f",
                            program_id,
                            year,
                            month,
                            most_likely,
                            state["active"],
                        )
                else:
                    conn.execute(
                        "INSERT INTO am_subsidy_30yr_forecast "
                        "(program_unified_id, forecast_year_offset, horizon_month, state, "
                        " p_active, p_paused, p_sunset, p_renewed, expected_call_count, "
                        " program_tier, refreshed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            program_id,
                            year,
                            month,
                            most_likely,
                            state["active"],
                            state["paused"],
                            state["sunset"],
                            state["renewed"],
                            expected_calls,
                            prog["tier"],
                            refreshed_at,
                        ),
                    )
                    rows_written += 1
                state = _step_markov(state, transitions)
        if (pi + 1) % 500 == 0 and not dry_run:
            conn.commit()
            LOG.info(
                "progress %d/%d rows=%d elapsed=%.1fs",
                pi + 1,
                len(programs),
                rows_written,
                time.time() - t0,
            )

    if not dry_run:
        conn.commit()
        conn.execute(
            "UPDATE am_subsidy_30yr_forecast_refresh_log SET finished_at = ?, "
            "  programs_processed = ?, rows_written = ?, skipped_no_round_data = ? "
            "WHERE refresh_id = ?",
            (
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
                len(programs),
                rows_written,
                skipped,
                refresh_id,
            ),
        )
        conn.commit()
    conn.close()
    LOG.info("forecast_30yr_subsidy_cycle done programs=%d rows=%d", len(programs), rows_written)
    return {"programs": len(programs), "rows": rows_written, "skipped": skipped}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-programs", type=int, default=None)
    p.add_argument("--horizon-years", type=int, default=DEFAULT_HORIZON_YEARS)
    p.add_argument("--horizon-months", type=int, default=DEFAULT_HORIZON_MONTHS)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = refresh(
        args.autonomath_db,
        dry_run=args.dry_run,
        max_programs=args.max_programs,
        horizon_years=args.horizon_years,
        horizon_months=args.horizon_months,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
