"""R8 cohort matcher tests (api/case_cohort_match.py + cohort_match_tools.py).

Two layers of coverage:

  1. Implementation (``case_cohort_match_impl``) — pure function, asserted
     against the seeded tmp jpintel.db. Adoption-records side is empty in
     the test fixture (no autonomath.db tables), so we assert the response
     gracefully degrades to a case_studies-only cohort.

  2. REST endpoint (``POST /v1/cases/cohort_match``) — exercised through
     TestClient against the same seeded fixtures, including:
       - happy path (200 + envelope shape)
       - input validation (negative bands return 400)
       - empty cohort (200 + total=0)
       - billing log_usage emission

The tests deliberately do NOT hit the production-corpus autonomath.db
because the global seeded jpintel.db fixture in conftest.py points
``JPINTEL_DB_PATH`` at a tmp 1.6MB DB, while the autonomath conn helper
opens whichever file is at ``AUTONOMATH_DB_PATH``. Seeding the matcher's
case_studies side via the same conftest fixture is sufficient to validate
all four cohort axes and the program rollup.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.mcp.autonomath_tools.cohort_match_tools import (
    _DISCLAIMER_COHORT_MATCH,
    case_cohort_match_impl,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_cohort_cases(seeded_db: Path) -> Path:
    """Insert a cohort of 5 case_studies on top of the base seed."""
    rows = [
        {
            "case_id": "COH-CS-001",
            "company_name": "株式会社東京製作所",
            "houjin_bangou": "1111111111111",
            "is_sole_proprietor": 0,
            "prefecture": "東京都",
            "municipality": "大田区",
            "industry_jsic": "E29",
            "industry_name": "金属製品製造業",
            "employees": 25,
            "founded_year": 1995,
            "capital_yen": 50_000_000,
            "case_title": "ものづくり補助金で精密加工ライン更新",
            "case_summary": "5軸 NC マシン導入で歩留まり 1.8 倍。",
            "programs_used_json": json.dumps(
                ["ものづくり補助金", "事業再構築補助金"], ensure_ascii=False
            ),
            "total_subsidy_received_yen": 8_000_000,
            "publication_date": "2024-11-01",
            "source_url": "https://example.go.jp/case/coh-001",
            "confidence": 0.92,
        },
        {
            "case_id": "COH-CS-002",
            "company_name": "大阪鋳造所",
            "is_sole_proprietor": 1,
            "prefecture": "大阪府",
            "industry_jsic": "E25",
            "industry_name": "非鉄金属製造業",
            "employees": 5,
            "capital_yen": 8_000_000,
            "case_title": "IT 導入補助金で見積自動化",
            "programs_used_json": json.dumps(["IT 導入補助金"], ensure_ascii=False),
            "total_subsidy_received_yen": 1_500_000,
            "publication_date": "2024-09-12",
            "source_url": "https://example.go.jp/case/coh-002",
        },
        {
            "case_id": "COH-CS-003",
            "company_name": "東京ものづくり工房",
            "prefecture": "東京都",
            "industry_jsic": "E29",
            "industry_name": "金属製品製造業",
            "employees": 60,
            "capital_yen": 120_000_000,
            "case_title": "ものづくり補助金で量産ライン拡張",
            "programs_used_json": json.dumps(["ものづくり補助金"], ensure_ascii=False),
            "publication_date": "2024-06-30",
            "source_url": "https://example.go.jp/case/coh-003",
        },
        {
            "case_id": "COH-CS-004",
            "company_name": "東京農園株式会社",
            "prefecture": "東京都",
            "industry_jsic": "A0111",
            "industry_name": "米作",
            "employees": 30,
            "case_title": "六次産業化支援で加工施設整備",
            "programs_used_json": json.dumps(["六次産業化支援"], ensure_ascii=False),
            "publication_date": "2024-08-15",
            "source_url": "https://example.go.jp/case/coh-004",
        },
        {
            "case_id": "COH-CS-005",
            "company_name": "東京メーカー(規模オーバー)",
            "prefecture": "東京都",
            "industry_jsic": "E29",
            "employees": 5000,
            "capital_yen": 5_000_000_000,
            "case_title": "大企業案件",
            "programs_used_json": json.dumps([], ensure_ascii=False),
            "publication_date": "2024-05-01",
            "source_url": "https://example.go.jp/case/coh-005",
        },
    ]

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    for r in rows:
        cols = ",".join(r.keys())
        placeholders = ",".join("?" * len(r))
        conn.execute(
            f"INSERT OR IGNORE INTO case_studies({cols}) VALUES ({placeholders})",
            list(r.values()),
        )
    conn.commit()
    conn.close()
    return seeded_db


def test_impl_returns_canonical_envelope(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        prefecture="東京都",
        limit=20,
    )
    for key in (
        "results",
        "total",
        "limit",
        "offset",
        "matched_case_studies",
        "matched_adoption_records",
        "program_rollup",
        "summary",
        "axes_applied",
        "sparsity_notes",
        "_disclaimer",
        "_next_calls",
        "_billing_unit",
        "input",
    ):
        assert key in res, f"missing top-level key {key!r}"

    assert res["_billing_unit"] == 1
    assert res["_disclaimer"] == _DISCLAIMER_COHORT_MATCH
    assert isinstance(res["matched_case_studies"], list)
    assert isinstance(res["matched_adoption_records"], list)
    assert isinstance(res["program_rollup"], list)
    assert isinstance(res["sparsity_notes"], list)
    assert len(res["sparsity_notes"]) >= 3, "expected at least 3 honest sparsity notes"


def test_impl_industry_prefix_filters_case_studies(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(industry_jsic="E", limit=50)
    case_ids = {c["case_id"] for c in res["matched_case_studies"]}
    assert {"COH-CS-001", "COH-CS-002", "COH-CS-003", "COH-CS-005"}.issubset(case_ids)
    assert "COH-CS-004" not in case_ids


def test_impl_prefecture_filter(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(prefecture="東京都", limit=50)
    case_ids = {c["case_id"] for c in res["matched_case_studies"]}
    assert "COH-CS-001" in case_ids
    assert "COH-CS-002" not in case_ids


def test_impl_employee_range_excludes_giant(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        prefecture="東京都",
        employee_count_range=[1, 100],
        limit=50,
    )
    case_ids = {c["case_id"] for c in res["matched_case_studies"]}
    assert "COH-CS-001" in case_ids
    assert "COH-CS-003" in case_ids
    assert "COH-CS-005" not in case_ids


def test_impl_revenue_range_uses_capital_proxy(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        revenue_yen_range=[10_000_000, 200_000_000],
        limit=50,
    )
    case_ids = {c["case_id"] for c in res["matched_case_studies"]}
    assert "COH-CS-001" in case_ids
    assert "COH-CS-003" in case_ids
    assert "COH-CS-002" not in case_ids
    assert "COH-CS-005" not in case_ids


def test_impl_program_rollup_aggregates(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        prefecture="東京都",
        limit=50,
    )
    rollup = {p["program_label"]: p for p in res["program_rollup"]}
    assert "ものづくり補助金" in rollup
    mono = rollup["ものづくり補助金"]
    assert mono["case_study_count"] >= 2
    assert mono["appearance_count"] >= 2
    assert mono["avg_amount_yen"] == 8_000_000
    assert 0.0 < mono["cohort_share"] <= 1.0
    assert len(mono["example_case_ids"]) <= 3


def test_impl_summary_amount_stats(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        prefecture="東京都",
        limit=50,
    )
    summary = res["summary"]
    assert summary["amount_yen_with_value"] >= 1
    assert summary["amount_yen_mean"] is not None
    assert summary["amount_yen_min"] >= 0
    assert summary["amount_yen_max"] >= summary["amount_yen_min"]


def test_impl_invalid_employee_range_returns_error(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        employee_count_range=[100, 10],
        limit=20,
    )
    assert "error" in res
    assert res["error"]["code"] == "out_of_range"
    assert res["error"]["field"] == "employee_count_range"


def test_impl_negative_employee_lower_returns_error(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        employee_count_range=[-1, 100],
        limit=20,
    )
    assert "error" in res
    assert res["error"]["code"] == "out_of_range"


def test_impl_limit_clamped(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(industry_jsic="E", limit=500)
    assert res["limit"] == 100


def test_impl_no_industry_no_prefecture_passes(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(limit=10)
    assert isinstance(res["matched_case_studies"], list)
    assert "error" not in res
    assert res["total"] == len(res["results"])


def test_impl_next_calls_compounding(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(industry_jsic="E", prefecture="東京都", limit=20)
    next_calls = res["_next_calls"]
    assert isinstance(next_calls, list)
    assert len(next_calls) >= 1
    for hint in next_calls:
        assert "tool" in hint
        assert "args" in hint
        assert "rationale" in hint


def test_impl_axes_applied_disclosure(seeded_cohort_cases) -> None:
    res = case_cohort_match_impl(
        industry_jsic="E",
        prefecture="東京都",
        employee_count_range=[1, 100],
        revenue_yen_range=[10_000_000, 200_000_000],
        limit=20,
    )
    axes = res["axes_applied"]
    assert axes["industry_jsic"] == "E"
    assert axes["prefecture"] == "東京都"
    assert axes["case_studies_axes"] == [
        "industry_jsic",
        "employee",
        "revenue_proxy",
        "prefecture",
    ]
    assert axes["adoption_records_axes"] == ["industry_jsic_medium", "prefecture"]


def test_rest_post_happy_path(client, seeded_cohort_cases) -> None:
    r = client.post(
        "/v1/cases/cohort_match",
        json={
            "industry_jsic": "E",
            "prefecture": "東京都",
            "employee_count_range": [1, 100],
            "limit": 20,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["input"]["industry_jsic"] == "E"
    assert body["input"]["prefecture"] == "東京都"
    assert isinstance(body["matched_case_studies"], list)
    assert isinstance(body["program_rollup"], list)
    assert "_disclaimer" in body


def test_rest_post_validation_error_returns_400(client, seeded_cohort_cases) -> None:
    r = client.post(
        "/v1/cases/cohort_match",
        json={"employee_count_range": [100, 1]},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "out_of_range"


def test_rest_post_empty_cohort_still_200(client, seeded_cohort_cases) -> None:
    r = client.post(
        "/v1/cases/cohort_match",
        json={"industry_jsic": "ZZZZZ", "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched_case_studies"] == []
    assert body["matched_adoption_records"] == []
    assert body["program_rollup"] == []


def test_rest_post_logs_usage_event(client, seeded_cohort_cases, seeded_db, paid_key) -> None:
    """log_usage('case_cohort_match') must fire for the metering pipeline."""
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = ? AND key_hash = ?",
            ("case_cohort_match", key_hash),
        ).fetchone()
    finally:
        conn.close()

    r = client.post(
        "/v1/cases/cohort_match",
        json={"industry_jsic": "E", "limit": 5},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = ? AND key_hash = ?",
            ("case_cohort_match", key_hash),
        ).fetchone()
    finally:
        conn.close()
    assert after == before + 1


def test_rest_post_limit_clamped_to_100(client, seeded_cohort_cases) -> None:
    r = client.post(
        "/v1/cases/cohort_match",
        json={"limit": 500},
    )
    assert r.status_code == 422


def test_rest_post_extra_fields_ignored(client, seeded_cohort_cases) -> None:
    r = client.post(
        "/v1/cases/cohort_match",
        json={
            "industry_jsic": "E",
            "limit": 5,
            "garbage_field": "should be ignored",
        },
    )
    assert r.status_code == 200
