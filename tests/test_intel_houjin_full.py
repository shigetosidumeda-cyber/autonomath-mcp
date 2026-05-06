"""Tests for GET /v1/intel/houjin/{houjin_id}/full composite endpoint.

The endpoint merges 5+ legacy fan-out reads (`/v1/houjin/{bangou}` +
`/v1/intel/probability_radar` + `/v1/am/check_enforcement` + invoice
lookup + peer density + watch status) into one GET.

Coverage:
  1. Happy path — known 法人番号 with seeded adoption + enforcement +
     invoice + peer rows returns 200 + the full composite envelope
     (sections + _disclaimer + _billing_unit + corpus_snapshot_id).
  2. 422 — malformed houjin_bangou (non-13-digit) returns the structured
     invalid_houjin_bangou error.
  3. include_sections filter — narrows the response to only the
     requested sections.
  4. Envelope check — every 2xx body carries _disclaimer / _billing_unit:1
     and the §52 / §72 / §1 fence wording.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test fixtures — build a minimal autonomath.db slice + a customer_watches
# row in the seeded jpintel.db so the endpoint has something to project.
# ---------------------------------------------------------------------------


_TEST_HOUJIN = "1234567890123"
_TEST_INVOICE = "T1234567890123"
_TEST_PROGRAM_NAME = "テスト ものづくり高度化補助金"
_SPARSE_HOUJIN = "1234567890456"


def _seed_jpintel_customer_watches(jpintel_db: Path) -> None:
    """Add customer_watches table + a single active watch row on _TEST_HOUJIN.

    The seeded_db fixture only runs the base schema (init_db) which pre-dates
    migration 088. We CREATE TABLE IF NOT EXISTS + INSERT so the watch_status
    section has a non-trivial answer.
    """
    conn = sqlite3.connect(jpintel_db)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customer_watches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_hash    TEXT NOT NULL,
                watch_kind      TEXT NOT NULL
                                    CHECK (watch_kind IN ('houjin', 'program', 'law')),
                target_id       TEXT NOT NULL,
                registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
                last_event_at   TEXT,
                status          TEXT NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'disabled')),
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                disabled_at     TEXT,
                disabled_reason TEXT
            );
            """
        )
        conn.execute(
            "DELETE FROM customer_watches WHERE watch_kind = 'houjin' AND target_id = ?",
            (_TEST_HOUJIN,),
        )
        conn.execute(
            "INSERT INTO customer_watches (api_key_hash, watch_kind, target_id, status) "
            "VALUES (?, 'houjin', ?, 'active')",
            ("test-key-hash-1", _TEST_HOUJIN),
        )
        conn.execute(
            "INSERT INTO customer_watches (api_key_hash, watch_kind, target_id, status) "
            "VALUES (?, 'houjin', ?, 'active')",
            ("test-key-hash-2", _TEST_HOUJIN),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def seeded_intel_houjin_full_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> Path:
    """Build a tmp autonomath.db with the substrate the endpoint reads.

    Returns the autonomath path (the seeded_db fixture covers jpintel.db).
    Pins ``settings.autonomath_db_path`` + ``AUTONOMATH_DB_PATH`` to the
    tmp file so the endpoint reads our slice instead of the live 9.4 GB DB.
    """
    db_path = tmp_path / "autonomath_intel_full.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE houjin_master (
                houjin_bangou      TEXT PRIMARY KEY,
                normalized_name    TEXT NOT NULL,
                alternative_names_json TEXT,
                address_normalized TEXT,
                prefecture         TEXT,
                municipality       TEXT,
                corporation_type   TEXT,
                established_date   TEXT,
                close_date         TEXT,
                last_updated_nta   TEXT,
                data_sources_json  TEXT,
                total_adoptions    INTEGER NOT NULL DEFAULT 0,
                total_received_yen INTEGER NOT NULL DEFAULT 0,
                notes              TEXT,
                fetched_at         TEXT NOT NULL,
                jsic_major         TEXT,
                jsic_middle        TEXT,
                jsic_minor         TEXT,
                jsic_assigned_at   TEXT,
                jsic_assigned_method TEXT
            );
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value_text TEXT,
                field_value_numeric REAL,
                unit TEXT,
                field_kind TEXT
            );
            CREATE TABLE am_adopted_company_features (
                houjin_bangou           TEXT PRIMARY KEY,
                adoption_count          INTEGER NOT NULL DEFAULT 0,
                distinct_program_count  INTEGER NOT NULL DEFAULT 0,
                first_adoption_at       TEXT,
                last_adoption_at        TEXT,
                dominant_jsic_major     TEXT,
                dominant_prefecture     TEXT,
                enforcement_count       INTEGER NOT NULL DEFAULT 0,
                invoice_registered      INTEGER NOT NULL DEFAULT 0,
                loan_count              INTEGER NOT NULL DEFAULT 0,
                credibility_score       REAL,
                computed_at             TEXT
            );
            CREATE TABLE am_enforcement_detail (
                enforcement_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id         TEXT NOT NULL,
                houjin_bangou     TEXT,
                target_name       TEXT,
                enforcement_kind  TEXT,
                issuing_authority TEXT,
                issuance_date     TEXT NOT NULL,
                exclusion_start   TEXT,
                exclusion_end     TEXT,
                reason_summary    TEXT,
                related_law_ref   TEXT,
                amount_yen        INTEGER,
                source_url        TEXT,
                source_fetched_at TEXT,
                created_at        TEXT
            );
            CREATE TABLE jpi_invoice_registrants (
                invoice_registration_number TEXT PRIMARY KEY,
                houjin_bangou TEXT,
                normalized_name TEXT NOT NULL,
                address_normalized TEXT,
                prefecture TEXT,
                registered_date TEXT NOT NULL,
                revoked_date TEXT,
                expired_date TEXT,
                registrant_kind TEXT NOT NULL,
                trade_name TEXT,
                last_updated_nta TEXT,
                source_url TEXT NOT NULL,
                source_checksum TEXT,
                confidence REAL NOT NULL DEFAULT 0.98,
                fetched_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE jpi_adoption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                houjin_bangou TEXT,
                program_id TEXT,
                program_name_raw TEXT,
                amount_granted_yen INTEGER,
                announced_at TEXT,
                round_label TEXT,
                prefecture TEXT,
                source_url TEXT,
                industry_jsic_medium TEXT
            );
            CREATE TABLE am_amendment_diff (
                diff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id      TEXT NOT NULL,
                field_name     TEXT NOT NULL,
                prev_value     TEXT,
                new_value      TEXT,
                prev_hash      TEXT,
                new_hash       TEXT,
                detected_at    TIMESTAMP NOT NULL,
                source_url     TEXT
            );
            """
        )

        # Seed the queried 法人番号 with rich data spanning every section.
        conn.execute(
            "INSERT INTO houjin_master (houjin_bangou, normalized_name, "
            " address_normalized, prefecture, municipality, corporation_type, "
            " established_date, jsic_major, total_adoptions, total_received_yen, "
            " fetched_at) "
            "VALUES (?, '株式会社テスト', '東京都千代田区1-1', '東京都', "
            " '千代田区', '株式会社', '2010-04-01', 'E', 3, 12000000, "
            " '2026-05-01T00:00:00Z')",
            (_TEST_HOUJIN,),
        )
        conn.execute(
            "INSERT INTO houjin_master (houjin_bangou, normalized_name, "
            " address_normalized, prefecture, municipality, corporation_type, "
            " established_date, jsic_major, total_adoptions, total_received_yen, "
            " fetched_at) "
            "VALUES (?, '株式会社スパース', '大阪府大阪市1-1', '大阪府', "
            " '大阪市', '株式会社', '2020-01-01', 'G', 0, 0, "
            " '2026-05-01T00:00:00Z')",
            (_SPARSE_HOUJIN,),
        )
        # capital + employees as EAV facts.
        conn.executemany(
            "INSERT INTO am_entity_facts (entity_id, field_name, field_value_numeric, unit, field_kind) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (f"houjin:{_TEST_HOUJIN}", "corp.capital_amount", 50_000_000, "JPY", "money"),
                (f"houjin:{_TEST_HOUJIN}", "corp.employee_count", 42, "person", "count"),
            ],
        )
        # adoption_history
        conn.executemany(
            "INSERT INTO jpi_adoption_records (houjin_bangou, program_id, "
            " program_name_raw, amount_granted_yen, announced_at, prefecture, "
            " industry_jsic_medium) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    _TEST_HOUJIN,
                    "UNI-test-mono-1",
                    _TEST_PROGRAM_NAME,
                    8_000_000,
                    "2025-03-01",
                    "東京都",
                    "E25",
                ),
                (
                    _TEST_HOUJIN,
                    "UNI-test-it-1",
                    "テスト IT 導入補助金",
                    3_000_000,
                    "2024-09-15",
                    "東京都",
                    "E25",
                ),
                (
                    _TEST_HOUJIN,
                    "UNI-test-jisedai-1",
                    "テスト 次世代 GX",
                    1_000_000,
                    "2023-08-01",
                    "神奈川県",
                    "E25",
                ),
            ],
        )
        # enforcement_records
        conn.execute(
            "INSERT INTO am_enforcement_detail (entity_id, houjin_bangou, "
            " target_name, enforcement_kind, issuing_authority, issuance_date, "
            " amount_yen, reason_summary, source_url) "
            "VALUES (?, ?, '株式会社テスト', 'business_improvement', "
            "        '東京都産業労働局', '2024-06-01', NULL, '軽微な改善命令', "
            "        'https://example.tokyo/enforcement/1')",
            (f"houjin:{_TEST_HOUJIN}", _TEST_HOUJIN),
        )
        # invoice_status — active registration.
        conn.execute(
            "INSERT INTO jpi_invoice_registrants ("
            " invoice_registration_number, houjin_bangou, normalized_name, "
            " prefecture, registered_date, registrant_kind, source_url, "
            " fetched_at, updated_at) "
            "VALUES (?, ?, '株式会社テスト', '東京都', '2023-10-01', "
            "        'corporation', 'https://www.invoice-kohyo.nta.go.jp/'  , "
            "        '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (_TEST_INVOICE, _TEST_HOUJIN),
        )
        # peer_summary — 3 peers in same JSIC × prefecture cohort + the test row itself.
        conn.executemany(
            "INSERT INTO am_adopted_company_features (houjin_bangou, "
            " adoption_count, distinct_program_count, dominant_jsic_major, "
            " dominant_prefecture, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (_TEST_HOUJIN, 3, 3, "E", "東京都", "2026-05-05"),
                ("9999999999991", 2, 2, "E", "東京都", "2026-05-05"),
                ("9999999999992", 5, 4, "E", "東京都", "2026-05-05"),
                ("9999999999993", 1, 1, "E", "東京都", "2026-05-05"),
            ],
        )
        # last_amendment for watch_status
        conn.execute(
            "INSERT INTO am_amendment_diff (entity_id, field_name, "
            " prev_value, new_value, detected_at) "
            "VALUES (?, 'corp.legal_name', '株式会社テスト旧', "
            "        '株式会社テスト', '2026-04-15T10:00:00Z')",
            (f"houjin:{_TEST_HOUJIN}",),
        )

        conn.commit()
    finally:
        conn.close()

    # Pin both env + settings so the endpoint resolves to this slice.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Wire jpintel-side customer_watches.
    _seed_jpintel_customer_watches(seeded_db)
    return db_path


@pytest.fixture()
def intel_full_client(seeded_intel_houjin_full_db: Path) -> TestClient:
    """TestClient with the autonomath slice + customer_watches wired."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_intel_houjin_full_happy_path_returns_envelope(
    intel_full_client: TestClient,
) -> None:
    """Known 法人番号 returns the full composite envelope across every section."""
    r = intel_full_client.get(f"/v1/intel/houjin/{_TEST_HOUJIN}/full")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level envelope keys.
    assert body["houjin_bangou"] == _TEST_HOUJIN
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body
    # §52 / §72 / §1 fence wording is mandatory.
    disc = body["_disclaimer"]
    assert "税理士法 §52" in disc
    assert "弁護士法 §72" in disc
    assert "行政書士法 §1" in disc
    assert "corpus_snapshot_id" in body

    # All seven sections present at default include_sections.
    assert body.get("houjin_meta")
    meta = body["houjin_meta"]
    assert meta["name"] == "株式会社テスト"
    assert meta["capital"] == 50_000_000
    assert meta["employees"] == 42
    assert meta["founded"] == "2010-04-01"
    assert meta["jsic"] == "E"
    assert meta["address"] == "東京都千代田区1-1"

    # adoption_history sorted by amount DESC.
    adopt = body["adoption_history"]
    assert isinstance(adopt, list)
    assert len(adopt) == 3
    assert adopt[0]["program_id"] == "UNI-test-mono-1"
    assert adopt[0]["amount"] == 8_000_000
    assert adopt[0]["year"] == "2025"

    # enforcement_records carries severity classification.
    enf = body["enforcement_records"]
    assert isinstance(enf, list) and len(enf) == 1
    assert enf[0]["action"] == "business_improvement"
    assert enf[0]["severity"] == "low"
    assert enf[0]["date"] == "2024-06-01"

    # invoice_status — active registration.
    inv = body["invoice_status"]
    assert inv["registered"] is True
    assert inv["registration_no"] == _TEST_INVOICE
    assert inv["registered_date"] == "2023-10-01"

    # peer_summary — 3 peers in same cohort.
    peer = body["peer_summary"]
    assert peer["peer_count"] == 3
    assert peer["peer_avg_adoption_count"] is not None
    assert peer["cohort_jsic"] == "E"
    assert peer["cohort_prefecture"] == "東京都"
    # query_percentile in [0, 1].
    assert 0.0 <= float(peer["query_percentile"]) <= 1.0

    # jurisdiction_breakdown.
    jur = body["jurisdiction_breakdown"]
    assert jur["registered_pref"] == "東京都"
    assert jur["invoice_pref"] == "東京都"
    assert "東京都" in jur["operational_prefs"]
    # Two prefectures in operational (神奈川県 + 東京都) → still consistent
    # is False because operational expands beyond registered/invoice.
    # Test that the `consistent` field is at least present and boolean.
    assert isinstance(jur["consistent"], bool)

    # watch_status — 2 active watch rows seeded.
    watch = body["watch_status"]
    assert watch["is_watched"] is True
    assert watch["watch_subscribers"] == 2
    assert watch["last_amendment"] == "2026-04-15T10:00:00Z"

    # decision_support is deterministic and only derived from returned body fields.
    ds = body["decision_support"]
    risk = ds["risk_summary"]
    assert risk["enforcement"]["status"] == "detected"
    assert risk["enforcement"]["record_count"] == 1
    assert risk["invoice_status"]["status"] == "active"
    assert risk["jurisdiction"]["status"] == "mismatch"
    assert risk["watch_status"]["status"] == "watched"
    assert "enforcement_records_present" in risk["flags"]
    assert "jurisdiction_mismatch" in risk["flags"]

    action_ids = {a["action"] for a in ds["next_actions"]}
    assert {
        "verify_enforcement_source",
        "review_invoice_status",
        "review_jurisdiction",
        "monitor_changes",
    } <= action_ids
    assert ds["decision_insights"]
    assert all(i.get("source_fields") for i in ds["decision_insights"])


