#!/usr/bin/env python3
"""
Wave 12 Agent #4 - Enforcement MCP tool
2026-04-24

Public surface:
  check_enforcement(houjin_bangou=None, target_name=None, as_of_date='today')

Returns: dict with
  - queried: {houjin_bangou, target_name, as_of_date}
  - found: bool
  - currently_excluded: bool  (flag: 現時点で補助金排除中)
  - active_exclusions: [...]  # effective at as_of_date
  - recent_history: [...]     # past 5 years regardless of active
  - all_count: int
"""

import os
import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from .error_envelope import make_error

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))

_COVERAGE_SCOPE = (
    "1,185 公表済 行政処分 records (補助金不正受給 + 金商法 + 建築業法 等). "
    "Absence here is NOT a 反社チェック, NOT a 与信, NOT a 信用情報 lookup — "
    "it only rules out disclosed 行政処分 in our corpus. "
    "別途: 反社 DB / 信用情報 / 帝国データバンク / 官報 は範囲外."
)

_HOUJIN_SUFFIXES = (
    "株式会社",
    "(株)",
    "（株）",
    "有限会社",
    "(有)",
    "（有）",
    "合同会社",
    "合資会社",
    "合名会社",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "公益財団法人",
    "社会福祉法人",
    "医療法人",
    "医療法人社団",
    "医療法人財団",
    "学校法人",
    "宗教法人",
    "特定非営利活動法人",
    "NPO法人",
    "独立行政法人",
    "国立大学法人",
    "地方独立行政法人",
)


def _normalize_houjin(value: Any) -> str | None:
    """Strip any non-digit (incl. the インボイス 'T' prefix, hyphens, 全角→半角 via regex)
    and return the 13-digit canonical form. Returns None if the resulting digit
    string is not exactly 13 chars.

    Accepts:
      '1234567890123'
      'T1234567890123'    (国税庁 インボイス番号 は T + 13 桁)
      '1234-5678-9012-3'
      '１２３４５６７８９０１２３' (全角)
    """
    if value is None:
        return None
    s = unicodedata.normalize("NFKC", str(value))
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 13 else None


def _normalize_name(value: Any) -> str | None:
    """Loose-compare normalization: NFKC + 法人格 strip + whitespace fold + casefold.

    Handles (1) full-width → half-width via NFKC (`ｅａｓｅ` → `ease`),
    (2) 株式会社/合同会社/etc. prefix-or-suffix strip, (3) ascii+全角 whitespace
    removal, (4) casefold for ascii tokens. SQL side must apply the same
    normalization (do it Python-side after fetching candidate rows)."""
    if value is None:
        return None
    s = unicodedata.normalize("NFKC", str(value))
    # Strip 法人格 from start AND end (some registrations put 株式会社 at tail).
    changed = True
    while changed:
        changed = False
        for suf in _HOUJIN_SUFFIXES:
            if s.startswith(suf):
                s = s[len(suf) :]
                changed = True
                break
            if s.endswith(suf):
                s = s[: -len(suf)]
                changed = True
                break
    s = s.replace(" ", "").replace("　", "").strip()
    return s.casefold() if s else s


def _as_date(value: Any) -> str:
    if value in (None, "", "today"):
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) + timedelta(hours=9)).date().isoformat()
    return str(value)


def _err_envelope(code: str, message: str, hint: str | None = None, retry_with: list[str] | None = None) -> dict[str, Any]:
    """Canonical error envelope matching the rest of the am tool surface."""
    env = {"code": code, "message": message}
    if hint:
        env["hint"] = hint
    if retry_with:
        env["retry_with"] = retry_with
    return {
        "found": False,
        "currently_excluded": False,
        "active_exclusions": [],
        "recent_history": [],
        "all_count": 0,
        "error": env,
    }


