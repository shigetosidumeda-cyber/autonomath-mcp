from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db
from jpintel_mcp.api.intel_news_brief import router


@pytest.fixture()
def news_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "news.db"
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
            "program:UNI-news-1",
            "recent_change.application_window",
            "公募締切が2026-06-30に変更されました",
            None,
            None,
            "https://example.go.jp/program/change",
            "2026-05-04T10:00:00Z",
        ),
        (
            "program:UNI-news-1",
            "enforcement.administrative_order",
            "不正受給に関する行政処分の公表",
            None,
            None,
            "https://example.go.jp/program/enforcement",
            "2026-05-04T11:00:00Z",
        ),
        (
            "industry:manufacturing",
            "recent_change.industry_note",
            "製造業向け設備投資枠が更新",
            None,
            None,
            "https://example.go.jp/industry/update",
            "2026-05-03T09:00:00Z",
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
def sparse_news_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "sparse-news.db"
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


def test_news_brief_happy_path(news_client: TestClient) -> None:
    resp = news_client.post("/v1/intel/news_brief", json={"program": "UNI-news-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["as_of"] == "2026-05-04T11:00:00Z"
    assert len(body["recent_changes"]) == 1
    assert "締切" in body["recent_changes"][0]["summary"]
    assert len(body["enforcement_mentions"]) == 1
    assert "行政処分" in body["enforcement_mentions"][0]["summary"]
    assert {link["url"] for link in body["source_links"]} == {
        "https://example.go.jp/program/change",
        "https://example.go.jp/program/enforcement",
    }
    assert body["known_gaps"] == []


def test_news_brief_validation_requires_query(news_client: TestClient) -> None:
    resp = news_client.post("/v1/intel/news_brief", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "missing_query"


def test_news_brief_sparse_db_graceful(sparse_news_client: TestClient) -> None:
    resp = sparse_news_client.post("/v1/intel/news_brief", json={"industry": "製造業"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["recent_changes"] == []
    assert body["enforcement_mentions"] == []
    assert body["source_links"] == []
    assert "am_entity_facts table is not available" in body["known_gaps"]
    assert "no matching local facts found for the supplied query" in body["known_gaps"]
