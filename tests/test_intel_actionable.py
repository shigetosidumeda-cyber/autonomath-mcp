"""Tests for /v1/intel/actionable/* (Wave 30-5 RE-RUN).

Covers:

1. Migration applies idempotently — running the CREATE TABLE / CREATE INDEX
   block twice does not raise.
2. POST /lookup hit returns the cached envelope with `_cache_meta.cache_hit=True`
   and bumps hit_count.
3. POST /lookup miss returns 404 with `_not_cached: true`.
4. GET /{cache_key} hit and miss path mirror the POST contract.
5. Populate script writes >=10 entries to a fixture DB.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_actionable_fixture_db(db_path: Path) -> None:
    """Create a minimal autonomath.db that matches the columns the
    populator + endpoint touch.

    We seed:
      * jpi_programs with a handful of S/A/B tier rows so the populator
        has at least 10 programs to enumerate over (>=10 cache rows).
      * am_amendment_diff so amendment_diff renderer has data.
      * am_region so subsidy_search can resolve a prefecture_code -> name.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id            TEXT PRIMARY KEY,
            primary_name          TEXT NOT NULL,
            tier                  TEXT NOT NULL,
            authority_level       TEXT,
            authority_name        TEXT,
            prefecture            TEXT,
            municipality          TEXT,
            program_kind          TEXT,
            official_url          TEXT,
            amount_max_man_yen    INTEGER,
            amount_min_man_yen    INTEGER,
            subsidy_rate          REAL,
            subsidy_rate_text     TEXT,
            trust_level           TEXT,
            coverage_score        REAL,
            target_types_json     TEXT,
            funding_purpose_json  TEXT,
            amount_band           TEXT,
            application_window_json TEXT,
            enriched_json         TEXT,
            source_mentions_json  TEXT,
            source_url            TEXT,
            source_fetched_at     TEXT,
            source_checksum       TEXT,
            updated_at            TEXT,
            excluded              INTEGER DEFAULT 0
        );
        CREATE TABLE am_amendment_diff (
            program_unified_id  TEXT NOT NULL,
            field_name          TEXT,
            old_value           TEXT,
            new_value           TEXT,
            detected_at         TEXT
        );
        CREATE TABLE am_region (
            code                TEXT PRIMARY KEY,
            name                TEXT NOT NULL
        );
        CREATE TABLE program_law_refs (
            program_unified_id  TEXT NOT NULL,
            law_id              TEXT,
            article_number      TEXT
        );
        """
    )
    # 12 programs (>10 needed for the populator-writes-10+ test).
    seeds = [
        ("UNI-test-act-s-1", "テスト S 補助金 #1", "S", "東京都", 1000, "https://example.gov/s1"),
        ("UNI-test-act-s-2", "テスト S 補助金 #2", "S", "東京都", 2000, "https://example.gov/s2"),
        ("UNI-test-act-a-1", "テスト A 補助金 #1", "A", "大阪府", 500, "https://example.gov/a1"),
        ("UNI-test-act-a-2", "テスト A 補助金 #2", "A", "大阪府", 800, "https://example.gov/a2"),
        ("UNI-test-act-a-3", "テスト A 補助金 #3", "A", None, 1500, "https://example.gov/a3"),
        ("UNI-test-act-b-1", "テスト B 融資 #1", "B", "東京都", 30000, "https://example.gov/b1"),
        ("UNI-test-act-b-2", "テスト B 融資 #2", "B", "北海道", 10000, "https://example.gov/b2"),
        ("UNI-test-act-b-3", "テスト B 融資 #3", "B", "福岡県", 20000, "https://example.gov/b3"),
        ("UNI-test-act-b-4", "テスト B 融資 #4", "B", "愛知県", 15000, "https://example.gov/b4"),
        ("UNI-test-act-c-1", "テスト C 認定 #1", "C", "京都府", 200, "https://example.gov/c1"),
        ("UNI-test-act-c-2", "テスト C 認定 #2", "C", "兵庫県", 300, "https://example.gov/c2"),
        ("UNI-test-act-c-3", "テスト C 認定 #3", "C", "宮城県", 400, "https://example.gov/c3"),
    ]
    for uid, name, tier, pref, amt, url in seeds:
        conn.execute(
            "INSERT INTO jpi_programs(unified_id, primary_name, tier, prefecture, "
            "  amount_max_man_yen, source_url, official_url, program_kind, "
            "  authority_level, target_types_json, funding_purpose_json, excluded) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                uid,
                name,
                tier,
                pref,
                amt,
                url,
                url,
                "補助金",
                "国",
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
            ),
        )
    # Amendment diff rows for one program so amendment_diff render returns >0.
    for i in range(3):
        conn.execute(
            "INSERT INTO am_amendment_diff(program_unified_id, field_name, "
            "  old_value, new_value, detected_at) VALUES (?,?,?,?,?)",
            (
                "UNI-test-act-s-1",
                "amount_max_man_yen",
                str(900 + i),
                str(1000 + i),
                f"2026-04-2{i}T00:00:00Z",
            ),
        )
    # Prefectures for the subsidy_search resolver.
    conn.executemany(
        "INSERT INTO am_region(code, name) VALUES (?,?)",
        [
            ("13", "東京都"),
            ("27", "大阪府"),
            ("01", "北海道"),
            ("40", "福岡県"),
            ("23", "愛知県"),
            ("26", "京都府"),
            ("28", "兵庫県"),
            ("04", "宮城県"),
        ],
    )
    # Law refs for citation_pack render.
    conn.execute(
        "INSERT INTO program_law_refs(program_unified_id, law_id, article_number) VALUES (?,?,?)",
        ("UNI-test-act-s-1", "法人税法", "第2条"),
    )
    conn.commit()
    conn.close()


def _seed_actionable_cache_row(
    db_path: Path,
    *,
    cache_key: str,
    intent_class: str,
    input_hash: str,
    rendered: dict[str, object],
    corpus_snapshot_id: str = "test-snapshot-final-cap",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
              cache_key             TEXT PRIMARY KEY,
              intent_class          TEXT NOT NULL,
              input_hash            TEXT NOT NULL,
              rendered_answer_json  TEXT NOT NULL,
              rendered_at           INTEGER NOT NULL,
              hit_count             INTEGER NOT NULL DEFAULT 0,
              corpus_snapshot_id    TEXT NOT NULL
            )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO am_actionable_qa_cache(cache_key, intent_class, "
        "  input_hash, rendered_answer_json, rendered_at, hit_count, "
        "  corpus_snapshot_id) VALUES (?,?,?,?,?,?,?)",
        (
            cache_key,
            intent_class,
            input_hash,
            json.dumps(rendered, ensure_ascii=False, sort_keys=True),
            int(time.time()),
            0,
            corpus_snapshot_id,
        ),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def actionable_fixture(tmp_path: Path, monkeypatch) -> Path:
    """Build a temp autonomath.db + point AUTONOMATH_DB_PATH at it."""
    am_path = tmp_path / "actionable_test_autonomath.db"
    _build_actionable_fixture_db(am_path)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(am_path))
    # Purge the cached autonomath_tools.db module so the path is re-resolved.
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp.mcp.autonomath_tools.db"):
            del sys.modules[mod]
    return am_path


@pytest.fixture()
def actionable_client(seeded_db: Path, actionable_fixture: Path) -> TestClient:
    """TestClient backed by the shared seeded jpintel.db + temp autonomath.db."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_169_applies_idempotently(actionable_fixture: Path) -> None:
    """Apply migration 169 twice — second pass must not raise."""
    sql_file = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "migrations"
        / "169_am_actionable_qa_cache.sql"
    )
    sql = sql_file.read_text(encoding="utf-8")
    conn = sqlite3.connect(actionable_fixture)
    conn.executescript(sql)
    conn.executescript(sql)  # second apply must not fail
    # Verify table + indexes exist.
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_actionable_qa_cache'"
    )
    assert cursor.fetchone() is not None
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name IN ('idx_am_actionable_intent_hash','idx_am_actionable_rendered_at')"
    )
    idx_rows = cursor.fetchall()
    assert len(idx_rows) == 2
    conn.close()


