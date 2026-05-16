"""Stream T coverage gap: utils/ — wareki / jp_money / slug / jp_constants.

Targets ``src/jpintel_mcp/utils/`` — exercising the era conversion,
yen parser/formatter, hepburn slug, and jp_constants lookup tables.
No DB / network / LLM — all stdlib + pykakasi (optional dep).

No source mutation. Fixtures inline.
"""

from __future__ import annotations

import datetime

import pytest

from jpintel_mcp.utils.jp_constants import (
    INDUSTRY_ALIAS_TO_JSIC,
    PREFECTURE_TO_REGION,
)
from jpintel_mcp.utils.jp_money import format_yen, parse_yen, parse_yen_range
from jpintel_mcp.utils.slug import program_static_slug, program_static_url
from jpintel_mcp.utils.wareki import (
    parse_wareki_date,
    parse_wareki_year,
    to_wareki,
    to_wareki_year,
)

# ---------------------------------------------------------------------------
# wareki — parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("令和元年5月1日", datetime.date(2019, 5, 1)),
        ("令和6年4月1日", datetime.date(2024, 4, 1)),
        ("平成31年4月30日", datetime.date(2019, 4, 30)),
        ("昭和64年1月7日", datetime.date(1989, 1, 7)),
        ("大正15年12月24日", datetime.date(1926, 12, 24)),
        ("明治45年7月29日", datetime.date(1912, 7, 29)),
        ("R6.4.1", datetime.date(2024, 4, 1)),
        ("H31.4.30", datetime.date(2019, 4, 30)),
    ],
)
def test_parse_wareki_date_valid(raw: str, expected: datetime.date) -> None:
    assert parse_wareki_date(raw) == expected


def test_parse_wareki_date_rejects_out_of_era() -> None:
    # 平成31年5月1日 is past 平成 end (2019-04-30) → ValueError
    with pytest.raises(ValueError):
        parse_wareki_date("平成31年5月1日")


def test_parse_wareki_date_rejects_unknown_era() -> None:
    with pytest.raises(ValueError):
        parse_wareki_date("Z1年1月1日")


def test_parse_wareki_year_valid() -> None:
    assert parse_wareki_year("令和6年") == 2024
    assert parse_wareki_year("平成31") == 2019  # year-only ok


# ---------------------------------------------------------------------------
# wareki — formatting
# ---------------------------------------------------------------------------


def test_to_wareki_long() -> None:
    out = to_wareki(datetime.date(2024, 4, 1))
    assert out == "令和6年4月1日"


def test_to_wareki_short() -> None:
    out = to_wareki(datetime.date(2024, 4, 1), era_format="short")
    assert out == "R6.4.1"


def test_to_wareki_year_long() -> None:
    assert to_wareki_year(2024) == "令和6年"


def test_to_wareki_invalid_format() -> None:
    with pytest.raises(ValueError):
        to_wareki(datetime.date(2024, 4, 1), era_format="weird")


def test_to_wareki_rejects_pre_meiji() -> None:
    with pytest.raises(ValueError):
        to_wareki(datetime.date(1860, 1, 1))


# ---------------------------------------------------------------------------
# jp_money — parse_yen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,000", 1000),
        ("¥1,000", 1000),
        ("￥1,000", 1000),
        ("1,000円", 1000),
        ("1万", 10000),
        ("1.5万", 15000),
        ("1億", 100_000_000),
        ("1億2,000万", 120_000_000),
        ("△500", -500),
        ("(500)", -500),
        ("（500）", -500),
        ("△(500)", 500),  # double negation
    ],
)
def test_parse_yen_table(raw: str, expected: int) -> None:
    assert parse_yen(raw) == expected


def test_parse_yen_full_width_via_nfkc() -> None:
    # ０ = full-width 0; NFKC → ASCII 0
    assert parse_yen("１,０００円") == 1000


def test_parse_yen_passthrough_int_and_float() -> None:
    assert parse_yen(1500) == 1500
    assert parse_yen(1500.7) == 1500  # truncate, not round


def test_parse_yen_rejects_none_and_bool() -> None:
    with pytest.raises(ValueError):
        parse_yen(None)
    with pytest.raises(ValueError):
        parse_yen(True)  # bool is int subclass; rejected explicitly


def test_parse_yen_rejects_percentage() -> None:
    with pytest.raises(ValueError, match="percentage"):
        parse_yen("50%")


def test_parse_yen_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_yen("")
    with pytest.raises(ValueError):
        parse_yen("   ")


