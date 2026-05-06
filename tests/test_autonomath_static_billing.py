from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


def _usage_count(seeded_db: Path, *, key_hash: str, endpoint: str) -> int:
    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _latest_usage_status(seeded_db: Path, *, key_hash: str, endpoint: str) -> int:
    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT status FROM usage_events WHERE key_hash = ? AND endpoint = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (key_hash, endpoint),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("method", "path", "json_body", "endpoint", "expected_status"),
    [
        ("GET", "/v1/am/static/does_not_exist", None, "am.static.get", 404),
        (
            "GET",
            "/v1/am/example_profiles/unknown",
            None,
            "am.example_profiles.get",
            404,
        ),
        (
            "GET",
            "/v1/am/templates/saburoku_kyotei/metadata",
            None,
            "am.template.metadata",
            503,
        ),
        (
            "POST",
            "/v1/am/templates/saburoku_kyotei",
            {},
            "am.template.render",
            503,
        ),
    ],
)
def test_autonomath_failure_responses_record_actual_usage_status(
    client,
    seeded_db: Path,
    paid_key: str,
    method: str,
    path: str,
    json_body: dict | None,
    endpoint: str,
    expected_status: int,
) -> None:
    key_hash = hash_api_key(paid_key)

    response = client.request(
        method,
        path,
        headers={"X-API-Key": paid_key},
        json=json_body,
    )

    assert response.status_code == expected_status, response.text
    assert _latest_usage_status(seeded_db, key_hash=key_hash, endpoint=endpoint) == (
        expected_status
    )


def test_autonomath_enabled_template_error_records_422_usage_status(
    client,
    seeded_db: Path,
    paid_key: str,
    monkeypatch,
) -> None:
    from jpintel_mcp.api import autonomath as am_api

    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(am_api.settings, "saburoku_kyotei_enabled", True)

    response = client.post(
        "/v1/am/templates/saburoku_kyotei",
        headers={"X-API-Key": paid_key},
        json={},
    )

    assert response.status_code == 422, response.text
    assert (
        _latest_usage_status(
            seeded_db,
            key_hash=key_hash,
            endpoint="am.template.render",
        )
        == 422
    )


def test_static_list_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_db: Path,
    paid_key: str,
    monkeypatch,
) -> None:
    import jpintel_mcp.api.deps as deps

    key_hash = hash_api_key(paid_key)
    before = _usage_count(seeded_db, key_hash=key_hash, endpoint="am.static.list")
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    response = client.get("/v1/am/static", headers={"X-API-Key": paid_key})

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, key_hash=key_hash, endpoint="am.static.list") == before


def test_example_profile_get_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_db: Path,
    paid_key: str,
    monkeypatch,
) -> None:
    import jpintel_mcp.api.deps as deps

    key_hash = hash_api_key(paid_key)
    before = _usage_count(seeded_db, key_hash=key_hash, endpoint="am.example_profiles.get")
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    response = client.get("/v1/am/example_profiles/minimal", headers={"X-API-Key": paid_key})

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, key_hash=key_hash, endpoint="am.example_profiles.get") == before
