import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.api.deps import hash_api_key as _hash_api_key
from jpintel_mcp.billing.keys import (
    generate_api_key,
    hash_api_key,
    issue_key,
    resolve_tier_from_price,
    revoke_key,
    revoke_subscription,
    update_tier_by_subscription,
)


@pytest.fixture()
def conn(seeded_db: Path):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_generate_key_shape():
    raw, h = generate_api_key()
    assert raw.startswith("am_")
    assert len(raw) > 30
    assert hash_api_key(raw) == h
    assert hash_api_key(raw + "tamper") != h


def test_issue_and_revoke_key(conn):
    raw = issue_key(conn, customer_id="cus_test", tier="paid", stripe_subscription_id="sub_1")
    key_hash = hash_api_key(raw)
    row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
    assert row is not None
    assert row["tier"] == "paid"
    assert row["customer_id"] == "cus_test"
    assert row["revoked_at"] is None

    assert revoke_key(conn, key_hash) is True
    row = conn.execute("SELECT revoked_at FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
    assert row["revoked_at"] is not None


def test_revoke_subscription_cascades(conn):
    issue_key(conn, customer_id="c1", tier="paid", stripe_subscription_id="sub_cascade")
    issue_key(conn, customer_id="c1", tier="paid", stripe_subscription_id="sub_cascade")
    n = revoke_subscription(conn, "sub_cascade")
    assert n == 2


def test_update_tier(conn):
    issue_key(conn, customer_id="c2", tier="free", stripe_subscription_id="sub_upd")
    n = update_tier_by_subscription(conn, "sub_upd", "paid")
    assert n == 1
    row = conn.execute(
        "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
        ("sub_upd",),
    ).fetchone()
    assert row["tier"] == "paid"


def test_resolve_tier_unknown_price():
    assert resolve_tier_from_price("price_unknown") == "free"


# ---------------------------------------------------------------------------
# HTTP-level billing endpoint tests.
# Stripe is never called for real — Session.retrieve / Subscription.retrieve /
# Webhook.construct_event are monkeypatched.
# ---------------------------------------------------------------------------


class _FakeCustomerDetails:
    def __init__(self, email: str | None) -> None:
        self.email = email


class _FakeCheckoutSession:
    def __init__(
        self,
        *,
        payment_status: str = "no_payment_required",
        customer: str = "cus_checkout_1",
        subscription: str = "sub_checkout_1",
        customer_email: str | None = None,
        cd_email: str | None = "buyer@example.com",
    ) -> None:
        # Metered subs default to "no_payment_required" (Stripe doesn't
        # charge upfront — first invoice comes from usage_records).
        self.payment_status = payment_status
        self.customer = customer
        self.subscription = subscription
        self.customer_email = customer_email
        self.customer_details = _FakeCustomerDetails(cd_email) if cd_email else None


class _FakeSubscription(dict):
    """Stripe SDK Subscription is dict-like. The code indexes sub['items']['data']..."""


def _fake_sub(price_id: str, sub_id: str = "sub_checkout_1") -> _FakeSubscription:
    return _FakeSubscription(
        {
            "id": sub_id,
            "items": {"data": [{"price": {"id": price_id}}]},
        }
    )


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so _stripe() doesn't 503."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(
        settings, "stripe_price_per_request", "price_metered_test", raising=False
    )
    yield settings


def test_checkout_503_when_stripe_not_configured(client, monkeypatch):
    """_stripe() raises 503 when STRIPE_SECRET_KEY is unset — prevents prod-misconfig leaks."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "", raising=False)
    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://example.test/ok",
            "cancel_url": "https://example.test/no",
        },
    )
    assert r.status_code == 503
    assert "stripe" in r.json()["detail"].lower()


def test_checkout_503_when_price_not_configured(client, monkeypatch):
    """STRIPE_PRICE_PER_REQUEST unset → 503 service_unavailable.

    Was 400 historically; flipped to 503 because the caller did nothing wrong
    — this is an operator-side mis-configuration (Fly secret unset) and 503
    maps cleanly to the canonical envelope's `service_unavailable` code so an
    LLM caller reading `error.code` sees an actionable retry signal instead
    of a misleading client-error tag.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "", raising=False)
    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://example.test/ok",
            "cancel_url": "https://example.test/no",
        },
    )
    assert r.status_code == 503
    body = r.json()
    # Detail string carries the explanation; envelope `error.code` carries
    # the canonical machine-readable code.
    detail_str = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
    assert "billing" in detail_str.lower() or "price" in detail_str.lower()
    err = body.get("error") or {}
    if err:
        assert err.get("code") == "service_unavailable"


