"""Tests for Moat N2 portfolio MCP wrappers.

Covers ``get_houjin_portfolio`` and ``find_gap_programs`` against a
synthetic ``am_houjin_program_portfolio`` table so the tests are
hermetic and do not require the full 12.7 GB ``autonomath.db``. The
schema is embedded inline so the test does not couple to the SQL
migration file path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS am_houjin_program_portfolio (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou        TEXT NOT NULL,
    program_id           TEXT NOT NULL,
    applicability_score  REAL NOT NULL,
    score_industry       REAL NOT NULL DEFAULT 0.0,
    score_size           REAL NOT NULL DEFAULT 0.0,
    score_region         REAL NOT NULL DEFAULT 0.0,
    score_sector         REAL NOT NULL DEFAULT 0.0,
    score_target_form    REAL NOT NULL DEFAULT 0.0,
    applied_status       TEXT NOT NULL DEFAULT 'unknown',
    applied_at           TEXT,
    deadline             TEXT,
    deadline_kind        TEXT,
    priority_rank        INTEGER,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    method               TEXT NOT NULL DEFAULT 'lane_n2_deterministic_v1',
    notes                TEXT
);
CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin
    ON am_houjin_program_portfolio(houjin_bangou, applicability_score DESC);
CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin_priority
    ON am_houjin_program_portfolio(houjin_bangou, priority_rank ASC);
CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin_unapplied
    ON am_houjin_program_portfolio(houjin_bangou, applied_status, applicability_score DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_am_hpp_houjin_program_method
    ON am_houjin_program_portfolio(houjin_bangou, program_id, method);
"""


def _seed_portfolio_db(db_path: Path) -> None:
    """Apply schema + seed rows for two houjin_bangou.

    Houjin A (1111111111111): 3 unapplied + 1 applied + 1 unknown
    Houjin B (2222222222222): empty (no rows)
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        rows = [
            (
                "1111111111111",
                "UNI-prog-A",
                95.0,
                30.0,
                25.0,
                25.0,
                10.0,
                5.0,
                "unapplied",
                None,
                "2026-06-30",
                "end_date",
                1,
                "2026-05-17T00:00:00Z",
                "lane_n2_deterministic_v1",
            ),
            (
                "1111111111111",
                "UNI-prog-B",
                80.0,
                30.0,
                20.0,
                20.0,
                10.0,
                0.0,
                "unapplied",
                None,
                None,
                "none",
                2,
                "2026-05-17T00:00:00Z",
                "lane_n2_deterministic_v1",
            ),
            (
                "1111111111111",
                "UNI-prog-C",
                75.0,
                30.0,
                20.0,
                15.0,
                10.0,
                0.0,
                "unapplied",
                None,
                None,
                "rolling",
                3,
                "2026-05-17T00:00:00Z",
                "lane_n2_deterministic_v1",
            ),
            (
                "1111111111111",
                "UNI-prog-D",
                70.0,
                25.0,
                20.0,
                15.0,
                10.0,
                0.0,
                "applied",
                "2025-08-01",
                None,
                "none",
                4,
                "2026-05-17T00:00:00Z",
                "lane_n2_deterministic_v1",
            ),
            (
                "1111111111111",
                "UNI-prog-E",
                60.0,
                10.0,
                25.0,
                15.0,
                10.0,
                0.0,
                "unknown",
                None,
                None,
                "none",
                5,
                "2026-05-17T00:00:00Z",
                "lane_n2_deterministic_v1",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO am_houjin_program_portfolio (
                houjin_bangou, program_id, applicability_score,
                score_industry, score_size, score_region, score_sector,
                score_target_form, applied_status, applied_at, deadline,
                deadline_kind, priority_rank, computed_at, method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def portfolio_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "autonomath_n2.db"
    _seed_portfolio_db(db)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db))

    from jpintel_mcp.mcp.autonomath_tools import db as autonomath_db

    autonomath_db.close_all()
    monkeypatch.setattr(autonomath_db, "AUTONOMATH_DB_PATH", db)
    return db


def test_get_houjin_portfolio_ok(portfolio_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import get_houjin_portfolio

    res = get_houjin_portfolio(houjin_bangou="1111111111111")
    assert res["primary_result"]["status"] == "ok"
    assert res["primary_result"]["houjin_bangou"] == "1111111111111"
    summary = res["primary_result"]["summary"]
    assert summary["total"] == 5
    assert summary["applied"] == 1
    assert summary["unapplied"] == 3
    assert summary["unknown"] == 1
    assert summary["top_score"] == 95.0
    ranks = [r["priority_rank"] for r in res["results"]]
    assert ranks == [1, 2, 3, 4, 5]
    first = res["results"][0]
    assert first["program_id"] == "UNI-prog-A"
    assert first["score_breakdown"]["industry"] == 30.0
    assert first["score_breakdown"]["region"] == 25.0
    assert "_disclaimer" in res
    assert res["_billing_unit"] == 1


def test_get_houjin_portfolio_empty(portfolio_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import get_houjin_portfolio

    res = get_houjin_portfolio(houjin_bangou="2222222222222")
    assert res["primary_result"]["status"] == "no_portfolio_rows"
    assert res["total"] == 0
    assert res["results"] == []


def test_get_houjin_portfolio_pending_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "nope.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(missing))

    from jpintel_mcp.mcp.autonomath_tools import db as autonomath_db

    autonomath_db.close_all()
    monkeypatch.setattr(autonomath_db, "AUTONOMATH_DB_PATH", missing)

    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import get_houjin_portfolio

    res = get_houjin_portfolio(houjin_bangou="9999999999999")
    assert res["primary_result"]["status"] == "pending_upstream_lane"
    assert res["primary_result"]["lane_id"] == "N2"


def test_find_gap_programs_ok(portfolio_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import find_gap_programs

    res = find_gap_programs(houjin_bangou="1111111111111", top_n=20)
    assert res["primary_result"]["status"] == "ok"
    summary = res["primary_result"]["summary"]
    assert summary["total_gap_programs"] == 3
    assert summary["top_score"] == 95.0
    assert summary["earliest_deadline"] == "2026-06-30"
    for row in res["results"]:
        assert row["applied_status"] == "unapplied"
    program_ids = [r["program_id"] for r in res["results"]]
    assert program_ids == ["UNI-prog-A", "UNI-prog-B", "UNI-prog-C"]


def test_find_gap_programs_respects_top_n(portfolio_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import find_gap_programs

    res = find_gap_programs(houjin_bangou="1111111111111", top_n=2)
    assert res["total"] == 2
    assert [r["program_id"] for r in res["results"]] == ["UNI-prog-A", "UNI-prog-B"]


def test_find_gap_programs_empty(portfolio_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import find_gap_programs

    res = find_gap_programs(houjin_bangou="2222222222222")
    assert res["primary_result"]["status"] == "no_portfolio_rows"
    assert res["results"] == []


def test_moat_n2_no_llm_call() -> None:
    """Smoke: the module must not import any LLM SDK."""
    import jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import anthropic", "import openai", "import google.generativeai"):
        assert forbidden not in src, f"LLM SDK import detected: {forbidden}"
