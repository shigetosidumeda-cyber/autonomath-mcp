"""Tests for GET /v1/ping."""

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
        customer_id="cus_ping_test",
        tier="paid",
        stripe_subscription_id="sub_ping_test",
    )
    c.commit()
    c.close()
    return raw


def test_ping_anonymous(client):
    from jpintel_mcp import __version__

    r = client.get("/v1/ping")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["authenticated"] is False
    assert body["tier"] == "free"
    assert body["server_version"] == __version__
    # Anon: remaining is the configured free-tier ceiling (100 in tests).
    assert body["rate_limit_remaining"] == 100
    # RFC-ish UTC timestamp, Z-suffixed.
    assert body["server_time_utc"].endswith("Z")


def test_ping_authenticated_paid(client, plus_key):
    r = client.get("/v1/ping", headers={"X-API-Key": plus_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authenticated"] is True
    assert body["tier"] == "paid"
    # Paid tier is metered (no hard cap) → rate_limit_remaining is None.
    assert body["rate_limit_remaining"] is None


def test_ping_increments_usage_for_authed_only(client, plus_key, seeded_db: Path):
    """Authed calls get logged to usage_events (decrementing the remaining
    counter). Anonymous calls don't — we have nothing per-IP to log against."""
    from jpintel_mcp.api.deps import hash_api_key

    kh = hash_api_key(plus_key)

    # Clear any prior usage rows from the shared session DB.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM usage_events WHERE key_hash = ?", (kh,))
        c.commit()
    finally:
        c.close()

    # Baseline anon ping — no row should land for this key.
    r = client.get("/v1/ping")
    assert r.status_code == 200

    c = sqlite3.connect(seeded_db)
    try:
        (n_after_anon,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?", (kh,)
        ).fetchone()
        assert n_after_anon == 0
    finally:
        c.close()

    # Authed ping — one row lands.
    r = client.get("/v1/ping", headers={"X-API-Key": plus_key})
    assert r.status_code == 200

    c = sqlite3.connect(seeded_db)
    try:
        (n_after_authed,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (kh, "ping"),
        ).fetchone()
        assert n_after_authed == 1
    finally:
        c.close()


def test_ping_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    plus_key,
    seeded_db: Path,
    monkeypatch,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.middleware import customer_cap

    kh = hash_api_key(plus_key)

    def usage_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            (count,) = c.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (kh, "ping"),
            ).fetchone()
            return int(count)
        finally:
            c.close()

    before = usage_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    r = client.get("/v1/ping", headers={"X-API-Key": plus_key})

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
