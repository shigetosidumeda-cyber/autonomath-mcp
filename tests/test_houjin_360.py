"""Tests for GET /v1/houjin/{houjin_bangou}/360 unified surface.

The endpoint joins houjin_master + jpi_adoption_records + am_enforcement_detail
+ bids + jpi_invoice_registrants + am_amendment_diff + customer_watches into a
single envelope and projects a deterministic 3-axis scoring block.

Coverage:
  1. Happy path — 200 + every section + 3-axis scores in [0, 1].
  2. 422 — malformed houjin_bangou.
  3. 404 — unknown but well-formed bangou.
  4. T-prefix normalisation.
  5. Empty / sparse houjin still returns scores (compliance maxed when
     enforcement.total == 0 and invoice 'active'); risk close to 0.
  6. Bids_won surface — top-N by awarded amount, total tally.
  7. Disclaimer envelope carries the §52 / §72 / §1 fence.
  8. _billing_unit == 1 regardless of limit.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path


_TEST_HOUJIN = "1234567890123"
_TEST_INVOICE = "T1234567890123"
_SPARSE_HOUJIN = "9876543210987"
_CLEAN_HOUJIN = "1111222233334"


def _seed_jpintel_bids_and_watches(jpintel_db: Path) -> None:
    """Add bids + customer_watches rows on the jpintel-side seeded DB.

    The base seeded_db fixture runs init_db schema. Both ``bids`` and
    ``customer_watches`` are part of that schema, so the table likely
    already exists; we just INSERT idempotently. CREATE TABLE IF NOT
    EXISTS is added for safety on stripped-down test schemas.
    """
    conn = sqlite3.connect(jpintel_db)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bids (
                unified_id TEXT PRIMARY KEY,
                bid_title TEXT NOT NULL,
                bid_kind TEXT NOT NULL,
                procuring_entity TEXT NOT NULL,
                procuring_houjin_bangou TEXT,
                ministry TEXT,
                prefecture TEXT,
                program_id_hint TEXT,
                announcement_date TEXT,
                question_deadline TEXT,
                bid_deadline TEXT,
                decision_date TEXT,
                budget_ceiling_yen INTEGER,
                awarded_amount_yen INTEGER,
                winner_name TEXT,
                winner_houjin_bangou TEXT,
                participant_count INTEGER,
                bid_description TEXT,
                eligibility_conditions TEXT,
                classification_code TEXT,
                source_url TEXT NOT NULL,
                source_excerpt TEXT,
                source_checksum TEXT,
                confidence REAL NOT NULL DEFAULT 0.9,
                fetched_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS customer_watches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_hash    TEXT NOT NULL,
                watch_kind      TEXT NOT NULL,
                target_id       TEXT NOT NULL,
                registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
                last_event_at   TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                disabled_at     TEXT,
                disabled_reason TEXT
            );
            """
        )
        # Two won bids for the test houjin.
        conn.execute(
            "INSERT OR REPLACE INTO bids (unified_id, bid_title, bid_kind, "
            " procuring_entity, ministry, prefecture, decision_date, "
            " awarded_amount_yen, budget_ceiling_yen, winner_name, "
            " winner_houjin_bangou, classification_code, source_url, "
            " confidence, fetched_at, updated_at) "
            "VALUES ('BID-aabbccdd01', '令和7年度 ○○調達', 'open', "
            "        '国土交通省関東地方整備局', '国土交通省', NULL, "
            "        '2025-04-15', 18000000, 20000000, '株式会社テスト', "
            "        ?, '役務', "
            "        'https://www.e-procurement.go.jp/x/test1', 0.95, "
            "        '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (_TEST_HOUJIN,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO bids (unified_id, bid_title, bid_kind, "
            " procuring_entity, ministry, prefecture, decision_date, "
            " awarded_amount_yen, budget_ceiling_yen, winner_name, "
            " winner_houjin_bangou, classification_code, source_url, "
            " confidence, fetched_at, updated_at) "
            "VALUES ('BID-aabbccdd02', '令和6年度 物品調達', 'selective', "
            "        '東京都産業労働局', NULL, '東京都', "
            "        '2024-08-20', 5000000, 6000000, '株式会社テスト', "
            "        ?, '物品', "
            "        'https://www.e-procurement.go.jp/x/test2', 0.95, "
            "        '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (_TEST_HOUJIN,),
        )
        # 2 active watches on the test houjin.
        conn.execute(
            "DELETE FROM customer_watches WHERE watch_kind = 'houjin' AND target_id = ?",
            (_TEST_HOUJIN,),
        )
        for tag in ("test-key-hash-a", "test-key-hash-b"):
            conn.execute(
                "INSERT INTO customer_watches (api_key_hash, watch_kind, "
                " target_id, status, last_event_at) "
                "VALUES (?, 'houjin', ?, 'active', '2026-05-06T12:00:00Z')",
                (tag, _TEST_HOUJIN),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def seeded_houjin_360_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> Path:
    """Build an autonomath.db slice with all substrate tables the endpoint reads."""
    db_path = tmp_path / "autonomath_houjin_360.db"
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

        # === Test houjin: rich data spanning every surface. ===
        conn.execute(
            "INSERT INTO houjin_master (houjin_bangou, normalized_name, "
            " address_normalized, prefecture, municipality, corporation_type, "
            " established_date, jsic_major, jsic_middle, total_adoptions, "
            " total_received_yen, last_updated_nta, fetched_at) "
            "VALUES (?, '株式会社テスト', '東京都千代田区1-1', '東京都', "
            " '千代田区', '株式会社', '2010-04-01', 'E', 'E25', 3, "
            " 12000000, '2026-05-01', '2026-05-01T00:00:00Z')",
            (_TEST_HOUJIN,),
        )
        conn.executemany(
            "INSERT INTO am_entity_facts (entity_id, field_name, "
            " field_value_text, field_value_numeric, unit, field_kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.capital_amount",
                    None,
                    50_000_000,
                    "JPY",
                    "money",
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.employee_count",
                    None,
                    42,
                    "person",
                    "count",
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.representative",
                    "代表 太郎",
                    None,
                    None,
                    "text",
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.company_url",
                    "https://example.test/",
                    None,
                    None,
                    "url",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO jpi_adoption_records (houjin_bangou, program_id, "
            " program_name_raw, amount_granted_yen, announced_at, prefecture, "
            " industry_jsic_medium, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    _TEST_HOUJIN,
                    "UNI-test-mono-1",
                    "ものづくり高度化補助金",
                    8_000_000,
                    "2025-03-01",
                    "東京都",
                    "E25",
                    "https://example.test/adoption/1",
                ),
                (
                    _TEST_HOUJIN,
                    "UNI-test-it-1",
                    "IT 導入補助金",
                    3_000_000,
                    "2024-09-15",
                    "東京都",
                    "E25",
                    "https://example.test/adoption/2",
                ),
                (
                    _TEST_HOUJIN,
                    "UNI-test-jisedai-1",
                    "次世代 GX",
                    1_000_000,
                    "2023-08-01",
                    "神奈川県",
                    "E25",
                    "https://example.test/adoption/3",
                ),
            ],
        )
        # Two enforcement records — one low (warning), one medium (exclude).
        conn.executemany(
            "INSERT INTO am_enforcement_detail (entity_id, houjin_bangou, "
            " target_name, enforcement_kind, issuing_authority, issuance_date, "
            " amount_yen, reason_summary, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"houjin:{_TEST_HOUJIN}",
                    _TEST_HOUJIN,
                    "株式会社テスト",
                    "subsidy_exclude",
                    "経済産業省",
                    "2024-06-01",
                    None,
                    "補助対象除外",
                    "https://example.test/enforcement/1",
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    _TEST_HOUJIN,
                    "株式会社テスト",
                    "warning",
                    "東京都産業労働局",
                    "2023-11-12",
                    None,
                    "軽微な警告",
                    "https://example.test/enforcement/2",
                ),
            ],
        )
        # Active invoice.
        conn.execute(
            "INSERT INTO jpi_invoice_registrants ("
            " invoice_registration_number, houjin_bangou, normalized_name, "
            " prefecture, registered_date, registrant_kind, source_url, "
            " fetched_at, updated_at) "
            "VALUES (?, ?, '株式会社テスト', '東京都', '2023-10-01', "
            "        'corporation', 'https://www.invoice-kohyo.nta.go.jp/', "
            "        '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (_TEST_INVOICE, _TEST_HOUJIN),
        )
        # Recent news = amendment diff.
        conn.executemany(
            "INSERT INTO am_amendment_diff (entity_id, field_name, "
            " prev_value, new_value, detected_at, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.legal_name",
                    "株式会社テスト旧",
                    "株式会社テスト",
                    "2026-04-15T10:00:00Z",
                    "https://example.test/diff/1",
                ),
                (
                    f"houjin:{_TEST_HOUJIN}",
                    "corp.location",
                    "東京都新宿区",
                    "東京都千代田区1-1",
                    "2026-03-20T14:00:00Z",
                    "https://example.test/diff/2",
                ),
            ],
        )

        # === Clean houjin: active invoice, 0 enforcement. ===
        conn.execute(
            "INSERT INTO houjin_master (houjin_bangou, normalized_name, "
            " address_normalized, prefecture, municipality, corporation_type, "
            " established_date, jsic_major, total_adoptions, total_received_yen, "
            " fetched_at) "
            "VALUES (?, '株式会社クリーン', '大阪府大阪市1-1', '大阪府', "
            " '大阪市', '株式会社', '2018-01-01', 'F', 0, 0, "
            " '2026-05-01T00:00:00Z')",
            (_CLEAN_HOUJIN,),
        )
        conn.execute(
            "INSERT INTO jpi_invoice_registrants ("
            " invoice_registration_number, houjin_bangou, normalized_name, "
            " prefecture, registered_date, registrant_kind, source_url, "
            " fetched_at, updated_at) "
            "VALUES ('T1111222233334', ?, '株式会社クリーン', '大阪府', "
            "        '2023-10-01', 'corporation', "
            "        'https://www.invoice-kohyo.nta.go.jp/', "
            "        '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (_CLEAN_HOUJIN,),
        )

        conn.commit()
    finally:
        conn.close()

    # Pin the autonomath path so the endpoint reads our slice.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # Wire jpintel-side bids + customer_watches.
    _seed_jpintel_bids_and_watches(seeded_db)
    return db_path


