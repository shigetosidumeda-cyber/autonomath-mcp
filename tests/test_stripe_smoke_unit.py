"""Unit tests for scripts/stripe_smoke_e2e.py.

These tests exercise:
  - `stripe_signature()` helper round-trips against Stripe's official
    `stripe.Webhook.construct_event()` (i.e. the signatures we emit are
    accepted by the same verifier the server uses at runtime)
  - the webhook POST flow through our FastAPI app end-to-end without ever
    touching real Stripe (all `stripe.*` symbols are mocked via
    `unittest.mock.patch`). This guards against signature-header drift and
    webhook-dispatch regressions in CI.

No real Stripe calls happen here — this file is safe to run offline.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import stripe

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Load the smoke module without installing it as a package.
# ---------------------------------------------------------------------------


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "stripe_smoke_e2e",
        REPO / "scripts" / "stripe_smoke_e2e.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = _load_smoke_module()


# ---------------------------------------------------------------------------
# stripe_signature() round-trip
# ---------------------------------------------------------------------------


def test_stripe_signature_accepted_by_construct_event():
    """Our signature helper produces headers that Stripe's own verifier accepts.

    This is the "does the smoke's HMAC actually match the server's expectation"
    contract. If Stripe ever changes the signing format this test flips red.
    """
    secret = "whsec_unit_test_secret"
    payload = json.dumps(
        {
            "id": "evt_unit_1",
            # Stripe SDK v15 reads `.object` on the decoded event to branch
            # between v1 and v2 event shapes — must be present on the
            # top-level envelope or construct_event raises AttributeError.
            "object": "event",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_unit_1"}},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    t = int(time.time())
    header = smoke.stripe_signature(payload, secret, t)

    # Real Stripe SDK verifier — no mocks.
    event = stripe.Webhook.construct_event(payload, header, secret)
    assert event["id"] == "evt_unit_1"
    assert event["type"] == "customer.subscription.created"


def test_stripe_signature_rejected_on_wrong_secret():
    """Flip the secret; verifier must raise SignatureVerificationError."""
    payload = b'{"id":"evt_bad"}'
    t = int(time.time())
    header = smoke.stripe_signature(payload, "whsec_A", t)
    with pytest.raises(stripe.SignatureVerificationError):
        stripe.Webhook.construct_event(payload, header, "whsec_B")


def test_stripe_signature_format_shape():
    """Header is `t=<int>,v1=<64hex>`. Ensures we never emit a malformed one."""
    h = smoke.stripe_signature(b"{}", "whsec_x", 1700000000)
    parts = dict(p.split("=", 1) for p in h.split(","))
    assert parts["t"] == "1700000000"
    assert len(parts["v1"]) == 64  # sha256 hex
    assert all(c in "0123456789abcdef" for c in parts["v1"])


# ---------------------------------------------------------------------------
# Webhook round-trip through the real FastAPI app (mocked Stripe SDK)
# ---------------------------------------------------------------------------


def test_webhook_roundtrip_subscription_created(client, monkeypatch, seeded_db: Path):
    """End-to-end: signed payload → FastAPI billing router → event row.

    `stripe.Webhook.construct_event` is patched to return a fixed event so
    we're not depending on webhook-secret env alignment here (that's covered
    by `test_stripe_signature_accepted_by_construct_event` above). This test
    proves the smoke's payload *structure* is accepted by the handler without
    issuing a raw key from the webhook.
    """
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_unit", raising=False)

    event = {
        "id": "evt_unit_sub_created",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_unit_new",
                "customer": "cus_unit_new",
                "items": {"data": [{"price": {"id": "price_unit"}}]},
            }
        },
    }

    def _construct(_body, _sig, _secret):
        return event

    with patch.object(billing_mod.stripe.Webhook, "construct_event", _construct):
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        header = smoke.stripe_signature(payload, "whsec_dummy", int(time.time()))
        r = client.post(
            "/v1/billing/webhook",
            content=payload,
            headers={
                "stripe-signature": header,
                "content-type": "application/json",
            },
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}

    c = sqlite3.connect(seeded_db)
    try:
        (n_keys,) = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_unit_new",),
        ).fetchone()
        event_row = c.execute(
            "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_unit_sub_created",),
        ).fetchone()
    finally:
        c.close()
    assert n_keys == 0
    assert event_row is not None
    assert event_row[0] is not None


def test_webhook_roundtrip_payment_failed_demotes_tier(client, monkeypatch, seeded_db: Path):
    """invoice.payment_failed via smoke's payload shape → tier=free."""
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.billing.keys import issue_key
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_unit", raising=False)

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    issue_key(c, customer_id="cus_dun", tier="paid", stripe_subscription_id="sub_dun_1")
    c.commit()
    c.close()

    event = {
        "id": "evt_unit_fail",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": "sub_dun_1",
                "customer": "cus_dun",
                "attempt_count": 1,
            }
        },
    }

    def _construct(_body, _sig, _secret):
        return event

    with patch.object(billing_mod.stripe.Webhook, "construct_event", _construct):
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        header = smoke.stripe_signature(payload, "whsec_dummy", int(time.time()))
        r = client.post(
            "/v1/billing/webhook",
            content=payload,
            headers={"stripe-signature": header},
        )
    assert r.status_code == 200, r.text

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_dun_1",),
        ).fetchone()
    finally:
        c.close()
    assert row[0] == "free", f"expected demotion to free, got {row[0]}"


# ---------------------------------------------------------------------------
# Credential gate: never lets an sk_live_* key slip through
# ---------------------------------------------------------------------------


def test_require_test_creds_rejects_live_key(monkeypatch, capsys):
    """Even if someone exports an sk_live_* key to the smoke, it must bail."""
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_live_oops")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_x")
    monkeypatch.setenv("STRIPE_PRICE_ID_TEST", "price_x")
    with pytest.raises(SystemExit) as excinfo:
        smoke._require_test_creds()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "not a test-mode secret key" in out


def test_require_test_creds_rejects_missing_env(monkeypatch, capsys):
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_x")
    monkeypatch.setenv("STRIPE_PRICE_ID_TEST", "price_x")
    with pytest.raises(SystemExit) as excinfo:
        smoke._require_test_creds()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "STRIPE_SECRET_KEY_TEST" in out


def test_require_test_creds_rejects_non_price_id(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_ok")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_x")
    monkeypatch.setenv("STRIPE_PRICE_ID_TEST", "prod_oops")
    with pytest.raises(SystemExit) as excinfo:
        smoke._require_test_creds()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "not a Stripe Price id" in out
