"""Tests for POST /v1/intel/diff composite endpoint.

The diff endpoint compares two entities of compatible kinds (program ×
program, houjin × houjin, law × law) and returns shared / unique /
conflict points joined across primary tables (programs / houjin_master /
am_law_article), the wave24 5-hop graph, the eligibility predicate set,
and the cross-namespace id bridge.

Coverage:
    1. program × program — shared + unique + conflict_points populated
       (+ predicate axis exercised via am_program_eligibility_predicate).
    2. houjin × houjin   — shared + unique + conflict_points populated
       across the houjin_master attribute set.
    3. envelope validation — corpus_snapshot_id + _disclaimer +
       _billing_unit + data_quality block all present, plus structural
       422 / 404 paths exercised.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures: augment seeded_db with extra programs / houjin / autonomath
# ---------------------------------------------------------------------------


def _seed_diff_programs(seeded_db: Path) -> None:
    """Seed two program rows with overlapping + diverging attributes.

    UNI-diff-prog-A and UNI-diff-prog-B share `tier='A'` and
    `program_kind='補助金'` but diverge on prefecture / authority /
    amount — gives us a real conflict_points set to assert on.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                "UNI-diff-prog-A",
                "東京都ものづくり助成事業 (DIFF テスト A)",
                "A",
                "東京都",
                "都道府県",
                "東京都産業労働局",
                "補助金",
                3000,
            ),
            (
                "UNI-diff-prog-B",
                "大阪府ものづくり助成事業 (DIFF テスト B)",
                "A",
                "大阪府",
                "都道府県",
                "大阪府商工労働部",
                "補助金",
                1500,
            ),
        ]
        for uid, name, tier, pref, lvl, authority, kind, amax in rows:
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
                "  enriched_json, source_mentions_json, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    name,
                    None,
                    lvl,
                    authority,
                    pref,
                    None,
                    kind,
                    None,
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
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_diff_houjin(seeded_db: Path) -> None:
    """Seed two houjin_master rows with one overlapping field + divergence."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                "1234567890123",
                "ABC 株式会社",
                "東京都千代田区1-1",
                "東京都",
                "千代田区",
                "株式会社",
                "2010-01-01",
                None,
                "2026-04-01",
                10,
                50_000_000,
            ),
            (
                "9876543210987",
                "XYZ 株式会社",
                "大阪府大阪市北区2-2",
                "大阪府",
                "大阪市北区",
                "株式会社",
                "2015-06-15",
                None,
                "2026-04-01",
                3,
                12_000_000,
            ),
        ]
        for r in rows:
            (
                hb,
                name,
                addr,
                pref,
                muni,
                ctype,
                established,
                closed,
                last_nta,
                total_adopt,
                total_yen,
            ) = r
            conn.execute(
                "INSERT OR IGNORE INTO houjin_master("
                "  houjin_bangou, normalized_name, alternative_names_json, "
                "  address_normalized, prefecture, municipality, "
                "  corporation_type, established_date, close_date, "
                "  last_updated_nta, data_sources_json, total_adoptions, "
                "  total_received_yen, notes, fetched_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    hb,
                    name,
                    None,
                    addr,
                    pref,
                    muni,
                    ctype,
                    established,
                    closed,
                    last_nta,
                    None,
                    total_adopt,
                    total_yen,
                    None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def diff_autonomath_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Build a tiny autonomath.db with the wave24 tables we exercise.

    Tables created:
      * am_id_bridge
      * am_5hop_graph
      * am_program_eligibility_predicate
      * am_law_article (so the law × law happy path can resolve)
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE am_id_bridge (
                id_a         TEXT NOT NULL,
                id_b         TEXT NOT NULL,
                bridge_kind  TEXT NOT NULL,
                confidence   REAL NOT NULL DEFAULT 1.0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (id_a, id_b)
            );
            CREATE TABLE am_5hop_graph (
                start_entity_id TEXT NOT NULL,
                hop INTEGER NOT NULL,
                end_entity_id TEXT NOT NULL,
                path TEXT NOT NULL,
                edge_kinds TEXT,
                PRIMARY KEY (start_entity_id, end_entity_id, hop)
            );
            CREATE TABLE am_program_eligibility_predicate (
                predicate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_unified_id TEXT NOT NULL,
                predicate_kind TEXT NOT NULL,
                operator TEXT NOT NULL,
                value_text TEXT,
                value_num REAL,
                value_json TEXT,
                is_required INTEGER NOT NULL DEFAULT 1,
                source_url TEXT,
                source_clause_quote TEXT,
                extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_law_article (
                article_id TEXT PRIMARY KEY,
                law_canonical_id TEXT NOT NULL,
                article_number TEXT,
                article_number_sort INTEGER,
                title TEXT,
                text_summary TEXT,
                text_full TEXT,
                effective_from TEXT,
                effective_until TEXT,
                last_amended TEXT,
                source_url TEXT,
                source_fetched_at TEXT
            );
            """
        )

        # 5hop neighbours: A's depth-1 has {n1, n2}; B's depth-1 has
        # {n2, n3}. shared = {n2}, unique_to_a = {n1}, unique_to_b = {n3}.
        for sid, hop, eid in (
            ("UNI-diff-prog-A", 1, "n1"),
            ("UNI-diff-prog-A", 1, "n2"),
            ("UNI-diff-prog-B", 1, "n2"),
            ("UNI-diff-prog-B", 1, "n3"),
        ):
            conn.execute(
                "INSERT INTO am_5hop_graph "
                "(start_entity_id, hop, end_entity_id, path, edge_kinds) "
                "VALUES (?,?,?,?,?)",
                (sid, hop, eid, "[]", '["program_law_ref"]'),
            )

        # Eligibility predicates: shared capital_max=50_000_000;
        # divergent employee_max (A=300, B=100) → conflict; unique to A
        # = jsic_in 'E', unique to B = region_in '大阪'.
        preds = [
            ("UNI-diff-prog-A", "capital_max", "<=", None, 50_000_000.0, None),
            ("UNI-diff-prog-B", "capital_max", "<=", None, 50_000_000.0, None),
            ("UNI-diff-prog-A", "employee_max", "<=", None, 300.0, None),
            ("UNI-diff-prog-B", "employee_max", "<=", None, 100.0, None),
            ("UNI-diff-prog-A", "jsic_in", "IN", "E", None, None),
            ("UNI-diff-prog-B", "region_in", "IN", "大阪", None, None),
        ]
        for r in preds:
            conn.execute(
                "INSERT INTO am_program_eligibility_predicate "
                "(program_unified_id, predicate_kind, operator, "
                " value_text, value_num, value_json) "
                "VALUES (?,?,?,?,?,?)",
                r,
            )

        # Law articles for the law × law happy path.
        for art_id, law_id, art_no, eff_from, last_am in (
            ("art:houjin:1", "law:houjinzeiho", "第1条", "2020-04-01", "2024-04-01"),
            ("art:houjin:2", "law:houjinzeiho", "第2条", "2020-04-01", "2025-04-01"),
            ("art:shotoku:1", "law:shotokuzeiho", "第1条", "2018-04-01", "2025-04-01"),
        ):
            conn.execute(
                "INSERT INTO am_law_article "
                "(article_id, law_canonical_id, article_number, "
                " effective_from, last_amended, source_url) "
                "VALUES (?,?,?,?,?,?)",
                (
                    art_id,
                    law_id,
                    art_no,
                    eff_from,
                    last_am,
                    f"https://example.gov/{law_id}/{art_no}",
                ),
            )

        # id_bridge: nothing controversial — just ensure the resolver
        # path returns the seed unchanged when no bridge row exists.
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path


