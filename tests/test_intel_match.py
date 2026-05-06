"""Tests for POST /v1/intel/match — smart matchmaking endpoint.

Covers three contracts:

1. Happy path — returns matched_programs with the expected envelope keys
   (match_score / required_documents / similar_adopted_companies /
   applicable_laws / applicable_tsutatsu / audit_proof + the standard
   _disclaimer / _billing_unit / corpus_snapshot_id wrapper).
2. Validation — invalid prefecture_code / industry_jsic_major both 422.
3. Filter narrowing — a keyword that matches one fixture program returns
   a higher-scored hit than a keyword that matches nothing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path


def _augment_programs_for_match(seeded_db: Path) -> None:
    """Add columns the match endpoint introspects for + seed extra rows.

    The shared `seeded_db` fixture only runs `init_db` (schema.sql) which
    pre-dates migrations 148/167. Add the columns we depend on, then seed
    a handful of programs that exercise the matchmaking ranker.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(programs)")}
        if "jsic_majors" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN jsic_majors TEXT")
        if "jsic_major" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN jsic_major TEXT")
        if "verification_count" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN verification_count INTEGER DEFAULT 0")
        if "audit_quarantined" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN audit_quarantined INTEGER DEFAULT 0")
        if "source_url" not in existing_cols:
            conn.execute("ALTER TABLE programs ADD COLUMN source_url TEXT")

        # Backfill jsic_majors / verification_count for the original rows
        # so the matchmaking SELECT can locate them.
        conn.execute(
            "UPDATE programs SET jsic_majors = ?, verification_count = 1, "
            "source_url = 'https://example.gov/s1' "
            "WHERE unified_id = 'UNI-test-s-1'",
            (json.dumps(["E"]),),
        )

        now = datetime.now(UTC).isoformat()
        # Seed 3 manufacturing (E) programs in 東京都 with varying tier /
        # verification_count + 1 keyword-bearing program for the keyword test.
        seeds = [
            (
                "UNI-match-s-tokyo-1",
                "東京都製造業 DX 推進補助金",
                "S",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                3000,
                json.dumps(["E"]),
                3,
                "https://example.tokyo/s1",
            ),
            (
                "UNI-match-a-tokyo-1",
                "東京都ものづくり高度化助成事業",
                "A",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                2000,
                json.dumps(["E"]),
                2,
                "https://example.tokyo/a1",
            ),
            (
                "UNI-match-b-tokyo-1",
                "中小企業設備投資 B プログラム",
                "B",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                500,
                json.dumps(["E"]),
                1,
                "https://example.tokyo/b1",
            ),
            (
                "UNI-match-c-national-1",
                "全国対応 製造業 ものづくり 中小企業向け補助金",
                "C",
                "全国",
                "国",
                "経済産業省",
                "補助金",
                1500,
                json.dumps(["E"]),
                0,
                "https://example.go/c1",
            ),
            (
                "UNI-match-other-pref-1",
                "大阪府ものづくり助成事業",
                "A",
                "大阪府",
                "都道府県",
                "大阪府",
                "補助金",
                1000,
                json.dumps(["E"]),
                2,
                "https://example.osaka/a1",
            ),
            (
                "UNI-match-quarantined-1",
                "DX 隔離テスト補助金 — should be excluded",
                "A",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                100,
                json.dumps(["E"]),
                1,
                "https://example.bad/q1",
            ),
        ]
        for s in seeds:
            (
                uid,
                name,
                tier,
                pref,
                lvl,
                authority,
                kind,
                amax,
                jsicm,
                vcount,
                url,
            ) = s
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
                "  source_url, jsic_majors, verification_count, audit_quarantined"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    name,
                    None,
                    lvl,
                    authority,
                    pref,
                    None,
                    kind,
                    url,
                    amax,
                    None,
                    None,
                    None,
                    tier,
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
                    url,
                    jsicm,
                    vcount,
                    1 if "quarantined" in uid else 0,
                ),
            )
            # programs_fts is not UNIQUE-constrained; use a guard read.
            existing_fts = conn.execute(
                "SELECT 1 FROM programs_fts WHERE unified_id = ? LIMIT 1",
                (uid,),
            ).fetchone()
            if not existing_fts:
                conn.execute(
                    "INSERT INTO programs_fts("
                    "  unified_id, primary_name, aliases, enriched_text"
                    ") VALUES (?,?,?,?)",
                    (uid, name, "", name),
                )

        documents = [
            (
                "東京都製造業 DX 推進補助金",
                "交付申請書",
                "required",
                "pdf",
                "https://example.tokyo/forms/s1-application.pdf",
                1,
            ),
            (
                "東京都製造業 DX 推進補助金",
                "登記事項証明書",
                "required",
                "pdf",
                "",
                0,
            ),
        ]
        for doc in documents:
            conn.execute(
                "INSERT OR IGNORE INTO program_documents("
                "  program_name, form_name, form_type, form_format, "
                "  form_url_direct, signature_required"
                ") VALUES (?,?,?,?,?,?)",
                doc,
            )

        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def match_client(seeded_db: Path) -> TestClient:
    """TestClient backed by the shared seeded_db plus match-specific seeds."""
    _augment_programs_for_match(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_intel_match_happy_path_returns_envelope(match_client: TestClient) -> None:
    """E + 13 (東京都) + DX keyword + cap-50M returns at least 1 hit
    with the full composite envelope shape."""
    payload = {
        "industry_jsic_major": "E",
        "prefecture_code": "13",
        "capital_jpy": 50_000_000,
        "employee_count": 50,
        "keyword": "DX",
        "limit": 5,
    }
    r = match_client.post("/v1/intel/match", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert "matched_programs" in body
    matched = body["matched_programs"]
    assert isinstance(matched, list)
    assert len(matched) >= 1
    # Envelope-level invariants.
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body and body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert body["applied_filters"]
    assert "tier_in_SABC" in body["applied_filters"]
    assert "audit_quarantined=0" in body["applied_filters"]
    assert "prefecture_or_national" in body["applied_filters"]
    assert "keyword_like" in body["applied_filters"]

    # Per-record envelope shape.
    top = matched[0]
    expected_keys = {
        "program_id",
        "primary_name",
        "tier",
        "match_score",
        "score_components",
        "authority_name",
        "prefecture",
        "program_kind",
        "source_url",
        "eligibility_predicate",
        "required_documents",
        "next_questions",
        "eligibility_gaps",
        "document_readiness",
        "similar_adopted_companies",
        "applicable_laws",
        "applicable_tsutatsu",
        "audit_proof",
    }
    missing = expected_keys - set(top.keys())
    assert not missing, f"top record missing keys: {sorted(missing)}"
    assert 0.0 <= float(top["match_score"]) <= 1.0
    # Audit-proof block is always present (merkle_root may be null when
    # the cron has not yet anchored).
    assert set(top["audit_proof"].keys()) >= {"merkle_root", "ots_url"}
    # Quarantined program must NOT appear.
    program_ids = {m["program_id"] for m in matched}
    assert "UNI-match-quarantined-1" not in program_ids
    # Eligibility predicate must surface the structured columns.
    pred = top["eligibility_predicate"]
    assert "amount_max_man_yen" in pred
    assert "target_types" in pred
    assert "funding_purpose" in pred
    assert "industry_jsic_majors" in pred

    assert isinstance(top["next_questions"], list)
    assert isinstance(top["eligibility_gaps"], list)
    readiness = top["document_readiness"]
    assert readiness["required_document_count"] == 2
    assert readiness["forms_with_url_count"] == 1
    assert readiness["signature_required_count"] == 1
    assert readiness["needs_user_confirmation"] is True
    doc_question_fields = {q["field"] for q in top["next_questions"]}
    assert "required_documents[0].user_confirmation" in doc_question_fields


def test_intel_match_validation_invalid_prefecture_and_jsic(
    match_client: TestClient,
) -> None:
    """Bad prefecture_code and bad industry_jsic_major both 422."""
    bad_pref = match_client.post(
        "/v1/intel/match",
        json={
            "industry_jsic_major": "E",
            "prefecture_code": "99",
            "limit": 3,
        },
    )
    assert bad_pref.status_code == 422
    detail = bad_pref.json()["detail"]
    assert detail["error"] == "invalid_prefecture_code"

    bad_jsic = match_client.post(
        "/v1/intel/match",
        json={
            "industry_jsic_major": "Z",
            "prefecture_code": "13",
            "limit": 3,
        },
    )
    assert bad_jsic.status_code == 422
    detail2 = bad_jsic.json()["detail"]
    assert detail2["error"] == "invalid_jsic_major"


def test_intel_match_keyword_narrows_and_ranks(match_client: TestClient) -> None:
    """A keyword that matches one fixture program ranks it #1; an empty
    keyword returns a wider candidate pool ordered by tier weight."""
    # Keyword present → the only DX-bearing fixture row should be #1.
    with_kw = match_client.post(
        "/v1/intel/match",
        json={
            "industry_jsic_major": "E",
            "prefecture_code": "13",
            "keyword": "DX",
            "limit": 5,
        },
    )
    assert with_kw.status_code == 200, with_kw.text
    body_kw = with_kw.json()
    matched_kw = body_kw["matched_programs"]
    assert matched_kw, "expected at least one DX-keyword match"
    assert matched_kw[0]["program_id"] == "UNI-match-s-tokyo-1"
    # match_score on the leader is normalised to 1.0.
    assert matched_kw[0]["match_score"] == pytest.approx(1.0, abs=0.01)

    # No keyword → candidate pool widens (national rows now included via
    # prefecture_or_national filter), and S tier still leads.
    without_kw = match_client.post(
        "/v1/intel/match",
        json={
            "industry_jsic_major": "E",
            "prefecture_code": "13",
            "limit": 5,
        },
    )
    assert without_kw.status_code == 200, without_kw.text
    body_nokw = without_kw.json()
    matched_nokw = body_nokw["matched_programs"]
    assert matched_nokw, "no-keyword query should still return programs"
    # S tier dominates rank 0.
    assert matched_nokw[0]["tier"] == "S"
    # Total candidates without keyword should be >= total with keyword
    # (same WHERE minus the LIKE).
    assert body_nokw["total_candidates"] >= body_kw["total_candidates"]
    # Other-prefecture row must NOT appear (different prefecture, not national).
    program_ids = {m["program_id"] for m in matched_nokw}
    assert "UNI-match-other-pref-1" not in program_ids
    # National row IS allowed in the no-keyword pool.
    assert "UNI-match-c-national-1" in program_ids


def test_intel_match_returns_next_questions_for_missing_inputs(
    match_client: TestClient,
) -> None:
    r = match_client.post(
        "/v1/intel/match",
        json={
            "industry_jsic_major": "E",
            "prefecture_code": "13",
            "keyword": "DX",
            "limit": 1,
        },
    )
    assert r.status_code == 200, r.text
    top = r.json()["matched_programs"][0]

    question_fields = {q["field"] for q in top["next_questions"]}
    assert "employee_count" in question_fields
    assert "capital_jpy" in question_fields
    assert "entity_type" in question_fields
    assert "funding_purpose" in question_fields

    gap_fields = {g["field"] for g in top["eligibility_gaps"]}
    assert {"employee_count", "capital_jpy", "entity_type"}.issubset(gap_fields)
    assert top["document_readiness"]["needs_user_confirmation"] is True


def test_intel_match_paid_final_cap_failure_returns_503_without_usage_event(
    match_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "intel.match"),
            ).fetchone()
            return int(n)
        finally:
            conn.close()

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    before_usage = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = match_client.post(
        "/v1/intel/match",
        headers={"X-API-Key": paid_key},
        json={
            "industry_jsic_major": "E",
            "prefecture_code": "13",
            "capital_jpy": 50_000_000,
            "employee_count": 50,
            "keyword": "DX",
            "limit": 5,
        },
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before_usage
