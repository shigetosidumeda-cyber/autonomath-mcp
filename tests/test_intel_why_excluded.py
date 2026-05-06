"""Tests for POST /v1/intel/why_excluded — eligibility-failure reasoning.

Covers three contracts:

1. All predicates pass (eligible=true) — happy houjin matches every axis.
2. Single predicate fails (blocking + remediation) — capital cap exceeded.
3. Multiple predicates fail (alternative_programs surfaced) — wrong
   prefecture + wrong industry, with am_recommended_programs alts.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixture — a tmp autonomath.db with predicate JSON + houjin facts +
# am_recommended_programs alts wired up.
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_why_excluded_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> Path:
    """Build a self-contained autonomath.db slice for /v1/intel/why_excluded.

    Seeds three programs:
      * UNI-WX-OK         : E (製造業) / 東京都 / capital ≤ 100M / employees ≤ 100
      * UNI-WX-CAP-FAIL   : E / 東京都 / capital ≤ 5M (the test houjin has 50M)
      * UNI-WX-MULTI-FAIL : K (不動産) / 大阪府 / capital ≤ 100M

    Plus one houjin (T9999999999991) with corp.* facts + 1
    am_recommended_programs row pointing at UNI-WX-ALT-1 so the
    multi-fail test gets at least one alternative.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_program_eligibility_predicate_json (
            program_id                        TEXT PRIMARY KEY,
            predicate_json                    TEXT NOT NULL,
            extraction_method                 TEXT NOT NULL DEFAULT 'rule_based',
            confidence                        REAL,
            extracted_at                      TEXT NOT NULL DEFAULT (datetime('now')),
            source_program_corpus_snapshot_id TEXT
        );
        CREATE TABLE jpi_programs (
            unified_id      TEXT PRIMARY KEY,
            primary_name    TEXT,
            prefecture      TEXT,
            program_kind    TEXT,
            authority_name  TEXT,
            source_url      TEXT
        );
        CREATE TABLE am_entities (
            canonical_id    TEXT PRIMARY KEY,
            primary_name    TEXT,
            record_kind     TEXT,
            source_url      TEXT,
            fetched_at      TEXT,
            confidence      REAL
        );
        CREATE TABLE am_entity_facts (
            entity_id            TEXT NOT NULL,
            field_name           TEXT NOT NULL,
            field_value_text     TEXT,
            field_value_numeric  REAL,
            unit                 TEXT,
            field_kind           TEXT
        );
        CREATE TABLE am_recommended_programs (
            houjin_bangou      TEXT NOT NULL,
            program_unified_id TEXT NOT NULL,
            rank               INTEGER NOT NULL,
            score              REAL NOT NULL,
            reason_json        TEXT,
            computed_at        TEXT,
            source_snapshot_id TEXT,
            PRIMARY KEY (houjin_bangou, program_unified_id)
        );
        """
    )

    # Predicates (the heart of this test surface).
    predicates = [
        (
            "UNI-WX-OK",
            json.dumps(
                {
                    "industries_jsic": ["E"],
                    "prefectures": ["東京都"],
                    "prefecture_jis": ["13"],
                    "capital_max_yen": 100_000_000,
                    "employee_max": 100,
                    "target_entity_types": ["corporation"],
                },
                ensure_ascii=False,
            ),
        ),
        (
            "UNI-WX-CAP-FAIL",
            json.dumps(
                {
                    "industries_jsic": ["E"],
                    "prefectures": ["東京都"],
                    "capital_max_yen": 5_000_000,
                    "target_entity_types": ["corporation"],
                },
                ensure_ascii=False,
            ),
        ),
        (
            "UNI-WX-MULTI-FAIL",
            json.dumps(
                {
                    "industries_jsic": ["K"],
                    "prefectures": ["大阪府"],
                    "prefecture_jis": ["27"],
                    "capital_max_yen": 100_000_000,
                    "target_entity_types": ["corporation"],
                },
                ensure_ascii=False,
            ),
        ),
    ]
    conn.executemany(
        "INSERT INTO am_program_eligibility_predicate_json "
        "(program_id, predicate_json, extraction_method, confidence) "
        "VALUES (?, ?, 'rule_based', 0.85)",
        predicates,
    )

    # jpi_programs metadata so program_name + source_url surface.
    programs = [
        (
            "UNI-WX-OK",
            "テスト製造業 DX 補助金 (OK)",
            "東京都",
            "補助金",
            "経産省",
            "https://example.gov/ok",
        ),
        (
            "UNI-WX-CAP-FAIL",
            "テスト小規模事業者 持続化補助金",
            "東京都",
            "補助金",
            "中企庁",
            "https://example.gov/cap",
        ),
        (
            "UNI-WX-MULTI-FAIL",
            "大阪府不動産活性化補助金",
            "大阪府",
            "補助金",
            "大阪府",
            "https://example.osaka/multi",
        ),
        (
            "UNI-WX-ALT-1",
            "代替候補 製造業向け融資",
            "東京都",
            "融資",
            "公庫",
            "https://example.gov/alt1",
        ),
        (
            "UNI-WX-ALT-2",
            "代替候補 IT導入補助金",
            "東京都",
            "補助金",
            "中企庁",
            "https://example.gov/alt2",
        ),
    ]
    conn.executemany(
        "INSERT INTO jpi_programs "
        "(unified_id, primary_name, prefecture, program_kind, authority_name, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        programs,
    )

    # houjin facts for T9999999999991 — 50M capital, 30 employees,
    # JSIC E (製造業), 東京都, founded 2010.
    bangou = "9999999999991"
    canonical = f"houjin:{bangou}"
    conn.execute(
        "INSERT INTO am_entities (canonical_id, primary_name, record_kind) VALUES (?, ?, ?)",
        (canonical, "テスト株式会社", "corporate_entity"),
    )
    conn.executemany(
        "INSERT INTO am_entity_facts "
        "(entity_id, field_name, field_value_text, field_value_numeric, unit, field_kind) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (canonical, "corp.capital_amount", None, 50_000_000.0, "JPY", "numeric"),
            (canonical, "corp.employee_count", None, 30.0, "person", "numeric"),
            (canonical, "corp.jsic_major", "E", None, None, "text"),
            (canonical, "corp.industry_raw", "製造業", None, None, "text"),
            (canonical, "corp.prefecture", "東京都", None, None, "text"),
            (canonical, "corp.date_of_establishment", "2010-04-01", None, None, "text"),
        ],
    )

    # Alternative recommendations for the multi-fail case.
    conn.executemany(
        "INSERT INTO am_recommended_programs "
        "(houjin_bangou, program_unified_id, rank, score, reason_json, computed_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        [
            (
                bangou,
                "UNI-WX-ALT-1",
                1,
                0.91,
                json.dumps({"match": "industry"}),
            ),
            (
                bangou,
                "UNI-WX-ALT-2",
                2,
                0.78,
                json.dumps({"match": "prefecture"}),
            ),
        ],
    )

    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


@pytest.fixture()
def why_excluded_client(seeded_db: Path, seeded_why_excluded_db: Path) -> TestClient:
    """TestClient backed by the shared seeded_db + the why_excluded autonomath slice."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_why_excluded_all_predicates_pass(why_excluded_client: TestClient) -> None:
    """A houjin that satisfies every axis returns eligible=True with NO failed
    predicates and NO remediation steps."""
    payload = {
        "program_id": "UNI-WX-OK",
        "houjin": {
            "id": "T9999999999991",
            # explicit attrs win over hydrated facts; supplied identically
            # to keep the test deterministic.
            "capital": 50_000_000,
            "employees": 30,
            "jsic": "E",
            "prefecture": "東京都",
            "founded_year": 2010,
        },
    }
    r = why_excluded_client.post("/v1/intel/why_excluded", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["eligible"] is True
    assert body["program_id"] == "UNI-WX-OK"
    assert body["program_name"] == "テスト製造業 DX 補助金 (OK)"
    assert body["match_score"] == 1.0
    pe = body["predicate_evaluation"]
    assert pe["evaluated_axes"] >= 4
    assert pe["blocking_failures"] == 0
    assert pe["failed"] == []
    assert len(pe["passed"]) == pe["evaluated_axes"]
    # No failed -> no remediation either.
    assert body["remediation_steps"] == []
    assert body["alternative_programs"] == []
    # Envelope fence.
    assert body["_billing_unit"] == 1
    assert "行政書士法 §1" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body


def test_why_excluded_single_predicate_fail_blocking_with_remediation(
    why_excluded_client: TestClient,
) -> None:
    """capital_max=5M but the houjin has 50M → blocking=True + remediation
    step appended for the capital_max_yen axis."""
    payload = {
        "program_id": "UNI-WX-CAP-FAIL",
        "houjin": {
            "id": "T9999999999991",
            "capital": 50_000_000,
            "employees": 30,
            "jsic": "E",
            "prefecture": "東京都",
        },
    }
    r = why_excluded_client.post("/v1/intel/why_excluded", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["eligible"] is False
    pe = body["predicate_evaluation"]
    assert pe["blocking_failures"] >= 1
    failed_axes = [f["predicate"] for f in pe["failed"]]
    assert "capital_max_yen" in failed_axes
    cap_failure = next(f for f in pe["failed"] if f["predicate"] == "capital_max_yen")
    assert cap_failure["blocking"] is True
    assert cap_failure["expected"] == 5_000_000
    assert float(cap_failure["actual"]) == 50_000_000.0
    assert cap_failure["remediation"] is not None
    assert "減資" in cap_failure["remediation"]

    # remediation_steps must include the capital reduction step + verify.
    rem_kinds = [step["step"] for step in body["remediation_steps"]]
    assert any("減資" in s for s in rem_kinds)
    assert any("公募要領" in s for s in rem_kinds)
    # difficulty enum + timeline integer present on every step.
    for step in body["remediation_steps"]:
        assert step["est_difficulty"] in {"easy", "med", "hard"}
        assert isinstance(step["est_timeline_days"], int) and step["est_timeline_days"] >= 1


def test_why_excluded_multiple_fails_surfaces_alternative_programs(
    why_excluded_client: TestClient,
) -> None:
    """Wrong industry + wrong prefecture → 2 blocking fails + alts from
    am_recommended_programs."""
    payload = {
        "program_id": "UNI-WX-MULTI-FAIL",
        "houjin": {
            "id": "T9999999999991",
            "capital": 50_000_000,
            "employees": 30,
            "jsic": "E",  # predicate expects K
            "prefecture": "東京都",  # predicate expects 大阪府
        },
    }
    r = why_excluded_client.post("/v1/intel/why_excluded", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["eligible"] is False
    pe = body["predicate_evaluation"]
    assert pe["blocking_failures"] >= 2
    failed_axes = {f["predicate"] for f in pe["failed"]}
    assert "industries_jsic" in failed_axes
    # `_evaluate_predicate` records the prefecture failure under whichever
    # key the predicate carries first; both should be recognised.
    assert ("prefectures" in failed_axes) or ("prefecture_jis" in failed_axes)

    # Alternatives surfaced from am_recommended_programs.
    alts = body["alternative_programs"]
    assert isinstance(alts, list)
    assert len(alts) >= 1
    alt_ids = {a["program_id"] for a in alts}
    assert "UNI-WX-ALT-1" in alt_ids
    top_alt = alts[0]
    assert "match_score" in top_alt
    assert 0.0 <= float(top_alt["match_score"]) <= 1.0
    assert top_alt["relax_reason"]
    # The excluded program itself must NOT appear in the alternatives.
    assert "UNI-WX-MULTI-FAIL" not in alt_ids

    # Per-failure remediation should be non-empty for at least one
    # blocking failure, and the global remediation_steps[] must include
    # the verify-primary-source fence.
    rem_steps = body["remediation_steps"]
    assert any("公募要領" in s["step"] for s in rem_steps)


def test_why_excluded_paid_final_cap_failure_returns_503_without_usage_event(
    why_excluded_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid final cap rejection must fail closed before delivering the 2xx body."""
    key_hash = hash_api_key(paid_key)
    endpoint = "intel.why_excluded"

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

    import jpintel_mcp.api.deps as deps

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = why_excluded_client.post(
        "/v1/intel/why_excluded",
        json={
            "program_id": "UNI-WX-OK",
            "houjin": {
                "id": "T9999999999991",
                "capital": 50_000_000,
                "employees": 30,
                "jsic": "E",
                "prefecture": "東京都",
                "founded_year": 2010,
            },
        },
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