@pytest.fixture()
def diff_client(
    seeded_db: Path,
    diff_autonomath_db: Path,  # noqa: ARG001 — autouse to seed the AM DB
) -> TestClient:
    """TestClient backed by the seeded jpintel.db + diff autonomath.db."""
    _seed_diff_programs(seeded_db)
    _seed_diff_houjin(seeded_db)
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test 1: program × program
# ---------------------------------------------------------------------------


def test_diff_program_x_program_populates_all_axes(diff_client: TestClient):
    """Two programs sharing tier+kind but diverging on prefecture / amount."""
    resp = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "program", "id": "UNI-diff-prog-A"},
            "b": {"type": "program", "id": "UNI-diff-prog-B"},
            "depth": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level shape
    assert body["a"]["id"] == "UNI-diff-prog-A"
    assert body["b"]["id"] == "UNI-diff-prog-B"
    assert body["a"]["resolved"] is True
    assert body["b"]["resolved"] is True
    assert body["depth"] == 2

    shared_fields = {item["field"] for item in body["shared_attrs"]}
    unique_a_fields = {item["field"] for item in body["unique_to_a"]}
    unique_b_fields = {item["field"] for item in body["unique_to_b"]}
    conflict_fields = {item["field"] for item in body["conflict_points"]}

    # Shared: tier + program_kind from the primary attrs axis.
    assert "tier" in shared_fields
    assert "program_kind" in shared_fields

    # Conflicts on diverging primary attrs.
    assert "prefecture" in conflict_fields
    assert "authority_name" in conflict_fields
    assert "amount_max_man_yen" in conflict_fields

    # 5hop axis populated with the synthetic neighbours.
    nbr_field = "am_5hop_graph.depth_2_neighbours"
    nbr_shared_values = {
        item["value"] for item in body["shared_attrs"] if item["field"] == nbr_field
    }
    assert nbr_shared_values == {"n2"}
    nbr_unique_a = {item["value"] for item in body["unique_to_a"] if item["field"] == nbr_field}
    nbr_unique_b = {item["value"] for item in body["unique_to_b"] if item["field"] == nbr_field}
    assert nbr_unique_a == {"n1"}
    assert nbr_unique_b == {"n3"}

    # Predicate axis populated:
    # - shared capital_max
    # - conflict on employee_max
    # - unique_to_a jsic_in, unique_to_b region_in
    assert "predicate.capital_max.<=" in shared_fields
    assert "predicate.employee_max.<=" in conflict_fields
    assert "predicate.jsic_in.IN" in unique_a_fields
    assert "predicate.region_in.IN" in unique_b_fields

    # data_quality must list the predicate axis
    dq = body["data_quality"]
    assert "am_program_eligibility_predicate" in dq["axes"]
    assert dq["a_predicate_count"] >= 3
    assert dq["b_predicate_count"] >= 3


