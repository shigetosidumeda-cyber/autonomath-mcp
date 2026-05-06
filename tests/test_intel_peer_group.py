"""Tests for POST /v1/intel/peer_group — 同業他社 peer-group endpoint.

Three contracts covered:

1. Happy path with houjin_id — registered法人 lookup returns N peers with
   the full envelope (similarity_score / adoption_count / total_amount /
   top_categories / statistical_context / recommended_programs_peers_used).
2. Happy path with houjin_attributes (no houjin_id) — synthetic / 未登録
   profile path matches peers via the jsic + prefecture + capital/employees
   axes alone.
3. Statistical_context validates the percentile + peer_avg_adoption_count
   computation against a known cohort.

The fixture builds a minimal autonomath.db slice (houjin_master +
am_adopted_company_features + jpi_adoption_records + jpi_programs +
am_entity_facts) so similarity scoring + per-peer enrichment + the
peer_recommended_programs join all have real rows to walk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path  # noqa: TC003

import pytest

# ---------------------------------------------------------------------------
# Fixture: tiny autonomath.db with 1 query houjin + 6 peers + 3 programs.
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_peer_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> tuple[Path, str]:
    """Build a minimal autonomath.db slice for peer-group tests.

    Returns (db_path, query_houjin_bangou). The query houjin lives at
    ``"1010001000001"`` and has profile (jsic=E, pref=東京都, capital=10M,
    employees=20). 6 peer houjin in JSIC=E or pref=東京都 with varied
    capital/employees so similarity scores differentiate.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT NOT NULL,
            alternative_names_json TEXT,
            address_normalized TEXT,
            prefecture TEXT,
            municipality TEXT,
            corporation_type TEXT,
            established_date TEXT,
            close_date TEXT,
            last_updated_nta TEXT,
            data_sources_json TEXT,
            total_adoptions INTEGER NOT NULL DEFAULT 0,
            total_received_yen INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            fetched_at TEXT NOT NULL,
            jsic_major TEXT,
            jsic_middle TEXT,
            jsic_minor TEXT,
            jsic_assigned_at TEXT,
            jsic_assigned_method TEXT
        );
        CREATE TABLE am_adopted_company_features (
            houjin_bangou TEXT PRIMARY KEY,
            adoption_count INTEGER NOT NULL DEFAULT 0,
            distinct_program_count INTEGER NOT NULL DEFAULT 0,
            first_adoption_at TEXT,
            last_adoption_at TEXT,
            dominant_jsic_major TEXT,
            dominant_prefecture TEXT,
            enforcement_count INTEGER NOT NULL DEFAULT 0,
            invoice_registered INTEGER NOT NULL DEFAULT 0,
            loan_count INTEGER NOT NULL DEFAULT 0,
            credibility_score REAL,
            computed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE am_geo_industry_density (
            prefecture_code TEXT NOT NULL,
            jsic_major TEXT NOT NULL,
            program_count INTEGER NOT NULL DEFAULT 0,
            program_tier_S INTEGER NOT NULL DEFAULT 0,
            program_tier_A INTEGER NOT NULL DEFAULT 0,
            verified_count INTEGER NOT NULL DEFAULT 0,
            adoption_count INTEGER NOT NULL DEFAULT 0,
            enforcement_count INTEGER NOT NULL DEFAULT 0,
            loan_count INTEGER NOT NULL DEFAULT 0,
            density_score REAL,
            last_updated TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (prefecture_code, jsic_major)
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_json TEXT,
            field_value_numeric REAL,
            field_kind TEXT NOT NULL DEFAULT 'number',
            unit TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_am_facts_field ON am_entity_facts(field_name);
        CREATE INDEX idx_am_facts_entity ON am_entity_facts(entity_id);
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            houjin_bangou TEXT NOT NULL,
            program_id_hint TEXT,
            program_name_raw TEXT,
            company_name_raw TEXT,
            round_label TEXT,
            round_number INTEGER,
            announced_at TEXT,
            prefecture TEXT,
            municipality TEXT,
            project_title TEXT,
            industry_raw TEXT,
            industry_jsic_medium TEXT,
            amount_granted_yen INTEGER,
            amount_project_total_yen INTEGER,
            source_url TEXT NOT NULL,
            source_pdf_page TEXT,
            fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.85,
            program_id TEXT,
            program_id_match_method TEXT,
            program_id_match_score REAL
        );
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            program_kind TEXT,
            tier TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )

    # Seed 1 query houjin + 6 peers. The query houjin lives at
    # 1010001000001; peers live at 1010001000002..1010001000007.
    houjin_seeds = [
        # bangou,            name,           jsic, pref,        cap_yen,    emp
        ("1010001000001", "クエリ株式会社", "E", "東京都", 10_000_000, 20),
        ("1010001000002", "ピア東京E同規模", "E", "東京都", 12_000_000, 18),
        ("1010001000003", "ピア東京E大規模", "E", "東京都", 500_000_000, 200),
        ("1010001000004", "ピア大阪E同規模", "E", "大阪府", 15_000_000, 25),
        ("1010001000005", "ピア東京F同規模", "F", "東京都", 11_000_000, 22),
        ("1010001000006", "ピア東京E微小", "E", "東京都", 500_000, 2),
        ("1010001000007", "ピア福岡E大規模", "E", "福岡県", 200_000_000, 100),
    ]
    for bangou, name, jsic, pref, cap, emp in houjin_seeds:
        conn.execute(
            "INSERT INTO houjin_master(houjin_bangou, normalized_name, "
            "  prefecture, jsic_major, fetched_at) "
            "VALUES (?, ?, ?, ?, '2026-05-04T00:00:00Z')",
            (bangou, name, pref, jsic),
        )
        # Use 1-based adoption counts so the percentile distribution is
        # not all-zero.
        adoption = 1 if bangou == "1010001000001" else (int(bangou[-1]) + 1)
        conn.execute(
            "INSERT INTO am_adopted_company_features(houjin_bangou, "
            "  adoption_count, distinct_program_count, dominant_jsic_major, "
            "  dominant_prefecture) VALUES (?, ?, ?, ?, ?)",
            (bangou, adoption, adoption, jsic, pref),
        )
        # capital + employees facts under entity_id `houjin:<bangou>`.
        conn.execute(
            "INSERT INTO am_entity_facts(entity_id, field_name, "
            "  field_value_numeric, field_kind, unit) "
            "VALUES (?, 'corp.capital_amount', ?, 'amount', 'yen')",
            (f"houjin:{bangou}", float(cap)),
        )
        conn.execute(
            "INSERT INTO am_entity_facts(entity_id, field_name, "
            "  field_value_numeric, field_kind, unit) "
            "VALUES (?, 'corp.employee_count', ?, 'number', 'persons')",
            (f"houjin:{bangou}", float(emp)),
        )

    # 3 programs, 4 distinct adoption records spanning peers so the
    # peer_recommended_programs aggregator has rates to compute.
    programs = [
        ("UNI-prog-a", "ものづくり補助金", "補助金"),
        ("UNI-prog-b", "事業再構築補助金", "補助金"),
        ("UNI-prog-c", "IT導入補助金", "補助金"),
    ]
    for uid, name, kind in programs:
        conn.execute(
            "INSERT INTO jpi_programs(unified_id, primary_name, program_kind, "
            "  tier, updated_at) VALUES (?, ?, ?, 'A', '2026-05-04T00:00:00Z')",
            (uid, name, kind),
        )

    # Adoptions: peer 02 = prog-a + prog-b, peer 03 = prog-a, peer 04 = prog-a,
    # peer 05 = prog-b, peer 06 = prog-c, peer 07 = prog-a + prog-c.
    adoptions = [
        ("1010001000002", "UNI-prog-a", 5_000_000),
        ("1010001000002", "UNI-prog-b", 8_000_000),
        ("1010001000003", "UNI-prog-a", 6_000_000),
        ("1010001000004", "UNI-prog-a", 5_500_000),
        ("1010001000005", "UNI-prog-b", 7_500_000),
        ("1010001000006", "UNI-prog-c", 1_000_000),
        ("1010001000007", "UNI-prog-a", 6_500_000),
        ("1010001000007", "UNI-prog-c", 2_000_000),
    ]
    for bangou, prog, amount in adoptions:
        conn.execute(
            "INSERT INTO jpi_adoption_records(houjin_bangou, program_id, "
            "  amount_granted_yen, source_url, fetched_at, prefecture) "
            "VALUES (?, ?, ?, 'https://example.com/seed', "
            "'2026-05-04T00:00:00Z', '東京都')",
            (bangou, prog, amount),
        )

    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    # Drop any cached per-thread autonomath connection from prior tests so
    # the patched AUTONOMATH_DB_PATH actually opens the seeded fixture file.
    from jpintel_mcp.mcp.autonomath_tools.db import close_all

    close_all()
    return db_path, "1010001000001"