@pytest.fixture()
def houjin_360_client(seeded_houjin_360_db: Path) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_houjin_360_happy_path_returns_unified_envelope(
    houjin_360_client: TestClient,
) -> None:
    """Known 法人番号 returns master + adoption + enforcement + bids_won + invoice + news + watch + scores."""
    r = houjin_360_client.get(f"/v1/houjin/{_TEST_HOUJIN}/360")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level envelope keys.
    assert body["houjin_bangou"] == _TEST_HOUJIN
    assert body["_billing_unit"] == 1
    disc = body["_disclaimer"]
    assert "税理士法 §52" in disc
    assert "弁護士法 §72" in disc
    assert "行政書士法 §1" in disc

    # master
    master = body["master"]
    assert master is not None
    assert master["name"] == "株式会社テスト"
    assert master["prefecture"] == "東京都"
    assert master["capital_yen"] == 50_000_000
    assert master["employees"] == 42
    assert master["jsic_major"] == "E"
    assert master["active"] is True
    assert master["representative"] == "代表 太郎"

    # adoption_records
    adopt = body["adoption_records"]
    assert adopt["total"] == 3
    assert adopt["total_amount_yen"] == 12_000_000
    assert len(adopt["records"]) == 3
    # Sorted by amount DESC.
    assert adopt["records"][0]["amount_granted_yen"] == 8_000_000

    # enforcement_cases — one medium + one low → max_severity == 'medium'.
    enf = body["enforcement_cases"]
    assert enf["total"] == 2
    assert enf["max_severity"] == "medium"
    severities = {r["severity"] for r in enf["records"]}
    assert "medium" in severities
    assert "low" in severities

    # bids_won
    bids = body["bids_won"]
    assert bids["total"] == 2
    assert bids["total_awarded_yen"] == 23_000_000
    # Top-N sorted by awarded amount DESC.
    assert bids["records"][0]["awarded_amount_yen"] == 18_000_000
    assert bids["records"][0]["procuring_entity"] == "国土交通省関東地方整備局"

    # invoice_registrant_status
    inv = body["invoice_registrant_status"]
    assert inv["registered"] is True
    assert inv["registration_no"] == _TEST_INVOICE
    assert inv["status"] == "active"

    # recent_news
    news = body["recent_news"]
    assert isinstance(news, list)
    assert len(news) == 2
    assert news[0]["detected_at"].startswith("2026-04-15")  # most recent first

    # watch_alerts
    watch = body["watch_alerts"]
    assert watch["is_watched"] is True
    assert watch["watch_subscribers"] == 2
    assert watch["last_amendment_at"] == "2026-04-15T10:00:00Z"
    assert len(watch["recent_alerts"]) >= 1

    # scores — 3-axis composite.
    scores = body["scores"]
    for axis in ("risk_score", "credit_score", "compliance_score"):
        assert axis in scores
        v = scores[axis]["value"]
        assert 0.0 <= float(v) <= 1.0
        # Each axis returns a components dict + weights dict.
        assert isinstance(scores[axis]["components"], dict)
        assert isinstance(scores[axis]["weights"], dict)

    # risk_score: enforcement medium + active invoice + 2 news → > 0.
    assert scores["risk_score"]["value"] > 0.0
    # credit_score: 3 adoptions (¥12M) + 2 bids (¥23M) + 50M capital + 42 emp.
    assert scores["credit_score"]["value"] > 0.20
    # compliance_score: invoice active + max_severity medium + master complete.
    assert 0.30 < scores["compliance_score"]["value"] < 1.0


