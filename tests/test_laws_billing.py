from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


def test_laws_search_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_db: Path,
    paid_key: str,
    monkeypatch,
) -> None:
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "laws.search"),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    import jpintel_mcp.api.deps as deps

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    response = client.get(
        "/v1/laws/search",
        params={"limit": 5},
        headers={"X-API-Key": paid_key},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
