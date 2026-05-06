from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest


@pytest.fixture()
def court_decision_seed(seeded_db):
    now = datetime.now(UTC).isoformat()
    decision_id = "HAN-b1llcap001"

    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO court_decisions(
                   unified_id, case_name, case_number,
                   court, court_level, decision_date, decision_type,
                   subject_area, related_law_ids_json, key_ruling,
                   source_url, fetched_at, updated_at
               )
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                decision_id,
                "テスト租税訴訟事件",
                "令和3年(行コ)第123号",
                "東京高等裁判所",
                "high",
                "2024-03-10",
                "判決",
                "租税",
                '["LAW-b1llcap001"]',
                "テスト判決の要旨。",
                "https://www.courts.go.jp/",
                now,
                now,
            ),
        )
        conn.commit()
        yield
    finally:
        conn.execute("DELETE FROM court_decisions WHERE unified_id = ?", (decision_id,))
        conn.commit()
        conn.close()


def test_court_decisions_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    court_decision_seed: None,
    seeded_db,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "court_decisions.search"),
            ).fetchone()
            return int(n)
        finally:
            conn.close()

    before = usage_count()
    monkeypatch.setattr(
        deps,
        "_metered_cap_final_check",
        lambda *_args, **_kwargs: (False, False),
    )

    r = client.get(
        "/v1/court-decisions/search",
        params={"q": "租税", "limit": 5},
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