def test_houjin_360_clean_houjin_inflates_compliance_drops_risk(
    houjin_360_client: TestClient,
) -> None:
    """Clean houjin (no enforcement, active invoice) → high compliance, low risk."""
    r = houjin_360_client.get(f"/v1/houjin/{_CLEAN_HOUJIN}/360")
    assert r.status_code == 200, r.text
    body = r.json()
    scores = body["scores"]
    # No enforcement + no news → risk dominated by 0 or near-0.
    assert scores["risk_score"]["value"] < 0.10
    # Compliance dominated by enforcement=1.0 + invoice=1.0 → high.
    assert scores["compliance_score"]["value"] > 0.70


def test_houjin_360_malformed_houjin_returns_422(
    houjin_360_client: TestClient,
) -> None:
    """Non-13-digit houjin_bangou returns 422."""
    r = houjin_360_client.get("/v1/houjin/12345/360")
    assert r.status_code == 422

    r2 = houjin_360_client.get("/v1/houjin/abcdefghijklm/360")
    assert r2.status_code == 422
    body2 = r2.json()
    detail = body2.get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "invalid_houjin_bangou"


def test_houjin_360_unknown_houjin_returns_404(
    houjin_360_client: TestClient,
) -> None:
    """Well-formed but unknown bangou returns structured 404."""
    r = houjin_360_client.get("/v1/houjin/0000000000001/360")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "houjin_not_found"
    assert detail["houjin_bangou"] == "0000000000001"


