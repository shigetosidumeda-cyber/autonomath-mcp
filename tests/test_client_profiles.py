"""Smoke tests for /v1/me/client_profiles CRUD (migration 096).

Covers the three endpoints wired by `src/jpintel_mcp/api/client_profiles.py`:

    POST   /v1/me/client_profiles/bulk_import   CSV upload
    GET    /v1/me/client_profiles               list calling key's profiles
    DELETE /v1/me/client_profiles/{profile_id}  hard-delete

The 補助金コンサル fan-out depends on this metadata being persisted per
api_key_hash so the saved_searches cron can join × N profiles per call.

Mirrors the test_saved_searches.py pattern: applies migration 096 onto the
shared `seeded_db` fixture so the table exists for the router.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def consultant_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_consult_test",
        tier="paid",
        stripe_subscription_id="sub_consult_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_client_profiles_table(seeded_db: Path):
    """Apply migration 096 onto the test DB so the router has its table."""
    repo = Path(__file__).resolve().parent.parent
    mig = repo / "scripts" / "migrations" / "096_client_profiles.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(mig.read_text(encoding="utf-8"))
        # Wipe between tests so per-test counts stay deterministic.
        c.execute("DELETE FROM client_profiles")
        c.commit()
    finally:
        c.close()
    yield


def test_bulk_import_creates_profiles(client, consultant_key):
    """Happy path: a small CSV imports cleanly and the rows surface in GET."""
    csv_body = (
        "name_label,jsic_major,prefecture,employee_count,capital_yen\n"
        "アルファ商事,E,東京都,30,10000000\n"
        "ベータ製作所,E,大阪府,12,5000000\n"
    ).encode()

    r = client.post(
        "/v1/me/client_profiles/bulk_import",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", io.BytesIO(csv_body), "text/csv")},
        data={"upsert": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2
    assert body["updated"] == 0
    assert body["skipped"] == 0
    assert body["total_after_import"] == 2

    # GET surfaces both profiles
    r2 = client.get(
        "/v1/me/client_profiles",
        headers={"X-API-Key": consultant_key},
    )
    assert r2.status_code == 200, r2.text
    rows = r2.json()
    assert isinstance(rows, list)
    assert len(rows) == 2
    by_name = {r["name_label"]: r for r in rows}
    assert "アルファ商事" in by_name
    assert by_name["アルファ商事"]["jsic_major"] == "E"
    assert by_name["アルファ商事"]["prefecture"] == "東京都"
    assert by_name["アルファ商事"]["employee_count"] == 30


def test_bulk_import_anonymous_is_401(client):
    """No API key → 401 (per-key surface, anonymous tier rejected)."""
    csv_body = b"name_label\nfoo\n"
    r = client.post(
        "/v1/me/client_profiles/bulk_import",
        files={"file": ("clients.csv", io.BytesIO(csv_body), "text/csv")},
        data={"upsert": "true"},
    )
    assert r.status_code == 401, r.text


def test_delete_removes_profile(client, consultant_key):
    """DELETE soft-removes a profile owned by the calling key."""
    csv_body = b"name_label\nDeleteMe\n"
    r = client.post(
        "/v1/me/client_profiles/bulk_import",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", io.BytesIO(csv_body), "text/csv")},
        data={"upsert": "true"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1

    # find the profile_id
    rows = client.get(
        "/v1/me/client_profiles",
        headers={"X-API-Key": consultant_key},
    ).json()
    assert len(rows) == 1
    pid = rows[0]["profile_id"]

    r_del = client.delete(
        f"/v1/me/client_profiles/{pid}",
        headers={"X-API-Key": consultant_key},
    )
    assert r_del.status_code == 200, r_del.text
    assert r_del.json() == {"ok": True, "profile_id": pid}

    # Re-list returns empty
    rows2 = client.get(
        "/v1/me/client_profiles",
        headers={"X-API-Key": consultant_key},
    ).json()
    assert rows2 == []


def test_bulk_import_missing_required_header_is_400(client, consultant_key):
    """CSV without `name_label` column → 400."""
    csv_body = "jsic_major,prefecture\nE,東京都\n".encode()
    r = client.post(
        "/v1/me/client_profiles/bulk_import",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", io.BytesIO(csv_body), "text/csv")},
        data={"upsert": "true"},
    )
    assert r.status_code == 400, r.text
    # Error body mentions the missing column
    assert "name_label" in r.text
