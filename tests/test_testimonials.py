"""Tests for /v1/testimonials + /v1/me/testimonials + /v1/admin/testimonials.

Coverage:
  1. POST /v1/me/testimonials requires X-API-Key (401 anonymous)
  2. POST happy path — pending_review=true, audience CHECK enforced
  3. invalid audience → 422
  4. text too short / too long → 422
  5. GET /v1/testimonials returns approved rows only (pending hidden)
  6. /v1/admin/testimonials/{id}/approve flips approved_at; appears on public
  7. /v1/admin/testimonials/{id}/unapprove hides it again
  8. DELETE /v1/me/testimonials/{id} works for owner key
  9. DELETE returns 404 for someone else's testimonial (no info leak)
 10. PII posture: api_key_hash never in public response
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path


ADMIN_KEY = "test-admin-secret-testimonials"


@pytest.fixture()
def admin_enabled(monkeypatch):
    from jpintel_mcp.api import admin as admin_mod
    from jpintel_mcp.config import settings

    for settings_obj in (settings, admin_mod.settings):
        monkeypatch.setattr(settings_obj, "admin_api_key", ADMIN_KEY, raising=False)
    yield ADMIN_KEY


@pytest.fixture(autouse=True)
def _clear_testimonials(seeded_db: Path):
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM testimonials")
        c.commit()
    finally:
        c.close()
    yield


@pytest.fixture()
def submitter_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_testimonial_test",
        tier="paid",
        stripe_subscription_id="sub_testimonial_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture()
def other_key(seeded_db: Path) -> str:
    """A second submitter key — used to assert key_hash isolation on DELETE."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_testimonial_other",
        tier="paid",
        stripe_subscription_id="sub_testimonial_other",
    )
    c.commit()
    c.close()
    return raw


def _submit_one(client, submitter_key: str, audience: str = "Dev", text: str | None = None) -> int:
    body = {
        "audience": audience,
        "text": text or "AutonoMath は法令引用が公式 e-Gov に紐付いていて引用根拠が明確。",
        "name": "梅田",
        "organization": "Bookyou株式会社",
    }
    r = client.post(
        "/v1/me/testimonials",
        headers={"X-API-Key": submitter_key},
        json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()["testimonial_id"]


# ---------------------------------------------------------------------------
# Submission auth
# ---------------------------------------------------------------------------


def test_submit_requires_api_key(client):
    r = client.post(
        "/v1/me/testimonials",
        json={"audience": "Dev", "text": "x" * 30},
    )
    assert r.status_code == 401


def test_submit_happy_path_pending(client, submitter_key, seeded_db: Path):
    tid = _submit_one(client, submitter_key, audience="税理士")
    # Verify the row landed pending (approved_at = NULL).
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT audience, approved_at, name, organization FROM testimonials WHERE id = ?",
            (tid,),
        ).fetchone()
        assert row is not None
        assert row["audience"] == "税理士"
        assert row["approved_at"] is None
        assert row["name"] == "梅田"
        assert row["organization"] == "Bookyou株式会社"
    finally:
        c.close()


def test_submit_invalid_audience_rejected(client, submitter_key):
    r = client.post(
        "/v1/me/testimonials",
        headers={"X-API-Key": submitter_key},
        json={"audience": "VC-stage-A", "text": "x" * 30},
    )
    assert r.status_code == 422


def test_submit_text_too_short_rejected(client, submitter_key):
    r = client.post(
        "/v1/me/testimonials",
        headers={"X-API-Key": submitter_key},
        json={"audience": "Dev", "text": "short"},
    )
    assert r.status_code == 422


def test_submit_text_too_long_rejected(client, submitter_key):
    r = client.post(
        "/v1/me/testimonials",
        headers={"X-API-Key": submitter_key},
        json={"audience": "Dev", "text": "x" * 2001},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Public list — approved only
# ---------------------------------------------------------------------------


def test_public_list_hides_pending(client, submitter_key):
    _submit_one(client, submitter_key)
    r = client.get("/v1/testimonials")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["rows"] == []


def test_public_list_shows_approved(client, submitter_key, admin_enabled, seeded_db: Path):
    tid = _submit_one(client, submitter_key, audience="VC")
    # Approve.
    r = client.post(
        f"/v1/admin/testimonials/{tid}/approve",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    assert r.json()["approved"] is True

    r2 = client.get("/v1/testimonials")
    assert r2.status_code == 200
    body = r2.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["audience"] == "VC"
    # PII: api_key_hash MUST NOT surface
    assert "api_key_hash" not in row


def test_public_list_drops_after_unapprove(client, submitter_key, admin_enabled):
    tid = _submit_one(client, submitter_key)
    client.post(
        f"/v1/admin/testimonials/{tid}/approve",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert client.get("/v1/testimonials").json()["total"] == 1
    # Now unapprove.
    r = client.post(
        f"/v1/admin/testimonials/{tid}/unapprove",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 200
    assert r.json()["approved"] is False
    assert client.get("/v1/testimonials").json()["total"] == 0


# ---------------------------------------------------------------------------
# Admin auth posture
# ---------------------------------------------------------------------------


def test_approve_requires_admin_key(client, submitter_key, admin_enabled):
    tid = _submit_one(client, submitter_key)
    r = client.post(f"/v1/admin/testimonials/{tid}/approve")
    assert r.status_code == 401


def test_approve_503_when_admin_disabled(client, submitter_key, monkeypatch):
    from jpintel_mcp.api import admin as admin_mod
    from jpintel_mcp.config import settings

    for settings_obj in (settings, admin_mod.settings):
        monkeypatch.setattr(settings_obj, "admin_api_key", "", raising=False)
    tid = _submit_one(client, submitter_key)
    r = client.post(
        f"/v1/admin/testimonials/{tid}/approve",
        headers={"X-API-Key": "anything"},
    )
    assert r.status_code == 503


def test_approve_404_for_unknown_id(client, admin_enabled):
    r = client.post(
        "/v1/admin/testimonials/9999999/approve",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Owner-only DELETE
# ---------------------------------------------------------------------------


def test_owner_can_delete_own_testimonial(client, submitter_key):
    tid = _submit_one(client, submitter_key)
    r = client.delete(
        f"/v1/me/testimonials/{tid}",
        headers={"X-API-Key": submitter_key},
    )
    assert r.status_code == 204


def test_other_key_cannot_delete_someone_elses_testimonial(client, submitter_key, other_key):
    tid = _submit_one(client, submitter_key)
    r = client.delete(
        f"/v1/me/testimonials/{tid}",
        headers={"X-API-Key": other_key},
    )
    # 404 (not 403) — never leak existence to a non-owner key
    assert r.status_code == 404


def test_delete_unknown_id_returns_404(client, submitter_key):
    r = client.delete(
        "/v1/me/testimonials/9999999",
        headers={"X-API-Key": submitter_key},
    )
    assert r.status_code == 404


def test_delete_anonymous_rejected(client, submitter_key):
    tid = _submit_one(client, submitter_key)
    r = client.delete(f"/v1/me/testimonials/{tid}")
    assert r.status_code == 401