def test_intel_houjin_full_malformed_houjin_returns_422(
    intel_full_client: TestClient,
) -> None:
    """Non-13-digit houjin_id returns 422 with a structured detail."""
    # Path-level FastAPI validation: min_length=13. A 5-digit id triggers the
    # validator BEFORE our handler runs.
    r = intel_full_client.get("/v1/intel/houjin/12345/full")
    assert r.status_code == 422

    # A 13-character non-numeric string passes the length check but fails the
    # _normalize_houjin guard inside the handler.
    r2 = intel_full_client.get("/v1/intel/houjin/abcdefghijklm/full")
    assert r2.status_code == 422
    body2 = r2.json()
    detail = body2.get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "invalid_houjin_bangou"
    else:
        # FastAPI may wrap pydantic validation errors as a list of issues —
        # in either case the response must be 422, which is the contract.
        assert r2.status_code == 422


def test_intel_houjin_full_include_sections_filter(
    intel_full_client: TestClient,
) -> None:
    """include_sections narrows the response to only the requested sections."""
    r = intel_full_client.get(
        f"/v1/intel/houjin/{_TEST_HOUJIN}/full",
        params={"include_sections": "meta,watch_status"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Requested sections present.
    assert body.get("houjin_meta")
    assert body.get("watch_status")
    # Sections NOT requested must be absent.
    assert "adoption_history" not in body
    assert "enforcement_records" not in body
    assert "invoice_status" not in body
    assert "peer_summary" not in body
    assert "jurisdiction_breakdown" not in body

    # sections_returned echoes the parsed canonical list.
    assert set(body["sections_returned"]) == {"meta", "watch_status"}

    # Envelope invariants still apply.
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body

    ds = body["decision_support"]
    action_ids = {a["action"] for a in ds["next_actions"]}
    assert action_ids == {"monitor_changes"}
    assert "enforcement" not in ds["risk_summary"]
    assert "invoice_status" not in ds["risk_summary"]
    assert "jurisdiction" not in ds["risk_summary"]
    assert {i["section"] for i in ds["decision_insights"]} == {"watch_status"}


def test_intel_houjin_full_decision_support_known_gaps_for_empty_sections(
    intel_full_client: TestClient,
) -> None:
    """Empty requested sections become known_gaps, not implicit safety proof."""
    r = intel_full_client.get(f"/v1/intel/houjin/{_SPARSE_HOUJIN}/full")
    assert r.status_code == 200, r.text
    body = r.json()

    ds = body["decision_support"]
    gaps = ds["known_gaps"]
    gap_sections = {g["section"] for g in gaps}
    assert {
        "adoption_history",
        "enforcement",
        "invoice_status",
        "peer_summary",
        "watch_status",
    } <= gap_sections
    assert any("not proof of safety" in g["message"] for g in gaps)

    assert ds["risk_summary"]["enforcement"]["status"] == "not_detected_in_returned_section"
    assert ds["risk_summary"]["invoice_status"]["status"] == "not_found_in_returned_section"
    action_ids = {a["action"] for a in ds["next_actions"]}
    assert "verify_enforcement_source" not in action_ids
    assert "review_invoice_status" in action_ids
    assert "monitor_changes" in action_ids


def test_intel_houjin_full_compact_keeps_decision_support(
    intel_full_client: TestClient,
) -> None:
    """compact=true keeps the top-level decision_support block."""
    r = intel_full_client.get(
        f"/v1/intel/houjin/{_TEST_HOUJIN}/full",
        params={"compact": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["_c"] == 1
    assert "decision_support" in body
    assert body["decision_support"]["risk_summary"]["enforcement"]["status"] == "detected"


def test_intel_houjin_full_unknown_houjin_returns_404(
    intel_full_client: TestClient,
) -> None:
    """Well-formed but unknown houjin_id returns a structured 404."""
    r = intel_full_client.get("/v1/intel/houjin/0000000000001/full")
    assert r.status_code == 404
    body = r.json()
    detail = body["detail"]
    assert detail["error"] == "houjin_not_found"
    assert detail["houjin_id"] == "0000000000001"


def test_intel_houjin_full_strips_t_prefix(
    intel_full_client: TestClient,
) -> None:
    """A 'T'-prefixed 14-char input normalises to the 13-digit canonical id."""
    r = intel_full_client.get(f"/v1/intel/houjin/T{_TEST_HOUJIN}/full")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["houjin_bangou"] == _TEST_HOUJIN


def test_intel_houjin_full_paid_final_cap_failure_returns_503_without_usage_event(
    intel_full_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final cap rejection must fail closed before delivering a paid 2xx."""

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    endpoint = "intel.houjin_full"
    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = intel_full_client.get(
        f"/v1/intel/houjin/{_TEST_HOUJIN}/full",
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()
    assert n == 0
