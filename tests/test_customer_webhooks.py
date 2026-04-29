"""Tests for /v1/me/webhooks + scripts/cron/dispatch_webhooks.

Coverage:
  * POST   /v1/me/webhooks              — auth, validation, secret reveal,
                                          internal-IP block, count cap
  * GET    /v1/me/webhooks              — only-mine, secret hidden in list
  * DELETE /v1/me/webhooks/{id}         — soft-delete + 404 on foreign id
  * POST   /v1/me/webhooks/{id}/test    — happy path + rate limit
  * Cron `dispatch_webhooks.run`        — collect events, dedup,
                                          retry policy, auto-disable

The cron uses httpx so we monkeypatch httpx.Client to avoid real network
I/O. The dispatcher's HMAC + payload formatting is asserted by capturing
the headers / body the patched client sees.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def webhook_key(seeded_db: Path) -> str:
    """Authenticated paid key for webhook tests."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_webhook_test",
        tier="paid",
        stripe_subscription_id="sub_webhook_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_customer_webhooks_table(seeded_db: Path):
    """Apply migration 080 onto the test DB and clear rows between cases."""
    repo = Path(__file__).resolve().parent.parent
    sql_path = repo / "scripts" / "migrations" / "080_customer_webhooks.sql"
    sql = sql_path.read_text(encoding="utf-8")

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        # webhook_deliveries has a FK on customer_webhooks — children
        # must be cleared first, otherwise the parent DELETE 1555s.
        c.execute("DELETE FROM webhook_deliveries")
        c.execute("DELETE FROM customer_webhooks")
        # Also wipe programs rows seeded by prior cron tests (the
        # seeded_db fixture is session-scoped, so without this the
        # second dispatcher test sees leaked rows from the first).
        c.execute("DELETE FROM programs WHERE unified_id LIKE 'P-%'")
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_register_requires_auth(client):
    r = client.post(
        "/v1/me/webhooks",
        json={
            "url": "https://hooks.example.com/x",
            "event_types": ["program.created"],
        },
    )
    assert r.status_code == 401


def test_register_rejects_http_url(client, webhook_key):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "http://example.com/hook",
            "event_types": ["program.created"],
        },
    )
    assert r.status_code == 400
    assert "https" in r.json()["detail"].lower()


def test_register_rejects_internal_ip(client, webhook_key):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "https://10.0.0.5/hook",
            "event_types": ["program.created"],
        },
    )
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "private" in detail or "internal" in detail


def test_register_rejects_loopback(client, webhook_key):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "https://127.0.0.1/hook",
            "event_types": ["program.created"],
        },
    )
    assert r.status_code == 400


def test_register_rejects_unknown_event_type(client, webhook_key):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "https://hooks.example.com/x",
            "event_types": ["totally.fake"],
        },
    )
    # Pydantic Literal rejection => 422
    assert r.status_code == 422


def test_register_happy_path_returns_secret_once(client, webhook_key, seeded_db):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "https://hooks.example.com/zk",
            "event_types": ["program.created", "program.amended"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["url"] == "https://hooks.example.com/zk"
    assert body["event_types"] == ["program.created", "program.amended"]
    assert body["status"] == "active"
    assert body["failure_count"] == 0
    # The full secret comes ONLY on register response.
    assert body["secret_hmac"] is not None
    assert body["secret_hmac"].startswith("whsec_")
    assert body["secret_last4"] == body["secret_hmac"][-4:]

    # Listing it back returns secret_hmac=None (only secret_last4).
    r2 = client.get("/v1/me/webhooks", headers={"X-API-Key": webhook_key})
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["secret_hmac"] is None
    assert rows[0]["secret_last4"] == body["secret_last4"]


def test_list_only_mine(client, webhook_key, seeded_db):
    # Register one for our key.
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={
            "url": "https://hooks.example.com/mine",
            "event_types": ["program.created"],
        },
    )
    assert r.status_code == 201

    # Insert a foreign row directly (different api_key_hash).
    c = sqlite3.connect(seeded_db)
    c.execute(
        "INSERT INTO customer_webhooks(api_key_hash, url, event_types_json, "
        "secret_hmac) VALUES (?, ?, ?, ?)",
        ("foreign_key_hash", "https://other.example.com/x", '["program.created"]',
         "whsec_foreign"),
    )
    c.commit()
    c.close()

    # List for our key — must NOT include foreign row.
    r2 = client.get("/v1/me/webhooks", headers={"X-API-Key": webhook_key})
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["url"] == "https://hooks.example.com/mine"


