from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key
from tests.test_intel_houjin_full import (
    _SPARSE_HOUJIN,
    _TEST_HOUJIN,
    intel_full_client,
    seeded_intel_houjin_full_db,
)

_ = (intel_full_client, seeded_intel_houjin_full_db)

_COMPANY_ARTIFACTS = [
    (
        "/v1/artifacts/company_public_baseline",
        "company_public_baseline",
        "artifacts.company_public_baseline",
    ),
    (
        "/v1/artifacts/company_folder_brief",
        "company_folder_brief",
        "artifacts.company_folder_brief",
    ),
    (
        "/v1/artifacts/company_public_audit_pack",
        "company_public_audit_pack",
        "artifacts.company_public_audit_pack",
    ),
]

_REQUIRED_RESPONSE_KEYS = {
    "summary",
    "sections",
    "sources",
    "known_gaps",
    "next_actions",
    "human_review_required",
    "_disclaimer",
    "copy_paste_parts",
    "markdown_display",
    "_evidence",
    "source_receipts",
    "recommended_followup_by_channel",
    "agent_routing",
    "billing_note",
    "billing_metadata",
}

_AUDIT_SOURCE_RECEIPT_FIELDS = {
    "source_url",
    "source_fetched_at",
    "content_hash",
    "license",
    "used_in",
}


