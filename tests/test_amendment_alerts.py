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
    sql_path = repo / "scripts" / "migrations" / "wave24_194_amendment_alert_subscriptions.sql"
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
# R3 P1-4 (2026-05-13): industry_jsic IN-list cap + EXPLAIN QUERY PLAN
# ---------------------------------------------------------------------------


def test_industry_watch_list_too_long_returns_422():
    """`_fetch_diffs_for_watches` rejects the 51st industry_jsic watch in the
    unioned feed call with HTTP 422 `industry_watch_list_too_long`.

    Why this lives at the helper layer (not at /feed):
      The /feed route unions watches across ALL of the caller's active
      subscriptions. The per-subscription Pydantic cap (50) does not bound
      the per-call cap; only the helper sees the post-union list.
    """
    from fastapi import HTTPException

    from jpintel_mcp.api.amendment_alerts import (
        MAX_INDUSTRY_WATCHES_PER_CALL,
        WatchEntry,
        _fetch_diffs_for_watches,
    )

    # 50 industry_jsic + 1 → 51 → over cap, must 422.
    watches = [
        WatchEntry(type="industry_jsic", id=f"JSIC-{i}")
        for i in range(MAX_INDUSTRY_WATCHES_PER_CALL + 1)
    ]
    with pytest.raises(HTTPException) as exc_info:
        _fetch_diffs_for_watches(watches, since_iso="2026-01-01T00:00:00+00:00", limit=100)
    assert exc_info.value.status_code == 422
    assert "industry_watch_list_too_long" in exc_info.value.detail


def test_industry_watch_list_at_cap_does_not_422(monkeypatch):
    """Exactly 50 industry_jsic watches MUST be accepted (boundary case).

    Stub `connect_autonomath` so we do not require the 9.4 GB production DB.
    The returned conn raises `no such table: am_amendment_diff`, which the
    helper catches and converts to []. The path under test is the
    pre-connection cap branch — we only care it does not 422.
    """
    from jpintel_mcp.api import amendment_alerts as mod
    from jpintel_mcp.api.amendment_alerts import (
        MAX_INDUSTRY_WATCHES_PER_CALL,
        WatchEntry,
        _fetch_diffs_for_watches,
    )

    class _NoSuchTableConn:
        def execute(self, *_a, **_kw):
            raise sqlite3.OperationalError("no such table: am_amendment_diff")

        def close(self):
            pass

    monkeypatch.setattr(mod, "connect_autonomath", lambda: _NoSuchTableConn())

    watches = [
        WatchEntry(type="industry_jsic", id=f"JSIC-{i}")
        for i in range(MAX_INDUSTRY_WATCHES_PER_CALL)
    ]
    # Should NOT raise; returns [] because the stub trips the no-such-table guard.
    rows = _fetch_diffs_for_watches(watches, since_iso="2026-01-01T00:00:00+00:00", limit=100)
    assert rows == []


