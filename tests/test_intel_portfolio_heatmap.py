from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db, hash_api_key
from jpintel_mcp.api.intel_portfolio_heatmap import router

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def portfolio_heatmap_client(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    missing_autonomath = tmp_path / "missing-autonomath.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing_autonomath))

    from jpintel_mcp.config import settings
    from jpintel_mcp.mcp.autonomath_tools import db as autonomath_db

    monkeypatch.setattr(settings, "autonomath_db_path", missing_autonomath)
    monkeypatch.setattr(autonomath_db, "AUTONOMATH_DB_PATH", missing_autonomath)
    autonomath_db.close_all()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        conn = sqlite3.connect(seeded_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_portfolio_heatmap_paid_final_cap_failure_returns_503_without_usage_event(
    portfolio_heatmap_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps

    endpoint = "intel.portfolio_heatmap"
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    res = portfolio_heatmap_client.post(
        "/v1/intel/portfolio_heatmap",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-b-1"]},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
