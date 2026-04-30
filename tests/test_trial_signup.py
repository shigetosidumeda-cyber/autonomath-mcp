"""Tests for the email-only trial signup flow (POST /v1/signup,
GET /v1/signup/verify, scripts/cron/expire_trials).

Coverage:
    1. POST /v1/signup → 202 + trial_signups row + magic-link mail.
    2. GET /v1/signup/verify with the issued token →
       302 redirect to /trial.html#api_key=... + new tier='trial'
       api_keys row + verified_at + issued_api_key_hash.
    3. /v1/me-equivalent: the issued key authenticates against
       require_key (we test the same auth-validation contract by
       calling a /v1/programs/search with X-API-Key, which uses
       require_key under the hood — /v1/me itself requires a session
       cookie, not a bearer key, so we exercise the bearer-validate
       path that the trial key actually walks).
    4. Trial expiration cron: simulating 14 days elapsed, the
       expire_trials script revokes the key and the same key now
       401's on subsequent requests.
    5. Per-IP velocity: second signup attempt within 24h → 429.
    6. Email normalisation: gmail dot/+plus dedup.

Email side-effect is stubbed so we never reach Postmark. We assert on
the trial_signups DB state and the redirect contract instead.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture()
def email_recorder(monkeypatch):
    """Capture every magic-link email side-effect.

    We replace `_send_magic_link_email` (the BackgroundTasks target) so
    the test asserts on call shape regardless of how Postmark itself
    happens to dispatch.
    """
    captured: list[dict] = []

    def _fake_send(**kwargs) -> None:
        captured.append(kwargs)

    from jpintel_mcp.api import signup as mod

    monkeypatch.setattr(mod, "_send_magic_link_email", _fake_send)
    return captured


@pytest.fixture()
def welcome_recorder(monkeypatch):
    """Capture every post-activation welcome enqueue.

    We replace `_enqueue_trial_welcome` so the test never has to spin up
    the bg_task_worker (which would race with the test loop).
    """
    captured: list[dict] = []

    def _fake_enqueue(conn, **kwargs) -> None:
        captured.append(kwargs)

    from jpintel_mcp.api import signup as mod

    monkeypatch.setattr(mod, "_enqueue_trial_welcome", _fake_enqueue)
    return captured


@pytest.fixture(autouse=True)
def _clear_trial_rows(seeded_db):
    """Each test starts with empty trial_signups + trial keys cleared.

    Without this, the lifetime UNIQUE on email_normalized + per-IP
    velocity gate bleed across tests on the shared TestClient IP.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM trial_signups")
        c.execute("DELETE FROM api_keys WHERE tier = 'trial'")
        c.commit()
    except sqlite3.OperationalError:
        # tables may not exist on a very old test DB; safe to skip
        pass
    finally:
        c.close()
    yield


def _post_signup(client, email: str):
    """Helper — POST /v1/signup and return the response."""
    return client.post("/v1/signup", json={"email": email})


def test_trial_signup_creates_pending_row_and_mails_link(
    client, seeded_db, email_recorder
):
    r = _post_signup(client, "evaluator@example.com")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert "リンク" in body["detail"]

    # trial_signups row landed, unverified, with the right normalisation.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT email, email_normalized, verified_at, issued_api_key_hash, "
            "token_hash, created_at, created_ip_hash "
            "FROM trial_signups"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "evaluator@example.com"
    assert row["email_normalized"] == "evaluator@example.com"
    assert row["verified_at"] is None
    assert row["issued_api_key_hash"] is None
    assert isinstance(row["token_hash"], str) and len(row["token_hash"]) == 64

    # Email side-effect fired exactly once with the right shape.
    assert len(email_recorder) == 1
    sent = email_recorder[0]
    assert sent["to"] == "evaluator@example.com"
    assert "/v1/signup/verify" in sent["magic_link_url"]
    assert "token=" in sent["magic_link_url"]
    assert sent["expires_at_iso"]


def test_trial_signup_gmail_dot_plus_normalisation(
    client, seeded_db, email_recorder
):
    """gmail dot/+ collapsing: the two below are the same mailbox to Google."""
    from jpintel_mcp.api.signup import _normalize_email

    assert _normalize_email("F.O.O+test@gmail.com") == "foo@gmail.com"
    assert _normalize_email("foo@googlemail.com") == "foo@gmail.com"
    assert _normalize_email("Bar+anything@example.com") == "bar@example.com"


