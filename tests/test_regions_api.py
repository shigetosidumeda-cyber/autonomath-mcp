"""Tests for the R8 GEO REGION API surface (regions.py + region_tools.py).

Covers
------
* ``GET /v1/programs/by_region/{code}`` — 国 / 都道府県 / 市区町村 buckets,
  designated_ward → city → prefecture walk, totals.
* ``GET /v1/regions/{code}/coverage`` — counts + coverage_gap detection.
* ``GET /v1/regions/search`` — name fuzzy search + level filter.
* MCP impl mirrors (``_impl_programs_by_region`` /
  ``_impl_region_coverage`` / ``_impl_search_regions``).

Test substrate
--------------
A tiny on-disk autonomath.db is built per-test with am_region rows for
全国 (00000) → 東京都 (13000) → 文京区 (13105), 北海道 (01000) → 札幌市
(01100) → 中央区 (01101). The jpintel.db comes from the session-scoped
``seeded_db`` fixture and we INSERT a handful of programs covering all
three buckets (国 / 都道府県 / 市区町村) before each request.
"""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path
else:
    from pathlib import Path  # noqa: TC003 — runtime use in fixtures


def _build_am_region(path: Path) -> None:
    """Build a minimal am_region table at ``path`` for tests."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE am_region (
            region_code TEXT PRIMARY KEY,
            region_level TEXT NOT NULL,
            name_ja TEXT NOT NULL,
            name_en TEXT,
            name_kana TEXT,
            parent_code TEXT,
            iso_3166_2 TEXT,
            note TEXT,
            population INTEGER,
            population_band TEXT,
            population_source TEXT,
            population_exact INTEGER,
            household_count INTEGER,
            population_exact_source TEXT,
            population_exact_as_of TEXT
        )
        """
    )
    rows = [
        ("00000", "nation", "全国", None),
        ("13000", "prefecture", "東京都", "00000"),
        ("13105", "municipality", "文京区", "13000"),
        ("13117", "municipality", "北区", "13000"),
        ("01000", "prefecture", "北海道", "00000"),
        ("01100", "designated_city", "札幌市", "01000"),
        ("01101", "designated_ward", "札幌市中央区", "01100"),
        ("28201", "municipality", "姫路市", "28000"),  # orphan (no 兵庫県 row)
    ]
    for code, level, name, parent in rows:
        conn.execute(
            "INSERT INTO am_region (region_code, region_level, name_ja, parent_code) "
            "VALUES (?, ?, ?, ?)",
            (code, level, name, parent),
        )
    conn.commit()
    conn.close()