# ---------------------------------------------------------------------------
# Test 1: happy path with houjin_id
# ---------------------------------------------------------------------------


def test_peer_group_with_houjin_id(client, seeded_peer_db):
    """houjin_id supplied → 5 peers returned with full envelope shape."""
    _db_path, query_bangou = seeded_peer_db
    resp = client.post(
        "/v1/intel/peer_group",
        json={
            "houjin_id": query_bangou,
            "peer_count": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level shape.
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body
    assert "景表法" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body

    # Query houjin profile.
    qh = body["query_houjin"]
    assert qh["id"] == query_bangou
    assert qh["jsic"] == "E"
    assert qh["prefecture"] == "東京都"
    assert qh["capital"] == 10_000_000
    assert qh["employees"] == 20

    # Peers — exactly 5 returned (peer_count) and the query houjin must
    # never appear in its own peer list.
    peers = body["peers"]
    assert isinstance(peers, list)
    assert len(peers) == 5
    peer_ids = {p["houjin_id"] for p in peers}
    assert query_bangou not in peer_ids

    # Each peer carries the canonical fields.
    expected_peer_keys = {
        "houjin_id",
        "name",
        "similarity_score",
        "axes_compared",
        "adoption_count",
        "total_amount_estimated",
        "top_categories",
    }
    for p in peers:
        missing = expected_peer_keys - set(p.keys())
        assert not missing, f"peer missing keys: {sorted(missing)}"
        assert 0.0 <= float(p["similarity_score"]) <= 1.0
        assert isinstance(p["top_categories"], list)
        assert "jsic" in p["axes_compared"]
        assert "prefecture" in p["axes_compared"]

    # Peers are sorted by similarity desc.
    sims = [float(p["similarity_score"]) for p in peers]
    assert sims == sorted(sims, reverse=True)

    # Top peer must be the same-JSIC + same-prefecture + same-capital-bucket
    # candidate (1010001000002 = ピア東京E同規模, cap=12M → bucket 7 same as
    # query 10M → bucket 7, emp 18 → bucket 1 same as query 20 → bucket 1).
    assert peers[0]["houjin_id"] == "1010001000002"
    assert peers[0]["similarity_score"] == 1.0

    # Statistical context block.
    sc = body["statistical_context"]
    assert sc["peer_count"] == 5
    assert sc["peer_avg_adoption_count"] is not None
    assert sc["query_adoption_count"] == 1
    # Percentile is between 0 and 100.
    assert 0.0 <= float(sc["query_percentile"]) <= 100.0

    # Recommended programs (peers used) — should include prog-a (4 of 5
    # peers adopted it across the wider cohort).
    rec = body["recommended_programs_peers_used"]
    assert isinstance(rec, list)
    assert len(rec) >= 1
    rec_ids = {r["program_id"] for r in rec}
    assert "UNI-prog-a" in rec_ids
    top_rec = rec[0]
    assert top_rec["program_id"] == "UNI-prog-a"
    assert top_rec["peer_adopter_count"] >= 1
    assert 0.0 <= float(top_rec["peer_adoption_rate"]) <= 1.0


# ---------------------------------------------------------------------------
# Test 2: happy path with houjin_attributes (未登録 path)
# ---------------------------------------------------------------------------


def test_peer_group_with_houjin_attributes_only(client, seeded_peer_db):
    """No houjin_id → attributes-only path matches via jsic + prefecture."""
    _db_path, _query_bangou = seeded_peer_db
    resp = client.post(
        "/v1/intel/peer_group",
        json={
            "houjin_attributes": {
                "name": "新設の合同会社",
                "capital": 10_000_000,
                "employees": 20,
                "jsic": "E",
                "prefecture": "東京都",
            },
            "peer_count": 3,
            "comparison_axes": ["adoption_count", "total_amount"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    qh = body["query_houjin"]
    assert qh["id"] is None
    assert qh["name"] == "新設の合同会社"
    assert qh["jsic"] == "E"
    assert qh["prefecture"] == "東京都"
    assert qh["capital"] == 10_000_000
    assert qh["employees"] == 20

    peers = body["peers"]
    assert len(peers) == 3
    # Best match is the same-bucket peer 02.
    assert peers[0]["houjin_id"] == "1010001000002"
    assert peers[0]["similarity_score"] == 1.0
    # comparison_axes is honoured: category_diversity NOT requested.
    assert "category_diversity" not in peers[0]["axes_compared"]
    assert "adoption_count" in peers[0]["axes_compared"]
    assert "total_amount" in peers[0]["axes_compared"]

    # Statistical context still populates even on the 未登録 path.
    sc = body["statistical_context"]
    assert sc["peer_count"] == 3
    # query_adoption_count is 0 because the attribute path has no bangou
    # to look up against am_adopted_company_features.
    assert sc["query_adoption_count"] == 0


# ---------------------------------------------------------------------------
# Test 3: statistical_context computation
# ---------------------------------------------------------------------------


def test_peer_group_statistical_context_math(client, seeded_peer_db):
    """peer_avg_adoption_count + percentile compute correctly."""
    _db_path, query_bangou = seeded_peer_db
    resp = client.post(
        "/v1/intel/peer_group",
        json={
            "houjin_id": query_bangou,
            "peer_count": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sc = body["statistical_context"]

    peers = body["peers"]
    expected_avg = round(sum(p["adoption_count"] for p in peers) / len(peers), 2)
    assert sc["peer_avg_adoption_count"] == expected_avg

    # The query houjin's adoption count (1) is below every peer's count
    # (3..8 in the seed), so the percentile must be at the bottom of the
    # distribution. With the midrank convention used in the implementation,
    # 1 is strictly less than every peer count, so percentile = 0.0.
    assert sc["query_adoption_count"] == 1
    assert sc["query_percentile"] == 0.0

    # peer_avg_amount is the mean of total_amount_estimated across peers
    # (excluding peers with null total_amount).
    amounts = [
        p["total_amount_estimated"] for p in peers if p["total_amount_estimated"] is not None
    ]
    if amounts:
        expected_amount = int(round(sum(amounts) / len(amounts)))
        assert sc["peer_avg_amount"] == expected_amount


# ---------------------------------------------------------------------------
# Test 4 (bonus): validation — neither houjin_id nor houjin_attributes
# ---------------------------------------------------------------------------


def test_peer_group_requires_one_of(client, seeded_peer_db):
    """Empty payload → 422 from the model_validator."""
    resp = client.post(
        "/v1/intel/peer_group",
        json={"peer_count": 5},
    )
    assert resp.status_code == 422, resp.text


def test_peer_group_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_peer_db,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid final-cap rejection must not silently return an unmetered 200."""
    _db_path, query_bangou = seeded_peer_db

    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    endpoint = "intel.peer_group"

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    resp = client.post(
        "/v1/intel/peer_group",
        json={
            "houjin_id": query_bangou,
            "peer_count": 5,
        },
        headers={"X-API-Key": paid_key},
    )

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
