"""Tests for /v1/me/alerts and the amendment_alert cron (P5-ι++).

Coverage:
  * POST /v1/me/alerts/subscribe — auth, validation, webhook URL safety
  * GET  /v1/me/alerts/subscriptions — only-mine + only-active
  * DELETE /v1/me/alerts/subscriptions/{id} — soft-delete + 404
  * scripts/cron/amendment_alert.run — dry-run path with seeded amendments
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
def alert_key(seeded_db: Path) -> str:
    """Authenticated paid key for alert tests."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_alert_test",
        tier="paid",
        stripe_subscription_id="sub_alert_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_alert_subscriptions_table(seeded_db: Path):
    """Apply migration 038 onto the test DB and clear rows between cases.

    schema.sql does not declare alert_subscriptions yet — the table only
    lives in scripts/migrations/038_alert_subscriptions.sql. We apply that
    migration on demand so tests don't depend on the migration runner.
    """
    repo = Path(__file__).resolve().parent.parent
    sql_path = repo / "scripts" / "migrations" / "038_alert_subscriptions.sql"
    sql = sql_path.read_text(encoding="utf-8")

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.execute("DELETE FROM alert_subscriptions")
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_subscribe_requires_auth(client):
    r = client.post(
        "/v1/me/alerts/subscribe",
        json={
            "filter_type": "all",
            "min_severity": "important",
            "email": "ops@example.com",
        },
    )
    assert r.status_code == 401


def test_subscribe_requires_channel(client, alert_key):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={"filter_type": "all", "min_severity": "important"},
    )
    assert r.status_code == 400
    assert "webhook_url" in r.json()["detail"] or "email" in r.json()["detail"]


def test_subscribe_filter_value_required_when_not_all(client, alert_key):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "law_id",
            "min_severity": "important",
            "email": "x@example.com",
        },
    )
    assert r.status_code == 400
    assert "filter_value" in r.json()["detail"]


def test_subscribe_rejects_http_webhook(client, alert_key):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "all",
            "min_severity": "important",
            "webhook_url": "http://example.com/hook",
        },
    )
    assert r.status_code == 400
    assert "https" in r.json()["detail"].lower()


def test_subscribe_rejects_internal_ip_webhook(client, alert_key):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "all",
            "min_severity": "important",
            "webhook_url": "https://10.0.0.5/hook",
        },
    )
    assert r.status_code == 400
    assert "private" in r.json()["detail"].lower() or "internal" in r.json()["detail"].lower()


def test_subscribe_rejects_loopback_webhook(client, alert_key):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "all",
            "min_severity": "important",
            "webhook_url": "https://127.0.0.1:8080/hook",
        },
    )
    assert r.status_code == 400


def test_subscribe_happy_path(client, alert_key, seeded_db):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "law_id",
            "filter_value": "law_345AC0000000050",
            "min_severity": "critical",
            "webhook_url": "https://hooks.example.com/alerts",
            "email": "ops@example.com",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["filter_type"] == "law_id"
    assert body["filter_value"] == "law_345AC0000000050"
    assert body["min_severity"] == "critical"
    assert body["webhook_url"] == "https://hooks.example.com/alerts"
    assert body["email"] == "ops@example.com"
    assert body["active"] is True
    assert body["last_triggered"] is None

    # Persisted with correct api_key_hash.
    from jpintel_mcp.api.deps import hash_api_key

    expected_hash = hash_api_key(alert_key)
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT api_key_hash, filter_type FROM alert_subscriptions WHERE id = ?",
            (body["id"],),
        ).fetchone()
        assert row["api_key_hash"] == expected_hash
        assert row["filter_type"] == "law_id"
    finally:
        c.close()


def test_subscribe_normalises_filter_value_to_null_when_all(client, alert_key, seeded_db):
    r = client.post(
        "/v1/me/alerts/subscribe",
        headers={"X-API-Key": alert_key},
        json={
            "filter_type": "all",
            "filter_value": "ignored",  # should be discarded server-side
            "min_severity": "info",
            "email": "ops@example.com",
        },
    )
    assert r.status_code == 201
    sub_id = r.json()["id"]

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT filter_value FROM alert_subscriptions WHERE id = ?",
            (sub_id,),
        ).fetchone()
        assert row[0] is None
    finally:
        c.close()


