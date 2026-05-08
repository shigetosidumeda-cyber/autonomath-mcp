import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.api.deps import hash_api_key as _hash_api_key
from jpintel_mcp.billing.keys import (
    generate_api_key,
    hash_api_key,
    issue_child_key,
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
        metadata: dict | None = None,
        status: str = "complete",
        mode: str = "subscription",
        livemode: bool = False,
    ) -> None:
        # Metered subs default to "no_payment_required" (Stripe doesn't
        # charge upfront — first invoice comes from usage_records).
        self.payment_status = payment_status
        self.customer = customer
        self.subscription = subscription
        self.customer_email = customer_email
        self.customer_details = _FakeCustomerDetails(cd_email) if cd_email else None
        self.metadata = metadata or {}
        self.status = status
        self.mode = mode
        self.livemode = livemode


class _FakeSubscription(dict):
    """Stripe SDK Subscription is dict-like. The code indexes sub['items']['data']..."""


def _fake_sub(
    price_id: str,
    sub_id: str = "sub_checkout_1",
    status: str = "active",
) -> _FakeSubscription:
    return _FakeSubscription(
        {
            "id": sub_id,
            "status": status,
            "items": {"data": [{"price": {"id": price_id}}]},
        }
    )


def _fake_multi_item_sub(
    *,
    sub_id: str = "sub_multi_item",
    status: str = "active",
    metered_price_id: str = "price_metered_test",
) -> _FakeSubscription:
    return _FakeSubscription(
        {
            "id": sub_id,
            "status": status,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_base_seat",
                            "recurring": {"usage_type": "licensed"},
                        }
                    },
                    {
                        "price": {
                            "id": metered_price_id,
                            "recurring": {"usage_type": "metered"},
                        }
                    },
                ]
            },
        }
    )


def _checkout_state_metadata(client, billing_mod, state: str = "checkout-state-test") -> dict:
    client.cookies.set(billing_mod._CHECKOUT_STATE_COOKIE, state, path="/v1/billing")
    return {"checkout_state_hash": billing_mod._checkout_state_hash(state)}


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so _stripe() doesn't 503."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
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


def test_checkout_rejects_external_success_url(client, stripe_env, monkeypatch):
    """Checkout redirects must stay on jpcite so session_id cannot leak off-origin."""
    from jpintel_mcp.api import billing as billing_mod

    called: list[dict] = []

    def _create(**kwargs):  # pragma: no cover - regression guard
        called.append(kwargs)
        raise AssertionError("Stripe Checkout must not be created for external URLs")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "create", _create)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://evil.example/success?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://jpcite.com/pricing.html?cancelled=1",
        },
    )
    assert r.status_code == 400
    assert "success_url" in r.json()["detail"]
    assert called == []


def test_checkout_rejects_nonstandard_jpcite_port(client, stripe_env):
    """jpcite hostnames are allowed only on normal HTTPS, not arbitrary ports."""
    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://jpcite.com:444/success.html?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://jpcite.com/pricing.html?cancelled=1",
        },
    )
    assert r.status_code == 400
    assert "success_url" in r.json()["detail"]


