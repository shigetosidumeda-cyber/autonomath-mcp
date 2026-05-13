from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db, hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def competitor_landscape_client(
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

    import jpintel_mcp.api.intel_competitor_landscape as landscape_mod

    app = FastAPI()
    app.include_router(landscape_mod.router)

    def override_db():
        conn = sqlite3.connect(seeded_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_competitor_landscape_paid_final_cap_failure_returns_503_without_usage_event(
    competitor_landscape_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.intel_competitor_landscape as landscape_mod

    def _reject_log_usage(*_args: object, **kwargs: object) -> None:
        assert kwargs.get("strict_metering") is True
        raise HTTPException(
            status_code=503,
            detail={
                "code": "billing_cap_final_check_failed",
                "message": (
                    "This paid response was not delivered because the final "
                    "billing-cap check rejected the metered charge."
                ),
            },
        )

    endpoint = "intel.competitor_landscape"
    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(landscape_mod, "log_usage", _reject_log_usage)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    res = competitor_landscape_client.post(
        "/v1/intel/competitor_landscape",
        json={"industry": "E", "peer_limit": 3},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    assert after == before
