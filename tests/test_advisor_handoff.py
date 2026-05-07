from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HANDOFF_HOUJIN = ("9000000000001", "9000000000002", "9000000000003")


@pytest.fixture()
def advisors_handoff_db(seeded_db: Path) -> Path:
    migration = _REPO / "scripts" / "migrations" / "024_advisors.sql"
    assert migration.is_file()

    conn = sqlite3.connect(seeded_db)
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        placeholders = ",".join("?" for _ in _HANDOFF_HOUJIN)
        conn.execute(
            "DELETE FROM advisor_referrals WHERE advisor_id IN "
            f"(SELECT id FROM advisors WHERE houjin_bangou IN ({placeholders}))",
            _HANDOFF_HOUJIN,
        )
        conn.execute(
            f"DELETE FROM advisors WHERE houjin_bangou IN ({placeholders})",
            _HANDOFF_HOUJIN,
        )

        now = datetime.now(UTC).isoformat()
        rows = [
            (
                "9000000000001",
                "東京税務サポート",
                "税理士法人",
                ["tax", "subsidy"],
                ["manufacturing"],
                "東京都",
                "https://advisor.example/tokyo-tax",
                "tokyo-tax@example.jp",
                "製造業の補助金と税制確認に対応します。",
                1_000_000,
            ),
            (
                "9000000000002",
                "東京融資サポート",
                "認定支援機関",
                ["loan"],
                ["retail"],
                "東京都",
                "https://advisor.example/tokyo-loan",
                "tokyo-loan@example.jp",
                "資金繰りと融資相談に対応します。",
                1,
            ),
            (
                "9000000000003",
                "大阪税務サポート",
                "税理士法人",
                ["tax"],
                ["manufacturing"],
                "大阪府",
                "https://advisor.example/osaka-tax",
                "osaka-tax@example.jp",
                "関西圏の製造業税制に対応します。",
                1_000_001,
            ),
        ]
        for row in rows:
            conn.execute(
                "INSERT INTO advisors"
                " (houjin_bangou, firm_name, firm_type, specialties_json,"
                "  industries_json, prefecture, contact_url, contact_email,"
                "  intro_blurb, success_count, commission_model,"
                "  commission_yen_per_intro, commission_rate_pct, verified_at,"
                "  source_url, source_fetched_at, active, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row[0],
                    row[1],
                    row[2],
                    json.dumps(row[3], ensure_ascii=False),
                    json.dumps(row[4], ensure_ascii=False),
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                    "flat",
                    3000,
                    5,
                    now,
                    "https://example.jp/advisor-source",
                    now,
                    1,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return seeded_db


def _count_rows(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_handoff_preview_matches_advisors_without_persistence(
    client,
    advisors_handoff_db: Path,
):
    referrals_before = _count_rows(advisors_handoff_db, "advisor_referrals")
    usage_before = _count_rows(advisors_handoff_db, "usage_events")

    response = client.post(
        "/v1/advisors/handoffs/preview",
        json={
            "prefecture": "東京",
            "industry": "manufacture",
            "specialty": "tax",
            "known_gaps": [
                "見積書未確認",
                {
                    "gap_id": "deadline_primary_source",
                    "message_ja": "申請期限の一次情報確認が必要",
                    "source_fields": ["source_receipts"],
                },
            ],
            "human_review_required": True,
            "source_receipts": [
                {
                    "source_id": "program:UNI-test-s-1",
                    "source_url": "https://example.jp/programs/UNI-test-s-1",
                }
            ],
            "summary": "製造業の設備投資について、補助金と税制の併用可否を確認したい。",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "補助金と税制の併用可否" in body["handoff_summary"]
    assert "見積書未確認" in body["handoff_summary"]
    assert body["professional_boundary"]
    assert body["display_order"]["paid_influence"] is False
    assert body["matched_advisors"][0]["firm_name"] == "東京税務サポート"
    assert all(advisor["prefecture"] == "東京都" for advisor in body["matched_advisors"])
    assert "source_receipts" not in body
    assert "token" not in body
    assert "referral_token" not in json.dumps(body, ensure_ascii=False)
    assert _count_rows(advisors_handoff_db, "advisor_referrals") == referrals_before
    assert _count_rows(advisors_handoff_db, "usage_events") == usage_before


def test_handoff_preview_rejects_unknown_prefecture_without_widening_match(
    client,
    advisors_handoff_db: Path,
):
    response = client.post(
        "/v1/advisors/handoffs/preview",
        json={
            "prefecture": "Atlantis",
            "industry": "manufacturing",
            "specialty": "tax",
            "known_gaps": [],
            "human_review_required": False,
            "source_receipts": [],
            "summary": "確認用のプレビュー。",
        },
    )

    assert response.status_code == 422, response.text
    assert "prefecture unrecognized" in response.text