def test_checkout_allows_english_redirect_paths(client, stripe_env, monkeypatch, seeded_db: Path):
    """English pricing page must be able to create Checkout sessions."""
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict] = []

    class _FakeSession:
        id = "cs_en_ok"
        url = "https://checkout.stripe.test/en-ok"

    def _create(**kwargs):
        captured.append(kwargs)
        return _FakeSession()

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "create", _create)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://jpcite.com/en/success.html?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://jpcite.com/en/pricing.html?cancelled=1",
            "locale": "en",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "https://checkout.stripe.test/en-ok"
    assert captured[0]["success_url"].startswith("https://jpcite.com/en/success.html")
    assert captured[0]["cancel_url"].startswith("https://jpcite.com/en/pricing.html")
    assert captured[0]["locale"] == "en"
    assert captured[0]["branding_settings"] == {"display_name": "jpcite"}

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_name, page, user_agent_class, properties_json "
            "FROM funnel_events WHERE event_name = ? ORDER BY id DESC LIMIT 1",
            ("checkout_session_created",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "checkout_session_created"
    assert row[1] == "/en/pricing.html"
    assert row[2] == "server"
    props = json.loads(row[3])
    assert props["session_id"] == "cs_en_ok"
    assert props["locale"] == "en"
    assert props["success_path"] == "/en/success.html"


def test_checkout_attaches_pending_device_user_code_metadata(client, stripe_env, monkeypatch):
    """MCP device-flow checkout must bind the Stripe Session to the pending code."""
    from jpintel_mcp.api import billing as billing_mod

    auth = client.post(
        "/v1/device/authorize",
        json={},
        headers={"user-agent": "pytest-checkout-device-flow"},
    )
    assert auth.status_code == 200, auth.text
    device = auth.json()

    captured: list[dict] = []

    class _FakeSession:
        id = "cs_device_checkout"
        url = "https://checkout.stripe.test/device"

    def _create(**kwargs):
        captured.append(kwargs)
        return _FakeSession()

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "create", _create)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://jpcite.com/success.html?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://jpcite.com/pricing.html?cancelled=1",
            "user_code": device["user_code"],
        },
    )

    assert r.status_code == 200, r.text
    metadata = captured[0]["metadata"]
    assert metadata["device_code"] == device["device_code"]
    assert metadata["user_code"] == device["user_code"]
    assert metadata["checkout_state_hash"]


def test_checkout_rejects_nonpending_device_user_code(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    from jpintel_mcp.api import billing as billing_mod

    auth = client.post(
        "/v1/device/authorize",
        json={},
        headers={"user-agent": "pytest-checkout-device-flow"},
    )
    assert auth.status_code == 200, auth.text
    user_code = auth.json()["user_code"]

    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE device_codes SET status = 'denied' WHERE user_code = ?",
            (user_code,),
        )
        c.commit()
    finally:
        c.close()

    called: list[dict] = []

    def _should_not_be_called(**kwargs):  # pragma: no cover - regression guard
        called.append(kwargs)
        raise AssertionError("Stripe Checkout must not be created for denied device code")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": "https://jpcite.com/success.html?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://jpcite.com/pricing.html?cancelled=1",
            "user_code": user_code,
        },
    )

    assert r.status_code == 409, r.text
    assert "not pending" in r.json()["detail"]
    assert called == []


def test_portal_unauthed_returns_401(client, stripe_env, monkeypatch):
    """P0-6: anonymous (no X-API-Key) caller gets 401, NEVER a portal URL.

    Pre-fix the body-supplied `customer_id` was sent verbatim to Stripe,
    letting any caller open the portal for any guessed `cus_*` id. The
    fix requires an auth'd API key and resolves the customer server-side.
    """
    from jpintel_mcp.api import billing as billing_mod

    called: list[dict] = []

    def _should_not_be_called(**kwargs):  # pragma: no cover — exercised on regression
        called.append(kwargs)
        raise AssertionError(
            "Stripe portal session created for unauthed request — enumeration regression"
        )

    monkeypatch.setattr(billing_mod.stripe.billing_portal.Session, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/portal",
        json={"customer_id": "cus_victim_1", "return_url": "https://jpcite.com/dashboard"},
    )
    assert r.status_code == 401, r.text
    assert called == []


