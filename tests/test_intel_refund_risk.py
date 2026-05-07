from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.intel_refund_risk import router

if TYPE_CHECKING:
    from pathlib import Path

_HOUJIN = "1234567890123"


def _client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def refund_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "refund.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_enforcement_detail (
                id INTEGER PRIMARY KEY,
                houjin_bangou TEXT,
                enforcement_kind TEXT,
                issuance_date TEXT,
                amount_yen INTEGER,
                related_law_ref TEXT,
                reason TEXT,
                source_url TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO am_enforcement_detail "
            "(houjin_bangou, enforcement_kind, issuance_date, amount_yen, related_law_ref, reason, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    _HOUJIN,
                    "grant_refund",
                    "2026-04-01",
                    12_000_000,
                    "UNI-refund-1",
                    "補助金返還",
                    "https://example.go.jp/refund",
                ),
                (
                    _HOUJIN,
                    "other",
                    "2026-03-01",
                    None,
                    "UNI-other",
                    "目的外使用による取消",
                    None,
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_refund_risk_happy_path(refund_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(refund_db, monkeypatch)

    res = client.post(
        "/v1/intel/refund_risk",
        json={
            "houjin_id": f"T{_HOUJIN}",
            "program_ids": ["UNI-refund-1"],
            "amount": 15_000_000,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["houjin_id"] == _HOUJIN
    assert body["risk_score"] > 0
    assert body["signals"]["evidence_count"] == 1
    assert body["signals"]["refund_or_return_count"] == 1
    assert body["signals"]["program_overlap_count"] == 1
    assert body["evidence"][0]["kind"] == "refund"
    assert "信用格付けではありません" in body["_disclaimer"]


def test_refund_risk_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(tmp_path / "missing.db", monkeypatch)

    res = client.post(
        "/v1/intel/refund_risk",
        json={"houjin_id": "not-a-number!!", "program_ids": [], "amount": 1},
    )

    assert res.status_code == 422


def test_refund_risk_sparse_db_graceful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "sparse.db"
    sqlite3.connect(db_path).close()
    client = _client(db_path, monkeypatch)

    res = client.post(
        "/v1/intel/refund_risk",
        json={"houjin_id": _HOUJIN, "program_ids": ["UNI-refund-1"], "amount": 1_000_000},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["risk_score"] == 0
    assert body["evidence"] == []
    assert body["data_coverage"]["sparse"] is True
    assert "am_enforcement_detail" in body["data_coverage"]["missing_tables"]
