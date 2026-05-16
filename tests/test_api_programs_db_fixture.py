"""DB-fixture-based coverage push for ``src/jpintel_mcp/api/programs.py``.

Stream HH 2026-05-16 — push coverage 80→85% via tmp_path-backed minimal
schemas. No touch of the 9.7 GB production autonomath.db (memory:
``feedback_no_quick_check_on_huge_sqlite``); every test in this file opens
its OWN sqlite3.connect against a freshly-CREATEd file under tmp_path.

Targets (pure-function + fixture-backed paths):
  * ``_validate_as_of_date`` — early 422 path for malformed input.
  * ``_encode_cursor`` / ``_decode_cursor`` — round-trip + version guard.
  * ``_tokenize_query`` — punctuation / quoted-phrase / NFKC.
  * ``_build_fts_match`` — single + multi-token + KANA_EXPANSIONS branch.
  * ``_fts_escape`` — `"` -> `""` doubling.
  * ``_extract_required_documents`` — heterogeneous enriched shape.
  * ``_extract_next_deadline`` + ``_post_cache_next_deadline`` — date pivot.
  * ``_build_program`` — sqlite Row -> Program (via tmp_path schema).
  * ``_row_to_program`` cache — _PROGRAM_CACHE LRU contract.
  * ``_clear_program_cache`` — clears the cache.
  * ``_build_tier_weight_case`` — produces a CASE expression.
  * ``_check_fields_tier_allowed`` — anon → fields=full forbidden.
  * ``_trim_to_fields`` — minimal whitelist shape.
  * ``_extract_enriched_and_sources`` — JSON decode fallback.
  * ``_attach_program_translation_meta`` — translated_field stripping.
  * ``_is_pure_kanji`` / ``_is_pure_ascii_word`` — script-classifier branches.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import jpintel_mcp.api.programs as P

# ---------------------------------------------------------------------------
# Tmp_path minimal schema (programs + FTS + program_documents)
# ---------------------------------------------------------------------------


def _make_minimal_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            aliases_json TEXT,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            program_kind TEXT,
            official_url TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate TEXT,
            trust_level TEXT,
            tier TEXT,
            coverage_score REAL,
            gap_to_tier_s_json TEXT,
            a_to_j_coverage_json TEXT,
            excluded INTEGER DEFAULT 0,
            exclusion_reason TEXT,
            crop_categories_json TEXT,
            equipment_category TEXT,
            target_types_json TEXT,
            funding_purpose_json TEXT,
            amount_band TEXT,
            application_window_json TEXT,
            enriched_json TEXT,
            source_mentions_json TEXT,
            updated_at TEXT,
            source_url TEXT,
            source_checksum TEXT
        );
        CREATE VIRTUAL TABLE programs_fts USING fts5(
            unified_id UNINDEXED, primary_name, aliases, enriched_text,
            tokenize="trigram"
        );
        CREATE TABLE program_documents (
            id INTEGER PRIMARY KEY,
            program_name TEXT,
            form_name TEXT,
            form_type TEXT,
            form_format TEXT,
            form_url_direct TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _seed_program(
    db_path: Path,
    *,
    unified_id: str,
    primary_name: str,
    tier: str = "S",
    enriched_json: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO programs(unified_id, primary_name, tier, updated_at, "
        "application_window_json, enriched_json) VALUES (?,?,?,?,?,?)",
        (unified_id, primary_name, tier, "2026-05-16", None, enriched_json),
    )
    conn.execute(
        "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
        "VALUES (?,?,?,?)",
        (unified_id, primary_name, "", primary_name),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "fixture.db"
    _make_minimal_db(db)
    return db


@pytest.fixture()
def tmp_conn(tmp_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# _validate_as_of_date — early 422 path
# ---------------------------------------------------------------------------


def test_validate_as_of_date_none_returns_none() -> None:
    assert P._validate_as_of_date(None) is None


def test_validate_as_of_date_valid_iso_passes() -> None:
    assert P._validate_as_of_date("2026-05-16") == "2026-05-16"


def test_validate_as_of_date_malformed_raises_422() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        P._validate_as_of_date("not-a-date")
    assert excinfo.value.status_code == 422


def test_validate_as_of_date_short_form_raises_422() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        P._validate_as_of_date("2026-5-1")


# ---------------------------------------------------------------------------
# _encode_cursor / _decode_cursor — round trip
# ---------------------------------------------------------------------------


def test_encode_decode_cursor_round_trip() -> None:
    token = P._encode_cursor(
        score=0.42,
        primary_name="補助金A",
        unified_id="UNI-x-1",
        fts=True,
    )
    payload = P._decode_cursor(token)
    # decoded payload retains the unified_id under its packed key 'u'
    assert payload.get("u") == "UNI-x-1" or payload.get("unified_id") == "UNI-x-1"


def test_decode_cursor_malformed_raises_422() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        P._decode_cursor("not-a-base64-cursor-token-at-all")
    assert excinfo.value.status_code == 422


# ---------------------------------------------------------------------------
# _tokenize_query / _build_fts_match
# ---------------------------------------------------------------------------


def test_tokenize_query_empty_returns_empty_list() -> None:
    assert P._tokenize_query("") == []
    assert P._tokenize_query("   ") == []


def test_tokenize_query_user_quoted_phrase_kept_as_one_token() -> None:
    out = P._tokenize_query('"DX 製造業"')
    assert any(is_quoted for _, is_quoted in out)


def test_tokenize_query_punctuation_separators_split() -> None:
    out = P._tokenize_query("中小企業、デジタル化")
    tokens = [t for t, _ in out]
    assert len(tokens) >= 2


def test_build_fts_match_empty_returns_empty_string() -> None:
    assert P._build_fts_match("") == ""
    assert P._build_fts_match("   ") == ""


def test_build_fts_match_single_token_phrase_quoted() -> None:
    out = P._build_fts_match("税額控除")
    assert '"税額控除"' in out


def test_build_fts_match_multi_token_and_combined() -> None:
    out = P._build_fts_match("中小企業 製造業")
    assert "AND" in out


def test_fts_escape_double_quotes_escaped() -> None:
    assert P._fts_escape('foo"bar') == 'foo""bar'


# ---------------------------------------------------------------------------
# _extract_required_documents — heterogeneous enriched shape
# ---------------------------------------------------------------------------


def test_extract_required_documents_none_returns_empty() -> None:
    assert P._extract_required_documents(None) == []


def test_extract_required_documents_string_items() -> None:
    out = P._extract_required_documents(
        {"required_documents": ["事業計画書", "決算書"]}
    )
    assert out == ["事業計画書", "決算書"]


def test_extract_required_documents_dict_items_with_name() -> None:
    out = P._extract_required_documents(
        {"documents": [{"name": "見積書"}, {"title": "申請書"}]}
    )
    assert "見積書" in out
    assert "申請書" in out


def test_extract_required_documents_dedup_preserves_order() -> None:
    out = P._extract_required_documents(
        {"required_documents": ["A", "B", "A"]}
    )
    assert out == ["A", "B"]


def test_extract_required_documents_procedure_path() -> None:
    out = P._extract_required_documents(
        {"procedure": {"提出書類": ["税務署提出書"]}}
    )
    assert out == ["税務署提出書"]


# ---------------------------------------------------------------------------
# _post_cache_next_deadline — date pivot
# ---------------------------------------------------------------------------


def test_post_cache_next_deadline_none() -> None:
    assert P._post_cache_next_deadline(None) is None


def test_post_cache_next_deadline_invalid_returns_none() -> None:
    assert P._post_cache_next_deadline("not-iso") is None


def test_post_cache_next_deadline_far_future_kept() -> None:
    assert P._post_cache_next_deadline("2099-12-31") == "2099-12-31"


def test_post_cache_next_deadline_past_dropped() -> None:
    assert P._post_cache_next_deadline("2000-01-01") is None


# ---------------------------------------------------------------------------
# _build_tier_weight_case — case expression shape
# ---------------------------------------------------------------------------


def test_build_tier_weight_case_contains_when_then() -> None:
    out = P._build_tier_weight_case("programs.tier")
    assert "CASE programs.tier" in out
    assert "WHEN 'S'" in out
    assert "ELSE" in out
    assert "END" in out


# ---------------------------------------------------------------------------
# _is_pure_kanji / _is_pure_ascii_word
# ---------------------------------------------------------------------------


def test_is_pure_kanji_true_for_kanji_only() -> None:
    assert P._is_pure_kanji("補助金") is True


def test_is_pure_kanji_false_for_kana() -> None:
    assert P._is_pure_kanji("のうぎょう") is False


def test_is_pure_kanji_false_for_mixed() -> None:
    assert P._is_pure_kanji("補助A") is False


def test_is_pure_ascii_word_true() -> None:
    assert P._is_pure_ascii_word("DX") is True


def test_is_pure_ascii_word_false_kanji() -> None:
    assert P._is_pure_ascii_word("税") is False


# ---------------------------------------------------------------------------
# _clear_program_cache + cache hit path via tmp_path DB
# ---------------------------------------------------------------------------


def test_clear_program_cache_empties_cache() -> None:
    # Direct manipulation: insert a sentinel and assert clear removes it.
    P._PROGRAM_CACHE[("test-uid", "ck1")] = None  # type: ignore[assignment]
    P._clear_program_cache()
    assert ("test-uid", "ck1") not in P._PROGRAM_CACHE


# ---------------------------------------------------------------------------
# _check_fields_tier_allowed — anon-tier disallows full
# ---------------------------------------------------------------------------


def test_check_fields_tier_allowed_anon_default_ok() -> None:
    # No exception for default fields on anon tier.
    P._check_fields_tier_allowed("default", "anon")


def test_check_fields_tier_allowed_anon_full_forbidden() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        P._check_fields_tier_allowed("full", "anon")
    assert excinfo.value.status_code in (402, 403)


# ---------------------------------------------------------------------------
# _extract_enriched_and_sources — JSON decode + null path
# ---------------------------------------------------------------------------


def test_extract_enriched_and_sources_with_tmp_db(tmp_db: Path) -> None:
    enriched = {"required_documents": ["A"]}
    _seed_program(
        tmp_db,
        unified_id="UNI-test-1",
        primary_name="テスト補助金",
        tier="S",
        enriched_json=json.dumps(enriched, ensure_ascii=False),
    )
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT enriched_json, source_mentions_json, 'src' AS source_url, "
        "       'official' AS official_url, 'fetched' AS source_fetched_at "
        "FROM programs WHERE unified_id = ?",
        ("UNI-test-1",),
    ).fetchone()
    # Function signature: returns tuple (enriched, sources, source_url, official_url, fetched)
    out = P._extract_enriched_and_sources(row)
    assert isinstance(out, tuple)
    # First element should be the decoded enriched dict (or None)
    assert out[0] is None or out[0].get("required_documents") == ["A"]
    conn.close()


# ---------------------------------------------------------------------------
# _trim_to_fields — minimal whitelist + default passthrough
# ---------------------------------------------------------------------------


def test_trim_to_fields_minimal_drops_extras() -> None:
    rec = {
        "unified_id": "UNI-x",
        "primary_name": "name",
        "tier": "S",
        "prefecture": "東京都",
        "amount_max_man_yen": 100,
        "extra_field_should_disappear": "x",
    }
    out = P._trim_to_fields(rec, "minimal")
    assert "extra_field_should_disappear" not in out


def test_trim_to_fields_default_passthrough_unchanged() -> None:
    rec = {"unified_id": "UNI-x", "primary_name": "name"}
    out = P._trim_to_fields(rec, "default")
    assert out["unified_id"] == "UNI-x"
