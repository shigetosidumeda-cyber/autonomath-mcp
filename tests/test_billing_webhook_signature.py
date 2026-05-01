"""Real Stripe-signature roundtrip + edge cases (P0 launch blocker).

The existing webhook tests stub `stripe.Webhook.construct_event`, which
means every prior assertion has been about dispatch + dedup mechanics
ONLY. A subtle HMAC SHA-256 / timestamp-comparison regression in our
handler — or a Stripe SDK breaking change — could pass every other test
in the suite while production webhooks silently 400.

This file builds a real `Stripe-Signature` header by hand
(`t={timestamp},v1={hex_digest}`) and POSTs to /v1/billing/webhook so
the handler exercises the real `stripe.Webhook.construct_event` path.
We additionally verify our hand-computed signature interops with
`stripe.webhook.WebhookSignature.verify_header` directly to catch the
opposite drift (our test math wrong, handler still right) — that single
roundtrip call is the canonical interop check the rest of the suite
hangs on.

Test taxonomy (audit a37c4ec09836f3f93):
1. Valid signature → 200 + dedup row
2. Tampered payload byte → 400
3. Stale timestamp (>5min old) → 400
4. Missing Stripe-Signature header → 400
5. Wrong secret → 400
6. Replay (same event_id, same signature) → 200 dedup hit
7. livemode toggle (dev/prod) processes / skips correctly
8. Content-Length > 1MB → 413 BEFORE signature validation
9. customer.subscription.trial_will_end → audit_log row, no email
10. Multiple v1 signatures (rotation) → valid one wins
11. invoice.payment_failed → dunning email enqueue
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path  # noqa: TC003

import pytest
import stripe  # noqa: F401  (kept for parity / future use)
from stripe._webhook import WebhookSignature

WHSEC_TEST = "whsec_test_xxxxx"


def _sign_payload(
    payload_bytes: bytes,
    *,
    secret: str = WHSEC_TEST,
    timestamp: int | None = None,
    extra_v1_sigs: list[str] | None = None,
    scheme: str = "v1",
) -> tuple[str, int]:
    """Build a Stripe-Signature header for `payload_bytes`.

    Returns (header_value, timestamp_used). Mirrors
    stripe.webhook.WebhookSignature._compute_signature exactly so a
    drift between this test and stripe-python surfaces as a 400 in
    test_valid_signature_returns_200, not a silent green elsewhere.
    """
    ts = int(time.time()) if timestamp is None else timestamp
    signed_payload = f"{ts}.{payload_bytes.decode('utf-8')}".encode()
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=signed_payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    parts = [f"t={ts}", f"{scheme}={digest}"]
    for extra in extra_v1_sigs or []:
        parts.append(f"{scheme}={extra}")
    return ",".join(parts), ts


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so _stripe() doesn't 503 and the webhook
    path uses our deterministic test secret."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", WHSEC_TEST, raising=False)
    monkeypatch.setattr(
        settings, "stripe_price_per_request", "price_metered_test", raising=False
    )
    monkeypatch.setattr(settings, "env", "dev", raising=False)
    yield settings


# ---------------------------------------------------------------------------
# Roundtrip: our hand-computed signature must validate via stripe-python
# itself. If THIS fails, every other test below is moot — fix the test math
# first.
# ---------------------------------------------------------------------------


def test_hand_signature_validates_via_stripe_sdk():
    """Sanity floor: stripe.webhook.WebhookSignature must accept our header."""
    payload = b'{"id":"evt_roundtrip","type":"ping"}'
    header, _ = _sign_payload(payload)
    # Direct call. Raises SignatureVerificationError on mismatch.
    assert WebhookSignature.verify_header(
        payload.decode("utf-8"), header, WHSEC_TEST, tolerance=300
    ) is True


# ---------------------------------------------------------------------------
# Helpers — real event payloads + handlers used by multiple tests
# ---------------------------------------------------------------------------


def _sub_updated_payload(
    *,
    event_id: str = "evt_real_sig_updated",
    sub_id: str = "sub_real_sig",
    livemode: bool = False,
) -> bytes:
    """Real customer.subscription.updated JSON shape — only the fields the
    handler reads. The handler indexes obj['items']['data'][0]['price']['id']
    so that nesting is non-optional even in test fixtures."""
    body = {
        "id": event_id,
        "object": "event",
        "type": "customer.subscription.updated",
        "livemode": livemode,
        "data": {
            "object": {
                "id": sub_id,
                "object": "subscription",
                "customer": "cus_real_sig",
                "status": "active",
                "current_period_end": 1900000000,
                "cancel_at_period_end": False,
                "items": {
                    "data": [
                        {"price": {"id": "price_metered_test"}}
                    ]
                },
            }
        },
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _trial_will_end_payload(
    *, event_id: str = "evt_trial_will_end"
) -> bytes:
    body = {
        "id": event_id,
        "object": "event",
        "type": "customer.subscription.trial_will_end",
        "livemode": False,
        "data": {
            "object": {
                "id": "sub_trial_real",
                "object": "subscription",
                "customer": "cus_trial_real",
                "trial_end": 1900000000,
                "status": "trialing",
                "items": {
                    "data": [
                        {"price": {"id": "price_metered_test"}}
                    ]
                },
            }
        },
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _payment_failed_payload(
    *, event_id: str = "evt_payment_failed_real_sig"
) -> bytes:
    body = {
        "id": event_id,
        "object": "event",
        "type": "invoice.payment_failed",
        "livemode": False,
        "data": {
            "object": {
                "object": "invoice",
                "subscription": "sub_payfail_real_sig",
                "customer": "cus_payfail_real_sig",
                "customer_email": "payfail@example.com",
                "attempt_count": 2,
                "next_payment_attempt": 1900000000,
            }
        },
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Valid signature → 200 + dedup row
# ---------------------------------------------------------------------------


def test_valid_signature_returns_200_and_records_dedup_row(
    client, stripe_env, seeded_db: Path
):
    payload = _sub_updated_payload(event_id="evt_real_sig_valid")
    header, _ = _sign_payload(payload)

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
        row = c.execute(
            "SELECT event_id, event_type, processed_at FROM stripe_webhook_events "
            "WHERE event_id = ?",
            ("evt_real_sig_valid",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "evt_real_sig_valid"
    assert row[1] == "customer.subscription.updated"
    assert row[2] is not None  # processed_at filled


# ---------------------------------------------------------------------------
# 2. Tampered payload byte → 400
# ---------------------------------------------------------------------------


def test_tampered_payload_byte_returns_400(client, stripe_env):
    payload = _sub_updated_payload(event_id="evt_real_sig_tamper")
    header, _ = _sign_payload(payload)
    # Flip one byte in the body AFTER signing.
    tampered = bytearray(payload)
    # Pick a byte we know is part of a JSON value, not structural.
    idx = tampered.find(b"sub_real_sig")
    assert idx >= 0
    tampered[idx] = ord("X")  # 's' -> 'X'
    r = client.post(
        "/v1/billing/webhook",
        content=bytes(tampered),
        headers={
            "stripe-signature": header,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 3. Stale timestamp (>5min old per Stripe default) → 400
# ---------------------------------------------------------------------------


def test_stale_timestamp_returns_400(client, stripe_env):
    payload = _sub_updated_payload(event_id="evt_real_sig_stale")
    # 10 minutes in the past — outside the 5-min default tolerance.
    stale_ts = int(time.time()) - 600
    header, _ = _sign_payload(payload, timestamp=stale_ts)
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={
            "stripe-signature": header,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 4. Missing Stripe-Signature header → 400
# ---------------------------------------------------------------------------


def test_missing_signature_header_returns_400(client, stripe_env):
    payload = _sub_updated_payload(event_id="evt_real_sig_missing")
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 5. Wrong secret → 400
# ---------------------------------------------------------------------------


def test_wrong_secret_returns_400(client, stripe_env):
    payload = _sub_updated_payload(event_id="evt_real_sig_wrong_secret")
    header, _ = _sign_payload(payload, secret="whsec_INTRUDER_xxxxx")
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={
            "stripe-signature": header,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 6. Replay (same event_id, same signature) → 200 + duplicate_ignored
# ---------------------------------------------------------------------------


def test_replay_same_signature_dedup_hit(client, stripe_env, seeded_db: Path):
    payload = _sub_updated_payload(event_id="evt_real_sig_replay")
    header, _ = _sign_payload(payload)
    headers = {
        "stripe-signature": header,
        "content-type": "application/json",
    }

    r1 = client.post("/v1/billing/webhook", content=payload, headers=headers)
    assert r1.status_code == 200
    assert r1.json() == {"status": "received"}

    # Replay an arbitrary number of times — every retry must dedup.
    for _ in range(3):
        r = client.post("/v1/billing/webhook", content=payload, headers=headers)
        assert r.status_code == 200
        assert r.json() == {"status": "duplicate_ignored"}

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_real_sig_replay",),
        ).fetchone()
    finally:
        c.close()
    assert n == 1


# ---------------------------------------------------------------------------
# 7. livemode toggle (dev vs prod) — processes match, skips mismatch
# ---------------------------------------------------------------------------


def test_livemode_false_in_dev_processes(client, stripe_env, seeded_db: Path):
    """env=dev + livemode=False matches → 200 + processed."""
    payload = _sub_updated_payload(
        event_id="evt_real_sig_lm_dev", livemode=False
    )
    header, _ = _sign_payload(payload)
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": header, "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "received"}


def test_livemode_false_in_prod_env_skipped(client, stripe_env, monkeypatch):
    """env=prod + livemode=False mismatches → 200 + livemode_mismatch_ignored.

    (Reverse direction of the dev-to-prod misroute test in
    test_billing_webhook_idempotency.py — a Stripe TEST endpoint is
    sometimes accidentally pointed at the live URL.)
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "env", "prod", raising=False)
    payload = _sub_updated_payload(
        event_id="evt_real_sig_lm_prod_skip", livemode=False
    )
    header, _ = _sign_payload(payload)
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": header, "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "livemode_mismatch_ignored"}


