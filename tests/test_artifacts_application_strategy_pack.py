from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key


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


def _sections(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {section["section_id"]: section for section in body["sections"]}


def test_application_strategy_pack_wraps_prescreen(client: TestClient) -> None:
    response = client.post(
        "/v1/artifacts/application_strategy_pack",
        json={
            "profile": {
                "prefecture": "Tokyo",
                "is_sole_proprietor": True,
                "planned_investment_man_yen": 100,
            },
            "max_candidates": 3,
            "compatibility_top_n": 0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["artifact_type"] == "application_strategy_pack"
    assert body["endpoint"] == "artifacts.application_strategy_pack"
    assert body["summary"]["candidate_count"] >= 1
    assert body["summary"]["profile_echo"]["prefecture"] == "東京都"
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body
    assert body["packet_id"].startswith("pkt_application_strategy_pack_")
    assert body["_evidence"]["source_count"] == len(body["sources"])
    assert "source_receipts" in body
    assert body["billing_note"] == body["agent_routing"]["pricing_note"]
    assert body["billing_metadata"]["endpoint"] == "artifacts.application_strategy_pack"
    assert body["billing_metadata"]["unit_type"] == "artifact_call"
    assert body["billing_metadata"]["quantity"] == 1
    assert body["billing_metadata"]["result_count"] == body["summary"]["candidate_count"]
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
    assert body["markdown_display"].startswith("# application_strategy_pack")
    assert body["recommended_followup"]
    assert any(
        isinstance(gap, dict) and gap.get("gap_id") == "source_receipts_missing"
        for gap in body["known_gaps"]
    )
    assert any(item.startswith("source_receipt_gap:") for item in body["human_review_required"])

    sections = _sections(body)
    assert {"ranked_candidates", "application_questions"} <= set(sections)
    candidates = sections["ranked_candidates"]["rows"]
    assert candidates[0]["unified_id"] == "UNI-test-s-1"
    assert candidates[0]["recommendation"] in {
        "primary_candidate",
        "backup_candidate",
        "review_first",
    }
    assert candidates[0]["money_fit"]["status"] == "covers_plan"
    assert sections["application_questions"]["rows"]
    assert body["next_actions"]


def test_application_strategy_pack_adds_compatibility_section(
    client: TestClient,
    monkeypatch,
) -> None:
    from jpintel_mcp.api import artifacts

    class _FakeResult:
        def to_dict(self) -> dict[str, Any]:
            return {
                "program_ids": ["UNI-test-s-1", "UNI-test-b-1"],
                "total_pairs": 1,
                "all_pairs_status": "incompatible",
                "pairs": [
                    {
                        "program_a": "UNI-test-s-1",
                        "program_b": "UNI-test-b-1",
                        "verdict": "incompatible",
                        "confidence": 1.0,
                        "rule_chain": [
                            {
                                "source": "exclusion_rules",
                                "source_url": "https://example.com/compat",
                            }
                        ],
                    }
                ],
                "blockers": [{"program_a": "UNI-test-s-1", "program_b": "UNI-test-b-1"}],
                "warnings": [],
                "next_actions": [],
                "_disclaimer": "test",
            }

    class _FakeChecker:
        def check_stack(self, program_ids: list[str]) -> _FakeResult:
            assert program_ids == ["UNI-test-s-1", "UNI-test-b-1"]
            return _FakeResult()

    monkeypatch.setattr(artifacts, "_get_checker", lambda: _FakeChecker())

    response = client.post(
        "/v1/artifacts/application_strategy_pack",
        json={
            "profile": {"prefecture": "Tokyo", "limit": 10},
            "max_candidates": 2,
            "compatibility_top_n": 2,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    sections = _sections(body)

    assert sections["compatibility_screen"]["summary"]["all_pairs_status"] == "incompatible"
    assert body["summary"]["compatibility_status"] == "incompatible"
    assert "https://example.com/compat" in {source["source_url"] for source in body["sources"]}
    assert any(
        isinstance(gap, dict) and gap.get("gap_id") == "source_receipt_missing_fields"
        for gap in body["known_gaps"]
    )
    assert any(item.startswith("pair_001:") for item in body["human_review_required"])


def test_application_strategy_pack_carries_source_metadata_to_receipts(
    client: TestClient,
    seeded_db: Path,
) -> None:
    source_url = "https://example.com/application-strategy-source"
    source_fetched_at = "2026-05-06T00:00:00Z"
    source_checksum = "sha256:application-strategy-checksum"
    license_or_terms = "government standard terms 2.0"

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    original = conn.execute(
        "SELECT source_url, source_fetched_at, source_checksum, source_mentions_json "
        "FROM programs WHERE unified_id = ?",
        ("UNI-test-s-1",),
    ).fetchone()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS source_catalog ("
            "source_url TEXT PRIMARY KEY, "
            "license_or_terms TEXT, "
            "source_type TEXT, "
            "official_owner TEXT, "
            "attribution_text TEXT"
            ")",
        )
        conn.execute(
            "INSERT OR REPLACE INTO source_catalog("
            "source_url, license_or_terms, source_type, official_owner, attribution_text"
            ") VALUES (?,?,?,?,?)",
            (
                source_url,
                license_or_terms,
                "official_publication",
                "Test Authority",
                "Test attribution",
            ),
        )
        conn.execute(
            "UPDATE programs SET source_url = ?, source_fetched_at = ?, "
            "source_checksum = ?, source_mentions_json = ? WHERE unified_id = ?",
            (
                source_url,
                source_fetched_at,
                source_checksum,
                '{"source_url":"https://example.com/secondary","license_or_terms":"secondary"}',
                "UNI-test-s-1",
            ),
        )
        conn.commit()

        response = client.post(
            "/v1/artifacts/application_strategy_pack",
            json={
                "profile": {
                    "prefecture": "Tokyo",
                    "is_sole_proprietor": True,
                    "planned_investment_man_yen": 100,
                },
                "max_candidates": 1,
                "compatibility_top_n": 0,
            },
        )
    finally:
        conn.execute("DELETE FROM source_catalog WHERE source_url = ?", (source_url,))
        conn.execute(
            "UPDATE programs SET source_url = ?, source_fetched_at = ?, "
            "source_checksum = ?, source_mentions_json = ? WHERE unified_id = ?",
            (
                original["source_url"] if original else None,
                original["source_fetched_at"] if original else None,
                original["source_checksum"] if original else None,
                original["source_mentions_json"] if original else None,
                "UNI-test-s-1",
            ),
        )
        conn.commit()
        conn.close()

    assert response.status_code == 200, response.text
    body = response.json()
    candidate = _sections(body)["ranked_candidates"]["rows"][0]
    assert candidate["source_url"] == source_url
    assert candidate["source_checksum"] == source_checksum
    assert candidate["content_hash"] == source_checksum
    assert candidate["license"] == license_or_terms
    assert candidate["license_or_terms"] == license_or_terms

    source = next(item for item in body["sources"] if item["source_url"] == source_url)
    assert source["content_hash"] == source_checksum
    assert source["license"] == license_or_terms

    receipt = next(item for item in body["source_receipts"] if item["source_url"] == source_url)
    assert receipt["source_fetched_at"] == source_fetched_at
    assert receipt["content_hash"] == source_checksum
    assert receipt["license"] == license_or_terms


def test_application_strategy_pack_usage_logged_as_one_artifact(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
) -> None:
    key_hash = hash_api_key(paid_key)
    response = client.post(
        "/v1/artifacts/application_strategy_pack",
        json={
            "profile": {"prefecture": "Tokyo"},
            "max_candidates": 2,
            "compatibility_top_n": 0,
        },
        headers={"X-API-Key": paid_key},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "audit_seal" in body
    assert "_seal_unavailable" not in body
    assert body["billing_metadata"]["endpoint"] == "artifacts.application_strategy_pack"
    assert body["billing_metadata"]["quantity"] == 1
    assert body["billing_metadata"]["result_count"] == body["summary"]["candidate_count"]
    assert body["billing_metadata"]["metered"] is True
    assert body["billing_metadata"]["audit_seal"]["authenticated_key_present"] is True
    assert body["billing_metadata"]["audit_seal"]["requested_for_metered_key"] is True
    assert body["billing_metadata"]["audit_seal"]["included_when_available"] is True

    conn = sqlite3.connect(seeded_db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT quantity, result_count FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'artifacts.application_strategy_pack' "
            "ORDER BY id DESC LIMIT 1",
            (key_hash,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert int(row["quantity"]) == 1
    assert int(row["result_count"]) == 2


def test_application_strategy_pack_rejects_honeypot(client: TestClient) -> None:
    response = client.post(
        "/v1/artifacts/application_strategy_pack",
        json={"profile": {"company_url": "https://spam.example"}},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_input"
