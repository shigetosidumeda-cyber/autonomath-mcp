"""Tests for POST /v1/feedback."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def plus_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_feedback_test",
        tier="paid",
        stripe_subscription_id="sub_feedback_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _clear_feedback_rows(seeded_db: Path):
    """Each test starts with an empty feedback table so rate-limit counts
    do not bleed between cases."""
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM feedback")
        c.commit()
    finally:
        c.close()
    yield


def test_feedback_anonymous_happy_path(client, seeded_db: Path):
    r = client.post(
        "/v1/feedback",
        json={
            "message": "search で 認定新規就農者 が出ない件",
            "rating": 3,
            "endpoint": "/v1/programs/search",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["received"] is True
    assert isinstance(body["feedback_id"], int)
    assert body["feedback_id"] > 0

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT key_hash, customer_id, tier, message, rating, endpoint, ip_hash "
            "FROM feedback WHERE id = ?",
            (body["feedback_id"],),
        ).fetchone()
        assert row is not None
        assert row["key_hash"] is None
        assert row["customer_id"] is None
        assert row["tier"] is None
        assert row["rating"] == 3
        assert row["endpoint"] == "/v1/programs/search"
        assert row["ip_hash"] is not None  # raw IP never stored
    finally:
        c.close()


def test_feedback_authed_attaches_customer_and_tier(client, plus_key, seeded_db: Path):
    from jpintel_mcp.api.deps import hash_api_key

    r = client.post(
        "/v1/feedback",
        headers={"X-API-Key": plus_key},
        json={"message": "naming suggestion: /v1/grants/search is clearer", "rating": 5},
    )
    assert r.status_code == 201, r.text

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT key_hash, customer_id, tier FROM feedback WHERE id = ?",
            (r.json()["feedback_id"],),
        ).fetchone()
        assert row["key_hash"] == hash_api_key(plus_key)
        assert row["customer_id"] == "cus_feedback_test"
        assert row["tier"] == "paid"
    finally:
        c.close()


def test_feedback_too_long_message_rejected(client):
    r = client.post("/v1/feedback", json={"message": "x" * 4001})
    assert r.status_code == 422


def test_feedback_empty_message_rejected(client):
    r = client.post("/v1/feedback", json={"message": ""})
    assert r.status_code == 422


def test_feedback_invalid_rating_rejected(client):
    r = client.post("/v1/feedback", json={"message": "ok", "rating": 6})
    assert r.status_code == 422
    r = client.post("/v1/feedback", json={"message": "ok", "rating": 0})
    assert r.status_code == 422


def test_feedback_rate_limit_anonymous(client):
    # 10 posts allowed, 11th is 429
    for i in range(10):
        rr = client.post("/v1/feedback", json={"message": f"msg {i}"})
        assert rr.status_code == 201, (i, rr.text)
    r = client.post("/v1/feedback", json={"message": "one too many"})
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"]


def test_feedback_rate_limit_authed_per_key(client, plus_key):
    headers = {"X-API-Key": plus_key}
    for i in range(10):
        rr = client.post("/v1/feedback", headers=headers, json={"message": f"k{i}"})
        assert rr.status_code == 201, (i, rr.text)
    r = client.post("/v1/feedback", headers=headers, json={"message": "k over"})
    assert r.status_code == 429