# ---------------------------------------------------------------------------
# Test 2: houjin × houjin
# ---------------------------------------------------------------------------


def test_diff_houjin_x_houjin_populates_attrs(diff_client: TestClient):
    """Two houjin sharing corporation_type but diverging on every other field."""
    resp = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "houjin", "id": "1234567890123"},
            "b": {"type": "houjin", "id": "9876543210987"},
            "depth": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["a"]["resolved"] is True
    assert body["b"]["resolved"] is True

    shared_fields = {item["field"] for item in body["shared_attrs"]}
    conflict_fields = {item["field"] for item in body["conflict_points"]}

    # Both 株式会社 → corporation_type is in shared.
    assert "corporation_type" in shared_fields

    # Different prefecture / municipality / address → conflict.
    assert "prefecture" in conflict_fields
    assert "municipality" in conflict_fields
    assert "normalized_name" in conflict_fields

    # Predicate axis is NOT applied for houjin (only for program).
    assert "am_program_eligibility_predicate" not in body["data_quality"]["axes"]

    # T-prefix tolerance: a request with the leading T should still resolve.
    resp_t = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "houjin", "id": "T1234567890123"},
            "b": {"type": "houjin", "id": "T9876543210987"},
            "depth": 1,
        },
    )
    assert resp_t.status_code == 200, resp_t.text
    assert resp_t.json()["a"]["resolved"] is True


# ---------------------------------------------------------------------------
# Test 3: envelope validation
# ---------------------------------------------------------------------------


def test_diff_envelope_carries_required_metadata(diff_client: TestClient):
    """corpus_snapshot_id + corpus_checksum + _disclaimer + _billing_unit + 404/422."""
    resp = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "program", "id": "UNI-diff-prog-A"},
            "b": {"type": "program", "id": "UNI-diff-prog-B"},
            "depth": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Auditor reproducibility pair.
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body
    assert isinstance(body["corpus_snapshot_id"], str)
    assert body["corpus_checksum"].startswith("sha256:")

    # Disclaimer + billing_unit.
    assert body["_billing_unit"] == 1
    assert isinstance(body["_disclaimer"], str)
    assert "M&A" in body["_disclaimer"] or "デューデリジェンス" in body["_disclaimer"]

    # data_quality block must list the axes we touched.
    axes = body["data_quality"]["axes"]
    assert "primary_attrs" in axes
    assert "am_5hop_graph" in axes
    assert "am_id_bridge" in axes

    # 422 when kinds disagree.
    resp_bad = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "program", "id": "UNI-diff-prog-A"},
            "b": {"type": "houjin", "id": "1234567890123"},
            "depth": 1,
        },
    )
    assert resp_bad.status_code == 422, resp_bad.text
    assert resp_bad.json()["detail"]["error"] == "incompatible_entity_kinds"

    # 404 when both ids are unknown in the chosen axis.
    resp_404 = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "program", "id": "UNI-does-not-exist-xx"},
            "b": {"type": "program", "id": "UNI-also-does-not-exist-xx"},
            "depth": 1,
        },
    )
    assert resp_404.status_code == 404, resp_404.text
    assert resp_404.json()["detail"]["error"] == "both_entities_unresolved"


def test_diff_paid_final_cap_failure_returns_503_without_usage_event(
    diff_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api.middleware import customer_cap

    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "intel.diff"),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    before = usage_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    resp = diff_client.post(
        "/v1/intel/diff",
        json={
            "a": {"type": "program", "id": "UNI-diff-prog-A"},
            "b": {"type": "program", "id": "UNI-diff-prog-B"},
            "depth": 2,
        },
        headers={"X-API-Key": paid_key},
    )

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
