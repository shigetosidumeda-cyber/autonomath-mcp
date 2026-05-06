"""Smoke tests for the workflow-integrations 5-pack (migration 105).

Five integrations under test:
  1. Slack       — slash command + incoming webhook (api/integrations.py)
  2. Google      — OAuth start + callback + sheet binding
  3. Email       — Postmark inbound parse + connect flag
  4. Excel       — saved_search results.xlsx download
  5. kintone     — connect (REST) + sync with idempotency

Test posture:
  * No external network calls. The Google token endpoint, Slack incoming
    webhook, and kintone REST API are mocked at the urllib.request layer.
  * Each integration: at least one happy path + at least one negative
    edge (unauth, SSRF prefix, idempotency dedup).
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures — apply migration 105 + provision a Fernet secret
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _integration_token_secret(monkeypatch):
    """Provide a deterministic Fernet key for the helper module."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("INTEGRATION_TOKEN_SECRET", Fernet.generate_key().decode())
    yield


@pytest.fixture(autouse=True)
def _ensure_integrations_schema(seeded_db: Path):
    """Apply migrations 079 (saved_searches) + 099 + 105 onto the test DB."""
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"
    extend105 = repo / "scripts" / "migrations" / "105_integrations.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        # 099 / 105 ALTER TABLE statements are not idempotent in SQLite;
        # guard via PRAGMA table_info before re-applying.
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        if "sheet_id" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN sheet_id TEXT")
        if "sheet_tab_name" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN sheet_tab_name TEXT")

        # CREATE statements from 105 are idempotent (IF NOT EXISTS); split
        # the script and apply only the CREATE parts to avoid the ALTERs
        # which we just guarded above. Tables first, then indexes (the
        # latter reference the former). Strip leading comment lines from
        # each fragment before classifying.
        sql105 = extend105.read_text(encoding="utf-8")

        def _strip_comments(s: str) -> str:
            return "\n".join(
                line
                for line in s.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ).strip()

        fragments = [_strip_comments(s) for s in sql105.split(";")]
        tables = [s for s in fragments if s.upper().startswith("CREATE TABLE")]
        indexes = [s for s in fragments if s.upper().startswith("CREATE INDEX")]
        for s in tables + indexes:
            c.execute(s)
        c.execute("DELETE FROM saved_searches")
        c.execute("DELETE FROM integration_accounts")
        c.execute("DELETE FROM integration_sync_log")
        c.commit()
    finally:
        c.close()
    yield


@pytest.fixture()
def integration_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_integration_test",
        tier="paid",
        stripe_subscription_id="sub_integ_test",
    )
    c.commit()
    c.close()
    return raw


# ---------------------------------------------------------------------------
# 1) Slack — slash command + SSRF prefix on /v1/me/recurring/slack
# ---------------------------------------------------------------------------


