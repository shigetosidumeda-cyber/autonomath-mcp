"""Webhook idempotency / livemode / serialization tests (P0 launch blockers).

Covers the three webhook fixes that landed alongside migration
053_stripe_webhook_events:

* Fix 1 — event-level dedup table. Same event_id, replayed → side-effects
  do NOT run twice. Distinct from the existing subscription-level dedup
  test in test_billing.py (which exercises only the api_keys row count).
* Fix 2 — livemode mismatch guard. event["livemode"]=True with
  settings.env != "prod" must be ignored with status=200 (so Stripe stops
  retrying the misrouted event).
* Fix 3 — BEGIN IMMEDIATE serialization. Concurrent invoice.paid +
  subscription.updated for the same customer must converge to the
  documented final state, not corrupt rows half-way through.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key


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


def _patch_webhook_construct_event(monkeypatch, event: dict):
    """Bypass Stripe signature verification; still exercises dispatch logic."""
    from jpintel_mcp.api import billing as billing_mod

    def _construct(_body, _sig, _secret):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


# ---------------------------------------------------------------------------
# Fix 1 — event-level dedup
# ---------------------------------------------------------------------------


def test_event_dedup_records_event_id_on_first_delivery(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """A fresh event is recorded in stripe_webhook_events with processed_at set."""
    event = {
        "id": "evt_dedup_first",
        "type": "customer.subscription.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_dedup_first",
                "customer": "cus_dedup_first",
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
    assert r.json() == {"status": "received"}

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_id, event_type, livemode, processed_at "
            "FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_dedup_first",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "evt_dedup_first"
    assert row[1] == "customer.subscription.created"
    assert row[2] == 0  # livemode False stored as 0
    assert row[3] is not None  # processed_at filled


def test_duplicate_event_id_returns_200_and_does_not_double_process(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Replaying the same event_id 3x => exactly 1 stripe_webhook_events row,
    exactly 1 api_keys row, and the duplicate responses say 'duplicate_ignored'."""
    event = {
        "id": "evt_dedup_replay",
        "type": "customer.subscription.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_dedup_replay",
                "customer": "cus_dedup_replay",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r1 = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"status": "received"}

    for _ in range(2):
        r = client.post(
            "/v1/billing/webhook",
            content=json.dumps(event).encode("utf-8"),
            headers={"stripe-signature": "t=1,v1=xx"},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "duplicate_ignored"}

    c = sqlite3.connect(seeded_db)
    try:
        (n_events,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_dedup_replay",),
        ).fetchone()
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_dedup_replay",),
        ).fetchone()
    finally:
        c.close()
    assert n_events == 1, "event_id row must be unique"
    assert n_keys == 1, "key must NOT be re-issued on duplicate event"


