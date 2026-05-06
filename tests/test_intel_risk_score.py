from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


_TEST_HOUJIN = "1234567890123"


@pytest.fixture()
def seeded_risk_score_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    db_path = tmp_path / "autonomath_risk_score.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE houjin_master (
                houjin_bangou TEXT PRIMARY KEY,
                normalized_name TEXT,
                prefecture TEXT,
                municipality TEXT,
                address_normalized TEXT,
                jsic_major TEXT,
                total_received_yen INTEGER
            );
            CREATE TABLE am_enforcement_detail (
                enforcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT,
                houjin_bangou TEXT,
                target_name TEXT,
                enforcement_kind TEXT,
                issuance_date TEXT,
                related_law_ref TEXT,
                amount_yen INTEGER
            );
            CREATE TABLE jpi_invoice_registrants (
                invoice_registration_number TEXT PRIMARY KEY,
                houjin_bangou TEXT,
                prefecture TEXT,
                registered_date TEXT,
                revoked_date TEXT,
                expired_date TEXT
            );
            CREATE TABLE jpi_adoption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                houjin_bangou TEXT,
                program_id TEXT,
                prefecture TEXT
            );
            CREATE TABLE am_amendment_diff (
                diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT,
                detected_at TEXT
            );
            CREATE TABLE am_adopted_company_features (
                houjin_bangou TEXT PRIMARY KEY,
                dominant_jsic_major TEXT,
                enforcement_count INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO houjin_master VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _TEST_HOUJIN,
                "株式会社リスク",
                "東京都",
                "千代田区",
                "東京都千代田区",
                "E",
                12_000_000,
            ),
        )
        conn.executemany(
            "INSERT INTO houjin_master VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("9999999999991", "同業A", "東京都", None, None, "E", 15_000_000),
                ("9999999999992", "同業B", "東京都", None, None, "E", 18_000_000),
            ],
        )
        conn.executemany(
            "INSERT INTO am_enforcement_detail "
            "(entity_id, houjin_bangou, target_name, enforcement_kind, issuance_date, related_law_ref, amount_yen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"houjin:{_TEST_HOUJIN}",
                    _TEST_HOUJIN,
                    "株式会社リスク",
                    "grant_refund",
                    "2026-04-01",
                    "UNI-risk-1",
                    12_000_000,
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    _TEST_HOUJIN,
                    "株式会社リスク",
                    "business_improvement",
                    "2025-10-01",
                    None,
                    None,
                ),
            ],
        )
        conn.execute(
            "INSERT INTO jpi_invoice_registrants VALUES (?, ?, ?, ?, ?, ?)",
            ("T1234567890123", _TEST_HOUJIN, "神奈川県", "2023-10-01", None, None),
        )
        conn.execute(
            "INSERT INTO jpi_adoption_records (houjin_bangou, program_id, prefecture) VALUES (?, ?, ?)",
            (_TEST_HOUJIN, "UNI-risk-1", "大阪府"),
        )
        conn.execute(
            "INSERT INTO am_amendment_diff (entity_id, detected_at) VALUES (?, ?)",
            ("UNI-risk-1", "2026-03-01T00:00:00Z"),
        )
        conn.executemany(
            "INSERT INTO am_adopted_company_features VALUES (?, ?, ?)",
            [
                (_TEST_HOUJIN, "E", 2),
                ("9999999999991", "E", 0),
                ("9999999999992", "E", 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


@pytest.fixture()
def risk_score_client(seeded_db: Path, seeded_risk_score_db: Path) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


def test_risk_score_happy_path_returns_all_axes(risk_score_client: TestClient) -> None:
    res = risk_score_client.post(
        "/v1/intel/risk_score",
        json={"houjin_id": f"T{_TEST_HOUJIN}"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["houjin_id"] == _TEST_HOUJIN
    assert body["name"] == "株式会社リスク"
    assert body["total_score"] > 0
    assert body["risk_label"] in {"low", "med", "high", "critical"}
    assert body["axes"]["enforcement_risk"]["evidence_count"] == 2
    assert body["axes"]["refund_risk"]["historical_refund_count"] == 1
    assert body["axes"]["invoice_compliance_risk"]["registered"] is True
    assert body["axes"]["jurisdiction_drift_risk"]["divergence_count"] == 2
    assert body["_billing_unit"] == 1
    assert "THIS IS NOT A CREDIT RATING" in body["_disclaimer"]


def test_risk_score_include_axes_filters_payload(risk_score_client: TestClient) -> None:
    res = risk_score_client.post(
        "/v1/intel/risk_score",
        json={"houjin_id": _TEST_HOUJIN, "include_axes": ["refund"]},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["axes_evaluated"] == ["refund"]
    assert set(body["axes"]) == {"refund_risk"}


def test_risk_score_unknown_houjin_returns_404(risk_score_client: TestClient) -> None:
    res = risk_score_client.post(
        "/v1/intel/risk_score",
        json={"houjin_id": "9999999999999"},
    )

    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "houjin_not_found"


def test_risk_score_paid_final_cap_failure_returns_503_without_usage_event(
    risk_score_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    res = risk_score_client.post(
        "/v1/intel/risk_score",
        json={"houjin_id": _TEST_HOUJIN},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, "intel.risk_score"),
        ).fetchone()
    finally:
        conn.close()

    assert n == 0