def test_list_only_mine_and_active(client, alert_key, seeded_db):
    headers = {"X-API-Key": alert_key}
    # 2 active for our key.
    r1 = client.post(
        "/v1/me/alerts/subscribe",
        headers=headers,
        json={"filter_type": "all", "email": "a@example.com"},
    )
    r2 = client.post(
        "/v1/me/alerts/subscribe",
        headers=headers,
        json={
            "filter_type": "tool",
            "filter_value": "search_tax_incentives",
            "email": "b@example.com",
        },
    )
    assert r1.status_code == r2.status_code == 201

    # Insert a foreign-key sub directly.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO alert_subscriptions("
            "api_key_hash, filter_type, min_severity, email, active, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                "not_my_hash",
                "all",
                "important",
                "x@example.com",
                1,
                "2026-04-24T00:00:00+00:00",
                "2026-04-24T00:00:00+00:00",
            ),
        )
        # Insert an inactive (deactivated) sub for our key.
        from jpintel_mcp.api.deps import hash_api_key

        c.execute(
            "INSERT INTO alert_subscriptions("
            "api_key_hash, filter_type, min_severity, email, active, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                hash_api_key(alert_key),
                "all",
                "important",
                "old@example.com",
                0,
                "2026-04-24T00:00:00+00:00",
                "2026-04-24T00:00:00+00:00",
            ),
        )
        c.commit()
    finally:
        c.close()

    r = client.get("/v1/me/alerts/subscriptions", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    emails = {row["email"] for row in rows}
    assert emails == {"a@example.com", "b@example.com"}


def test_delete_deactivates_and_404s(client, alert_key, seeded_db):
    headers = {"X-API-Key": alert_key}
    create = client.post(
        "/v1/me/alerts/subscribe",
        headers=headers,
        json={"filter_type": "all", "email": "x@example.com"},
    )
    assert create.status_code == 201
    sub_id = create.json()["id"]

    d = client.delete(f"/v1/me/alerts/subscriptions/{sub_id}", headers=headers)
    assert d.status_code == 200
    assert d.json() == {"ok": True, "id": sub_id}

    # row remains, but active=0
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT active FROM alert_subscriptions WHERE id = ?",
            (sub_id,),
        ).fetchone()
        assert row[0] == 0
    finally:
        c.close()

    # second DELETE -> 404 (already inactive)
    d2 = client.delete(f"/v1/me/alerts/subscriptions/{sub_id}", headers=headers)
    assert d2.status_code == 404


