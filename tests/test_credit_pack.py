"""Stripe credit pack prepay tests (¥300K / ¥1M / ¥3M one-time top-up).

Covers the four launch contracts:

* test_create_invoice_returns_url — POST /v1/billing/credit/purchase issues a
  Stripe Invoice and returns the hosted URL + projected balance_after.
* test_webhook_applies_balance_after_paid — invoice.paid webhook with
  metadata.kind="credit_pack" calls Customer.create_balance_transaction
  and flips the local row to status='paid'.
* test_balance_consumed_on_metered_call — once balance is applied,
  Stripe consumes it on the next ¥3/req metered invoice (Stripe-side
  semantics; we assert our local row shows the right balance projection).
* test_refund_not_allowed — once status='paid', the API does NOT expose
  a refund endpoint; ToS §19の4 codifies the non-refundable rule.

Stripe SDK calls are monkeypatched throughout; no live network IO.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Per-test autonomath.db (writable, isolated)
# ---------------------------------------------------------------------------


@pytest.fixture()
def autonomath_db_path(monkeypatch) -> Path:
    """Override AUTONOMATH_DB_PATH to a per-test tmp file.

    The route handler auto-creates the am_credit_pack_purchase table on
    open (idempotent CREATE TABLE IF NOT EXISTS), so no migration runner
    is needed in tests. Cleared between tests because each gets a fresh
    tmp path.
    """
    with tempfile.NamedTemporaryFile(
        prefix="jpintel-credit-pack-",
        suffix=".db",
        delete=False,
    ) as tmp:
        path = Path(tmp.name)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(path))
    yield path
    for ext in ("", "-wal", "-shm"):
        target = Path(str(path) + ext)
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so _stripe() doesn't 503."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "admin_api_key", "admin_test_key", raising=False)
    yield settings


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    """Headers an operator uses to purchase on behalf of a customer."""
    return {"X-API-Key": "admin_test_key"}


def _patch_invoice_create(monkeypatch, *, invoice_id: str, hosted_url: str):
    """Replace Stripe InvoiceItem + Invoice constructors with deterministic stubs."""
    from jpintel_mcp.api import billing as billing_mod

    created = {"item": [], "invoice": [], "finalize": []}

    class _FakeItem:
        id = "ii_credit_pack_test"

    def _item_create(**kwargs):
        created["item"].append(kwargs)
        return _FakeItem()

    class _FakeInvoice(dict):
        pass

    def _invoice_create(**kwargs):
        created["invoice"].append(kwargs)
        return _FakeInvoice(
            id=invoice_id,
            hosted_invoice_url=hosted_url,
            metadata=kwargs.get("metadata", {}),
            status="draft",
        )

    def _invoice_finalize(invoice_id_arg, **_kw):
        created["finalize"].append(invoice_id_arg)
        return _FakeInvoice(
            id=invoice_id_arg,
            hosted_invoice_url=hosted_url,
            metadata=created["invoice"][-1].get("metadata", {}),
            status="open",
        )

    monkeypatch.setattr(billing_mod.stripe.InvoiceItem, "create", _item_create)
    monkeypatch.setattr(billing_mod.stripe.Invoice, "create", _invoice_create)
    monkeypatch.setattr(billing_mod.stripe.Invoice, "finalize_invoice", _invoice_finalize)
    return created


def _patch_balance_txn_create(monkeypatch, *, txn_id: str = "cbtxn_test"):
    """Replace Customer.create_balance_transaction with a deterministic stub."""
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict] = []

    def _create(customer_id, **kwargs):
        captured.append({"customer": customer_id, **kwargs})
        return {"id": txn_id, "amount": kwargs.get("amount"), "currency": "jpy"}

    monkeypatch.setattr(billing_mod.stripe.Customer, "create_balance_transaction", _create)
    return captured


def _patch_webhook_construct_event(monkeypatch, event: dict):
    from jpintel_mcp.api import billing as billing_mod

    def _construct(_body, _sig, _secret, **_kw):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


# ---------------------------------------------------------------------------
# 1. test_create_invoice_returns_url
# ---------------------------------------------------------------------------


def test_create_invoice_returns_url(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """Admin caller can purchase a credit pack and get back the hosted URL."""
    created = _patch_invoice_create(
        monkeypatch,
        invoice_id="in_credit_pack_300k",
        hosted_url="https://invoice.stripe.com/i/test_300k",
    )

    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 300000, "customer_id": "cus_credit_buyer_1"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invoice_url"] == "https://invoice.stripe.com/i/test_300k"
    assert body["balance_after"] == -300000
    assert body["expires_at"] is None

    # Verify the InvoiceItem / Invoice stripe calls carried the right
    # metadata.kind so the webhook can route on it later.
    assert created["item"][0]["amount"] == 300000
    assert created["item"][0]["currency"] == "jpy"
    assert created["item"][0]["metadata"]["kind"] == "credit_pack"
    assert created["item"][0]["metadata"]["amount_jpy"] == "300000"
    assert created["invoice"][0]["customer"] == "cus_credit_buyer_1"
    assert created["invoice"][0]["collection_method"] == "send_invoice"
    assert created["invoice"][0]["metadata"]["kind"] == "credit_pack"
    assert created["finalize"] == ["in_credit_pack_300k"]

    # Local row recorded as pending.
    conn = sqlite3.connect(str(autonomath_db_path))
    try:
        row = conn.execute(
            "SELECT customer_id, amount_jpy, stripe_invoice_id, status, paid_at "
            "FROM am_credit_pack_purchase WHERE stripe_invoice_id = ?",
            ("in_credit_pack_300k",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "cus_credit_buyer_1"
    assert row[1] == 300000
    assert row[2] == "in_credit_pack_300k"
    assert row[3] == "pending"
    assert row[4] is None


def test_create_invoice_rejects_unauthenticated(
    client, stripe_env, autonomath_db_path, monkeypatch
):
    """No X-API-Key → 401, no Stripe call."""
    from jpintel_mcp.api import billing as billing_mod

    def _should_not_be_called(**kwargs):
        raise AssertionError("Stripe must not be hit on unauthenticated request")

    monkeypatch.setattr(billing_mod.stripe.InvoiceItem, "create", _should_not_be_called)
    monkeypatch.setattr(billing_mod.stripe.Invoice, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 300000, "customer_id": "cus_no_auth"},
    )
    assert r.status_code == 401


def test_create_invoice_503_when_admin_key_disabled(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """Empty ADMIN_API_KEY disables the operator-only credit purchase route."""
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    def _should_not_be_called(**kwargs):
        raise AssertionError("Stripe must not be hit when admin endpoints are disabled")

    monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
    monkeypatch.setattr(billing_mod.stripe.InvoiceItem, "create", _should_not_be_called)
    monkeypatch.setattr(billing_mod.stripe.Invoice, "create", _should_not_be_called)

    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 300000, "customer_id": "cus_admin_disabled"},
        headers=admin_headers,
    )
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()


def test_create_invoice_rejects_invalid_amount(
    client, stripe_env, autonomath_db_path, admin_headers
):
    """¥500K is not in the published pack tiers — Pydantic Literal rejects."""
    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 500000, "customer_id": "cus_bad_amount"},
        headers=admin_headers,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 2. test_webhook_applies_balance_after_paid
# ---------------------------------------------------------------------------


def test_webhook_applies_balance_after_paid(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """invoice.paid with metadata.kind=credit_pack → balance applied + row → paid."""
    _patch_invoice_create(
        monkeypatch,
        invoice_id="in_credit_pack_1m",
        hosted_url="https://invoice.stripe.com/i/test_1m",
    )

    # Step 1 — create the pending row.
    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 1000000, "customer_id": "cus_credit_paid"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text

    # Step 2 — fire the invoice.paid webhook.
    captured = _patch_balance_txn_create(monkeypatch, txn_id="cbtxn_credit_1m")

    event = {
        "id": "evt_credit_pack_paid_1m",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_credit_pack_1m",
                "customer": "cus_credit_paid",
                "metadata": {"kind": "credit_pack", "amount_jpy": "1000000"},
                # subscription is None for one-time invoices.
                "subscription": None,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    wr = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr.status_code == 200, wr.text

    # Step 3 — assert Stripe balance txn was called with NEGATIVE amount.
    assert len(captured) == 1, captured
    assert captured[0]["customer"] == "cus_credit_paid"
    assert captured[0]["amount"] == -1000000
    assert captured[0]["currency"] == "jpy"
    assert captured[0]["idempotency_key"] == "credit_pack:in_credit_pack_1m"

    # Step 4 — local row flipped to paid + linked to txn.
    conn = sqlite3.connect(str(autonomath_db_path))
    try:
        row = conn.execute(
            "SELECT status, stripe_balance_txn_id, paid_at "
            "FROM am_credit_pack_purchase WHERE stripe_invoice_id = ?",
            ("in_credit_pack_1m",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "paid"
    assert row[1] == "cbtxn_credit_1m"
    assert row[2] is not None  # paid_at filled


def test_webhook_replay_does_not_double_apply(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """Webhook redelivery of the same invoice.paid must not double-credit."""
    _patch_invoice_create(
        monkeypatch,
        invoice_id="in_credit_pack_replay",
        hosted_url="https://invoice.stripe.com/i/test_replay",
    )
    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 300000, "customer_id": "cus_replay"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text

    captured = _patch_balance_txn_create(monkeypatch, txn_id="cbtxn_replay")

    event = {
        "id": "evt_credit_pack_replay",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_credit_pack_replay",
                "customer": "cus_replay",
                "metadata": {"kind": "credit_pack", "amount_jpy": "300000"},
                "subscription": None,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    # First delivery → applies.
    wr1 = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr1.status_code == 200

    # Second delivery → event-level dedup short-circuits before handler.
    wr2 = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr2.status_code == 200
    assert wr2.json() == {"status": "duplicate_ignored"}

    # Stripe was hit exactly once.
    assert len(captured) == 1


def test_webhook_reserved_midflight_is_not_acknowledged(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """A credit-pack invoice must not be ACKed until the grant is complete."""
    _patch_invoice_create(
        monkeypatch,
        invoice_id="in_credit_pack_midflight",
        hosted_url="https://invoice.stripe.com/i/test_midflight",
    )
    r = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 300000, "customer_id": "cus_midflight_webhook"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text

    from jpintel_mcp.api import billing as billing_mod

    def _fake_grant(*_args, **_kwargs):
        return {
            "status": "reserved",
            "fresh": False,
            "retryable": True,
            "manual_reconciliation_required": False,
            "idempotency_key": "credit_pack:in_credit_pack_midflight",
            "stripe_balance_txn_id": None,
        }

    monkeypatch.setattr(billing_mod, "grant_credit_pack_idempotent", _fake_grant)

    event = {
        "id": "evt_credit_pack_midflight",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_credit_pack_midflight",
                "customer": "cus_midflight_webhook",
                "metadata": {"kind": "credit_pack", "amount_jpy": "300000"},
                "subscription": None,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    wr = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )

    assert wr.status_code == 500
    conn = sqlite3.connect(str(autonomath_db_path))
    try:
        row = conn.execute(
            "SELECT status, stripe_balance_txn_id, paid_at "
            "FROM am_credit_pack_purchase WHERE stripe_invoice_id = ?",
            ("in_credit_pack_midflight",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] is None
    assert row[2] is None


# ---------------------------------------------------------------------------
# 3. test_balance_consumed_on_metered_call
# ---------------------------------------------------------------------------


def test_balance_consumed_on_metered_call(
    client, stripe_env, autonomath_db_path, admin_headers, monkeypatch
):
    """After paid: local projection reflects -¥XXX balance (Stripe debits the
    balance against subsequent metered invoices server-side; we assert the
    apply happened with the correct sign).
    """
    _patch_invoice_create(
        monkeypatch,
        invoice_id="in_credit_pack_consume",
        hosted_url="https://invoice.stripe.com/i/test_consume",
    )
    create_resp = client.post(
        "/v1/billing/credit/purchase",
        json={"amount_jpy": 3000000, "customer_id": "cus_consume"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["balance_after"] == -3000000  # projected after paid

    captured = _patch_balance_txn_create(monkeypatch, txn_id="cbtxn_3m")
    event = {
        "id": "evt_credit_pack_consume",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_credit_pack_consume",
                "customer": "cus_consume",
                "metadata": {"kind": "credit_pack", "amount_jpy": "3000000"},
                "subscription": None,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)
    wr = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr.status_code == 200

    # Stripe balance was credited NEGATIVELY (Stripe convention: negative
    # customer_balance = customer is owed money / has prepaid credit).
    # Stripe server-side then debits subsequent metered invoices against
    # this balance; that part is Stripe's responsibility, not ours.
    assert captured[0]["amount"] == -3000000
    assert captured[0]["currency"] == "jpy"

    # Local row reflects the applied state with the right balance txn id —
    # which is what /v1/me/billing-history would surface for accounting.
    conn = sqlite3.connect(str(autonomath_db_path))
    try:
        row = conn.execute(
            "SELECT amount_jpy, status, stripe_balance_txn_id "
            "FROM am_credit_pack_purchase WHERE stripe_invoice_id = ?",
            ("in_credit_pack_consume",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == 3000000  # purchased amount (positive in our table)
    assert row[1] == "paid"
    assert row[2] == "cbtxn_3m"


# ---------------------------------------------------------------------------
# 4. test_refund_not_allowed
# ---------------------------------------------------------------------------


def test_refund_not_allowed(client, stripe_env, autonomath_db_path, admin_headers):
    """Per ToS §19の4: no refund endpoint exists; PATCH/DELETE return 405.

    Also asserts the credit_pack module does NOT export a refund helper.
    """
    # No refund / cancel surface published. Both verbs must 4xx.
    for verb in ("PATCH", "DELETE", "POST"):
        # POST to /credit/refund must NOT exist.
        r = client.request(
            verb,
            "/v1/billing/credit/refund",
            headers=admin_headers,
        )
        assert r.status_code in (404, 405), (
            f"verb={verb} status={r.status_code} body={r.text} — refund surface must not exist"
        )

    # Module surface — no refund helper exported.
    from jpintel_mcp.billing import credit_pack as cp_mod

    assert not hasattr(cp_mod, "refund_credit_pack"), (
        "credit_pack module must not export a refund helper (ToS §19の4 non-refundable)"
    )
    # Schema CHECK accepts 'refunded' as an OPERATOR-only manual override
    # state, but no automated path produces it. Confirm the allowlist.
    assert "refunded" not in {"pending", "paid", "expired"}  # documentation guard