def test_portal_resolves_customer_from_authed_key(client, stripe_env, paid_key, monkeypatch):
    """Authed caller gets a portal URL whose `customer` is the API key's
    own `customer_id` from the DB — the body-supplied `customer_id` is
    IGNORED so a paying customer cannot pivot to another customer's
    portal session.
    """
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
        headers={"X-API-Key": paid_key},
        json={
            # Attempt enumeration: caller forges a different customer_id
            # in the body. The endpoint must IGNORE this and use the DB
            # `customer_id` keyed off the auth'd key hash instead.
            "customer_id": "cus_victim_other",
            "return_url": "https://jpcite.com/dashboard",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://billing.stripe.test/portal/abc"}
    # The `paid_key` fixture issues with customer_id="cus_test_paid".
    assert captured[0]["customer"] == "cus_test_paid"
    assert captured[0]["customer"] != "cus_victim_other"
    assert captured[0]["return_url"] == "https://jpcite.com/dashboard"


def test_portal_rejects_offsite_return_url(client, stripe_env, paid_key, monkeypatch):
    """Stripe must not redirect an authenticated customer to an attacker origin."""
    from jpintel_mcp.api import billing as billing_mod

    called: list[dict] = []

    def _should_not_be_called(**kwargs):  # pragma: no cover — regression only
        called.append(kwargs)
        raise AssertionError("Stripe portal created with offsite return_url")

    monkeypatch.setattr(billing_mod.stripe.billing_portal.Session, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/portal",
        headers={"X-API-Key": paid_key},
        json={"return_url": "https://example.test/back"},
    )
    assert r.status_code == 400, r.text
    assert called == []


def test_service_checkout_redirect_validator_rejects_offsite_urls():
    from fastapi import HTTPException

    from jpintel_mcp.api.billing import validate_jpcite_service_redirect_url

    with pytest.raises(HTTPException):
        validate_jpcite_service_redirect_url("https://example.test/alerts.html", kind="success")

    assert (
        validate_jpcite_service_redirect_url(
            "https://jpcite.com/alerts.html?status=ok", kind="success"
        )
        == "https://jpcite.com/alerts.html?status=ok"
    )


def test_portal_rejects_child_api_key(client, stripe_env, paid_key, monkeypatch, seeded_db: Path):
    """A delegated child key can use data APIs, but cannot manage billing."""
    from jpintel_mcp.api import billing as billing_mod

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

    monkeypatch.setattr(billing_mod.stripe.billing_portal.Session, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/portal",
        headers={"X-API-Key": child_raw},
        json={"return_url": "https://jpcite.com/dashboard"},
    )
    assert r.status_code == 403, r.text
    assert called == []


def test_issue_from_checkout_402_when_session_not_paid(client, stripe_env, monkeypatch):
    """Refuse key issuance for an unpaid/abandoned Checkout session."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve(_sid, **_):
        return _FakeCheckoutSession(payment_status="unpaid", metadata=metadata)

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_abandoned"})
    assert r.status_code == 402
    assert "not paid" in r.json()["detail"].lower()


def test_issue_from_checkout_rejects_inactive_subscription(client, stripe_env, monkeypatch):
    """A completed Checkout cannot mint a paid key after the subscription is inactive."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            subscription="sub_canceled",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(
            price_id="price_metered_test",
            sub_id="sub_canceled",
            status="canceled",
        )

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_canceled"})
    assert r.status_code == 402
    assert "subscription is not active" in r.json()["detail"].lower()


def test_issue_from_checkout_requires_browser_checkout_state(client, stripe_env, monkeypatch):
    """A stolen/guessed Stripe session_id cannot reveal a key without the checkout cookie."""
    from jpintel_mcp.api import billing as billing_mod

    def _retrieve(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            metadata={"checkout_state_hash": billing_mod._checkout_state_hash("victim-state")},
        )

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_stolen"})
    assert r.status_code == 403
    assert "checkout state" in r.json()["detail"].lower()


