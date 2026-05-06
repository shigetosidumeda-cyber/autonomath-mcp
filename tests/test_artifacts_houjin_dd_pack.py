from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

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


def test_houjin_dd_pack_wraps_houjin_full(intel_full_client: TestClient) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": _TEST_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["artifact_type"] == "houjin_dd_pack"
    assert body["endpoint"] == "artifacts.houjin_dd_pack"
    assert body["summary"]["houjin_bangou"] == _TEST_HOUJIN
    assert body["summary"]["company_name"] == "株式会社テスト"
    assert body["summary"]["enforcement_record_count"] == 1
    assert body["summary"]["invoice_status"] == "active"
    assert body["summary"]["jurisdiction_status"] == "mismatch"
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body
    assert "_disclaimer" in body
    assert body["packet_id"].startswith("pkt_houjin_dd_pack_")
    assert body["_evidence"]["source_count"] == len(body["sources"])
    assert body["_evidence"]["source_receipt_completion"]["total"] == len(body["source_receipts"])
    assert body["billing_note"] == body["agent_routing"]["pricing_note"]
    assert body["billing_metadata"]["endpoint"] == "artifacts.houjin_dd_pack"
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
    assert body["copy_paste_parts"]
    assert body["markdown_display"].startswith("# houjin_dd_pack")
    assert body["recommended_followup"]

    sections = {section["section_id"]: section for section in body["sections"]}
    assert {
        "corporate_profile",
        "public_risk_signals",
        "funding_and_peer_signals",
        "dd_questions",
        "decision_support",
    } <= set(sections)
    assert sections["dd_questions"]["rows"]
    assert any(
        source["source_url"] == "https://example.tokyo/enforcement/1" for source in body["sources"]
    )
    assert body["next_actions"]
    assert body["human_review_required"]


def test_houjin_dd_pack_sparse_houjin_keeps_known_gaps(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": _SPARSE_HOUJIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    gap_sections = {gap.get("section") for gap in body["known_gaps"]}
    assert "enforcement" in gap_sections
    assert "invoice_status" in gap_sections
    assert any("not proof of safety" in gap["message"] for gap in body["known_gaps"])


def test_houjin_dd_pack_invalid_houjin_returns_422(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": "abcdefghijklm"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "invalid_houjin_bangou"


def test_houjin_dd_pack_accepts_t_prefix(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": f"T{_TEST_HOUJIN}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["houjin_bangou"] == _TEST_HOUJIN


def test_houjin_dd_pack_partial_empty_section_does_not_hide_existing_houjin(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": _SPARSE_HOUJIN, "include_sections": ["enforcement"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["houjin_bangou"] == _SPARSE_HOUJIN
    assert any(gap.get("section") == "enforcement" for gap in body["known_gaps"])


def test_houjin_dd_pack_unknown_houjin_returns_404(
    intel_full_client: TestClient,
) -> None:
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": "1111111111111"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["error"] == "houjin_not_found"


def test_houjin_dd_pack_usage_logged_as_one_artifact(
    intel_full_client: TestClient,
    seeded_db: Path,
    paid_key: str,
) -> None:
    key_hash = hash_api_key(paid_key)
    response = intel_full_client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": _TEST_HOUJIN},
        headers={"X-API-Key": paid_key},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "audit_seal" in body
    assert body["billing_metadata"]["endpoint"] == "artifacts.houjin_dd_pack"
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
            "WHERE key_hash = ? AND endpoint = 'artifacts.houjin_dd_pack' "
            "ORDER BY id DESC LIMIT 1",
            (key_hash,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert int(row["quantity"]) == 1
    assert int(row["result_count"]) == 7


def test_houjin_dd_pack_final_metering_cap_failure_not_billed_or_sealed(
    intel_full_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api.middleware import customer_cap

    endpoint = "artifacts.houjin_dd_pack"
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
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": _TEST_HOUJIN},
        headers={"X-API-Key": paid_key},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_totals() == before_usage
    assert audit_seal_count() == before_seals
