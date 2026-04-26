import datetime

import pytest

from jpintel_mcp.utils.wareki import (
    parse_wareki_date,
    parse_wareki_year,
    to_wareki,
    to_wareki_year,
)


def test_parse_long_reiwa():
    assert parse_wareki_date("令和7年4月1日") == datetime.date(2025, 4, 1)


def test_parse_short_reiwa():
    assert parse_wareki_date("R7.4.1") == datetime.date(2025, 4, 1)


def test_parse_dot_reiwa_zero_padded():
    assert parse_wareki_date("令和7.04.01") == datetime.date(2025, 4, 1)


def test_parse_gannen_year_only():
    assert parse_wareki_year("令和元年") == 2019
    assert parse_wareki_year("令和1年") == 2019
    assert parse_wareki_year("令和元年") == parse_wareki_year("令和1年")


def test_parse_gannen_full_date_uses_era_start():
    assert parse_wareki_date("令和元年5月1日") == datetime.date(2019, 5, 1)
    assert parse_wareki_date("昭和元年12月25日") == datetime.date(1926, 12, 25)


def test_era_boundary_heisei_start():
    assert parse_wareki_date("平成元年1月8日") == datetime.date(1989, 1, 8)


def test_era_boundary_showa_end():
    assert parse_wareki_date("昭和64年1月7日") == datetime.date(1989, 1, 7)
    assert to_wareki(datetime.date(1989, 1, 7)) == "昭和64年1月7日"
    assert to_wareki(datetime.date(1989, 1, 8)) == "平成1年1月8日"


def test_zero_padded_long():
    assert parse_wareki_date("令和07年04月01日") == datetime.date(2025, 4, 1)


def test_full_width_digits():
    assert parse_wareki_date("令和7年4月1日") == datetime.date(2025, 4, 1)
    assert parse_wareki_year("令和7年") == 2025


def test_short_prefixes_each_era():
    assert parse_wareki_year("R7") == 2025
    assert parse_wareki_year("H30") == 2018
    assert parse_wareki_year("S64") == 1989
    assert parse_wareki_year("T15") == 1926
    assert parse_wareki_year("M45") == 1912


def test_short_prefix_lowercase():
    assert parse_wareki_year("r7") == 2025
    assert parse_wareki_date("h30.4.1") == datetime.date(2018, 4, 1)


def test_to_wareki_long_each_era():
    assert to_wareki(datetime.date(2025, 4, 1)) == "令和7年4月1日"
    assert to_wareki(datetime.date(2018, 4, 1)) == "平成30年4月1日"
    assert to_wareki(datetime.date(1985, 6, 15)) == "昭和60年6月15日"
    assert to_wareki(datetime.date(1920, 1, 1)) == "大正9年1月1日"
    assert to_wareki(datetime.date(1900, 5, 5)) == "明治33年5月5日"


def test_to_wareki_short():
    assert to_wareki(datetime.date(2025, 4, 1), era_format="short") == "R7.4.1"
    assert to_wareki(datetime.date(1989, 1, 7), era_format="short") == "S64.1.7"


def test_to_wareki_year_round_trip():
    assert to_wareki_year(2025) == "令和7年"
    assert to_wareki_year(2018) == "平成30年"
    assert to_wareki_year(2025, era_format="short") == "R7"


def test_invalid_showa_70_raises():
    with pytest.raises(ValueError):
        parse_wareki_year("昭和70年")


def test_invalid_date_string_raises():
    with pytest.raises(ValueError):
        parse_wareki_date("not a date")


def test_invalid_era_raises():
    with pytest.raises(ValueError):
        parse_wareki_date("X7年4月1日")


def test_invalid_era_year_zero_raises():
    with pytest.raises(ValueError):
        parse_wareki_year("令和0年")


def test_date_outside_era_raises():
    with pytest.raises(ValueError):
        parse_wareki_date("令和1年4月30日")
    with pytest.raises(ValueError):
        parse_wareki_date("昭和元年12月24日")


def test_invalid_calendar_date_raises():
    with pytest.raises(ValueError):
        parse_wareki_date("令和7年2月30日")


def test_to_wareki_predates_meiji_raises():
    with pytest.raises(ValueError):
        to_wareki(datetime.date(1800, 1, 1))


def test_to_wareki_invalid_format_raises():
    with pytest.raises(ValueError):
        to_wareki(datetime.date(2025, 4, 1), era_format="medium")


def test_round_trip_long():
    for d in [
        datetime.date(2025, 4, 1),
        datetime.date(1989, 1, 8),
        datetime.date(1989, 1, 7),
        datetime.date(1926, 12, 25),
        datetime.date(1912, 7, 30),
        datetime.date(1900, 1, 1),
    ]:
        assert parse_wareki_date(to_wareki(d)) == d


def test_round_trip_short():
    for d in [
        datetime.date(2025, 4, 1),
        datetime.date(2018, 4, 1),
        datetime.date(1985, 6, 15),
    ]:
        assert parse_wareki_date(to_wareki(d, era_format="short")) == d
