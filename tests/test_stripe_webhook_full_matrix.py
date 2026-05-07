"""Stripe webhook full coverage matrix — closes the last two gaps from W6-3.

Audit (W6-3, 2026-05-04) of `tests/test_stripe_*.py` + `tests/test_billing*.py`
+ `tests/test_revoke_cascade.py` found these scope cases COVERED elsewhere:

  - valid signature + 正常 event (subscription.created / invoice.paid /
    payment_failed / subscription.deleted)
        → test_billing.py::test_webhook_subscription_created_does_not_issue_key
        → test_billing.py::test_webhook_invoice_paid_does_not_issue_hidden_key
        → test_billing.py::test_webhook_payment_failed_logs_but_does_not_touch_keys
        → test_billing.py::test_webhook_subscription_deleted_revokes_all_keys_for_subscription
        → test_billing_webhook_signature.py::test_valid_signature_returns_200_and_records_dedup_row
  - invalid signature → 400
        → test_billing.py::test_webhook_rejects_bad_signature
        → test_billing_webhook_signature.py::test_tampered_payload_byte_returns_400
        → test_billing_webhook_signature.py::test_wrong_secret_returns_400
        → test_billing_webhook_signature.py::test_missing_signature_header_returns_400
  - replay attack (>tolerance) → 400 (W1-5 tolerance=60)
        → test_billing_webhook_signature.py::test_stale_timestamp_returns_400 (10min stale)
        → test_webhook_tolerance.py::test_construct_event_called_with_tolerance_60
  - duplicate event_id → 200 + dedup
        → test_stripe_webhook_dedup.py (both cases)
        → test_billing_webhook_idempotency.py::test_duplicate_event_id_returns_200_and_does_not_double_process
        → test_billing.py::test_webhook_is_idempotent_on_replay
  - livemode mismatch → 200 + livemode_mismatch_ignored
        → test_billing_webhook_idempotency.py (3 directions)
        → test_billing_webhook_signature.py::test_livemode_false_in_prod_env_skipped
  - child key cascade revoke (W1-4)
        → test_revoke_cascade.py (4 tests)

Two scope cases had NO direct test before this file:

  1. **charge.refunded** — handler at `api/billing.py:1354` revokes ALL
     active api_keys for the customer + writes `key_revoke` audit_log
     rows. Asserted nowhere (only the ``charge.dispute.created`` close-
     enough sibling is tested in `test_stripe_edge_cases.py`).

  2. **COMMIT failure → ROLLBACK → 500 → Stripe retry recovers** —
     handler at `api/billing.py:1521-1529` rolls back when
     `conn.execute("COMMIT")` raises (disk full / WAL lock storm) and
     re-raises so Stripe retries. The retry must succeed cleanly because
     the dedup row was rolled back too. No prior test exercises this
     path; it is the only way to validate that a sustained COMMIT fault
     does NOT leave the dedup row behind (which would silently swallow
     every subsequent retry as `duplicate_ignored`).

Both cases monkeypatch `stripe.Webhook.construct_event` so the dispatch
mechanics (not the HMAC math, which is covered in
`test_billing_webhook_signature.py`) are the unit under test.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path  # noqa: TC003

import pytest

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so `_stripe()` doesn't 503 on the dispatch path."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "env", "dev", raising=False)
    yield settings


def _patch_construct_event(monkeypatch, event: dict) -> None:
    """Bypass Stripe signature verification; exercise dispatch only.

    M13 (2026-05-04): handler now passes `tolerance=60` kwarg, so the stub
    must accept arbitrary kwargs to avoid TypeError.
    """
    from jpintel_mcp.api import billing as billing_mod

    def _construct(_body, _sig, _secret, **_kw):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


def _post_webhook(client, event: dict):
    return client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )


# ---------------------------------------------------------------------------
# Gap 1 — charge.refunded revokes all customer keys + emits audit_log rows
# ---------------------------------------------------------------------------


def test_charge_refunded_revokes_all_customer_keys_and_audits(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """charge.refunded → every active api_keys row for the customer flips to
    revoked_at IS NOT NULL + one `key_revoke` audit_log row per key.

    Per the handler comment: refunds are a strong fraud / chargeback signal
    so we revoke ALL keys for the customer (not just the subscription tied
    to the refunded charge) because lingering keys present credential-leak
    risk on a closed account. We also need a forensic audit row per key
    so a future "why did my key stop working" support ticket has a trail.

    A foreign-customer key MUST stay alive — the revoke is customer-scoped.
    """
    c = sqlite3.connect(seeded_db)
    try:
        # Two paid keys for the refund target customer (e.g. parent + a
        # separate non-fan-out flat key). Both must die.
        issue_key(
            c,
            customer_id="cus_refund_target",
            tier="paid",
            stripe_subscription_id="sub_refund_a",
        )
        issue_key(
            c,
            customer_id="cus_refund_target",
            tier="paid",
            stripe_subscription_id="sub_refund_b",
        )
        # Foreign customer's key — must stay alive.
        issue_key(
            c,
            customer_id="cus_unrelated",
            tier="paid",
            stripe_subscription_id="sub_unrelated",
        )
        c.commit()
    finally:
        c.close()

    event = {
        "id": "evt_refund_full_matrix",
        "type": "charge.refunded",
        "livemode": False,
        "data": {
            "object": {
                "id": "ch_refund_target_1",
                "object": "charge",
                "customer": "cus_refund_target",
                "amount": 9000,
                "amount_refunded": 9000,
                "currency": "jpy",
                "refunded": True,
            }
        },
    }
    _patch_construct_event(monkeypatch, event)

    r = _post_webhook(client, event)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "received"}

    c = sqlite3.connect(seeded_db)
    try:
        # Both target keys revoked.
        target_rows = c.execute(
            "SELECT revoked_at FROM api_keys WHERE customer_id = ?",
            ("cus_refund_target",),
        ).fetchall()
        assert len(target_rows) == 2
        assert all(
            r[0] is not None for r in target_rows
        ), "every active key for the refunded customer must be revoked"

        # Foreign key untouched.
        (foreign_revoked,) = c.execute(
            "SELECT revoked_at FROM api_keys WHERE customer_id = ?",
            ("cus_unrelated",),
        ).fetchone()
        assert foreign_revoked is None, "charge.refunded must NOT revoke unrelated customers' keys"

        # One audit_log row per revoked key — both tagged with the charge id.
        audit_rows = c.execute(
            "SELECT key_hash, customer_id, metadata FROM audit_log "
            "WHERE event_type = 'key_revoke' AND customer_id = ?",
            ("cus_refund_target",),
        ).fetchall()
    finally:
        c.close()

    assert (
        len(audit_rows) == 2
    ), f"expected 2 key_revoke audit rows (one per key), got {len(audit_rows)}"
    for kh, cid, md_json in audit_rows:
        assert kh, "key_revoke audit row must carry the revoked key_hash"
        assert cid == "cus_refund_target"
        md = json.loads(md_json) if md_json else {}
        assert md.get("reason") == "charge.refunded"
        assert md.get("stripe_charge_id") == "ch_refund_target_1"
        assert md.get("amount_refunded") == 9000


def test_charge_refunded_replay_does_not_double_revoke_or_double_audit(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """Replaying the same charge.refunded event_id is a no-op.

    The dedup short-circuit at `api/billing.py:1095` returns
    `duplicate_ignored` BEFORE the revoke/audit branch runs, so the second
    delivery must:
      * return status="duplicate_ignored"
      * NOT add a second audit_log row
      * leave revoked_at untouched (already set by delivery #1)
    """
    c = sqlite3.connect(seeded_db)
    try:
        issue_key(
            c,
            customer_id="cus_refund_replay",
            tier="paid",
            stripe_subscription_id="sub_refund_replay",
        )
        c.commit()
    finally:
        c.close()

    event = {
        "id": "evt_refund_replay_full_matrix",
        "type": "charge.refunded",
        "livemode": False,
        "data": {
            "object": {
                "id": "ch_refund_replay",
                "object": "charge",
                "customer": "cus_refund_replay",
                "amount": 3000,
                "amount_refunded": 3000,
                "currency": "jpy",
                "refunded": True,
            }
        },
    }
    _patch_construct_event(monkeypatch, event)

    r1 = _post_webhook(client, event)
    assert r1.status_code == 200
    assert r1.json() == {"status": "received"}

    r2 = _post_webhook(client, event)
    assert r2.status_code == 200
    assert r2.json() == {"status": "duplicate_ignored"}

    c = sqlite3.connect(seeded_db)
    try:
        (n_audit,) = c.execute(
            "SELECT COUNT(*) FROM audit_log WHERE event_type = 'key_revoke' AND customer_id = ?",
            ("cus_refund_replay",),
        ).fetchone()
        (n_events,) = c.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id = ?",
            ("evt_refund_replay_full_matrix",),
        ).fetchone()
    finally:
        c.close()

    assert n_audit == 1, f"replay must NOT emit a second key_revoke audit row, got {n_audit}"
    assert n_events == 1, "single dedup row regardless of retry count"


# ---------------------------------------------------------------------------
# Gap 2 — COMMIT failure rolls back the dedup row so Stripe retry recovers
# ---------------------------------------------------------------------------


def test_commit_failure_rolls_back_dedup_row_so_retry_recovers(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    """If `conn.execute("COMMIT")` raises, the dedup row + side-effects roll
    back AND the next Stripe retry processes the event cleanly.

    Handler block: `api/billing.py:1513-1529` — on COMMIT exception we run
    ROLLBACK + re-raise. Stripe will retry within minutes; the retry must
    not be silently swallowed as `duplicate_ignored` (which would happen
    if the dedup row were still present).

    Strategy:
      1. Pre-issue a paid key for the subscription so the
         `customer.subscription.updated` handler has a row to flip.
      2. Override the `get_db` FastAPI dependency to yield a wrapped
         sqlite3 connection whose `.execute()` raises once when invoked
         with the literal string "COMMIT", then passes through normally.
      3. First POST → 500 (handler raises HTTPException). Verify NO
         dedup row exists (rollback worked) — otherwise Stripe retries
         would be swallowed.
      4. Second POST (Stripe retry, same event_id) → 200 received, dedup
         row appears, side-effects applied.

    The dependency is resolved at request time, so `client.app` (the
    FastAPI app) carries the override across both POSTs. We restore the
    original override (if any) in a finally block so the test isolates
    cleanly from neighbouring tests in the same module.

    NOTE on FastAPI behavior: the handler re-raises the COMMIT exception
    AS-IS (`raise` after running ROLLBACK). FastAPI's default exception
    handler maps this to HTTP 500 in real production, but the TestClient
    re-raises server exceptions by default. We construct a separate
    TestClient with `raise_server_exceptions=False` for this test so we
    can observe the production HTTP-500 surface.
    """
    from fastapi.testclient import TestClient

    from jpintel_mcp.api import deps as deps_mod
    from jpintel_mcp.db.session import connect as _real_connect

    # Pre-existing paid key — `subscription.updated` flips its tier cache.
    c = sqlite3.connect(seeded_db)
    try:
        issue_key(
            c,
            customer_id="cus_commit_fail",
            tier="paid",
            stripe_subscription_id="sub_commit_fail",
        )
        c.commit()
    finally:
        c.close()

    # Number of times we've intercepted a "COMMIT" execute. We fail the
    # FIRST one (the dedup-row commit on first delivery) and let every
    # subsequent COMMIT pass through.
    commit_attempts = {"n": 0}

    class _CommitOnceFailConn:
        """Wrap a sqlite3.Connection so the literal SQL "COMMIT" raises once."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kwargs):
            if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                commit_attempts["n"] += 1
                if commit_attempts["n"] == 1:
                    # Simulate a transient SQLite error at COMMIT time. The
                    # handler's except-block must run ROLLBACK + re-raise.
                    raise sqlite3.OperationalError("disk I/O error (simulated)")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    def _override_get_db():
        real = _real_connect()
        try:
            yield _CommitOnceFailConn(real)
        finally:
            real.close()

    app = client.app
    prior = app.dependency_overrides.get(deps_mod.get_db)
    app.dependency_overrides[deps_mod.get_db] = _override_get_db
    # The shared `client` fixture has raise_server_exceptions=True (the
    # TestClient default), so an unhandled OperationalError on COMMIT
    # would propagate through pytest as a raw exception and we couldn't
    # observe the HTTP 500 status. Build a per-test TestClient that
    # surfaces server errors as 500 responses, mirroring real
    # production behavior.
    failing_client = TestClient(app, raise_server_exceptions=False)

    try:
        event = {
            "id": "evt_commit_fail_recovery",
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {
                "object": {
                    "id": "sub_commit_fail",
                    "status": "active",
                    "current_period_end": 1900000000,
                    "cancel_at_period_end": False,
                    "items": {"data": [{"price": {"id": "price_metered_test"}}]},
                }
            },
        }
        _patch_construct_event(monkeypatch, event)

        # ---- Delivery #1: COMMIT fails → handler raises 500 --------------
        r1 = _post_webhook(failing_client, event)
        assert r1.status_code == 500, (
            f"COMMIT failure must surface as 500 so Stripe retries; "
            f"got {r1.status_code} body={r1.text!r}"
        )

        # The dedup row MUST have been rolled back. If it survived, the
        # next Stripe retry would short-circuit as `duplicate_ignored`
        # and the side-effects (tier flip) would be permanently lost.
        c = sqlite3.connect(seeded_db)
        try:
            existing = c.execute(
                "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
                ("evt_commit_fail_recovery",),
            ).fetchone()
        finally:
            c.close()
        assert existing is None, (
            "COMMIT-failure ROLLBACK leaked the dedup row — Stripe "
            "retries would be silently swallowed. This is the bug the "
            "test guards against."
        )

        # ---- Delivery #2: Stripe retry — COMMIT now succeeds → 200 ------
        r2 = _post_webhook(failing_client, event)
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"status": "received"}

        c = sqlite3.connect(seeded_db)
        try:
            # Dedup row now persists with processed_at set.
            row = c.execute(
                "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
                ("evt_commit_fail_recovery",),
            ).fetchone()
            # Pre-existing key tier remains 'paid' after the handler runs
            # (no-op in this case — it was already 'paid' — but the
            # update_tier_by_subscription branch executed without error).
            (final_tier,) = c.execute(
                "SELECT tier FROM api_keys WHERE stripe_subscription_id = ?",
                ("sub_commit_fail",),
            ).fetchone()
        finally:
            c.close()

        assert row is not None, "retry must persist the dedup row"
        assert row[0] is not None, "processed_at must be filled on successful retry"
        assert final_tier == "paid"
        assert commit_attempts["n"] >= 2, (
            f"expected at least 2 COMMIT attempts (1 fail + 1 retry "
            f"success), got {commit_attempts['n']}"
        )
    finally:
        if prior is None:
            app.dependency_overrides.pop(deps_mod.get_db, None)
        else:
            app.dependency_overrides[deps_mod.get_db] = prior
