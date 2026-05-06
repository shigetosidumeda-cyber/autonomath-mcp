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
from fastapi import HTTPException, status

from jpintel_mcp.api.deps import hash_api_key
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
                "ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'"
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


def test_quarterly_billing_503_does_not_leave_pdf_cache(
    client,
    recurring_key,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api import recurring_quarterly as mod

    def fake_render(*, out_path: Path, context: dict[str, object]) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\nfake quarterly pdf")
        return True

    def fail_billing(conn: sqlite3.Connection, key_hash: str) -> bool:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_cap_final_check_failed"},
        )

    monkeypatch.setattr(mod, "_QUARTERLY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_render_pdf_to", fake_render)
    monkeypatch.setattr(mod, "_record_metered_pdf", fail_billing)

    r = client.get(
        "/v1/me/recurring/quarterly/2026/1",
        headers={"X-API-Key": recurring_key},
    )

    assert r.status_code == 503
    assert list(tmp_path.iterdir()) == []


def test_quarterly_cron_billing_503_does_not_leave_pdf_cache(
    seeded_db: Path,
    recurring_key,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api import recurring_quarterly as mod
    from scripts.cron import generate_quarterly_reports as cron

    key_hash = hash_api_key(recurring_key)
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("DELETE FROM client_profiles")
        conn.execute(
            "INSERT INTO client_profiles(api_key_hash, name_label) VALUES (?, ?)",
            (key_hash, "billing-fail-profile"),
        )
        conn.commit()
    finally:
        conn.close()

    def fake_render(*, out_path: Path, context: dict[str, object]) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\nfake quarterly pdf")
        return True

    def fail_billing(conn: sqlite3.Connection, key_hash: str) -> bool:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_cap_final_check_failed"},
        )

    monkeypatch.setattr(mod, "_QUARTERLY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_render_pdf_to", fake_render)
    monkeypatch.setattr(mod, "_record_metered_pdf", fail_billing)

    summary = cron.run(year=2026, quarter=1)

    assert summary["rendered"] == 0
    assert summary["billed"] == 0
    assert summary["billing_failed"] == 1
    assert summary["render_failed"] == 0
    assert list(tmp_path.iterdir()) == []


def test_quarterly_cron_unexpected_usage_exception_skips_customer_and_continues(
    seeded_db: Path,
    recurring_key,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api import recurring_quarterly as mod
    from scripts.cron import generate_quarterly_reports as cron

    failing_hash = hash_api_key(recurring_key)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DELETE FROM client_profiles")
        succeeding_key = issue_key(
            conn,
            customer_id="cus_recurring_success",
            tier="paid",
            stripe_subscription_id="sub_recurring_success",
        )
        succeeding_hash = hash_api_key(succeeding_key)
        conn.executemany(
            "INSERT INTO client_profiles(api_key_hash, name_label) VALUES (?, ?)",
            [
                (failing_hash, "billing-exception-profile"),
                (succeeding_hash, "billing-success-profile"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    def fake_render(*, out_path: Path, context: dict[str, object]) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\nfake quarterly pdf")
        return True

    billed_hashes: list[str] = []

    def record_or_fail(conn: sqlite3.Connection, key_hash: str) -> bool:
        if key_hash == failing_hash:
            raise sqlite3.OperationalError("usage_events insert failed")
        billed_hashes.append(key_hash)
        return True

    monkeypatch.setattr(mod, "_QUARTERLY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_render_pdf_to", fake_render)
    monkeypatch.setattr(mod, "_record_metered_pdf", record_or_fail)
    monkeypatch.setattr(cron, "_eligible_keys", lambda _conn: [failing_hash, succeeding_hash])

    summary = cron.run(year=2026, quarter=1)

    failing_cache = tmp_path / f"{mod._api_key_id_token(failing_hash)}_2026_q1.pdf"
    succeeding_cache = tmp_path / f"{mod._api_key_id_token(succeeding_hash)}_2026_q1.pdf"
    assert summary["rendered"] == 1
    assert summary["billed"] == 1
    assert summary["billing_failed"] == 1
    assert summary["render_failed"] == 0
    assert billed_hashes == [succeeding_hash]
    assert not failing_cache.exists()
    assert succeeding_cache.exists()


def test_quarterly_cron_charges_first_then_render_failure_is_pdf_failed(
    seeded_db: Path,
    recurring_key,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEEP-47 Pattern A — charge BEFORE render.

    Replaces the legacy "render then bill" path. Under the charge-first
    fence, a render failure leaves a billed row behind (status='pdf_failed'
    in the saga table) which the reconcile cron can refund out-of-band.
    The previous behaviour (render fails before billing happens) created a
    surface where 100% of cap-exceeded keys still ate WeasyPrint CPU.
    """
    from jpintel_mcp.api import recurring_quarterly as mod
    from scripts.cron import generate_quarterly_reports as cron

    key_hash = hash_api_key(recurring_key)
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("DELETE FROM client_profiles")
        conn.execute(
            "INSERT INTO client_profiles(api_key_hash, name_label) VALUES (?, ?)",
            (key_hash, "render-fail-profile"),
        )
        conn.commit()
    finally:
        conn.close()

    def fail_render(*, out_path: Path, context: dict[str, object]) -> bool:
        return False

    billed_calls: list[str] = []

    def record_billing(conn: sqlite3.Connection, key_hash: str) -> bool:
        billed_calls.append(key_hash)
        return True

    monkeypatch.setattr(mod, "_QUARTERLY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_render_pdf_to", fail_render)
    monkeypatch.setattr(mod, "_record_metered_pdf", record_billing)
    monkeypatch.setattr(cron, "_eligible_keys", lambda _conn: [key_hash])

    summary = cron.run(year=2026, quarter=1)

    # Pattern A: billing fired pre-render and succeeded; the render failure
    # is a separate signal handled by reconcile cron, not a billing failure.
    assert summary["rendered"] == 0
    assert summary["render_failed"] == 1
    assert billed_calls == [key_hash]
    assert list(tmp_path.iterdir()) == []


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
