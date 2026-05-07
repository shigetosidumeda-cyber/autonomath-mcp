"""Tests for R8 (2026-05-07) timeline + trend endpoints.

Coverage:
    1. /v1/programs/{program_id}/timeline — yearly rollup + next_round
       + trend_flag + competition_proxy + envelope shape.
    2. /v1/cases/timeline_trend — JSIC × prefecture × N-year filter
       + trend_flag derivation.
    3. /v1/me/upcoming_rounds_for_my_profile — auth fence (401 anon)
       + profile-fan-out match against am_application_round.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _ensure_client_profiles_table(seeded_db: Path) -> None:
    """Apply migration 096 onto the test DB so the router has its table."""
    repo = Path(__file__).resolve().parent.parent
    mig = repo / "scripts" / "migrations" / "096_client_profiles.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(mig.read_text(encoding="utf-8"))
        c.execute("DELETE FROM client_profiles")
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def seeded_timeline_trend_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> tuple[Path, str, str]:
    """Build a tmp autonomath.db slice carrying timeline_trend substrate.

    Returns (db_path, target_uni_id, target_am_id).

    Seeds:
      * `entity_id_map` mapping `UNI-tt-1` ↔ `program:test:tt-1`.
      * `jpi_adoption_records` 6 rows across 3 years (2024, 2025, 2026).
      * `am_application_round` 3 rows: 1 closed (past) + 1 open (future)
        + 1 upcoming (further future).
      * `programs` row in jpintel.db so the primary_name resolves +
        target_types_json overlap with seeded client_profile.
      * `client_profiles` row attached to the paid_key so
        upcoming_rounds_for_my_profile has a profile to match against.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entity_id_map (
            jpi_unified_id   TEXT NOT NULL,
            am_canonical_id  TEXT NOT NULL,
            match_method     TEXT NOT NULL,
            confidence       REAL NOT NULL,
            matched_at       TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (jpi_unified_id, am_canonical_id)
        );
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            houjin_bangou        TEXT NOT NULL,
            program_id_hint      TEXT,
            program_name_raw     TEXT,
            company_name_raw     TEXT,
            round_label          TEXT,
            round_number         INTEGER,
            announced_at         TEXT,
            prefecture           TEXT,
            municipality         TEXT,
            project_title        TEXT,
            industry_raw         TEXT,
            industry_jsic_medium TEXT,
            amount_granted_yen   INTEGER,
            amount_project_total_yen INTEGER,
            source_url           TEXT NOT NULL,
            source_pdf_page      TEXT,
            fetched_at           TEXT NOT NULL,
            confidence           REAL NOT NULL DEFAULT 0.85,
            program_id           TEXT,
            program_id_match_method TEXT,
            program_id_match_score REAL
        );
        CREATE TABLE am_application_round (
            round_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id       TEXT NOT NULL,
            round_label             TEXT NOT NULL,
            round_seq               INTEGER,
            application_open_date   TEXT,
            application_close_date  TEXT,
            announced_date          TEXT,
            disbursement_start_date TEXT,
            budget_yen              INTEGER,
            status                  TEXT,
            source_url              TEXT,
            source_fetched_at       TEXT,
            UNIQUE (program_entity_id, round_label)
        );
        """
    )

    target_uni = "UNI-tt-1"
    target_am = "program:test:tt-1"
    conn.execute(
        "INSERT INTO entity_id_map (jpi_unified_id, am_canonical_id, "
        " match_method, confidence) VALUES (?, ?, ?, ?)",
        (target_uni, target_am, "exact_name", 1.0),
    )
    # 6 adoption rows: 1 in 2024, 2 in 2025, 3 in 2026 (increasing trend).
    rows = [
        ("9999999999991", target_am, "2024-03-15", "東京都", "E29", 5_000_000),
        ("9999999999992", target_am, "2025-03-15", "東京都", "E29", 6_000_000),
        ("9999999999993", target_am, "2025-09-15", "東京都", "E29", 7_000_000),
        ("9999999999994", target_am, "2026-01-15", "東京都", "E29", 8_000_000),
        ("9999999999995", target_am, "2026-02-15", "東京都", "E30", 9_000_000),
        ("9999999999996", target_am, "2026-03-15", "東京都", "E29", 10_000_000),
    ]
    conn.executemany(
        "INSERT INTO jpi_adoption_records "
        "(houjin_bangou, program_id, announced_at, prefecture, "
        " industry_jsic_medium, amount_granted_yen, source_url, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(*r, "https://example.go.jp/", "2026-05-01") for r in rows],
    )

    # 3 rounds: 1 closed (past), 1 open (close in 30 days), 1 upcoming (close in 90 days).
    from datetime import UTC, datetime, timedelta

    today = (datetime.now(UTC) + timedelta(hours=9)).date()
    past_close = (today - timedelta(days=30)).isoformat()
    open_close = (today + timedelta(days=30)).isoformat()
    upcoming_close = (today + timedelta(days=90)).isoformat()

    conn.executemany(
        "INSERT INTO am_application_round "
        "(program_entity_id, round_label, application_open_date, "
        " application_close_date, status, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                target_am,
                "第1回",
                "2026-01-01",
                past_close,
                "closed",
                "https://example.go.jp/r1",
            ),
            (
                target_am,
                "第2回",
                "2026-04-01",
                open_close,
                "open",
                "https://example.go.jp/r2",
            ),
            (
                target_am,
                "第3回",
                "2026-06-01",
                upcoming_close,
                "upcoming",
                "https://example.go.jp/r3",
            ),
        ],
    )

    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Seed jpintel.db `programs` row so primary_name resolves.
    jp_conn = sqlite3.connect(seeded_db)
    try:
        jp_conn.execute(
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
                target_uni,
                "テスト製造業 DX 補助金 (timeline_trend 用)",
                None,
                "国",
                "経済産業省",
                "東京都",
                None,
                "補助金",
                "https://example.go.jp/program",
                1500,
                None,
                None,
                None,
                "A",
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                '["製造業","設備投資"]',
                None,
                None,
                None,
                None,
                None,
                "2026-05-05T00:00:00",
            ),
        )
        jp_conn.commit()
    finally:
        jp_conn.close()

    return db_path, target_uni, target_am


@pytest.fixture()
def trend_client(seeded_db: Path, seeded_timeline_trend_db) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test 1: program timeline happy path
# ---------------------------------------------------------------------------


def test_program_timeline_returns_yearly_buckets_and_next_round(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    _db, target_uni, _am = seeded_timeline_trend_db
    r = trend_client.get(
        f"/v1/programs/{target_uni}/timeline",
        params={"years": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["program_id"] == target_uni
    assert body["program_name"]
    assert body["years"] == 5
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body

    # 5 yearly buckets must be present (gap-filled).
    yearly = body["yearly"]
    assert len(yearly) == 5
    years_present = [b["year"] for b in yearly]
    assert years_present == sorted(years_present), years_present

    # 6 adoptions total across the seeded data.
    total_adoptions = sum(b["adoption_count"] for b in yearly)
    assert total_adoptions == 6

    # next_round must point at the open round (close in 30d), not the past
    # closed one and not the upcoming-only one.
    nxt = body["next_round"]
    assert nxt is not None
    assert nxt["status"] == "open"
    assert nxt["round_label"] == "第2回"
    assert nxt["days_remaining"] is not None
    assert nxt["days_remaining"] > 0

    # Trend should be 'increasing' since 1 → 2 → 3 adoptions over the years.
    assert body["summary_stats"]["trend_flag"] in {"increasing", "stable"}
    # Total amount = 5+6+7+8+9+10 = 45M yen.
    assert body["summary_stats"]["total_amount_yen"] == 45_000_000


def test_program_timeline_unknown_program_returns_zero_buckets(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    r = trend_client.get(
        "/v1/programs/UNI-does-not-exist/timeline",
        params={"years": 3},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["program_id"] == "UNI-does-not-exist"
    # 3 buckets, all zero.
    assert len(body["yearly"]) == 3
    assert all(b["adoption_count"] == 0 for b in body["yearly"])
    assert body["next_round"] is None
    assert body["summary_stats"]["trend_flag"] == "n/a"


def test_program_timeline_invalid_years_returns_422(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    _db, target_uni, _am = seeded_timeline_trend_db
    r = trend_client.get(
        f"/v1/programs/{target_uni}/timeline",
        params={"years": 999},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Test 2: cases timeline trend
# ---------------------------------------------------------------------------


def test_cases_timeline_trend_filters_industry_and_prefecture(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    r = trend_client.get(
        "/v1/cases/timeline_trend",
        params={"industry": "E", "prefecture": "東京都", "years": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["industry"] == "E"
    assert body["prefecture"] == "東京都"
    assert body["years"] == 5
    assert body["_billing_unit"] == 1

    yearly = body["yearly"]
    assert len(yearly) == 5
    # All 6 seeded adoptions are JSIC E* prefix and 東京都 → captured.
    total = sum(b["adoption_count"] for b in yearly)
    assert total == 6

    # Different industry filter → should miss all rows.
    r2 = trend_client.get(
        "/v1/cases/timeline_trend",
        params={"industry": "Z", "prefecture": "東京都", "years": 5},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert sum(b["adoption_count"] for b in body2["yearly"]) == 0


def test_cases_timeline_trend_with_no_filter_aggregates_all(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    r = trend_client.get("/v1/cases/timeline_trend", params={"years": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    # No filter → still 6 adoptions in scope.
    assert sum(b["adoption_count"] for b in body["yearly"]) >= 6


# ---------------------------------------------------------------------------
# Test 3: upcoming_rounds_for_my_profile
# ---------------------------------------------------------------------------


def test_upcoming_rounds_for_my_profile_anon_returns_401(
    trend_client: TestClient, seeded_timeline_trend_db
) -> None:
    r = trend_client.get("/v1/me/upcoming_rounds_for_my_profile")
    assert r.status_code == 401, r.text


def test_upcoming_rounds_for_my_profile_with_paid_key_no_profiles_yet(
    trend_client: TestClient,
    seeded_timeline_trend_db,
    paid_key: str,
) -> None:
    r = trend_client.get(
        "/v1/me/upcoming_rounds_for_my_profile",
        params={"horizon_days": 60},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # No client_profiles yet → empty match list, profile_count=0.
    assert body["profile_count"] == 0
    assert body["matches"] == []
    assert body["summary_stats"]["total_matches"] == 0
    assert body["data_quality"]["no_profiles"] is True


def test_upcoming_rounds_for_my_profile_with_seeded_profile_matches(
    trend_client: TestClient,
    seeded_timeline_trend_db,
    seeded_db: Path,
    paid_key: str,
) -> None:
    # Seed a client_profile attached to the paid_key with 東京都 + target_types
    # overlapping the seeded program.
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO client_profiles "
            "(api_key_hash, name_label, jsic_major, prefecture, "
            " target_types_json, last_active_program_ids_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key_hash,
                "テスト顧問先",
                "E",
                "東京都",
                '["製造業","設備投資"]',
                "[]",
            ),
        )
        c.commit()
    finally:
        c.close()

    r = trend_client.get(
        "/v1/me/upcoming_rounds_for_my_profile",
        params={"horizon_days": 60},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_count"] == 1
    # The "open" round (close in 30d) is in scope; the "upcoming" round
    # (close in 90d) is outside the 60-day horizon.
    matches = body["matches"]
    assert len(matches) >= 1
    first = matches[0]
    assert first["profile_name_label"] == "テスト顧問先"
    assert first["round_label"] == "第2回"
    assert (
        "prefecture_match" in first["match_reasons"]
        or "target_types_overlap" in first["match_reasons"]
    )
    assert body["summary_stats"]["profiles_with_match"] == 1
