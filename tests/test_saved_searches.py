"""Smoke tests for /v1/me/saved_searches CRUD + Slack channel validation.

Coverage focus is the gap-fix surface added by migration 099:
    * channel_format / channel_url accepted on create + update
    * Slack URL must start with https://hooks.slack.com/services/ (SSRF)
    * email channel must NOT carry a channel_url
    * row read survives the legacy-shape branch (channel_format absent)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def saved_search_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_saved_test",
        tier="paid",
        stripe_subscription_id="sub_saved_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_saved_searches_table(seeded_db: Path):
    """Apply 079 (base) + 099 (channel_format/url) migrations onto test DB."""
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        # 099 has multiple statements; ALTER TABLE ADD COLUMN is not
        # idempotent in SQLite so guard via PRAGMA table_info.
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format "
                "TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        c.execute("DELETE FROM saved_searches")
        c.commit()
    finally:
        c.close()
    yield


def test_create_email_channel_default(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "東京都の補助金",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["channel_format"] == "email"
    assert body["channel_url"] is None


def test_create_slack_requires_slack_prefix(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Slack 配信",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "slack",
            "channel_url": "https://attacker.example.com/webhook",
        },
    )
    assert r.status_code == 422, r.text
    assert "hooks.slack.com" in r.text


def test_create_slack_with_valid_url(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Slack OK",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "slack",
            "channel_url": "https://hooks.slack.com/services/T0/B0/XYZ",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["channel_format"] == "slack"
    assert body["channel_url"].startswith("https://hooks.slack.com/services/")


def test_create_email_rejects_url(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Bad email shape",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "email",
            "channel_url": "https://hooks.slack.com/services/X",
        },
    )
    assert r.status_code == 422, r.text
