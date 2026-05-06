from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient


def _usage_count(db_path: Path, key_hash: str, endpoint: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
        return int(count)
    finally:
        conn.close()


def test_autonomath_search_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api import autonomath as am_api

    endpoint = "am.certifications.search"
    key_hash = hash_api_key(paid_key)

    monkeypatch.setattr(
        am_api.tools,
        "search_certifications",
        lambda **_kwargs: {"total": 0, "limit": 1, "offset": 0, "results": []},
    )
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    before = _usage_count(seeded_db, key_hash, endpoint)
    res = client.get(
        "/v1/am/certifications",
        params={"limit": 1},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, key_hash, endpoint) == before


def test_autonomath_check_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api import autonomath as am_api

    endpoint = "am.enforcement.check"
    key_hash = hash_api_key(paid_key)

    monkeypatch.setattr(
        am_api.autonomath_wrappers,
        "check_enforcement_am",
        lambda **_kwargs: {
            "houjin_bangou": "1234567890123",
            "target_name_query": None,
            "as_of_date": "2026-05-06",
            "is_currently_barred": False,
            "active_cases": [],
            "past_cases": [],
        },
    )
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    before = _usage_count(seeded_db, key_hash, endpoint)
    res = client.get(
        "/v1/am/enforcement",
        params={"houjin_bangou": "1234567890123", "as_of_date": "2026-05-06"},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, key_hash, endpoint) == before


def test_autonomath_tax_rule_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api import autonomath as am_api

    endpoint = "am.tax_rule.get"
    key_hash = hash_api_key(paid_key)

    monkeypatch.setattr(
        am_api.tax_rule_tool,
        "get_am_tax_rule",
        lambda **_kwargs: {"rule_id": "tax-rule-1", "measure_name": "中小企業税制"},
    )
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    before = _usage_count(seeded_db, key_hash, endpoint)
    res = client.get(
        "/v1/am/tax_rule",
        params={"measure_name_or_id": "中小企業税制"},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, key_hash, endpoint) == before