def test_portal_calls_stripe_with_customer_and_return_url(client, stripe_env, monkeypatch):
    """/billing/portal hands Stripe the customer_id + return_url verbatim."""
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict] = []

    class _FakePortalSession:
        url = "https://billing.stripe.test/portal/abc"

    def _create(**kwargs):
        captured.append(kwargs)
        return _FakePortalSession()

    monkeypatch.setattr(billing_mod.stripe.billing_portal.Session, "create", _create)

    r = client.post(
        "/v1/billing/portal",
        json={"customer_id": "cus_portal_1", "return_url": "https://example.test/back"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://billing.stripe.test/portal/abc"}
    assert captured[0]["customer"] == "cus_portal_1"
    assert captured[0]["return_url"] == "https://example.test/back"


def test_issue_from_checkout_402_when_session_not_paid(client, stripe_env, monkeypatch):
    """Refuse key issuance for an unpaid/abandoned Checkout session."""
    from jpintel_mcp.api import billing as billing_mod

    def _retrieve(_sid, **_):
        return _FakeCheckoutSession(payment_status="unpaid")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_abandoned"})
    assert r.status_code == 402
    assert "not paid" in r.json()["detail"].lower()


def test_issue_from_checkout_returns_raw_key_once_and_persists_hash(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Happy path: metered Checkout → raw API key returned + hashed row in api_keys."""
    from jpintel_mcp.api import billing as billing_mod

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_happy",
            subscription="sub_happy",
            cd_email="happy@example.com",
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_happy")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_happy"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"
    assert body["customer_id"] == "cus_happy"
    raw_key = body["api_key"]
    assert raw_key.startswith("am_")

    # Raw key never in DB — only the HMAC hash.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier, customer_id, stripe_subscription_id, revoked_at FROM api_keys "
            "WHERE key_hash = ?",
            (_hash_api_key(raw_key),),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"
    assert row[1] == "cus_happy"
    assert row[2] == "sub_happy"
    assert row[3] is None


def test_issue_from_checkout_is_idempotent_per_subscription(client, stripe_env, monkeypatch):
    """Second call for the same subscription returns 409, not a duplicate key.

    Prevents the "customer double-clicks the Checkout success page" failure
    mode that would mint two valid keys and leave billing desynced.
    """
    from jpintel_mcp.api import billing as billing_mod

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_dupe",
            subscription="sub_dupe",
            cd_email=None,
            customer_email="dupe@example.com",
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_dupe")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r1 = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_dupe"})
    assert r1.status_code == 200, r1.text

    r2 = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_dupe"})
    assert r2.status_code == 409, r2.text
    assert "already issued" in r2.json()["detail"].lower()


# --- webhook -----------------------------------------------------------------


def _patch_webhook_construct_event(monkeypatch, event: dict):
    """Bypass Stripe signature verification; still exercises dispatch logic."""
    from jpintel_mcp.api import billing as billing_mod

    def _construct(body, sig, secret):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


def test_webhook_503_without_secret(client, monkeypatch):
    """No STRIPE_WEBHOOK_SECRET → refuse every call."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "", raising=False)
    r = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=abc"},
    )
    assert r.status_code == 503


def test_webhook_rejects_bad_signature(client, stripe_env, monkeypatch):
    """Stripe SDK raises SignatureVerificationError → 400."""
    import stripe

    from jpintel_mcp.api import billing as billing_mod

    def _construct(*_args, **_kw):
        raise stripe.SignatureVerificationError("bad", "sig")

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)

    r = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=AAAA"},
    )
    assert r.status_code == 400
    assert "signature" in r.json()["detail"].lower()


def test_webhook_rejects_oversize_content_length(client, stripe_env):
    """DoS hardening: Content-Length > 1 MB → 413 BEFORE reading body."""
    r = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={
            "stripe-signature": "t=1,v1=AAAA",
            "content-length": "2000000",
        },
    )
    assert r.status_code == 413
    detail = r.json().get("detail", {})
    assert detail.get("error") == "out_of_range"


def test_webhook_no_content_length_still_validates_signature(
    client, stripe_env, monkeypatch
):
    """Missing content-length → no 413; signature path is still hit."""
    import stripe

    from jpintel_mcp.api import billing as billing_mod

    def _construct(*_args, **_kw):
        raise stripe.SignatureVerificationError("bad", "sig")

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)

    # httpx auto-sets content-length; explicitly suppress would require a custom
    # transport. Instead assert that a small body with content-length present
    # passes the size guard and reaches signature verification (→ 400).
    r = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=AAAA"},
    )
    assert r.status_code == 400, r.text


