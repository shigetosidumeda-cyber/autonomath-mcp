"""Regression: /v1/meta/freshness must aggregate from `programs.source_fetched_at`.

Production ships `data/jpintel.db` with `source_fetched_at` populated, but does
NOT ship the legacy `backend/knowledge_base/data/canonical/enriched/` tree. An
older implementation read fetched_at from those JSON files and silently
returned `total=0` in prod. This test pins the DB-backed loader.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def freshness_db(seeded_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stamp source_fetched_at on the seeded programs and return the DB path."""
    today = dt.date.today().isoformat() + "T00:00:00+00:00"
    long_ago = (dt.date.today() - dt.timedelta(days=365)).isoformat() + "T00:00:00+00:00"
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE programs SET source_fetched_at = ? WHERE unified_id IN (?, ?)",
            (today, "UNI-test-s-1", "UNI-test-a-1"),
        )
        c.execute(
            "UPDATE programs SET source_fetched_at = ? WHERE unified_id = ?",
            (long_ago, "UNI-test-b-1"),
        )
        c.commit()
    finally:
        c.close()

    # Synthetic registry that maps unified_ids to active programs.
    reg_path = tmp_path / "unified_registry.json"
    reg = {
        "schema_version": "test",
        "programs": {
            "UNI-test-s-1": {"primary_name": "テスト S-tier", "tier": "S"},
            "UNI-test-a-1": {"primary_name": "青森 A-tier", "tier": "A"},
            "UNI-test-b-1": {"primary_name": "B-tier 融資", "tier": "B"},
            "UNI-test-x-1": {"primary_name": "除外", "tier": "X", "excluded": 1},
        },
    }
    reg_path.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("AUTONOMATH_REGISTRY_PATH", str(reg_path))

    # Bust the lru_cache so the new registry is picked up.
    from jpintel_mcp.api import meta_freshness as mf

    mf._load_registry_cached.cache_clear()
    return seeded_db


def test_load_enriched_lookup_uses_db(freshness_db: Path) -> None:
    from jpintel_mcp.api.meta_freshness import _load_enriched_lookup

    look = _load_enriched_lookup()
    # The seeded DB has 3 programs with non-null source_fetched_at.
    assert "UNI-test-s-1" in look
    assert "UNI-test-a-1" in look
    assert "UNI-test-b-1" in look
    assert look["UNI-test-s-1"]["_meta"]["fetched_at"]


def test_endpoint_returns_nonzero_total(freshness_db: Path) -> None:
    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    client = TestClient(create_app())
    r = client.get("/v1/meta/freshness?limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    # 3 active programs in the seeded fixture have source_fetched_at; X is excluded.
    assert body["total"] == 3
    assert body["median_fetched_at"] is not None
    assert len(body["top_rows"]) <= 5
    # Every row must have the required shape.
    for row in body["top_rows"]:
        assert {"canonical_id", "name", "tier", "source_fetched_at", "days_ago"} <= row.keys()