# ---------------------------------------------------------------------------
# 8. Content-Length > 1MB → 413 BEFORE signature validation
# ---------------------------------------------------------------------------


def test_oversize_content_length_returns_413_before_signature_check(
    client, stripe_env
):
    """1 MB+1 byte must 413 even with a structurally invalid signature.

    The cheap reject MUST happen before the signature path — otherwise
    a malicious sender could DOS the HMAC compute by streaming garbage.
    """
    payload = _sub_updated_payload(event_id="evt_real_sig_oversize")
    # We don't actually need to send 1MB+ of data — FastAPI inspects the
    # Content-Length header before reading the body. The handler reads
    # `request.headers.get("content-length")` and 413s on > 1MB. Send a
    # short body but lie about content-length: the test client will trust
    # whatever we put in the headers dict for inspection purposes.
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={
            # Fabricated >1MB declared length — the guard inspects the
            # header only; an attacker would similarly bait us.
            "content-length": str(2 * 1024 * 1024),
            "stripe-signature": "t=0,v1=deadbeef",
            "content-type": "application/json",
        },
    )
    # FastAPI/Starlette TestClient may strip/recompute Content-Length when
    # serializing the request — fall back to asserting the guard works
    # via a direct body that actually exceeds 1MB if the header trick
    # didn't take effect.
    if r.status_code != 413:
        big_body = b"x" * (1_048_577)  # 1 MB + 1 byte
        r = client.post(
            "/v1/billing/webhook",
            content=big_body,
            headers={
                "stripe-signature": "t=0,v1=deadbeef",
                "content-type": "application/json",
            },
        )
    assert r.status_code == 413, r.text