def test_duplicate_event_does_not_re_send_welcome_email(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """The welcome-email side-effect is the highest-impact dedup target —
    replaying must not double-mail the customer."""
    from jpintel_mcp.api import billing as billing_mod

    sent: list[dict] = []

    class _CountingClient:
        def send_welcome(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(billing_mod, "_get_email_client", lambda: _CountingClient())

    event = {
        "id": "evt_dedup_email",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "subscription": "sub_dedup_email",
                "customer": "cus_dedup_email",
                "customer_email": "dedup@example.com",
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)
    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _id, **_: {"id": "sub_dedup_email", "items": {"data": [{"price": {"id": "price_metered_test"}}]}},
    )

    for _ in range(3):
        r = client.post(
            "/v1/billing/webhook",
            content=json.dumps(event).encode("utf-8"),
            headers={"stripe-signature": "t=1,v1=xx"},
        )
        assert r.status_code == 200, r.text

    assert len(sent) == 1, f"welcome email should fire once, fired {len(sent)} times"


# ---------------------------------------------------------------------------
# Fix 2 — livemode mismatch
# ---------------------------------------------------------------------------


def test_livemode_mismatch_in_dev_env_ignores_live_event(
    client, stripe_env, monkeypatch, seeded_db: Path, caplog
):
    """settings.env == 'dev' (default) + livemode=True => 200 + ignored.

    A misrouted live event must NOT be processed in a non-prod environment;
    we return 200 so Stripe stops retrying it (a live event will never
    become valid against a dev/test deployment).
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "env", "dev", raising=False)

    event = {
        "id": "evt_livemode_mismatch",
        "type": "customer.subscription.created",
        "livemode": True,  # routed from PROD by mistake
        "data": {
            "object": {
                "id": "sub_should_not_be_created",
                "customer": "cus_misrouted",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    import logging
    with caplog.at_level(logging.ERROR, logger="jpintel.billing"):
        r = client.post(
            "/v1/billing/webhook",
            content=json.dumps(event).encode("utf-8"),
            headers={"stripe-signature": "t=1,v1=xx"},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "livemode_mismatch_ignored"}

    # Side-effect must NOT have happened: no key, no dedup row.
    c = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_should_not_be_created",),
        ).fetchone()
        (n_events,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_livemode_mismatch",),
        ).fetchone()
    finally:
        c.close()
    assert n_keys == 0
    assert n_events == 0  # the dedup INSERT runs AFTER the livemode check

    # Error log emitted with event_id for triage.
    assert any(
        "livemode_mismatch" in rec.message and "evt_livemode_mismatch" in rec.message
        for rec in caplog.records
    ), [r.message for r in caplog.records]


def test_livemode_match_in_dev_env_processes_normally(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """settings.env == 'dev' + livemode=False => normal dispatch."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "env", "dev", raising=False)

    event = {
        "id": "evt_livemode_match",
        "type": "customer.subscription.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_livemode_match",
                "customer": "cus_livemode_match",
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
    assert r.json() == {"status": "received"}


def test_livemode_mismatch_in_prod_env_ignores_test_event(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """settings.env == 'prod' + livemode=False (testmode event) => ignored.

    The reverse direction: a Stripe TEST event firing into the production
    webhook URL must also be ignored (someone left the wrong endpoint
    configured in test-mode Dashboard).
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "env", "prod", raising=False)

    event = {
        "id": "evt_test_to_prod",
        "type": "customer.subscription.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_test_to_prod",
                "customer": "cus_test_to_prod",
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
    assert r.json() == {"status": "livemode_mismatch_ignored"}


# ---------------------------------------------------------------------------
# Fix 3 — BEGIN IMMEDIATE serialization
# ---------------------------------------------------------------------------


def test_concurrent_invoice_paid_and_subscription_updated_converge(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Two webhook deliveries hitting the SAME customer at once must converge.

    Scenario: Stripe delivers `invoice.paid` and `customer.subscription.updated`
    almost simultaneously. Both write to api_keys (tier flip + status cache).
    With BEGIN IMMEDIATE the second writer waits on the SQLite RESERVED lock
    rather than racing.

    We pre-issue a key (subscription already exists), then fire both events
    concurrently and assert the final api_keys row reflects BOTH writes.
    """
    from jpintel_mcp.api import billing as billing_mod

    # Pre-existing subscription.
    c = sqlite3.connect(seeded_db)
    issue_key(
        c,
        customer_id="cus_concurrent",
        tier="free",  # demoted by an earlier payment_failed (hypothetical)
        stripe_subscription_id="sub_concurrent",
    )
    c.commit()
    c.close()

    paid_event = {
        "id": "evt_concurrent_paid",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "subscription": "sub_concurrent",
                "customer": "cus_concurrent",
                "customer_email": "concurrent@example.com",
            }
        },
    }
    updated_event = {
        "id": "evt_concurrent_updated",
        "type": "customer.subscription.updated",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_concurrent",
                "status": "active",
                "current_period_end": 1800000000,
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }

    # Stripe.Subscription.retrieve is called by the invoice.paid handler.
    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _id, **_: {
            "id": "sub_concurrent",
            "status": "active",
            "current_period_end": 1800000000,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_metered_test"}}]},
        },
    )

    # The webhook handler dispatches based on `event["type"]` after Stripe
    # construct_event is patched per-thread. We swap construct_event to a
    # lookup keyed by signature header so both threads can run independently
    # against the same TestClient.
    def _construct(body, sig, secret):
        # `sig` is unique per request (we set it from each thread). Use the
        # body itself to pick the event back; both events serialize unique
        # JSON so the body is the natural lookup key.
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        if "evt_concurrent_paid" in text:
            return paid_event
        if "evt_concurrent_updated" in text:
            return updated_event
        raise AssertionError(f"unexpected webhook body: {text!r}")

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)

    results: dict[str, int] = {}

    def _post(name: str, payload: dict) -> None:
        r = client.post(
            "/v1/billing/webhook",
            content=json.dumps(payload).encode("utf-8"),
            headers={"stripe-signature": f"t=1,v1={name}"},
        )
        results[name] = r.status_code

    t1 = threading.Thread(target=_post, args=("paid", paid_event))
    t2 = threading.Thread(target=_post, args=("updated", updated_event))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert results == {"paid": 200, "updated": 200}, results

    # Final state: tier == 'paid' (both handlers set it; either ordering
    # converges to 'paid'), status cache reflects the active subscription.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier, stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            ("sub_concurrent",),
        ).fetchone()
        (n_events,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events "
            "WHERE event_id IN (?, ?)",
            ("evt_concurrent_paid", "evt_concurrent_updated"),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "paid", f"expected tier=paid after both events, got {row[0]}"
    # status cache may end up 'active' (from .updated) — invoice.paid does
    # a best-effort live-retrieve which we patched to return 'active' too.
    assert row[1] == "active"
    assert n_events == 2, "both events recorded in dedup table"