def test_houjin_360_strips_t_prefix(
    houjin_360_client: TestClient,
) -> None:
    """T-prefixed input normalises to the 13-digit canonical id."""
    r = houjin_360_client.get(f"/v1/houjin/T{_TEST_HOUJIN}/360")
    assert r.status_code == 200
    assert r.json()["houjin_bangou"] == _TEST_HOUJIN


def test_houjin_360_limit_caps_lists(
    houjin_360_client: TestClient,
) -> None:
    """`limit` caps every list-shaped section but totals stay accurate."""
    r = houjin_360_client.get(
        f"/v1/houjin/{_TEST_HOUJIN}/360",
        params={"limit": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["limit_per_section"] == 1
    assert body["adoption_records"]["total"] == 3
    assert len(body["adoption_records"]["records"]) == 1
    assert body["bids_won"]["total"] == 2
    assert len(body["bids_won"]["records"]) == 1
    # _billing_unit invariant.
    assert body["_billing_unit"] == 1


def test_houjin_360_disclaimer_states_descriptive_only(
    houjin_360_client: TestClient,
) -> None:
    """Disclaimer must explicitly note the 3-axis scores are descriptive."""
    r = houjin_360_client.get(f"/v1/houjin/{_TEST_HOUJIN}/360")
    body = r.json()
    disc = body["_disclaimer"]
    assert "descriptive" in disc
    assert "与信判断" in disc


def test_houjin_360_compact_envelope(
    houjin_360_client: TestClient,
) -> None:
    """compact=true returns the compact envelope marker + disclaimer ref."""
    r = houjin_360_client.get(
        f"/v1/houjin/{_TEST_HOUJIN}/360",
        params={"compact": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # compact envelope marker — to_compact projects the heavy body off.
    assert body.get("_c") == 1
    # disclaimer reference / projection still preserved.
    assert "_dx" in body or "_disclaimer" in body