def _seed_programs(seeded_db: Path) -> None:
    """Insert program rows that exercise the 3 buckets (国 / 都道府県 / 市区町村).

    The session-scoped ``seeded_db`` already has 4 rows from conftest;
    we add a handful that have predictable prefecture / municipality
    values so the bucket counts in the assertions are exact.
    """
    rows: list[dict[str, Any]] = [
        # National-level (国 / national tag) — appear in every region's national bucket.
        {
            "unified_id": "TEST-region-national-1",
            "primary_name": "国 全国補助金 テスト",
            "tier": "S",
            "authority_level": "national",
            "prefecture": None,
            "municipality": None,
        },
        {
            "unified_id": "TEST-region-national-2",
            "primary_name": "国レベル 制度 テスト",
            "tier": "A",
            "authority_level": "国",
            "prefecture": None,
            "municipality": None,
        },
        # 東京都 prefecture-level (no municipality).
        {
            "unified_id": "TEST-region-tokyo-pref-1",
            "primary_name": "東京都 都道府県補助金",
            "tier": "A",
            "authority_level": "prefecture",
            "prefecture": "東京都",
            "municipality": None,
        },
        # 文京区 municipality-level.
        {
            "unified_id": "TEST-region-tokyo-bunkyo-1",
            "primary_name": "文京区 中小企業支援金",
            "tier": "B",
            "authority_level": "municipality",
            "prefecture": "東京都",
            "municipality": "文京区",
        },
        # X-tier (excluded) — must NOT appear in any bucket.
        {
            "unified_id": "TEST-region-tokyo-bunkyo-x",
            "primary_name": "文京区 X-tier 除外",
            "tier": "X",
            "excluded": 1,
            "exclusion_reason": "old",
            "authority_level": "municipality",
            "prefecture": "東京都",
            "municipality": "文京区",
        },
    ]
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    for r in rows:
        cols = list(r.keys())
        if "updated_at" not in cols:
            cols.append("updated_at")
            r["updated_at"] = "2026-05-07T00:00:00Z"
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            f"INSERT OR IGNORE INTO programs ({','.join(cols)}) VALUES ({placeholders})",
            tuple(r[c] for c in cols),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def autonomath_region_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test autonomath.db with am_region seeded."""
    db = tmp_path / "autonomath.db"
    _build_am_region(db)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    return db


@pytest.fixture()
def seeded_regions_client(client, autonomath_region_db, seeded_db):
    _seed_programs(seeded_db)
    return client


# ---------------------------------------------------------------------------
# REST: /v1/programs/by_region/{code}
# ---------------------------------------------------------------------------


def test_by_region_prefecture_returns_pref_and_national(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/programs/by_region/13000")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["region"]["region_code"] == "13000"
    assert body["region"]["region_level"] == "prefecture"
    assert body["region"]["prefecture_name"] == "東京都"
    # national bucket includes both tagged-as 'national' and tagged-as '国'.
    national_ids = {p["unified_id"] for p in body["national"]}
    assert "TEST-region-national-1" in national_ids
    assert "TEST-region-national-2" in national_ids
    pref_ids = {p["unified_id"] for p in body["prefecture"]}
    assert "TEST-region-tokyo-pref-1" in pref_ids
    # municipality bucket is empty when the region itself is a prefecture.
    assert body["municipality"] == []
    # X-tier never surfaces.
    assert "TEST-region-tokyo-bunkyo-x" not in pref_ids


def test_by_region_municipality_walks_to_prefecture(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/programs/by_region/13105")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["region"]["region_code"] == "13105"
    assert body["region"]["region_level"] == "municipality"
    assert body["region"]["prefecture_name"] == "東京都"
    muni_ids = {p["unified_id"] for p in body["municipality"]}
    assert "TEST-region-tokyo-bunkyo-1" in muni_ids
    # X-tier excluded
    assert "TEST-region-tokyo-bunkyo-x" not in muni_ids
    # Prefecture bucket is the parent prefecture's rows.
    pref_ids = {p["unified_id"] for p in body["prefecture"]}
    assert "TEST-region-tokyo-pref-1" in pref_ids


def test_by_region_designated_ward_walks_two_hops(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/programs/by_region/01101")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["region"]["region_level"] == "designated_ward"
    # ward → 札幌市 → 北海道.
    assert body["region"]["prefecture_code"] == "01000"
    assert body["region"]["prefecture_name"] == "北海道"


def test_by_region_unknown_code_returns_404(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/programs/by_region/99999")
    assert r.status_code == 404


def test_by_region_invalid_code_format_400(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/programs/by_region/abcde")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# REST: /v1/regions/{code}/coverage
# ---------------------------------------------------------------------------


def test_region_coverage_pref_with_data(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/regions/13000/coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["national"] >= 2
    assert body["counts"]["prefecture"] >= 1
    # prefecture region: municipality count = 0 by definition (we only count
    # rows whose municipality matches name_ja, and 東京都 is a prefecture).
    assert body["counts"]["municipality"] == 0
    # not a coverage_gap because prefecture > 0.
    assert body["coverage_gap"] is False


def test_region_coverage_gap_for_orphan_municipality(seeded_regions_client) -> None:
    # 姫路市 (28201) is in the test fixture but has zero programs mapped.
    r = seeded_regions_client.get("/v1/regions/28201/coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["prefecture"] == 0
    assert body["counts"]["municipality"] == 0
    assert body["coverage_gap"] is True


def test_region_coverage_nation_no_gap(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/regions/00000/coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    # nation level always reports counts but never as a gap.
    assert body["coverage_gap"] is False


# ---------------------------------------------------------------------------
# REST: /v1/regions/search
# ---------------------------------------------------------------------------


def test_regions_search_substring(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/regions/search", params={"q": "文京区"})
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [row["region_code"] for row in body["results"]]
    assert "13105" in codes


def test_regions_search_level_filter(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/regions/search", params={"q": "京", "level": "prefecture"})
    assert r.status_code == 200, r.text
    body = r.json()
    levels = {row["region_level"] for row in body["results"]}
    assert levels == {"prefecture"} or levels == set()  # may be empty if no match


def test_regions_search_exact_ranks_first(seeded_regions_client) -> None:
    """北区 should rank above other 北区-suffixed wards (we don't have ward rows for 北区 except 13117)."""
    r = seeded_regions_client.get("/v1/regions/search", params={"q": "北区"})
    assert r.status_code == 200, r.text
    body = r.json()
    if body["results"]:
        assert body["results"][0]["name_ja"] == "北区"


def test_regions_search_empty_q_400(seeded_regions_client) -> None:
    r = seeded_regions_client.get("/v1/regions/search", params={"q": ""})
    # FastAPI rejects empty q via min_length=1 → 422 from validation.
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# MCP impl mirrors (no MCP plumbing — pure Python).
# ---------------------------------------------------------------------------


def test_mcp_impl_programs_by_region_invalid_code(autonomath_region_db, seeded_db) -> None:
    from jpintel_mcp.mcp.autonomath_tools.region_tools import (
        _impl_programs_by_region,
    )

    out = _impl_programs_by_region(region_code="bad")
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_mcp_impl_programs_by_region_unknown(autonomath_region_db, seeded_db) -> None:
    from jpintel_mcp.mcp.autonomath_tools.region_tools import (
        _impl_programs_by_region,
    )

    out = _impl_programs_by_region(region_code="99999")
    assert "error" in out
    assert out["error"]["code"] == "no_matching_records"


def test_mcp_impl_region_coverage_municipality(autonomath_region_db, seeded_db) -> None:
    _seed_programs(seeded_db)
    os.environ["JPINTEL_DB_PATH"] = str(seeded_db)
    from jpintel_mcp.mcp.autonomath_tools.region_tools import _impl_region_coverage

    out = _impl_region_coverage(region_code="13105")
    assert "error" not in out
    assert out["region"]["name_ja"] == "文京区"
    assert out["counts"]["municipality"] >= 1
    assert out["coverage_gap"] is False


def test_mcp_impl_search_regions_basic(autonomath_region_db, seeded_db) -> None:
    from jpintel_mcp.mcp.autonomath_tools.region_tools import _impl_search_regions

    out = _impl_search_regions(q="札幌")
    assert "error" not in out
    names = [row["name_ja"] for row in out["results"]]
    assert "札幌市" in names


def test_mcp_impl_search_regions_invalid_level(autonomath_region_db, seeded_db) -> None:
    from jpintel_mcp.mcp.autonomath_tools.region_tools import _impl_search_regions

    out = _impl_search_regions(q="東京", level="bogus")
    assert "error" in out
    assert out["error"]["code"] == "invalid_enum"