def test_delete_soft_deletes_and_404_on_foreign(client, webhook_key, seeded_db):
    # Register
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={"url": "https://hooks.example.com/x", "event_types": ["program.created"]},
    )
    wid = r.json()["id"]

    # Foreign id => 404.
    r404 = client.delete("/v1/me/webhooks/9999", headers={"X-API-Key": webhook_key})
    assert r404.status_code == 404

    # Own id => ok=True; row stays (soft delete).
    rdel = client.delete(f"/v1/me/webhooks/{wid}", headers={"X-API-Key": webhook_key})
    assert rdel.status_code == 200 and rdel.json() == {"ok": True, "id": wid}

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT status, disabled_reason FROM customer_webhooks WHERE id = ?", (wid,)
    ).fetchone()
    c.close()
    assert row["status"] == "disabled"
    assert row["disabled_reason"] == "deleted_by_customer"


def test_count_cap(client, webhook_key, monkeypatch):
    """At MAX_WEBHOOKS_PER_KEY=10 the 11th register should 400."""
    from jpintel_mcp.api import customer_webhooks as cw

    # Lower the cap for a faster test.
    monkeypatch.setattr(cw, "MAX_WEBHOOKS_PER_KEY", 2)

    for i in range(2):
        r = client.post(
            "/v1/me/webhooks",
            headers={"X-API-Key": webhook_key},
            json={
                "url": f"https://hooks.example.com/{i}",
                "event_types": ["program.created"],
            },
        )
        assert r.status_code == 201, r.text

    r3 = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={"url": "https://hooks.example.com/x", "event_types": ["program.created"]},
    )
    assert r3.status_code == 400
    assert "cap" in r3.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test delivery (POST /test)
# ---------------------------------------------------------------------------


class _MockResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.is_success = 200 <= status_code < 300


class _MockClient:
    """Capturing httpx.Client double for /test + cron tests.

    Records every (url, content, headers) tuple it sees so tests can
    assert on the HMAC, headers, and body shape. ``status_code`` and
    ``raise_kind`` cycle through ``responses`` so retry-policy tests can
    seed multiple distinct outcomes.
    """

    def __init__(self, responses=None):
        # responses is a list of (status_code, text) OR an Exception
        # instance to raise. Cycle deterministically.
        self._responses = list(responses or [(200, "")])
        self._idx = 0
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def post(self, url, *, content=None, headers=None, timeout=None, **_):
        self.calls.append((url, content, dict(headers or {})))
        idx = min(self._idx, len(self._responses) - 1)
        self._idx += 1
        resp = self._responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return _MockResponse(*resp)


def test_test_delivery_signs_payload_with_hmac(
    client, webhook_key, monkeypatch,
):
    # Register first.
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={"url": "https://hooks.example.com/test", "event_types": ["program.created"]},
    )
    body = r.json()
    wid = body["id"]
    secret = body["secret_hmac"]

    # Stub httpx.Client used inside test_delivery.
    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)

    rt = client.post(f"/v1/me/webhooks/{wid}/test", headers={"X-API-Key": webhook_key})
    assert rt.status_code == 200, rt.text
    out = rt.json()
    assert out["ok"] is True
    assert out["status_code"] == 200
    assert out["error"] is None
    assert out["signature"].startswith("hmac-sha256=")

    # Verify the HMAC matches the body bytes the mock saw.
    assert len(mock.calls) == 1
    sent_url, sent_body, sent_headers = mock.calls[0]
    assert sent_url == "https://hooks.example.com/test"
    expected_sig = "hmac-sha256=" + hmac.new(
        secret.encode(), sent_body, hashlib.sha256
    ).hexdigest()
    assert sent_headers["X-Zeimu-Signature"] == expected_sig
    assert sent_headers["User-Agent"] == "zeimu-kaikei-webhook/1.0"
    payload = json.loads(sent_body.decode())
    assert payload["event_type"] == "test.ping"