def test_post_lookup_miss_returns_404_with_not_cached(
    actionable_client: TestClient,
) -> None:
    """A cache miss returns 404 + {_not_cached: True, intent_class, input_hash}."""
    r = actionable_client.post(
        "/v1/intel/actionable/lookup",
        json={
            "intent_class": "subsidy_search",
            "input_dict": {"prefecture_code": "99", "industry_jsic_major": "Z"},
        },
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["_not_cached"] is True
    assert body["intent_class"] == "subsidy_search"
    assert "input_hash" in body and len(body["input_hash"]) == 64
    assert body["cache_key"].startswith("subsidy_search:")
    assert "_disclaimer" in body and body["_disclaimer"]
    assert body["_billing_unit"] == 1
    assert body["_cache_meta"]["cache_hit"] is False


def test_post_lookup_hit_returns_cached_envelope(
    actionable_client: TestClient, actionable_fixture: Path
) -> None:
    """Pre-seed one cache row → POST /lookup returns it as a hit + bumps hit_count."""
    from jpintel_mcp.api.intel_actionable import (
        build_cache_key,
        canonical_input_hash,
    )

    # Seed one row directly (mirrors what the populator does).
    intent_class = "amendment_diff"
    input_dict = {"program_id": "UNI-test-act-s-1"}
    input_hash = canonical_input_hash(input_dict)
    cache_key = build_cache_key(intent_class, input_hash)
    rendered = {
        "intent_class": intent_class,
        "input": input_dict,
        "amendments": [
            {
                "field_name": "amount_max_man_yen",
                "old_value": "900",
                "new_value": "1000",
                "detected_at": "2026-04-21T00:00:00Z",
            }
        ],
        "amendment_count": 1,
        "_disclaimer": "test disclaimer",
        "_billing_unit": 1,
        "corpus_snapshot_id": "test-snapshot-1",
    }
    conn = sqlite3.connect(actionable_fixture)
    # Ensure table exists in case migration not applied.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
              cache_key             TEXT PRIMARY KEY,
              intent_class          TEXT NOT NULL,
              input_hash            TEXT NOT NULL,
              rendered_answer_json  TEXT NOT NULL,
              rendered_at           INTEGER NOT NULL,
              hit_count             INTEGER NOT NULL DEFAULT 0,
              corpus_snapshot_id    TEXT NOT NULL
            )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO am_actionable_qa_cache(cache_key, intent_class, "
        "  input_hash, rendered_answer_json, rendered_at, hit_count, "
        "  corpus_snapshot_id) VALUES (?,?,?,?,?,?,?)",
        (
            cache_key,
            intent_class,
            input_hash,
            json.dumps(rendered, ensure_ascii=False, sort_keys=True),
            int(time.time()),
            0,
            "test-snapshot-1",
        ),
    )
    conn.commit()
    conn.close()

    # Lookup hits.
    r = actionable_client.post(
        "/v1/intel/actionable/lookup",
        json={"intent_class": intent_class, "input_dict": input_dict},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_cache_meta"]["cache_hit"] is True
    assert body["_cache_meta"]["intent_class"] == intent_class
    assert body["_cache_meta"]["input_hash"] == input_hash
    assert body["_cache_meta"]["cache_key"] == cache_key
    assert body["_cache_meta"]["hit_count"] == 1  # post-bump value
    assert body["amendments"][0]["new_value"] == "1000"
    assert body["corpus_snapshot_id"] == "test-snapshot-1"
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body

    # Verify hit_count actually got bumped on disk.
    conn = sqlite3.connect(actionable_fixture)
    row = conn.execute(
        "SELECT hit_count FROM am_actionable_qa_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 1


def test_get_actionable_by_cache_key_hit_and_miss(
    actionable_client: TestClient, actionable_fixture: Path
) -> None:
    """GET /{cache_key} mirrors POST /lookup contract."""
    from jpintel_mcp.api.intel_actionable import (
        build_cache_key,
        canonical_input_hash,
    )

    intent_class = "citation_pack"
    input_dict = {"program_id": "UNI-test-act-s-2"}
    input_hash = canonical_input_hash(input_dict)
    cache_key = build_cache_key(intent_class, input_hash)
    rendered = {
        "intent_class": intent_class,
        "input": input_dict,
        "citations": [{"kind": "program_source", "url": "https://example.gov/s2"}],
        "citation_count": 1,
        "_disclaimer": "test disclaimer",
        "_billing_unit": 1,
        "corpus_snapshot_id": "test-snapshot-2",
    }
    conn = sqlite3.connect(actionable_fixture)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
              cache_key             TEXT PRIMARY KEY,
              intent_class          TEXT NOT NULL,
              input_hash            TEXT NOT NULL,
              rendered_answer_json  TEXT NOT NULL,
              rendered_at           INTEGER NOT NULL,
              hit_count             INTEGER NOT NULL DEFAULT 0,
              corpus_snapshot_id    TEXT NOT NULL
            )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO am_actionable_qa_cache(cache_key, intent_class, "
        "  input_hash, rendered_answer_json, rendered_at, hit_count, "
        "  corpus_snapshot_id) VALUES (?,?,?,?,?,?,?)",
        (
            cache_key,
            intent_class,
            input_hash,
            json.dumps(rendered, ensure_ascii=False, sort_keys=True),
            int(time.time()),
            0,
            "test-snapshot-2",
        ),
    )
    conn.commit()
    conn.close()

    r_hit = actionable_client.get(f"/v1/intel/actionable/{cache_key}")
    assert r_hit.status_code == 200, r_hit.text
    body = r_hit.json()
    assert body["_cache_meta"]["cache_hit"] is True
    assert body["citations"][0]["url"] == "https://example.gov/s2"

    r_miss = actionable_client.get(
        "/v1/intel/actionable/citation_pack:0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert r_miss.status_code == 404
    body = r_miss.json()
    assert body["_not_cached"] is True


def test_get_actionable_paid_final_cap_failure_returns_503_without_usage_event(
    actionable_client: TestClient,
    actionable_fixture: Path,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.intel_actionable import (
        build_cache_key,
        canonical_input_hash,
    )

    intent_class = "citation_pack"
    input_dict = {"program_id": "UNI-test-act-s-2"}
    input_hash = canonical_input_hash(input_dict)
    cache_key = build_cache_key(intent_class, input_hash)
    _seed_actionable_cache_row(
        actionable_fixture,
        cache_key=cache_key,
        intent_class=intent_class,
        input_hash=input_hash,
        rendered={
            "intent_class": intent_class,
            "input": input_dict,
            "citations": [{"kind": "program_source", "url": "https://example.gov/s2"}],
            "citation_count": 1,
            "_disclaimer": "test disclaimer",
            "_billing_unit": 1,
            "corpus_snapshot_id": "test-snapshot-final-cap",
        },
    )

    endpoint = "intel.actionable.get"
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(n)
        finally:
            conn.close()

    before = usage_count()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = actionable_client.get(
        f"/v1/intel/actionable/{cache_key}",
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


def test_post_actionable_lookup_paid_final_cap_failure_returns_503_without_usage_event(
    actionable_client: TestClient,
    actionable_fixture: Path,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.intel_actionable import (
        build_cache_key,
        canonical_input_hash,
    )

    intent_class = "amendment_diff"
    input_dict = {"program_id": "UNI-test-act-s-1"}
    input_hash = canonical_input_hash(input_dict)
    cache_key = build_cache_key(intent_class, input_hash)
    _seed_actionable_cache_row(
        actionable_fixture,
        cache_key=cache_key,
        intent_class=intent_class,
        input_hash=input_hash,
        rendered={
            "intent_class": intent_class,
            "input": input_dict,
            "amendments": [{"field_name": "amount_max_man_yen", "new_value": "1000"}],
            "amendment_count": 1,
            "_disclaimer": "test disclaimer",
            "_billing_unit": 1,
            "corpus_snapshot_id": "test-snapshot-final-cap",
        },
    )

    endpoint = "intel.actionable.lookup"
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(n)
        finally:
            conn.close()

    before = usage_count()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = actionable_client.post(
        "/v1/intel/actionable/lookup",
        headers={"X-API-Key": paid_key},
        json={"intent_class": intent_class, "input_dict": input_dict},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


def test_post_lookup_invalid_intent_returns_422(actionable_client: TestClient) -> None:
    r = actionable_client.post(
        "/v1/intel/actionable/lookup",
        json={"intent_class": "not_a_real_intent", "input_dict": {}},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_intent_class"
    assert "subsidy_search" in detail["allowed"]


def test_populate_script_writes_at_least_10_entries(
    actionable_fixture: Path,
) -> None:
    """Run the precompute script with --budget 50 and verify >=10 rows landed."""
    # Import via path so the script's __main__ guard does not fire.
    import importlib.util

    script_path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "cron"
        / "precompute_actionable_answers.py"
    )
    spec = importlib.util.spec_from_file_location("precompute_actionable_answers", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.run(budget=50, dry_run=False)
    assert result["ok"] is True

    # Verify >=10 cache rows landed.
    conn = sqlite3.connect(actionable_fixture)
    (n,) = conn.execute("SELECT COUNT(*) FROM am_actionable_qa_cache").fetchone()
    conn.close()
    assert n >= 10, f"Expected populator to write >=10 rows, got {n}. Result envelope: {result}"

    # Verify the hash invariant: cache_key == intent_class + ':' + input_hash.
    conn = sqlite3.connect(actionable_fixture)
    rows = conn.execute(
        "SELECT cache_key, intent_class, input_hash, corpus_snapshot_id "
        "FROM am_actionable_qa_cache LIMIT 5"
    ).fetchall()
    conn.close()
    for ck, ic, ih, snap in rows:
        assert ck == f"{ic}:{ih}"
        assert len(ih) == 64  # sha256 hex
        assert snap, "corpus_snapshot_id must be set"
