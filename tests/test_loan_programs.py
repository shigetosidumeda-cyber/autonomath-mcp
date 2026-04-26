"""Loan programs API + MCP surface tests.

Covers `/v1/loan-programs/*` REST (loan_programs.py) and MCP tool mirrors
(`search_loan_programs`, `get_loan_program`).

The headline feature under test: three-axis risk filtering. A single row
for JFC マル経 (無担保・無保証) vs. a row with 担保あり and 個人保証 must
be independently addressable — that is the 2026-04-23 pivot captured in
migration 013. See project_autonomath_loan_risk_axes memory for the why.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_loan_programs(seeded_db: Path) -> Path:
    """Insert three loan_programs rows spanning the three risk-axis
    combinations the 無担保・無保証 filter needs to distinguish.
    """
    rows = [
        {
            "program_name": "マル経融資（テスト）",
            "provider": "日本政策金融公庫",
            "loan_type": "運転資金",
            "amount_max_yen": 20_000_000,
            "loan_period_years_max": 10,
            "interest_rate_base_annual": 0.0135,
            "rate_names": "基準利率（マル経）",
            "security_required": "無担保・無保証人",
            "target_conditions": "商工会議所の経営指導を 6 か月以上受けた小規模事業者",
            "official_url": "https://www.jfc.go.jp/n/finance/search/example_maruke",
            "collateral_required": "not_required",
            "personal_guarantor_required": "not_required",
            "third_party_guarantor_required": "not_required",
            "confidence": 0.95,
        },
        {
            "program_name": "中小企業設備資金（テスト）",
            "provider": "東京都信用保証協会",
            "loan_type": "設備資金",
            "amount_max_yen": 80_000_000,
            "loan_period_years_max": 15,
            "interest_rate_base_annual": 0.021,
            "rate_names": "協調融資基準",
            "security_required": "担保・保証人あり",
            "collateral_required": "required",
            "personal_guarantor_required": "required",
            "third_party_guarantor_required": "required",
            "confidence": 0.85,
        },
        {
            "program_name": "創業支援融資（テスト）",
            "provider": "日本政策金融公庫",
            "loan_type": "運転資金",
            "amount_max_yen": 30_000_000,
            "loan_period_years_max": 7,
            "interest_rate_base_annual": 0.017,
            "rate_names": "基準利率（創業）",
            "collateral_required": "negotiable",
            "personal_guarantor_required": "required",
            "third_party_guarantor_required": "not_required",
            "confidence": 0.9,
        },
    ]

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    for r in rows:
        cols = ",".join(r.keys())
        placeholders = ",".join("?" * len(r))
        conn.execute(
            f"INSERT OR IGNORE INTO loan_programs({cols}) VALUES ({placeholders})",
            list(r.values()),
        )
    conn.commit()
    conn.close()
    return seeded_db


def _ids_by_name(results: list[dict]) -> set[str]:
    return {r["program_name"] for r in results}


# ---------------------------------------------------------------------------
# REST: /v1/loan-programs/search
# ---------------------------------------------------------------------------


def test_search_returns_seeded_rows(client, seeded_loan_programs):
    r = client.get("/v1/loan-programs/search", params={"limit": 100})
    assert r.status_code == 200
    d = r.json()
    names = _ids_by_name(d["results"])
    assert {
        "マル経融資（テスト）",
        "中小企業設備資金（テスト）",
        "創業支援融資（テスト）",
    }.issubset(names)


def test_search_orders_by_amount_max_desc(client, seeded_loan_programs):
    r = client.get("/v1/loan-programs/search", params={"limit": 100})
    d = r.json()
    amounts = [row["amount_max_yen"] for row in d["results"]]
    for a, b in zip(amounts, amounts[1:], strict=False):
        if a is None or b is None:
            continue
        assert a >= b


def test_search_free_text_matches_provider(client, seeded_loan_programs):
    r = client.get(
        "/v1/loan-programs/search", params={"q": "商工会議所", "limit": 100}
    )
    names = _ids_by_name(r.json()["results"])
    assert "マル経融資（テスト）" in names


def test_search_filter_provider(client, seeded_loan_programs):
    r = client.get(
        "/v1/loan-programs/search",
        params={"provider": "東京都信用保証協会", "limit": 100},
    )
    names = _ids_by_name(r.json()["results"])
    assert "中小企業設備資金（テスト）" in names
    assert "マル経融資（テスト）" not in names


def test_search_three_axis_fully_unsecured(client, seeded_loan_programs):
    """The HEADLINE feature: asking "give me 無担保・無保証人 offerings"
    must return マル経 and only マル経 from the seeded set.
    """
    r = client.get(
        "/v1/loan-programs/search",
        params={
            "collateral_required": "not_required",
            "personal_guarantor_required": "not_required",
            "third_party_guarantor_required": "not_required",
            "limit": 100,
        },
    )
    names = _ids_by_name(r.json()["results"])
    assert "マル経融資（テスト）" in names
    assert "中小企業設備資金（テスト）" not in names
    assert "創業支援融資（テスト）" not in names


def test_search_third_party_not_required_only(client, seeded_loan_programs):
    """Partial relaxation — 第三者保証 無 でよいが代表者保証は可。
    マル経 (全3軸 not_required) と 創業支援 (3軸目 not_required) の両方に当たる。
    """
    r = client.get(
        "/v1/loan-programs/search",
        params={"third_party_guarantor_required": "not_required", "limit": 100},
    )
    names = _ids_by_name(r.json()["results"])
    assert {"マル経融資（テスト）", "創業支援融資（テスト）"}.issubset(names)
    assert "中小企業設備資金（テスト）" not in names


def test_search_rejects_unknown_axis_value(client):
    r = client.get(
        "/v1/loan-programs/search",
        params={"collateral_required": "definitely_required"},
    )
    assert r.status_code == 422
    body = r.json()
    assert "collateral_required" in body["detail"]


def test_search_max_interest_rate(client, seeded_loan_programs):
    """1.5 % 以下 → マル経 (1.35 %) だけ。"""
    r = client.get(
        "/v1/loan-programs/search",
        params={"max_interest_rate": 0.015, "limit": 100},
    )
    names = _ids_by_name(r.json()["results"])
    assert "マル経融資（テスト）" in names
    assert "中小企業設備資金（テスト）" not in names
    assert "創業支援融資（テスト）" not in names


def test_search_min_loan_period_years(client, seeded_loan_programs):
    """10 年以上 → マル経 (10) と 設備 (15)。"""
    r = client.get(
        "/v1/loan-programs/search",
        params={"min_loan_period_years": 10, "limit": 100},
    )
    names = _ids_by_name(r.json()["results"])
    assert {"マル経融資（テスト）", "中小企業設備資金（テスト）"}.issubset(names)
    assert "創業支援融資（テスト）" not in names


def test_search_limit_clamp_upper_bound(client):
    r = client.get("/v1/loan-programs/search", params={"limit": 101})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# REST: /v1/loan-programs/{loan_id}
# ---------------------------------------------------------------------------


def test_get_loan_detail(client, seeded_loan_programs):
    search = client.get(
        "/v1/loan-programs/search",
        params={"provider": "東京都信用保証協会", "limit": 1},
    )
    loan_id = search.json()["results"][0]["id"]
    r = client.get(f"/v1/loan-programs/{loan_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["program_name"] == "中小企業設備資金（テスト）"
    assert d["collateral_required"] == "required"


def test_get_loan_404(client, seeded_loan_programs):
    r = client.get("/v1/loan-programs/999999999")
    assert r.status_code == 404


def test_get_loan_bad_id_type(client):
    r = client.get("/v1/loan-programs/not-a-number")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# MCP tool parity
# ---------------------------------------------------------------------------


def test_mcp_search_loan_programs_three_axis(client, seeded_loan_programs):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(
        collateral_required="not_required",
        personal_guarantor_required="not_required",
        third_party_guarantor_required="not_required",
        limit=100,
    )
    names = _ids_by_name(res["results"])
    assert "マル経融資（テスト）" in names
    assert "中小企業設備資金（テスト）" not in names


def test_mcp_search_loan_programs_bad_axis_returns_error_envelope(client, seeded_loan_programs):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(collateral_required="lolnope")
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "invalid_enum"
    assert "collateral_required" in res["error"]["message"]
    assert "retry_with" in res["error"]
    # Empty payload still present alongside the error.
    assert res["results"] == []


def test_mcp_search_loan_programs_limit_clamp(client, seeded_loan_programs):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(limit=10_000)
    assert res["limit"] == 100


def test_mcp_get_loan_program(client, seeded_loan_programs):
    from jpintel_mcp.mcp.server import get_loan_program, search_loan_programs

    s = search_loan_programs(provider="日本政策金融公庫", limit=100)
    target = next(r for r in s["results"] if r["program_name"] == "マル経融資（テスト）")
    rec = get_loan_program(target["id"])
    assert rec["program_name"] == "マル経融資（テスト）"
    assert rec["collateral_required"] == "not_required"
    assert rec["third_party_guarantor_required"] == "not_required"


def test_mcp_get_loan_program_missing_returns_error_envelope(client, seeded_loan_programs):
    from jpintel_mcp.mcp.server import get_loan_program

    res = get_loan_program(999_999_999)
    assert res.get("error"), "expected structured error envelope"
    assert res["code"] == "no_matching_records"
    assert "not found" in res["error"]
    assert "hint" in res