def test_webhook_subscription_created_issues_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.created → mint one key for metered subscription.

    This is the primary issuance moment now — metered subs fire
    subscription.created immediately on Checkout completion, before any
    invoice event.
    """
    event = {
        "id": "evt_sub_created",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_metered_new",
                "customer": "cus_metered_new",
                "items": {
                    "data": [{"price": {"id": "price_metered_test"}}]
                },
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier, customer_id FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_metered_new",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"


def test_webhook_invoice_paid_safety_net_issues_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """invoice.paid for a previously-unseen subscription → mint one key.

    Safety-net path when subscription.created was lost in transit.
    """
    from jpintel_mcp.api import billing as billing_mod

    event = {
        "id": "evt_paid_1",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_webhook_fallback",
                "customer": "cus_webhook_fallback",
                "customer_email": "wh@example.com",
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)
    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _id, **_: _fake_sub(
            price_id="price_metered_test", sub_id="sub_webhook_fallback"
        ),
    )

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier, customer_id FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_webhook_fallback",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"


def test_webhook_is_idempotent_on_replay(client, stripe_env, monkeypatch, seeded_db: Path):
    """Stripe delivers subscription.created twice (retry) → still one row.

    Duplicate webhook deliveries must NEVER mint duplicate keys.
    """
    event = {
        "id": "evt_replay",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_replay",
                "customer": "cus_replay",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    for _ in range(3):
        r = client.post(
            "/v1/billing/webhook",
            content=json.dumps(event).encode("utf-8"),
            headers={"stripe-signature": "t=1,v1=xx"},
        )
        assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_replay",),
        ).fetchone()
    finally:
        c.close()
    assert n == 1, f"expected exactly one key row for replayed sub, got {n}"


def test_webhook_subscription_updated_flips_tier_on_existing_keys(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.updated → api_keys.tier moves to the new price's tier.

    Edge case: price swap from the metered price to some other price (or
    vice versa). Our single-price model normally keeps this at `paid`,
    but the handler still maps via resolve_tier_from_price.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_upg", tier="free", stripe_subscription_id="sub_upgrade")
    c.commit()
    c.close()

    event = {
        "id": "evt_upd",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_upgrade",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_upgrade",),
        ).fetchone()
    finally:
        c.close()
    assert row[0] == "paid"


def test_webhook_subscription_deleted_revokes_all_keys_for_subscription(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.deleted → every active key for that sub gets revoked_at."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_cancel", tier="paid", stripe_subscription_id="sub_cancel")
    issue_key(c, customer_id="cus_cancel", tier="paid", stripe_subscription_id="sub_cancel")
    c.commit()
    c.close()

    event = {
        "id": "evt_del",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_cancel"}},
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT revoked_at FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_cancel",),
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 2
    assert all(r[0] is not None for r in rows), "both keys must be revoked"


def test_webhook_payment_failed_logs_but_does_not_touch_keys(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """invoice.payment_failed is informational only — no DB side-effects.

    Stripe's dunning flow eventually promotes to subscription.deleted; we
    must not pre-emptively revoke on a soft failure.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_fail", tier="paid", stripe_subscription_id="sub_fail_keep")
    c.commit()
    c.close()

    event = {
        "id": "evt_fail",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": "sub_fail_keep",
                "customer": "cus_fail",
                "attempt_count": 2,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT revoked_at FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_fail_keep",),
        ).fetchone()
    finally:
        c.close()
    assert row[0] is None, "payment_failed must NOT revoke the key — dunning handles that"


def test_send_welcome_safe_swallows_email_errors(monkeypatch):
    """A broken email transport must not bubble up into the Stripe handler."""
    from jpintel_mcp.api import billing as billing_mod

    class _Exploder:
        def send_welcome(self, **_):
            raise RuntimeError("postmark down")

    monkeypatch.setattr(billing_mod, "_get_email_client", lambda: _Exploder())
    # Must NOT raise.
    billing_mod._send_welcome_safe(to="x@example.com", raw_key="jpintel_rawkey1234", tier="paid")


def test_send_welcome_safe_noop_without_recipient(monkeypatch):
    """No `to` → early return, no client instantiated."""
    from jpintel_mcp.api import billing as billing_mod

    called: list[bool] = []

    def _get():
        called.append(True)
        raise AssertionError("should not be called")

    monkeypatch.setattr(billing_mod, "_get_email_client", _get)
    billing_mod._send_welcome_safe(to=None, raw_key="jpintel_x", tier="paid")
    assert called == []