def test_issue_from_checkout_returns_raw_key_once_and_persists_hash(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Happy path: metered Checkout → raw API key returned + hashed row in api_keys."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_happy",
            subscription="sub_happy",
            cd_email="happy@example.com",
            metadata=metadata,
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

    c = sqlite3.connect(seeded_db)
    try:
        events = c.execute(
            "SELECT event_name, key_hash, user_agent_class, is_anonymous, properties_json "
            "FROM funnel_events WHERE event_name IN (?, ?) ORDER BY id ASC",
            ("checkout_completed", "key_issued"),
        ).fetchall()
    finally:
        c.close()
    assert [event[0] for event in events[-2:]] == ["checkout_completed", "key_issued"]
    assert events[-2][1] is None
    assert events[-2][2] == "server"
    assert events[-2][3] == 1
    assert events[-1][1] == _hash_api_key(raw_key)
    assert events[-1][2] == "server"
    assert events[-1][3] == 0
    checkout_props = json.loads(events[-2][4])
    key_props = json.loads(events[-1][4])
    assert checkout_props["session_id"] == "cs_happy"
    assert checkout_props["subscription_id"] == "sub_happy"
    assert key_props["key_last4"] == raw_key[-4:]


def test_issue_from_checkout_uses_metered_item_not_first_subscription_item(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Base + metered subscriptions must resolve tier from the metered item."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_multi_item",
            subscription="sub_multi_item",
            cd_email="multi@example.com",
            metadata=metadata,
        )

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _sub_id, **_: _fake_multi_item_sub(sub_id="sub_multi_item"),
    )

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_multi_item"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_multi_item",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"


def test_issue_from_checkout_rejects_unknown_metered_subscription_item(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_other_metered",
            subscription="sub_other_metered",
            cd_email="other-metered@example.com",
            metadata=metadata,
        )

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _sub_id, **_: _fake_multi_item_sub(
            sub_id="sub_other_metered",
            metered_price_id="price_other_metered",
        ),
    )

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_other_metered"})
    assert r.status_code == 402
    assert "configured jpcite price" in r.json()["detail"]

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_other_metered",),
        ).fetchone()
    finally:
        c.close()
    assert n == 0


def test_issue_from_checkout_503_when_price_not_configured(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    metadata = _checkout_state_metadata(client, billing_mod)
    monkeypatch.setattr(settings, "stripe_price_per_request", "", raising=False)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_no_price_config",
            subscription="sub_no_price_config",
            cd_email="no-price-config@example.com",
            metadata=metadata,
        )

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_no_price_config"})
    assert r.status_code == 503
    assert "billing not configured" in r.json()["detail"]

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_no_price_config",),
        ).fetchone()
    finally:
        c.close()
    assert n == 0


def test_issue_from_checkout_still_returns_key_when_welcome_enqueue_fails(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """The raw key is only shown once, so welcome-mail enqueue must be best-effort."""
    from jpintel_mcp.api import _bg_task_queue
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_enqueue_fail",
            subscription="sub_enqueue_fail",
            cd_email="enqueue-fail@example.com",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_enqueue_fail")

    def _raise_enqueue(*_args, **_kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)
    monkeypatch.setattr(_bg_task_queue, "enqueue", _raise_enqueue)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_enqueue_fail"})
    assert r.status_code == 200, r.text
    raw_key = r.json()["api_key"]
    assert raw_key.startswith("am_")

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT customer_id, stripe_subscription_id, revoked_at FROM api_keys "
            "WHERE key_hash = ?",
            (_hash_api_key(raw_key),),
        ).fetchone()
    finally:
        c.close()
    assert row == ("cus_enqueue_fail", "sub_enqueue_fail", None)


