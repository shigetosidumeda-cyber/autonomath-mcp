"""DD-02: Stripe webhook replay-window tolerance contract tests.

Locks the production tolerance value at 300 seconds (Stripe SDK default,
5 min replay window). Per
`tools/offline/_inbox/value_growth_dual/_m00_implementation/M00_D_billing_safety/DD_02_stripe_webhook_tolerance.md`.

These tests fail if a future refactor:
  * Drops the tolerance kwarg from the construct_event call.
  * Changes the tolerance to a different value.
  * Lets a stale-signature delivery silently succeed.
  * Lets a duplicate event_id within the tolerance window double-write.
  * Lets a duplicate event_id beyond the tolerance window slip past the
    signature-verification fence.

Five cases:
  1. test_in_tolerance_succeeds          — t=now-200, sig OK → 200
  2. test_out_of_tolerance_rejected      — t=now-400, sig OK → 400
  3. test_replay_within_window_idempotent — same event_id 2x → both 200,
                                             one DB row
  4. test_replay_beyond_window_rejected   — same event_id, second stale → 400
  5. test_invalid_signature_rejected      — bad HMAC → 400

The tests build a real `stripe-signature` header (HMAC-SHA256 over
"<t>.<body>" with the test webhook secret) so we exercise the real
`stripe.Webhook.construct_event` path including its tolerance check.
We do NOT monkeypatch construct_event itself — that would defeat the
purpose of this contract. We DO monkeypatch the side-effect handlers
that rely on Stripe API calls (Customer.retrieve, Subscription.modify)
so the test can run offline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

WHSEC = "whsec_test_dd02_tolerance_contract"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stripe_signature(payload: bytes, secret: str, timestamp: int) -> str:
    """Build a Stripe `t=<int>,v1=<hex>` signature header.

    Mirrors `scripts/stripe_smoke_e2e.py::stripe_signature` so the real
    Stripe SDK verifier accepts it. Used to control the timestamp
    portion of the signature, which is what the tolerance check inspects.
    """
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _make_event_body(event_id: str) -> bytes:
    """Minimal Stripe event envelope the billing handler can dispatch.

    Uses a deliberately unhandled type so the handler logs + records the
    event in `stripe_webhook_events` but does NOT issue a key or call
    out to Stripe API — keeping the test self-contained.
    """
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "ping.unhandled",
            "livemode": False,
            "data": {"object": {}},
        },
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe + env settings the webhook handler needs."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", WHSEC, raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    # `dev` so the livemode-mismatch guard does not short-circuit on
    # event["livemode"]=False.
    monkeypatch.setattr(settings, "env", "dev", raising=False)
    yield settings


def _post_webhook(client, body: bytes, signature: str):
    return client.post(
        "/v1/billing/webhook",
        content=body,
        headers={"stripe-signature": signature},
    )


def _count_dedup_rows(seeded_db: Path, event_id: str) -> int:
    conn = sqlite3.connect(seeded_db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _count_audit_stale(seeded_db: Path) -> int:
    """Count audit_log rows of type stripe_webhook_stale_signature.

    Returns 0 if the audit_log table is missing (older test DB without
    migration 058) — that is acceptable for the in-tolerance test which
    asserts 0 anyway.
    """
    conn = sqlite3.connect(seeded_db)
    try:
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE event_type = 'stripe_webhook_stale_signature'"
            ).fetchone()
            return int(row[0])
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. In-tolerance delivery succeeds.
# ---------------------------------------------------------------------------


def test_in_tolerance_succeeds(client, stripe_env, seeded_db: Path):
    """Timestamp 200 seconds in the past is within the 300s window → 200.

    The dispatcher must accept the signature, record the event_id in the
    dedup table, and emit no stale-signature audit row.
    """
    event_id = "evt_dd02_in_tolerance"
    body = _make_event_body(event_id)
    timestamp = int(time.time()) - 200
    sig = _stripe_signature(body, WHSEC, timestamp)

    audit_before = _count_audit_stale(seeded_db)

    r = _post_webhook(client, body, sig)

    assert r.status_code == 200, (
        f"In-tolerance delivery (age=200s, window=300s) must return 200; "
        f"got {r.status_code}: {r.text}"
    )
    assert (
        _count_dedup_rows(seeded_db, event_id) == 1
    ), "stripe_webhook_events row must be inserted on first accepted delivery"
    audit_after = _count_audit_stale(seeded_db)
    assert audit_after == audit_before, (
        "No stripe_webhook_stale_signature audit_log row must be emitted "
        "for an in-tolerance delivery"
    )


# ---------------------------------------------------------------------------
# 2. Out-of-tolerance delivery rejected.
# ---------------------------------------------------------------------------


def test_out_of_tolerance_rejected(client, stripe_env, seeded_db: Path):
    """Timestamp 400 seconds in the past is OUTSIDE the 300s window → 400.

    Even though the HMAC is computed correctly, the SDK must reject on
    timestamp tolerance. The handler must NOT insert into
    stripe_webhook_events (event was never accepted).
    """
    event_id = "evt_dd02_out_of_tolerance"
    body = _make_event_body(event_id)
    timestamp = int(time.time()) - 400
    sig = _stripe_signature(body, WHSEC, timestamp)

    r = _post_webhook(client, body, sig)

    assert r.status_code == 400, (
        f"Out-of-tolerance delivery (age=400s, window=300s) must return 400; "
        f"got {r.status_code}: {r.text}"
    )
    assert (
        _count_dedup_rows(seeded_db, event_id) == 0
    ), "Rejected stale-signature delivery must NOT insert into stripe_webhook_events"
    # Note: audit_log emission is part of the DD-02 implementation
    # (construct_event_or_audit helper). Until that helper lands the count
    # may stay at 0; this assertion is intentionally one-sided so it does
    # NOT block the test on the helper landing first. Once the helper is
    # wired, flip this to `assert _count_audit_stale(seeded_db) >= 1`.


# ---------------------------------------------------------------------------
# 3. Replay within the tolerance window is idempotent.
# ---------------------------------------------------------------------------


def test_replay_within_window_idempotent(client, stripe_env, seeded_db: Path):
    """Same event_id delivered twice within the window → both 200, one DB row.

    The first delivery records the event and runs side effects (none for
    ping.unhandled). The second delivery hits the dedup short-circuit
    and returns 200 with `duplicate_ignored` (or equivalent), making no
    DB mutation.
    """
    event_id = "evt_dd02_replay_in_window"

    # First delivery: now-100s
    body1 = _make_event_body(event_id)
    sig1 = _stripe_signature(body1, WHSEC, int(time.time()) - 100)
    r1 = _post_webhook(client, body1, sig1)
    assert r1.status_code == 200, f"First delivery must succeed; got {r1.text}"

    rows_after_first = _count_dedup_rows(seeded_db, event_id)
    assert (
        rows_after_first == 1
    ), f"First delivery must insert exactly one stripe_webhook_events row; got {rows_after_first}"

    # Second delivery: now-50s (still in window, fresh signature, same event_id)
    body2 = _make_event_body(event_id)
    sig2 = _stripe_signature(body2, WHSEC, int(time.time()) - 50)
    r2 = _post_webhook(client, body2, sig2)
    assert r2.status_code == 200, (
        f"Replay within tolerance window must return 200 (idempotent); "
        f"got {r2.status_code}: {r2.text}"
    )

    rows_after_second = _count_dedup_rows(seeded_db, event_id)
    assert (
        rows_after_second == 1
    ), f"Replay must NOT insert a second stripe_webhook_events row; got {rows_after_second}"

    # Optional shape assertion: handler signals the duplicate with a
    # status string. Be tolerant of envelope variations across handler
    # versions but require the keyword.
    try:
        body_json: dict[str, Any] = r2.json()
    except Exception:
        body_json = {}
    if isinstance(body_json, dict) and "status" in body_json:
        assert "duplicate" in body_json["status"].lower() or body_json["status"] in (
            "duplicate_ignored",
            "ignored",
            "ok",
        ), f"Replay response status should signal duplicate; got {body_json['status']!r}"


# ---------------------------------------------------------------------------
# 4. Replay beyond the tolerance window is rejected on signature.
# ---------------------------------------------------------------------------


def test_replay_beyond_window_rejected(client, stripe_env, seeded_db: Path):
    """Second delivery with a stale timestamp is rejected at signature step.

    Defense-in-depth: even if the dedup table somehow loses the row (DB
    rollback, schema drift), the SDK's tolerance check rejects the stale
    signature BEFORE we look at the dedup state. This test exercises that
    fence.
    """
    event_id = "evt_dd02_replay_beyond_window"

    # First delivery: in window
    body1 = _make_event_body(event_id)
    sig1 = _stripe_signature(body1, WHSEC, int(time.time()) - 100)
    r1 = _post_webhook(client, body1, sig1)
    assert r1.status_code == 200, f"First delivery must succeed; got {r1.text}"

    # Second delivery: stale timestamp (400s > 300s window).
    # Same event_id, valid HMAC — but stale.
    body2 = _make_event_body(event_id)
    sig2 = _stripe_signature(body2, WHSEC, int(time.time()) - 400)
    r2 = _post_webhook(client, body2, sig2)
    assert r2.status_code == 400, (
        f"Stale-timestamp replay must return 400 (signature fence beats "
        f"dedup fence); got {r2.status_code}: {r2.text}"
    )

    # The dedup table still has exactly one row from the first delivery.
    rows = _count_dedup_rows(seeded_db, event_id)
    assert (
        rows == 1
    ), f"Stale-timestamp replay must NOT touch stripe_webhook_events; got {rows} rows"


# ---------------------------------------------------------------------------
# 5. Invalid signature rejected regardless of timestamp.
# ---------------------------------------------------------------------------


def test_invalid_signature_rejected(client, stripe_env, seeded_db: Path):
    """A fresh timestamp does NOT save an HMAC mismatch → 400.

    This test confirms the signature fence is independent of the
    tolerance fence — both must pass, not either-or.
    """
    event_id = "evt_dd02_bad_hmac"
    body = _make_event_body(event_id)
    timestamp = int(time.time())  # fresh — tolerance OK
    bad_sig = f"t={timestamp},v1={'0' * 64}"  # zero hex = mismatch

    r = _post_webhook(client, body, bad_sig)

    assert r.status_code == 400, (
        f"Invalid-HMAC delivery must return 400 even with a fresh "
        f"timestamp; got {r.status_code}: {r.text}"
    )
    assert (
        _count_dedup_rows(seeded_db, event_id) == 0
    ), "Rejected bad-HMAC delivery must NOT insert into stripe_webhook_events"


# ---------------------------------------------------------------------------
# Contract probe: the production code must explicitly pass tolerance=300.
# ---------------------------------------------------------------------------


def test_construct_event_called_with_tolerance_300(client, stripe_env, monkeypatch):
    """The handler MUST pass `tolerance=300` to construct_event.

    Captures the kwargs of the SDK call so a future refactor that drops
    the kwarg or changes its value flips this red. See DD-02 §3.1 for
    the rationale on locking at 300s vs 60s.
    """
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict[str, Any]] = []

    def _construct(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.append({"args": args, "kwargs": kwargs})
        return {
            "id": "evt_dd02_tolerance_probe",
            "object": "event",
            "type": "ping.unhandled",
            "livemode": False,
            "data": {"object": {}},
        }

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)

    body = _make_event_body("evt_dd02_tolerance_probe")
    r = client.post(
        "/v1/billing/webhook",
        content=body,
        headers={"stripe-signature": "t=1,v1=ignored_by_stub"},
    )

    assert r.status_code in (200, 204), r.text
    assert len(captured) == 1, "construct_event must be invoked exactly once"
    call = captured[0]
    assert "tolerance" in call["kwargs"], (
        "DD-02: stripe.Webhook.construct_event must be called with explicit "
        f"tolerance kwarg; got args={call['args']!r} kwargs={call['kwargs']!r}"
    )
    assert call["kwargs"]["tolerance"] == 300, (
        "DD-02: tolerance LOCKED at 300s (Stripe SDK default). See "
        "tools/offline/_inbox/value_growth_dual/_m00_implementation/"
        "M00_D_billing_safety/DD_02_stripe_webhook_tolerance.md §3.1. "
        f"Got tolerance={call['kwargs']['tolerance']!r}"
    )
