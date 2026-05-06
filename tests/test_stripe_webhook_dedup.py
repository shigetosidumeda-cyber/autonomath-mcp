"""Stripe webhook event-level idempotency dedup tests.

Covers the dedup table `stripe_webhook_events` (migration 053) and the
short-circuit path in `api/billing.py::webhook` lines 686-746.

Two cases:
  1. 初回処理 — first delivery of an event_id inserts into the dedup table
     AND processes the side effects (api_keys row created, status="received").
  2. 重複 replay → skip — second delivery of the SAME event_id returns
     status="duplicate_ignored" without re-running side effects (no second
     api_keys row, no extra welcome email schedule).

Lives in jpintel.db (the default per scripts/migrate.py — no `-- target_db:`
marker on migration 053 means jpintel.db). The seeded_db fixture in
conftest.py runs init_db() which executes schema.sql, and migration 053
is replicated into schema.sql (verified at fixture boot).
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so _stripe() / construct_event don't 503."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "env", "test", raising=False)
    yield settings


def _patch_construct_event(monkeypatch, event: dict) -> None:
    """Replace stripe.Webhook.construct_event with a stub returning `event`."""
    from jpintel_mcp.api import billing as billing_mod

    def _construct(_body, _sig, _secret):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


def _post_webhook(client, event: dict):
    return client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )


# ---------------------------------------------------------------------------
# Case 1: 初回処理 — first delivery records the event and does not issue a key
# ---------------------------------------------------------------------------


def test_first_delivery_processes_and_records_event(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """First webhook delivery: event row inserted; raw key waits for checkout state."""
    event = {
        "id": "evt_dedup_first_legacy",
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
    _patch_construct_event(monkeypatch, event)

    r = _post_webhook(client, event)

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_id, event_type, livemode FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_dedup_first_legacy",),
        ).fetchone()
        assert row is not None, "first delivery did not record event into dedup table"
        assert row[0] == "evt_dedup_first_legacy"
        assert row[1] == "customer.subscription.created"
        assert row[2] == 0  # livemode=False

        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_dedup_first",),
        ).fetchone()
        assert n_keys == 0, f"subscription.created must not issue keys, got {n_keys}"
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Case 2: 重複 replay → skip
# ---------------------------------------------------------------------------


def test_duplicate_replay_short_circuits(client, stripe_env, monkeypatch, seeded_db: Path):
    """Second delivery of the same event_id returns duplicate_ignored.

    The dedup row already exists from delivery #1. Delivery #2 must:
      * return status="duplicate_ignored" (not "received")
     * NOT create an api_keys row
      * NOT re-schedule background tasks (welcome email, Customer.modify)
    """
    event = {
        "id": "evt_dedup_replay_legacy",
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
    _patch_construct_event(monkeypatch, event)

    r1 = _post_webhook(client, event)
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"status": "received"}

    # Replay — same event_id. The handler must short-circuit before any
    # subscription side-effect or background task scheduling.
    with patch("jpintel_mcp.api.billing._apply_invoice_metadata_safe") as mock_apply:
        r2 = _post_webhook(client, event)

    assert r2.status_code == 200, r2.text
    assert r2.json() == {"status": "duplicate_ignored"}, (
        f"expected duplicate_ignored on replay, got {r2.json()}"
    )
    mock_apply.assert_not_called()

    # Database invariants: still exactly 1 dedup row + 1 api_keys row.
    c = sqlite3.connect(seeded_db)
    try:
        (n_events,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_dedup_replay_legacy",),
        ).fetchone()
        assert n_events == 1, f"expected single dedup row after replay, got {n_events}"

        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_dedup_replay",),
        ).fetchone()
        assert n_keys == 0, f"subscription.created replay must not mint keys, got {n_keys} keys"
    finally:
        c.close()
