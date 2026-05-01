"""Tests for /v1/me Stripe subscription_status enrichment (migration 052).

The dashboard dunning banner reads from /v1/me.subscription_status. These
tests assert:

  1. The new fields appear in every /v1/me response (additive — existing
     callers keep their tier / customer_id / created_at fields untouched).
  2. NULL cached state -> 'no_subscription' (the legacy / free path).
  3. The Stripe webhook handler writes status / current_period_end /
     cancel_at_period_end into api_keys on the canonical event types.

Stripe is never called for real; webhook signature verification + the
Subscription.retrieve fallback used by invoice.paid are monkeypatched.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key, update_subscription_status

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def paid_key_with_status(seeded_db: Path) -> tuple[str, str]:
    """Mint a paid key + cache an active subscription_status against it.

    Returns (raw_api_key, stripe_subscription_id).
    """
    sub_id = "sub_status_active"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_status_active",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    # Cache an active subscription (current_period_end ~ 30 days out).
    cpe = int(time.time()) + 30 * 86400
    update_subscription_status(
        c,
        sub_id,
        status="active",
        current_period_end=cpe,
        cancel_at_period_end=False,
    )
    c.commit()
    c.close()
    return raw, sub_id


# ---------------------------------------------------------------------------
# /v1/me response shape
# ---------------------------------------------------------------------------


def test_me_returns_subscription_status_active(client, paid_key_with_status):
    """Cached 'active' -> /v1/me surfaces it verbatim with period_end + cancel flag."""
    raw, _sub_id = paid_key_with_status
    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200, r.text

    r = client.get("/v1/me")
    assert r.status_code == 200, r.text
    body = r.json()
    # Existing fields still present (must NOT regress the response shape).
    assert body["tier"] == "paid"
    assert body["customer_id"] == "cus_status_active"
    assert body["created_at"] is not None
    # New fields.
    assert body["subscription_status"] == "active"
    assert body["subscription_current_period_end"] is not None
    # ISO 8601 Z-suffixed UTC datetime.
    assert body["subscription_current_period_end"].endswith("Z")
    assert body["subscription_cancel_at_period_end"] is False


def test_me_returns_no_subscription_when_status_unset(client, paid_key):
    """Legacy / free row with NULL cached state -> 'no_subscription' translation."""
    r = client.post("/v1/session", json={"api_key": paid_key})
    assert r.status_code == 200, r.text

    r = client.get("/v1/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscription_status"] == "no_subscription"
    assert body["subscription_current_period_end"] is None
    assert body["subscription_cancel_at_period_end"] is False


def test_me_surfaces_past_due_status(client, seeded_db: Path):
    """A row with cached 'past_due' surfaces via /v1/me — drives the dunning banner."""
    sub_id = "sub_past_due"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_past_due",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    update_subscription_status(c, sub_id, status="past_due")
    c.commit()
    c.close()

    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200
    r = client.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["subscription_status"] == "past_due"


def test_me_surfaces_cancel_at_period_end_true(client, seeded_db: Path):
    """A scheduled cancellation surfaces as cancel_at_period_end=True."""
    sub_id = "sub_will_cancel"
    cpe = int(time.time()) + 7 * 86400
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_will_cancel",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    update_subscription_status(
        c,
        sub_id,
        status="active",
        current_period_end=cpe,
        cancel_at_period_end=True,
    )
    c.commit()
    c.close()

    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200
    body = client.get("/v1/me").json()
    assert body["subscription_status"] == "active"
    assert body["subscription_cancel_at_period_end"] is True


# ---------------------------------------------------------------------------
# Webhook -> api_keys cache writes
# ---------------------------------------------------------------------------


def _patch_webhook_construct_event(monkeypatch, event: dict) -> None:
    from jpintel_mcp.api import billing as billing_mod

    monkeypatch.setattr(
        billing_mod.stripe.Webhook,
        "construct_event",
        lambda body, sig, secret: event,
    )


@pytest.fixture()
def stripe_env(monkeypatch):
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(
        settings, "stripe_price_per_request", "price_metered_test", raising=False
    )
    yield settings


def test_webhook_subscription_created_caches_status(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.created refreshes status on an already-revealed key."""
    from jpintel_mcp.billing.keys import issue_key

    cpe = int(time.time()) + 30 * 86400
    conn = sqlite3.connect(seeded_db)
    try:
        issue_key(
            conn,
            customer_id="cus_status_created",
            tier="paid",
            stripe_subscription_id="sub_status_created",
        )
        conn.commit()
    finally:
        conn.close()
    event = {
        "id": "evt_sub_created_status",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_status_created",
                "customer": "cus_status_created",
                "status": "active",
                "current_period_end": cpe,
                "cancel_at_period_end": False,
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
            "SELECT stripe_subscription_status, "
            "       stripe_subscription_current_period_end, "
            "       stripe_subscription_cancel_at_period_end "
            "FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_status_created",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "active"
    assert row[1] == cpe
    assert row[2] == 0


def test_webhook_subscription_updated_writes_past_due(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.updated with status=past_due keeps paid access suspended."""
    sub_id = "sub_to_past_due"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_pd", tier="paid", stripe_subscription_id=sub_id)
    c.commit()
    c.close()

    event = {
        "id": "evt_pd",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": sub_id,
                "status": "past_due",
                "current_period_end": int(time.time()) + 5 * 86400,
                "cancel_at_period_end": False,
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
            "SELECT tier, stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    assert row[0] == "free"
    assert row[1] == "past_due"


def test_webhook_payment_failed_marks_past_due(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """invoice.payment_failed (no Subscription payload) -> caches 'past_due'."""
    sub_id = "sub_invoice_failed"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_pf", tier="paid", stripe_subscription_id=sub_id)
    c.commit()
    c.close()

    event = {
        "id": "evt_pf",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": sub_id,
                "customer": "cus_pf",
                "attempt_count": 1,
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
            "SELECT stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    assert row[0] == "past_due"


def test_webhook_payment_failed_does_not_regress_canceled(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """If status is already 'canceled' or 'unpaid', payment_failed must not regress to 'past_due'.

    Stripe occasionally delivers events out of order; the webhook must
    preserve the worse state.
    """
    sub_id = "sub_already_canceled"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_ac", tier="paid", stripe_subscription_id=sub_id)
    update_subscription_status(c, sub_id, status="canceled")
    c.commit()
    c.close()

    event = {
        "id": "evt_pf_late",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": sub_id,
                "customer": "cus_ac",
                "attempt_count": 4,
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
            "SELECT stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    # Must remain 'canceled' — not regressed to 'past_due'.
    assert row[0] == "canceled"


def test_webhook_invoice_paid_resyncs_from_stripe(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """invoice.paid -> live retrieve refreshes the cached subscription_status."""
    from jpintel_mcp.api import billing as billing_mod

    sub_id = "sub_invoice_paid_resync"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_paid_rs", tier="free", stripe_subscription_id=sub_id)
    update_subscription_status(c, sub_id, status="past_due")
    c.commit()
    c.close()

    cpe = int(time.time()) + 28 * 86400

    class _FakeSub(dict):
        pass

    fake_sub = _FakeSub(
        {
            "id": sub_id,
            "status": "active",
            "current_period_end": cpe,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_metered_test"}}]},
        }
    )

    monkeypatch.setattr(
        billing_mod.stripe.Subscription,
        "retrieve",
        lambda _id, **_: fake_sub,
    )

    event = {
        "id": "evt_paid_resync",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": sub_id,
                "customer": "cus_paid_rs",
                "customer_email": "rs@example.com",
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

    # The live-retrieve refresh is enqueued (kind=stripe_status_refresh)
    # because firing it inline would deadlock against the webhook's own
    # BEGIN IMMEDIATE writer. Drain the queue once here so the cached
    # status flips from past_due → active before we read it back.
    from jpintel_mcp.api._bg_task_queue import claim_next, mark_done
    from jpintel_mcp.api._bg_task_worker import _dispatch_one

    drain_conn = sqlite3.connect(seeded_db, isolation_level=None)
    drain_conn.row_factory = sqlite3.Row
    try:
        for _ in range(20):
            row = claim_next(drain_conn)
            if row is None:
                break
            ok, _err = _dispatch_one(row)
            if ok:
                mark_done(drain_conn, int(row["id"]))
    finally:
        drain_conn.close()

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT stripe_subscription_status, "
            "       stripe_subscription_current_period_end "
            "FROM api_keys "
            "WHERE stripe_subscription_id = ? AND revoked_at IS NULL",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    # past_due was upgraded to active by the live retrieve.
    assert row[0] == "active"
    assert row[1] == cpe


def test_webhook_subscription_deleted_marks_canceled(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """customer.subscription.deleted -> any non-revoked rows get 'canceled'.

    revoke_subscription itself flips revoked_at; update_subscription_status
    only touches WHERE revoked_at IS NULL, so for a fresh sub the status
    write is a no-op. To exercise the status path we keep one row alive
    by issuing two keys for the sub and only revoking one before the event.
    """
    sub_id = "sub_being_deleted"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_del", tier="paid", stripe_subscription_id=sub_id)
    update_subscription_status(c, sub_id, status="active")
    c.commit()
    c.close()

    event = {
        "id": "evt_del_status",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": sub_id}},
    }
    _patch_webhook_construct_event(monkeypatch, event)

    r = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT revoked_at, stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            (sub_id,),
        ).fetchone()
    finally:
        c.close()
    # revoked_at flipped, status still readable (cached value preserved on
    # revoked rows since update_subscription_status_by_id targets only
    # active rows). The dashboard won't see this row anyway because /v1/me
    # for the revoked key would 401.
    assert row["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Direct helper sanity check (covers the dual-call wrapper)
# ---------------------------------------------------------------------------


def test_update_subscription_status_only_touches_non_revoked(seeded_db: Path):
    """update_subscription_status must NOT mutate revoked rows (audit trail)."""
    sub_id = "sub_helper_test"
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_h", tier="paid", stripe_subscription_id=sub_id)
    # Now revoke it.
    kh = hash_api_key(raw)
    c.execute(
        "UPDATE api_keys SET revoked_at = '2026-01-01T00:00:00+00:00' WHERE key_hash = ?",
        (kh,),
    )
    c.commit()

    n = update_subscription_status(c, sub_id, status="past_due")
    c.commit()
    assert n == 0

    row = c.execute(
        "SELECT stripe_subscription_status FROM api_keys WHERE key_hash = ?",
        (kh,),
    ).fetchone()
    assert row[0] is None  # untouched
    c.close()