@pytest.fixture(autouse=True)
def _ensure_audit_seal_tables(seeded_db: Path) -> None:
    """Layer audit seal migrations onto the baseline seeded jpintel DB."""
    migrations = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
    for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
        conn = sqlite3.connect(seeded_db)
        try:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.executescript((migrations / mig).read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()

    from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

    _reset_corpus_snapshot_cache_for_tests()


def _sections(body: dict[str, Any]) -> set[str]:
    return {section["section_id"] for section in body["sections"]}


def _assert_common_company_artifact(
    body: dict[str, Any],
    *,
    artifact_type: str,
    endpoint: str,
) -> None:
    assert set(body) >= _REQUIRED_RESPONSE_KEYS
    assert body["artifact_type"] == artifact_type
    assert body["endpoint"] == endpoint
    assert body["summary"]["houjin_bangou"] == _TEST_HOUJIN
    assert body["summary"]["company_name"] == "株式会社テスト"
    assert body["summary"]["invoice_status"] == "active"
    assert body["summary"]["enforcement_record_count"] == 1
    assert body["summary"]["jurisdiction_status"] == "mismatch"
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body
    assert body["packet_id"].startswith(f"pkt_{artifact_type}_")
    assert body["_evidence"]["source_count"] == len(body["sources"])
    assert body["copy_paste_parts"]
    assert any(part["part_id"] == "folder_readme" for part in body["copy_paste_parts"])
    assert body["markdown_display"].startswith(f"# {artifact_type}")
    assert "Source receipts:" in body["markdown_display"]
    assert "Billing:" in body["markdown_display"]
    assert body["_evidence"]["source_receipt_completion"]["total"] == len(body["source_receipts"])
    assert body["source_receipts"]
    assert body["recommended_followup_by_channel"]["use_web_search_for"]
    assert body["agent_routing"]["no_llm_called_by_jpcite"] is True
    assert body["billing_note"] == body["agent_routing"]["pricing_note"]
    assert body["billing_metadata"]["endpoint"] == endpoint
    assert body["billing_metadata"]["unit_type"] == "artifact_call"
    assert body["billing_metadata"]["quantity"] == 1
    assert body["billing_metadata"]["result_count"] == 7
    assert body["billing_metadata"]["metered"] is False
    assert body["billing_metadata"]["strict_metering"] is True
    assert body["billing_metadata"]["pricing_note"] == body["billing_note"]
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is False
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is False
    assert (
        body["billing_metadata"]["audit_seal"]["billing_metadata_covered_by_response_hash"] is False
    )
    assert body["billing_metadata"]["audit_seal"]["seal_field_excluded_from_response_hash"] is False
    assert body["next_actions"]
    assert body["human_review_required"]
    assert any(
        source["source_url"] == "https://example.tokyo/enforcement/1" for source in body["sources"]
    )


def test_company_public_baseline_happy_path(intel_full_client: TestClient) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/company_public_baseline",
        json={"houjin_bangou": _TEST_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_common_company_artifact(
        body,
        artifact_type="company_public_baseline",
        endpoint="artifacts.company_public_baseline",
    )
    assert {"company_identity", "registration_status", "public_signals", "data_gaps"} <= (
        _sections(body)
    )
    assert body["subject"]["identity_confidence"] == "exact_houjin_bangou"
    assert body["benefit_angles"]
    assert body["risk_angles"]
    assert body["questions_to_ask"]
    assert body["folder_tasks"]
    assert body["watch_targets"]


def test_company_folder_brief_happy_path(intel_full_client: TestClient) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/company_folder_brief",
        json={"houjin_bangou": _TEST_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_common_company_artifact(
        body,
        artifact_type="company_folder_brief",
        endpoint="artifacts.company_folder_brief",
    )
    assert {"brief_header", "company_profile", "diligence_snapshot", "folder_checklist"} <= (
        _sections(body)
    )
    assert body["questions_to_ask"]
    assert body["folder_tasks"]
    assert body["watch_targets"]


def test_company_public_audit_pack_happy_path(intel_full_client: TestClient) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/company_public_audit_pack",
        json={"houjin_bangou": _TEST_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_common_company_artifact(
        body,
        artifact_type="company_public_audit_pack",
        endpoint="artifacts.company_public_audit_pack",
    )
    assert {"audit_subject", "evidence_ledger", "risk_and_gap_register", "review_controls"} <= (
        _sections(body)
    )
    assert body["source_receipt_expectation"]["required_for_workpaper"] is True
    assert "jurisdiction_mismatch" in body["mismatch_flags"]
    assert body["questions_to_ask"]


def test_company_public_audit_pack_source_receipts_quality_gate(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/company_public_audit_pack",
        json={"houjin_bangou": _TEST_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    receipts = body["source_receipts"]
    assert receipts
    assert all(set(receipt) >= _AUDIT_SOURCE_RECEIPT_FIELDS for receipt in receipts)
    assert all(receipt["source_url"] for receipt in receipts)
    assert all(isinstance(receipt["used_in"], list) and receipt["used_in"] for receipt in receipts)

    receipt_gap_fields_by_url = {
        gap["source_url"]: set(gap["missing_fields"])
        for gap in body["known_gaps"]
        if isinstance(gap, dict) and gap.get("gap_id") == "source_receipt_missing_fields"
    }
    assert {
        "source_fetched_at",
        "content_hash",
        "license",
    } <= receipt_gap_fields_by_url["https://example.tokyo/enforcement/1"]
    assert (
        not {
            "source_url",
            "used_in",
        }
        & receipt_gap_fields_by_url["https://example.tokyo/enforcement/1"]
    )
    assert any(item.startswith("source_receipt_gap:") for item in body["human_review_required"])
    risk_gap_section = next(
        section for section in body["sections"] if section["section_id"] == "risk_and_gap_register"
    )
    section_gap_ids = {
        gap.get("gap_id")
        for row in risk_gap_section["rows"]
        for gap in row.get("known_gaps", [])
        if isinstance(gap, dict)
    }
    assert "source_receipt_missing_fields" in section_gap_ids


@pytest.mark.parametrize(
    ("route", "artifact_type"),
    [
        ("/v1/artifacts/company_public_baseline", "company_public_baseline"),
        ("/v1/artifacts/company_folder_brief", "company_folder_brief"),
    ],
)
def test_non_audit_company_artifacts_surface_source_receipt_gaps(
    intel_full_client: TestClient,
    route: str,
    artifact_type: str,
) -> None:
    response = intel_full_client.post(route, json={"houjin_bangou": _TEST_HOUJIN})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["artifact_type"] == artifact_type
    assert any(
        isinstance(gap, dict) and gap.get("gap_id") == "source_receipt_missing_fields"
        for gap in body["known_gaps"]
    )
    assert any(item.startswith("source_receipt_gap:") for item in body["human_review_required"])


def test_company_public_audit_pack_preserves_source_receipt_metadata() -> None:
    from jpintel_mcp.api import artifacts as artifacts_module

    body = {
        "artifact_type": "company_public_audit_pack",
        "sources": [
            {
                "source_url": "https://example.metro/source/ok",
                "used_in": ["sections[0].rows[0].source_url"],
                "source_fetched_at": "2026-05-06T00:00:00+00:00",
                "content_hash": "sha256:abc",
                "license": "PDL-1.0",
            }
        ],
        "known_gaps": [],
        "human_review_required": [],
    }

    receipts = artifacts_module._source_receipts(body)
    artifacts_module._append_source_receipt_quality_gaps(body, receipts)

    assert receipts == [
        {
            "source_receipt_id": receipts[0]["source_receipt_id"],
            "source_url": "https://example.metro/source/ok",
            "source_kind": None,
            "used_in": ["sections[0].rows[0].source_url"],
            "source_fetched_at": "2026-05-06T00:00:00+00:00",
            "content_hash": "sha256:abc",
            "license": "PDL-1.0",
        }
    ]
    assert body["known_gaps"] == []
    assert body["human_review_required"] == []


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_artifacts_accept_t_prefix(
    intel_full_client: TestClient,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    response = intel_full_client.post(
        route,
        json={"houjin_bangou": f"T{_TEST_HOUJIN}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_common_company_artifact(body, artifact_type=artifact_type, endpoint=endpoint)


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_artifacts_invalid_houjin_returns_422(
    intel_full_client: TestClient,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    _ = (artifact_type, endpoint)
    response = intel_full_client.post(route, json={"houjin_bangou": "abcdefghijklm"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "invalid_houjin_bangou"


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_artifacts_unknown_houjin_returns_404(
    intel_full_client: TestClient,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    _ = (artifact_type, endpoint)
    response = intel_full_client.post(route, json={"houjin_bangou": "1111111111111"})
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["error"] == "houjin_not_found"


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_artifacts_sparse_houjin_keeps_known_gaps(
    intel_full_client: TestClient,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    response = intel_full_client.post(route, json={"houjin_bangou": _SPARSE_HOUJIN})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact_type"] == artifact_type
    assert body["endpoint"] == endpoint
    gap_sections = {gap.get("section") for gap in body["known_gaps"] if isinstance(gap, dict)}
    assert "enforcement" in gap_sections
    assert "invoice_status" in gap_sections
    assert any(
        isinstance(gap, dict) and "not proof of safety" in gap["message"]
        for gap in body["known_gaps"]
    )


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_artifacts_paid_key_usage_and_audit_seal(
    intel_full_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    key_hash = hash_api_key(paid_key)
    response = intel_full_client.post(
        route,
        json={"houjin_bangou": _TEST_HOUJIN},
        headers={"X-API-Key": paid_key},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact_type"] == artifact_type
    assert "audit_seal" in body
    assert "_seal_unavailable" not in body
    assert body["billing_metadata"]["endpoint"] == endpoint
    assert body["billing_metadata"]["quantity"] == 1
    assert body["billing_metadata"]["result_count"] == 7
    assert body["billing_metadata"]["metered"] is True
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is True
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is True
    assert body["billing_metadata"]["audit_seal"]["included_when_available"] is True

    conn = sqlite3.connect(seeded_db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT quantity, result_count FROM usage_events "
            "WHERE key_hash = ? AND endpoint = ? "
            "ORDER BY id DESC LIMIT 1",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert int(row["quantity"]) == 1
    assert int(row["result_count"]) == 7


@pytest.mark.parametrize(("route", "artifact_type", "endpoint"), _COMPANY_ARTIFACTS)
def test_company_public_paid_artifact_final_metering_cap_failure_not_billed_or_sealed(
    intel_full_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    artifact_type: str,
    endpoint: str,
) -> None:
    from jpintel_mcp.api.middleware import customer_cap

    _ = artifact_type
    key_hash = hash_api_key(paid_key)

    def usage_totals() -> tuple[int, int]:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM usage_events "
                "WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0]), int(row[1])
        finally:
            conn.close()

    def audit_seal_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM audit_seals WHERE api_key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    before_usage = usage_totals()
    before_seals = audit_seal_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    response = intel_full_client.post(
        route,
        json={"houjin_bangou": _TEST_HOUJIN},
        headers={"X-API-Key": paid_key},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_totals() == before_usage
    assert audit_seal_count() == before_seals
