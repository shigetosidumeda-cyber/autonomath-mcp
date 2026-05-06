"""Tests for GET /v1/intel/timeline/{program_id} — annual event timeline.

Coverage:
    1. Happy path — events sorted by date desc + envelope shape +
       summary_stats counts match per-type counts in events[].
    2. include_types filter — only the requested event type appears.
    3. year=past returns empty events but valid summary_stats (graceful
       degradation, not 404).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_timeline_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> tuple[Path, str, int]:
    """Build a tmp autonomath.db slice carrying timeline event substrate.

    Returns (db_path, target_program_id, target_year).

    Seeds:
      * `entity_id_map` mapping `UNI-tl-1` ↔ `program:test:tl-1`.
      * `am_entities` with the program row + JSIC E classification.
      * `am_industry_jsic` so the industry-level adoption rollup joins back.
      * `am_amendment_diff` 3 rows (1 high-impact eligibility, 1 high-impact
        amount, 1 low-impact other) inside the target year + 1 row outside.
      * `am_adoption_trend_monthly` 2 rows for JSIC E in the target year.
      * `am_enforcement_anomaly` 1 anomaly-flagged row + 1 normal.
      * `am_program_narrative_full` 1 narrative regen.
      * `am_adopted_company_features` joined via `jpi_adoption_records`.
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
        CREATE TABLE am_entities (
            canonical_id  TEXT PRIMARY KEY,
            record_kind   TEXT NOT NULL,
            primary_name  TEXT
        );
        CREATE TABLE am_industry_jsic (
            program_canonical_id  TEXT NOT NULL,
            jsic_major            TEXT NOT NULL,
            PRIMARY KEY (program_canonical_id, jsic_major)
        );
        CREATE TABLE am_amendment_diff (
            diff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id      TEXT NOT NULL,
            field_name     TEXT NOT NULL,
            prev_value     TEXT,
            new_value      TEXT,
            prev_hash      TEXT,
            new_hash       TEXT,
            detected_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url     TEXT
        );
        CREATE TABLE am_adoption_trend_monthly (
            year_month              TEXT NOT NULL,
            jsic_major              TEXT NOT NULL,
            adoption_count          INTEGER NOT NULL DEFAULT 0,
            distinct_houjin_count   INTEGER NOT NULL DEFAULT 0,
            distinct_program_count  INTEGER NOT NULL DEFAULT 0,
            trend_flag              TEXT,
            computed_at             TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (year_month, jsic_major)
        );
        CREATE TABLE am_enforcement_anomaly (
            prefecture_code         TEXT NOT NULL,
            jsic_major              TEXT NOT NULL,
            enforcement_count       INTEGER NOT NULL DEFAULT 0,
            z_score                 REAL,
            anomaly_flag            INTEGER NOT NULL DEFAULT 0,
            dominant_violation_kind TEXT,
            last_updated            TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (prefecture_code, jsic_major)
        );
        CREATE TABLE am_program_narrative_full (
            program_id                          TEXT PRIMARY KEY,
            narrative_md                        TEXT NOT NULL,
            counter_arguments_md                TEXT,
            generated_at                        TEXT NOT NULL DEFAULT (datetime('now')),
            model_used                          TEXT,
            content_hash                        TEXT,
            source_program_corpus_snapshot_id   TEXT
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
            computed_at             TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE jpi_adoption_records (
            houjin_bangou      TEXT,
            program_id         TEXT,
            announced_at       TEXT,
            amount_granted_yen INTEGER
        );
        """
    )

    target_uni = "UNI-tl-1"
    target_am = "program:test:tl-1"
    target_year = 2026

    conn.execute(
        "INSERT INTO entity_id_map (jpi_unified_id, am_canonical_id, "
        " match_method, confidence) VALUES (?, ?, ?, ?)",
        (target_uni, target_am, "exact_name", 1.0),
    )
    conn.execute(
        "INSERT INTO am_entities (canonical_id, record_kind, primary_name) VALUES (?, ?, ?)",
        (target_am, "program", "テスト製造業 DX 補助金 (timeline 用)"),
    )
    conn.execute(
        "INSERT INTO am_industry_jsic (program_canonical_id, jsic_major) VALUES (?, ?)",
        (target_am, "E"),
    )

    # 3 in-year amendment events + 1 outside.
    conn.executemany(
        "INSERT INTO am_amendment_diff "
        "(entity_id, field_name, prev_value, new_value, detected_at, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                target_am,
                "eligibility_text",
                "中小企業のみ",
                "中小企業 + 小規模事業者",
                "2026-03-15T10:00:00",
                "https://example.go.jp/koubo/v2.pdf",
            ),
            (
                target_am,
                "amount_max_man_yen",
                "1000",
                "1500",
                "2026-06-20T10:00:00",
                "https://example.go.jp/koubo/v3.pdf",
            ),
            (
                target_am,
                "title",  # low-impact field
                "旧名称",
                "新名称",
                "2026-09-10T10:00:00",
                None,
            ),
            # Outside the target year — must NOT appear.
            (
                target_am,
                "amount_max_man_yen",
                "500",
                "1000",
                "2024-01-15T10:00:00",
                None,
            ),
        ],
    )

    # 2 in-year adoption rollup rows + 1 wrong year.
    conn.executemany(
        "INSERT INTO am_adoption_trend_monthly "
        "(year_month, jsic_major, adoption_count, distinct_houjin_count, "
        " distinct_program_count, trend_flag) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-01", "E", 150, 145, 1, "increasing"),
            ("2026-04", "E", 25, 23, 1, "stable"),
            ("2025-08", "E", 99, 90, 1, "stable"),
        ],
    )

    # 1 anomaly row + 1 normal — both inside the year.
    conn.executemany(
        "INSERT INTO am_enforcement_anomaly "
        "(prefecture_code, jsic_major, enforcement_count, z_score, "
        " anomaly_flag, dominant_violation_kind, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("13000", "E", 80, 3.21, 1, "business_improvement", "2026-02-01T00:00:00"),
            ("01000", "E", 5, 0.4, 0, "investigation", "2026-08-01T00:00:00"),
        ],
    )

    # 1 narrative regen.
    conn.execute(
        "INSERT INTO am_program_narrative_full "
        "(program_id, narrative_md, generated_at, model_used, content_hash) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            target_uni,
            "本制度の概要 ...",
            "2026-05-05T12:00:00",
            "claude-opus-4-7",
            "sha256:abcdef1234567890",
        ),
    )

    # Adopted company features + adoption record join.
    conn.execute(
        "INSERT INTO am_adopted_company_features "
        "(houjin_bangou, adoption_count, last_adoption_at, "
        " dominant_prefecture, credibility_score) "
        "VALUES (?, ?, ?, ?, ?)",
        ("9999999999991", 6, "2026-07-01T00:00:00", "東京都", 0.92),
    )
    conn.execute(
        "INSERT INTO jpi_adoption_records "
        "(houjin_bangou, program_id, announced_at, amount_granted_yen) "
        "VALUES (?, ?, ?, ?)",
        ("9999999999991", target_am, "2026-07-01T00:00:00", 5_000_000),
    )

    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Seed jpintel.db `programs` row so the program_name lookup resolves.
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
                "テスト製造業 DX 補助金 (timeline 用)",
                None,
                "国",
                "経済産業省",
                "東京都",
                None,
                "補助金",
                None,
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
                None,
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

    return db_path, target_uni, target_year


@pytest.fixture()
def timeline_client(seeded_db: Path, seeded_timeline_db) -> TestClient:
    """TestClient with the timeline-substrate autonomath.db wired in."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test 1: Happy path — events sorted by date desc + envelope shape
# ---------------------------------------------------------------------------


def test_intel_timeline_happy_path_sorted_desc(
    timeline_client: TestClient, seeded_timeline_db
) -> None:
    _db, program_id, year = seeded_timeline_db
    r = timeline_client.get(
        f"/v1/intel/timeline/{program_id}",
        params={"year": year},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level shape.
    assert body["program_id"] == program_id
    assert body["program_name"]
    assert body["year"] == year
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 5  # 3 amendments + 2 adoptions + ...
    assert body["_billing_unit"] == 1
    assert "_disclaimer" in body
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert "data_quality" in body
    assert "missing_tables" in body["data_quality"]

    # Each event carries the canonical fields.
    for e in body["events"]:
        assert set(e.keys()) >= {
            "date",
            "type",
            "severity",
            "title",
            "summary",
            "evidence_url",
            "source_table",
        }
        assert e["type"] in {
            "amendment",
            "adoption",
            "enforcement",
            "narrative_update",
        }
        assert e["severity"] in {"low", "med", "high"}

    # Sorted by date desc.
    dates = [e["date"] for e in body["events"]]
    assert dates == sorted(dates, reverse=True), dates

    # summary_stats counts must match per-type counts in events[].
    stats = body["summary_stats"]
    assert stats["amendments"] == sum(1 for e in body["events"] if e["type"] == "amendment")
    assert stats["adoptions"] == sum(1 for e in body["events"] if e["type"] == "adoption")
    assert stats["enforcement_actions"] == sum(
        1 for e in body["events"] if e["type"] == "enforcement"
    )
    # 3 amendments inside year (one outside got filtered).
    assert stats["amendments"] == 3
    # 1 anomaly-flagged enforcement event = anomalies_flagged.
    assert stats["anomalies_flagged"] == 1
    # 1 narrative update.
    assert stats["narrative_updates"] == 1


# ---------------------------------------------------------------------------
# Test 2: include_types filter narrows the event stream
# ---------------------------------------------------------------------------


def test_intel_timeline_include_types_filter(
    timeline_client: TestClient, seeded_timeline_db
) -> None:
    _db, program_id, year = seeded_timeline_db
    r = timeline_client.get(
        f"/v1/intel/timeline/{program_id}",
        params=[("year", year), ("include_types", "amendment")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["include_types"] == ["amendment"]
    # Only amendment events allowed.
    types = {e["type"] for e in body["events"]}
    assert types == {"amendment"}, types
    # Other categories must report 0.
    assert body["summary_stats"]["adoptions"] == 0
    assert body["summary_stats"]["enforcement_actions"] == 0
    assert body["summary_stats"]["narrative_updates"] == 0


# ---------------------------------------------------------------------------
# Test 3: past year returns empty events but valid summary_stats
# ---------------------------------------------------------------------------


def test_intel_timeline_past_year_returns_empty(
    timeline_client: TestClient, seeded_timeline_db
) -> None:
    _db, program_id, _year = seeded_timeline_db
    r = timeline_client.get(
        f"/v1/intel/timeline/{program_id}",
        params={"year": 2010},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2010
    assert body["events"] == []
    stats = body["summary_stats"]
    # All counts zero — but the keys are still present (envelope contract).
    for k in (
        "amendments",
        "adoptions",
        "enforcement_actions",
        "anomalies_flagged",
        "narrative_updates",
    ):
        assert stats[k] == 0, (k, stats)
    # data_quality still present.
    assert "data_quality" in body
    assert isinstance(body["data_quality"]["missing_tables"], list)


# ---------------------------------------------------------------------------
# Test 4: paid final cap failure must fail closed without billing
# ---------------------------------------------------------------------------


def test_intel_timeline_paid_final_cap_failure_does_not_bill(
    timeline_client: TestClient,
    seeded_timeline_db,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api.middleware import customer_cap

    _db, program_id, year = seeded_timeline_db
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "intel.timeline"),
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

    r = timeline_client.get(
        f"/v1/intel/timeline/{program_id}",
        params={"year": year},
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


# ---------------------------------------------------------------------------
# Test 5: invalid include_types value returns 422
# ---------------------------------------------------------------------------


def test_intel_timeline_invalid_include_types_returns_422(
    timeline_client: TestClient, seeded_timeline_db
) -> None:
    _db, program_id, year = seeded_timeline_db
    r = timeline_client.get(
        f"/v1/intel/timeline/{program_id}",
        params=[("year", year), ("include_types", "not_a_real_type")],
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_include_types"
    assert "not_a_real_type" in str(detail)