def test_test_delivery_disabled_webhook_400(client, webhook_key, seeded_db):
    r = client.post(
        "/v1/me/webhooks",
        headers={"X-API-Key": webhook_key},
        json={"url": "https://hooks.example.com/x", "event_types": ["program.created"]},
    )
    wid = r.json()["id"]
    # Manually disable
    c = sqlite3.connect(seeded_db)
    c.execute("UPDATE customer_webhooks SET status='disabled' WHERE id = ?", (wid,))
    c.commit()
    c.close()

    rt = client.post(f"/v1/me/webhooks/{wid}/test", headers={"X-API-Key": webhook_key})
    assert rt.status_code == 400
    assert "disabled" in rt.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Dispatcher cron tests
# ---------------------------------------------------------------------------


def _backdate_existing_programs(db_path: Path) -> None:
    """Push every existing programs.updated_at into the deep past.

    The dispatcher filters by `updated_at >= since_iso`. By backdating
    the seeded_db fixture's 4 demo programs we leave only the rows the
    individual test inserts in the dispatcher's window. Call once at
    the start of any dispatcher-cron test BEFORE seeding fresh rows.
    """
    c = sqlite3.connect(db_path)
    c.execute(
        "UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'"
    )
    c.commit()
    c.close()


def _seed_program_created(db_path: Path, unified_id: str = "P-TEST-1") -> None:
    """Insert a 'newly updated' programs row that the dispatcher will pick."""
    c = sqlite3.connect(db_path)
    c.execute(
        "INSERT OR REPLACE INTO programs("
        "  unified_id, primary_name, official_url, source_url, prefecture,"
        "  program_kind, tier, excluded, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))",
        (
            unified_id,
            "Test Program",
            "https://example.gov/p",
            "https://example.gov/p/source",
            "全国",
            "subsidy",
            "A",
        ),
    )
    c.commit()
    c.close()


def _register_webhook(db_path: Path, api_key_hash: str, url: str,
                      event_types: list[str], secret: str = "whsec_test") -> int:
    c = sqlite3.connect(db_path)
    cur = c.execute(
        "INSERT INTO customer_webhooks(api_key_hash, url, event_types_json, "
        "secret_hmac, status, failure_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', 0, datetime('now'), datetime('now'))",
        (api_key_hash, url, json.dumps(event_types), secret),
    )
    wid = cur.lastrowid
    c.commit()
    c.close()
    return wid


def test_dispatch_delivers_signs_and_dedups(seeded_db, webhook_key, monkeypatch):
    """Full integration: register webhook + program.created event;
    run dispatcher; assert HMAC matches; running again is a no-op (dedup).
    """
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key)
    secret = "whsec_dedup_test"
    _backdate_existing_programs(seeded_db)
    wid = _register_webhook(
        seeded_db, key_hash, "https://hooks.example.com/zk",
        ["program.created"], secret=secret,
    )
    _seed_program_created(seeded_db, unified_id="P-DEDUP-1")

    # Stub httpx.Client + the autonomath collector (we're testing
    # program.created here, not amendment_diff which lives in autonomath.db).
    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)

    # Stub the stripe report path so the test does not require Stripe.
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    # Bypass DNS-based safety check so the test does not depend on
    # resolvable example domains — _is_safe_webhook does a real
    # socket.getaddrinfo on hostnames not in the literal-IP path.
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary["events_collected"] >= 1
    assert summary["deliveries_succeeded"] == 1
    assert summary["deliveries_failed"] == 0

    # HMAC matches.
    sent_url, sent_body, sent_headers = mock.calls[0]
    expected = "hmac-sha256=" + hmac.new(
        secret.encode(), sent_body, hashlib.sha256
    ).hexdigest()
    assert sent_headers["X-Zeimu-Signature"] == expected
    assert sent_headers["User-Agent"] == "zeimu-kaikei-webhook/1.0"
    assert sent_headers["X-Zeimu-Event"] == "program.created"
    payload = json.loads(sent_body.decode())
    assert payload["event_type"] == "program.created"
    assert payload["data"]["unified_id"] == "P-DEDUP-1"
    assert "timestamp" in payload

    # webhook_deliveries row recorded.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT event_type, event_id, status_code, attempt_count "
        "FROM webhook_deliveries WHERE webhook_id = ?", (wid,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "program.created"
    assert rows[0]["event_id"] == "P-DEDUP-1"
    assert rows[0]["status_code"] == 200
    c.close()

    # Re-run is a no-op (dedup): no new HTTP call, summary skipped++.
    mock2 = _MockClient(responses=[(200, "")])
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock2)
    summary2 = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary2["deliveries_skipped_dedup"] >= 1
    assert summary2["deliveries_succeeded"] == 0
    assert len(mock2.calls) == 0