def test_trial_signup_lifetime_dedup_silent_no_double_send(
    client, seeded_db, email_recorder
):
    """Re-signup with the same email → 202 (uniform shape) but NO second mail."""
    # First signup succeeds.
    r1 = _post_signup(client, "dup@example.com")
    assert r1.status_code == 202

    # Reset per-IP gate so we test the email-uniqueness path, not the IP path.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM trial_signups WHERE email_normalized != ?",
                  ("dup@example.com",))
        # bump created_at backwards so the per-IP 24h check passes.
        old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        c.execute(
            "UPDATE trial_signups SET created_at = ? WHERE email_normalized = ?",
            (old, "dup@example.com"),
        )
        c.commit()
    finally:
        c.close()

    r2 = _post_signup(client, "dup@example.com")
    # Uniform 202 response so account-existence isn't leaked, but no
    # new mail was sent (the duplicate check short-circuited).
    assert r2.status_code == 202
    # Only the first mail was sent.
    assert len(email_recorder) == 1


def test_trial_signup_per_ip_velocity_429(client, seeded_db, email_recorder):
    """Two distinct emails from one IP within 24h → second is 429."""
    r1 = _post_signup(client, "first@example.com")
    assert r1.status_code == 202
    r2 = _post_signup(client, "second@example.com")
    assert r2.status_code == 429
    body = r2.json()
    assert body["detail"]["error"] == "signup_rate_limited"
    assert body["detail"]["retry_after"] == 24 * 3600


