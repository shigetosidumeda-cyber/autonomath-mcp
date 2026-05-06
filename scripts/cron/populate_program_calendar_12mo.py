#!/usr/bin/env python3
"""Populate `am_program_calendar_12mo` (W3-12 / W3-13 fix).

What it does:
  Materializes one row per (program × month) for the next 12 months
  by joining `jpi_programs` (tier S/A/B, excluded=0) against
  `am_application_round` (Wave22 substrate, 1,256 rows). For every
  tier-S+A+B program × the rolling 12-month window from the current
  month, the row records:

    * is_open               — 1 iff any round has
                              application_open_date <= month_end AND
                              (application_close_date IS NULL OR
                               application_close_date >= month_start)
    * deadline              — earliest application_close_date that
                              falls inside the month (ISO date), else NULL
    * round_id_json         — JSON list of round_ids that intersect month
    * notes                 — short JA hint:
                                "公募中"            (is_open AND no
                                                     deadline this month)
                                "今月締切 YYYY-MM-DD" (deadline in month)
                                "次回 YYYY-MM"      (closed but next
                                                     round known)
                                NULL                (no signal)

Why this exists:
  Migration 128 (`wave24_128_am_program_calendar_12mo.sql`) created the
  table but no populate path was wired. Smoke tests UC2 / UC7 / UC10
  (`get_program_calendar_12mo` tool) returned empty results because the
  table is 0 rows.

Source of truth:
  * `jpi_programs` rows for the program universe + tier filter
    (mirrored from jpintel.db via migration 032; lives in
    autonomath.db).
  * `am_application_round` for round windows (canonical source — same
    table that `programs_active_at_v2` view (migration 070) reads).

  We deliberately do NOT use `jpi_programs.application_window_json`
  as the primary source: that JSON is sparse + non-canonical (most
  rows have null start_date / end_date), and `am_application_round`
  is the table all sibling tools (forecast_program_renewal,
  apply_eligibility_chain_am, find_combinable_programs) already
  consume. Keeping one source preserves cross-tool consistency.

Cadence:
  Monthly on the 5th 18:00 UTC (= 03:00 JST 6th). 5-day buffer after
  month-flip lets last-minute round amendments land before the
  rebuild.

Idempotency:
  DELETE-then-INSERT inside a single transaction (mirrors
  `precompute_refresh.py`). UNIQUE(program_unified_id, month_start)
  is enforced by the schema PRIMARY KEY.

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + standard library.
  * Single rw connection to autonomath.db (both source tables live
    there post migration 032).
  * Idempotent: re-running same month yields identical row set.

Usage:
    python scripts/cron/populate_program_calendar_12mo.py
    python scripts/cron/populate_program_calendar_12mo.py --dry-run
    python scripts/cron/populate_program_calendar_12mo.py --max-programs 5
    python scripts/cron/populate_program_calendar_12mo.py --tiers S,A
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.populate_program_calendar_12mo")


HORIZON_MONTHS = 12
DEFAULT_TIERS: tuple[str, ...] = ("S", "A", "B")


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.populate_program_calendar_12mo")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# ---------------------------------------------------------------------------
# Date helpers — month grid
# ---------------------------------------------------------------------------


def _first_of_month(d: _dt.date) -> _dt.date:
    return d.replace(day=1)


def _add_months(d: _dt.date, n: int) -> _dt.date:
    """Add n months to a date, returning the first-of-month result."""
    total = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(total, 12)
    return _dt.date(y, m0 + 1, 1)


def _month_grid(today: _dt.date, horizon: int = HORIZON_MONTHS) -> list[_dt.date]:
    """Return list of `horizon` first-of-month dates starting at today's month."""
    start = _first_of_month(today)
    return [_add_months(start, i) for i in range(horizon)]


def _parse_iso_date(value: str | None) -> _dt.date | None:
    """Parse ISO date prefix (handles 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS')."""
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------


def _select_target_programs(
    conn: sqlite3.Connection,
    tiers: tuple[str, ...],
    max_programs: int | None,
) -> list[sqlite3.Row]:
    """Fetch tier-filtered, non-excluded programs from jpi_programs.

    Rows are stable-ordered by unified_id so (a) re-runs visit the same
    programs in the same order and (b) --max-programs sampling is
    reproducible.
    """
    placeholders = ",".join("?" for _ in tiers)
    sql = f"""
        SELECT unified_id, primary_name, tier
          FROM jpi_programs
         WHERE tier IN ({placeholders})
           AND COALESCE(excluded, 0) = 0
         ORDER BY unified_id
    """
    params: list[object] = list(tiers)
    if max_programs is not None:
        sql += " LIMIT ?"
        params.append(int(max_programs))
    return conn.execute(sql, params).fetchall()


