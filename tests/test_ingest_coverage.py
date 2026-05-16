"""Coverage push #3 — ingest/ modules.

Lifts the four 0%-coverage ingest modules (canonical, _gbiz_attribution,
_gbiz_rate_limiter, plain_japanese_dict) into the 70-95% band by driving
each public surface against real fixtures.

CLAUDE.md "What NOT to do #1": no DB mocking — every canonical-ingest
test uses a real SQLite file under `tmp_path` so the FTS5 + DELETE +
INSERT + checksum-preservation paths actually fire end-to-end.

CLAUDE.md "Non-negotiable constraints": NO LLM API imports — the
ingest modules under test are pure stdlib + httpx + sqlite, so this
file imports nothing under `anthropic`, `openai`, etc.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import pytest

from jpintel_mcp.db import session
from jpintel_mcp.ingest import (
    _gbiz_attribution,
    _gbiz_rate_limiter,
    canonical,
    plain_japanese_dict,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# canonical.py — real SQLite ingest end-to-end.
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_fixture(tmp_path: Path) -> dict[str, Any]:
    """Build a minimal-but-real Autonomath layout under tmp_path."""
    am_root = tmp_path / "autonomath_root"
    data_dir = am_root / "data"
    enriched_dir = am_root / "backend" / "knowledge_base" / "data" / "canonical" / "enriched"
    agri_dir = am_root / "backend" / "knowledge_base" / "data" / "agri"
    data_dir.mkdir(parents=True)
    enriched_dir.mkdir(parents=True)
    agri_dir.mkdir(parents=True)

    registry = {
        "_meta": {"generated_at": "2026-05-17T00:00:00Z"},
        "programs": {
            "UNI-test-001": {
                "primary_name": "テスト補助金A",
                "aliases": ["テスト助成A", "Test Subsidy A"],
                "authority_level": "国",
                "authority_name": "経済産業省",
                "prefecture": "東京都",
                "municipality": None,
                "program_kind": "subsidy",
                "official_url": "https://example.jp/programs/A",
                "amount_max_man_yen": 500.0,
                "amount_min_man_yen": 100.0,
                "subsidy_rate": 0.5,
                "trust_level": "high",
                "tier": "S",
                "coverage_score": 0.92,
                "gap_to_tier_s": [],
                "a_to_j_coverage": {"a": True, "b": True},
                "excluded": False,
                "exclusion_reason": None,
                "crop_categories": [],
                "equipment_category": None,
                "target_types": ["中小企業"],
                "funding_purpose": ["設備投資"],
                "amount_band": "100-500",
                "application_window": {"open": "2026-04-01", "close": "2026-06-30"},
                "source_mentions": [],
            },
            "UNI-test-002": {
                "primary_name": "テスト融資B",
                "aliases": [],
                "authority_level": "都道府県",
                "authority_name": "大阪府",
                "prefecture": "大阪府",
                "municipality": "大阪市",
                "program_kind": "loan",
                "official_url": "https://example.jp/programs/B",
                "amount_max_man_yen": None,
                "amount_min_man_yen": None,
                "subsidy_rate": None,
                "trust_level": "medium",
                "tier": "A",
                "coverage_score": 0.75,
                "excluded": True,
                "exclusion_reason": "duplicate",
            },
            # Non-dict entry — should be skipped silently.
            "UNI-skip-001": "not-a-dict",
        },
    }
    (data_dir / "unified_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8"
    )

    enriched_doc = {
        "official_url": "https://example.jp/programs/A/enriched",
        "summary": "詳細データ",
        "primary_source": {"url": "https://example.jp/source/A"},
    }
    (enriched_dir / "UNI-test-001.json").write_text(
        json.dumps(enriched_doc, ensure_ascii=False), encoding="utf-8"
    )
    # Broken JSON enriched file — _load_enriched must log + return None.
    (enriched_dir / "UNI-test-002.json").write_text("{not json", encoding="utf-8")

    rules = {
        "rules": {
            "rule-001": {
                "rule_id": "rule-001",
                "kind": "exclude",
                "severity": "absolute",
                "program_a": "UNI-test-001",
                "program_b": "UNI-test-002",
                "program_b_group": ["UNI-test-002"],
                "description": "重複申請禁止",
                "source_notes": "MAFF 通達 R6-001",
                "source_urls": ["https://maff.go.jp/r6-001"],
                "extra_field": "passthrough",
            },
            # Non-dict — should be skipped.
            "rule-bad": "not-a-dict",
        }
    }
    (agri_dir / "exclusion_rules.json").write_text(
        json.dumps(rules, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "am_root": am_root,
        "registry_path": data_dir / "unified_registry.json",
        "enriched_dir": enriched_dir,
        "rules_path": agri_dir / "exclusion_rules.json",
    }


def test_json_dump_handles_none() -> None:
    assert canonical._json_dump(None) is None


def test_json_dump_handles_empty_list_and_dict() -> None:
    assert canonical._json_dump([]) is None
    assert canonical._json_dump({}) is None


def test_json_dump_serializes_populated_list() -> None:
    out = canonical._json_dump(["a", "b"])
    assert isinstance(out, str)
    assert "a" in out and "b" in out


def test_json_dump_serializes_scalar() -> None:
    out = canonical._json_dump("solo")
    assert isinstance(out, str)
    assert "solo" in out


def test_flatten_enriched_text_walks_nested_structure() -> None:
    enriched = {
        "summary": "  trim me  ",
        "tags": ["alpha", "", "beta"],
        "nested": {"depth": 1, "blob": ["x"]},
        "none_field": None,
        "float_field": 3.14,
    }
    flat = canonical._flatten_enriched_text(enriched)
    assert "trim me" in flat
    assert "alpha" in flat and "beta" in flat
    assert "summary" in flat
    assert "3.14" in flat


def test_extract_source_url_prefers_enriched_official_url() -> None:
    url = canonical._extract_source_url(
        enriched={"official_url": "https://a.example/", "primary_source": "https://b.example/"},
        entry={"official_url": "https://c.example/"},
    )
    assert url == "https://a.example/"


def test_extract_source_url_falls_back_to_primary_source_string() -> None:
    url = canonical._extract_source_url(
        enriched={"primary_source": "https://b.example/"},
        entry={"official_url": "https://c.example/"},
    )
    assert url == "https://b.example/"


def test_extract_source_url_handles_primary_source_dict() -> None:
    url = canonical._extract_source_url(
        enriched={"primary_source": {"url": "https://d.example/"}},
        entry={},
    )
    assert url == "https://d.example/"


def test_extract_source_url_falls_back_to_entry_url() -> None:
    url = canonical._extract_source_url(
        enriched=None,
        entry={"official_url": "https://c.example/"},
    )
    assert url == "https://c.example/"


def test_extract_source_url_returns_none_when_nothing_present() -> None:
    assert canonical._extract_source_url(None, {}) is None
    assert canonical._extract_source_url({"primary_source": {}}, {}) is None


def test_compute_source_checksum_is_stable_across_runs() -> None:
    enriched = {"official_url": "https://a", "summary": "x"}
    entry = {
        "primary_name": "P",
        "official_url": "https://a",
        "amount_max_man_yen": 100,
        "amount_min_man_yen": 50,
        "subsidy_rate": 0.5,
        "tier": "S",
    }
    h1 = canonical._compute_source_checksum(enriched, entry)
    h2 = canonical._compute_source_checksum(enriched, entry)
    assert h1 == h2
    assert len(h1) == 16


def test_compute_source_checksum_changes_when_payload_differs() -> None:
    base = {"primary_name": "P", "tier": "S"}
    other = {"primary_name": "Q", "tier": "S"}
    assert canonical._compute_source_checksum(None, base) != canonical._compute_source_checksum(
        None, other
    )


def test_load_enriched_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert canonical._load_enriched(tmp_path, "UNI-nope") is None


def test_load_enriched_returns_none_on_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "UNI-broken.json").write_text("not json at all", encoding="utf-8")
    assert canonical._load_enriched(tmp_path, "UNI-broken") is None


def test_load_enriched_returns_none_on_non_dict_payload(tmp_path: Path) -> None:
    (tmp_path / "UNI-list.json").write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert canonical._load_enriched(tmp_path, "UNI-list") is None


def test_load_enriched_returns_dict(tmp_path: Path) -> None:
    (tmp_path / "UNI-ok.json").write_text(json.dumps({"summary": "y"}), encoding="utf-8")
    out = canonical._load_enriched(tmp_path, "UNI-ok")
    assert out == {"summary": "y"}


def test_canonical_run_end_to_end(monkeypatch, tmp_path: Path, registry_fixture) -> None:
    """Full ingest pipeline against a real SQLite + real fixtures."""
    db_path = tmp_path / "jpintel_run.db"
    # Override settings to point at our fixture tree + tmp DB.
    monkeypatch.setattr(canonical.settings, "db_path", db_path)
    monkeypatch.setattr(canonical.settings, "autonomath_path", registry_fixture["am_root"])
    rc = canonical.run()
    assert rc == 0

    # Verify rows landed correctly.
    conn = session.connect(db_path=db_path)
    try:
        rows = conn.execute(
            "SELECT unified_id, primary_name, tier, prefecture, authority_level FROM programs ORDER BY unified_id"
        ).fetchall()
        assert len(rows) == 2
        names = {r["unified_id"]: r["primary_name"] for r in rows}
        assert names["UNI-test-001"] == "テスト補助金A"
        assert names["UNI-test-002"] == "テスト融資B"

        # exclusion_rules ingest.
        ex = conn.execute("SELECT rule_id, kind, severity FROM exclusion_rules").fetchall()
        assert len(ex) == 1
        assert ex[0]["rule_id"] == "rule-001"
        assert ex[0]["kind"] == "exclude"

        # meta rows.
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["total_programs"] == "2"
        assert meta["total_exclusion_rules"] == "1"
        assert "last_ingested_at" in meta
        assert meta["data_as_of"] == "2026-05-17T00:00:00Z"

        # FTS rows match.
        fts_count = conn.execute("SELECT COUNT(*) FROM programs_fts").fetchone()[0]
        assert fts_count == 2
    finally:
        conn.close()


def test_canonical_run_preserves_source_fetched_at_on_unchanged_payload(
    monkeypatch, tmp_path: Path, registry_fixture
) -> None:
    """Second ingest of the SAME payload must keep the original source_fetched_at."""
    db_path = tmp_path / "jpintel_preserve.db"
    monkeypatch.setattr(canonical.settings, "db_path", db_path)
    monkeypatch.setattr(canonical.settings, "autonomath_path", registry_fixture["am_root"])

    canonical.run()
    conn = session.connect(db_path=db_path)
    try:
        first = conn.execute(
            "SELECT unified_id, source_fetched_at, source_checksum FROM programs ORDER BY unified_id"
        ).fetchall()
    finally:
        conn.close()

    # Second pass — registry unchanged → fetched_at must match.
    canonical.run()
    conn = session.connect(db_path=db_path)
    try:
        second = conn.execute(
            "SELECT unified_id, source_fetched_at, source_checksum FROM programs ORDER BY unified_id"
        ).fetchall()
    finally:
        conn.close()

    by_uid_first = {r["unified_id"]: r for r in first}
    by_uid_second = {r["unified_id"]: r for r in second}
    for uid in by_uid_first:
        assert by_uid_first[uid]["source_checksum"] == by_uid_second[uid]["source_checksum"]
        assert by_uid_first[uid]["source_fetched_at"] == by_uid_second[uid]["source_fetched_at"]


def test_canonical_run_missing_registry_returns_2(monkeypatch, tmp_path: Path) -> None:
    """No unified_registry.json → run() exits with code 2."""
    monkeypatch.setattr(canonical.settings, "db_path", tmp_path / "x.db")
    monkeypatch.setattr(canonical.settings, "autonomath_path", tmp_path / "missing")
    assert canonical.run() == 2


def test_ingest_programs_raises_when_programs_dict_empty(
    monkeypatch, tmp_path: Path, registry_fixture
) -> None:
    """Empty 'programs' must raise RuntimeError (loud failure, not silent skip)."""
    db_path = tmp_path / "empty.db"
    session.init_db(db_path=db_path)
    conn = session.connect(db_path=db_path)
    try:
        with pytest.raises(RuntimeError, match="no 'programs' dict"):
            canonical._ingest_programs(conn, {"programs": {}}, registry_fixture["enriched_dir"])
    finally:
        conn.close()


def test_ingest_exclusion_rules_missing_file_returns_zero(tmp_path: Path) -> None:
    db = tmp_path / "ex.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        n = canonical._ingest_exclusion_rules(conn, tmp_path / "no_such_file.json")
        assert n == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _gbiz_attribution.py — verbatim strings + dict assembly.
# ---------------------------------------------------------------------------


def test_attribution_short_contains_canonical_publisher() -> None:
    short = _gbiz_attribution.attribution_disclaimer_short()
    assert "経済産業省" in short
    assert "Gビズインフォ" in short


def test_attribution_long_contains_license_url() -> None:
    long_form = _gbiz_attribution.attribution_disclaimer_long()
    assert "https://help.info.gbiz.go.jp" in long_form
    assert "CC BY 4.0" in long_form


def test_build_attribution_returns_envelope_with_all_keys() -> None:
    env = _gbiz_attribution.build_attribution(
        source_url="https://info.gbiz.go.jp/hojin/ichiran?n=8010001213708",
        fetched_at="2026-05-17T00:00:00Z",
        upstream_source="NTA Houjin Bangou Web-API",
    )
    block = env["_attribution"]
    assert block["source"] == "Gビズインフォ"
    assert block["publisher"] == "経済産業省"
    assert block["primary_url"] == "https://info.gbiz.go.jp/"
    assert block["fetched_at"] == "2026-05-17T00:00:00Z"
    assert block["snapshot_date"] == "2026-05-17T00:00:00Z"
    assert block["upstream_source"] == "NTA Houjin Bangou Web-API"
    assert block["operator"].startswith("Bookyou")
    assert "license" in block and "license_url" in block


def test_build_attribution_requires_upstream_source() -> None:
    with pytest.raises(ValueError, match="upstream_source"):
        _gbiz_attribution.build_attribution(
            source_url="https://info.gbiz.go.jp/x",
            fetched_at="2026-05-17T00:00:00Z",
            upstream_source="",
        )


def test_build_attribution_rejects_whitespace_only_upstream_source() -> None:
    with pytest.raises(ValueError, match="upstream_source"):
        _gbiz_attribution.build_attribution(
            source_url="https://info.gbiz.go.jp/x",
            fetched_at="2026-05-17T00:00:00Z",
            upstream_source="   ",
        )


def test_inject_attribution_into_empty_envelope_sets_disclaimer() -> None:
    env = _gbiz_attribution.inject_attribution_into_response(
        envelope={},
        source_url="https://info.gbiz.go.jp/x",
        fetched_at="2026-05-17T00:00:00Z",
        upstream_source="jGrants",
    )
    assert "_attribution" in env
    assert env["_disclaimer"] == _gbiz_attribution.ATTRIBUTION_SHORT
    assert env["_attribution"]["upstream_source"] == "jGrants"


def test_inject_attribution_preserves_existing_disclaimer_and_adds_sibling() -> None:
    """Existing _disclaimer (§52 / §47条の2) must be kept; gBiz copy goes to _disclaimer_gbiz."""
    env = _gbiz_attribution.inject_attribution_into_response(
        envelope={"_disclaimer": "§52 disclaimer text"},
        source_url="https://info.gbiz.go.jp/x",
        fetched_at="2026-05-17T00:00:00Z",
        upstream_source="MAFF",
    )
    assert env["_disclaimer"] == "§52 disclaimer text"
    assert env["_disclaimer_gbiz"] == _gbiz_attribution.ATTRIBUTION_SHORT


def test_inject_attribution_overwrites_attribution_block() -> None:
    env = {"_attribution": {"stale": "value"}}
    out = _gbiz_attribution.inject_attribution_into_response(
        envelope=env,
        source_url="https://info.gbiz.go.jp/y",
        fetched_at="2026-05-17T01:00:00Z",
        upstream_source="中企庁",
    )
    assert "stale" not in out["_attribution"]
    assert out["_attribution"]["upstream_source"] == "中企庁"


def test_inject_attribution_returns_same_envelope_mutated() -> None:
    env = {"data": "preserved"}
    out = _gbiz_attribution.inject_attribution_into_response(
        envelope=env,
        source_url="https://info.gbiz.go.jp/z",
        fetched_at="2026-05-17T02:00:00Z",
        upstream_source="p-portal",
    )
    assert out is env
    assert env["data"] == "preserved"


# ---------------------------------------------------------------------------
# _gbiz_rate_limiter.py — token, cache, gate, client paths.
# ---------------------------------------------------------------------------


def test_get_token_returns_env_value(monkeypatch) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "secret-token-xyz")
    assert _gbiz_rate_limiter._get_token() == "secret-token-xyz"


def test_get_token_raises_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("GBIZINFO_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GBIZINFO_API_TOKEN"):
        _gbiz_rate_limiter._get_token()


def test_get_cache_dir_creates_directory(monkeypatch, tmp_path: Path) -> None:
    """Forces the home-dir branch to a tmp path so the test stays hermetic."""
    monkeypatch.setattr(_gbiz_rate_limiter.Path, "home", lambda: tmp_path)
    # Patch out the /data branch so we deterministically take the home fallback.
    original_exists = _gbiz_rate_limiter.Path.exists

    def patched_exists(self) -> bool:
        if str(self) == "/data":
            return False
        return original_exists(self)

    monkeypatch.setattr(_gbiz_rate_limiter.Path, "exists", patched_exists)
    cache_dir = _gbiz_rate_limiter._get_cache_dir()
    assert cache_dir.is_dir()
    assert str(tmp_path) in str(cache_dir)


def test_json_file_cache_roundtrip(tmp_path: Path) -> None:
    cache = _gbiz_rate_limiter._JsonFileCache(tmp_path)
    cache.set("key-a", {"value": 1, "name": "demo"}, expire=3600)
    hit = cache.get("key-a")
    assert hit == {"value": 1, "name": "demo"}


def test_json_file_cache_returns_none_on_miss(tmp_path: Path) -> None:
    cache = _gbiz_rate_limiter._JsonFileCache(tmp_path)
    assert cache.get("missing-key") is None


def test_json_file_cache_returns_none_on_expired_entry(tmp_path: Path) -> None:
    cache = _gbiz_rate_limiter._JsonFileCache(tmp_path)
    cache.set("temp", {"x": 1}, expire=1)
    # Re-write the expire file in the past.
    h = _gbiz_rate_limiter._JsonFileCache._hash("temp")
    (tmp_path / f"{h}.expire").write_text(str(time.time() - 1000), encoding="utf-8")
    assert cache.get("temp") is None


def test_json_file_cache_get_with_age_reports_age_hours(tmp_path: Path) -> None:
    cache = _gbiz_rate_limiter._JsonFileCache(tmp_path)
    cache.set("aged", {"x": 2}, expire=_gbiz_rate_limiter.GBIZ_CACHE_TTL_SECONDS)
    item = cache.get_with_age("aged")
    assert item is not None
    body, age_hours = item
    assert body == {"x": 2}
    # Freshly set → age very close to 0.
    assert age_hours is not None and age_hours < 0.01


def test_json_file_cache_get_with_age_handles_corrupt_expire(tmp_path: Path) -> None:
    cache = _gbiz_rate_limiter._JsonFileCache(tmp_path)
    cache.set("corrupt", {"x": 3}, expire=3600)
    h = _gbiz_rate_limiter._JsonFileCache._hash("corrupt")
    (tmp_path / f"{h}.expire").write_text("not-a-number", encoding="utf-8")
    assert cache.get_with_age("corrupt") is None


def test_make_cache_returns_json_cache_when_diskcache_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_gbiz_rate_limiter, "_HAS_DISKCACHE", False)
    cache = _gbiz_rate_limiter._make_cache(tmp_path)
    assert isinstance(cache, _gbiz_rate_limiter._JsonFileCache)


def test_build_cache_key_includes_sorted_params() -> None:
    key = _gbiz_rate_limiter.GbizRateLimitedClient._build_cache_key(
        "https://info.gbiz.go.jp/x", {"b": 2, "a": 1, "c": 3}
    )
    # Sorted alphabetically.
    assert key == "https://info.gbiz.go.jp/x?a=1&b=2&c=3"


def test_build_cache_key_returns_url_when_params_empty() -> None:
    key = _gbiz_rate_limiter.GbizRateLimitedClient._build_cache_key(
        "https://info.gbiz.go.jp/y", None
    )
    assert key == "https://info.gbiz.go.jp/y"


def test_with_cache_meta_appends_meta_block() -> None:
    out = _gbiz_rate_limiter.GbizRateLimitedClient._with_cache_meta(
        body={"name": "Demo", "value": 1},
        cache_hit=True,
        cache_age_hours=3.5,
    )
    assert out["name"] == "Demo"
    assert out["_cache_meta"] == {"cache_hit": True, "cache_age_hours": 3.5}


def test_with_cache_meta_does_not_mutate_input() -> None:
    body = {"name": "Demo"}
    _gbiz_rate_limiter.GbizRateLimitedClient._with_cache_meta(
        body=body, cache_hit=False, cache_age_hours=None
    )
    assert "_cache_meta" not in body


def test_get_client_returns_singleton(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-singleton")
    # Reset the module-level singleton so this test stays hermetic.
    monkeypatch.setattr(_gbiz_rate_limiter, "_default_client", None)
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    a = _gbiz_rate_limiter.get_client()
    b = _gbiz_rate_limiter.get_client()
    assert a is b


def test_client_get_returns_cached_value_on_hit(monkeypatch, tmp_path: Path) -> None:
    """When cache has a hit, the client must NOT call httpx."""
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-cache-hit")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-cache-hit")
    # Seed the cache directly.
    cache_key = client._build_cache_key(
        f"{_gbiz_rate_limiter.GBIZ_API_BASE.rstrip('/')}/v2/hojin/8010001213708", None
    )
    client._cache.set(
        cache_key, {"name": "Bookyou"}, expire=_gbiz_rate_limiter.GBIZ_CACHE_TTL_SECONDS
    )

    # If we accidentally fall through to httpx the test must fail loudly.
    def boom(*args, **kwargs):
        raise AssertionError("httpx.Client must not be invoked on a cache hit")

    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", boom)
    out = client.get("v2/hojin/8010001213708")
    assert out["name"] == "Bookyou"
    assert out["_cache_meta"]["cache_hit"] is True


def test_client_get_handles_full_url_passthrough(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-passthrough")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-passthrough")
    url = "https://info.gbiz.go.jp/full/path"
    client._cache.set(url, {"ok": True}, expire=_gbiz_rate_limiter.GBIZ_CACHE_TTL_SECONDS)

    monkeypatch.setattr(
        _gbiz_rate_limiter.httpx,
        "Client",
        lambda **kw: (_ for _ in ()).throw(AssertionError("must not call httpx")),
    )
    out = client.get(url)
    assert out["ok"] is True


def test_cache_get_with_age_returns_none_when_cache_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-empty")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-empty")
    assert client._cache_get_with_age("never-set-key") is None


# ---------------------------------------------------------------------------
# plain_japanese_dict.py — substitution rule application.
# ---------------------------------------------------------------------------


def test_replace_plain_japanese_empty_input_returns_empty_string() -> None:
    assert plain_japanese_dict.replace_plain_japanese("") == ""
    assert plain_japanese_dict.replace_plain_japanese(None) == ""


def test_replace_plain_japanese_substitutes_subsidy_term() -> None:
    out = plain_japanese_dict.replace_plain_japanese("補助率は50%です")
    assert "お金の半分くれます" in out


def test_replace_plain_japanese_substitutes_tax_term() -> None:
    out = plain_japanese_dict.replace_plain_japanese("税額控除を受けられます")
    assert "払う税金を少なくしてくれる制度" in out


def test_replace_plain_japanese_longest_match_wins_for_program_name() -> None:
    """'IT導入補助金' must win over the shorter '補助金' alone."""
    out = plain_japanese_dict.replace_plain_japanese("IT導入補助金の説明")
    assert "パソコンや業務ソフトを買うお金を助ける制度" in out


def test_replace_plain_japanese_preserves_unrelated_text() -> None:
    out = plain_japanese_dict.replace_plain_japanese("こんにちは世界")
    assert out == "こんにちは世界"


def test_replace_plain_japanese_handles_multiple_substitutions() -> None:
    out = plain_japanese_dict.replace_plain_japanese("補助率と融資の条件")
    assert "お金の半分くれます" in out
    assert "銀行などからお金を借りること" in out


def test_plain_replacements_table_has_canonical_entries() -> None:
    keys = {jargon for jargon, _ in plain_japanese_dict._PLAIN_REPLACEMENTS}
    # Spot-check a handful that the W3-12 LINE blocker relies on.
    assert "補助率" in keys
    assert "税額控除" in keys
    assert "確定申告" in keys
    assert "認定" in keys


# ---------------------------------------------------------------------------
# Rate limit gate — both branches (decorator + manual sleep fallback).
# ---------------------------------------------------------------------------


def test_rate_limit_gate_does_not_raise() -> None:
    """The gate must be callable in isolation regardless of which branch is active."""
    _gbiz_rate_limiter._rate_limit_gate()


def test_logger_present_on_rate_limiter() -> None:
    assert isinstance(_gbiz_rate_limiter._LOG, logging.Logger)


# ---------------------------------------------------------------------------
# _gbiz_rate_limiter — HTTP error / 401 / 429 / 200 happy paths via stub.
# ---------------------------------------------------------------------------


class _StubResponse:
    """Minimal httpx.Response stand-in with the surface the client uses."""

    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx as _h

            req = _h.Request("GET", "https://info.gbiz.go.jp/stub")
            raise _h.HTTPStatusError(
                f"status {self.status_code}",
                request=req,
                response=_h.Response(self.status_code, request=req),
            )


class _StubClient:
    """httpx.Client stand-in driven by a queue of responses or an exception."""

    def __init__(self, *, responses=None, raise_exc=None) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url, params=None, headers=None):
        self.calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._responses.pop(0)


def test_client_get_caches_200_response_and_marks_cache_miss(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-200")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-200")

    stub = _StubClient(responses=[_StubResponse(200, {"name": "Bookyou株式会社"})])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    # Don't actually sleep in the rate-limit gate.
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)

    out = client.get("v2/hojin/8010001213708")
    assert out["name"] == "Bookyou株式会社"
    assert out["_cache_meta"]["cache_hit"] is False
    # A second call must now hit the cache (stub would raise on a second get call).
    out2 = client.get("v2/hojin/8010001213708")
    assert out2["_cache_meta"]["cache_hit"] is True


def test_client_get_raises_runtime_error_on_401(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-401")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-401")
    stub = _StubClient(responses=[_StubResponse(401)])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    with pytest.raises(RuntimeError, match="gbiz_token_invalid_or_revoked"):
        client.get("v2/hojin/8010001213708")


def test_client_get_raises_runtime_error_on_403(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-403")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-403")
    stub = _StubClient(responses=[_StubResponse(403)])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    with pytest.raises(RuntimeError, match="gbiz_token_invalid_or_revoked"):
        client.get("v2/hojin/8010001213708")


def test_client_get_raises_runtime_error_on_429(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-429")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-429")
    stub = _StubClient(responses=[_StubResponse(429)])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    with pytest.raises(RuntimeError, match="gbiz_rate_limit_exceeded"):
        client.get("v2/hojin/8010001213708")


def test_client_get_retries_on_transport_error_then_succeeds(monkeypatch, tmp_path: Path) -> None:
    """httpx.HTTPError on first attempt must back off and retry."""
    import httpx as _h

    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-retry")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-retry")

    # First attempt raises HTTPError; second returns 200.
    call_count = {"n": 0}

    class _RetryStub:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _h.ConnectError("connection reset", request=_h.Request("GET", "https://x"))
            return _StubResponse(200, {"name": "retry-success"})

    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: _RetryStub())
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    monkeypatch.setattr(_gbiz_rate_limiter.time, "sleep", lambda s: None)

    out = client.get("v2/hojin/8010001213708")
    assert out["name"] == "retry-success"
    assert call_count["n"] == 2


def test_client_get_raises_after_all_retries_exhausted(monkeypatch, tmp_path: Path) -> None:
    import httpx as _h

    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-fail")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-fail")

    class _AlwaysFailStub:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, *a, **kw):
            raise _h.ConnectError("always fails", request=_h.Request("GET", "https://x"))

    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: _AlwaysFailStub())
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)
    monkeypatch.setattr(_gbiz_rate_limiter.time, "sleep", lambda s: None)
    with pytest.raises(_h.HTTPError):
        client.get("v2/hojin/8010001213708")


def test_module_level_gbiz_get_uses_default_client(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-module")
    monkeypatch.setattr(_gbiz_rate_limiter, "_default_client", None)
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)

    stub = _StubClient(responses=[_StubResponse(200, {"ok": True})])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)

    out = _gbiz_rate_limiter.gbiz_get("v2/hojin/8010001213708")
    assert out["ok"] is True
    # Backward-compat alias must hit the same path.
    out2 = _gbiz_rate_limiter.get("v2/hojin/8010001213708")
    assert out2["_cache_meta"]["cache_hit"] is True


def test_client_get_force_refresh_bypasses_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-force")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-force")
    # Pre-seed cache with stale value.
    cache_key = client._build_cache_key(
        f"{_gbiz_rate_limiter.GBIZ_API_BASE.rstrip('/')}/v2/hojin/8010001213708", None
    )
    client._cache.set(cache_key, {"stale": True}, expire=86400)

    stub = _StubClient(responses=[_StubResponse(200, {"fresh": True})])
    monkeypatch.setattr(_gbiz_rate_limiter.httpx, "Client", lambda **kw: stub)
    monkeypatch.setattr(_gbiz_rate_limiter, "_rate_limit_gate", lambda: None)

    out = client.get("v2/hojin/8010001213708", force_refresh=True)
    assert out["fresh"] is True
    assert "stale" not in out


def test_cache_get_with_age_falls_back_to_simple_get(monkeypatch, tmp_path: Path) -> None:
    """Cache backends without get_with_age must degrade gracefully."""
    monkeypatch.setenv("GBIZINFO_API_TOKEN", "tok-simple")
    monkeypatch.setattr(_gbiz_rate_limiter, "_get_cache_dir", lambda: tmp_path)
    client = _gbiz_rate_limiter.GbizRateLimitedClient(token="tok-simple")

    class _SimpleCache:
        def __init__(self):
            self._d: dict[str, dict[str, Any]] = {}

        def get(self, key, expire_time=None):
            if expire_time:
                raise TypeError("simple cache rejects expire_time kwarg")
            return self._d.get(key)

        def set(self, key, value, expire):
            self._d[key] = value

    simple = _SimpleCache()
    simple.set("the-key", {"a": 1}, expire=3600)
    client._cache = simple
    out = client._cache_get_with_age("the-key")
    assert out is not None
    body, age = out
    assert body == {"a": 1}
    assert age is None
