"""Case studies API + MCP surface tests.

Covers `/v1/case-studies/*` REST (case_studies.py) and the MCP tool
parity mirrors (`search_case_studies`, `get_case_study`).

These are 2,286 採択事例 / success-story records aggregated from
Jグランツ 採択結果, mirasapo 事業事例, and prefectural 事例集. Used by
callers to prove "a business like mine has actually received this"
before applying. Read-only surface — ingest lives externally.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_case_studies(seeded_db: Path) -> Path:
    """Insert a handful of case_studies on top of the base seed.

    Session-scoped `seeded_db` is shared; we guard with INSERT OR IGNORE
    on case_id so repeated runs are no-ops.
    """
    rows = [
        {
            "case_id": "CS-001",
            "company_name": "株式会社テスト農園",
            "houjin_bangou": "1234567890123",
            "is_sole_proprietor": 0,
            "prefecture": "北海道",
            "municipality": "札幌市",
            "industry_jsic": "0111",
            "industry_name": "米作",
            "employees": 12,
            "founded_year": 1998,
            "capital_yen": 10_000_000,
            "case_title": "スマート農業による生産性向上",
            "case_summary": "ドローンと ICT を活用して作業効率を 2 倍に改善した事例。",
            "programs_used_json": json.dumps(
                ["UNI-test-a-1", "スマート農業実証"], ensure_ascii=False
            ),
            "total_subsidy_received_yen": 5_000_000,
            "outcomes_json": json.dumps(["売上増", "作業時間短縮"], ensure_ascii=False),
            "patterns_json": json.dumps({"型": "スマート化"}, ensure_ascii=False),
            "publication_date": "2024-08-15",
            "source_url": "https://www.mirasapo-plus.go.jp/hint/example1",
            "source_excerpt": "スマート農業で生産性 2 倍",
            "confidence": 0.9,
        },
        {
            "case_id": "CS-002",
            "company_name": "テスト工業所",
            "is_sole_proprietor": 1,
            "prefecture": "東京都",
            "industry_jsic": "2451",
            "employees": 3,
            "case_title": "IT 導入で受発注を電子化",
            "programs_used_json": json.dumps(["IT 導入補助金"], ensure_ascii=False),
            "total_subsidy_received_yen": 800_000,
            "publication_date": "2023-03-01",
            "source_url": "https://www.mirasapo-plus.go.jp/hint/example2",
        },
        {
            "case_id": "CS-003",
            "company_name": "株式会社別会社",
            "prefecture": "北海道",
            "industry_jsic": "A",
            "employees": 80,
            "case_title": "六次産業化プロジェクト",
            "programs_used_json": json.dumps(
                ["UNI-test-b-1", "六次産業化支援"], ensure_ascii=False
            ),
            "total_subsidy_received_yen": 20_000_000,
            "publication_date": "2025-01-20",
            "source_url": "https://www.maff.go.jp/example3",
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


# ---------------------------------------------------------------------------
# REST: /v1/case-studies/search
# ---------------------------------------------------------------------------


def test_search_returns_all_seeded_rows(client, seeded_case_studies):
    r = client.get("/v1/case-studies/search", params={"limit": 100})
    assert r.status_code == 200
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert {"CS-001", "CS-002", "CS-003"}.issubset(ids)
    assert d["total"] >= 3
    assert d["limit"] == 100
    assert d["offset"] == 0


def test_search_orders_by_publication_date_desc(client, seeded_case_studies):
    r = client.get("/v1/case-studies/search", params={"limit": 100})
    d = r.json()
    dates = [row["publication_date"] for row in d["results"]]
    # Most recent first; NULLs coalesce to empty string and sink to bottom.
    for a, b in zip(dates, dates[1:], strict=False):
        if a is None or b is None:
            continue
        assert a >= b


def test_search_free_text_matches_case_title(client, seeded_case_studies):
    r = client.get("/v1/case-studies/search", params={"q": "スマート農業"})
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "CS-001" in ids
    assert "CS-002" not in ids


def test_search_filter_prefecture(client, seeded_case_studies):
    r = client.get(
        "/v1/case-studies/search",
        params={"prefecture": "北海道", "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert {"CS-001", "CS-003"}.issubset(ids)
    assert "CS-002" not in ids


def test_search_filter_industry_jsic_prefix(client, seeded_case_studies):
    """`A` should prefix-match both `A` (CS-003) and the numeric 0111 / 2451
    only if they happen to start with A (they don't), so only CS-003 passes.
    """
    r = client.get(
        "/v1/case-studies/search",
        params={"industry_jsic": "A", "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "CS-003" in ids
    assert "CS-001" not in ids
    assert "CS-002" not in ids


def test_search_filter_houjin_bangou_exact(client, seeded_case_studies):
    r = client.get(
        "/v1/case-studies/search",
        params={"houjin_bangou": "1234567890123"},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert ids == {"CS-001"}


def test_search_filter_program_used_substring(client, seeded_case_studies):
    """programs_used_json substring match — CS-001 uses UNI-test-a-1."""
    r = client.get(
        "/v1/case-studies/search",
        params={"program_used": "UNI-test-a-1", "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "CS-001" in ids
    assert "CS-002" not in ids


def test_search_filter_min_subsidy(client, seeded_case_studies):
    r = client.get(
        "/v1/case-studies/search",
        params={"min_subsidy_yen": 3_000_000, "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "CS-001" in ids  # 5M
    assert "CS-003" in ids  # 20M
    assert "CS-002" not in ids  # 800k


def test_search_filter_employee_range(client, seeded_case_studies):
    r = client.get(
        "/v1/case-studies/search",
        params={"min_employees": 5, "max_employees": 50, "limit": 100},
    )
    d = r.json()
    ids = {row["case_id"] for row in d["results"]}
    assert "CS-001" in ids  # 12
    assert "CS-002" not in ids  # 3
    assert "CS-003" not in ids  # 80


def test_search_programs_used_deserialised_as_list(client, seeded_case_studies):
    r = client.get("/v1/case-studies/search", params={"houjin_bangou": "1234567890123"})
    d = r.json()
    row = d["results"][0]
    assert row["programs_used"] == ["UNI-test-a-1", "スマート農業実証"]


def test_search_is_sole_proprietor_bool_cast(client, seeded_case_studies):
    """Two seeded rows: CS-001 is sole=0, CS-002 is sole=1."""
    r = client.get(
        "/v1/case-studies/search",
        params={"houjin_bangou": "1234567890123"},
    )
    d = r.json()
    assert d["results"][0]["is_sole_proprietor"] is False


def test_search_limit_clamp_upper_bound(client):
    r = client.get("/v1/case-studies/search", params={"limit": 101})
    assert r.status_code == 422


def test_search_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_case_studies,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps

    endpoint = "case_studies.search"
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = client.get(
        "/v1/case-studies/search",
        params={"limit": 100},
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


# ---------------------------------------------------------------------------
# REST: /v1/case-studies/{case_id}
# ---------------------------------------------------------------------------


def test_get_case_detail(client, seeded_case_studies):
    r = client.get("/v1/case-studies/CS-001")
    assert r.status_code == 200
    d = r.json()
    assert d["case_id"] == "CS-001"
    assert d["company_name"] == "株式会社テスト農園"
    assert d["programs_used"] == ["UNI-test-a-1", "スマート農業実証"]
    assert d["outcomes"] == ["売上増", "作業時間短縮"]
    assert d["patterns"] == {"型": "スマート化"}
    assert d["is_sole_proprietor"] is False


def test_get_case_404(client, seeded_case_studies):
    r = client.get("/v1/case-studies/DOES-NOT-EXIST")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# MCP tool parity
# ---------------------------------------------------------------------------


def test_mcp_search_case_studies(client, seeded_case_studies):
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(prefecture="北海道", limit=100)
    # Token-shaping cap (dd_v3_09 / v8 P3-K) means limit=100 emits a
    # limit_capped warning; the envelope still carries the standard 4 keys
    # plus optional input_warnings.
    assert {"total", "limit", "offset", "results"} <= set(res.keys())
    ids = {r["case_id"] for r in res["results"]}
    assert "CS-001" in ids
    assert "CS-003" in ids
    assert "CS-002" not in ids


def test_mcp_search_case_studies_limit_clamp(client, seeded_case_studies):
    """MCP tool silently caps at 20 (token-shaping); REST would 422."""
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(limit=10_000)
    assert res["limit"] == 20
    warns = res.get("input_warnings", [])
    assert any(w.get("code") == "limit_capped" for w in warns)


def test_mcp_get_case_study(client, seeded_case_studies):
    from jpintel_mcp.mcp.server import get_case_study

    rec = get_case_study("CS-001")
    assert rec["case_id"] == "CS-001"
    assert rec["is_sole_proprietor"] is False
    assert rec["programs_used"] == ["UNI-test-a-1", "スマート農業実証"]


def test_mcp_get_case_study_missing_returns_error_envelope(client, seeded_case_studies):
    from jpintel_mcp.mcp.server import get_case_study

    res = get_case_study("NOT-A-CASE")
    assert res.get("error"), "expected structured error envelope"
    assert res["code"] == "no_matching_records"
    assert "not found" in res["error"]
    assert "NOT-A-CASE" in res["error"]
    assert "hint" in res
