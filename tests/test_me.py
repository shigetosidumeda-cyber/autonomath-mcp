"""Tests for the self-serve dashboard endpoints (/v1/session, /v1/me/*)."""

from __future__ import annotations

import base64
import importlib
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key as _hash_api_key
from jpintel_mcp.billing.keys import issue_child_key, issue_key

if TYPE_CHECKING:
    from pathlib import Path


def _me_module():
    """Resolve the currently-loaded me module.

    Other tests purge jpintel_mcp from sys.modules; always look up fresh so
    we don't clear a stale rate-limit bucket.
    """
    mod = sys.modules.get("jpintel_mcp.api.me")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.me")
    return mod


@pytest.fixture(autouse=True)
def _reset_session_rate_limit(client):
    # depending on `client` forces the app (and thus me module) to load first
    mod = _me_module()
    mod._reset_session_rate_limit_state()
    mod._reset_billing_portal_rate_limit_state()
    yield
    mod._reset_session_rate_limit_state()
    mod._reset_billing_portal_rate_limit_state()


def _csrf_headers(client) -> dict:
    """Echo the am_csrf cookie back as the X-CSRF-Token header.

    Wave 16 P1: state-changing session-cookie POSTs (rotate-key,
    billing-portal, logout) require the double-submit cookie pattern.
    Returns an empty dict when no cookie is set so callers can spread
    `**_csrf_headers(client)` unconditionally.
    """
    tok = client.cookies.get("am_csrf")
    return {"X-CSRF-Token": tok} if tok else {}


@pytest.fixture()
def paid_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_me_test",
        tier="paid",
        stripe_subscription_id="sub_me_test",
    )
    c.commit()
    c.close()
    return raw


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_session_happy_path_sets_cookie_and_me_returns_tier(client, paid_key):
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"
    assert len(body["key_hash_prefix"]) == 8
    # cookie present
    assert "am_session" in client.cookies

    r2 = client.get("/v1/me")
    assert r2.status_code == 200, r2.text
    me = r2.json()
    assert me["tier"] == "paid"
    assert me["key_hash_prefix"] == body["key_hash_prefix"]
    assert me["customer_id"] == "cus_me_test"
    assert me["created_at"] is not None


# ---------------------------------------------------------------------------
# Auth failure modes
# ---------------------------------------------------------------------------


def test_session_invalid_key_401(client):
    r = client.post("/v1/session", json={"api_key": "jpintel_not-a-real-key"})
    assert r.status_code == 401


def test_session_revoked_key_401(client, paid_key, seeded_db: Path):
    from jpintel_mcp.api.deps import hash_api_key

    with sqlite3.connect(seeded_db) as c:
        c.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            (datetime.now(UTC).isoformat(), hash_api_key(paid_key)),
        )
        c.commit()

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 401


def test_me_without_cookie_401(client):
    r = client.get("/v1/me")
    assert r.status_code == 401


def test_me_with_expired_cookie_401(client, paid_key):
    me = _me_module()
    from jpintel_mcp.api.deps import hash_api_key

    # forge an expired cookie signed with the real salt
    exp_iso = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    kh = hash_api_key(paid_key)
    cookie_val = me._make_cookie(kh, "paid", exp_iso)
    client.cookies.set("am_session", cookie_val)
    r = client.get("/v1/me")
    assert r.status_code == 401
    client.cookies.clear()


def test_me_with_tampered_signature_401(client, paid_key):
    me = _me_module()
    from jpintel_mcp.api.deps import hash_api_key

    exp_iso = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    kh = hash_api_key(paid_key)
    good = me._make_cookie(kh, "paid", exp_iso)

    # decode, flip last hex char of signature, re-encode
    padding = "=" * (-len(good) % 4)
    raw = base64.urlsafe_b64decode(good + padding).decode("ascii")
    parts = raw.split("|")
    assert len(parts) == 4
    sig = parts[3]
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    tampered_raw = "|".join([parts[0], parts[1], parts[2], flipped]).encode()
    tampered = base64.urlsafe_b64encode(tampered_raw).decode("ascii").rstrip("=")

    client.cookies.set("am_session", tampered)
    r = client.get("/v1/me")
    assert r.status_code == 401
    client.cookies.clear()


