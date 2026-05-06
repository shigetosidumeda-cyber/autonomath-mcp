"""P3.5 Stripe edge-case handler tests (2026-04-25).

Covers ``src/jpintel_mcp/billing/stripe_edge_cases.py``:

  1. refund_request — POST /v1/billing/refund_request inserts a row +
     returns the request_id with the manual-review note (memory:
     `feedback_autonomath_no_api_use` — already-billed metering NOT
     auto-reversed).
  2. dispute — `charge.dispute.created` webhook flows through the new
     handler + writes an audit_log row WITHOUT auto-revoking keys.
  3. tax_exempt — `customer.updated` with metadata.tax_exempt="exempt"
     calls Stripe Customer.modify(tax_exempt="exempt").
  4. currency_edge — invoice.created with currency="usd" emits a warning
     log + audit_log row + does NOT short-circuit other handlers.
  5. invoice_modification — invoice.voided writes an audit_log row tagged
     with the original invoice id + status.
  6. stripe_tax_fallback — Stripe Tax 5xx → cache hit returns cached rate;
     cache miss returns JP standard 1000 bps.

Plus latent-bug regression: the dedup path uses ``event["id"]`` indexing,
not ``event.get("id")``, when the stripe SDK Event object is consumed.
The dedup test in ``test_stripe_webhook_dedup.py`` already exercises the
dict-stub path; this module's case 7 verifies the bracket access works
unchanged on a pathological dict missing the "id" key.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def stripe_env(monkeypatch):
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "env", "test", raising=False)
    yield settings


def _patch_construct_event(monkeypatch, event: dict) -> None:
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
# 1. Refund request intake
# ---------------------------------------------------------------------------


def test_refund_request_persists_and_returns_id(client, seeded_db, stripe_env):
    """POST /v1/billing/refund_request inserts a refund_requests row + 201."""
    payload = {
        "requester_email": "user@example.com",
        "customer_id": "cus_test_refund_1",
        "amount_yen": 9000,
        "reason": "サービス停止のため返金希望",
    }
    r = client.post("/v1/billing/refund_request", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["request_id"].startswith("返金-")
    assert body["expected_response_within_days"] == 14
    assert body["contact"] == "info@bookyou.net"
    # Memory `feedback_autonomath_no_api_use`: response must announce manual
    # review + non-reversal of metering.
    assert "自動取消し" in body["note"]

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT customer_id, amount_yen, reason, status FROM refund_requests "
            "WHERE request_id = ?",
            (body["request_id"],),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "cus_test_refund_1"
    assert row[1] == 9000
    assert row[3] == "pending"


# ---------------------------------------------------------------------------
# 2. Dispute handler
# ---------------------------------------------------------------------------


def test_dispute_created_audit_log_no_revoke(client, stripe_env, monkeypatch, seeded_db):
    """charge.dispute.created writes audit_log row WITHOUT revoking keys.

    Memory: dispute lifecycle can flip closed→won, so auto-revoking on
    `created` would punish legitimate customers caught in issuer false
    positives. The handler must only audit + log.
    """
    # Pre-seed an api_keys row for the customer so we can assert it stays
    # active (revoked_at IS NULL). The schema-required NOT NULL columns are
    # key_hash + tier + created_at; everything else is optional.
    from datetime import UTC
    from datetime import datetime as _dt

    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO api_keys(key_hash, customer_id, tier, "
            "stripe_subscription_id, created_at) VALUES (?,?,?,?,?)",
            (
                "hash_dispute_1",
                "cus_dispute_1",
                "paid",
                "sub_dispute_1",
                _dt.now(UTC).isoformat(),
            ),
        )
        c.commit()
    finally:
        c.close()

    event = {
        "id": "evt_dispute_created_1",
        "type": "charge.dispute.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "dp_test_1",
                "charge": "ch_test_1",
                "amount": 9000,
                "currency": "jpy",
                "reason": "fraudulent",
                "status": "warning_needs_response",
                "evidence_details": {"due_by": 1714000000},
            }
        },
    }
    _patch_construct_event(monkeypatch, event)
    r = _post_webhook(client, event)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"

    c = sqlite3.connect(seeded_db)
    try:
        # Audit row exists.
        row = c.execute(
            "SELECT event_type FROM audit_log WHERE event_type = ? ORDER BY ts DESC LIMIT 1",
            ("charge.dispute.created",),
        ).fetchone()
        assert row is not None, "dispute.created should write audit_log row"
        # Key NOT revoked.
        (revoked,) = c.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ?",
            ("hash_dispute_1",),
        ).fetchone()
        assert revoked is None, "dispute.created must NOT auto-revoke"
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 3. Tax-exempt customer
# ---------------------------------------------------------------------------


def test_tax_exempt_metadata_propagates_to_stripe(client, stripe_env, monkeypatch, seeded_db):
    """customer.updated with metadata.tax_exempt="exempt" → Customer.modify."""
    event = {
        "id": "evt_tax_exempt_1",
        "type": "customer.updated",
        "livemode": False,
        "data": {
            "object": {
                "id": "cus_govt_1",
                "metadata": {"tax_exempt": "exempt"},
                "tax_exempt": "none",
            }
        },
    }
    _patch_construct_event(monkeypatch, event)

    modify_calls: list[dict] = []

    def _fake_modify(customer_id, **kwargs):
        modify_calls.append({"customer_id": customer_id, **kwargs})
        return {"id": customer_id, "tax_exempt": kwargs.get("tax_exempt")}

    # Patch the stripe module at the import site inside the edge handler.
    import stripe as _stripe_mod

    monkeypatch.setattr(_stripe_mod.Customer, "modify", _fake_modify)

    r = _post_webhook(client, event)
    assert r.status_code == 200, r.text

    assert len(modify_calls) == 1, f"expected 1 modify call, got {modify_calls}"
    assert modify_calls[0]["customer_id"] == "cus_govt_1"
    assert modify_calls[0]["tax_exempt"] == "exempt"


# ---------------------------------------------------------------------------
# 4. Currency edge
# ---------------------------------------------------------------------------


def test_currency_edge_non_jpy_audits_and_warns(client, stripe_env, monkeypatch, seeded_db, caplog):
    """invoice.created with currency="usd" emits warning + audit_log row."""
    event = {
        "id": "evt_currency_usd_1",
        "type": "invoice.created",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_test_usd_1",
                "customer": "cus_intl_1",
                "currency": "usd",
                "amount_due": 3000,
                "customer_tax_exempt": "none",
            }
        },
    }
    _patch_construct_event(monkeypatch, event)

    # Tax-exempt handler also fires on invoice.created; stub
    # Customer.retrieve so it doesn't blow up trying to talk to Stripe.
    import stripe as _stripe_mod

    monkeypatch.setattr(
        _stripe_mod.Customer,
        "retrieve",
        lambda *a, **k: {"id": "cus_intl_1", "metadata": {}},
    )

    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="jpintel.billing.edge_cases"):
        r = _post_webhook(client, event)
    assert r.status_code == 200, r.text

    # Warning log emitted with currency=usd.
    assert any(
        "stripe.currency_edge" in rec.message and "usd" in rec.message for rec in caplog.records
    ), f"missing currency_edge warning; saw {[r.message for r in caplog.records]}"

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_type, metadata FROM audit_log "
            "WHERE event_type = 'stripe.currency_edge' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    finally:
        c.close()
    assert row is not None, "currency_edge must write audit_log row"
    md = json.loads(row[1])
    assert md["currency"] == "usd"
    assert md["trigger_etype"] == "invoice.created"


# ---------------------------------------------------------------------------
# 5. Invoice modification (invoice.voided)
# ---------------------------------------------------------------------------


def test_invoice_voided_audit_logs_with_original_id(client, stripe_env, monkeypatch, seeded_db):
    """invoice.voided writes audit_log row tagged with the invoice id."""
    event = {
        "id": "evt_invoice_voided_1",
        "type": "invoice.voided",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_voided_1",
                "customer": "cus_voided_1",
                "subscription": "sub_voided_1",
                "amount_due": 9000,
                "status": "void",
                "hosted_invoice_url": "https://invoice.stripe.com/i/test",
            }
        },
    }
    _patch_construct_event(monkeypatch, event)
    r = _post_webhook(client, event)
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_type, metadata FROM audit_log "
            "WHERE event_type = 'invoice.voided' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    md = json.loads(row[1])
    assert md["stripe_invoice_id"] == "in_voided_1"
    assert md["invoice_status"] == "void"
    assert md["amount_due"] == 9000


# ---------------------------------------------------------------------------
# 6. Stripe Tax API failure fallback
# ---------------------------------------------------------------------------


def test_stripe_tax_fallback_cache_hit_then_jp_default(seeded_db, stripe_env, monkeypatch):
    """Stripe Tax 5xx → cached rate. No cache → JP standard 1000 bps."""
    import stripe as _stripe_mod

    from jpintel_mcp.billing.stripe_edge_cases import (
        cache_successful_tax_calculation,
        stripe_tax_with_fallback,
    )

    class _BoomError(Exception):
        pass

    def _explode(**kwargs):
        raise _BoomError("simulated Stripe Tax 5xx")

    # The edge module imports stripe lazily; patch the public Calculation
    # path so any access shape (stripe.tax.Calculation.create) raises.
    fake_tax = MagicMock()
    fake_tax.Calculation.create.side_effect = _explode
    monkeypatch.setattr(_stripe_mod, "tax", fake_tax, raising=False)

    conn = sqlite3.connect(seeded_db)
    try:
        # ---- Sub-case A: cache miss → JP standard 10% (1000 bps) ----------
        # Ensure clean cache for this customer.
        conn.execute(
            "DELETE FROM stripe_tax_cache WHERE customer_id = ?",
            ("cus_tax_fallback_1",),
        )
        conn.commit()
        result_miss = stripe_tax_with_fallback(
            conn,
            customer_id="cus_tax_fallback_1",
            line_items=[{"amount": 3000, "reference": "req_1"}],
        )
        assert result_miss["source"] == "jp_standard_default"
        assert result_miss["rate_bps"] == 1000

        # ---- Sub-case B: cache hit → return cached rate ------------------
        cache_successful_tax_calculation(
            conn,
            customer_id="cus_tax_fallback_2",
            rate_bps=1000,
            tax_amount_yen=300,
        )
        conn.commit()
        result_hit = stripe_tax_with_fallback(
            conn,
            customer_id="cus_tax_fallback_2",
            line_items=[{"amount": 3000, "reference": "req_2"}],
        )
        assert result_hit["source"] == "cache"
        assert result_hit["rate_bps"] == 1000
        assert result_hit["fallback_reason"] == "stripe_5xx"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Latent bug fix regression: pathological event missing "id" / "livemode"
# ---------------------------------------------------------------------------


def test_dedup_path_handles_event_without_id_key(client, stripe_env, monkeypatch, seeded_db):
    """A stub event without an "id" key must still 200 (empty event_id path).

    The latent-bug fix changed `event.get("id") or ""` to `event["id"] or ""`
    + an except clause for KeyError/TypeError. Verifies the except branch
    runs cleanly when the SDK shape unexpectedly omits the field.
    """
    event = {
        # NOTE: deliberately missing "id" and "livemode".
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_no_event_id_1",
                "customer": "cus_no_event_id_1",
                "items": {"data": [{"price": {"id": "price_metered_test"}}]},
            }
        },
    }
    _patch_construct_event(monkeypatch, event)
    r = _post_webhook(client, event)
    assert r.status_code == 200, r.text
    # No event_id → no dedup row written; the handler still completes.
    body = r.json()
    # When event_id is empty, dedup path is skipped — webhook returns
    # "received" or whichever handler-side status.
    assert body.get("status") in ("received", "livemode_mismatch_ignored")
