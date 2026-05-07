"""funding_stage matcher tests (api/funding_stage.py + funding_stage_tools.py).

Two layers:
  1. Pure-Python impl (``match_programs_by_funding_stage_impl``) over the
     conftest-seeded jpintel.db — sanity checks the catalog, the matcher
     fence (keywords_any / keywords_avoid), the age/year conversion, and
     input validation.
  2. REST endpoints — POST /v1/programs/by_funding_stage happy / invalid
     / 422; GET /v1/funding_stages/catalog 200 + envelope shape.

The conftest seeded fixture gives us a small set of `programs` rows; we
extend it with stage-specific names so the matcher fence has something to
hit (otherwise growth + ipo would always return []).
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.funding_stage import (
    _STAGE_BY_ID,
    _STAGES,
    _age_years_from_year,
    _likelihood_score,
)
from jpintel_mcp.mcp.autonomath_tools.funding_stage_tools import (
    match_programs_by_funding_stage_impl,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_stage_programs(seeded_db: Path) -> Path:
    """Insert a small set of stage-flavoured programs on top of the base seed."""
    rows = [
        # seed cohort
        {
            "unified_id": "STG-SEED-001",
            "primary_name": "新創業融資 (テスト)",
            "tier": "S",
            "program_kind": "loan",
            "amount_max_man_yen": 7000.0,
            "prefecture": None,
        },
        {
            "unified_id": "STG-SEED-002",
            "primary_name": "創業支援補助金 (東京都・テスト)",
            "tier": "A",
            "program_kind": "subsidy",
            "amount_max_man_yen": 200.0,
            "prefecture": "東京都",
        },
        # early cohort
        {
            "unified_id": "STG-EARLY-001",
            "primary_name": "ものづくり補助金 (テスト)",
            "tier": "S",
            "program_kind": "subsidy",
            "amount_max_man_yen": 5000.0,
            "prefecture": None,
        },
        {
            "unified_id": "STG-EARLY-002",
            "primary_name": "IT導入補助金 (テスト)",
            "tier": "S",
            "program_kind": "subsidy",
            "amount_max_man_yen": 450.0,
            "prefecture": None,
        },
        # growth cohort
        {
            "unified_id": "STG-GROW-001",
            "primary_name": "中小企業成長加速化補助金 (テスト)",
            "tier": "A",
            "program_kind": "subsidy",
            "amount_max_man_yen": 50000.0,
            "prefecture": None,
        },
        {
            "unified_id": "STG-GROW-002",
            "primary_name": "JETRO 海外展開支援 (テスト)",
            "tier": "B",
            "program_kind": "subsidy",
            "amount_max_man_yen": 1000.0,
            "prefecture": None,
        },
        # IPO cohort
        {
            "unified_id": "STG-IPO-001",
            "primary_name": "J-Startup グローバルアクセラレーション (テスト)",
            "tier": "A",
            "program_kind": "incentive",
            "amount_max_man_yen": 30000.0,
            "prefecture": None,
        },
        # succession cohort
        {
            "unified_id": "STG-SUCC-001",
            "primary_name": "事業承継・M&A補助金 (テスト)",
            "tier": "S",
            "program_kind": "subsidy",
            "amount_max_man_yen": 1500.0,
            "prefecture": None,
        },
        {
            "unified_id": "STG-SUCC-002",
            "primary_name": "事業承継税制 (特例措置・テスト)",
            "tier": "S",
            "program_kind": "tax_deduction",
            "amount_max_man_yen": 0.0,
            "prefecture": None,
        },
        # noise — should be filtered out by keywords_avoid
        {
            "unified_id": "STG-NOISE-001",
            "primary_name": "創業 と 事業承継 を併記する false-positive (テスト)",
            "tier": "B",
            "program_kind": "subsidy",
            "amount_max_man_yen": 100.0,
            "prefecture": None,
        },
    ]
    conn = sqlite3.connect(seeded_db)
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO programs(
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json,
                a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["unified_id"],
                r["primary_name"],
                json.dumps([], ensure_ascii=False),
                None,
                None,
                r.get("prefecture"),
                None,
                r.get("program_kind"),
                None,
                r.get("amount_max_man_yen"),
                None,
                None,
                None,
                r.get("tier"),
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                None,
                None,
                None,
                None,
                "2026-05-07T00:00:00Z",
            ),
        )
    conn.commit()
    conn.close()
    return seeded_db


# ---------------------------------------------------------------------------
# Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_stages_closed_enum_5_entries() -> None:
    assert {s["id"] for s in _STAGES} == {
        "seed",
        "early",
        "growth",
        "ipo",
        "succession",
    }
    # Every stage must declare keywords_any (matcher fence).
    for s in _STAGES:
        assert s["keywords_any"], f"{s['id']} missing keywords_any"


def test_age_years_from_year_handles_none_and_future() -> None:
    assert _age_years_from_year(None) is None
    assert _age_years_from_year(2026) == 0  # current-year incorporation
    assert _age_years_from_year(3000) == 0  # future → clamped to 0
    assert _age_years_from_year(2020) >= 5


def test_likelihood_score_baseline_and_keyword_density() -> None:
    keywords = ["創業", "起業", "スタートアップ"]
    # No keyword match → minimum floor 0.1
    assert (
        _likelihood_score(primary_name="ものづくり補助金", tier="S", keywords_any=keywords) == 0.1
    )
    # 1 keyword + tier S
    s_one = _likelihood_score(primary_name="創業支援補助金", tier="S", keywords_any=keywords)
    assert 0.55 <= s_one <= 1.0
    # Multi-keyword density bumps base
    s_multi = _likelihood_score(
        primary_name="創業 起業 スタートアップ 支援", tier="S", keywords_any=keywords
    )
    assert s_multi >= s_one


def test_likelihood_score_tier_decay() -> None:
    keywords = ["事業承継"]
    s_s = _likelihood_score(primary_name="事業承継 補助金", tier="S", keywords_any=keywords)
    s_c = _likelihood_score(primary_name="事業承継 補助金", tier="C", keywords_any=keywords)
    assert s_s > s_c


# ---------------------------------------------------------------------------
# Impl tests against seeded jpintel.db
# ---------------------------------------------------------------------------


def test_impl_invalid_stage_returns_error(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="series-a")
    assert "error" in res
    assert res["error"]["field"] == "stage"


def test_impl_seed_stage_returns_seed_cohort(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="seed", limit=20)
    assert "error" not in res
    names = [p["primary_name"] for p in res["matched_programs"]]
    assert any("創業" in n or "起業" in n or "スタートアップ" in n for n in names)
    # avoid-keyword fence: 事業承継 は seed では除外される
    assert all("事業承継" not in n for n in names)


def test_impl_growth_stage_returns_growth_cohort(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="growth", limit=20)
    assert "error" not in res
    names = [p["primary_name"] for p in res["matched_programs"]]
    assert any("成長" in n or "海外展開" in n or "設備投資" in n for n in names)
    # avoid-keyword fence: 創業 / 事業承継 は growth では除外
    assert all("事業承継" not in n for n in names)


def test_impl_succession_stage_returns_succession_cohort(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="succession", limit=20)
    assert "error" not in res
    names = [p["primary_name"] for p in res["matched_programs"]]
    assert any("事業承継" in n or "M&A" in n for n in names)


def test_impl_envelope_carries_disclaimer(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="early", limit=10)
    assert "_disclaimer" in res
    assert (
        "stage" in res["_disclaimer"]
        or "資金調達" in res["_disclaimer"]
        or "stage" in res["_disclaimer"].lower()
    )


def test_impl_next_calls_compounding(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="growth", limit=5)
    assert isinstance(res["_next_calls"], list)
    assert any(h["tool"] == "check_funding_stack_am" for h in res["_next_calls"])


def test_impl_limit_clamped(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="early", limit=500)
    assert res["limit"] == 100


def test_impl_negative_revenue_returns_error(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="growth", annual_revenue_yen=-1, limit=10)
    assert "error" in res
    assert res["error"]["field"] == "annual_revenue_yen"


def test_impl_negative_employees_returns_error(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="growth", employee_count=-5, limit=10)
    assert "error" in res
    assert res["error"]["field"] == "employee_count"


def test_impl_invalid_year_returns_error(seeded_stage_programs) -> None:
    res = match_programs_by_funding_stage_impl(stage="growth", incorporation_year=1700, limit=10)
    assert "error" in res
    assert res["error"]["field"] == "incorporation_year"


# ---------------------------------------------------------------------------
# REST tests
# ---------------------------------------------------------------------------


def test_rest_catalog_returns_5_stages(client, seeded_stage_programs) -> None:
    r = client.get("/v1/funding_stages/catalog")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    ids = [s["id"] for s in body["stages"]]
    assert ids == ["seed", "early", "growth", "ipo", "succession"]
    for s in body["stages"]:
        assert "keywords_any" in s
        assert "representative_programs" in s
    assert "_disclaimer" in body


def test_rest_match_post_happy_path(client, seeded_stage_programs) -> None:
    r = client.post(
        "/v1/programs/by_funding_stage",
        json={
            "stage": "growth",
            "annual_revenue_yen": 500_000_000,
            "employee_count": 50,
            "incorporation_year": 2018,
            "prefecture": None,
            "limit": 10,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["input"]["stage"] == "growth"
    assert body["input"]["age_years"] is not None
    assert isinstance(body["matched_programs"], list)
    assert "_disclaimer" in body
    assert body["stage_definition"]["id"] == "growth"


def test_rest_match_post_invalid_stage_returns_422(client, seeded_stage_programs) -> None:
    r = client.post(
        "/v1/programs/by_funding_stage",
        json={"stage": "series-a", "limit": 10},
    )
    assert r.status_code == 422, r.text


def test_rest_match_post_invalid_revenue_returns_422(client, seeded_stage_programs) -> None:
    r = client.post(
        "/v1/programs/by_funding_stage",
        json={"stage": "growth", "annual_revenue_yen": -100, "limit": 10},
    )
    # pydantic Field(ge=0) rejects with 422.
    assert r.status_code == 422, r.text


def test_rest_match_post_seed_returns_seed_cohort(client, seeded_stage_programs) -> None:
    r = client.post(
        "/v1/programs/by_funding_stage",
        json={"stage": "seed", "limit": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    names = [p["primary_name"] for p in body["matched_programs"]]
    assert any("創業" in n or "起業" in n or "スタートアップ" in n for n in names)


def test_stage_definitions_no_overlap_seed_succession() -> None:
    """seed と succession は keyword fence が反対方向 — 重なるべきでない。"""
    seed = _STAGE_BY_ID["seed"]
    succ = _STAGE_BY_ID["succession"]
    # succession の keywords_any は seed の keywords_avoid に含まれるべき。
    assert "事業承継" in succ["keywords_any"]
    assert "事業承継" in seed["keywords_avoid"]
    # 逆方向。
    assert "創業" in seed["keywords_any"]
    assert "創業" in succ["keywords_avoid"]