# ---------------------------------------------------------------------------
# jp_money — parse_yen_range
# ---------------------------------------------------------------------------


def test_parse_yen_range_full_form() -> None:
    assert parse_yen_range("100万〜500万") == (1_000_000, 5_000_000)


def test_parse_yen_range_kara_form() -> None:
    assert parse_yen_range("100万円から500万円") == (1_000_000, 5_000_000)


def test_parse_yen_range_propagates_unit_leftward() -> None:
    # "100-500万" means both sides should be in 万 units
    assert parse_yen_range("100-500万") == (1_000_000, 5_000_000)


def test_parse_yen_range_single_value_returns_both_same() -> None:
    assert parse_yen_range("500万") == (5_000_000, 5_000_000)


def test_parse_yen_range_swaps_when_inverted() -> None:
    # 500-100万 → low=1M, high=5M after swap
    low, high = parse_yen_range("500-100万")
    assert low <= high


# ---------------------------------------------------------------------------
# jp_money — format_yen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [
        (1500, "1,500円"),
        (10000, "1万円"),
        (15000, "1.5万円"),
        (100_000_000, "1億円"),
        (150_000_000, "1.5億円"),
        (-5000, "-5,000円"),
    ],
)
def test_format_yen_auto(n: int, expected: str) -> None:
    assert format_yen(n) == expected


def test_format_yen_explicit_unit() -> None:
    assert format_yen(500_000, unit="man") == "50万円"
    assert format_yen(100_000_000, unit="yen") == "100,000,000円"


def test_format_yen_rejects_non_int() -> None:
    with pytest.raises(ValueError):
        format_yen("1000")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        format_yen(True)  # bool is int but rejected


def test_format_yen_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError):
        format_yen(1000, unit="weird")


# ---------------------------------------------------------------------------
# slug — program_static_slug / program_static_url
# ---------------------------------------------------------------------------


def test_program_static_slug_has_sha1_suffix() -> None:
    slug = program_static_slug("ものづくり補助金", "unified-id-001")
    # Always ends in -<6 hex chars>
    parts = slug.rsplit("-", 1)
    assert len(parts) == 2
    assert len(parts[1]) == 6
    assert all(c in "0123456789abcdef" for c in parts[1])


def test_program_static_slug_handles_empty_name() -> None:
    slug = program_static_slug(None, "unified-id-002")
    # Falls back to 'program' base name
    assert slug.startswith("program-")


def test_program_static_slug_stable_for_same_id() -> None:
    assert program_static_slug("X", "id-3") == program_static_slug("X", "id-3")


def test_program_static_slug_unique_for_different_ids() -> None:
    a = program_static_slug("ものづくり", "id-A")
    b = program_static_slug("ものづくり", "id-B")
    assert a != b


def test_program_static_url_returns_relative_by_default() -> None:
    url = program_static_url("X", "id-1")
    assert url.startswith("/programs/")
    assert url.endswith(".html")


def test_program_static_url_with_domain() -> None:
    url = program_static_url("X", "id-1", domain="jpcite.com")
    assert url.startswith("https://jpcite.com/programs/")


def test_program_static_url_strips_trailing_slash() -> None:
    url = program_static_url("X", "id-1", domain="jpcite.com/")
    assert url.startswith("https://jpcite.com/programs/")
    # Ensure no double slash
    assert "//programs/" not in url[len("https://") :]


# ---------------------------------------------------------------------------
# jp_constants — lookup tables
# ---------------------------------------------------------------------------


def test_industry_alias_to_jsic_has_expected_aliases() -> None:
    assert INDUSTRY_ALIAS_TO_JSIC["農業"] == "農業、林業"
    assert INDUSTRY_ALIAS_TO_JSIC["IT"] == "情報通信業"
    assert INDUSTRY_ALIAS_TO_JSIC["it"] == "情報通信業"


def test_prefecture_to_region_47_entries() -> None:
    # Should have exactly 47 prefectures
    assert len(PREFECTURE_TO_REGION) == 47


def test_prefecture_to_region_canonical_buckets() -> None:
    assert PREFECTURE_TO_REGION["東京都"] == "関東"
    assert PREFECTURE_TO_REGION["大阪府"] == "近畿"
    assert PREFECTURE_TO_REGION["北海道"] == "北海道"
    # 沖縄県 is its own region bucket per jp_constants source.
    assert PREFECTURE_TO_REGION["沖縄県"] in ("沖縄", "九州")
