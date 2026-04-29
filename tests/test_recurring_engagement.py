"""Smoke tests for /v1/me/recurring/* (slack bind, quarterly PDF, email_course alias).

Coverage focus:
    * POST /v1/me/recurring/slack — auth + Slack URL prefix (SSRF guard)
    * GET  /v1/me/recurring/quarterly/{year}/{q} — auth + quarter range
    * POST /v1/me/recurring/email_course/start — auth + alias to courses
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def recurring_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_recurring_test",
        tier="paid",
        stripe_subscription_id="sub_recurring_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_recurring_tables(seeded_db: Path):
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"
    profiles = repo / "scripts" / "migrations" / "096_client_profiles.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        c.executescript(profiles.read_text(encoding="utf-8"))
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format "
                "TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        # course_subscriptions
        c.execute("""
            CREATE TABLE IF NOT EXISTS course_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id TEXT NOT NULL,
                email TEXT NOT NULL,
                course_slug TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                current_day INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                last_sent_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(api_key_id, course_slug, started_at)
            )
        """)
        c.execute("DELETE FROM saved_searches")
        c.execute("DELETE FROM course_subscriptions")
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Slack webhook bind
# ---------------------------------------------------------------------------


def test_slack_bind_requires_auth(client):
    r = client.post(
        "/v1/me/recurring/slack",
        json={
            "saved_search_id": 1,
            "channel_url": "https://hooks.slack.com/services/T/B/X",
        },
    )
    assert r.status_code == 401


def test_slack_bind_rejects_non_slack_url(client, recurring_key):
    r = client.post(
        "/v1/me/recurring/slack",
        headers={"X-API-Key": recurring_key},
        json={
            "saved_search_id": 1,
            "channel_url": "https://attacker.example.com/webhook",
        },
    )
    assert r.status_code == 422
    assert "hooks.slack.com" in r.text


# ---------------------------------------------------------------------------
# Quarterly PDF
# ---------------------------------------------------------------------------


def test_quarterly_requires_auth(client):
    r = client.get("/v1/me/recurring/quarterly/2026/1")
    assert r.status_code == 401


def test_quarterly_rejects_invalid_quarter(client, recurring_key):
    r = client.get(
        "/v1/me/recurring/quarterly/2026/9",
        headers={"X-API-Key": recurring_key},
    )
    assert r.status_code == 400


def test_quarterly_rejects_invalid_year(client, recurring_key):
    r = client.get(
        "/v1/me/recurring/quarterly/1999/1",
        headers={"X-API-Key": recurring_key},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Email course alias
# ---------------------------------------------------------------------------


def test_email_course_start_requires_auth(client):
    r = client.post(
        "/v1/me/recurring/email_course/start",
        json={"notify_email": "test@example.com", "course_slug": "invoice"},
    )
    assert r.status_code == 401


def test_email_course_start_invalid_slug(client, recurring_key):
    r = client.post(
        "/v1/me/recurring/email_course/start",
        headers={"X-API-Key": recurring_key},
        json={"notify_email": "test@example.com", "course_slug": "unknown"},
    )
    # Pydantic Literal rejects unknown slug at request schema level
    assert r.status_code == 422
