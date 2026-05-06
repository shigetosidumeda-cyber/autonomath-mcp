"""Smoke tests for /v1/me/courses CRUD (migration 099 — M5 email courses).

Covers the three endpoints wired by `src/jpintel_mcp/api/courses.py`:

    POST   /v1/me/courses                         subscribe to a course
    GET    /v1/me/courses                         list active subscriptions
    DELETE /v1/me/courses/{course_slug}           cancel an active subscription

Two pre-recorded courses exist in COURSE_CATALOG: 'invoice' (5d) /
'dencho' (7d). Each daily delivery is metered ¥3 — but the synchronous
D+1 fire on subscribe is mocked here via the bg_task_queue inline
runner (already wired in the conftest fixture).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - Fixture annotations use pytest runtime objects.

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def course_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_courses_test",
        tier="paid",
        stripe_subscription_id="sub_courses_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_course_subscriptions_table(seeded_db: Path):
    """Apply migration 099 onto the test DB so the router has its table.

    099 is a multi-statement migration covering saved_searches columns +
    course_subscriptions + sunset_calendar_subs. We pull the
    course_subscriptions create out (idempotent already) and apply only it
    so we don't collide with the saved_searches ALTER TABLE statements
    which are already covered by tests/test_saved_searches.py's fixture.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS course_subscriptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id      TEXT NOT NULL,
                email           TEXT NOT NULL,
                course_slug     TEXT NOT NULL CHECK (
                                    course_slug IN ('invoice','dencho')
                                ),
                started_at      TEXT NOT NULL DEFAULT (
                                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                                ),
                current_day     INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'active' CHECK (
                                    status IN ('active','complete','cancelled')
                                ),
                last_sent_at    TEXT,
                completed_at    TEXT,
                created_at      TEXT NOT NULL DEFAULT (
                                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                                ),
                UNIQUE(api_key_id, course_slug, started_at)
            );
            """
        )
        c.execute("DELETE FROM course_subscriptions")
        c.commit()
    finally:
        c.close()
    yield


def test_subscribe_creates_active_row(client, course_key):
    """POST creates an active course_subscription row + GET surfaces it."""
    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={
            "course_slug": "invoice",
            "notify_email": "test@example.com",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["course_slug"] == "invoice"
    assert body["status"] == "active"
    assert body["length_days"] == 5
    # Response-body PII redactor masks notify_email — assert it's a
    # string and either matches the input or is the redacted sentinel.
    assert isinstance(body["notify_email"], str)
    assert body["notify_email"] in ("test@example.com", "<email-redacted>")
    # current_day jumps to 1 if D+1 send succeeded; can stay 0 if email
    # transport is in test mode and skipped — both paths are valid.
    assert body["current_day"] in (0, 1)

    # GET lists the subscription
    r2 = client.get("/v1/me/courses", headers={"X-API-Key": course_key})
    assert r2.status_code == 200, r2.text
    rows = r2.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["course_slug"] == "invoice"
    assert rows[0]["status"] == "active"


def test_subscribe_unauth_is_401(client):
    """Anonymous POST → 401, not 200."""
    r = client.post(
        "/v1/me/courses",
        json={"course_slug": "invoice", "notify_email": "test@example.com"},
    )
    assert r.status_code == 401, r.text


def test_subscribe_unknown_course_is_422(client, course_key):
    """Bad course_slug → 422 from the Pydantic Literal validator."""
    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={"course_slug": "nonexistent", "notify_email": "test@example.com"},
    )
    assert r.status_code == 422, r.text


def test_subscribe_duplicate_is_409(client, course_key):
    """Same course twice → 409 (active subscription already exists)."""
    body = {"course_slug": "dencho", "notify_email": "dup@example.com"}
    r1 = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json=body,
    )
    assert r1.status_code == 201, r1.text

    r2 = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json=body,
    )
    assert r2.status_code == 409, r2.text


def test_subscribe_final_cap_failure_does_not_send_or_persist(
    client,
    course_key,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The immediate D+1 delivery must fail closed before email/sub state."""
    from jpintel_mcp.api import courses as courses_mod

    key_hash = hash_api_key(course_key)
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
            (3, key_hash),
        )
        conn.execute(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key_hash,
                "already.billed",
                datetime.now(UTC).isoformat(),
                200,
                1,
                1,
            ),
        )
        before_usage = conn.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'courses.delivery'",
            (key_hash,),
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    sends: list[dict] = []

    def _send_day_n_now(**kwargs):
        sends.append(kwargs)
        return {"MessageID": "should-not-send"}

    monkeypatch.setattr(courses_mod, "_send_day_n_now", _send_day_n_now)

    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={
            "course_slug": "invoice",
            "notify_email": "cap@example.com",
        },
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert sends == []

    conn = sqlite3.connect(seeded_db)
    try:
        course_count = conn.execute(
            "SELECT COUNT(*) FROM course_subscriptions "
            "WHERE api_key_id = ? AND course_slug = 'invoice'",
            (key_hash,),
        ).fetchone()[0]
        after_usage = conn.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'courses.delivery'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert course_count == 0
    assert after_usage == before_usage