def _select_program_rounds(conn: sqlite3.Connection, program_unified_id: str) -> list[sqlite3.Row]:
    """All am_application_round rows for one program."""
    return conn.execute(
        """
        SELECT round_id, application_open_date, application_close_date, status
          FROM am_application_round
         WHERE program_entity_id = ?
        """,
        (program_unified_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Per-month classification
# ---------------------------------------------------------------------------


def _month_end(month_start: _dt.date) -> _dt.date:
    """Inclusive last day of the calendar month."""
    nxt = _add_months(month_start, 1)
    return nxt - _dt.timedelta(days=1)


def _classify_month(
    month_start: _dt.date,
    rounds: list[sqlite3.Row],
) -> tuple[int, str | None, list[int], str | None]:
    """Compute (is_open, deadline, round_ids, notes) for one (program, month).

    A round "intersects" month iff:
      open_date <= month_end AND (close_date IS NULL OR close_date >= month_start)

    `deadline` = earliest close_date that falls inside [month_start, month_end].
    """
    m_end = _month_end(month_start)
    intersecting_ids: list[int] = []
    deadlines_in_month: list[_dt.date] = []
    next_open_after: _dt.date | None = None

    for r in rounds:
        open_d = _parse_iso_date(r["application_open_date"])
        close_d = _parse_iso_date(r["application_close_date"])

        # Track "next round" candidates for closed-month notes.
        if (
            open_d is not None
            and open_d > m_end
            and (next_open_after is None or open_d < next_open_after)
        ):
            next_open_after = open_d

        if open_d is None:
            # Without an open date we cannot place the round in time.
            continue

        # Round must have started by month_end and not yet closed by month_start.
        opened_by_m_end = open_d <= m_end
        not_closed_before_month = (close_d is None) or (close_d >= month_start)
        if opened_by_m_end and not_closed_before_month:
            intersecting_ids.append(int(r["round_id"]))
            if close_d is not None and month_start <= close_d <= m_end:
                deadlines_in_month.append(close_d)

    is_open = 1 if intersecting_ids else 0
    deadline = min(deadlines_in_month).isoformat() if deadlines_in_month else None

    notes: str | None
    if deadline is not None:
        notes = f"今月締切 {deadline}"
    elif is_open:
        notes = "公募中"
    elif next_open_after is not None:
        notes = f"次回 {next_open_after.strftime('%Y-%m')}"
    else:
        notes = None

    return is_open, deadline, intersecting_ids, notes


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def run(
    am_db_path: Path,
    tiers: tuple[str, ...],
    max_programs: int | None,
    dry_run: bool,
    today: _dt.date | None = None,
) -> dict[str, int]:
    """Rebuild am_program_calendar_12mo and return counters.

    Counters:
      * programs_scanned     — programs visited
      * months_per_program   — horizon (12)
      * rows_written         — rows INSERTed (or would-be in dry-run)
      * rows_open            — subset where is_open = 1
    """
    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return {
            "programs_scanned": 0,
            "months_per_program": HORIZON_MONTHS,
            "rows_written": 0,
            "rows_open": 0,
        }

    today = today or _dt.date.today()
    months = _month_grid(today, HORIZON_MONTHS)

    conn = connect(am_db_path)
    try:
        # Confirm the calendar table exists. Migration 128 may not be
        # applied to the dev DB — fail loudly rather than silently no-op.
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_program_calendar_12mo'"
        ).fetchone()
        if exists is None:
            logger.error(
                "am_program_calendar_12mo_missing path=%s "
                "did_you_apply_migration=wave24_128_am_program_calendar_12mo.sql",
                am_db_path,
            )
            return {
                "programs_scanned": 0,
                "months_per_program": HORIZON_MONTHS,
                "rows_written": 0,
                "rows_open": 0,
            }

        programs = _select_target_programs(conn, tiers, max_programs)
        logger.info(
            "populate_start db=%s programs=%d tiers=%s months=%d dry_run=%s",
            am_db_path,
            len(programs),
            ",".join(tiers),
            HORIZON_MONTHS,
            dry_run,
        )

        rows_written = 0
        rows_open = 0

        if not dry_run:
            conn.execute("BEGIN")
        try:
            if not dry_run:
                conn.execute("DELETE FROM am_program_calendar_12mo")

            for p in programs:
                program_uid = p["unified_id"]
                rounds = _select_program_rounds(conn, program_uid)
                for m in months:
                    is_open, deadline, round_ids, notes = _classify_month(m, rounds)
                    rows_written += 1
                    if is_open:
                        rows_open += 1
                    if dry_run:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO am_program_calendar_12mo (
                            program_unified_id, month_start,
                            is_open, deadline, round_id_json, notes
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            program_uid,
                            m.isoformat(),
                            int(is_open),
                            deadline,
                            json.dumps(round_ids) if round_ids else None,
                            notes,
                        ),
                    )

            if not dry_run:
                conn.execute("COMMIT")
        except Exception:
            if not dry_run:
                conn.execute("ROLLBACK")
            raise

        counters = {
            "programs_scanned": len(programs),
            "months_per_program": HORIZON_MONTHS,
            "rows_written": rows_written,
            "rows_open": rows_open,
        }
        logger.info(
            "populate_done programs=%d rows=%d open=%d",
            counters["programs_scanned"],
            counters["rows_written"],
            counters["rows_open"],
        )
        return counters
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_tiers(value: str) -> tuple[str, ...]:
    parts = tuple(t.strip().upper() for t in value.split(",") if t.strip())
    valid = {"S", "A", "B", "C"}
    bad = [t for t in parts if t not in valid]
    if bad:
        raise argparse.ArgumentTypeError(f"invalid tier(s): {bad}. Allowed: {sorted(valid)}")
    return parts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Populate am_program_calendar_12mo (W3-12 / W3-13 fix)")
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--tiers",
        type=_parse_tiers,
        default=DEFAULT_TIERS,
        help="Comma-separated tier filter (default: S,A,B)",
    )
    p.add_argument(
        "--max-programs",
        type=int,
        default=None,
        help="Process only the first N programs (test mode)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute classifications but do not DELETE/INSERT",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    with heartbeat("populate_program_calendar_12mo") as hb:
        try:
            counters = run(
                am_db_path=am_db_path,
                tiers=args.tiers,
                max_programs=args.max_programs,
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("populate_program_calendar_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("rows_written", 0) or 0)
        hb["metadata"] = {
            "programs_scanned": counters.get("programs_scanned"),
            "rows_open": counters.get("rows_open"),
            "months_per_program": counters.get("months_per_program"),
            "tiers": ",".join(args.tiers),
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