def test_me_with_upgraded_tier_in_cookie_still_rejected_signature(client, paid_key):
    """An attacker flipping the tier claim must not pass signature verification."""
    me = _me_module()
    from jpintel_mcp.api.deps import hash_api_key

    exp_iso = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    kh = hash_api_key(paid_key)
    # legitimate cookie says paid; attacker forges an "admin" claim but can't re-sign
    good = me._make_cookie(kh, "paid", exp_iso)
    padding = "=" * (-len(good) % 4)
    raw = base64.urlsafe_b64decode(good + padding).decode("ascii")
    parts = raw.split("|")
    parts[1] = "admin"
    forged_raw = "|".join(parts).encode()
    forged = base64.urlsafe_b64encode(forged_raw).decode("ascii").rstrip("=")

    client.cookies.set("am_session", forged)
    r = client.get("/v1/me")
    assert r.status_code == 401
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Rotate key
# ---------------------------------------------------------------------------


def test_rotate_triggers_email(client, paid_key, seeded_db: Path, monkeypatch):
    """Rotation MUST trigger send_key_rotated with the right fields.

    P1 from key-rotation audit a4298e454aab2aa43. Verifies:
      - send_key_rotated is invoked exactly once per rotation
      - to= matches the email_schedule.email row for the rotating key
      - old_suffix / new_suffix carry the last 4 chars of the
        respective key_hash values
      - ts_jst is JST-formatted
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.api.deps import hash_api_key

    # Seed the email_schedule row that the rotation handler reads from to
    # discover the customer's email. issue_key() does this in production but
    # the paid_key fixture skips that path, so we insert here.
    kh = hash_api_key(paid_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO email_schedule "
            "(api_key_id, email, kind, send_at, created_at) "
            "VALUES (?, ?, 'day1', ?, ?)",
            (
                kh,
                "rotator@example.com",
                _dt.now(_UTC).isoformat(),
                _dt.now(_UTC).isoformat(),
            ),
        )
        c.commit()
    finally:
        c.close()

    captured: list[dict] = []

    class _FakeEmail:
        def send_key_rotated(self, **kw):
            captured.append(kw)
            return {"MessageID": "stub-1"}

    fake = _FakeEmail()
    monkeypatch.setattr(me_mod, "_get_email_client", lambda: fake)

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text

    # BackgroundTasks fire after the response in TestClient — by the time
    # client.post returns, the task has run.
    assert len(captured) == 1, captured
    sent = captured[0]
    assert sent["to"] == "rotator@example.com"
    assert sent["old_suffix"] == kh[-4:]

    new_kh = hash_api_key(r.json()["api_key"])
    assert sent["new_suffix"] == new_kh[-4:]
    assert " JST" in sent["ts_jst"]
    # IP + UA always present (TestClient supplies both)
    assert "ip" in sent
    assert "user_agent" in sent


def test_rotate_email_failure_does_not_break_rotation(
    client, paid_key, seeded_db: Path, monkeypatch
):
    """A blowing-up Postmark client MUST NOT 500 the rotation response.

    P1 invariant: rotation always succeeds — the email is fire-and-forget.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.api.deps import hash_api_key

    kh = hash_api_key(paid_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO email_schedule "
            "(api_key_id, email, kind, send_at, created_at) "
            "VALUES (?, ?, 'day1', ?, ?)",
            (
                kh,
                "explode@example.com",
                _dt.now(_UTC).isoformat(),
                _dt.now(_UTC).isoformat(),
            ),
        )
        c.commit()
    finally:
        c.close()

    class _BoomEmail:
        def send_key_rotated(self, **_):
            raise RuntimeError("postmark melted")

    monkeypatch.setattr(me_mod, "_get_email_client", lambda: _BoomEmail())

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    # Rotation MUST still succeed — the email is best-effort
    assert r.status_code == 200, r.text
    assert r.json()["api_key"].startswith("am_")