def test_subscribe_unbillable_key_does_not_send_or_persist(
    client,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Non-metered keys cannot trigger the paid immediate course delivery."""
    from jpintel_mcp.api import courses as courses_mod

    conn = sqlite3.connect(seeded_db)
    try:
        free_key = issue_key(
            conn,
            customer_id="cus_courses_free",
            tier="free",
            stripe_subscription_id=None,
        )
        conn.commit()
    finally:
        conn.close()

    key_hash = hash_api_key(free_key)
    sends: list[dict] = []

    def _send_day_n_now(**kwargs):
        sends.append(kwargs)
        return {"MessageID": "should-not-send"}

    monkeypatch.setattr(courses_mod, "_send_day_n_now", _send_day_n_now)

    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": free_key},
        json={
            "course_slug": "invoice",
            "notify_email": "free@example.com",
        },
    )

    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "billing_required"
    assert sends == []

    conn = sqlite3.connect(seeded_db)
    try:
        course_count = conn.execute(
            "SELECT COUNT(*) FROM course_subscriptions WHERE api_key_id = ?",
            (key_hash,),
        ).fetchone()[0]
        usage_count = conn.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'courses.delivery'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert course_count == 0
    assert usage_count == 0


def test_subscribe_does_not_hold_writer_lock_while_sending(
    client,
    course_key,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The preflight BEGIN IMMEDIATE must be closed before external email I/O."""
    from jpintel_mcp.api import courses as courses_mod

    lock_probe_ok = False

    def _send_day_n_now(**kwargs):
        nonlocal lock_probe_ok
        probe = sqlite3.connect(seeded_db, timeout=0.05, isolation_level=None)
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.execute("COMMIT")
            lock_probe_ok = True
        finally:
            probe.close()
        return {"MessageID": "sent-without-held-writer-lock"}

    monkeypatch.setattr(courses_mod, "_send_day_n_now", _send_day_n_now)

    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={
            "course_slug": "invoice",
            "notify_email": "lock@example.com",
        },
    )

    assert r.status_code == 201, r.text
    assert lock_probe_ok is True


def test_subscribe_charge_failure_before_send_does_not_email(
    client,
    course_key,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """DEEP-46 Pattern A — charge fails BEFORE send → no email, no advance.

    Replaces the legacy "charge fails AFTER send" path; under Pattern A the
    charge happens pre-send so a billing failure must short-circuit the
    flow before any external email goes out. The subscription row remains
    at current_day=0 so the cron retries cleanly on the next sweep.
    """
    from jpintel_mcp.api import courses as courses_mod

    sends: list[dict] = []

    def _send_day_n_now(**kwargs):
        sends.append(kwargs)
        return {"MessageID": f"sent-{len(sends)}"}

    def _record_metered_delivery(**kwargs):
        raise sqlite3.OperationalError("simulated usage_events write failure")

    monkeypatch.setattr(courses_mod, "_send_day_n_now", _send_day_n_now)
    monkeypatch.setattr(courses_mod, "_record_metered_delivery", _record_metered_delivery)

    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={
            "course_slug": "invoice",
            "notify_email": "audit-fail@example.com",
        },
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    # Pattern A — email never went out because charge failed first.
    assert len(sends) == 0

    key_hash = hash_api_key(course_key)
    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT current_day, last_sent_at FROM course_subscriptions "
            "WHERE api_key_id = ? AND course_slug = 'invoice' AND status = 'active'",
            (key_hash,),
        ).fetchone()
        usage_count = conn.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'courses.delivery'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    # Subscription row exists (insert succeeded) but stays at day 0 +
    # no last_sent_at because the email was never attempted.
    assert row is not None
    assert row[0] == 0
    assert row[1] is None
    assert usage_count == 0


def test_cancel_flips_status(client, course_key):
    """DELETE sets status='cancelled'; GET no longer lists active rows."""
    r = client.post(
        "/v1/me/courses",
        headers={"X-API-Key": course_key},
        json={"course_slug": "invoice", "notify_email": "cancel@example.com"},
    )
    assert r.status_code == 201, r.text

    r_del = client.delete(
        "/v1/me/courses/invoice",
        headers={"X-API-Key": course_key},
    )
    assert r_del.status_code == 200, r_del.text
    assert r_del.json() == {"ok": True, "course_slug": "invoice"}

    # Re-cancel → 404 (no active row)
    r_again = client.delete(
        "/v1/me/courses/invoice",
        headers={"X-API-Key": course_key},
    )
    assert r_again.status_code == 404, r_again.text