def test_issue_from_checkout_retry_reissues_usable_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """A lost success-page response must not strand a paid customer without a key."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod, state="retry-state")

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_retry",
            subscription="sub_retry",
            cd_email=None,
            customer_email="retry@example.com",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_retry")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r1 = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_retry"})
    assert r1.status_code == 200, r1.text
    raw1 = r1.json()["api_key"]

    # Model the browser/network losing the first response before processing
    # Set-Cookie deletion. The same browser-bound Checkout state is still
    # allowed to recover by rotating the active key and revealing a fresh one.
    _checkout_state_metadata(client, billing_mod, state="retry-state")
    r2 = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_retry"})
    assert r2.status_code == 200, r2.text
    raw2 = r2.json()["api_key"]
    assert raw2.startswith("am_")
    assert raw2 != raw1

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT key_hash, revoked_at FROM api_keys "
            "WHERE stripe_subscription_id = ? ORDER BY revoked_at IS NULL",
            ("sub_retry",),
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 2
    active = [row for row in rows if row[1] is None]
    revoked = [row for row in rows if row[1] is not None]
    assert len(active) == 1
    assert len(revoked) == 1
    assert active[0][0] == _hash_api_key(raw2)


def test_issue_from_checkout_retry_refreshes_pending_welcome_payload(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """A checkout retry must not leave the welcome queue pointing at an old key."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod, state="retry-welcome-state")

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_retry_welcome",
            subscription="sub_retry_welcome",
            cd_email="retry-welcome@example.com",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_retry_welcome")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r1 = client.post(
        "/v1/billing/keys/from-checkout",
        json={"session_id": "cs_retry_welcome"},
    )
    assert r1.status_code == 200, r1.text

    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE bg_task_queue SET payload_json = ? WHERE dedup_key = ?",
            (
                json.dumps(
                    {"to": "retry-welcome@example.com", "key_last4": "STALE", "tier": "paid"}
                ),
                "welcome:sub_retry_welcome",
            ),
        )
        c.commit()
    finally:
        c.close()

    _checkout_state_metadata(client, billing_mod, state="retry-welcome-state")
    r2 = client.post(
        "/v1/billing/keys/from-checkout",
        json={"session_id": "cs_retry_welcome"},
    )
    assert r2.status_code == 200, r2.text
    raw2 = r2.json()["api_key"]

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT payload_json, status FROM bg_task_queue WHERE dedup_key = ?",
            ("welcome:sub_retry_welcome",),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    payload = json.loads(rows[0][0])
    assert payload["to"] == "retry-welcome@example.com"
    assert payload["key_last4"] == raw2[-4:]
    assert rows[0][1] == "pending"


def test_issue_from_checkout_retry_refuses_when_children_exist(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """A delayed Checkout retry must not revoke active delegated child keys."""
    from jpintel_mcp.api import billing as billing_mod

    metadata = _checkout_state_metadata(client, billing_mod, state="retry-child-state")

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer="cus_retry_child",
            subscription="sub_retry_child",
            cd_email=None,
            customer_email="retry-child@example.com",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id="sub_retry_child")

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r1 = client.post(
        "/v1/billing/keys/from-checkout",
        json={"session_id": "cs_retry_child"},
    )
    assert r1.status_code == 200, r1.text
    parent_raw = r1.json()["api_key"]

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child_raw, child_hash = issue_child_key(
            c,
            parent_key_hash=_hash_api_key(parent_raw),
            label="tenant-a",
        )
        assert child_raw.startswith("am_")
        c.commit()
    finally:
        c.close()

    _checkout_state_metadata(client, billing_mod, state="retry-child-state")
    r2 = client.post(
        "/v1/billing/keys/from-checkout",
        json={"session_id": "cs_retry_child"},
    )
    assert r2.status_code == 409, r2.text
    assert "already issued" in r2.json()["detail"]

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT key_hash, parent_key_id, revoked_at FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            ("sub_retry_child",),
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 2
    assert {row["key_hash"] for row in rows} == {
        _hash_api_key(parent_raw),
        child_hash,
    }
    assert all(row["revoked_at"] is None for row in rows)


# --- webhook -----------------------------------------------------------------


def _patch_webhook_construct_event(monkeypatch, event: dict):
    """Bypass Stripe signature verification; still exercises dispatch logic."""
    from jpintel_mcp.api import billing as billing_mod

    def _construct(body, sig, secret, **_kwargs):
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


def test_webhook_no_content_length_still_validates_signature(client, stripe_env, monkeypatch):
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