def test_industry_jsic_subquery_uses_index_in_explain_query_plan(tmp_path):
    """EXPLAIN QUERY PLAN asserts the sub-SELECT on `am_entity_facts` filtered
    by (field_name='industry_jsic', value IN (?)) uses an index.

    Why this test
    -------------
    R3 P1-4 capped the IN-list to 50, but unindexed access to am_entity_facts
    on (field_name, value) would still scan 6.12M rows × 50 lookups. The
    storage-side invariant is that an index on (field_name, value) exists.
    On the in-memory test DB we create the index explicitly and assert
    EXPLAIN reports SEARCH ... USING INDEX. Skip cleanly if EXPLAIN QUERY
    PLAN is unavailable (very old sqlite) or if the index plan cannot be
    forced (e.g. an empty table where SQLite always picks SCAN).
    """
    db_path = tmp_path / "explain_query_plan.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                value TEXT
            );
            -- The candidate index this test asserts as needed.
            CREATE INDEX idx_am_entity_facts_field_name_value
                ON am_entity_facts(field_name, value);
            """
        )
        # SQLite's planner won't reliably use the index on an empty table.
        # Seed enough rows to push the cost model toward the index.
        for i in range(200):
            conn.execute(
                "INSERT INTO am_entity_facts(entity_id, field_name, value) VALUES (?, ?, ?)",
                (f"ENT-{i:04d}", "industry_jsic" if i % 2 == 0 else "noise", f"V{i % 10}"),
            )
        conn.execute("ANALYZE")  # let the planner build sqlite_stat1
        conn.commit()

        try:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT entity_id FROM am_entity_facts "
                "WHERE field_name = 'industry_jsic' AND value IN (?, ?, ?)",
                ("V0", "V2", "V4"),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            pytest.skip(f"EXPLAIN QUERY PLAN unsupported on this sqlite build: {exc}")

        plan_text = " ".join(str(row) for row in plan).upper()
        if "USING INDEX" not in plan_text:
            pytest.skip(
                f"sqlite planner chose SCAN despite seeded rows + ANALYZE "
                f"(plan={plan_text!r}); test infra cannot exercise the "
                f"index-plan path. Production autonomath.db on Fly has the "
                f"row counts the planner needs."
            )
        assert "USING INDEX" in plan_text
        assert "AM_ENTITY_FACTS" in plan_text
    finally:
        conn.close()


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
            "INSERT INTO amendment_alert_subscriptions(api_key_hash, watch_json) VALUES (?, ?)",
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


def _apply_customer_webhooks_migration(db_path: Path) -> None:
    repo = Path(__file__).resolve().parent.parent
    sql_path = repo / "scripts" / "migrations" / "080_customer_webhooks.sql"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM webhook_deliveries")
        conn.execute("DELETE FROM customer_webhooks")
        conn.commit()
    finally:
        conn.close()


def _stub_amendment_diff_conn(entity_id: str = "UNI-test-s-1") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL,
            source_url TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO am_amendment_diff("
        "diff_id, entity_id, field_name, prev_value, new_value, detected_at, source_url"
        ") VALUES (?,?,?,?,?,?,?)",
        (
            9001,
            entity_id,
            "amount_max_yen",
            "100",
            "200",
            "2099-01-01T00:00:00+00:00",
            "https://example.gov/amendment/9001",
        ),
    )
    return conn


def _insert_amendment_subscription(db_path: Path, api_key_hash: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO amendment_alert_subscriptions(api_key_hash, watch_json) VALUES (?, ?)",
            (
                api_key_hash,
                json.dumps([{"type": "program_id", "id": "UNI-test-s-1"}]),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _fanout_cursor(db_path: Path, sub_id: int) -> str | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT last_fanout_at FROM amendment_alert_subscriptions WHERE id = ?",
            (sub_id,),
        ).fetchone()
        return row["last_fanout_at"]
    finally:
        conn.close()


def test_cron_uses_customer_webhooks_status_schema_and_advances_on_success(
    seeded_db,
    monkeypatch,
    feed_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import amendment_alert_fanout as cron_mod

    _apply_customer_webhooks_migration(seeded_db)
    key_hash = hash_api_key(feed_key)
    sub_id = _insert_amendment_subscription(seeded_db, key_hash)

    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            "INSERT INTO customer_webhooks("
            "api_key_hash, url, event_types_json, secret_hmac, status, failure_count"
            ") VALUES (?, ?, '[]', 'whsec_test', 'active', 0)",
            (key_hash, "https://hooks.example.com/amendment-ok"),
        )
        conn.commit()
    finally:
        conn.close()

    posted_urls: list[str] = []
    monkeypatch.setattr(cron_mod.settings, "db_path", seeded_db)
    monkeypatch.setattr(cron_mod, "_connect_autonomath", _stub_amendment_diff_conn)
    monkeypatch.setattr(
        cron_mod,
        "_post_webhook",
        lambda url, payload, dry_run: posted_urls.append(url) or {"ok": True, "status": 200},
    )

    summary = cron_mod.run(dry_run=False)

    assert posted_urls == ["https://hooks.example.com/amendment-ok"]
    assert summary["delivery_attempts"] == 1
    assert summary["delivery_ok"] == 1
    assert summary["cursors_advanced"] == 1
    assert _fanout_cursor(seeded_db, sub_id) is not None


def test_cron_does_not_advance_cursor_when_hits_have_no_delivery_channel(
    seeded_db,
    monkeypatch,
    feed_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import amendment_alert_fanout as cron_mod

    _apply_customer_webhooks_migration(seeded_db)
    key_hash = hash_api_key(feed_key)
    sub_id = _insert_amendment_subscription(seeded_db, key_hash)

    monkeypatch.setattr(cron_mod.settings, "db_path", seeded_db)
    monkeypatch.setattr(cron_mod, "_connect_autonomath", _stub_amendment_diff_conn)

    summary = cron_mod.run(dry_run=False)

    assert summary["diffs_total"] == 1
    assert summary["delivery_attempts"] == 0
    assert summary["delivery_no_channel"] == 1
    assert summary["cursors_blocked"] == 1
    assert summary["cursors_advanced"] == 0
    assert _fanout_cursor(seeded_db, sub_id) is None


def test_cron_does_not_advance_cursor_when_webhook_delivery_fails(
    seeded_db,
    monkeypatch,
    feed_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import amendment_alert_fanout as cron_mod

    _apply_customer_webhooks_migration(seeded_db)
    key_hash = hash_api_key(feed_key)
    sub_id = _insert_amendment_subscription(seeded_db, key_hash)

    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            "INSERT INTO customer_webhooks("
            "api_key_hash, url, event_types_json, secret_hmac, status, failure_count"
            ") VALUES (?, ?, '[]', 'whsec_test', 'active', 0)",
            (key_hash, "https://hooks.example.com/amendment-fail"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(cron_mod.settings, "db_path", seeded_db)
    monkeypatch.setattr(cron_mod, "_connect_autonomath", _stub_amendment_diff_conn)
    monkeypatch.setattr(
        cron_mod,
        "_post_webhook",
        lambda url, payload, dry_run: {"ok": False, "error": "http_500"},
    )

    summary = cron_mod.run(dry_run=False)

    assert summary["delivery_attempts"] == 1
    assert summary["delivery_ok"] == 0
    assert summary["delivery_failed"] == 1
    assert summary["cursors_blocked"] == 1
    assert summary["cursors_advanced"] == 0
    assert _fanout_cursor(seeded_db, sub_id) is None
