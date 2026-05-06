"""M13: assert /v1/billing/webhook calls construct_event with tolerance=300.

Stripe's `stripe.Webhook.construct_event` defaults to a 5-minute (300s)
timestamp tolerance. DD-02 locks that value explicitly so future SDK
defaults or refactors cannot silently change webhook replay behavior.

This test patches `stripe.Webhook.construct_event` with a recording stub
and asserts the handler invokes it with `tolerance=300`. The dispatch
mechanics themselves are covered elsewhere (see
test_billing_webhook_signature.py for the real-roundtrip path) — this
file only guards the explicit-tolerance contract so a future refactor
that drops the kwarg surfaces immediately.
"""

from __future__ import annotations

import json

import pytest

WHSEC_TEST = "whsec_test_tolerance_300"


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so `_stripe()` doesn't 503."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", WHSEC_TEST, raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "env", "dev", raising=False)
    yield settings


def test_construct_event_called_with_tolerance_300(client, stripe_env, monkeypatch):
    """The handler MUST pass `tolerance=300` to construct_event.

    We capture every (args, kwargs) the patched stub sees and assert
    `tolerance=60` is in the kwargs. The stub returns a minimal harmless
    event so the rest of the handler does not crash before we get to
    assert on the call record.
    """
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict] = []

    def _construct(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})
        # Return a minimal event the handler can dispatch without error
        # (unhandled type → handler logs + returns 200, no DB writes
        # required for this assertion).
        return {
            "id": "evt_tolerance_test",
            "object": "event",
            "type": "ping.unhandled",
            "livemode": False,
            "data": {"object": {}},
        }

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)

    body = json.dumps({"id": "evt_tolerance_test", "type": "ping.unhandled"}).encode("utf-8")
    r = client.post(
        "/v1/billing/webhook",
        content=body,
        headers={"stripe-signature": "t=1,v1=ignored_by_stub"},
    )

    # We don't assert on status here — the construct_event stub returned a
    # synthetic event so dispatch outcome is irrelevant to the contract
    # under test. We DO assert the stub was called (otherwise the kwargs
    # check below is vacuously true).
    assert r.status_code in (200, 204), r.text
    assert len(captured) == 1, "construct_event must be invoked exactly once"

    call = captured[0]
    assert "tolerance" in call["kwargs"], (
        "M13: stripe.Webhook.construct_event must be called with explicit "
        f"tolerance kwarg; got args={call['args']!r} kwargs={call['kwargs']!r}"
    )
    assert call["kwargs"]["tolerance"] == 300, (
        "M13: tolerance must be explicitly locked at 300s. "
        f"Got tolerance={call['kwargs']['tolerance']!r}"
    )
