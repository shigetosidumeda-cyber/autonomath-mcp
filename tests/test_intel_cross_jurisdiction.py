from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.intel_cross_jurisdiction import router

if TYPE_CHECKING:
    from pathlib import Path

_HOUJIN = "1234567890123"


def _client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def jurisdiction_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "jurisdiction.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE houjin_master (
                houjin_bangou TEXT PRIMARY KEY,
                prefecture TEXT
            );
            CREATE TABLE jpi_invoice_registrants (
                invoice_registration_number TEXT PRIMARY KEY,
                houjin_bangou TEXT,
                prefecture TEXT
            );
            CREATE TABLE jpi_adoption_records (
                id INTEGER PRIMARY KEY,
                houjin_bangou TEXT,
                program_id TEXT,
                prefecture TEXT
            );
            CREATE TABLE jpi_programs (
                unified_id TEXT PRIMARY KEY,
                prefecture TEXT
            );
            """
        )
        conn.execute("INSERT INTO houjin_master VALUES (?, ?)", (_HOUJIN, "東京都"))
        conn.execute(
            "INSERT INTO jpi_invoice_registrants VALUES (?, ?, ?)",
            ("T1234567890123", _HOUJIN, "神奈川県"),
        )
        conn.executemany(
            "INSERT INTO jpi_adoption_records (houjin_bangou, program_id, prefecture) VALUES (?, ?, ?)",
            [(_HOUJIN, "UNI-osaka", "大阪府"), (_HOUJIN, "UNI-tokyo", "東京都")],
        )
        conn.executemany(
            "INSERT INTO jpi_programs VALUES (?, ?)",
            [("UNI-osaka", "大阪府"), ("UNI-tokyo", "東京都")],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_cross_jurisdiction_happy_path(
    jurisdiction_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(jurisdiction_db, monkeypatch)

    res = client.post("/v1/intel/cross_jurisdiction", json={"houjin_id": f"T{_HOUJIN}"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["houjin_id"] == _HOUJIN
    assert body["consistent"] is False
    assert body["mismatch_count"] > 0
    assert body["jurisdictions"]["registered"] == "東京都"
    assert body["jurisdictions"]["invoice"] == "神奈川県"
    assert "大阪府" in body["jurisdictions"]["operational"]
    assert "税務代理ではありません" in body["_disclaimer"]


def test_cross_jurisdiction_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path / "missing.db", monkeypatch)

    res = client.post("/v1/intel/cross_jurisdiction", json={"houjin_id": "123"})

    assert res.status_code == 422


def test_cross_jurisdiction_sparse_db_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "sparse.db"
    sqlite3.connect(db_path).close()
    client = _client(db_path, monkeypatch)

    res = client.post("/v1/intel/cross_jurisdiction", json={"houjin_id": _HOUJIN})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["consistent"] is True
    assert body["mismatches"] == []
    assert body["data_coverage"]["sparse"] is True
    assert "houjin_master" in body["data_coverage"]["missing_tables"]
