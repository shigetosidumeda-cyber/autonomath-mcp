from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class _Era:
    kanji: str
    short: str
    start: datetime.date
    end: datetime.date | None


_ERAS: tuple[_Era, ...] = (
    _Era("令和", "R", datetime.date(2019, 5, 1), None),
    _Era("平成", "H", datetime.date(1989, 1, 8), datetime.date(2019, 4, 30)),
    _Era("昭和", "S", datetime.date(1926, 12, 25), datetime.date(1989, 1, 7)),
    _Era("大正", "T", datetime.date(1912, 7, 30), datetime.date(1926, 12, 24)),
    _Era("明治", "M", datetime.date(1868, 10, 23), datetime.date(1912, 7, 29)),
)

_BY_KANJI = {e.kanji: e for e in _ERAS}
_BY_SHORT = {e.short: e for e in _ERAS}
_BY_SHORT_LOWER = {e.short.lower(): e for e in _ERAS}


def _normalize(s: str) -> str:
    if not isinstance(s, str):
        raise ValueError(f"expected str, got {type(s).__name__}")
    s = unicodedata.normalize("NFKC", s).strip()
    s = s.replace("元", "1")
    return s


def _resolve_era(token: str) -> _Era:
    if token in _BY_KANJI:
        return _BY_KANJI[token]
    if token in _BY_SHORT:
        return _BY_SHORT[token]
    if token.lower() in _BY_SHORT_LOWER:
        return _BY_SHORT_LOWER[token.lower()]
    raise ValueError(f"unknown era: {token!r}")


def _validate_era_year(era: _Era, era_year: int) -> int:
    if era_year < 1:
        raise ValueError(f"era year must be >= 1, got {era_year}")
    gregorian = era.start.year + era_year - 1
    last_year = era.end.year if era.end else datetime.date.today().year + 50
    if gregorian > last_year:
        raise ValueError(f"{era.kanji}{era_year}年 is out of range ({era.kanji} ended {era.end})")
    return gregorian


_DATE_LONG = re.compile(
    r"^(?P<era>令和|平成|昭和|大正|明治|[RHSTMrhstm])"
    r"(?P<y>\d+)年"
    r"(?P<m>\d+)月"
    r"(?P<d>\d+)日$"
)
_DATE_DOT = re.compile(
    r"^(?P<era>令和|平成|昭和|大正|明治|[RHSTMrhstm])"
    r"(?P<y>\d+)[.\-/]"
    r"(?P<m>\d+)[.\-/]"
    r"(?P<d>\d+)$"
)
_YEAR_ONLY = re.compile(r"^(?P<era>令和|平成|昭和|大正|明治|[RHSTMrhstm])" r"(?P<y>\d+)年?$")


def parse_wareki_date(s: str) -> datetime.date:
    norm = _normalize(s)
    m = _DATE_LONG.match(norm) or _DATE_DOT.match(norm)
    if not m:
        raise ValueError(f"unparseable wareki date: {s!r}")
    era = _resolve_era(m.group("era"))
    era_year = int(m.group("y"))
    month = int(m.group("m"))
    day = int(m.group("d"))
    gregorian_year = _validate_era_year(era, era_year)
    try:
        d = datetime.date(gregorian_year, month, day)
    except ValueError as exc:
        raise ValueError(f"invalid date {s!r}: {exc}") from exc
    if d < era.start or (era.end is not None and d > era.end):
        raise ValueError(
            f"{s!r} resolves to {d} which is outside {era.kanji} ({era.start}..{era.end})"
        )
    return d


def parse_wareki_year(s: str) -> int:
    norm = _normalize(s)
    m = _YEAR_ONLY.match(norm)
    if not m:
        raise ValueError(f"unparseable wareki year: {s!r}")
    era = _resolve_era(m.group("era"))
    era_year = int(m.group("y"))
    return _validate_era_year(era, era_year)


def _find_era(d: datetime.date) -> _Era:
    for era in _ERAS:
        if d >= era.start and (era.end is None or d <= era.end):
            return era
    raise ValueError(f"date {d} predates 明治 (1868-10-23)")


def to_wareki(d: datetime.date, *, era_format: str = "long") -> str:
    if not isinstance(d, datetime.date):
        raise ValueError(f"expected datetime.date, got {type(d).__name__}")
    era = _find_era(d)
    era_year = d.year - era.start.year + 1
    if era_format == "long":
        return f"{era.kanji}{era_year}年{d.month}月{d.day}日"
    if era_format == "short":
        return f"{era.short}{era_year}.{d.month}.{d.day}"
    raise ValueError(f"era_format must be 'long' or 'short', got {era_format!r}")


def to_wareki_year(year: int, *, era_format: str = "long") -> str:
    if not isinstance(year, int) or isinstance(year, bool):
        raise ValueError(f"expected int, got {type(year).__name__}")
    probe = datetime.date(year, 12, 31)
    era = _find_era(probe)
    if era.start.year > year:
        raise ValueError(f"year {year} predates known eras")
    era_year = year - era.start.year + 1
    if era_format == "long":
        return f"{era.kanji}{era_year}年"
    if era_format == "short":
        return f"{era.short}{era_year}"
    raise ValueError(f"era_format must be 'long' or 'short', got {era_format!r}")
