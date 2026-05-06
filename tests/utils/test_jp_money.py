"""Tests for src/jpintel_mcp/utils/jp_money.py."""

from __future__ import annotations

import pytest

from jpintel_mcp.utils.jp_money import format_yen, parse_yen, parse_yen_range

# ---------------------------------------------------------------------------
# parse_yen — happy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,000", 1_000),
        ("¥1,000", 1_000),
        ("￥1,000", 1_000),
        ("1,000円", 1_000),
        ("1万", 10_000),
        ("1万円", 10_000),
        ("1.5万", 15_000),
        ("1.5万円", 15_000),
        ("1億", 100_000_000),
        ("1億円", 100_000_000),
        ("1億2,000万", 120_000_000),
        ("1億2000万円", 120_000_000),
        ("5,000,000", 5_000_000),
        ("0", 0),
        ("0円", 0),
        ("100", 100),
    ],
)
def test_parse_yen_happy(raw: str, expected: int) -> None:
    assert parse_yen(raw) == expected


# ---------------------------------------------------------------------------
# parse_yen — negative markers
# ---------------------------------------------------------------------------


def test_parse_yen_triangle_negative() -> None:
    assert parse_yen("△500") == -500


def test_parse_yen_black_triangle_negative() -> None:
    assert parse_yen("▲1,000") == -1_000


def test_parse_yen_paren_negative() -> None:
    assert parse_yen("(500)") == -500


def test_parse_yen_fullwidth_paren_negative() -> None:
    assert parse_yen("（500）") == -500


def test_parse_yen_paren_negative_with_yen_suffix() -> None:
    assert parse_yen("(1,000円)") == -1_000


def test_parse_yen_minus_negative() -> None:
    assert parse_yen("-500") == -500


def test_parse_yen_double_negative_cancels() -> None:
    # paren XOR prefix: △(500) = +500
    assert parse_yen("△(500)") == 500


# ---------------------------------------------------------------------------
# parse_yen — full-width / NFKC
# ---------------------------------------------------------------------------


def test_parse_yen_fullwidth_digits() -> None:
    assert parse_yen("１，０００") == 1_000


def test_parse_yen_fullwidth_oku() -> None:
    assert parse_yen("１億") == 100_000_000


def test_parse_yen_fullwidth_man_with_yen() -> None:
    assert parse_yen("１．５万円") == 15_000


# ---------------------------------------------------------------------------
# parse_yen — type passthrough
# ---------------------------------------------------------------------------


def test_parse_yen_int_passthrough() -> None:
    assert parse_yen(1000) == 1000


def test_parse_yen_float_truncates() -> None:
    # Truncate, not round: 1000.7 -> 1000 (NOT 1001)
    assert parse_yen(1000.7) == 1000


def test_parse_yen_negative_float_truncates_toward_zero() -> None:
    assert parse_yen(-1000.7) == -1000


# ---------------------------------------------------------------------------
# parse_yen — error cases
# ---------------------------------------------------------------------------


def test_parse_yen_percent_raises() -> None:
    with pytest.raises(ValueError):
        parse_yen("50%")


def test_parse_yen_fullwidth_percent_raises() -> None:
    # ％ -> % via NFKC, then rejected
    with pytest.raises(ValueError):
        parse_yen("50％")


def test_parse_yen_empty_raises() -> None:
    with pytest.raises(ValueError):
        parse_yen("")


def test_parse_yen_whitespace_only_raises() -> None:
    with pytest.raises(ValueError):
        parse_yen("   ")


def test_parse_yen_none_raises() -> None:
    with pytest.raises(ValueError):
        parse_yen(None)


def test_parse_yen_garbage_raises() -> None:
    with pytest.raises(ValueError):
        parse_yen("abc")


def test_parse_yen_bool_raises() -> None:
    # bool is technically int subclass; explicit reject avoids surprises.
    with pytest.raises(ValueError):
        parse_yen(True)


# ---------------------------------------------------------------------------
# parse_yen_range
# ---------------------------------------------------------------------------


def test_range_man_tilde() -> None:
    assert parse_yen_range("100万〜500万") == (1_000_000, 5_000_000)


def test_range_man_kara() -> None:
    assert parse_yen_range("100万円から500万円") == (1_000_000, 5_000_000)


def test_range_unit_propagates_left() -> None:
    # "100-500万" — 万 attaches to BOTH numerals
    assert parse_yen_range("100-500万") == (1_000_000, 5_000_000)


def test_range_oku_propagates_left() -> None:
    assert parse_yen_range("1-3億") == (100_000_000, 300_000_000)


def test_range_single_value() -> None:
    assert parse_yen_range("500万") == (5_000_000, 5_000_000)


def test_range_swaps_when_low_gt_high() -> None:
    assert parse_yen_range("500万〜100万") == (1_000_000, 5_000_000)


def test_range_ascii_tilde() -> None:
    assert parse_yen_range("100万~500万") == (1_000_000, 5_000_000)


def test_range_with_yen_suffix_both_sides() -> None:
    assert parse_yen_range("100万円〜500万円") == (1_000_000, 5_000_000)


# ---------------------------------------------------------------------------
# format_yen
# ---------------------------------------------------------------------------


def test_format_auto_yen() -> None:
    assert format_yen(1_500) == "1,500円"


def test_format_auto_man() -> None:
    assert format_yen(15_000) == "1.5万円"


def test_format_auto_man_round_number() -> None:
    assert format_yen(5_000_000) == "500万円"


def test_format_auto_oku() -> None:
    assert format_yen(120_000_000) == "1.2億円"


def test_format_auto_oku_round_number() -> None:
    assert format_yen(100_000_000) == "1億円"


def test_format_explicit_yen_unit() -> None:
    assert format_yen(5_000_000, unit="yen") == "5,000,000円"


def test_format_explicit_man_unit_below_man_threshold() -> None:
    # Forced unit, value < 万 -> "0.2万円"
    assert format_yen(2_000, unit="man") == "0.2万円"


def test_format_negative() -> None:
    assert format_yen(-1_500) == "-1,500円"
    assert format_yen(-15_000) == "-1.5万円"


def test_format_zero() -> None:
    assert format_yen(0) == "0円"


def test_format_unknown_unit_raises() -> None:
    with pytest.raises(ValueError):
        format_yen(1000, unit="bogus")


def test_format_non_int_raises() -> None:
    with pytest.raises(ValueError):
        format_yen(1500.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Inverse property: parse(format(n)) == n for representative n
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n",
    [
        0,
        1,
        500,
        1_500,
        9_999,
        10_000,
        15_000,
        500_000,
        5_000_000,
        50_000_000,
        100_000_000,
        120_000_000,
        1_500_000_000,
        -500,
        -1_500_000,
    ],
)
def test_parse_inverse_of_format_auto(n: int) -> None:
    assert parse_yen(format_yen(n)) == n


@pytest.mark.parametrize("n", [0, 1, 500, 1_500_000, -500_000_000])
def test_parse_inverse_of_format_yen_unit(n: int) -> None:
    assert parse_yen(format_yen(n, unit="yen")) == n