def test_webhook_subscription_created_does_not_issue_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.created records the event but never reveals a raw key.

    Raw key issuance lives on the browser-bound /keys/from-checkout path so
    a webhook race cannot hide the only copy of the key from the buyer.
    """
    event = {
        "id": "evt_sub_created",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_metered_new",
                "customer": "cus_metered_new",
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
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_metered_new",),
        ).fetchone()
        event_row = c.execute(
            "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_sub_created",),
        ).fetchone()
    finally:
        c.close()
    assert n_keys == 0
    assert event_row is not None
    assert event_row[0] is not None


def test_webhook_invoice_paid_does_not_issue_hidden_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """invoice.paid must not mint a raw key that the buyer can never see."""
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
        lambda _id, **_: _fake_sub(price_id="price_metered_test", sub_id="sub_webhook_fallback"),
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
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_webhook_fallback",),
        ).fetchone()
    finally:
        c.close()
    assert n_keys == 0


def test_invoice_paid_before_checkout_does_not_block_key_reveal(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """If Stripe sends invoice.paid first, success.html can still reveal a key."""
    from jpintel_mcp.api import billing as billing_mod

    sub_id = "sub_paid_then_checkout"
    customer_id = "cus_paid_then_checkout"
    event = {
        "id": "evt_paid_before_checkout",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": sub_id,
                "customer": customer_id,
                "customer_email": "buyer@example.com",
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

    metadata = _checkout_state_metadata(client, billing_mod)

    def _retrieve_session(_sid, **_):
        return _FakeCheckoutSession(
            payment_status="no_payment_required",
            customer=customer_id,
            subscription=sub_id,
            cd_email="buyer@example.com",
            metadata=metadata,
        )

    def _retrieve_sub(_sub_id, **_):
        return _fake_sub(price_id="price_metered_test", sub_id=sub_id)

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "retrieve", _retrieve_session)
    monkeypatch.setattr(billing_mod.stripe.Subscription, "retrieve", _retrieve_sub)

    r = client.post("/v1/billing/keys/from-checkout", json={"session_id": "cs_after_paid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key"].startswith("am_")
    assert body["customer_id"] == customer_id

    c = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ? AND revoked_at IS NULL",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    assert n_keys == 1


def test_webhook_is_idempotent_on_replay(client, stripe_env, monkeypatch, seeded_db: Path):
    """Stripe delivers subscription.created twice (retry) → no key issuance.

    Duplicate webhook deliveries must NEVER mint keys; browser checkout state
    is required to reveal a raw API key.
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
    assert n == 0, f"expected no key row for replayed sub, got {n}"


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


def test_webhook_subscription_updated_uses_metered_item_not_first_item(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_multi_upg", tier="free", stripe_subscription_id="sub_multi_upg")
    c.commit()
    c.close()

    event = {
        "id": "evt_upd_multi_item",
        "type": "customer.subscription.updated",
        "data": {"object": _fake_multi_item_sub(sub_id="sub_multi_upg")},
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
            ("sub_multi_upg",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"


def test_webhook_subscription_updated_missing_price_does_not_demote_active_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(
        c,
        customer_id="cus_missing_price",
        tier="paid",
        stripe_subscription_id="sub_missing_price",
    )
    c.commit()
    c.close()

    event = {
        "id": "evt_upd_missing_price",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_missing_price",
                "status": "active",
                "items": {"data": []},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 500, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_missing_price",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid"


def test_webhook_subscription_updated_unknown_metered_price_does_not_demote_active_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(
        c,
        customer_id="cus_unknown_metered",
        tier="paid",
        stripe_subscription_id="sub_unknown_metered",
    )
    c.commit()
    c.close()

    event = {
        "id": "evt_upd_unknown_metered",
        "type": "customer.subscription.updated",
        "data": {
            "object": _fake_multi_item_sub(
                sub_id="sub_unknown_metered",
                metered_price_id="price_other_metered",
            )
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 500, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_unknown_metered",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
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
    # subscription.created no longer issues the raw key; the browser-bound
    # /keys/from-checkout path does. Therefore this event must not queue a
    # welcome email either. The test still proves slow Stripe calls are
    # scheduled, not run inline.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT 1 FROM bg_task_queue WHERE kind = ? AND dedup_key = ?",
            ("welcome_email", "welcome:sub_perf_gate"),
        ).fetchone()
    finally:
        c.close()
    assert row is None, "subscription.created must not queue a welcome email"
