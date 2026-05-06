from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key


def test_bids_search_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps

    endpoint = "bids.search"
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

    res = client.get(
        "/v1/bids/search",
        params={"limit": 1},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
