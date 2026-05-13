"""R8 cross-reference deep link API tests.

Covers the three new endpoints shipped in
``api/programs_full_context.py``:

  * GET /v1/programs/{program_id}/full_context — composite envelope
    bundling program + 法令根拠 + 改正履歴 + 関連判例 + 同業 採択事例 +
    関連 行政処分 + 排他ルール.
  * GET /v1/laws/{law_id}/related_programs — reverse lookup with
    supersession-chain walk + ref_kind histogram.
  * GET /v1/cases/by_industry_size_pref — 3-axis case_studies narrow.

Tests use the session-scoped ``seeded_db`` from ``conftest.py`` which
pre-creates the programs / exclusion_rules backbone. Per-test fixtures
seed the cross-reference rows (laws / program_law_refs / case_studies /
court_decisions / enforcement_cases) so the composite envelope walks
every section in the happy path.

NO LLM. NO HTTP. The tests boot the FastAPI app via ``TestClient`` and
share the same in-process SQLite that the live server uses.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_LAW_IDS = ("LAW-aaaaa01a0a", "LAW-bbbbb01b0a")
_COURT_IDS = ("HAN-aaaaaaa1ab", "HAN-bbbbbbb2cd")
_CASE_IDS = ("CS-pf-001", "CS-pf-002", "CS-pf-003")
_ENFORCEMENT_IDS = ("ENF-pf-001", "ENF-pf-002")


def _cleanup_cross_ref_rows(conn: sqlite3.Connection) -> None:
    """Remove only the rows owned by this test module.

    ``seeded_db`` is session-scoped, so these cross-reference rows otherwise
    bleed into whichever tests share the worker after this file.
    """
    conn.execute(
        f"DELETE FROM program_law_refs WHERE law_unified_id IN ({','.join('?' for _ in _LAW_IDS)})",
        _LAW_IDS,
    )
    conn.execute(
        f"DELETE FROM laws WHERE unified_id IN ({','.join('?' for _ in _LAW_IDS)})",
        _LAW_IDS,
    )
    conn.execute(
        f"DELETE FROM court_decisions WHERE unified_id IN ({','.join('?' for _ in _COURT_IDS)})",
        _COURT_IDS,
    )
    conn.execute(
        f"DELETE FROM case_studies WHERE case_id IN ({','.join('?' for _ in _CASE_IDS)})",
        _CASE_IDS,
    )
    conn.execute(
        "DELETE FROM enforcement_cases "
        f"WHERE case_id IN ({','.join('?' for _ in _ENFORCEMENT_IDS)})",
        _ENFORCEMENT_IDS,
    )


# ---------------------------------------------------------------------------
# Fixture: seed cross-reference rows on top of the base seeded_db. Idempotent
# via INSERT OR IGNORE so reruns within one session are no-ops.
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_cross_ref(seeded_db: Path) -> Iterator[Path]:
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        _cleanup_cross_ref_rows(conn)

        # ---- laws ----
        conn.execute(
            "INSERT OR IGNORE INTO laws ("
            "    unified_id, law_number, law_title, law_short_title, law_type, "
            "    ministry, promulgated_date, enforced_date, last_amended_date, "
            "    revision_status, superseded_by_law_id, article_count, "
            "    full_text_url, summary, subject_areas_json, source_url, "
            "    source_checksum, confidence, fetched_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "LAW-aaaaa01a0a",
                "平成12年法律第50号",
                "テスト補助金法",
                "テスト補助金法",
                "act",
                "経済産業省",
                "2000-04-01",
                "2000-07-01",
                "2024-12-15",
                "current",
                None,
                42,
                "https://elaws.e-gov.go.jp/test01a",
                "テスト補助金の根拠法",
                json.dumps(["産業"], ensure_ascii=False),
                "https://elaws.e-gov.go.jp/test01a",
                "checksum-01a",
                0.95,
                "2026-04-01T00:00:00Z",
                "2026-04-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO laws ("
            "    unified_id, law_number, law_title, law_short_title, law_type, "
            "    ministry, promulgated_date, enforced_date, last_amended_date, "
            "    revision_status, superseded_by_law_id, article_count, "
            "    full_text_url, summary, subject_areas_json, source_url, "
            "    source_checksum, confidence, fetched_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "LAW-bbbbb01b0a",
                "令和5年法律第10号",
                "テスト補助金法 改正版",
                None,
                "act",
                "経済産業省",
                "2023-04-01",
                "2023-04-01",
                "2024-12-15",
                "current",
                None,
                45,
                "https://elaws.e-gov.go.jp/test01b",
                "テスト補助金法の改正版",
                json.dumps(["産業"], ensure_ascii=False),
                "https://elaws.e-gov.go.jp/test01b",
                "checksum-01b",
                0.95,
                "2026-04-01T00:00:00Z",
                "2026-04-01T00:00:00Z",
            ),
        )
        # supersede LAW-aaaaa01a0a -> LAW-bbbbb01b0a so the chain walk has 2 hops.
        conn.execute(
            "UPDATE laws SET superseded_by_law_id = ? WHERE unified_id = ?",
            ("LAW-bbbbb01b0a", "LAW-aaaaa01a0a"),
        )

        # ---- program_law_refs ----
        plr_rows = [
            (
                "UNI-test-s-1",
                "LAW-aaaaa01a0a",
                "authority",
                "第5条第2項",
                "https://example.go.jp/koubo/v1.pdf",
                "2026-04-01T00:00:00Z",
                0.95,
            ),
            (
                "UNI-test-s-1",
                "LAW-bbbbb01b0a",
                "eligibility",
                "第10条",
                "https://example.go.jp/koubo/v1.pdf",
                "2026-04-01T00:00:00Z",
                0.90,
            ),
            (
                "UNI-test-a-1",
                "LAW-aaaaa01a0a",
                "reference",
                None,
                "https://example.go.jp/koubo/aomori.pdf",
                "2026-04-01T00:00:00Z",
                0.85,
            ),
        ]
        for r in plr_rows:
            conn.execute(
                "INSERT OR IGNORE INTO program_law_refs("
                "    program_unified_id, law_unified_id, ref_kind, "
                "    article_citation, source_url, fetched_at, confidence) "
                "VALUES (?,?,?,?,?,?,?)",
                r,
            )

        # ---- court_decisions ----
        court_rows = [
            (
                "HAN-aaaaaaa1ab",
                "テスト補助金不交付処分取消請求事件",
                "令和5年(行ウ)第1号",
                "東京地方裁判所",
                "district",
                "2023-12-15",
                "判決",
                "補助金適正化法",
                json.dumps(["LAW-aaaaa01a0a", "LAW-bbbbb01b0a"], ensure_ascii=False),
                "テスト補助金不交付の判断基準",
                "本件はテスト補助金法第5条第2項に基づく裁量判断の合理性が争点。",
                "持続的な事業基盤の有無で交付判断が分かれる。",
                "persuasive",
                "https://www.courts.go.jp/test01",
                "https://www.courts.go.jp/test01.pdf",
                "https://www.courts.go.jp/test01",
                "判決要旨抜粋",
                None,
                0.92,
                "2026-04-01T00:00:00Z",
                "2026-04-01T00:00:00Z",
            ),
            (
                "HAN-bbbbbbb2cd",
                "別事件",
                "令和4年(行ウ)第2号",
                "最高裁判所第三小法廷",
                "supreme",
                "2022-08-30",
                "判決",
                "租税",
                json.dumps(["LAW-cccccczzz1"], ensure_ascii=False),
                "本件は対象外",
                "本件は LAW-cccccczzz1 のみ参照、テスト補助金法とは無関係。",
                "テスト用の対象外行。",
                "binding",
                "https://www.courts.go.jp/test-other",
                None,
                "https://www.courts.go.jp/test-other",
                None,
                None,
                0.95,
                "2026-04-01T00:00:00Z",
                "2026-04-01T00:00:00Z",
            ),
        ]
        for r in court_rows:
            conn.execute(
                "INSERT OR IGNORE INTO court_decisions("
                "    unified_id, case_name, case_number, court, court_level, "
                "    decision_date, decision_type, subject_area, "
                "    related_law_ids_json, key_ruling, parties_involved, "
                "    impact_on_business, precedent_weight, full_text_url, "
                "    pdf_url, source_url, source_excerpt, source_checksum, "
                "    confidence, fetched_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                r,
            )

        # ---- case_studies ----
        case_rows = [
            (
                "CS-pf-001",
                "株式会社テスト製造",
                "1234567890123",
                0,
                "東京都",
                "新宿区",
                "2451",
                "金属プレス製品",
                25,
                2005,
                30_000_000,
                "テスト補助金で生産ライン更新",
                "テスト補助金 を活用してプレス機を更新。",
                json.dumps(["テスト S-tier 補助金"], ensure_ascii=False),
                12_000_000,
                json.dumps(["売上 1.3 倍"], ensure_ascii=False),
                json.dumps(["設備投資"], ensure_ascii=False),
                "2025-08-10",
                "https://example.go.jp/case-pf-001",
                "テスト補助金 で生産ラインを更新した。",
                "2026-04-01T00:00:00Z",
                0.91,
            ),
            (
                "CS-pf-002",
                "テスト工房",
                None,
                1,
                "東京都",
                "渋谷区",
                "2452",
                "金属切削加工",
                3,
                2018,
                3_000_000,
                "個人事業主 IT 化",
                "個人事業主が IT 化に成功。",
                json.dumps(["別補助金"], ensure_ascii=False),
                500_000,
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                "2024-01-20",
                "https://example.go.jp/case-pf-002",
                None,
                "2026-04-01T00:00:00Z",
                0.85,
            ),
            (
                "CS-pf-003",
                "別県別業種",
                None,
                0,
                "北海道",
                "札幌市",
                "0111",
                "米作",
                12,
                1990,
                10_000_000,
                "農業 IoT",
                "農業 IoT 試行。",
                json.dumps(["UNI-test-a-1"], ensure_ascii=False),
                2_000_000,
                None,
                None,
                "2024-08-01",
                "https://example.go.jp/case-pf-003",
                None,
                "2026-04-01T00:00:00Z",
                0.88,
            ),
        ]
        for r in case_rows:
            conn.execute(
                "INSERT OR IGNORE INTO case_studies("
                "    case_id, company_name, houjin_bangou, is_sole_proprietor, "
                "    prefecture, municipality, industry_jsic, industry_name, "
                "    employees, founded_year, capital_yen, "
                "    case_title, case_summary, programs_used_json, "
                "    total_subsidy_received_yen, outcomes_json, patterns_json, "
                "    publication_date, source_url, source_excerpt, "
                "    fetched_at, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                r,
            )

        # ---- enforcement_cases ----
        enforcement_rows = [
            (
                "ENF-pf-001",
                "subsidy_exclude",
                "テスト S-tier 補助金",
                "違反企業A",
                "corporation",
                "9999999999990",
                0,
                "経済産業省",
                None,
                "東京都",
                "経済産業省",
                json.dumps([2024], ensure_ascii=False),
                None,
                None,
                None,
                None,
                None,
                "申請書類偽装による不適切受給。",
                "テスト補助金法 第30条",
                "https://example.go.jp/enforcement-pf-001",
                "section",
                "title",
                "2025-03-10",
                None,
                "2026-04-01T00:00:00Z",
                0.94,
            ),
            (
                "ENF-pf-002",
                "fine",
                None,
                "違反企業B",
                "corporation",
                None,
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "別の事案、テスト S-tier 補助金 とは無関係。",
                "他の根拠法",
                "https://example.go.jp/enforcement-pf-002",
                None,
                None,
                "2024-12-01",
                None,
                "2026-04-01T00:00:00Z",
                0.80,
            ),
        ]
        for r in enforcement_rows:
            conn.execute(
                "INSERT OR IGNORE INTO enforcement_cases("
                "    case_id, event_type, program_name_hint, recipient_name, "
                "    recipient_kind, recipient_houjin_bangou, is_sole_proprietor, "
                "    bureau, intermediate_recipient, prefecture, ministry, "
                "    occurred_fiscal_years_json, amount_yen, "
                "    amount_project_cost_yen, amount_grant_paid_yen, "
                "    amount_improper_grant_yen, amount_improper_project_cost_yen, "
                "    reason_excerpt, legal_basis, source_url, source_section, "
                "    source_title, disclosed_date, disclosed_until, fetched_at, "
                "    confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                r,
            )

        conn.commit()
    finally:
        conn.close()
    yield seeded_db

    conn = sqlite3.connect(seeded_db)
    try:
        _cleanup_cross_ref_rows(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def cross_ref_client(seeded_cross_ref: Path) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests — /v1/programs/{program_id}/full_context
# ---------------------------------------------------------------------------


def test_full_context_happy_path(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get("/v1/programs/UNI-test-s-1/full_context")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level shape.
    assert body["program_id"] == "UNI-test-s-1"
    assert body["max_per_section"] == 10
    assert body["_billing_unit"] == 1
    assert "税理士法 §52" in body["_disclaimer"]
    assert "弁護士法 §72" in body["_disclaimer"]
    assert "data_quality" in body
    assert "corpus_snapshot_id" in body

    # Program metadata.
    program = body["program"]
    assert program["program_id"] == "UNI-test-s-1"
    assert program["primary_name"] == "テスト S-tier 補助金"
    assert program["tier"] == "S"
    assert program["prefecture"] == "東京都"
    assert program["expected_amount_max_yen"] == 1000 * 10_000

    # Law basis: 2 plr rows + the supersession chain.
    law_basis = body["law_basis"]
    assert isinstance(law_basis, dict)
    assert isinstance(law_basis["laws"], list)
    assert len(law_basis["laws"]) >= 2
    law_titles = {row["law_title"] for row in law_basis["laws"]}
    assert "テスト補助金法" in law_titles
    assert "テスト補助金法 改正版" in law_titles
    assert set(law_basis["law_unified_ids"]) == {"LAW-aaaaa01a0a", "LAW-bbbbb01b0a"}
    # authority rank ordering: first row is authority kind.
    assert law_basis["laws"][0]["ref_kind"] == "authority"

    # Court decisions: 1 in-scope + 1 unrelated; only the related one appears.
    court = body["court_decisions"]
    assert isinstance(court, list)
    court_ids = {row["unified_id"] for row in court}
    assert "HAN-aaaaaaa1ab" in court_ids
    assert "HAN-bbbbbbb2cd" not in court_ids
    related = next(row for row in court if row["unified_id"] == "HAN-aaaaaaa1ab")
    assert "LAW-aaaaa01a0a" in related["related_law_ids"]

    # Case studies: at least the program-name match (CS-pf-001).
    cases = body["case_studies"]
    assert isinstance(cases, list)
    assert len(cases) >= 1
    case_ids = {c["case_id"] for c in cases}
    assert "CS-pf-001" in case_ids

    # Enforcement cases: only ENF-pf-001 (program_name_hint match).
    enforcement = body["enforcement_cases"]
    assert isinstance(enforcement, list)
    case_ids = {c["case_id"] for c in enforcement}
    assert "ENF-pf-001" in case_ids
    assert "ENF-pf-002" not in case_ids

    # Exclusion rules: program participates as A on UID rule (`excl-test-uid-mutex`).
    rules = body["exclusion_rules"]
    assert isinstance(rules, list)
    rule_ids = {r["rule_id"] for r in rules}
    assert "excl-test-uid-mutex" in rule_ids


def test_full_context_include_sections_filter(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/programs/UNI-test-s-1/full_context",
        params=[
            ("include_sections", "program"),
            ("include_sections", "exclusion_rules"),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["include_sections"] == ["program", "exclusion_rules"]
    assert "program" in body
    assert "exclusion_rules" in body
    for stripped in (
        "law_basis",
        "court_decisions",
        "case_studies",
        "enforcement_cases",
    ):
        assert stripped not in body, f"{stripped} should not appear when stripped"


def test_full_context_404_unknown_program(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get("/v1/programs/UNI-does-not-exist-anywhere/full_context")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert "UNI-does-not-exist-anywhere" in detail


def test_full_context_invalid_section_returns_422(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/programs/UNI-test-s-1/full_context",
        params=[("include_sections", "not_a_real_section")],
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_include_sections"
    assert "not_a_real_section" in str(detail)


def test_full_context_jsic_narrows_case_studies(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/programs/UNI-test-s-1/full_context",
        params=[
            ("include_sections", "case_studies"),
            ("industry_jsic", "245"),
            ("prefecture", "東京都"),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Only JSIC 245x rows in 東京都 land — CS-pf-001 (2451) and CS-pf-002 (2452).
    case_ids = {c["case_id"] for c in body["case_studies"]}
    assert "CS-pf-003" not in case_ids
    assert "CS-pf-001" in case_ids
    assert "CS-pf-002" in case_ids


# ---------------------------------------------------------------------------
# Tests — /v1/laws/{law_id}/related_programs
# ---------------------------------------------------------------------------


def test_law_related_programs_chain_walk(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/laws/LAW-aaaaa01a0a/related_programs",
        params=[("include_superseded", "true")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["law"]["law_unified_id"] == "LAW-aaaaa01a0a"
    assert body["law"]["law_title"] == "テスト補助金法"
    # supersession chain walks forward to LAW-bbbbb01b0a.
    assert "LAW-bbbbb01b0a" in body["chain_law_unified_ids"]
    assert body["include_superseded"] is True

    # ref_kind histogram includes at-least the 3 fixture rows (1 authority
    # on LAW-aaaaa01a0a, 1 eligibility on LAW-bbbbb01b0a via supersession,
    # 1 reference on LAW-aaaaa01a0a). Exact totals can drift if other tests
    # in the same session-scoped DB also seed program_law_refs against the
    # chain ids.
    histo = body["ref_kind_histogram"]
    assert histo["authority"] >= 1
    assert histo["eligibility"] >= 1
    assert histo["reference"] >= 1

    # At least the 3 fixture rows land (2 distinct programs).
    assert body["total"] >= 3
    assert len(body["results"]) >= 3
    program_ids = {r["program_unified_id"] for r in body["results"]}
    assert "UNI-test-s-1" in program_ids
    assert "UNI-test-a-1" in program_ids
    # authority-first ordering puts an authority row at index 0.
    assert body["results"][0]["ref_kind"] == "authority"


def test_law_related_programs_no_chain_walk(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/laws/LAW-aaaaa01a0a/related_programs",
        params=[("include_superseded", "false")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chain_law_unified_ids"] == ["LAW-aaaaa01a0a"]
    # No supersession walk → only LAW-aaaaa01a0a refs surface. The 2
    # fixture rows we own are an authority (UNI-test-s-1) and a reference
    # (UNI-test-a-1); both must be present, and the seeded test program
    # must NOT have an eligibility ref to LAW-aaaaa01a0a directly.
    fixture_rows = [
        r
        for r in body["results"]
        if r["program_unified_id"] in {"UNI-test-s-1", "UNI-test-a-1"}
        and r["law_unified_id"] == "LAW-aaaaa01a0a"
    ]
    fixture_kinds = {r["ref_kind"] for r in fixture_rows}
    assert "authority" in fixture_kinds
    assert "reference" in fixture_kinds
    # Our fixture's eligibility row keys on LAW-bbbbb01b0a, so excluding
    # the chain walk should drop it from the result for these two programs.
    assert not any(
        r["program_unified_id"] == "UNI-test-s-1"
        and r["ref_kind"] == "eligibility"
        and r["law_unified_id"] == "LAW-aaaaa01a0a"
        for r in body["results"]
    )


def test_law_related_programs_ref_kind_filter(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/laws/LAW-aaaaa01a0a/related_programs",
        params=[("ref_kind", "authority")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert body["results"]
    assert all(row["ref_kind"] == "authority" for row in body["results"])
    assert any(
        row["program_unified_id"] == "UNI-test-s-1" and row["law_unified_id"] == "LAW-aaaaa01a0a"
        for row in body["results"]
    )


def test_law_related_programs_404(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get("/v1/laws/LAW-not-real/related_programs")
    assert r.status_code == 404, r.text
    assert "LAW-not-real" in r.json()["detail"]


def test_law_related_programs_invalid_ref_kind(cross_ref_client: TestClient) -> None:
    r = cross_ref_client.get(
        "/v1/laws/LAW-aaaaa01a0a/related_programs",
        params=[("ref_kind", "bogus")],
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Tests — /v1/cases/by_industry_size_pref
# ---------------------------------------------------------------------------


def test_cases_by_industry_size_pref_three_axis_intersection(
    cross_ref_client: TestClient,
) -> None:
    r = cross_ref_client.get(
        "/v1/cases/by_industry_size_pref",
        params=[
            ("industry_jsic", "245"),
            ("prefecture", "東京都"),
            ("min_employees", "10"),
            ("max_employees", "100"),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # CS-pf-001 (employees 25, JSIC 2451, 東京都) qualifies; CS-pf-002 (employees 3) is excluded by employee floor.
    case_ids = {c["case_id"] for c in body["results"]}
    assert "CS-pf-001" in case_ids
    assert "CS-pf-002" not in case_ids
    assert body["filters"]["industry_jsic"] == "245"


def test_cases_by_industry_size_pref_sole_proprietor_filter(
    cross_ref_client: TestClient,
) -> None:
    r = cross_ref_client.get(
        "/v1/cases/by_industry_size_pref",
        params=[("is_sole_proprietor", "true")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Only CS-pf-002 carries is_sole_proprietor=1.
    case_ids = {c["case_id"] for c in body["results"]}
    assert "CS-pf-002" in case_ids
    for case in body["results"]:
        assert case["is_sole_proprietor"] is True


def test_cases_by_industry_size_pref_capital_band(
    cross_ref_client: TestClient,
) -> None:
    r = cross_ref_client.get(
        "/v1/cases/by_industry_size_pref",
        params=[
            ("min_capital_yen", "5000000"),
            ("max_capital_yen", "50000000"),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # CS-pf-001 (30M) and CS-pf-003 (10M) pass; CS-pf-002 (3M) is excluded.
    case_ids = {c["case_id"] for c in body["results"]}
    assert "CS-pf-001" in case_ids
    assert "CS-pf-003" in case_ids
    assert "CS-pf-002" not in case_ids


def test_cases_by_industry_size_pref_invalid_band_returns_422(
    cross_ref_client: TestClient,
) -> None:
    r = cross_ref_client.get(
        "/v1/cases/by_industry_size_pref",
        params=[("min_employees", "100"), ("max_employees", "10")],
    )
    assert r.status_code == 422, r.text
    assert "min_employees" in r.json()["detail"]


def test_cases_by_industry_size_pref_billing_envelope(
    cross_ref_client: TestClient,
) -> None:
    r = cross_ref_client.get(
        "/v1/cases/by_industry_size_pref",
        params=[("limit", "1")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_billing_unit"] == 1
    assert isinstance(body["_disclaimer"], str)
    assert "corpus_snapshot_id" in body
