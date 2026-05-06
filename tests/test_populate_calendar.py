"""Tests for `scripts/cron/populate_program_calendar_12mo.py`.

Validates that the populate cron rebuilds `am_program_calendar_12mo`
from a seeded test DB into 5 programs × 12 months = 60 rows, with
correct is_open / deadline / notes classification per (program, month).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# Make the cron script importable as a module without installing.
_CRON = Path(__file__).resolve().parent.parent / "scripts" / "cron"
if str(_CRON) not in sys.path:
    sys.path.insert(0, str(_CRON))

import populate_program_calendar_12mo as cron  # noqa: E402

# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------


def _build_db(tmp_path: Path) -> Path:
    """Seed an autonomath-shaped sqlite file with 5 programs + rounds.

    The schema mirrors the production autonomath.db columns the cron
    actually reads from `jpi_programs`, `am_application_round`, and
    `am_program_calendar_12mo`.
    """
    db_path = tmp_path / "autonomath_test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id  TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            tier         TEXT,
            excluded     INTEGER DEFAULT 0
        );
        CREATE TABLE am_application_round (
            round_id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id TEXT NOT NULL,
            round_label TEXT NOT NULL,
            round_seq INTEGER,
            application_open_date TEXT,
            application_close_date TEXT,
            announced_date TEXT,
            disbursement_start_date TEXT,
            budget_yen INTEGER,
            status TEXT,
            source_url TEXT,
            source_fetched_at TEXT
        );
        CREATE TABLE am_program_calendar_12mo (
            program_unified_id TEXT NOT NULL,
            month_start        TEXT NOT NULL,
            is_open            INTEGER NOT NULL CHECK (is_open IN (0, 1)),
            deadline           TEXT,
            round_id_json      TEXT,
            notes              TEXT,
            computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (program_unified_id, month_start)
        );
        """
    )

    # 5 programs: 3 in-tier + 1 excluded + 1 wrong tier (must be filtered).
    conn.executemany(
        "INSERT INTO jpi_programs (unified_id, primary_name, tier, excluded) VALUES (?, ?, ?, ?)",
        [
            ("prog:s:always_open", "Always Open Program", "S", 0),
            ("prog:a:bounded_window", "Bounded Window", "A", 0),
            ("prog:b:future_round", "Future Round Only", "B", 0),
            ("prog:s:no_rounds", "No Rounds Recorded", "S", 0),
            ("prog:b:closed_past", "Closed Long Ago", "B", 0),
            # Filter targets:
            ("prog:c:wrong_tier", "C tier should skip", "C", 0),
            ("prog:s:excluded", "Excluded should skip", "S", 1),
        ],
    )

    # Rounds. Anchor everything to today so the test is time-independent.
    today = _dt.date.today()
    open_now = (today - _dt.timedelta(days=30)).isoformat()
    close_far = (today + _dt.timedelta(days=400)).isoformat()  # > 12mo
    close_in_3mo = (
        cron._add_months(cron._first_of_month(today), 3) + _dt.timedelta(days=14)
    ).isoformat()
    open_in_5mo = cron._add_months(cron._first_of_month(today), 5).isoformat()
    close_in_6mo = (
        cron._add_months(cron._first_of_month(today), 6) + _dt.timedelta(days=10)
    ).isoformat()
    open_past = (today - _dt.timedelta(days=400)).isoformat()
    close_past = (today - _dt.timedelta(days=200)).isoformat()

    conn.executemany(
        """INSERT INTO am_application_round
              (program_entity_id, round_label, round_seq,
               application_open_date, application_close_date, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
        [
            # always_open: open now, closes after horizon end -> 12 open months, no in-month deadline
            ("prog:s:always_open", "R1", 1, open_now, close_far, "open"),
            # bounded_window: open now, deadline ~ month +3
            ("prog:a:bounded_window", "R1", 1, open_now, close_in_3mo, "open"),
            # future_round: opens in 5mo, deadline at 6mo
            ("prog:b:future_round", "R1", 1, open_in_5mo, close_in_6mo, "scheduled"),
            # closed_past: round entirely before window -> no rows open
            ("prog:b:closed_past", "R1", 1, open_past, close_past, "closed"),
            # no_rounds program intentionally has zero rounds
        ],
    )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_month_grid_is_12_consecutive_first_of_months() -> None:
    today = _dt.date(2026, 5, 18)
    grid = cron._month_grid(today)
    assert len(grid) == 12
    assert grid[0] == _dt.date(2026, 5, 1)
    assert grid[1] == _dt.date(2026, 6, 1)
    assert grid[11] == _dt.date(2027, 4, 1)


def test_add_months_handles_year_rollover() -> None:
    assert cron._add_months(_dt.date(2026, 11, 1), 3) == _dt.date(2027, 2, 1)
    assert cron._add_months(_dt.date(2026, 1, 1), -1) == _dt.date(2025, 12, 1)


def test_classify_month_open_with_in_month_deadline() -> None:
    today_first = _dt.date(2026, 6, 1)
    Row = sqlite3.Row  # noqa: N806
    conn = sqlite3.connect(":memory:")
    conn.row_factory = Row
    conn.execute(
        "CREATE TABLE r (round_id INT, application_open_date TEXT, "
        "application_close_date TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO r VALUES (?, ?, ?, ?)",
        (7, "2026-05-15", "2026-06-20", "open"),
    )
    rounds = conn.execute("SELECT * FROM r").fetchall()
    is_open, deadline, ids, notes = cron._classify_month(today_first, rounds)
    assert is_open == 1
    assert deadline == "2026-06-20"
    assert ids == [7]
    assert notes == "今月締切 2026-06-20"


def test_classify_month_closed_with_next_round_hint() -> None:
    month = _dt.date(2026, 6, 1)
    Row = sqlite3.Row  # noqa: N806
    conn = sqlite3.connect(":memory:")
    conn.row_factory = Row
    conn.execute(
        "CREATE TABLE r (round_id INT, application_open_date TEXT, "
        "application_close_date TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO r VALUES (?, ?, ?, ?)",
        (9, "2026-09-01", "2026-10-31", "scheduled"),
    )
    rounds = conn.execute("SELECT * FROM r").fetchall()
    is_open, deadline, ids, notes = cron._classify_month(month, rounds)
    assert is_open == 0
    assert deadline is None
    assert ids == []
    assert notes == "次回 2026-09"


# ---------------------------------------------------------------------------
# End-to-end run
# ---------------------------------------------------------------------------


def test_run_populates_5_programs_x_12_months(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec deliverable: test DB seed → 60 rows (5 programs × 12 months)."""
    db_path = _build_db(tmp_path)

    # Stub `connect` so the cron uses a vanilla sqlite3 connection
    # against the test DB (the production connect() applies an
    # authorizer that forbids reading from `programs`-family tables on
    # autonomath.db; our test schema does not include those tables, so
    # bypassing the authorizer is safe and keeps the test hermetic).
    def _fake_connect(path: Path) -> sqlite3.Connection:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(cron, "connect", _fake_connect)

    counters = cron.run(
        am_db_path=db_path,
        tiers=("S", "A", "B"),
        max_programs=None,
        dry_run=False,
    )

    # 5 in-tier non-excluded programs × 12 months = 60.
    assert counters["programs_scanned"] == 5
    assert counters["months_per_program"] == 12
    assert counters["rows_written"] == 60

    # Verify row count physically landed.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    n = conn.execute("SELECT COUNT(*) AS c FROM am_program_calendar_12mo").fetchone()["c"]
    assert n == 60

    # Wrong-tier + excluded must NOT appear.
    forbidden = conn.execute(
        "SELECT COUNT(*) AS c FROM am_program_calendar_12mo "
        "WHERE program_unified_id IN ('prog:c:wrong_tier','prog:s:excluded')"
    ).fetchone()["c"]
    assert forbidden == 0

    # always_open: 12 open months, none with in-month deadline.
    open_count = conn.execute(
        "SELECT COUNT(*) AS c FROM am_program_calendar_12mo "
        "WHERE program_unified_id = 'prog:s:always_open' AND is_open = 1"
    ).fetchone()["c"]
    assert open_count == 12

    # closed_past + no_rounds: zero open months each.
    for pid in ("prog:b:closed_past", "prog:s:no_rounds"):
        c_open = conn.execute(
            "SELECT COUNT(*) AS c FROM am_program_calendar_12mo "
            "WHERE program_unified_id = ? AND is_open = 1",
            (pid,),
        ).fetchone()["c"]
        assert c_open == 0, f"{pid} should have 0 open months"

    # bounded_window: at least one row carries an in-month deadline note.
    deadline_rows = conn.execute(
        "SELECT COUNT(*) AS c FROM am_program_calendar_12mo "
        "WHERE program_unified_id = 'prog:a:bounded_window' "
        "AND deadline IS NOT NULL"
    ).fetchone()["c"]
    assert deadline_rows >= 1

    conn.close()


def test_run_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-running yields identical row count (DELETE-then-INSERT)."""
    db_path = _build_db(tmp_path)

    def _fake_connect(path: Path) -> sqlite3.Connection:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(cron, "connect", _fake_connect)

    cron.run(am_db_path=db_path, tiers=("S", "A", "B"), max_programs=None, dry_run=False)
    cron.run(am_db_path=db_path, tiers=("S", "A", "B"), max_programs=None, dry_run=False)

    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM am_program_calendar_12mo").fetchone()[0]
    conn.close()
    assert n == 60


def test_dry_run_writes_no_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _build_db(tmp_path)

    def _fake_connect(path: Path) -> sqlite3.Connection:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(cron, "connect", _fake_connect)

    counters = cron.run(
        am_db_path=db_path,
        tiers=("S", "A", "B"),
        max_programs=None,
        dry_run=True,
    )

    assert counters["rows_written"] == 60  # would-be count

    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM am_program_calendar_12mo").fetchone()[0]
    conn.close()
    assert n == 0


def test_max_programs_caps_universe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _build_db(tmp_path)

    def _fake_connect(path: Path) -> sqlite3.Connection:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(cron, "connect", _fake_connect)

    counters = cron.run(
        am_db_path=db_path,
        tiers=("S", "A", "B"),
        max_programs=2,
        dry_run=False,
    )
    assert counters["programs_scanned"] == 2
    assert counters["rows_written"] == 24
