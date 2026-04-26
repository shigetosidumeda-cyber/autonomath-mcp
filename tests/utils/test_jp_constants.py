"""Tests for jpintel_mcp.utils.jp_constants — verbatim port verification."""

from __future__ import annotations

import pytest

from jpintel_mcp.utils.jp_constants import (
    INDUSTRY_ALIAS_TO_JSIC,
    INDUSTRY_KEYWORDS,
    NICHE_PROGRAM_KEYWORDS,
    PREFECTURE_TO_REGION,
    industry_relevance_keywords,
    is_niche_program,
    normalize_industry,
    prefecture_region,
)


# ── table-shape invariants ─────────────────────────────────────────
def test_industry_alias_table_size() -> None:
    """22 alias pairs in Autonomath source (task spec said ~23, real count is 22)."""
    assert len(INDUSTRY_ALIAS_TO_JSIC) == 22


def test_prefecture_table_size() -> None:
    """All 47 prefectures must be present."""
    assert len(PREFECTURE_TO_REGION) == 47


def test_industry_keywords_table_size() -> None:
    """13 industries in Autonomath source."""
    assert len(INDUSTRY_KEYWORDS) == 13


def test_niche_keywords_size() -> None:
    """27 unique niche-program keywords in Autonomath source (task spec said 19, real count is 27)."""
    assert len(NICHE_PROGRAM_KEYWORDS) == 27


def test_all_47_prefectures_present() -> None:
    expected = {
        "北海道",
        "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
        "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
        "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
        "岐阜県", "静岡県", "愛知県",
        "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
        "鳥取県", "島根県", "岡山県", "広島県", "山口県",
        "徳島県", "香川県", "愛媛県", "高知県",
        "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
        "沖縄県",
    }
    assert set(PREFECTURE_TO_REGION) == expected
    # Region values must be drawn from the canonical 9-block taxonomy.
    assert set(PREFECTURE_TO_REGION.values()) == {
        "北海道", "東北", "関東", "中部", "近畿", "中国", "四国", "九州", "沖縄",
    }


# ── normalize_industry ─────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("農業", "農業、林業"),
        ("IT", "情報通信業"),
        ("it", "情報通信業"),
        ("医療", "医療、福祉"),
        ("製造業", "製造業"),  # already canonical-ish in alias table
        ("宇宙開発", "宇宙開発"),  # unknown → returned as-is
        ("", ""),  # empty fallback
    ],
)
def test_normalize_industry(raw: str, expected: str) -> None:
    assert normalize_industry(raw) == expected


# ── prefecture_region ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("pref", "expected"),
    [
        ("東京都", "関東"),
        ("北海道", "北海道"),
        ("沖縄県", "沖縄"),
        ("大阪府", "近畿"),
        ("Tokyo", None),       # unknown
        ("", None),            # empty
    ],
)
def test_prefecture_region(pref: str, expected: str | None) -> None:
    assert prefecture_region(pref) == expected


# ── is_niche_program ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("NEDO新エネルギーベンチャー助成", True),       # contains "NEDO"
        ("ZEB化支援事業", True),                       # contains "ZEB"
        ("グローバル展開支援補助金", True),            # contains "グローバル展開"
        ("林業就業支援", True),                        # contains "林業"
        ("ものづくり補助金", False),                   # no niche keyword
        ("小規模事業者持続化補助金", False),
        ("", False),                                   # empty
    ],
)
def test_is_niche_program(name: str, expected: bool) -> None:
    assert is_niche_program(name) is expected


# ── industry_relevance_keywords ────────────────────────────────────
def test_industry_relevance_keywords_known() -> None:
    kws = industry_relevance_keywords("農業")
    assert isinstance(kws, tuple)
    assert "就農" in kws
    assert "スマート農" in kws


def test_industry_relevance_keywords_it_branch() -> None:
    kws = industry_relevance_keywords("IT")
    assert "AI" in kws
    assert "DX" in kws


def test_industry_relevance_keywords_unknown() -> None:
    assert industry_relevance_keywords("宇宙開発") == ()
    assert industry_relevance_keywords("") == ()