def test_slack_slash_command_returns_blocks(client, integration_key):
    r = client.post(
        "/v1/integrations/slack",
        params={"key": integration_key},
        data={"text": "DX 補助金", "team_id": "T1", "user_id": "U1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response_type"] in ("in_channel", "ephemeral")
    assert "blocks" in body
    assert any(
        "税理士法" in b.get("text", {}).get("text", "")
        for b in body["blocks"]
        if b.get("type") == "context"
        for el in b.get("elements", [])
    ) or any(
        "税理士法" in str(el)
        for b in body["blocks"]
        if b.get("type") == "context"
        for el in b.get("elements", [])
    )


def test_slack_slash_command_empty_query_returns_help(client):
    r = client.post(
        "/v1/integrations/slack",
        data={"text": "", "team_id": "T1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["response_type"] == "ephemeral"
    assert "/zeimukaikei" in body["text"]


def test_slack_slash_command_paid_final_cap_failure_is_not_billed(
    client,
    integration_key,
    seeded_db,
    monkeypatch,
):
    from jpintel_mcp.api.middleware import customer_cap

    key_hash = hash_api_key(integration_key)

    def usage_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "programs.search"),
            ).fetchone()
            return int(row[0])
        finally:
            c.close()

    before_usage = usage_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    r = client.post(
        "/v1/integrations/slack",
        params={"key": integration_key},
        data={"text": "DX 補助金", "team_id": "T1", "user_id": "U1"},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before_usage


def test_slack_recurring_webhook_ssrf_prefix(client, integration_key):
    """SSRF defense: only https://hooks.slack.com/services/ allowed."""
    # First create a saved search so the bind has a target.
    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": integration_key},
        json={
            "name": "東京都の補助金",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r0.status_code == 201, r0.text
    saved_id = r0.json()["id"]

    # Reject non-Slack-domain webhook.
    r = client.post(
        "/v1/me/recurring/slack",
        headers={"X-API-Key": integration_key},
        json={
            "saved_search_id": saved_id,
            "channel_url": "https://attacker.example.com/evil",
        },
    )
    assert r.status_code == 422, r.text
    assert "hooks.slack.com" in r.text


# ---------------------------------------------------------------------------
# 2) Google Sheets — OAuth start + callback + sheet bind
# ---------------------------------------------------------------------------


def test_google_oauth_start_returns_authorize_url(client, integration_key, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    r = client.post(
        "/v1/integrations/google/start",
        headers={"X-API-Key": integration_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "authorize_url" in body
    assert "accounts.google.com" in body["authorize_url"]
    assert "test-client-id" in body["authorize_url"]
    # State token mirrors the api-key prefix + nonce.
    assert "." in body["state"]


def test_google_oauth_start_503_when_unconfigured(client, integration_key, monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    r = client.post(
        "/v1/integrations/google/start",
        headers={"X-API-Key": integration_key},
    )
    assert r.status_code == 503


def test_google_callback_persists_token(client, integration_key, monkeypatch, seeded_db):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csecret")
    # Begin flow.
    r = client.post(
        "/v1/integrations/google/start",
        headers={"X-API-Key": integration_key},
    )
    assert r.status_code == 200
    state = r.json()["state"]

    # Mock the urllib.request.urlopen call into Google's token endpoint.
    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    fake_token_response = _FakeResp(
        {
            "access_token": "ya29.a-test-access",
            "refresh_token": "1//refresh-test",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "token_type": "Bearer",
        }
    )
    with patch.object(urllib.request, "urlopen", return_value=fake_token_response):
        r2 = client.get(
            "/v1/integrations/google/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
    assert r2.status_code in (302, 303)

    # Verify token row landed.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT provider, encrypted_blob FROM integration_accounts WHERE provider='google_sheets'"
    ).fetchone()
    c.close()
    assert row is not None
    assert row["provider"] == "google_sheets"
    # Encrypted blob must NOT contain the plaintext refresh token.
    assert b"1//refresh-test" not in row["encrypted_blob"]


def test_bind_sheet_to_saved_search(client, integration_key):
    # Create saved search.
    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": integration_key},
        json={
            "name": "Sheet bind test",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    saved_id = r0.json()["id"]
    sheet_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890_test"
    r = client.post(
        f"/v1/me/saved_searches/{saved_id}/sheet",
        headers={"X-API-Key": integration_key},
        json={"sheet_id": sheet_id, "sheet_tab_name": "Tab1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sheet_id"] == sheet_id
    assert body["sheet_tab_name"] == "Tab1"


# ---------------------------------------------------------------------------
# 3) Email — Postmark inbound + connect flag
# ---------------------------------------------------------------------------


def test_email_connect_flags_account(client, integration_key, seeded_db):
    r = client.post(
        "/v1/integrations/email/connect",
        headers={"X-API-Key": integration_key},
        json={"reply_from": "query@parse.jpcite.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # The response sanitizer rewrites raw emails to <email-redacted> in the
    # outgoing JSON; the stored row preserves the original for cron use.

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT display_handle FROM integration_accounts WHERE provider='postmark_inbound'"
    ).fetchone()
    c.close()
    assert row is not None
    assert row["display_handle"] == "query@parse.jpcite.com"


def test_email_inbound_unknown_key_is_silently_ignored(client):
    """An inbound email from a key we cannot resolve must NOT 500 — Postmark
    will retry-storm a 5xx. We respond 200 with status='ignored'."""
    payload = {
        "OriginalRecipient": "query+am_unknownkey@parse.jpcite.com",
        "FromFull": {"Email": "outsider@example.com"},
        "Subject": "DX 補助金",
        "MessageID": "msg-1",
    }
    r = client.post("/v1/integrations/email/inbound", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ignored", "ok")


# ---------------------------------------------------------------------------
# 4) Excel — saved_search results.xlsx
# ---------------------------------------------------------------------------


def test_saved_search_results_xlsx_returns_workbook(client, integration_key):
    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": integration_key},
        json={
            "name": "XLSX dl",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    saved_id = r0.json()["id"]
    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results.xlsx",
        headers={"X-API-Key": integration_key},
    )
    # 200 (workbook) or 503 if openpyxl extra not installed in the test env.
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        # XLSX is a zip — first 2 bytes are 'PK'.
        assert r.content[:2] == b"PK"


def test_saved_search_xlsx_404_for_other_keys_id(client, integration_key, seeded_db):
    # Create an orphan saved search owned by a different key.
    c = sqlite3.connect(seeded_db)
    c.execute(
        "INSERT INTO saved_searches (api_key_hash, name, query_json, frequency, "
        "notify_email, channel_format, channel_url, last_run_at, created_at) "
        "VALUES (?, 'orphan', '{}', 'daily', 'x@x.com', 'email', NULL, NULL, "
        "'2026-04-29T00:00:00Z')",
        ("0000000000000000other_key_hash" + "0" * 16,),
    )
    other_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit()
    c.close()

    r = client.get(
        f"/v1/me/saved_searches/{other_id}/results.xlsx",
        headers={"X-API-Key": integration_key},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5) kintone — connect (REST) + sync (idempotency)
# ---------------------------------------------------------------------------


def test_kintone_connect_rejects_non_cybozu_domain(client, integration_key):
    r = client.post(
        "/v1/integrations/kintone/connect",
        headers={"X-API-Key": integration_key},
        json={
            "domain": "evil.example.com",
            "app_id": 1,
            "api_token": "x" * 16,
        },
    )
    assert r.status_code == 422


def test_kintone_connect_then_sync_is_idempotent(client, integration_key, seeded_db):
    # Connect.
    r0 = client.post(
        "/v1/integrations/kintone/connect",
        headers={"X-API-Key": integration_key},
        json={
            "domain": "acme.cybozu.com",
            "app_id": 42,
            "api_token": "kt-" + "x" * 32,
        },
    )
    assert r0.status_code == 200, r0.text

    # Build a saved search.
    r1 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": integration_key},
        json={
            "name": "kintone sync",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    saved_id = r1.json()["id"]

    # Mock the kintone POST so the test does not hit the network.
    class _OkResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ids":["1","2"],"revisions":["1","1"]}'

    with patch.object(urllib.request, "urlopen", return_value=_OkResp()):
        r2 = client.post(
            "/v1/integrations/kintone/sync",
            headers={"X-API-Key": integration_key},
            json={
                "saved_search_id": saved_id,
                "idempotency_key": "ss-test-2026-04-29",
                "max_rows": 5,
            },
        )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert body["deduped"] is False

    # Replay with same idempotency_key — must return deduped=True.
    with patch.object(urllib.request, "urlopen", return_value=_OkResp()):
        r3 = client.post(
            "/v1/integrations/kintone/sync",
            headers={"X-API-Key": integration_key},
            json={
                "saved_search_id": saved_id,
                "idempotency_key": "ss-test-2026-04-29",
                "max_rows": 5,
            },
        )
    assert r3.status_code == 200
    assert r3.json()["deduped"] is True


def test_kintone_sync_paid_final_cap_failure_does_not_push_or_lock_idempotency(
    client,
    integration_key,
    seeded_db,
    monkeypatch,
):
    from jpintel_mcp.api.middleware import customer_cap

    key_hash = hash_api_key(integration_key)
    idempotency_key = "ss-test-cap-fail-2026-05-06"

    r0 = client.post(
        "/v1/integrations/kintone/connect",
        headers={"X-API-Key": integration_key},
        json={
            "domain": "acme.cybozu.com",
            "app_id": 42,
            "api_token": "kt-" + "x" * 32,
        },
    )
    assert r0.status_code == 200, r0.text

    r1 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": integration_key},
        json={
            "name": "kintone cap failure",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    saved_id = r1.json()["id"]

    def usage_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, "programs.search"),
            ).fetchone()
            return int(row[0])
        finally:
            c.close()

    def sync_log_count() -> int:
        c = sqlite3.connect(seeded_db)
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM integration_sync_log "
                "WHERE provider = 'kintone' AND idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return int(row[0])
        finally:
            c.close()

    before_usage = usage_count()
    before_sync_logs = sync_log_count()
    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )

    with patch.object(urllib.request, "urlopen") as urlopen_mock:
        r2 = client.post(
            "/v1/integrations/kintone/sync",
            headers={"X-API-Key": integration_key},
            json={
                "saved_search_id": saved_id,
                "idempotency_key": idempotency_key,
                "max_rows": 5,
            },
        )

    assert r2.status_code == 503, r2.text
    assert r2.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert not urlopen_mock.called
    assert usage_count() == before_usage
    assert sync_log_count() == before_sync_logs


def test_kintone_sync_requires_connect(client, integration_key):
    r = client.post(
        "/v1/integrations/kintone/sync",
        headers={"X-API-Key": integration_key},
        json={"saved_search_id": 999, "max_rows": 5},
    )
    # 412 Precondition Failed — kintone not connected for this key.
    assert r.status_code in (412, 404)


# ---------------------------------------------------------------------------
# Token-storage helper (Fernet round-trip)
# ---------------------------------------------------------------------------


def test_token_blob_roundtrip(seeded_db):
    from jpintel_mcp.api._integration_tokens import (
        decrypt_blob,
        encrypt_blob,
    )

    payload = {"refresh_token": "1//abc", "expires_in": 3600}
    blob = encrypt_blob(payload)
    assert isinstance(blob, bytes)
    assert b"refresh_token" not in blob  # ciphertext, not plaintext
    out = decrypt_blob(blob)
    assert out["refresh_token"] == "1//abc"
    assert out["expires_in"] == 3600
