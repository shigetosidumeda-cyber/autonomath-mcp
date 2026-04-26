"""Tests for the API-boundary vocab normalizers.

The whole point is: LLM agents should not have to call ``enum_values`` and
retry when they send a natural variant of a prefecture / industry code /
authority level. These tests lock in the canonical mapping so future
refactors can't silently regress.
"""
from __future__ import annotations

import pytest

from jpintel_mcp.api.vocab import (
    _normalize_authority_level,
    _normalize_industry_jsic,
    _normalize_prefecture,
)

# ---------------------------------------------------------------------------
# prefecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        # canonical is idempotent
        ("東京都", "東京都"),
        ("北海道", "北海道"),
        ("全国", "全国"),
        # short JP form drops suffix — we add it back
        ("東京", "東京都"),
        ("大阪", "大阪府"),
        ("北海道", "北海道"),  # already no suffix
        # romaji variants (case-insensitive)
        ("tokyo", "東京都"),
        ("Tokyo", "東京都"),
        ("TOKYO", "東京都"),
        ("hokkaido", "北海道"),
        ("osaka", "大阪府"),
        ("okinawa", "沖縄県"),
        # nationwide synonyms
        ("national", "全国"),
        ("all", "全国"),
        ("japan", "全国"),
        # unknown passes through unchanged so the caller sees 0 rows,
        # not a silent rewrite
        ("Atlantis", "Atlantis"),
        ("東", "東"),
    ],
)
def test_normalize_prefecture_maps_to_canonical(value: str, expected: str) -> None:
    assert _normalize_prefecture(value) == expected


def test_normalize_prefecture_handles_none_and_empty() -> None:
    assert _normalize_prefecture(None) is None
    assert _normalize_prefecture("") is None
    assert _normalize_prefecture("   ") is None


def test_normalize_prefecture_strips_whitespace() -> None:
    assert _normalize_prefecture("  東京  ") == "東京都"
    assert _normalize_prefecture("\tTokyo\n") == "東京都"


# ---------------------------------------------------------------------------
# industry_jsic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        # canonical single letter is idempotent (and upper-cased)
        ("A", "A"),
        ("E", "E"),
        ("a", "A"),
        ("e", "E"),
        # common JP full names (no 、) → letter
        ("農業林業", "A"),
        ("建設業", "D"),
        ("製造業", "E"),
        ("情報通信業", "G"),
        # short JP aliases users actually type
        ("農業", "A"),
        ("建設", "D"),
        ("製造", "E"),
        ("IT", "G"),
        ("ソフトウェア", "G"),
        ("小売", "I"),
        ("飲食店", "M"),
        ("医療", "P"),
        # EN slugs
        ("manufacturing", "E"),
        ("construction", "D"),
        ("healthcare_welfare", "P"),
        # 中分類 / 小分類 digit codes: pass through verbatim so LIKE-prefix
        # against DB-stored JSIC codes keeps working
        ("29", "29"),
        ("E29", "E29"),
        # unknown → pass-through
        ("宇宙業", "宇宙業"),
    ],
)
def test_normalize_industry_jsic(value: str, expected: str) -> None:
    assert _normalize_industry_jsic(value) == expected


def test_normalize_industry_jsic_none_empty() -> None:
    assert _normalize_industry_jsic(None) is None
    assert _normalize_industry_jsic("") is None
    assert _normalize_industry_jsic("   ") is None


# ---------------------------------------------------------------------------
# authority_level (regression — existing behavior must survive the refactor)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("national", "national"),
        ("prefecture", "prefecture"),
        ("municipality", "municipality"),
        ("financial", "financial"),
        ("NATIONAL", "national"),
        ("National", "national"),
        ("国", "national"),
        ("都道府県", "prefecture"),
        ("市区町村", "municipality"),
        ("公庫", "financial"),
        ("unknown_value", "unknown_value"),
    ],
)
def test_normalize_authority_level(value: str, expected: str) -> None:
    assert _normalize_authority_level(value) == expected


def test_normalize_authority_level_none_empty() -> None:
    assert _normalize_authority_level(None) is None
    assert _normalize_authority_level("") is None