def test_trial_signup_invalid_email_format_422(client):
    r = client.post("/v1/signup", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_verify_issues_trial_key_and_redirects_to_landing(
    client, seeded_db, email_recorder, welcome_recorder
):
    """End-to-end: signup → verify URL → tier='trial' key in DB."""
    r = _post_signup(client, "claim@example.com")
    assert r.status_code == 202
    assert len(email_recorder) == 1

    # Extract the token from the captured magic-link URL.
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(magic_url)
    qs = parse_qs(parsed.query)
    token = qs["token"][0]
    email_param = qs["email"][0]
    assert email_param == "claim@example.com"

    # Hit verify. follow_redirects=False so we can assert on the 302.
    r = client.get(
        f"/v1/signup/verify?email={email_param}&token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith("https://jpcite.com/trial.html?status=ok")
    assert "#api_key=am_" in location
    assert "expires_at=" in location
    assert "request_cap=200" in location
    assert "duration_days=14" in location

    # DB state: tier='trial' api_keys row + verified_at on trial_signups.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        signup = c.execute(
            "SELECT verified_at, issued_api_key_hash "
            "FROM trial_signups WHERE email_normalized = ?",
            ("claim@example.com",),
        ).fetchone()
        assert signup["verified_at"] is not None
        assert signup["issued_api_key_hash"] is not None

        api_key = c.execute(
            "SELECT tier, customer_id, stripe_subscription_id, "
            "trial_email, trial_started_at, trial_expires_at, "
            "trial_requests_used, monthly_cap_yen "
            "FROM api_keys WHERE key_hash = ?",
            (signup["issued_api_key_hash"],),
        ).fetchone()
    finally:
        c.close()

    assert api_key["tier"] == "trial"
    assert api_key["customer_id"] is None
    assert api_key["stripe_subscription_id"] is None
    assert api_key["trial_email"] == "claim@example.com"
    assert api_key["trial_started_at"]
    assert api_key["trial_expires_at"]
    assert api_key["trial_requests_used"] == 0
    # 200 reqs * ¥3/req = ¥600 hard cap, even though no Stripe usage
    # is reported for tier='trial' rows.
    assert api_key["monthly_cap_yen"] == 600

    # Welcome email enqueued exactly once.
    assert len(welcome_recorder) == 1
    assert welcome_recorder[0]["to"] == "claim@example.com"


def test_verify_with_invalid_token_redirects_to_invalid_state(
    client, seeded_db, email_recorder
):
    r = _post_signup(client, "tampered@example.com")
    assert r.status_code == 202

    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    email_param = qs["email"][0]
    # Send a wrong token of the right format (64 hex).
    bogus = "0" * 64

    r = client.get(
        f"/v1/signup/verify?email={email_param}&token={bogus}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "trial.html?status=invalid" in r.headers["location"]
    # No api_keys row was issued.
    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE tier = 'trial'"
        ).fetchone()
    finally:
        c.close()
    assert rows[0] == 0


def test_verify_after_expiry_window_redirects_expired(
    client, seeded_db, email_recorder
):
    r = _post_signup(client, "stale@example.com")
    assert r.status_code == 202

    # Push the trial_signups.created_at 25h backwards so the 24h magic
    # link window has elapsed. Also update token_hash so the
    # defense-in-depth dual verify (HMAC compare + stored-hash compare)
    # passes — the production flow has these in sync because the row
    # was inserted atomically; the test has to keep them aligned.
    from jpintel_mcp.api.signup import _hash_token, _make_token

    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    new_token = _make_token("stale@example.com", old)
    new_hash = _hash_token(new_token)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE trial_signups SET created_at = ?, token_hash = ? "
            "WHERE email_normalized = ?",
            (old, new_hash, "stale@example.com"),
        )
        c.commit()
    finally:
        c.close()

    r = client.get(
        f"/v1/signup/verify?email=stale@example.com&token={new_token}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "trial.html?status=expired" in r.headers["location"]


def test_trial_key_authenticates_for_api_calls(
    client, seeded_db, email_recorder, welcome_recorder
):
    """Issued trial key authenticates: hitting an authed endpoint with
    X-API-Key returns 200, exercising the same require_key path that
    paid keys use.

    We hit /v1/programs/search because the seeded_db fixture has rows
    there; /v1/me is session-cookie-only and not the right surface for
    a bearer-token validation contract.
    """
    r = _post_signup(client, "auth@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    token = qs["token"][0]
    email_param = qs["email"][0]
    r = client.get(
        f"/v1/signup/verify?email={email_param}&token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    # Pull raw key out of the redirect fragment.
    location = r.headers["location"]
    fragment = location.split("#", 1)[1]
    raw_key = None
    for kv in fragment.split("&"):
        if kv.startswith("api_key="):
            from urllib.parse import unquote

            raw_key = unquote(kv.split("=", 1)[1])
            break
    assert raw_key and raw_key.startswith("am_")

    # Trial key authenticates through require_key.
    r = client.get(
        "/v1/programs/search?q=テスト&limit=1",
        headers={"X-API-Key": raw_key},
    )
    assert r.status_code == 200, r.text


def test_expire_trials_cron_revokes_past_deadline(
    client, seeded_db, email_recorder, welcome_recorder
):
    """Simulate 14d elapsed → cron revokes the key → subsequent calls 401."""
    r = _post_signup(client, "expire@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    r = client.get(
        f"/v1/signup/verify?email={qs['email'][0]}&token={qs['token'][0]}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers["location"]
    fragment = location.split("#", 1)[1]
    from urllib.parse import unquote

    raw_key = None
    for kv in fragment.split("&"):
        if kv.startswith("api_key="):
            raw_key = unquote(kv.split("=", 1)[1])
            break
    assert raw_key

    # Push trial_expires_at 1d into the past so the cron's predicate fires.
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET trial_expires_at = ? "
            "WHERE tier = 'trial' AND trial_email = ?",
            (past, "expire@example.com"),
        )
        c.commit()
    finally:
        c.close()

    # Run the cron. It opens its own DB connection via db.session.connect
    # which reads JPINTEL_DB_PATH (already set by conftest to seeded_db).
    from scripts.cron.expire_trials import expire_due_trials

    counts = expire_due_trials()
    assert counts["scanned"] == 1
    assert counts["revoked_expired"] == 1
    assert counts["revoked_cap"] == 0
    assert counts["email_enqueued"] == 1

    # Same key now 401's because revoked_at is set.
    r = client.get(
        "/v1/programs/search?q=テスト&limit=1",
        headers={"X-API-Key": raw_key},
    )
    assert r.status_code == 401, r.text


def test_expire_trials_cron_revokes_cap_exhaustion(
    client, seeded_db, email_recorder, welcome_recorder
):
    """Simulate 200 reqs used → cron revokes via cap path."""
    r = _post_signup(client, "cap@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    r = client.get(
        f"/v1/signup/verify?email={qs['email'][0]}&token={qs['token'][0]}",
        follow_redirects=False,
    )
    assert r.status_code == 302

    # Mark the key as having burned all 200 trial reqs without touching
    # trial_expires_at (still in the future). The cron must still revoke.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET trial_requests_used = 200 "
            "WHERE tier = 'trial' AND trial_email = ?",
            ("cap@example.com",),
        )
        c.commit()
    finally:
        c.close()

    from scripts.cron.expire_trials import expire_due_trials

    counts = expire_due_trials()
    assert counts["scanned"] == 1
    assert counts["revoked_cap"] == 1
    assert counts["revoked_expired"] == 0


def test_trial_request_cap_fires_at_200th(
    client, seeded_db, email_recorder, welcome_recorder
):
    """Synchronous 200-req cap (Bug 1, 2026-04-29 funnel audit).

    The pre-fix posture left this completely unenforced:
        * TIER_LIMITS had no 'trial' key → _enforce_quota fell through.
        * CustomerCapMiddleware filters metered=1, but trial keys are
          metered=0 (ApiContext.metered checks tier=='paid').
        * trial_requests_used was never incremented anywhere.

    Post-fix:
        * deps.TIER_LIMITS gains a 'trial' entry.
        * deps._enforce_quota reads api_keys.trial_requests_used and
          429s synchronously when used >= TRIAL_REQUEST_CAP.
        * deps.log_usage (both inline + deferred) bumps the counter.

    Test contract: issue a trial key, manually pre-charge the counter to
    199 (so we don't have to actually fire 200 real /v1/programs/search
    calls — the test is about the gate, not bulk traffic), then assert:
        * the 200th request (counter goes from 199 → 200) returns 200
        * the 201st request (counter is already at 200) returns 429
          with the spec envelope (upgrade_url, trial_terms, trial_request_cap).

    The cron then has nothing to do — the synchronous gate already
    blocks the request before the router runs.
    """
    # Sign up + verify to get a real trial key.
    r = _post_signup(client, "cap-sync@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, unquote, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    r = client.get(
        f"/v1/signup/verify?email={qs['email'][0]}&token={qs['token'][0]}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers["location"]
    fragment = location.split("#", 1)[1]
    raw_key = None
    for kv in fragment.split("&"):
        if kv.startswith("api_key="):
            raw_key = unquote(kv.split("=", 1)[1])
            break
    assert raw_key

    # Pre-charge the counter to 199 so the next request crosses the
    # threshold. We avoid firing 200 real calls so the test stays under
    # 1s and doesn't depend on the FTS5 cache TTL.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET trial_requests_used = 199 "
            "WHERE tier = 'trial' AND trial_email = ?",
            ("cap-sync@example.com",),
        )
        c.commit()
    finally:
        c.close()

    # 200th call: counter 199 → check passes (199 < 200), then log_usage
    # bumps to 200. Endpoint must return 200.
    r = client.get(
        "/v1/programs/search?q=テスト&limit=1",
        headers={"X-API-Key": raw_key},
    )
    assert r.status_code == 200, r.text

    # Verify counter is now 200.
    c = sqlite3.connect(seeded_db)
    try:
        used = c.execute(
            "SELECT trial_requests_used FROM api_keys "
            "WHERE tier = 'trial' AND trial_email = ?",
            ("cap-sync@example.com",),
        ).fetchone()[0]
    finally:
        c.close()
    assert used == 200, f"expected 200 after 200th call, got {used}"

    # 201st call: counter is already at 200 → _enforce_quota raises 429
    # synchronously BEFORE the router runs. No usage_events row written
    # for this rejected request (the inline log_usage path is past the
    # raise point).
    r = client.get(
        "/v1/programs/search?q=テスト&limit=1",
        headers={"X-API-Key": raw_key},
    )
    assert r.status_code == 429, r.text
    body = r.json()
    # FastAPI HTTPException with detail=dict surfaces the dict at
    # response['detail'].
    detail = body.get("detail", {})
    assert detail.get("error") == "trial_request_cap_reached"
    assert detail.get("trial_request_cap") == 200
    assert detail.get("trial_requests_used") == 200
    assert "upgrade_url" in detail
    assert detail["upgrade_url"] == (
        "https://jpcite.com/pricing.html?from=trial#api-paid"
    )
    assert "trial_terms" in detail
    assert "cta_text_ja" in detail


def test_trial_revoked_key_returns_recovery_envelope(
    client, seeded_db, email_recorder, welcome_recorder
):
    """Revoked trial key returns 401 with upgrade_url + cta hint (Bug 4).

    Prior to the 2026-04-29 audit fix, a trial caller hitting any
    endpoint with a revoked trial key got a generic
    {"detail": "api key revoked"} 401 with no recovery path. Now the
    revoke check on require_key surfaces upgrade_url + cta_text_ja +
    trial_expired=true so client tooling can route the user to the
    paid-API entry.
    """
    # Issue a trial key, then revoke it manually (mirroring what the
    # cron does after trial_expires_at <= now()).
    r = _post_signup(client, "revoked@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, unquote, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    r = client.get(
        f"/v1/signup/verify?email={qs['email'][0]}&token={qs['token'][0]}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers["location"]
    fragment = location.split("#", 1)[1]
    raw_key = None
    for kv in fragment.split("&"):
        if kv.startswith("api_key="):
            raw_key = unquote(kv.split("=", 1)[1])
            break
    assert raw_key

    # Revoke the key directly.
    now = datetime.now(UTC).isoformat()
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET revoked_at = ? "
            "WHERE tier = 'trial' AND trial_email = ?",
            (now, "revoked@example.com"),
        )
        c.commit()
    finally:
        c.close()

    r = client.get(
        "/v1/programs/search?q=テスト&limit=1",
        headers={"X-API-Key": raw_key},
    )
    assert r.status_code == 401, r.text
    body = r.json()
    detail = body.get("detail", {})
    assert isinstance(detail, dict)
    assert detail.get("trial_expired") is True
    assert detail.get("upgrade_url") == (
        "https://jpcite.com/pricing.html?from=trial#api-paid"
    )
    assert "cta_text_ja" in detail


def test_trial_expired_email_handler_dispatches(seeded_db, monkeypatch):
    """trial_expired_email handler exists in _HANDLERS and renders to
    the expected Postmark template alias (Bug 2 from 2026-04-29 audit).

    Prior to the fix, the cron enqueued kind='trial_expired_email' rows
    but no handler was registered → bg worker returned
    'unknown kind: trial_expired_email' and the email never sent. The
    test now drives the handler directly with a synthetic payload and
    asserts the Postmark client received the right template_alias and
    template_model keys.
    """
    captured: list[dict] = []

    class _StubClient:
        def _send(self, **kwargs):
            captured.append(kwargs)
            return {"ok": True}

    from jpintel_mcp.api import _bg_task_worker as worker
    from jpintel_mcp.email import postmark as postmark_mod

    monkeypatch.setattr(postmark_mod, "get_client", lambda: _StubClient())

    # Confirm the handler is registered.
    assert "trial_expired_email" in worker._HANDLERS

    # Drive the handler directly. The cron would enqueue a payload with
    # this exact shape via _bg_enqueue.
    worker._HANDLERS["trial_expired_email"]({
        "to": "expired-handler@example.com",
        "key_last4": "abcd",
        "cause": "expired",
        "checkout_url": (
            "https://jpcite.com/pricing.html?from=trial#api-paid"
        ),
    })

    assert len(captured) == 1
    sent = captured[0]
    assert sent["to"] == "expired-handler@example.com"
    assert sent["template_alias"] == "onboarding-trial-expired"
    assert sent["tag"] == "onboarding-trial-expired"
    model = sent["template_model"]
    assert model["key_last4"] == "abcd"
    assert model["cause"] == "expired"
    assert "checkout_url" in model and "from=trial" in model["checkout_url"]


def test_expire_trials_cron_uses_from_trial_url(
    client, seeded_db, email_recorder, welcome_recorder, monkeypatch
):
    """Cron enqueue must carry ?from=trial in checkout_url (Bug 2 follow-up).

    The trial_expired_email payload is what the handler renders into the
    template; if the cron enqueued bare /pricing.html the trial-attribution
    banner on /pricing.html would never light. We capture the enqueue
    payload by stubbing _bg_enqueue and assert the URL.
    """
    r = _post_signup(client, "checkout-url@example.com")
    assert r.status_code == 202
    magic_url = email_recorder[0]["magic_link_url"]
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(magic_url).query)
    r = client.get(
        f"/v1/signup/verify?email={qs['email'][0]}&token={qs['token'][0]}",
        follow_redirects=False,
    )
    assert r.status_code == 302

    # Mark cap exhaustion.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET trial_requests_used = 200 "
            "WHERE tier = 'trial' AND trial_email = ?",
            ("checkout-url@example.com",),
        )
        c.commit()
    finally:
        c.close()

    # Capture the enqueue payload.
    enqueued: list[dict] = []
    import scripts.cron.expire_trials as cron_mod

    def _capture_enqueue(conn, *, kind, payload, **kwargs):
        enqueued.append({"kind": kind, "payload": payload, **kwargs})
        return 1  # simulate row id

    monkeypatch.setattr(cron_mod, "_bg_enqueue", _capture_enqueue)

    counts = cron_mod.expire_due_trials()
    assert counts["revoked_cap"] == 1
    assert counts["email_enqueued"] == 1

    assert len(enqueued) == 1
    payload = enqueued[0]["payload"]
    assert enqueued[0]["kind"] == "trial_expired_email"
    assert payload["to"] == "checkout-url@example.com"
    assert payload["cause"] == "cap"
    # The single fix that unblocks the trial-attribution banner.
    assert payload["checkout_url"] == (
        "https://jpcite.com/pricing.html?from=trial#api-paid"
    )
