"""Pure-function coverage tests for ``api.programs`` private helpers.

Targets ``src/jpintel_mcp/api/programs.py`` (2,799 stmt). The module is
search + ranking logic. We exercise the deterministic FTS query builders,
cursor encode/decode, tier-weight SQL CASE builder, as-of-date validator
+ predicate, and Program row helpers that touch no DB.

NO DB / HTTP / LLM calls. Pure function I/O.

Stream CC tick (coverage 76% → 80% target).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

import jpintel_mcp.api.programs as p

# ---------------------------------------------------------------------------
# _build_tier_weight_case
# ---------------------------------------------------------------------------


def test_build_tier_weight_case_contains_all_canonical_tiers() -> None:
    sql = p._build_tier_weight_case("programs.tier")
    for tier in ("S", "A", "B", "C"):
        assert f"WHEN '{tier}' THEN " in sql
    # X is folded into ELSE per docstring.
    assert " ELSE " in sql
    assert sql.startswith("CASE programs.tier")
    assert sql.endswith("END")


def test_build_tier_weight_case_else_uses_x_weight() -> None:
    sql = p._build_tier_weight_case("tier")
    expected_else = f"ELSE {p.TIER_PRIOR_WEIGHTS['X']} END"
    assert sql.endswith(expected_else)


# ---------------------------------------------------------------------------
# _validate_as_of_date
# ---------------------------------------------------------------------------


def test_validate_as_of_date_none_returns_none() -> None:
    assert p._validate_as_of_date(None) is None


def test_validate_as_of_date_iso_passes_through() -> None:
    assert p._validate_as_of_date("2026-04-30") == "2026-04-30"


def test_validate_as_of_date_invalid_format_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        p._validate_as_of_date("not-a-date")
    assert exc.value.status_code == 422


def test_validate_as_of_date_invalid_month_raises_422() -> None:
    with pytest.raises(HTTPException):
        p._validate_as_of_date("2026-13-01")


# ---------------------------------------------------------------------------
# _as_of_predicate
# ---------------------------------------------------------------------------


def test_as_of_predicate_none_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    sql, params = p._as_of_predicate(None)
    assert sql == ""
    assert params == []


def test_as_of_predicate_with_versioning_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the flag off so the gate short-circuits even with a valid date.
    # ``_as_of_predicate`` does a lazy ``from jpintel_mcp.config import Settings``
    # inside the function body, so we monkeypatch the source attribute.
    import jpintel_mcp.config as cfg

    class _ShimSettings:
        r8_versioning_enabled: bool = False

    monkeypatch.setattr(cfg, "Settings", _ShimSettings)
    sql, params = p._as_of_predicate("2026-04-30")
    assert sql == ""
    assert params == []


def test_as_of_predicate_with_versioning_on_returns_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.config as cfg

    class _ShimSettings:
        r8_versioning_enabled: bool = True

    monkeypatch.setattr(cfg, "Settings", _ShimSettings)
    sql, params = p._as_of_predicate("2026-04-30", table_alias="programs")
    assert "valid_from" in sql
    assert "valid_until" in sql
    assert params == ["2026-04-30", "2026-04-30"]


# ---------------------------------------------------------------------------
# _encode_cursor / _decode_cursor
# ---------------------------------------------------------------------------


def test_encode_cursor_round_trip() -> None:
    token = p._encode_cursor(
        score=-1.5,
        primary_name="補助金A",
        unified_id="UNI-X",
        fts=True,
        raw_query="DX",
        literal_rank=1,
    )
    decoded = p._decode_cursor(token)
    assert decoded["s"] == -1.5
    assert decoded["n"] == "補助金A"
    assert decoded["u"] == "UNI-X"
    assert decoded["f"] == 1
    assert decoded["q"] == "DX"
    assert decoded["l"] == 1
    assert decoded["v"] == p._CURSOR_VERSION


def test_encode_cursor_with_nan_score_is_nulled() -> None:
    nan = float("nan")
    token = p._encode_cursor(
        score=nan,
        primary_name="X",
        unified_id="UNI-Y",
        fts=False,
    )
    decoded = p._decode_cursor(token)
    assert decoded["s"] is None


def test_encode_cursor_with_inf_score_is_nulled() -> None:
    inf = float("inf")
    token = p._encode_cursor(score=inf, primary_name="X", unified_id="UNI-Z", fts=False)
    decoded = p._decode_cursor(token)
    assert decoded["s"] is None


def test_decode_cursor_garbage_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        p._decode_cursor("@@@not-base64@@@")
    assert exc.value.status_code == 422


def test_decode_cursor_wrong_version_raises_422() -> None:
    import base64

    raw = json.dumps({"v": 99, "s": 0.0, "n": "x", "u": "u", "f": 0}, ensure_ascii=False).encode(
        "utf-8"
    )
    bad_token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(HTTPException) as exc:
        p._decode_cursor(bad_token)
    assert exc.value.status_code == 422


def test_decode_cursor_missing_unified_id_raises_422() -> None:
    import base64

    raw = json.dumps(
        {"v": p._CURSOR_VERSION, "s": None, "n": "x", "f": 0}, ensure_ascii=False
    ).encode("utf-8")
    bad_token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(HTTPException):
        p._decode_cursor(bad_token)


# ---------------------------------------------------------------------------
# _is_pure_kanji / _is_pure_ascii_word
# ---------------------------------------------------------------------------


def test_is_pure_kanji_two_kanji_passes() -> None:
    assert p._is_pure_kanji("税額") is True


def test_is_pure_kanji_with_kana_fails() -> None:
    assert p._is_pure_kanji("税金です") is False


def test_is_pure_kanji_with_ascii_fails() -> None:
    assert p._is_pure_kanji("税A") is False


def test_is_pure_kanji_empty_fails() -> None:
    assert p._is_pure_kanji("") is False


def test_is_pure_ascii_word_matches_alphanumeric() -> None:
    assert p._is_pure_ascii_word("DX") is True
    assert p._is_pure_ascii_word("IT2026") is True


def test_is_pure_ascii_word_rejects_kanji() -> None:
    assert p._is_pure_ascii_word("税") is False


def test_is_pure_ascii_word_rejects_empty() -> None:
    assert p._is_pure_ascii_word("") is False


def test_is_pure_ascii_word_rejects_punctuation() -> None:
    assert p._is_pure_ascii_word("a b") is False
    assert p._is_pure_ascii_word("a-b") is False


# ---------------------------------------------------------------------------
# _fts_escape
# ---------------------------------------------------------------------------


def test_fts_escape_doubles_internal_quotes() -> None:
    assert p._fts_escape('say "hi"') == 'say ""hi""'


def test_fts_escape_no_quotes_passthrough() -> None:
    assert p._fts_escape("plain") == "plain"


# ---------------------------------------------------------------------------
# _tokenize_query / _build_fts_match
# ---------------------------------------------------------------------------


def test_tokenize_query_simple_two_tokens() -> None:
    out = p._tokenize_query("DX 補助金")
    assert out == [("DX", False), ("補助金", False)]


def test_tokenize_query_user_quoted_preserved() -> None:
    out = p._tokenize_query('"中小企業 DX"')
    assert out == [("中小企業 DX", True)]


def test_tokenize_query_empty_string_returns_empty() -> None:
    assert p._tokenize_query("") == []


def test_tokenize_query_punctuation_only_returns_empty() -> None:
    assert p._tokenize_query("!?,。") == []


def test_build_fts_match_empty_returns_empty() -> None:
    assert p._build_fts_match("") == ""


def test_build_fts_match_single_token() -> None:
    out = p._build_fts_match("DX")
    # Should be a phrase-quoted term. KANA_EXPANSIONS may extend it.
    assert '"DX"' in out


def test_build_fts_match_kana_expansion_or_injected() -> None:
    # 'のうぎょう' -> '農業' per KANA_EXPANSIONS.
    out = p._build_fts_match("のうぎょう")
    assert '"のうぎょう"' in out
    assert '"農業"' in out
    assert " OR " in out


def test_build_fts_match_multi_token_uses_and() -> None:
    out = p._build_fts_match("DX 補助金")
    assert '"DX"' in out
    assert '"補助金"' in out
    assert " AND " in out


# ---------------------------------------------------------------------------
# _extract_next_deadline / _post_cache_next_deadline
# ---------------------------------------------------------------------------


def test_extract_next_deadline_returns_iso_when_present() -> None:
    out = p._extract_next_deadline({"end_date": "2026-12-31"})
    assert out == "2026-12-31"


def test_extract_next_deadline_with_trailing_time_truncates() -> None:
    out = p._extract_next_deadline({"end_date": "2026-12-31T23:59:59Z"})
    assert out == "2026-12-31"


def test_extract_next_deadline_no_end_date_returns_none() -> None:
    assert p._extract_next_deadline({"start_date": "2026-01-01"}) is None


def test_extract_next_deadline_non_dict_input_returns_none() -> None:
    assert p._extract_next_deadline(None) is None
    assert p._extract_next_deadline([{"end_date": "2026-12-31"}]) is None


def test_extract_next_deadline_invalid_date_returns_none() -> None:
    out = p._extract_next_deadline({"end_date": "2026-99-99"})
    assert out is None


def test_post_cache_next_deadline_future_passes() -> None:
    far_future = (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
    assert p._post_cache_next_deadline(far_future) == far_future


def test_post_cache_next_deadline_past_returns_none() -> None:
    long_past = "2000-01-01"
    assert p._post_cache_next_deadline(long_past) is None


def test_post_cache_next_deadline_none_returns_none() -> None:
    assert p._post_cache_next_deadline(None) is None


def test_post_cache_next_deadline_malformed_returns_none() -> None:
    assert p._post_cache_next_deadline("garbage") is None