def test_delete_other_keys_sub_404s(client, alert_key, seeded_db):
    """Deleting another key's subscription must look like a 404, not 403."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        c.execute(
            "INSERT INTO alert_subscriptions("
            "api_key_hash, filter_type, min_severity, email, active, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                "foreign_hash",
                "all",
                "important",
                "x@example.com",
                1,
                "2026-04-24T00:00:00+00:00",
                "2026-04-24T00:00:00+00:00",
            ),
        )
        c.commit()
        foreign_id = c.execute(
            "SELECT id FROM alert_subscriptions WHERE api_key_hash = 'foreign_hash'"
        ).fetchone()["id"]
    finally:
        c.close()

    headers = {"X-API-Key": alert_key}
    r = client.delete(f"/v1/me/alerts/subscriptions/{foreign_id}", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cron tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def amendment_db(tmp_path: Path) -> Path:
    """Build a tiny autonomath.db stand-in with the columns the cron needs."""
    p = tmp_path / "autonomath.db"
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind  TEXT NOT NULL,
            primary_name TEXT NOT NULL,
            raw_json     TEXT NOT NULL
        );
        CREATE TABLE am_amendment_snapshot (
            snapshot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id          TEXT NOT NULL,
            version_seq        INTEGER NOT NULL,
            observed_at        TEXT NOT NULL,
            effective_from     TEXT,
            effective_until    TEXT,
            amount_max_yen     INTEGER,
            subsidy_rate_max   REAL,
            target_set_json    TEXT,
            eligibility_hash   TEXT,
            summary_hash       TEXT,
            source_url         TEXT,
            source_fetched_at  TEXT,
            raw_snapshot_json  TEXT,
            UNIQUE (entity_id, version_seq)
        );
        """
    )
    # Entity referenced by the snapshots.
    c.execute(
        "INSERT INTO am_entities VALUES (?,?,?,?)",
        (
            "program:test:001",
            "program",
            "テスト補助金",
            json.dumps({"law_id": "law_345AC0000000050"}, ensure_ascii=False),
        ),
    )
    # Two versions: v2 sets effective_until -> critical
    c.execute(
        "INSERT INTO am_amendment_snapshot("
        "entity_id, version_seq, observed_at, amount_max_yen, "
        "eligibility_hash) VALUES (?,?,?,?,?)",
        ("program:test:001", 1, "2026-04-20T00:00:00+00:00", 1000000, "h1"),
    )
    c.execute(
        "INSERT INTO am_amendment_snapshot("
        "entity_id, version_seq, observed_at, effective_until, "
        "amount_max_yen, eligibility_hash) VALUES (?,?,?,?,?,?)",
        ("program:test:001", 2, "2026-04-25T00:00:00+00:00", "2026-12-31", 1000000, "h1"),
    )
    c.commit()
    c.close()
    return p


def test_cron_dry_run_with_subscription(seeded_db: Path, amendment_db: Path, alert_key: str):
    """End-to-end dry-run: subscription exists, amendment matches, cron runs."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron.amendment_alert import run as cron_run

    key_hash = hash_api_key(alert_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO alert_subscriptions("
            "api_key_hash, filter_type, filter_value, min_severity, "
            "webhook_url, email, active, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                key_hash,
                "law_id",
                "law_345AC0000000050",
                "critical",
                "https://hooks.example.com/x",
                "ops@example.com",
                1,
                "2026-04-20T00:00:00+00:00",
                "2026-04-20T00:00:00+00:00",
            ),
        )
        c.commit()
    finally:
        c.close()

    summary = cron_run(
        since_iso="2026-04-19T00:00:00+00:00",
        dry_run=True,
        autonomath_db=amendment_db,
        jpintel_db=seeded_db,
    )
    assert summary["amendments_scanned"] >= 2
    assert summary["subscriptions_active"] == 1
    # v2 snapshot has effective_until newly set -> critical -> matches sub
    assert summary["subscriptions_fired"] == 1
    assert summary["dry_run"] is True


def test_cron_skips_when_severity_below_min(seeded_db: Path, amendment_db: Path, alert_key: str):
    """A 'critical' min_severity filter should NOT match an info amendment."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron.amendment_alert import run as cron_run

    key_hash = hash_api_key(alert_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO alert_subscriptions("
            "api_key_hash, filter_type, filter_value, min_severity, "
            "email, active, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                key_hash,
                "law_id",
                "nonexistent_law_id",
                "critical",
                "ops@example.com",
                1,
                "2026-04-20T00:00:00+00:00",
                "2026-04-20T00:00:00+00:00",
            ),
        )
        c.commit()
    finally:
        c.close()

    summary = cron_run(
        since_iso="2026-04-19T00:00:00+00:00",
        dry_run=True,
        autonomath_db=amendment_db,
        jpintel_db=seeded_db,
    )
    # filter doesn't match -> no fire
    assert summary["subscriptions_fired"] == 0


def test_cron_handles_missing_autonomath_db(seeded_db: Path, tmp_path: Path):
    """A missing autonomath.db must short-circuit, not crash."""
    from scripts.cron.amendment_alert import run as cron_run

    summary = cron_run(
        since_iso="2026-04-19T00:00:00+00:00",
        dry_run=True,
        autonomath_db=tmp_path / "does_not_exist.db",
        jpintel_db=seeded_db,
    )
    assert summary.get("skipped") is True
    assert summary.get("reason") == "autonomath_db_missing"
