from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.advisors import _advisor_dashboard_token

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def advisors_db(seeded_db: Path) -> Path:
    migration = _REPO / "scripts" / "migrations" / "024_advisors.sql"
    conn = sqlite3.connect(seeded_db)
    try:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return seeded_db


def _seed_advisor(
    db_path: Path,
    *,
    houjin_bangou: str = "9999999999991",
    firm_type: str = "税理士法人",
    commission_model: str = "flat",
    contact_email: str = "advisor-security@example.com",
    referral_token: str = "a" * 32,
) -> int:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "DELETE FROM advisor_referrals WHERE advisor_id IN "
            "(SELECT id FROM advisors WHERE houjin_bangou = ?)",
            (houjin_bangou,),
        )
        conn.execute("DELETE FROM advisors WHERE houjin_bangou = ?", (houjin_bangou,))
        cur = conn.execute(
            "INSERT INTO advisors"
            " (houjin_bangou, firm_name, firm_type, specialties_json, industries_json,"
            "  prefecture, contact_email, commission_model, source_url, source_fetched_at,"
            "  verified_at, active, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                houjin_bangou,
                "セキュリティ確認税理士法人",
                firm_type,
                '["subsidy"]',
                '["manufacturing"]',
                "東京都",
                contact_email,
                commission_model,
                "https://jpcite.com/advisors.html",
                "2026-05-07T00:00:00+00:00",
                "2026-05-07T00:00:00+00:00",
                "2026-05-07T00:00:00+00:00",
                "2026-05-07T00:00:00+00:00",
            ),
        )
        advisor_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO advisor_referrals"
            " (referral_token, advisor_id, clicked_at, commission_yen)"
            " VALUES (?, ?, ?, ?)",
            (referral_token, advisor_id, "2026-05-07T00:01:00+00:00", 3000),
        )
        conn.commit()
        return advisor_id
    finally:
        conn.close()


def test_advisor_dashboard_data_requires_signed_token(
    client: TestClient,
    advisors_db: Path,
) -> None:
    advisor_id = _seed_advisor(advisors_db)

    missing = client.get(f"/v1/advisors/{advisor_id}/dashboard-data")
    assert missing.status_code == 403
    assert "advisor dashboard token required" in missing.text

    bad = client.get(
        f"/v1/advisors/{advisor_id}/dashboard-data",
        params={"token": "0" * 64},
    )
    assert bad.status_code == 403

    token = _advisor_dashboard_token(advisor_id, "advisor-security@example.com")
    ok = client.get(
        f"/v1/advisors/{advisor_id}/dashboard-data",
        params={"token": token},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["advisor"]["contact_email"] == "<email-redacted>"
    assert body["referrals"][0]["token_prefix"] == "aaaaaaaa…"
    assert "referral_token" not in body["referrals"][0]


def test_advisor_track_requires_explicit_user_consent(
    client: TestClient,
    advisors_db: Path,
) -> None:
    advisor_id = _seed_advisor(
        advisors_db,
        houjin_bangou="9999999999994",
        referral_token="c" * 32,
    )

    missing = client.post("/v1/advisors/track", json={"advisor_id": advisor_id})
    assert missing.status_code == 409
    assert "explicit user consent" in missing.text

    ok = client.post(
        "/v1/advisors/track",
        json={"advisor_id": advisor_id, "consent_granted": True},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert len(body["token"]) == 32
    assert f"ref={body['token']}" in body["redirect_url"]


def test_lawyer_signup_rejects_percent_commission(
    client: TestClient,
    advisors_db: Path,
) -> None:
    payload = {
        "firm_name": "弁護士法人テスト",
        "houjin_bangou": "9999999999992",
        "firm_type": "弁護士",
        "specialties": ["enforcement_defense"],
        "prefecture": "東京都",
        "contact_email": "lawyer-percent@example.com",
        "commission_model": "percent",
        "commission_rate_pct": 5,
        "commission_yen_per_intro": 3000,
        "agreed_to_terms": True,
    }

    response = client.post("/v1/advisors/signup", json=payload)
    assert response.status_code == 422
    assert "受任報酬比" in response.text


def test_lawyer_advisor_cannot_use_success_fee_referral_flow(
    client: TestClient,
    advisors_db: Path,
) -> None:
    advisor_id = _seed_advisor(
        advisors_db,
        houjin_bangou="9999999999993",
        firm_type="弁護士",
        commission_model="flat",
        contact_email="lawyer-flat@example.com",
        referral_token="b" * 32,
    )

    track = client.post("/v1/advisors/track", json={"advisor_id": advisor_id})
    assert track.status_code == 409
    assert "弁護士カテゴリ" in track.text

    report = client.post(
        "/v1/advisors/report-conversion",
        json={"referral_token": "b" * 32},
    )
    assert report.status_code == 409
    assert "弁護士カテゴリ" in report.text