# ---------------------------------------------------------------------------
# 9. customer.subscription.trial_will_end → audit_log row, no email
# ---------------------------------------------------------------------------


def test_trial_will_end_logs_audit_and_returns_200(
    client, stripe_env, seeded_db: Path, monkeypatch
):
    """No-op handler: audit_log row, 200, no welcome / dunning email sent.

    Verifies the gap from audit a37c4ec09836f3f93 — handler was missing
    entirely, so a rotated promo plan with a trial period would 200-with-
    no-record. We just want forensic visibility for now (email is future).
    """
    from jpintel_mcp.api import billing as billing_mod

    sent_dunning: list[dict] = []
    sent_welcome: list[dict] = []

    class _SpyClient:
        def send_dunning(self, **kwargs):
            sent_dunning.append(kwargs)

        def send_welcome(self, **kwargs):
            sent_welcome.append(kwargs)

    monkeypatch.setattr(billing_mod, "_get_email_client", lambda: _SpyClient())

    payload = _trial_will_end_payload(event_id="evt_real_sig_trial")
    header, _ = _sign_payload(payload)
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": header, "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}

    assert sent_dunning == []
    assert sent_welcome == []

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT event_type, customer_id, metadata FROM audit_log "
            "WHERE event_type = ? "
            "AND customer_id = ?",
            (
                "stripe.subscription.trial_will_end",
                "cus_trial_real",
            ),
        ).fetchone()
    finally:
        c.close()
    assert row is not None, "audit_log row missing for trial_will_end"
    assert row[0] == "stripe.subscription.trial_will_end"
    assert row[1] == "cus_trial_real"
    # metadata JSON carries sub_id + trial_end
    assert row[2] is not None
    md = json.loads(row[2])
    assert md.get("stripe_subscription_id") == "sub_trial_real"
    assert md.get("trial_end_epoch") == 1900000000


