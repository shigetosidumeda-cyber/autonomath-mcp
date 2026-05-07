"""Tests for /v1/me/amendment_alerts and the amendment_alert_fanout cron.

Coverage:
  * POST /v1/me/amendment_alerts/subscribe — auth, validation, watch shape
  * GET  /v1/me/amendment_alerts/feed       — auth, JSON / Atom format
  * DELETE /v1/me/amendment_alerts/{id}     — soft-delete + 404
  * scripts/cron/amendment_alert_fanout.run — dry-run with seeded diffs
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def feed_key(seeded_db: Path) -> str:
    """Authenticated paid key for amendment-alert tests."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_amendment_alert_test",
        tier="paid",
        stripe_subscription_id="sub_amendment_alert_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_amendment_alert_subscriptions_table(seeded_db: Path):
    """Apply migration wave24_194 onto the test DB and clear rows between cases.

    schema.sql does not declare amendment_alert_subscriptions yet — the
    table only lives in scripts/migrations/wave24_194_amendment_alert_subscriptions.sql.
    The router's _ensure_table helper guarantees the table exists at request
    time, but we apply the migration explicitly so unit tests reflect the
    production schema (CHECK constraints, defaults, indexes).
    """
    repo = Path(__file__).resolve().parent.parent
    sql_path = (
        repo
        / "scripts"
        / "migrations"
        / "wave24_194_amendment_alert_subscriptions.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.execute("DELETE FROM amendment_alert_subscriptions")
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# POST /subscribe
# ---------------------------------------------------------------------------


def test_subscribe_requires_auth(client):
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        json={"watch": [{"type": "program_id", "id": "UNI-test-s-1"}]},
    )
    assert r.status_code == 401


def test_subscribe_requires_watch_array(client, feed_key):
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={"watch": []},
    )
    # Pydantic min_length=1 ⇒ 422
    assert r.status_code in (400, 422)


def test_subscribe_rejects_unknown_type(client, feed_key):
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={"watch": [{"type": "bogus_type", "id": "x"}]},
    )
    assert r.status_code in (400, 422)


def test_subscribe_rejects_duplicate_watch(client, feed_key):
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={
            "watch": [
                {"type": "program_id", "id": "UNI-test-s-1"},
                {"type": "program_id", "id": "UNI-test-s-1"},
            ]
        },
    )
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower()


def test_subscribe_rejects_too_many_watches(client, feed_key):
    big = [{"type": "program_id", "id": f"UNI-{i}"} for i in range(60)]
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={"watch": big},
    )
    assert r.status_code in (400, 422)


def test_subscribe_happy_path(client, feed_key, seeded_db):
    r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={
            "watch": [
                {"type": "program_id", "id": "UNI-test-s-1"},
                {"type": "law_id", "id": "LAW-test-1"},
                {"type": "industry_jsic", "id": "D"},
            ]
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["watch_count"] == 3
    assert isinstance(body["subscription_id"], int)
    assert body["created_at"]

    # Verify the row is on disk under the calling key.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT id, watch_json, deactivated_at FROM amendment_alert_subscriptions"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    assert rows[0]["deactivated_at"] is None
    decoded = json.loads(rows[0]["watch_json"])
    assert {(w["type"], w["id"]) for w in decoded} == {
        ("program_id", "UNI-test-s-1"),
        ("law_id", "LAW-test-1"),
        ("industry_jsic", "D"),
    }


# ---------------------------------------------------------------------------
# GET /feed
# ---------------------------------------------------------------------------


def test_feed_requires_auth(client):
    r = client.get("/v1/me/amendment_alerts/feed")
    assert r.status_code == 401


def test_feed_empty_when_no_subscriptions(client, feed_key):
    r = client.get(
        "/v1/me/amendment_alerts/feed",
        headers={"X-API-Key": feed_key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["subscription_count"] == 0
    assert body["window_days"] == 90
    assert body["results"] == []


def test_feed_atom_format(client, feed_key):
    # Subscribe first so the feed has at least one watch in scope.
    sub_r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={"watch": [{"type": "program_id", "id": "UNI-test-s-1"}]},
    )
    assert sub_r.status_code == 201

    r = client.get(
        "/v1/me/amendment_alerts/feed?format=atom",
        headers={"X-API-Key": feed_key},
    )
    assert r.status_code == 200
    body = r.text
    assert body.startswith("<?xml")
    assert "<feed " in body
    assert "amendment alert feed" in body


# ---------------------------------------------------------------------------
# DELETE /{subscription_id}
# ---------------------------------------------------------------------------


def test_delete_requires_auth(client):
    r = client.delete("/v1/me/amendment_alerts/1")
    assert r.status_code == 401


def test_delete_404_for_unknown_id(client, feed_key):
    r = client.delete(
        "/v1/me/amendment_alerts/9999",
        headers={"X-API-Key": feed_key},
    )
    assert r.status_code == 404


def test_delete_soft_deletes_row(client, feed_key, seeded_db):
    sub_r = client.post(
        "/v1/me/amendment_alerts/subscribe",
        headers={"X-API-Key": feed_key},
        json={"watch": [{"type": "program_id", "id": "UNI-test-s-1"}]},
    )
    assert sub_r.status_code == 201
    sub_id = sub_r.json()["subscription_id"]

    r = client.delete(
        f"/v1/me/amendment_alerts/{sub_id}",
        headers={"X-API-Key": feed_key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "subscription_id": sub_id}

    # Row stays on disk with deactivated_at set.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT deactivated_at FROM amendment_alert_subscriptions WHERE id = ?",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row["deactivated_at"] is not None

    # Re-deleting returns 404 (cannot probe other keys' id space either).
    r2 = client.delete(
        f"/v1/me/amendment_alerts/{sub_id}",
        headers={"X-API-Key": feed_key},
    )
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Cron dry-run smoke
# ---------------------------------------------------------------------------


def test_cron_dry_run_smoke(seeded_db, monkeypatch, feed_key):
    """Cron dry-run on a freshly-seeded jpintel DB completes without error.

    Smoke test only — does not seed am_amendment_diff (autonomath.db is
    not provisioned in unit tests). Verifies the script imports cleanly,
    creates the table if missing, and returns a structured summary.
    """
    # Insert one active subscription.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        # Resolve the key_hash from the raw key.
        from jpintel_mcp.api.deps import hash_api_key

        key_hash = hash_api_key(feed_key)
        c.execute(
            "INSERT INTO amendment_alert_subscriptions(api_key_hash, watch_json) "
            "VALUES (?, ?)",
            (
                key_hash,
                json.dumps([{"type": "program_id", "id": "UNI-test-s-1"}]),
            ),
        )
        c.commit()
    finally:
        c.close()

    monkeypatch.setenv("JPINTEL_DB_PATH", str(seeded_db))

    # Stub out connect_autonomath so the cron does not try to open the
    # 9.4 GB production DB (which is absent in CI).
    from scripts.cron import amendment_alert_fanout as cron_mod

    class _StubConn:
        def execute(self, sql, *a, **kw):
            class _Cur:
                def fetchall(self):  # noqa: N805 (cursor stub, not a method on _StubConn)
                    return []

            return _Cur()

        def close(self):
            pass

    monkeypatch.setattr(cron_mod, "_connect_autonomath", lambda: _StubConn())

    summary = cron_mod.run(dry_run=True)
    assert summary["dry_run"] is True
    assert summary["subscriptions_seen"] >= 1
    assert summary["diffs_total"] == 0  # stubbed autonomath.db ⇒ no diffs
    assert "started_at" in summary
    assert "finished_at" in summary
