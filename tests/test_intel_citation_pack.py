"""Tests for GET /v1/intel/citation_pack/{program_id}.

Covers four contracts (Wave 31-9 spec):

1. **Markdown happy path** — known program_id returns markdown_text +
   byte_size + citation_count + sections list, footnote-style markers
   present (`^[N]`), envelope disclaimer + corpus_snapshot_id present.
2. **JSON happy path** — `?format=json` returns a flat citations[] list
   with the kind / id / title / url / snippet / anchor_id /
   last_verified_at fields; section grouping mirrored in `sections`.
3. **citation_count cap** — `?max_citations=5` enforces the cap.
4. **404** — unknown program_id returns a structured detail (not 500).

The fixture seeds extra programs + program_law_refs / law / hanrei /
enforcement / adoption rows so the assertions have data to walk against.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


def _augment_db_for_citation_pack(seeded_db: Path) -> None:
    """Seed the jpintel.db side with extra rows the citation pack reads."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        # Add source_url to programs if missing so the pack can surface it.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(programs)")}
        if "source_url" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN source_url TEXT")

        now = datetime.now(UTC).isoformat()

        # Seed a fresh program we own end-to-end for this test surface.
        conn.execute(
            "INSERT OR IGNORE INTO programs("
            "  unified_id, primary_name, aliases_json, "
            "  authority_level, authority_name, prefecture, municipality, "
            "  program_kind, official_url, "
            "  amount_max_man_yen, amount_min_man_yen, subsidy_rate, "
            "  trust_level, tier, coverage_score, gap_to_tier_s_json, "
            "  a_to_j_coverage_json, excluded, exclusion_reason, "
            "  crop_categories_json, equipment_category, "
            "  target_types_json, funding_purpose_json, "
            "  amount_band, application_window_json, "
            "  enriched_json, source_mentions_json, updated_at, "
            "  source_url"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "UNI-cit-pack-1",
                "建設業 DX 推進補助金 — 設備投資支援",
                None,
                "国",
                "経済産業省",
                "全国",
                None,
                "補助金",
                "https://example.gov/citpack",
                3000,
                None,
                None,
                None,
                "S",
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                json.dumps(["corporation"], ensure_ascii=False),
                json.dumps(["設備投資"], ensure_ascii=False),
                None,
                None,
                None,
                None,
                now,
                "https://example.gov/citpack",
            ),
        )

        # Seed a couple of laws and a program_law_ref so the law section
        # has guaranteed content.
        conn.execute(
            "INSERT OR IGNORE INTO laws("
            "  unified_id, law_number, law_title, law_short_title, law_type, "
            "  ministry, promulgated_date, enforced_date, last_amended_date, "
            "  revision_status, superseded_by_law_id, article_count, "
            "  full_text_url, summary, subject_areas_json, source_url, "
            "  source_checksum, confidence, fetched_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "LAW-citpack001",
                "昭和49年法律第84号",
                "建設業法",
                "建設業法",
                "act",
                "mlit",
                "1949-05-24",
                "1949-05-24",
                None,
                "current",
                None,
                100,
                "https://elaws.e-gov.go.jp/document?lawid=349AC0000000100",
                "建設業の許可と規制に関する法律",
                json.dumps(["construction"]),
                "https://elaws.e-gov.go.jp/document?lawid=349AC0000000100",
                None,
                0.95,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO program_law_refs("
            "  program_unified_id, law_unified_id, ref_kind, "
            "  article_citation, source_url, fetched_at, confidence"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                "UNI-cit-pack-1",
                "LAW-citpack001",
                "authority",
                "第3条",
                "https://example.gov/citpack/refs",
                now,
                0.9,
            ),
        )

        # Court decision linked via related_law_ids_json + name token match.
        court_cols = {row["name"] for row in conn.execute("PRAGMA table_info(court_decisions)")}
        if court_cols:
            conn.execute(
                "INSERT OR IGNORE INTO court_decisions("
                "  unified_id, case_name, case_number, court, court_level, "
                "  decision_date, decision_type, subject_area, "
                "  related_law_ids_json, key_ruling, parties_involved, "
                "  impact_on_business, precedent_weight, full_text_url, "
                "  pdf_url, source_url, source_excerpt, source_checksum, "
                "  confidence, fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "HAN-citpack01",
                    "建設業法違反事件",
                    "令和5年(行ヒ)第1号",
                    "最高裁判所第三小法廷",
                    "supreme",
                    "2025-03-15",
                    "判決",
                    "行政",
                    json.dumps(["LAW-citpack001"]),
                    "建設業 DX における補助金交付の解釈について示した判決",
                    "X 株式会社",
                    "建設業 DX 推進実務に直接影響",
                    "binding",
                    "https://www.courts.go.jp/example/citpack01",
                    "https://www.courts.go.jp/example/citpack01.pdf",
                    "https://www.courts.go.jp/example/citpack01",
                    None,
                    None,
                    0.95,
                    now,
                    now,
                ),
            )

        # Enforcement case keyed by program_name_hint substring.
        enforce_cols = {row["name"] for row in conn.execute("PRAGMA table_info(enforcement_cases)")}
        if enforce_cols:
            conn.execute(
                "INSERT OR IGNORE INTO enforcement_cases("
                "  case_id, event_type, program_name_hint, "
                "  recipient_name, recipient_kind, recipient_houjin_bangou, "
                "  is_sole_proprietor, bureau, intermediate_recipient, "
                "  prefecture, ministry, occurred_fiscal_years_json, "
                "  amount_yen, amount_project_cost_yen, amount_grant_paid_yen, "
                "  amount_improper_grant_yen, amount_improper_project_cost_yen, "
                "  reason_excerpt, legal_basis, source_url, source_section, "
                "  source_title, disclosed_date, disclosed_until, fetched_at, "
                "  confidence"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "enforce-citpack-01",
                    "返還命令",
                    "建設業 DX 推進補助金",
                    "Z 株式会社",
                    "houjin",
                    "1234567890123",
                    0,
                    "経産局",
                    None,
                    "東京都",
                    "経済産業省",
                    json.dumps([2023]),
                    5_000_000,
                    30_000_000,
                    25_000_000,
                    5_000_000,
                    6_000_000,
                    "実績報告書類の不備",
                    "補助金適正化法 第18条",
                    "https://example.gov/enforce/citpack01",
                    "返還命令一覧",
                    "令和6年度 返還命令公表",
                    "2024-12-15",
                    None,
                    now,
                    0.9,
                ),
            )

        # Adoption record. Canonical column is `program_name_raw`; the
        # citation pack also tolerates a legacy `program_name` column when
        # present.
        adoption_cols = {row["name"] for row in conn.execute("PRAGMA table_info(adoption_records)")}
        if "program_name_raw" in adoption_cols:
            conn.execute(
                "INSERT OR IGNORE INTO adoption_records("
                "  houjin_bangou, program_name_raw, company_name_raw, "
                "  prefecture, industry_jsic_medium, amount_granted_yen, "
                "  announced_at, source_url, fetched_at, confidence"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "9876543210987",
                    "建設業 DX 推進補助金 — 設備投資支援",
                    "Y 株式会社",
                    "東京都",
                    "D06",
                    25_000_000,
                    "2024-08-15",
                    "https://example.gov/adoption/citpack01",
                    now,
                    0.9,
                ),
            )

        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def citation_client(seeded_db: Path) -> TestClient:
    """TestClient backed by the shared seeded_db plus citation-pack seeds."""
    _augment_db_for_citation_pack(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_citation_pack_markdown_happy_path(citation_client: TestClient) -> None:
    """Markdown format returns body with citations and footnote markers."""
    r = citation_client.get(
        "/v1/intel/citation_pack/UNI-cit-pack-1",
        params={"format": "markdown", "max_citations": 30, "citation_style": "footnote"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["format"] == "markdown"
    assert body["citation_style"] == "footnote"
    assert isinstance(body["markdown_text"], str)
    assert isinstance(body["byte_size"], int)
    assert body["byte_size"] > 0
    assert body["byte_size"] == len(body["markdown_text"].encode("utf-8"))
    assert isinstance(body["sections"], list)

    # Envelope invariants
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body

    # Program echo
    assert body["program"]["program_id"] == "UNI-cit-pack-1"
    assert "建設業" in body["program"]["primary_name"]

    # Markdown body shape
    md = body["markdown_text"]
    assert md.startswith("# ")
    assert "出典 pack" in md
    assert "## 1. 法令根拠" in md
    # Footnote marker present (^[N]) anywhere in the body.
    assert "^[1]" in md, "expected footnote marker ^[1] in markdown body"
    # Footnote definition table emitted.
    assert "[^1]:" in md
    # Source license summary line present at the bottom.
    assert "**Source license**:" in md
    # Generated-at line carries the snapshot id.
    assert body["corpus_snapshot_id"] in md

    # Attribution block
    attribution = body["attribution"]
    assert "license" in attribution
    assert "source_disclaimer" in attribution
    # 建設業 keyword should trigger the business-law sensitive disclaimer.
    assert attribution["sensitive_disclaimer"] is not None
    assert "業法" in attribution["sensitive_disclaimer"]

    # Citation count is non-zero (we seeded at least 1 law).
    assert body["citation_count"] >= 1


def test_citation_pack_json_format_envelope(citation_client: TestClient) -> None:
    """JSON format returns a flat citations[] with the documented schema."""
    r = citation_client.get(
        "/v1/intel/citation_pack/UNI-cit-pack-1",
        params={"format": "json", "max_citations": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["format"] == "json"
    assert "markdown_text" not in body
    assert isinstance(body["citations"], list)
    assert body["citation_count"] == len(body["citations"])
    assert body["citation_count"] >= 1

    expected_keys = {
        "kind",
        "id",
        "title",
        "url",
        "snippet",
        "anchor_id",
        "last_verified_at",
    }
    valid_kinds = {
        "law",
        "tsutatsu",
        "kessai",
        "hanrei",
        "gyosei_shobun",
        "adoption",
    }
    for c in body["citations"]:
        missing = expected_keys - set(c.keys())
        assert not missing, f"citation missing keys: {sorted(missing)}"
        assert c["kind"] in valid_kinds
        assert c["anchor_id"], "anchor_id must be non-empty"

    # At least one law citation surfaces from the seed data.
    kinds = [c["kind"] for c in body["citations"]]
    assert "law" in kinds


def test_citation_pack_max_citations_cap(citation_client: TestClient) -> None:
    """citation_count must never exceed max_citations."""
    r = citation_client.get(
        "/v1/intel/citation_pack/UNI-cit-pack-1",
        params={"format": "json", "max_citations": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["citation_count"] <= 5
    assert len(body["citations"]) <= 5


def test_citation_pack_unknown_program_id_404(citation_client: TestClient) -> None:
    """Unknown program_id returns a structured 404, not a 500."""
    r = citation_client.get("/v1/intel/citation_pack/UNI-does-not-exist")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "program_not_found"
    assert detail["field"] == "program_id"


def test_citation_pack_paid_final_cap_failure_returns_503_without_usage_event(
    citation_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final cap rejection must fail closed, not return unmetered 200."""
    key_hash = hash_api_key(paid_key)
    endpoint = "intel.citation_pack"

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    import jpintel_mcp.api.deps as deps

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    r = citation_client.get(
        "/v1/intel/citation_pack/UNI-cit-pack-1",
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()
    assert after == before


def test_citation_pack_footnote_marker_count_matches_citation_count(
    citation_client: TestClient,
) -> None:
    """Every citation in markdown footnote mode gets a ^[N] marker AND a [^N]: definition."""
    r = citation_client.get(
        "/v1/intel/citation_pack/UNI-cit-pack-1",
        params={"format": "markdown", "citation_style": "footnote"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    md = body["markdown_text"]
    expected = int(body["citation_count"])
    # Count ^[N] inline markers + [^N]: footnote definitions.
    inline_markers = sum(1 for n in range(1, expected + 1) if f"^[{n}]" in md)
    fn_defs = sum(1 for n in range(1, expected + 1) if f"[^{n}]:" in md)
    assert inline_markers == expected
    assert fn_defs == expected
