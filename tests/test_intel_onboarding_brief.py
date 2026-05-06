from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db
from jpintel_mcp.api.intel_onboarding_brief import router


HOUJIN_ID = "1010001000001"


@pytest.fixture()
def onboarding_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "onboarding.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_url TEXT,
            fetched_at TEXT
        )
        """
    )
    rows = [
        (
            f"houjin:{HOUJIN_ID}",
            "corp.name",
            "テスト株式会社",
            None,
            None,
            "https://example.go.jp/houjin/profile",
            "2026-05-04T09:00:00Z",
        ),
        (
            f"houjin:{HOUJIN_ID}",
            "corp.prefecture",
            "東京都",
            None,
            None,
            "https://example.go.jp/houjin/profile",
            "2026-05-04T09:00:00Z",
        ),
        (
            f"houjin:{HOUJIN_ID}",
            "corp.employee_count",
            None,
            24,
            None,
            "https://example.go.jp/houjin/profile",
            "2026-05-04T09:00:00Z",
        ),
        (
            f"houjin:{HOUJIN_ID}",
            "corp.capital_amount",
            None,
            10000000,
            None,
            "https://example.go.jp/houjin/profile",
            "2026-05-04T09:00:00Z",
        ),
        (
            f"houjin:{HOUJIN_ID}",
            "corp.enforcement_count",
            None,
            1,
            None,
            "https://example.go.jp/houjin/enforcement",
            "2026-05-04T12:00:00Z",
        ),
    ]
    conn.executemany(
        "INSERT INTO am_entity_facts("
        " entity_id, field_name, field_value_text, field_value_numeric,"
        " field_value_json, source_url, fetched_at"
        ") VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


@pytest.fixture()
def sparse_onboarding_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "sparse-onboarding.db"
    sqlite3.connect(db_path).close()
    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_onboarding_brief_happy_path(onboarding_client: TestClient) -> None:
    resp = onboarding_client.post(
        "/v1/intel/onboarding_brief",
        json={
            "houjin_id": HOUJIN_ID,
            "customer_profile": {"industry": "製造業"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["houjin_id"] == HOUJIN_ID
    assert body["customer_profile"]["name"] == "テスト株式会社"
    assert body["customer_profile"]["industry"] == "製造業"
    assert body["customer_profile"]["employees"] == 24
    assert body["first_week_checklist"]
    assert len(body["due_diligence_prompts"]) >= 3
    assert any(flag["level"] == "high" for flag in body["risk_flags"])
    assert any(call["call"] == "Risk review call" for call in body["recommended_next_calls"])
    assert {link["url"] for link in body["source_links"]} == {
        "https://example.go.jp/houjin/profile",
        "https://example.go.jp/houjin/enforcement",
    }
    assert body["as_of"] == "2026-05-04T12:00:00Z"


def test_onboarding_brief_validation_requires_profile(
    onboarding_client: TestClient,
) -> None:
    resp = onboarding_client.post("/v1/intel/onboarding_brief", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "missing_profile"


def test_onboarding_brief_sparse_db_graceful(
    sparse_onboarding_client: TestClient,
) -> None:
    resp = sparse_onboarding_client.post(
        "/v1/intel/onboarding_brief",
        json={"houjin_id": HOUJIN_ID},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["first_week_checklist"] == []
    assert body["due_diligence_prompts"] == []
    assert body["risk_flags"] == []
    assert body["recommended_next_calls"] == []
    assert body["source_links"] == []
    assert "am_entity_facts table is not available" in body["known_gaps"]
    assert "no local facts found for houjin_id" in body["known_gaps"]