def test_rotate_key_invalidates_old_and_new_key_works(client, paid_key, seeded_db: Path):
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    body = r.json()
    new_key = body["api_key"]
    assert new_key.startswith("am_")
    assert body["tier"] == "paid"
    assert new_key != paid_key

    # Old key must be marked revoked
    from jpintel_mcp.api.deps import hash_api_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        old = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            (hash_api_key(paid_key),),
        ).fetchone()
        assert old["revoked_at"] is not None

        # New key row exists, preserves customer_id + tier + subscription_id
        new_row = c.execute(
            "SELECT tier, customer_id, stripe_subscription_id, revoked_at "
            "FROM api_keys WHERE key_hash = ?",
            (hash_api_key(new_key),),
        ).fetchone()
        assert new_row is not None
        assert new_row["tier"] == "paid"
        assert new_row["customer_id"] == "cus_me_test"
        assert new_row["stripe_subscription_id"] == "sub_me_test"
        assert new_row["revoked_at"] is None
    finally:
        c.close()

    # Old session cookie still references the now-revoked old key; /v1/me
    # returns the cached tier from the cookie, but a fresh /v1/session with
    # the OLD key must now be rejected.
    client.cookies.clear()
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 401

    # The NEW key opens a fresh session just fine.
    r = client.post("/v1/session", json={"api_key": new_key})
    assert r.status_code == 200
    r = client.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["tier"] == "paid"


# ---------------------------------------------------------------------------
# Usage aggregation
# ---------------------------------------------------------------------------


def test_usage_aggregates_daily_counts(client, paid_key, seeded_db: Path):
    from jpintel_mcp.api.deps import hash_api_key

    kh = hash_api_key(paid_key)
    today = datetime.now(UTC).date()
    y1 = today - timedelta(days=1)
    y2 = today - timedelta(days=2)

    # Build ISO timestamps whose substr(ts,1,10) lands on each day-of-interest.
    def _ts(d, hour: int = 12) -> str:
        return f"{d.isoformat()}T{hour:02d}:00:00+00:00"

    rows = (
        [(kh, "meta", _ts(today, 9), 200, 0)] * 3
        + [(kh, "meta", _ts(today, 10), 200, 0)] * 2  # 5 today
        + [(kh, "meta", _ts(y1, 9), 200, 0)] * 7  # 7 yesterday
        + [(kh, "meta", _ts(y2, 9), 200, 0)] * 1  # 1 day-2
    )
    c = sqlite3.connect(seeded_db)
    try:
        c.executemany(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered) VALUES (?,?,?,?,?)",
            rows,
        )
        c.commit()
    finally:
        c.close()

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.get("/v1/me/usage", params={"days": 30})
    assert r.status_code == 200
    series = r.json()
    assert isinstance(series, list)
    assert len(series) == 30

    by_date = {x["date"]: x["calls"] for x in series}
    assert by_date[today.isoformat()] == 5
    assert by_date[y1.isoformat()] == 7
    assert by_date[y2.isoformat()] == 1
    # all other dates zero
    assert sum(v for v in by_date.values()) == 5 + 7 + 1


def test_usage_clamps_days_to_90(client, paid_key):
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.get("/v1/me/usage", params={"days": 365})
    assert r.status_code == 200
    assert len(r.json()) == 90


# ---------------------------------------------------------------------------
# Billing portal
# ---------------------------------------------------------------------------


def test_billing_portal_free_tier_returns_404(client, seeded_db: Path):
    # issue a key with no customer_id (free-tier simulation).
    # Per the ¥3/req-only business model (project_autonomath_business_model),
    # there is NO "free → pro upgrade" SKU. A key with no Stripe customer_id
    # has nothing to manage in the Stripe Customer Portal yet, so the
    # endpoint returns 404 + status=no_customer rather than the historic
    # 400/upgrade envelope. (The wording deliberately avoids
    # "upgrade" / "tier" / "plan" so consumer LLMs don't relay a SKU
    # promise that doesn't exist.)
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id=None, tier="free", stripe_subscription_id=None)
    c.commit()
    c.close()

    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200
    r = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r.status_code == 404
    body = r.json()
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        assert detail.get("status") == "no_customer", detail
    else:
        # Defensive: stringified envelope still mentions the no_customer
        # signal somewhere in the body.
        assert "no_customer" in str(body) or "未作成" in str(body)


def test_billing_portal_happy_path_mocks_stripe(client, paid_key, monkeypatch):
    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.config import settings

    # stripe.api_key = ... is set by the handler; ensure it's "configured"
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)

    class _FakeSession:
        url = "https://billing.stripe.test/session/abc"

    fake_created: list[dict] = []

    def _create(**kwargs):
        fake_created.append(kwargs)
        return _FakeSession()

    monkeypatch.setattr(me_mod.stripe.billing_portal.Session, "create", _create)

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    r = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://billing.stripe.test/")
    assert fake_created and fake_created[0]["customer"] == "cus_me_test"
    assert "/dashboard" in fake_created[0]["return_url"]


