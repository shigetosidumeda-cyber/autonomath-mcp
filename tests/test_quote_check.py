"""Tests for `jpintel_mcp.ingest.quote_check` (W2-13 caveat #2).

Covers cache-hit (substring required) and cache-miss (form-only fallback
with warning log).
"""

from __future__ import annotations

import logging

import pytest

from jpintel_mcp.ingest import quote_check


def test_form_check_short_quote_fails(tmp_path):
    # length < 4 → form check fails regardless of cache state.
    assert quote_check.literal_quote_pass("abc", "p1", cache_dir=tmp_path) is False


def test_form_check_whitespace_only_fails(tmp_path):
    assert quote_check.literal_quote_pass("    \n", "p1", cache_dir=tmp_path) is False


def test_cache_hit_substring_match(tmp_path):
    (tmp_path / "p_xyz.txt").write_text(
        "中小企業向け補助金の対象は売上高 5 億円以下とする。\n",
        encoding="utf-8",
    )
    quote = "売上高 5 億円以下"
    assert quote_check.literal_quote_pass(quote, "p_xyz", cache_dir=tmp_path) is True


def test_cache_hit_substring_mismatch_returns_false(tmp_path):
    (tmp_path / "p_xyz.txt").write_text(
        "中小企業向け補助金の対象は売上高 5 億円以下とする。\n",
        encoding="utf-8",
    )
    fabricated = "売上高 1 兆円以下"  # not in cache
    assert (
        quote_check.literal_quote_pass(
            fabricated,
            "p_xyz",
            cache_dir=tmp_path,
        )
        is False
    )


def test_cache_miss_falls_back_to_form_only_with_warning(tmp_path, caplog):
    # Reset module-level dedup so the warning fires for this test.
    quote_check._WARNED_MISSING.clear()
    quote = "対象事業者は中小企業に限る"  # ≥4 chars, non-whitespace
    with caplog.at_level(logging.WARNING, logger="jpintel_mcp.ingest.quote_check"):
        result = quote_check.literal_quote_pass(
            quote,
            "p_no_cache",
            cache_dir=tmp_path,
        )
    assert result is True  # form-only fallback
    assert any("kobo_text_cache MISS" in r.message for r in caplog.records)


def test_cache_miss_warning_dedup_per_id(tmp_path, caplog):
    quote_check._WARNED_MISSING.clear()
    quote = "対象事業者は中小企業に限る"
    with caplog.at_level(logging.WARNING, logger="jpintel_mcp.ingest.quote_check"):
        quote_check.literal_quote_pass(quote, "p_dedup", cache_dir=tmp_path)
        quote_check.literal_quote_pass(quote, "p_dedup", cache_dir=tmp_path)
        quote_check.literal_quote_pass(quote, "p_dedup", cache_dir=tmp_path)
    miss_logs = [r for r in caplog.records if "kobo_text_cache MISS" in r.message]
    assert len(miss_logs) == 1


def test_kobo_text_cache_returns_none_on_missing_file(tmp_path):
    assert quote_check.kobo_text_cache("nope", cache_dir=tmp_path) is None


def test_kobo_text_cache_returns_text_on_hit(tmp_path):
    (tmp_path / "p_hit.txt").write_text("hello world", encoding="utf-8")
    assert quote_check.kobo_text_cache("p_hit", cache_dir=tmp_path) == "hello world"


def test_empty_program_unified_id_falls_back_to_form_only(tmp_path):
    # No id → cannot look up cache; form-only pass for non-empty ≥4 quote.
    assert (
        quote_check.literal_quote_pass(
            "this is a quote",
            None,
            cache_dir=tmp_path,
        )
        is True
    )


@pytest.mark.parametrize("quote", ["", "a", "ab", "abc"])
def test_form_check_below_min_length(tmp_path, quote):
    assert quote_check.literal_quote_pass(quote, "p", cache_dir=tmp_path) is False
