from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import close_stale_application_rounds as d1  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_application_round (
            round_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id       TEXT NOT NULL,
            round_label             TEXT NOT NULL,
            round_seq               INTEGER,
            application_open_date   TEXT,
            application_close_date  TEXT,
            announced_date          TEXT,
            disbursement_start_date TEXT,
            budget_yen              INTEGER,
            status                  TEXT,
            source_url              TEXT,
            source_fetched_at       TEXT,
            UNIQUE (program_entity_id, round_label)
        );
        """
    )
    return conn


def _insert_round(
    conn: sqlite3.Connection,
    *,
    round_id: int,
    close_date: str,
    status: str,
    label: str = "reviewed",
) -> None:
    conn.execute(
        """
        INSERT INTO am_application_round(
            round_id,
            program_entity_id,
            round_label,
            application_open_date,
            application_close_date,
            status,
            source_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            round_id,
            f"program:test:{round_id}",
            label,
            "2026-04-01",
            close_date,
            status,
            "https://example.go.jp/round",
        ),
    )


def test_dry_run_reports_only_stale_open_rounds() -> None:
    conn = _build_db()
    _insert_round(conn, round_id=810, close_date="2026-04-30", status="open")
    _insert_round(conn, round_id=811, close_date="2026-05-01", status="open")
    _insert_round(conn, round_id=812, close_date="2026-04-29", status="closed")

    result = d1.close_stale_application_rounds(
        conn,
        apply=False,
        today="2026-05-01",
        expected_round_ids=(810,),
    )

    assert result["mode"] == "dry_run"
    assert result["candidate_count"] == 1
    assert result["candidate_round_ids"] == [810]
    assert result["safe_to_apply"] is True
    assert result["updated_rows"] == 0


def test_apply_closes_safe_reviewed_stale_open_round() -> None:
    conn = _build_db()
    _insert_round(conn, round_id=810, close_date="2026-04-30", status="open")

    result = d1.close_stale_application_rounds(
        conn,
        apply=True,
        today="2026-05-01",
        expected_round_ids=(810,),
    )

    status = conn.execute(
        "SELECT status FROM am_application_round WHERE round_id = 810"
    ).fetchone()["status"]
    assert result["updated_rows"] == 1
    assert result["remaining_stale_open_count"] == 0
    assert status == "closed"


def test_apply_is_idempotent_after_round_is_closed() -> None:
    conn = _build_db()
    _insert_round(conn, round_id=810, close_date="2026-04-30", status="open")

    first = d1.close_stale_application_rounds(
        conn,
        apply=True,
        today="2026-05-01",
        expected_round_ids=(810,),
    )
    second = d1.close_stale_application_rounds(
        conn,
        apply=True,
        today="2026-05-01",
        expected_round_ids=(810,),
    )

    assert first["updated_rows"] == 1
    assert second["candidate_count"] == 0
    assert second["updated_rows"] == 0
    assert second["safe_to_apply"] is True


def test_apply_blocks_when_candidate_set_is_not_reviewed_safe_set() -> None:
    conn = _build_db()
    _insert_round(conn, round_id=810, close_date="2026-04-30", status="open")
    _insert_round(conn, round_id=999, close_date="2026-04-30", status="open")

    result = d1.close_stale_application_rounds(
        conn,
        apply=True,
        today="2026-05-01",
        expected_round_ids=(810,),
    )

    statuses = dict(
        conn.execute("SELECT round_id, status FROM am_application_round").fetchall()
    )
    assert result["safe_to_apply"] is False
    assert result["blocked_reason"]
    assert result["updated_rows"] == 0
    assert statuses == {810: "open", 999: "open"}