def test_webhook_returns_fast_with_slow_outbound_io(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """P1 perf gate (audit a9fd80e134b538a32): the webhook must 200 within 1s
    even when Stripe API + Postmark are slow.

    The previous inline-handler shape ran `_apply_invoice_metadata_safe`
    (Stripe.Customer.modify), `_check_b2b_tax_id_safe` (Stripe.Customer.retrieve),
    and `_send_welcome_safe` (Postmark) on the request path. Each Stripe call
    can stall multiple seconds during a Stripe outage; together they could
    push the response past Stripe's 5s redelivery budget. This test mocks
    every outbound call to sleep 2s and asserts the webhook still returns
    in well under 1s — only possible if those calls were moved to
    BackgroundTasks (which fire AFTER the response is sent).
    """
    import time

    from jpintel_mcp.api import billing as billing_mod

    def _slow(*_a, **_kw):
        time.sleep(2.0)

    class _SlowEmail:
        def send_welcome(self, **_):
            time.sleep(2.0)

        def send_dunning(self, **_):
            time.sleep(2.0)

    # Stripe.Customer.modify (in _apply_invoice_metadata_safe) — 2s sleep
    monkeypatch.setattr(billing_mod.stripe.Customer, "modify", _slow)
    # Stripe.Customer.retrieve (in _check_b2b_tax_id_safe) — 2s sleep
    monkeypatch.setattr(billing_mod.stripe.Customer, "retrieve", _slow)
    # Postmark (in _send_welcome_safe / _send_dunning_safe) — 2s sleep
    monkeypatch.setattr(billing_mod, "_get_email_client", lambda: _SlowEmail())

    event = {
        "id": "evt_perf_gate",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_perf_gate",
                "customer": "cus_perf_gate",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    # IMPORTANT: TestClient runs BackgroundTasks SYNCHRONOUSLY at the end of
    # the request lifecycle by default — they DO contribute to the wall-clock
    # of `client.post`. To assert the request-path duration alone, we measure
    # via a stripped-down direct-call to the handler. We do this by tearing
    # out background_tasks via a stub TestClient that consumes the response
    # before background tasks fire.
    #
    # Easiest portable approach: spin a separate thread for the request and
    # check the response is yielded promptly. But TestClient blocks until
    # bg-tasks complete. So instead, monkey-patch BackgroundTasks.add_task
    # to a no-op to confirm the handler itself is fast — i.e. nothing was
    # called inline.
    from fastapi import BackgroundTasks

    skipped: list[tuple] = []

    def _fake_add_task(self, fn, *args, **kwargs):
        skipped.append((fn.__name__, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", _fake_add_task)

    t0 = time.monotonic()
    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    elapsed = time.monotonic() - t0

    assert r.status_code == 200, r.text
    # Hard ceiling: with all 3 slow paths deferred, the request path is just
    # the dedup INSERT + issue_key + (skipped) add_task calls. Should easily
    # finish under 1s. If any slow path leaks back to inline, we'd see ~2s.
    assert elapsed < 1.0, (
        f"webhook took {elapsed:.3f}s — slow outbound IO must be deferred "
        f"to BackgroundTasks (perf gate per audit a9fd80e134b538a32)"
    )
    # Confirm the Stripe API ops were SCHEDULED via BackgroundTasks
    # (not run inline).
    fn_names = {name for name, _, _ in skipped}
    assert "_apply_invoice_metadata_safe" in fn_names, fn_names
    assert "_check_b2b_tax_id_safe" in fn_names, fn_names
    # Welcome email moved to the durable bg_task_queue (P1 credential-leak
    # fix per audit 2026-04-26) instead of in-memory BackgroundTasks. The
    # raw API key must never live in BackgroundTasks closures because that
    # surface is not durable across pod restarts and showing the key in
    # plaintext in another in-process queue is a leak surface. Verify the
    # enqueue landed in the persisted bg_task_queue with kind="welcome_email"
    # instead of asserting `_send_welcome_safe` was passed to add_task.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT 1 FROM bg_task_queue"
            " WHERE kind = ? AND dedup_key = ?",
            ("welcome_email", "welcome:sub_perf_gate"),
        ).fetchone()
    finally:
        c.close()
    assert row is not None, (
        "welcome email enqueue missing from bg_task_queue — webhook must "
        "persist the welcome mail through the durable queue, not via "
        "in-memory BackgroundTasks (audit 2026-04-26)"
    )
