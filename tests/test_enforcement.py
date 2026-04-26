"""Enforcement cases API + MCP surface tests.

Covers `/v1/enforcement-cases/*` REST (enforcement.py) and the MCP tool
parity mirrors (`search_enforcement_cases`, `get_enforcement_case`).

Data model rationale lives in src/jpintel_mcp/api/enforcement.py — these
are 1,185 会計検査院 findings used for compliance / DD lookup before
advising on a program with clawback history. The surface is read-only;
rows are ingested externally.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_enforcement_cases(seeded_db: Path) -> Path:
    """Insert a handful of enforcement_cases rows on top of the base seed.

    Session-scoped `seeded_db` is shared across tests; seeding here in a
    function-scoped fixture risks collisions across files. We guard with
    INSERT OR IGNORE on case_id so repeated runs are no-ops.
    """
    rows = [
        {
            "case_id": "ENF-001",
            "event_type": "improper_payment",
            "program_name_hint": "経営発展支援事業",
            "recipient_name": "株式会社テスト農園",
            "recipient_kind": "corporation",
            "recipient_houjin_bangou": "1234567890123",
            "is_sole_proprietor": 0,
            "bureau": "東北農政局",
            "prefecture": "青森県",
            "ministry": "農林水産省",
            "occurred_fiscal_years_json": json.dumps([2022, 2023]),
            "amount_yen": 5_000_000,
            "amount_improper_grant_yen": 3_000_000,
            "reason_excerpt": "対象外設備を計上していた",
            "legal_basis": "補助金等に係る予算の執行の適正化に関する法律",
            "source_url": "https://www.jbaudit.go.jp/report/example1.html",
            "source_title": "令和5年度決算検査報告",
            "disclosed_date": "2024-11-07",
            "confidence": 0.95,
        },
        {
            "case_id": "ENF-002",
            "event_type": "diversion",
            "program_name_hint": "雇用就農資金",
            "recipient_name": "テスト太郎",
            "recipient_kind": "sole_proprietor",
            "is_sole_proprietor": 1,
            "prefecture": "北海道",
            "ministry": "農林水産省",
            "occurred_fiscal_years_json": json.dumps([2021]),
            "amount_improper_grant_yen": 1_200_000,
            "reason_excerpt": "自家消費目的で購入した設備に補助金を充当",
            "disclosed_date": "2023-11-10",
            "source_url": "https://www.jbaudit.go.jp/report/example2.html",
        },
        {
            "case_id": "ENF-003",
            "event_type": "eligibility_failure",
            "program_name_hint": "ものづくり補助金",
            "ministry": "経済産業省",
            "prefecture": "東京都",
            "amount_improper_grant_yen": 10_000_000,
            "disclosed_date": "2025-11-05",
            "source_url": "https://www.jbaudit.go.jp/report/example3.html",
        },
    ]

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    for r in rows:
        cols = ",".join(r.keys())
        placeholders = ",".join("?" * len(r))
        conn.execute(
            f"INSERT OR IGNORE INTO enforcement_cases({cols}) VALUES ({placeholders})",
            list(r.values()),
        )
    conn.commit()
    conn.close()
    return seeded_db


# ---------------------------------------------------------------------------
# REST: /v1/enforcement-cases/search
# ---------------------------------------------------------------------------


def test_search_returns_all_seeded_rows(client, seeded_enforcement_cases):
    r = client.get("/v1/enforcement-cases/search", params={"limit": 100})
    assert r.status_code == 200
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert {"ENF-001", "ENF-002", "ENF-003"}.issubset(ids)
    assert d["total"] >= 3
    assert d["limit"] == 100
    assert d["offset"] == 0


def test_search_orders_by_disclosed_date_desc(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"limit": 100, "ministry": "農林水産省"},
    )
    d = r.json()
    dates = [row["disclosed_date"] for row in d["results"]]
    # Most recent first; NULLs coalesce to empty string and sink to bottom.
    for a, b in zip(dates, dates[1:], strict=False):
        if a is None or b is None:
            continue
        assert a >= b


def test_search_free_text_matches_program_hint(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search", params={"q": "経営発展"}
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "ENF-001" in ids


def test_search_filter_ministry(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"ministry": "経済産業省", "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "ENF-003" in ids
    assert "ENF-001" not in ids


def test_search_filter_prefecture(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"prefecture": "青森県", "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert ids == {"ENF-001"} or "ENF-001" in ids


def test_search_filter_houjin_bangou_exact_match(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"recipient_houjin_bangou": "1234567890123"},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert ids == {"ENF-001"}


def test_search_filter_min_improper_grant(client, seeded_enforcement_cases):
    """ENF-003 @ 10M yen should pass a 5M floor; ENF-002 @ 1.2M should not."""
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"min_improper_grant_yen": 5_000_000, "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "ENF-003" in ids
    assert "ENF-002" not in ids


def test_search_filter_disclosed_date_range(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={
            "disclosed_from": "2024-01-01",
            "disclosed_until": "2024-12-31",
            "limit": 100,
        },
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "ENF-001" in ids  # 2024-11-07
    assert "ENF-002" not in ids  # 2023
    assert "ENF-003" not in ids  # 2025


def test_search_rejects_malformed_disclosed_from(client):
    r = client.get(
        "/v1/enforcement-cases/search", params={"disclosed_from": "2024/01/01"}
    )
    assert r.status_code == 422


def test_search_occurred_fiscal_years_deserialized_as_int_list(
    client, seeded_enforcement_cases
):
    r = client.get(
        "/v1/enforcement-cases/search",
        params={"recipient_houjin_bangou": "1234567890123"},
    )
    d = r.json()
    row = d["results"][0]
    assert row["occurred_fiscal_years"] == [2022, 2023]


def test_search_is_sole_proprietor_bool_cast(client, seeded_enforcement_cases):
    r = client.get(
        "/v1/enforcement-cases/search", params={"prefecture": "北海道"}
    )
    d = r.json()
    row = next(row for row in d["results"] if row["case_id"] == "ENF-002")
    assert row["is_sole_proprietor"] is True


def test_search_limit_clamp_respects_upper_bound(client):
    r = client.get("/v1/enforcement-cases/search", params={"limit": 101})
    # Query(ge=1, le=100) → 422 on over-limit (not silent clamp).
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# REST: /v1/enforcement-cases/{case_id}
# ---------------------------------------------------------------------------


def test_get_case_detail(client, seeded_enforcement_cases):
    r = client.get("/v1/enforcement-cases/ENF-001")
    assert r.status_code == 200
    d = r.json()
    assert d["case_id"] == "ENF-001"
    assert d["ministry"] == "農林水産省"
    assert d["amount_improper_grant_yen"] == 3_000_000
    assert d["occurred_fiscal_years"] == [2022, 2023]
    assert d["is_sole_proprietor"] is False


def test_get_case_404(client, seeded_enforcement_cases):
    r = client.get("/v1/enforcement-cases/DOES-NOT-EXIST")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# MCP tool parity
# ---------------------------------------------------------------------------


def test_mcp_search_enforcement_cases(client, seeded_enforcement_cases):
    from jpintel_mcp.mcp.server import search_enforcement_cases

    res = search_enforcement_cases(ministry="農林水産省", limit=100)
    # Required envelope keys (dd_v4_08 / v8 P3-L adds meta + retrieval_note;
    # other optional keys like input_warnings may also appear).
    assert {"total", "limit", "offset", "results"} <= set(res.keys())
    assert "data_as_of" in res.get("meta", {})
    ids = {r["case_id"] for r in res["results"]}
    assert "ENF-001" in ids
    assert "ENF-002" in ids
    assert "ENF-003" not in ids


def test_mcp_search_enforcement_limit_clamp(client, seeded_enforcement_cases):
    """MCP tool caps at 20 (token-shaping cap, dd_v3_09 / v8 P3-K)."""
    from jpintel_mcp.mcp.server import search_enforcement_cases

    res = search_enforcement_cases(limit=10_000)
    assert res["limit"] == 20
    warns = res.get("input_warnings", [])
    assert any(w.get("code") == "limit_capped" for w in warns)


def test_mcp_get_enforcement_case(client, seeded_enforcement_cases):
    from jpintel_mcp.mcp.server import get_enforcement_case

    rec = get_enforcement_case("ENF-002")
    assert rec["case_id"] == "ENF-002"
    assert rec["is_sole_proprietor"] is True
    assert rec["occurred_fiscal_years"] == [2021]


def test_mcp_get_enforcement_case_missing_returns_error_envelope(client, seeded_enforcement_cases):
    from jpintel_mcp.mcp.server import get_enforcement_case

    res = get_enforcement_case("NOT-A-CASE")
    assert res.get("error"), "expected structured error envelope"
    assert res["code"] == "no_matching_records"
    assert "not found" in res["error"]
    assert "NOT-A-CASE" in res["error"]
    assert "hint" in res