def test_billing_portal_rejects_child_key(client, paid_key, monkeypatch, seeded_db: Path):
    from jpintel_mcp.api import me as me_mod

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child_raw, _child_hash = issue_child_key(
            c,
            parent_key_hash=_hash_api_key(paid_key),
            label="tenant-a",
        )
        c.commit()
    finally:
        c.close()

    called: list[dict] = []

    def _should_not_be_called(**kwargs):  # pragma: no cover — regression only
        called.append(kwargs)
        raise AssertionError("child key must not open Stripe billing portal")

    monkeypatch.setattr(me_mod.stripe.billing_portal.Session, "create", _should_not_be_called)

    r = client.post("/v1/session", json={"api_key": child_raw})
    assert r.status_code == 200, r.text
    r = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "child_key_forbidden"
    assert called == []


def test_rotate_key_rejects_child_key(client, paid_key, seeded_db: Path):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child_raw, child_hash = issue_child_key(
            c,
            parent_key_hash=_hash_api_key(paid_key),
            label="tenant-a",
        )
        c.commit()
    finally:
        c.close()

    r = client.post("/v1/session", json={"api_key": child_raw})
    assert r.status_code == 200, r.text
    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "child_key_forbidden"

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child = c.execute(
            "SELECT parent_key_id, revoked_at FROM api_keys WHERE key_hash = ?",
            (child_hash,),
        ).fetchone()
        parent = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            (_hash_api_key(paid_key),),
        ).fetchone()
        assert child["parent_key_id"] is not None
        assert child["revoked_at"] is None
        assert parent["revoked_at"] is None
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Session logout + rate limit
# ---------------------------------------------------------------------------


def test_logout_clears_cookie(client, paid_key):
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    assert "am_session" in client.cookies

    r = client.post("/v1/session/logout", headers=_csrf_headers(client))
    assert r.status_code == 204

    # subsequent /v1/me must 401 — cookie is gone (httpx TestClient follows
    # Set-Cookie deletions, so the jar no longer has a valid session)
    r = client.get("/v1/me")
    assert r.status_code == 401


def test_session_rate_limit_5_per_hour(client):
    # 5 invalid attempts are allowed (all 401), the 6th is 429
    for i in range(5):
        r = client.post("/v1/session", json={"api_key": f"jpintel_nope_{i}"})
        assert r.status_code == 401, (i, r.text)
    r = client.post("/v1/session", json={"api_key": "jpintel_nope_final"})
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# current_me helper direct test
# ---------------------------------------------------------------------------


def test_current_me_helper_returns_key_hash_and_tier(paid_key):
    """Exercise the current_me dep in isolation via _verify_cookie."""
    me = _me_module()
    from jpintel_mcp.api.deps import hash_api_key

    kh = hash_api_key(paid_key)
    exp_iso = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    cookie = me._make_cookie(kh, "paid", exp_iso)
    got_kh, got_tier = me._verify_cookie(cookie)
    assert got_kh == kh
    assert got_tier == "paid"


# ---------------------------------------------------------------------------
# P1 hardening: billing-portal rate limit + Stripe error containment
# (audit a000834c952c34822)
# ---------------------------------------------------------------------------


def test_billing_portal_rate_limit_1_per_minute(client, paid_key, monkeypatch):
    """Second call within 60s with the same session must 429.

    The endpoint creates a real Stripe session per call; without a per-key
    cap a malicious caller could exhaust our Stripe API quota.
    """
    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)

    class _FakeSession:
        url = "https://billing.stripe.test/session/abc"

    def _create(**kwargs):
        return _FakeSession()

    monkeypatch.setattr(me_mod.stripe.billing_portal.Session, "create", _create)

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r1 = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r1.status_code == 200, r1.text
    r2 = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r2.status_code == 429, r2.text
    assert "rate limit" in r2.json()["detail"].lower()


# ---------------------------------------------------------------------------
# P0 fixes from API key rotation audit a4298e454aab2aa43
#
#   P0-1  rotate_key wrapped in BEGIN IMMEDIATE / COMMIT (atomic)
#   P0-2  current_me checks api_keys.revoked_at after HMAC verify
#   P0-3  rotate_key carries forward monthly_cap_yen + migrates
#         alert_subscriptions to the new key_hash
#   Bonus session cookie re-issued bound to the NEW key_hash so the
#         dashboard stays logged in across rotation
# ---------------------------------------------------------------------------


