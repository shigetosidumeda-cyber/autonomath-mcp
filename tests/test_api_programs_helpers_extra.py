"""Additional pure-function tests for ``api.programs`` (Stream EE, 80%→85%).

Builds on ``tests/test_api_programs_pure.py`` (Stream CC). Targets the
private helpers not yet covered:
  * ``_is_pure_kanji`` / ``_is_pure_ascii_word`` — script-class detectors.
  * ``_fts_escape`` — phrase-literal quote-escape.
  * ``_tokenize_query`` — punctuation + user-quoted multi-token paths.
  * ``_build_fts_match`` — single token, KANA_EXPANSIONS OR, multi-token AND,
    user-quoted preservation, empty / punctuation-only short-circuit.
  * ``_encode_cursor`` / ``_decode_cursor`` — JSON round-trip + 422 paths.
  * ``KANA_EXPANSIONS`` lookup behavior via _build_fts_match.

NO DB / HTTP / LLM calls. All pure Python over module-private helpers.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import jpintel_mcp.api.programs as p

# ---------------------------------------------------------------------------
# _is_pure_kanji
# ---------------------------------------------------------------------------


def test_is_pure_kanji_pure_kanji_text() -> None:
    assert p._is_pure_kanji("税額控除") is True


def test_is_pure_kanji_with_kana_returns_false() -> None:
    assert p._is_pure_kanji("ふるさと納税") is False


def test_is_pure_kanji_with_ascii_returns_false() -> None:
    assert p._is_pure_kanji("税ABC") is False


def test_is_pure_kanji_empty_returns_false() -> None:
    assert p._is_pure_kanji("") is False


def test_is_pure_kanji_only_ascii_returns_false() -> None:
    assert p._is_pure_kanji("abc") is False


# ---------------------------------------------------------------------------
# _is_pure_ascii_word
# ---------------------------------------------------------------------------


def test_is_pure_ascii_word_alnum_returns_true() -> None:
    assert p._is_pure_ascii_word("IT") is True
    assert p._is_pure_ascii_word("DX2024") is True


def test_is_pure_ascii_word_with_space_returns_false() -> None:
    assert p._is_pure_ascii_word("IT 導入") is False


def test_is_pure_ascii_word_empty_returns_false() -> None:
    assert p._is_pure_ascii_word("") is False


# ---------------------------------------------------------------------------
# _fts_escape
# ---------------------------------------------------------------------------


def test_fts_escape_doubles_quote_chars() -> None:
    assert p._fts_escape('foo"bar') == 'foo""bar'


def test_fts_escape_passes_through_clean_strings() -> None:
    assert p._fts_escape("補助金") == "補助金"


# ---------------------------------------------------------------------------
# _tokenize_query
# ---------------------------------------------------------------------------


def test_tokenize_query_empty_returns_empty() -> None:
    assert p._tokenize_query("") == []


def test_tokenize_query_single_token_unquoted() -> None:
    out = p._tokenize_query("補助金")
    assert out == [("補助金", False)]


def test_tokenize_query_multiple_tokens_split_on_whitespace() -> None:
    out = p._tokenize_query("補助金 中小企業")
    assert out == [("補助金", False), ("中小企業", False)]


def test_tokenize_query_user_quoted_phrase_preserved() -> None:
    out = p._tokenize_query('"中小企業 デジタル化"')
    assert out == [("中小企業 デジタル化", True)]


def test_tokenize_query_unquoted_punctuation_dropped() -> None:
    out = p._tokenize_query("補助金、中小企業")
    # 、 is a separator.
    assert ("補助金", False) in out
    assert ("中小企業", False) in out


def test_tokenize_query_fts_special_chars_stripped() -> None:
    # `(税)` → ' 税 ' after strip → token "税".
    out = p._tokenize_query("(税)")
    assert ("税", False) in out


# ---------------------------------------------------------------------------
# _build_fts_match
# ---------------------------------------------------------------------------


def test_build_fts_match_empty_returns_empty() -> None:
    assert p._build_fts_match("") == ""


def test_build_fts_match_whitespace_only_returns_empty() -> None:
    assert p._build_fts_match("   ") == ""


def test_build_fts_match_punctuation_only_returns_empty() -> None:
    assert p._build_fts_match("**") == ""


def test_build_fts_match_single_token_phrase_quoted() -> None:
    out = p._build_fts_match("補助金")
    assert out == '"補助金"'


def test_build_fts_match_kana_expands_to_or_clause() -> None:
    # `のうぎょう` expands to include `農業`.
    out = p._build_fts_match("のうぎょう")
    assert '"のうぎょう"' in out
    assert '"農業"' in out
    assert " OR " in out


def test_build_fts_match_quoted_kana_does_not_expand() -> None:
    # User explicitly typed "..." → no expansion.
    out = p._build_fts_match('"のうぎょう"')
    assert '"のうぎょう"' in out
    assert "農業" not in out


def test_build_fts_match_multi_token_joined_by_and() -> None:
    out = p._build_fts_match("補助金 中小企業")
    assert " AND " in out
    assert '"補助金"' in out
    assert '"中小企業"' in out


def test_build_fts_match_nfkc_normalises_fullwidth_ascii() -> None:
    # `ＩＴ` should normalize to `IT` then phrase quote.
    out = p._build_fts_match("ＩＴ")
    assert "IT" in out


# ---------------------------------------------------------------------------
# _encode_cursor / _decode_cursor
# ---------------------------------------------------------------------------


def test_encode_decode_cursor_roundtrip() -> None:
    token = p._encode_cursor(
        score=12.3,
        primary_name="補助金A",
        unified_id="UNI-1",
        fts=True,
        raw_query="補助金",
        literal_rank=1,
    )
    out = p._decode_cursor(token)
    assert out["s"] == 12.3
    assert out["n"] == "補助金A"
    assert out["u"] == "UNI-1"
    assert out["f"] == 1
    assert out["q"] == "補助金"
    assert out["l"] == 1


def test_encode_cursor_nan_score_coerced_to_none() -> None:
    token = p._encode_cursor(
        score=float("nan"),
        primary_name="p",
        unified_id="UNI-x",
        fts=False,
    )
    out = p._decode_cursor(token)
    assert out["s"] is None


def test_encode_cursor_inf_score_coerced_to_none() -> None:
    token = p._encode_cursor(
        score=float("inf"),
        primary_name="p",
        unified_id="UNI-x",
        fts=False,
    )
    out = p._decode_cursor(token)
    assert out["s"] is None


def test_decode_cursor_malformed_base64_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        p._decode_cursor("***not-base64***")
    assert exc.value.status_code == 422


def test_decode_cursor_missing_unified_id_raises_422() -> None:
    import base64
    import json

    payload = {"v": p._CURSOR_VERSION, "s": 1.0, "n": "x", "f": 0}
    raw = json.dumps(payload).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(HTTPException) as exc:
        p._decode_cursor(token)
    assert exc.value.status_code == 422


def test_decode_cursor_wrong_version_raises_422() -> None:
    import base64
    import json

    payload = {"v": 99, "s": 1.0, "n": "x", "u": "UNI-1", "f": 0}
    raw = json.dumps(payload).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(HTTPException) as exc:
        p._decode_cursor(token)
    assert exc.value.status_code == 422