def test_dispatch_retry_on_5xx_then_success(seeded_db, webhook_key, monkeypatch):
    """First attempt 502, second 200 — single event, attempt_count == 2."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key)
    _backdate_existing_programs(seeded_db)
    _register_webhook(
        seeded_db, key_hash, "https://hooks.example.com/r",
        ["program.created"], secret="whsec_retry",
    )
    _seed_program_created(seeded_db, unified_id="P-RETRY-1")

    mock = _MockClient(responses=[(502, "bad gateway"), (200, "")])
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    # No-op the sleep so the test does not actually wait 60s.
    monkeypatch.setattr("scripts.cron.dispatch_webhooks.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    # Bypass DNS-based safety check so the test does not depend on
    # resolvable example domains — _is_safe_webhook does a real
    # socket.getaddrinfo on hostnames not in the literal-IP path.
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary["deliveries_succeeded"] == 1
    assert len(mock.calls) == 2  # initial + 1 retry

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT attempt_count, status_code FROM webhook_deliveries"
    ).fetchone()
    c.close()
    assert row["status_code"] == 200
    assert row["attempt_count"] == 2


def test_dispatch_auto_disable_after_5_failures(seeded_db, webhook_key, monkeypatch):
    """5 separate events all fail with 5xx → webhook flips to disabled."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key)
    _backdate_existing_programs(seeded_db)
    wid = _register_webhook(
        seeded_db, key_hash, "https://hooks.example.com/dead",
        ["program.created"], secret="whsec_dead",
    )
    # Seed 5 fresh program rows so the collector returns 5 events.
    for i in range(5):
        _seed_program_created(seeded_db, unified_id=f"P-DEAD-{i}")

    # All retries 5xx — every event fails through 4 attempts.
    # _MockClient cycles forever on the last entry once exhausted.
    mock = _MockClient(responses=[(503, "down")])
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr("scripts.cron.dispatch_webhooks.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    # Bypass DNS-based safety check so the test does not depend on
    # resolvable example domains — _is_safe_webhook does a real
    # socket.getaddrinfo on hostnames not in the literal-IP path.
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary["webhooks_disabled"] == 1

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT status, failure_count, disabled_reason FROM customer_webhooks "
        "WHERE id = ?", (wid,),
    ).fetchone()
    c.close()
    assert row["status"] == "disabled"
    assert row["failure_count"] >= 5
    assert "consecutive failures" in (row["disabled_reason"] or "").lower()


def test_dispatch_does_not_retry_4xx(seeded_db, webhook_key, monkeypatch):
    """A 400 Bad Request should NOT trigger retries — caller fix needed."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key)
    _backdate_existing_programs(seeded_db)
    _register_webhook(
        seeded_db, key_hash, "https://hooks.example.com/badreq",
        ["program.created"], secret="whsec_400",
    )
    _seed_program_created(seeded_db, unified_id="P-400-1")

    mock = _MockClient(responses=[(400, "bad request")])
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr("scripts.cron.dispatch_webhooks.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    # Bypass DNS-based safety check so the test does not depend on
    # resolvable example domains — _is_safe_webhook does a real
    # socket.getaddrinfo on hostnames not in the literal-IP path.
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    # Single attempt (no retry on 4xx).
    assert len(mock.calls) == 1
    assert summary["deliveries_failed"] == 1
    assert summary["deliveries_succeeded"] == 0


def test_compute_signature_matches_python_reference():
    """compute_signature must match the canonical HMAC-SHA256 spec."""
    from jpintel_mcp.api.customer_webhooks import compute_signature

    secret = "whsec_known"
    body = b'{"event_type":"x","timestamp":"y","data":{}}'
    expected = "hmac-sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    assert compute_signature(secret, body) == expected
