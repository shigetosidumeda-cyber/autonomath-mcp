"""Tests for /v1/subscribers public endpoints."""

from __future__ import annotations

import importlib
import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _subscribers_module():
    """Resolve the currently-loaded subscribers module.

    Other tests (e.g. test_lineage) purge jpintel_mcp from sys.modules, so we
    cannot rely on a top-level import — a stale module reference would clear
    the wrong rate-limit bucket. Always look it up fresh.
    """
    mod = sys.modules.get("jpintel_mcp.api.subscribers")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.subscribers")
    return mod


def make_unsubscribe_token(email: str) -> str:
    return _subscribers_module().make_unsubscribe_token(email)


@pytest.fixture(autouse=True)
def _reset_rate_limit(client):
    # Depending on `client` forces the TestClient (and thus the fresh app)
    # to be built first, which imports jpintel_mcp.api.subscribers. Only
    # after that can we reliably reset the bucket the live app is using.
    _subscribers_module()._reset_rate_limit_state()
    yield
    _subscribers_module()._reset_rate_limit_state()


def _row_count(db: Path, email: str) -> int:
    c = sqlite3.connect(db)
    try:
        (n,) = c.execute("SELECT COUNT(*) FROM subscribers WHERE email = ?", (email,)).fetchone()
        return n
    finally:
        c.close()


def test_subscribe_happy_path(client, seeded_db: Path):
    r = client.post(
        "/v1/subscribers",
        json={"email": "Alice@Example.com", "source": "landing"},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"subscribed": True}
    # stored lowercase
    assert _row_count(seeded_db, "alice@example.com") == 1


def test_subscribe_duplicate_is_idempotent(client, seeded_db: Path):
    r1 = client.post("/v1/subscribers", json={"email": "dup@example.com"})
    assert r1.status_code == 201
    r2 = client.post("/v1/subscribers", json={"email": "dup@example.com"})
    # idempotent: don't leak "already subscribed"; accept both 200/201 shapes
    assert r2.status_code in (200, 201)
    assert r2.json() == {"subscribed": True}
    # only one row stored
    assert _row_count(seeded_db, "dup@example.com") == 1


def test_subscribe_invalid_email_rejected(client):
    r = client.post("/v1/subscribers", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_subscribe_rate_limit(client):
    # 10 allowed, 11th is rejected
    for i in range(10):
        rr = client.post("/v1/subscribers", json={"email": f"rl{i}@example.com"})
        assert rr.status_code == 201, (i, rr.text)
    r = client.post("/v1/subscribers", json={"email": "rl_over@example.com"})
    assert r.status_code == 429


def test_unsubscribe_valid_token(client, seeded_db: Path):
    email = "leaver@example.com"
    r = client.post("/v1/subscribers", json={"email": email})
    assert r.status_code == 201
    token = make_unsubscribe_token(email)
    r = client.get(f"/v1/subscribers/unsubscribe?email={email}&token={token}")
    assert r.status_code == 200
    assert "Unsubscribed" in r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT unsubscribed_at FROM subscribers WHERE email = ?", (email,)
        ).fetchone()
        assert row is not None
        assert row[0] is not None
    finally:
        c.close()


def test_unsubscribe_bad_token(client):
    r = client.get("/v1/subscribers/unsubscribe?email=x@example.com&token=" + ("0" * 64))
    assert r.status_code == 400
    assert "Invalid" in r.text