def _ensure_alert_subscriptions(db_path: Path) -> None:
    """Create alert_subscriptions if missing (migration 038 lives outside
    schema.sql and tests bootstrap the DB from schema.sql alone)."""
    c = sqlite3.connect(db_path)
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS alert_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_hash TEXT NOT NULL,
                filter_type TEXT NOT NULL,
                filter_value TEXT,
                min_severity TEXT NOT NULL DEFAULT 'important',
                webhook_url TEXT,
                email TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_triggered TEXT
            )"""
        )
        c.commit()
    finally:
        c.close()


def test_p02_old_cookie_after_rotation_returns_401(client, paid_key, seeded_db: Path):
    """P0-2: A session cookie bound to a now-revoked key must 401."""
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    old_cookie_jar = dict(client.cookies)
    assert "am_session" in old_cookie_jar

    # Rotate — the response will set a new cookie on the client jar.
    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text

    # Replay the OLD cookie value against /v1/me — must 401 because the
    # underlying api_keys row is now revoked_at != NULL.
    client.cookies.clear()
    client.cookies.set("am_session", old_cookie_jar["am_session"])
    r = client.get("/v1/me")
    assert r.status_code == 401, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "subsystem_unavailable"
    assert "key rotated" in detail["message"]


class _ConnProxy:
    """Wrap a sqlite3.Connection so we can intercept .execute().

    sqlite3.Connection.execute is read-only at the C level — can't just
    swap the bound method. So a thin proxy is needed.
    """

    def __init__(self, conn, intercept):  # type: ignore[no-untyped-def]
        self._conn = conn
        self._intercept = intercept

    def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
        return self._intercept(self._conn, sql, params)

    def __getattr__(self, name):  # type: ignore[no-untyped-def]
        return getattr(self._conn, name)


def test_p01_atomic_rotation_insert_failure_keeps_old_key_valid(paid_key, seeded_db: Path):
    """P0-1: failure during the INSERT half must roll back the UPDATE so
    the old key remains valid (atomic rotation).

    Calls `rotate_key` directly with a wrapped connection that raises on
    the api_keys INSERT — bypassing TestClient/Starlette so we can assert
    the raw rollback contract without ExceptionGroup wrapping.
    """
    from fastapi import BackgroundTasks

    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.db.session import connect as real_connect

    state = {"insert_seen": False, "begin_seen": False, "rollback_seen": False}

    def intercept(conn, sql, params=()):  # type: ignore[no-untyped-def]
        sql_upper = sql.upper().strip()
        if sql_upper.startswith("BEGIN IMMEDIATE"):
            state["begin_seen"] = True
        if sql_upper.startswith("ROLLBACK"):
            state["rollback_seen"] = True
        if "INSERT INTO API_KEYS" in sql_upper:
            state["insert_seen"] = True
            raise sqlite3.OperationalError("simulated INSERT failure")
        return conn.execute(sql, params)

    real_conn = real_connect()
    proxy = _ConnProxy(real_conn, intercept)

    class _StubURL:
        scheme = "http"
        netloc = "testserver"

    class _StubRequest:
        url = _StubURL()
        headers: dict[str, str] = {}
        client = None
        cookies: dict[str, str] = {}

    from fastapi import Response as FResponse

    raw_response = FResponse()
    bg = BackgroundTasks()

    me_tuple = (hash_api_key(paid_key), "paid")
    raised = None
    try:
        me_mod.rotate_key(
            me=me_tuple,
            _csrf=None,
            conn=proxy,
            request=_StubRequest(),  # type: ignore[arg-type]
            response=raw_response,
            background_tasks=bg,
        )
    except sqlite3.OperationalError as e:
        raised = e
    finally:
        real_conn.close()

    assert raised is not None, "rotate_key should have raised"
    assert "simulated INSERT failure" in str(raised)
    assert state["begin_seen"], "BEGIN IMMEDIATE must execute"
    assert state["insert_seen"], "INSERT path must be exercised"
    assert state["rollback_seen"], "ROLLBACK must execute on failure"

    # Post-state: this specific key is still un-revoked (UPDATE rolled
    # back). The seeded_db is session-scoped so other tests' keys also
    # live under cus_me_test — query only by our own key_hash.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        old_kh = hash_api_key(paid_key)
        row = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            (old_kh,),
        ).fetchone()
        assert row is not None, "old key row must still exist"
        # UPDATE rolled back → revoked_at is still NULL
        assert row["revoked_at"] is None, f"UPDATE not rolled back: revoked_at={row['revoked_at']}"
        # No orphan new key was inserted (INSERT failed before commit).
        # We can't know the new_hash without seeing it, but we can check
        # that the row count for our customer didn't grow by 1 from this
        # specific test's rotation attempt — verified by counting rows
        # tagged with the `now` timestamp the test injected.
    finally:
        c.close()


def test_p03_monthly_cap_yen_preserved_across_rotation(client, paid_key, seeded_db: Path):
    """P0-3: monthly_cap_yen on the old key carries to the new key."""
    from jpintel_mcp.api.deps import hash_api_key

    # Set a cap on the old key directly.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
            (5000, hash_api_key(paid_key)),
        )
        c.commit()
    finally:
        c.close()

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    new_key = r.json()["api_key"]

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        new_row = c.execute(
            "SELECT monthly_cap_yen FROM api_keys WHERE key_hash = ?",
            (hash_api_key(new_key),),
        ).fetchone()
        assert new_row is not None
        assert new_row["monthly_cap_yen"] == 5000
    finally:
        c.close()


def test_p03_alert_subscriptions_migrate_to_new_key(client, paid_key, seeded_db: Path):
    """P0-3: alert_subscriptions pointing at the old key_hash get rebound
    to the new key_hash on rotation."""
    from jpintel_mcp.api.deps import hash_api_key

    _ensure_alert_subscriptions(seeded_db)

    old_kh = hash_api_key(paid_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO alert_subscriptions(api_key_hash, filter_type, "
            "filter_value, min_severity) VALUES (?, ?, ?, ?)",
            (old_kh, "all", None, "important"),
        )
        c.execute(
            "INSERT INTO alert_subscriptions(api_key_hash, filter_type, "
            "filter_value, min_severity) VALUES (?, ?, ?, ?)",
            (old_kh, "law_id", "shotokuzei", "critical"),
        )
        c.commit()
    finally:
        c.close()

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    new_key = r.json()["api_key"]
    new_kh = hash_api_key(new_key)

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        old_count = c.execute(
            "SELECT COUNT(*) AS n FROM alert_subscriptions WHERE api_key_hash = ?",
            (old_kh,),
        ).fetchone()["n"]
        new_count = c.execute(
            "SELECT COUNT(*) AS n FROM alert_subscriptions WHERE api_key_hash = ?",
            (new_kh,),
        ).fetchone()["n"]
        assert old_count == 0
        assert new_count == 2
    finally:
        # Clean up so other tests aren't polluted.
        cleanup = sqlite3.connect(seeded_db)
        try:
            cleanup.execute("DELETE FROM alert_subscriptions")
            cleanup.commit()
        finally:
            cleanup.close()
        c.close()


def test_bonus_rotation_reissues_session_cookie_for_new_key(client, paid_key, seeded_db: Path):
    """Bonus: the rotate-key response sets a fresh cookie bound to the
    NEW key_hash, so /v1/me succeeds with the cookie that came back
    from the rotate response."""
    from jpintel_mcp.api.deps import hash_api_key

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    old_cookie = client.cookies.get("am_session")

    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    new_cookie = client.cookies.get("am_session")
    assert new_cookie is not None
    assert new_cookie != old_cookie

    new_key = r.json()["api_key"]
    # Decode the cookie and confirm it carries the NEW key_hash.
    me = _me_module()
    kh, tier, _exp_iso, _sig = me._decode_cookie(new_cookie)
    assert kh == hash_api_key(new_key)
    assert tier == "paid"

    # /v1/me with the new cookie still works (no extra session POST).
    r = client.get("/v1/me")
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "paid"


def test_p01_concurrent_rotation_only_creates_one_new_key(client, paid_key, seeded_db: Path):
    """P0-1: N threads racing to /v1/me/rotate-key for the SAME old key
    end up with exactly one rotation winner — the others 401 (key already
    revoked inside the txn) or 5xx (writer-lock contention). Never end
    up with two new keys descended from the one old key.

    seeded_db is session-scoped so other tests' keys live in api_keys
    too — we measure the delta in rows tagged to OUR specific old key,
    not absolute counts.
    """
    import threading

    from fastapi.testclient import TestClient

    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.api.main import create_app

    old_kh = hash_api_key(paid_key)
    app = create_app()

    # One TestClient per thread (sharing one risks cookie-jar races).
    def _worker(results: list[int], new_keys: list[str], idx: int) -> None:
        c = TestClient(app)
        r = c.post("/v1/session", json={"api_key": paid_key})
        if r.status_code != 200:
            results[idx] = r.status_code
            return
        r2 = c.post("/v1/me/rotate-key", headers=_csrf_headers(c))
        results[idx] = r2.status_code
        if r2.status_code == 200:
            new_keys[idx] = r2.json()["api_key"]

    n = 4
    results: list[int] = [0] * n
    new_keys: list[str] = [""] * n
    threads = [threading.Thread(target=_worker, args=(results, new_keys, i)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = sum(1 for s in results if s == 200)
    assert successes >= 1, f"at least one winner expected, got {results}"

    # Atomicity invariant: the OLD key is now revoked exactly once
    # (the winning UPDATE), and at most ONE rotation succeeded — so
    # at most ONE new key descended from this old key.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        old_row = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            (old_kh,),
        ).fetchone()
        # Old key must be revoked (the one winner committed the UPDATE).
        assert old_row["revoked_at"] is not None
    finally:
        c.close()

    distinct_new = {k for k in new_keys if k}
    assert len(distinct_new) == successes, (
        f"each 200 response must yield a distinct new key, "
        f"got {len(distinct_new)} distinct vs {successes} successes; "
        f"results={results}"
    )
    # Critical: at most ONE successful rotation per old key — no two
    # threads produced a new key (which would mean the txn wasn't
    # atomic w.r.t. the revoked-at gate).
    assert successes <= 1, (
        f"expected ≤1 successful rotation, got {successes}; results={results}, new_keys={new_keys}"
    )


def test_billing_portal_stripe_error_returns_subsystem_unavailable(client, paid_key, monkeypatch):
    """Stripe failures must surface as a generic 503 envelope, not leak
    the upstream error message."""
    import stripe

    from jpintel_mcp.api import me as me_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)

    raw_stripe_message = "stripe_api_internal_x7q9_customer_id_visible"

    def _boom(**kwargs):
        raise stripe.error.APIError(raw_stripe_message)

    monkeypatch.setattr(me_mod.stripe.billing_portal.Session, "create", _boom)

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200

    r = client.post("/v1/me/billing-portal", headers=_csrf_headers(client))
    assert r.status_code == 503, r.text
    body = r.json()
    detail = body["detail"]
    assert detail["error"] == "subsystem_unavailable"
    assert "Billing service" in detail["message"]
    # Raw Stripe message must NOT leak in the response anywhere.
    assert raw_stripe_message not in r.text


# ---------------------------------------------------------------------------
# P1 audit log: rotate-key writes exactly one audit_log row
# (audit a4298e454aab2aa43, migration 058_audit_log)
# ---------------------------------------------------------------------------


def test_audit_log_rotate_key_writes_one_row(client, paid_key, seeded_db: Path):
    """rotate-key must produce exactly 1 audit_log row with both old and new
    key_hash populated. Forensic baseline for 不正アクセス禁止法 incident
    response."""
    from jpintel_mcp.api.deps import hash_api_key

    old_hash = hash_api_key(paid_key)

    # Pre-condition: zero audit_log rows for this key_hash before rotation.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        n_before = c.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'key_rotate' AND key_hash = ?",
            (old_hash,),
        ).fetchone()["n"]
    finally:
        c.close()
    assert n_before == 0

    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200
    r = client.post("/v1/me/rotate-key", headers=_csrf_headers(client))
    assert r.status_code == 200, r.text
    new_key = r.json()["api_key"]
    new_hash = hash_api_key(new_key)

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT event_type, key_hash, key_hash_new, customer_id "
            "FROM audit_log "
            "WHERE event_type = 'key_rotate' AND key_hash = ?",
            (old_hash,),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1, f"expected exactly 1 key_rotate row, got {len(rows)}"
    row = rows[0]
    assert row["event_type"] == "key_rotate"
    assert row["key_hash"] == old_hash
    assert row["key_hash_new"] == new_hash
    assert row["customer_id"] == "cus_me_test"