def check_enforcement(houjin_bangou=None, target_name=None, as_of_date="today"):
    """Query enforcement history for a company.

    Either houjin_bangou or target_name must be supplied.
    """
    if not houjin_bangou and not target_name:
        return _err_envelope(
            code="missing_required_arg",
            message="either houjin_bangou or target_name is required",
            hint=(
                "Supply at least one of houjin_bangou (13 digits, optional 'T' prefix) "
                "or target_name. houjin_bangou is exact-match and fastest; target_name "
                "uses NFKC + 法人格 strip + casefold loose compare."
            ),
            retry_with=["search_enforcement_cases"],
        )

    hj = _normalize_houjin(houjin_bangou)
    name_norm = _normalize_name(target_name)
    as_of = _as_date(as_of_date)

    if not hj and not name_norm:
        return _err_envelope(
            code="invalid_enum",
            message="input normalized to empty (houjin must be 13 digits, name cannot be empty)",
            hint=(
                f"houjin_bangou={houjin_bangou!r} -> normalized to {hj!r}; "
                f"target_name={target_name!r} -> normalized to {name_norm!r}. "
                "インボイス番号 (T + 13 digits) は T を除いた 13 桁が 法人番号 と 同一."
            ),
            retry_with=["search_enforcement_cases"],
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if hj:
        # Exact houjin_bangou match (indexed, fast path).
        cur.execute(
            """
            SELECT enforcement_id, entity_id, houjin_bangou, target_name,
                   enforcement_kind, issuing_authority, issuance_date,
                   exclusion_start, exclusion_end, reason_summary,
                   related_law_ref, amount_yen, source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
             ORDER BY issuance_date DESC
            """,
            (hj,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    else:
        # Name path: table is small (~1k rows), load and filter Python-side
        # so NFKC + 法人格 strip + casefold can run against stored names.
        cur.execute(
            """
            SELECT enforcement_id, entity_id, houjin_bangou, target_name,
                   enforcement_kind, issuing_authority, issuance_date,
                   exclusion_start, exclusion_end, reason_summary,
                   related_law_ref, amount_yen, source_url
              FROM am_enforcement_detail
             ORDER BY issuance_date DESC
            """
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        rows = [
            r
            for r in all_rows
            if r.get("target_name") and _normalize_name(r["target_name"]) == name_norm
        ]
    conn.close()

    if not rows:
        # Honesty gate: found=False means "not in our 1,185 行政処分 rows",
        # NOT "company is compliance-clean". The coverage_scope disclosure
        # is preserved on the error envelope so DD agents always see it.
        if name_norm and not hj:
            err = make_error(
                code="no_matching_records",
                message="名称一致で 1 件もヒットせず。",
                hint=(
                    "スペルや法人格 (株式会社 / (株)) の書き方違いを疑って "
                    "ください。houjin_bangou (13 桁) を入れれば確実。fuzzy / "
                    "キーワード検索は search_enforcement_cases を使用。"
                ),
                retry_with=[
                    "check_enforcement_am with houjin_bangou (13桁)",
                    "search_enforcement_cases",
                ],
                extra={
                    "data_state": "name_only_exact_match",
                    "coverage_scope": _COVERAGE_SCOPE,
                },
            )
        else:
            err = make_error(
                code="no_matching_records",
                message="no enforcement records matched the queried identifier.",
                hint=(
                    "Absence here is NOT a 反社/信用 lookup. Try "
                    "search_enforcement_cases for fuzzy / 独禁法 / 景表法 slices."
                ),
                retry_with=["search_enforcement_cases"],
                extra={"coverage_scope": _COVERAGE_SCOPE},
            )
        return {
            "queried": {
                "houjin_bangou": hj,
                "target_name": target_name,
                "as_of_date": as_of,
            },
            "found": False,
            "currently_excluded": False,
            "active_exclusions": [],
            "recent_history": [],
            "all_count": 0,
            "error": err["error"],
        }

    # active_exclusions: effective at as_of_date
    active = [
        r
        for r in rows
        if r.get("exclusion_start")
        and r.get("exclusion_end")
        and r["exclusion_start"] <= as_of <= r["exclusion_end"]
    ]

    # recent_history: within past 5 years of as_of_date
    # Rough — 1825 days
    try:
        y, m, d = map(int, as_of.split("-"))
        cutoff = date(y - 5, m, d).isoformat()
    except Exception:
        cutoff = "0000-01-01"
    recent = [r for r in rows if r.get("issuance_date") and r["issuance_date"] >= cutoff]

    return {
        "queried": {
            "houjin_bangou": hj,
            "target_name": target_name,
            "as_of_date": as_of,
        },
        "found": True,
        "currently_excluded": len(active) > 0,
        "active_exclusions": active,
        "recent_history": recent,
        "all_count": len(rows),
    }


# ======== Tests ========
def _run_tests() -> None:

    # Test 1: no input -> error
    r = check_enforcement()
    assert "error" in r, f"test1 failed: {r}"

    # Test 2: unknown houjin -> canonical no_matching_records envelope
    r = check_enforcement(houjin_bangou="9999999999999")
    assert r["found"] is False, f"test2 failed: {r}"
    assert r["currently_excluded"] is False
    assert r.get("error", {}).get("code") == "no_matching_records", f"test2 envelope: {r}"

    # Test 3: known enriched houjin (from seed result: 3040001101014 = 株式会社夢現)
    r = check_enforcement(houjin_bangou="3040001101014")
    assert r["found"] is True, f"test3 failed: {r}"
    assert r["all_count"] >= 1

    # Test 4: name lookup for 株式会社 夢現 (fullwidth space tolerated)
    r = check_enforcement(target_name="株式会社 夢現")
    assert r["found"] is True, f"test4 failed: {r}"
    # Expect active since disclosed_date 2026-02-13 + 5y range includes today
    assert r["currently_excluded"] is True, f"test4 active failed: {r}"

    # Test 5: as_of_date 2032 — past all 2031 exclusion ends -> no longer excluded
    r = check_enforcement(target_name="株式会社 夢現", as_of_date="2032-06-01")
    assert r["found"] is True
    assert r["currently_excluded"] is False, f"test5 failed: {r}"

    # Test 6: malformed houjin normalized/rejected
    r = check_enforcement(houjin_bangou="123")
    # too short -> hj becomes None. With no target_name -> error.
    # But name might still be None, so error path
    assert "error" in r or r["found"] is False, f"test6 failed: {r}"

    # Test 7: top-level shape contract
    r = check_enforcement(target_name="株式会社 夢現")
    for k in (
        "queried",
        "found",
        "currently_excluded",
        "active_exclusions",
        "recent_history",
        "all_count",
    ):
        assert k in r, f"test7 missing key {k}"

    print("[enforcement_tool] ALL TESTS PASS")
    return True


if __name__ == "__main__":
    _run_tests()