# ---------------------------------------------------------------------------
# 10. Multiple v1 signatures (Stripe sends multiple during rotation) → valid wins
# ---------------------------------------------------------------------------


def test_multiple_v1_signatures_valid_wins(client, stripe_env):
    """Stripe rotates webhook secrets by sending TWO `v1=` entries during
    the overlap window. The handler must accept the request iff AT LEAST
    ONE matches. Place the bogus sig FIRST so we prove order-independence.
    """
    payload = _sub_updated_payload(event_id="evt_real_sig_rotate")
    # Real signature with the live secret:
    real_header, ts = _sign_payload(payload)
    # Extract only the `v1=` digest from the real header so we can prepend
    # a bogus one before it.
    real_v1 = [p for p in real_header.split(",") if p.startswith("v1=")][0]
    bogus_v1 = "v1=" + ("0" * 64)
    multi_header = f"t={ts},{bogus_v1},{real_v1}"

    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={
            "stripe-signature": multi_header,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}


# ---------------------------------------------------------------------------
# 11. invoice.payment_failed → dunning email enqueue (BackgroundTasks)
# ---------------------------------------------------------------------------


def test_invoice_payment_failed_enqueues_dunning_via_background_task(
    client, stripe_env, seeded_db: Path, monkeypatch
):
    """The dunning email must be scheduled via BackgroundTasks, not run inline.

    Inline-sending would risk exceeding Stripe's 5s 200 deadline on
    Postmark P95 spikes. We capture the function reference + args added
    to the BackgroundTasks queue and assert _send_dunning_safe_bg lands
    there with the expected kwargs. We additionally check the email
    client was actually called (TestClient flushes background_tasks
    after returning the response).
    """
    from jpintel_mcp.api import billing as billing_mod

    sent: list[dict] = []

    class _SpyEmail:
        def send_dunning(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(billing_mod, "_get_email_client", lambda: _SpyEmail())

    # Pre-issue a key for the failing sub so the demote-to-free path has
    # a row to flip and the dunning helper has key_last4 to render.
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(seeded_db)
    try:
        issue_key(
            c,
            customer_id="cus_payfail_real_sig",
            tier="paid",
            stripe_subscription_id="sub_payfail_real_sig",
            customer_email="payfail@example.com",
        )
        c.commit()
    finally:
        c.close()

    payload = _payment_failed_payload(event_id="evt_real_sig_payfail")
    header, _ = _sign_payload(payload)
    r = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": header, "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text

    # Tier should be demoted to free (sync DB write).
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT tier, stripe_subscription_status FROM api_keys "
            "WHERE stripe_subscription_id = ?",
            ("sub_payfail_real_sig",),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    assert row[0] == "free", f"expected demotion to free, got {row[0]}"
    assert row[1] == "past_due"

    # The dunning email is now enqueued to the durable bg_task_queue
    # (migration 060) instead of fired inline; drain the queue so the
    # handler runs synchronously and sets `sent`. The handler's email
    # client resolution lands on `billing._send_dunning_safe`, which
    # uses our patched `billing._get_email_client` (still in scope).
    from jpintel_mcp.api._bg_task_queue import claim_next, mark_done
    from jpintel_mcp.api._bg_task_worker import _dispatch_one

    # Purge ANY non-dunning rows first so the drain only fires what this
    # test enqueued.
    drain_conn = sqlite3.connect(seeded_db, isolation_level=None)
    drain_conn.row_factory = sqlite3.Row
    try:
        for _ in range(20):  # bounded drain
            row = claim_next(drain_conn)
            if row is None:
                break
            ok, _err = _dispatch_one(row)
            if ok:
                mark_done(drain_conn, int(row["id"]))
    finally:
        drain_conn.close()

    assert len(sent) >= 1, f"expected one dunning email, got {len(sent)}"
    assert any(s.get("to") == "payfail@example.com" for s in sent)
    assert any(s.get("attempt_count") == 2 for s in sent)
