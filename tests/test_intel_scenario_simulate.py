from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.intel_scenario_simulate import router

if TYPE_CHECKING:
    from pathlib import Path


_HOUJIN = "1234567890123"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def scenario_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_scenario.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE houjin_master (
                houjin_bangou TEXT PRIMARY KEY,
                normalized_name TEXT,
                prefecture TEXT,
                jsic_major TEXT,
                capital_yen INTEGER,
                employee_count INTEGER
            );
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT,
                program_kind TEXT,
                prefecture TEXT,
                amount_max_man_yen REAL,
                amount_min_man_yen REAL
            );
            CREATE TABLE am_recommended_programs (
                houjin_bangou TEXT,
                program_unified_id TEXT,
                score REAL
            );
            CREATE TABLE jpi_adoption_records (
                houjin_bangou TEXT,
                program_id TEXT
            );
            CREATE TABLE am_funding_stack_empirical (
                program_a_id TEXT,
                program_b_id TEXT,
                conflict_flag INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO houjin_master VALUES (?, ?, ?, ?, ?, ?)",
            (_HOUJIN, "株式会社シナリオ", "東京都", "E", 50_000_000, 25),
        )
        conn.executemany(
            "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("UNI-sim-A", "シナリオ補助金 A", "補助金", "東京都", 1000, 100),
                ("UNI-sim-B", "シナリオ補助金 B", "補助金", "東京都", 500, 50),
                ("UNI-sim-C", "シナリオ補助金 C", "補助金", "東京都", 300, 30),
            ],
        )
        conn.executemany(
            "INSERT INTO am_recommended_programs VALUES (?, ?, ?)",
            [
                (_HOUJIN, "UNI-sim-A", 0.60),
                (_HOUJIN, "UNI-sim-B", 0.40),
                (_HOUJIN, "UNI-sim-C", 0.50),
            ],
        )
        conn.execute(
            "INSERT INTO jpi_adoption_records VALUES (?, ?)",
            (_HOUJIN, "UNI-sim-B"),
        )
        conn.execute(
            "INSERT INTO am_funding_stack_empirical VALUES (?, ?, ?)",
            ("UNI-sim-A", "UNI-sim-B", 1),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_scenario_simulate_happy_path_returns_baseline_after_delta(
    scenario_db: Path,
) -> None:
    res = _client().post(
        "/v1/intel/scenario/simulate",
        json={
            "houjin_id": f"T{_HOUJIN}",
            "program_ids": ["UNI-sim-A"],
            "scenario": {
                "capex_yen": 20_000_000,
                "subsidy_rate": 0.5,
                "requested_amount_yen": 8_000_000,
                "probability_adjustment_pct": 10,
                "additional_program_ids": ["UNI-sim-C"],
            },
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["input"]["houjin_id"] == _HOUJIN
    assert body["houjin_profile"]["normalized_name"] == "株式会社シナリオ"
    assert body["baseline"]["program_count"] == 2
    assert body["baseline"]["estimated_amount_yen"] == 15_000_000
    assert body["after"]["program_count"] == 3
    assert body["after"]["estimated_amount_yen"] == 8_000_000
    assert body["delta"]["expected_value_yen"] != 0
    assert body["known_gaps"] == []
    assert body["_billing_unit"] == 1
    assert "採択保証" in body["_disclaimer"]


def test_scenario_simulate_requires_houjin_or_program_ids() -> None:
    res = _client().post("/v1/intel/scenario/simulate", json={})

    assert res.status_code == 422
    assert res.json()["detail"]["error"] == "missing_scenario_anchor"


def test_scenario_simulate_sparse_db_returns_known_gaps_not_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "sparse.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    res = _client().post(
        "/v1/intel/scenario/simulate",
        json={"program_ids": ["UNI-missing"], "scenario": {"requested_amount_yen": 1_000_000}},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["baseline"]["matched_program_count"] == 0
    assert body["after"]["estimated_amount_yen"] == 1_000_000
    assert "autonomath_db_unavailable" in body["known_gaps"]
    assert body["risk_notes"]
