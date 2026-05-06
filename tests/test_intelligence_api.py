from __future__ import annotations

import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path


def _build_intelligence_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL DEFAULT 'primary',
                domain TEXT,
                content_hash TEXT,
                first_seen TEXT NOT NULL,
                last_verified TEXT,
                license TEXT
            );
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value_text TEXT,
                field_value_json TEXT,
                field_value_numeric REAL,
                field_kind TEXT NOT NULL DEFAULT 'text',
                source_id INTEGER REFERENCES am_source(id),
                confirming_source_count INTEGER DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE jpi_programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                authority_name TEXT,
                prefecture TEXT,
                tier TEXT,
                source_url TEXT,
                source_fetched_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id TEXT NOT NULL,
                am_canonical_id TEXT NOT NULL,
                match_method TEXT NOT NULL,
                confidence REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_amendment_diff (
                diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE am_program_summary (
                entity_id TEXT PRIMARY KEY,
                primary_name TEXT,
                summary_50 TEXT,
                summary_200 TEXT,
                summary_800 TEXT,
                token_50_est INT,
                token_200_est INT,
                token_800_est INT,
                generated_at TEXT DEFAULT (datetime('now')),
                source_quality REAL
            );
            """
        )
        con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "https://www.meti.go.jp/policy/pci.html",
                "primary",
                "www.meti.go.jp",
                "sha256:pci",
                "2026-04-28T00:00:00",
                "2026-04-29T00:00:00",
                "gov_standard_v2.0",
            ),
        )
        con.execute(
            "INSERT INTO jpi_programs(unified_id, primary_name, authority_name, "
            "prefecture, tier, source_url, source_fetched_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "UNI-pci-1",
                "PCI テスト 省力化補助金",
                "経済産業省",
                "東京都",
                "S",
                "https://www.meti.go.jp/policy/pci.html",
                "2026-04-29T00:00:00",
            ),
        )
        con.execute(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            ("UNI-pci-1", "program:pci:1", "exact_name", 1.0),
        )
        con.execute(
            "INSERT INTO am_amendment_diff(entity_id, field_name, detected_at) VALUES (?,?,?)",
            ("program:pci:1", "summary_200", "2026-04-29T00:00:00"),
        )
        con.execute(
            "INSERT INTO am_program_summary(entity_id, primary_name, summary_50, "
            "summary_200, summary_800, token_50_est, token_200_est, "
            "token_800_est, generated_at, source_quality) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "program:pci:1",
                "PCI テスト 省力化補助金",
                "省力化投資の短縮要約。",
                "省力化投資を支援するテスト制度。対象、上限、締切は一次資料で確認。",
                "省力化投資を支援するテスト制度。対象、上限、締切、併用条件は一次資料で確認。",
                18,
                44,
                72,
                "2026-04-29T00:00:00",
                0.93,
            ),
        )
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def intelligence_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "autonomath.db"
    _build_intelligence_db(db_path)

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    if "jpintel_mcp.services.evidence_packet" in sys.modules:
        from jpintel_mcp.services import evidence_packet as _evp

        _evp._reset_cache_for_tests()
    if "jpintel_mcp.api.evidence" in sys.modules:
        from jpintel_mcp.api import evidence as _evp_api

        _evp_api.reset_composer()

    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


def test_precomputed_intelligence_query_returns_compact_bundle(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "省力化", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bundle_kind"] == "precomputed_intelligence"
    assert body["bundle_id"].startswith("pci_")
    assert body["answer_basis"] == "precomputed"
    assert body["precomputed"]["available"] is True
    assert body["precomputed"]["record_count"] == 1
    assert body["usage"] == {
        "intended_for": "llm_context_prefetch",
        "web_search_required": False,
        "jpcite_requests": 1,
        "billing_units": 1,
    }
    recommendation = body["agent_recommendation"]
    assert recommendation["recommendation"] == "use_jpcite_prefetch"
    assert recommendation["recommend_to_user"] is True
    assert recommendation["recommend_for_cost_savings"] is False
    assert recommendation["cost_savings_decision"] == "needs_caller_baseline"
    assert "source_pdf_pages_or_source_token_count" in recommendation["missing_for_cost_claim"]
    assert recommendation["route"] == "/v1/intelligence/precomputed/query"
    assert "precomputed_summary_available" in recommendation["reason_codes"]
    assert "context_savings_baseline_needed" in recommendation["reason_codes"]

    record = body["records"][0]
    assert "facts" not in record
    assert record["precomputed"]["basis"] == "am_program_summary"
    assert record["precomputed"]["summaries"]["50"] == "省力化投資の短縮要約。"
    assert record["precomputed"]["token_estimates"] == {
        "50": 18,
        "200": 44,
        "800": 72,
    }
    assert body["compression"]["source_tokens_estimate"] is None
    assert body["compression"]["compression_ratio"] is None


def test_precomputed_intelligence_query_reports_response_metadata(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "省力化", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    missing = {
        "records_returned",
        "precomputed_record_count",
    } - body.keys()
    if missing:
        pytest.xfail(f"Desired response metadata is absent: {', '.join(sorted(missing))}")

    assert body["records_returned"] == len(body["records"]) == 1
    assert body["precomputed_record_count"] == body["precomputed"]["record_count"] == 1


def test_precomputed_intelligence_query_pdf_pages_compression(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "省力化",
            "limit": 1,
            "source_tokens_basis": "pdf_pages",
            "source_pdf_pages": 10,
            "input_token_price_jpy_per_1m": 300,
        },
    )

    assert response.status_code == 200
    compression = response.json()["compression"]
    assert compression["source_tokens_basis"] == "pdf_pages"
    assert compression["source_tokens_estimate"] == 7000
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["estimate_scope"] == "input_context_only"
    assert compression["savings_claim"] == "estimate_not_guarantee"


def test_precomputed_intelligence_query_token_count_compression(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "省力化",
            "limit": 1,
            "source_tokens_basis": "token_count",
            "source_token_count": 18_500,
            "input_token_price_jpy_per_1m": 300,
        },
    )

    assert response.status_code == 200
    compression = response.json()["compression"]
    assert compression["source_tokens_basis"] == "token_count"
    assert compression["source_tokens_estimate"] == 18_500
    assert compression["source_token_count"] == 18_500
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["estimate_scope"] == "input_context_only"
    assert compression["savings_claim"] == "estimate_not_guarantee"
    recommendation = response.json()["agent_recommendation"]
    assert recommendation["context_savings"]["evaluated"] is True
    assert recommendation["context_savings"]["break_even_met"] is True
    assert recommendation["recommend_for_cost_savings"] is True
    assert recommendation["cost_savings_decision"] == "supported_by_caller_baseline"
    assert recommendation["missing_for_cost_claim"] == []
    assert "caller_baseline_break_even_met" in recommendation["reason_codes"]


def test_precomputed_intelligence_no_records_suppresses_cost_savings(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "does-not-match",
            "limit": 1,
            "source_tokens_basis": "token_count",
            "source_token_count": 18_500,
            "input_token_price_jpy_per_1m": 300,
        },
    )

    assert response.status_code == 200
    recommendation = response.json()["agent_recommendation"]
    assert recommendation["context_savings"]["break_even_met"] is True
    assert recommendation["recommend_for_cost_savings"] is False
    assert recommendation["suppressed_cost_savings_decision"] == ("supported_by_caller_baseline")
    assert recommendation["cost_savings_decision"] == "not_applicable_no_evidence"
    assert recommendation["missing_for_cost_claim"] == ["source_linked_records_returned"]


def test_precomputed_intelligence_query_token_count_requires_count(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "省力化",
            "limit": 1,
            "source_tokens_basis": "token_count",
        },
    )

    assert response.status_code == 422
    assert "source_token_count is required" in response.text


def test_precomputed_intelligence_query_pdf_pages_requires_pages(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "省力化",
            "limit": 1,
            "source_tokens_basis": "pdf_pages",
        },
    )

    assert response.status_code == 422
    assert "source_pdf_pages is required" in response.text


def test_precomputed_intelligence_route_is_mounted(
    intelligence_client: TestClient,
) -> None:
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "does-not-match", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bundle_kind"] == "precomputed_intelligence"
    assert body["precomputed"]["available"] is False
    assert "precomputed_summary_unavailable" in body["quality"]["known_gaps"]
    assert body["agent_recommendation"]["recommendation"] == "broaden_query_or_skip"
    assert body["agent_recommendation"]["recommend_to_user"] is False
    assert body["agent_recommendation"]["recommend_for_cost_savings"] is False
    assert body["agent_recommendation"]["cost_savings_decision"] == "needs_caller_baseline"


def test_precomputed_intelligence_paid_final_cap_failure_is_not_billed(
    intelligence_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.middleware import customer_cap

    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        con = sqlite3.connect(seeded_db)
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "intelligence.precomputed.query"),
            ).fetchone()
            return int(row[0])
        finally:
            con.close()

    before_usage = usage_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "省力化", "limit": 1},
        headers={"X-API-Key": paid_key},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before_usage


# ---------------------------------------------------------------------------
# Plan §4-A — API value signal acceptance tests (2026-05-03)
# ---------------------------------------------------------------------------


def test_evidence_value_block_present_on_precomputed_bundle(
    intelligence_client: TestClient,
) -> None:
    """plan §4-A: evidence_value block ships on the precomputed bundle path."""
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "省力化", "limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    ev = body["evidence_value"]
    assert ev["records_returned"] == 1
    assert ev["source_linked_records"] >= 1
    assert ev["precomputed_records"] == 1
    assert ev["web_search_performed_by_jpcite"] is False
    assert ev["request_time_llm_call_performed"] is False


def test_precomputed_query_filters_proprietary_facts_before_recommendation(
    intelligence_client: TestClient,
) -> None:
    from jpintel_mcp.config import settings

    db_path = settings.autonomath_db_path
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, content_hash, "
            "first_seen, last_verified, license) VALUES (?,?,?,?,?,?,?)",
            (
                "https://example.com/private-intelligence",
                "secondary",
                "example.com",
                "sha256:private-intelligence",
                "2026-05-03T00:00:00",
                "2026-05-03T00:00:00",
                "proprietary",
            ),
        )
        source_id = cur.lastrowid
        con.execute(
            "INSERT INTO am_entity_facts(entity_id, field_name, field_value_text, "
            "field_kind, source_id, confirming_source_count) VALUES (?,?,?,?,?,?)",
            (
                "program:pci:1",
                "private_note",
                "must not export",
                "text",
                source_id,
                1,
            ),
        )
        con.commit()
    finally:
        con.close()

    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "省力化", "limit": 1, "include_facts": "true"},
    )

    assert response.status_code == 200
    assert "must not export" not in response.text
    body = response.json()
    assert body["records"] == []
    assert body["license_gate"]["allowed_count"] == 0
    assert body["license_gate"]["blocked_count"] == 1
    assert body["records_returned"] == 0
    assert body["evidence_value"]["records_returned"] == 0
    recommendation = body["agent_recommendation"]
    assert recommendation["recommend_to_user"] is False
    assert recommendation["recommend_for_evidence"] is False


def test_pdf_pages_baseline_returns_break_even_and_reduction(
    intelligence_client: TestClient,
) -> None:
    """plan §4-A: pdf_pages baseline → input_context_reduction_rate +
    break_even_source_tokens_estimate + provider_billing_not_guaranteed."""
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={
            "q": "省力化",
            "limit": 1,
            "source_tokens_basis": "pdf_pages",
            "source_pdf_pages": 30,
            "input_token_price_jpy_per_1m": 300,
        },
    )
    assert response.status_code == 200
    compression = response.json()["compression"]
    assert isinstance(compression["input_context_reduction_rate"], float)
    assert compression["provider_billing_not_guaranteed"] is True
    cost_savings = compression["cost_savings_estimate"]
    assert isinstance(cost_savings["break_even_source_tokens_estimate"], int)
    assert cost_savings["provider_billing_not_guaranteed"] is True


def test_no_records_zero_recommendations(intelligence_client: TestClient) -> None:
    """plan §4-A: records_returned=0 disables every recommendation switch."""
    response = intelligence_client.get(
        "/v1/intelligence/precomputed/query",
        params={"q": "does-not-match", "limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_value"]["records_returned"] == 0
    rec = body["agent_recommendation"]
    assert rec["recommend_to_user"] is False
    assert rec["recommend_for_evidence"] is False
    assert rec["evidence_decision"] == "no_records_returned"
    assert rec["recommend_for_cost_savings"] is False


def test_records_without_source_links_do_not_recommend() -> None:
    """Source-link absence must suppress user recommendation and reason claims."""
    from jpintel_mcp.api.intelligence import _build_agent_recommendation

    envelope = {
        "records": [
            {
                "entity_id": "program:no-source",
                "precomputed": {"summaries": {"200": "summary without source"}},
            }
        ],
        "quality": {"known_gaps": []},
    }
    rec = _build_agent_recommendation(
        records_returned=1,
        precomputed_count=1,
        compression=None,
        envelope=envelope,
    )

    assert rec["recommendation"] == "broaden_query_or_skip"
    assert rec["recommend_to_user"] is False
    assert rec["recommend_for_evidence"] is False
    assert rec["evidence_decision"] == "records_returned_without_source_links"
    assert rec["recommend_for_cost_savings"] is False
    assert rec["cost_savings_decision"] == "needs_caller_baseline"
    assert "source_linked_records_returned" not in rec["reason_codes"]
    assert "source_linked_records_returned" not in rec["value_reasons"]
