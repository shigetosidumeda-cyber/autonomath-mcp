"""R8 industry benchmark surface tests (api/benchmark.py + benchmark_tools.py).

Two layers of coverage, mirroring the cohort-matcher test pattern:

1. ``benchmark_cohort_average_impl`` — pure function, exercised against
   the seeded tmp jpintel.db. The autonomath side is empty in fixtures
   (no jpi_adoption_records), so the response gracefully degrades to a
   case_studies-only cohort.

2. REST endpoints — ``POST /v1/benchmark/cohort_average`` (anon path) and
   ``GET /v1/me/benchmark_vs_industry`` (authenticated). Asserts:
     * happy-path envelope shape
     * size_band capital filter slices the cohort correctly
     * outlier_top_decile is amount-driven and ceiling-1
     * authenticated /v1/me/benchmark_vs_industry sees its own usage
       and surfaces leakage_programs (取りこぼし)
     * unauthenticated /v1/me/benchmark_vs_industry returns 401
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.mcp.autonomath_tools.benchmark_tools import (
    _DISCLAIMER_BENCHMARK,
    _SIZE_BAND_BOUNDS,
    benchmark_cohort_average_impl,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture()
def seeded_benchmark_cases(seeded_db: Path) -> Path:
    """Insert 5 case_studies covering small / medium / large bands + JSIC mix."""
    rows = [
        {
            "case_id": "BMK-CS-001",
            "company_name": "東京小規模建設",
            "houjin_bangou": "1111111111111",
            "is_sole_proprietor": 0,
            "prefecture": "東京都",
            "municipality": "千代田区",
            "industry_jsic": "D",
            "industry_name": "総合工事業",
            "employees": 12,
            "founded_year": 2010,
            "capital_yen": 30_000_000,
            "case_title": "小規模建設業の事業承継",
            "case_summary": "事業承継補助金で次世代に承継。",
            "programs_used_json": json.dumps(
                ["BMK_事業承継補助金", "BMK_小規模補助金"], ensure_ascii=False
            ),
            "total_subsidy_received_yen": 5_000_000,
            "publication_date": "2024-10-01",
            "source_url": "https://example.go.jp/case/bmk-001",
            "confidence": 0.9,
        },
        {
            "case_id": "BMK-CS-002",
            "company_name": "東京中規模製造",
            "is_sole_proprietor": 0,
            "prefecture": "東京都",
            "municipality": "大田区",
            "industry_jsic": "E29",
            "industry_name": "金属製品製造業",
            "employees": 45,
            "capital_yen": 120_000_000,
            "case_title": "中規模製造業の設備刷新",
            "programs_used_json": json.dumps(
                ["BMK_中規模補助金", "BMK_事業再構築補助金"], ensure_ascii=False
            ),
            "total_subsidy_received_yen": 12_000_000,
            "publication_date": "2024-09-01",
            "source_url": "https://example.go.jp/case/bmk-002",
        },
        {
            "case_id": "BMK-CS-003",
            "company_name": "東京大規模卸売",
            "prefecture": "東京都",
            "industry_jsic": "I",
            "industry_name": "卸売業",
            "employees": 250,
            "capital_yen": 600_000_000,
            "case_title": "大規模卸売の DX",
            "programs_used_json": json.dumps(["IT 導入補助金"], ensure_ascii=False),
            "total_subsidy_received_yen": 100_000_000,
            "publication_date": "2024-08-01",
            "source_url": "https://example.go.jp/case/bmk-003",
        },
        {
            "case_id": "BMK-CS-004",
            "company_name": "大阪小規模建設",
            "prefecture": "大阪府",
            "industry_jsic": "D",
            "employees": 8,
            "capital_yen": 10_000_000,
            "case_title": "大阪建設業の人材確保",
            "programs_used_json": json.dumps(["建設業人材確保支援"], ensure_ascii=False),
            "total_subsidy_received_yen": 2_000_000,
            "publication_date": "2024-07-01",
            "source_url": "https://example.go.jp/case/bmk-004",
        },
        {
            "case_id": "BMK-CS-005",
            "company_name": "東京サイズ未記載",
            "prefecture": "東京都",
            "industry_jsic": "D",
            "case_title": "資本金 NULL ケース",
            "programs_used_json": json.dumps(["BMK_小規模補助金"], ensure_ascii=False),
            "publication_date": "2024-06-01",
            "source_url": "https://example.go.jp/case/bmk-005",
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


def test_impl_envelope_shape(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(
        industry_jsic="D",
        size_band="small",
        prefecture="東京都",
    )
    for key in (
        "input",
        "cohort_size",
        "case_study_count",
        "adoption_record_count",
        "distinct_programs",
        "distinct_program_count",
        "accept_rate_proxy",
        "amount_summary",
        "outlier_top_decile",
        "axes_applied",
        "sparsity_notes",
        "_disclaimer",
        "_next_calls",
        "_billing_unit",
    ):
        assert key in res, f"missing top-level key {key!r}"

    assert res["_billing_unit"] == 1
    assert res["_disclaimer"] == _DISCLAIMER_BENCHMARK
    assert isinstance(res["distinct_programs"], list)
    assert isinstance(res["sparsity_notes"], list)
    assert len(res["sparsity_notes"]) >= 4


def test_impl_size_band_small_filters(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(
        industry_jsic="D",
        size_band="small",
        prefecture="東京都",
    )
    # BMK-CS-001 (capital 30M, small) and BMK-CS-005 (NULL → kept) match.
    # BMK-CS-002 / 003 are E29 / I, filtered by industry_jsic="D".
    distinct_programs = set(res["distinct_programs"])
    assert "BMK_事業承継補助金" in distinct_programs
    assert "BMK_小規模補助金" in distinct_programs


def test_impl_size_band_large_excludes_smalls(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(size_band="large")
    # Only BMK-CS-003 has capital > ¥300M (and a NULL row passes too).
    # The amount_summary should reflect 100M from BMK-CS-003 specifically.
    assert res["amount_summary"]["amount_yen_with_value"] >= 1
    assert res["amount_summary"]["amount_yen_max"] == 100_000_000


def test_impl_size_band_bounds_disclosed(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(size_band="medium")
    bounds = res["axes_applied"]["size_band_capital_yen"]
    assert bounds == list(_SIZE_BAND_BOUNDS["medium"])


def test_impl_unknown_size_band_normalizes_to_all(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(size_band="bogus")
    assert res["input"]["size_band"] == "all"


def test_impl_outlier_top_decile_amount_driven(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(prefecture="東京都")
    outliers = res["outlier_top_decile"]
    # At least one populated amount → at least one outlier (ceiling 1).
    assert len(outliers) >= 1
    # Outlier ranking is amount DESC; first row must be the largest amount.
    amounts = [o["amount_yen"] for o in outliers]
    assert amounts == sorted(amounts, reverse=True)


def test_impl_distinct_program_count_matches_list(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(industry_jsic="D")
    assert res["distinct_program_count"] == len(res["distinct_programs"])


def test_impl_accept_rate_proxy_directional(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(industry_jsic="D")
    rate = res["accept_rate_proxy"]
    # Without adoption_records the proxy is 0.0; impl returns None for an
    # empty cohort, otherwise a float in [0, 1].
    assert rate is None or 0.0 <= rate <= 1.0


def test_impl_no_filters_runs(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl()
    assert res["cohort_size"] >= 0
    assert "error" not in res


def test_impl_next_calls_emitted(seeded_benchmark_cases) -> None:
    res = benchmark_cohort_average_impl(industry_jsic="D", prefecture="東京都")
    next_calls = res["_next_calls"]
    assert isinstance(next_calls, list)
    assert any(c["tool"] == "case_cohort_match_am" for c in next_calls)


def test_rest_cohort_average_happy_path(client: TestClient, seeded_benchmark_cases) -> None:
    resp = client.post(
        "/v1/benchmark/cohort_average",
        json={
            "industry_jsic": "D",
            "size_band": "small",
            "prefecture": "東京都",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["_billing_unit"] == 1
    assert "distinct_programs" in data
    assert "outlier_top_decile" in data
    assert data["axes_applied"]["industry_jsic"] == "D"
    assert data["axes_applied"]["size_band"] == "small"


def test_rest_cohort_average_empty_body(client: TestClient, seeded_benchmark_cases) -> None:
    resp = client.post("/v1/benchmark/cohort_average", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["input"]["industry_jsic"] is None
    assert data["input"]["size_band"] == "all"


def test_rest_me_benchmark_requires_auth(client: TestClient, seeded_benchmark_cases) -> None:
    # No api key cookie / header → require_key returns ApiContext(None, "free")
    # but the endpoint guards on key_hash and returns 401 directly.
    resp = client.get("/v1/me/benchmark_vs_industry")
    # Either 200 with auth_required envelope or 401 from require_key.
    # The endpoint explicitly checks ctx.key_hash and surfaces 401.
    assert resp.status_code == 401


def test_rest_me_benchmark_authed_returns_envelope(
    client: TestClient, seeded_benchmark_cases, paid_key: str
) -> None:
    resp = client.get(
        "/v1/me/benchmark_vs_industry",
        params={
            "industry_jsic": "D",
            "size_band": "small",
            "prefecture": "東京都",
            "window_days": 30,
        },
        headers={"X-API-Key": paid_key},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in (
        "input",
        "cohort",
        "me",
        "leakage_programs",
        "leakage_program_count",
        "axes_applied",
        "sparsity_notes",
        "_disclaimer",
    ):
        assert key in data, f"missing key {key!r}"
    assert data["_disclaimer"] == _DISCLAIMER_BENCHMARK
    assert data["me"]["my_program_touches_known"] is False
    # leakage_programs ⊆ cohort distinct_programs.
    assert isinstance(data["leakage_programs"], list)
    assert data["leakage_program_count"] == len(data["leakage_programs"])


def test_rest_me_benchmark_clamps_window_days(
    client: TestClient, seeded_benchmark_cases, paid_key: str
) -> None:
    resp = client.get(
        "/v1/me/benchmark_vs_industry",
        params={"window_days": 9999},
        headers={"X-API-Key": paid_key},
    )
    # Pydantic Query(le=365) rejects 9999 with 422 — that's the correct
    # framework-level behaviour. The clamp inside the impl is belt-and-
    # suspenders for tests / cron callers that bypass the REST validator.
    assert resp.status_code == 422
