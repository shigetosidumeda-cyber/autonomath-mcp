"""Stripe invoice.paid / invoice.payment_succeeded → Credit Wallet auto-topup.

Wave 49 G5 contract. Validates the new ``_handle_invoice_paid_for_wallet``
helper that increments ``am_credit_wallet.balance_yen`` by ``amount_paid``
(JPY) when the Stripe Customer carries ``metadata.jpcite_wallet_id``.

Four contracts under test:

* ``test_wallet_topup_applies_balance_on_invoice_paid`` — happy path.
* ``test_wallet_topup_idempotent_on_event_redelivery`` — same event_id
  delivered twice; ledger row stamped once, balance bumped once. Stripe
  must accept both deliveries with 200.
* ``test_wallet_topup_graceful_skip_when_metadata_missing`` — Customer
  carries no ``jpcite_wallet_id``; legacy paths must not be perturbed and
  the wallet ledger stays empty.
* ``test_wallet_topup_via_invoice_payment_succeeded_event`` — Stripe
  accounts that emit ``invoice.payment_succeeded`` instead of
  ``invoice.paid`` must still flow through the same helper.

Stripe SDK calls are monkeypatched throughout; **no live network IO**.
The autonomath.db schema is materialised from ``scripts/migrations/281_credit_wallet.sql``.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_281 = REPO_ROOT / "scripts" / "migrations" / "281_credit_wallet.sql"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def autonomath_db_path(monkeypatch) -> Path:
    """Per-test autonomath.db with migration 281 applied."""
    with tempfile.NamedTemporaryFile(
        prefix="jpintel-wallet-webhook-",
        suffix=".db",
        delete=False,
    ) as tmp:
        path = Path(tmp.name)
    sql = MIG_281.read_text(encoding="utf-8")
    conn = sqlite3.connect(path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(path))
    yield path
    for ext in ("", "-wal", "-shm"):
        target = Path(str(path) + ext)
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so the webhook handler does not 503."""
    from jpintel_mcp.api import admin as admin_mod
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    for settings_obj in (settings, billing_mod.settings, admin_mod.settings):
        monkeypatch.setattr(settings_obj, "stripe_secret_key", "sk_test_dummy", raising=False)
        monkeypatch.setattr(settings_obj, "stripe_webhook_secret", "whsec_dummy", raising=False)
        monkeypatch.setattr(
            settings_obj,
            "stripe_price_per_request",
            "price_metered_test",
            raising=False,
        )
    yield settings


# ---------------------------------------------------------------------------
# Helpers — Stripe SDK monkeypatches (NO live API call)
# ---------------------------------------------------------------------------


def _patch_webhook_construct_event(monkeypatch, event: dict) -> None:
    from jpintel_mcp.api import billing as billing_mod

    def _construct(_body, _sig, _secret, **_kw):
        return event

    monkeypatch.setattr(billing_mod.stripe.Webhook, "construct_event", _construct)


def _patch_customer_retrieve(monkeypatch, *, metadata: dict[str, str] | None) -> list[str]:
    """Stub stripe.Customer.retrieve so the helper can read metadata.

    Returns a list that captures every customer_id the helper retrieves —
    useful for assertions that the wallet path actually fired (or did not).
    """
    from jpintel_mcp.api import billing as billing_mod

    captured: list[str] = []

    def _retrieve(customer_id, **_kw):
        captured.append(customer_id)
        if metadata is None:
            return {"id": customer_id, "metadata": {}}
        return {"id": customer_id, "metadata": dict(metadata)}

    monkeypatch.setattr(billing_mod.stripe.Customer, "retrieve", _retrieve)
    return captured


def _provision_wallet(autonomath_db_path: Path, *, balance_yen: int = 0) -> int:
    """Seed one am_credit_wallet row with a stable owner_token_hash."""
    owner_hash = "a" * 64  # 64-char hex placeholder (CHECK constraint enforces length)
    conn = sqlite3.connect(autonomath_db_path)
    try:
        conn.execute(
            "INSERT INTO am_credit_wallet (owner_token_hash, balance_yen) VALUES (?, ?)",
            (owner_hash, balance_yen),
        )
        conn.commit()
        row = conn.execute(
            "SELECT wallet_id FROM am_credit_wallet WHERE owner_token_hash = ?",
            (owner_hash,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


def _wallet_row(autonomath_db_path: Path, wallet_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(autonomath_db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT wallet_id, balance_yen FROM am_credit_wallet WHERE wallet_id = ?",
            (wallet_id,),
        ).fetchone()
    finally:
        conn.close()


def _topup_txns_for(autonomath_db_path: Path, wallet_id: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(autonomath_db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                "SELECT txn_id, amount_yen, txn_type, note "
                "FROM am_credit_transaction_log "
                "WHERE wallet_id = ? AND txn_type = 'topup' "
                "ORDER BY txn_id ASC",
                (wallet_id,),
            ).fetchall()
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. invoice.paid happy path — wallet metadata present, balance bumped
# ---------------------------------------------------------------------------


def test_wallet_topup_applies_balance_on_invoice_paid(
    client, stripe_env, autonomath_db_path, monkeypatch
) -> None:
    """metadata.jpcite_wallet_id is honored: balance += amount_paid (JPY)."""
    wallet_id = _provision_wallet(autonomath_db_path, balance_yen=0)
    retrievals = _patch_customer_retrieve(
        monkeypatch, metadata={"jpcite_wallet_id": str(wallet_id)}
    )

    event = {
        "id": "evt_wallet_topup_happy",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_wallet_5000",
                "customer": "cus_wallet_happy",
                "amount_paid": 5000,
                # No metadata.kind=credit_pack → the credit_pack branch
                # short-circuits and the subscription branch sees
                # subscription=None so it no-ops too. Only the wallet
                # helper should fire.
                "metadata": {},
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

    assert retrievals == ["cus_wallet_happy"], retrievals

    row = _wallet_row(autonomath_db_path, wallet_id)
    assert row is not None
    assert row["balance_yen"] == 5000

    txns = _topup_txns_for(autonomath_db_path, wallet_id)
    assert len(txns) == 1
    assert txns[0]["amount_yen"] == 5000
    assert txns[0]["txn_type"] == "topup"
    assert "[wallet-stripe-evt:evt_wallet_topup_happy]" in (txns[0]["note"] or "")


# ---------------------------------------------------------------------------
# 2. Idempotency — same event_id delivered twice; balance and ledger only
#    bumped once. Both deliveries return 200 to Stripe.
# ---------------------------------------------------------------------------


def test_wallet_topup_idempotent_on_event_redelivery(
    client, stripe_env, autonomath_db_path, monkeypatch
) -> None:
    """Stripe retries: same event_id → no double-credit."""
    wallet_id = _provision_wallet(autonomath_db_path, balance_yen=0)
    _patch_customer_retrieve(monkeypatch, metadata={"jpcite_wallet_id": str(wallet_id)})

    event = {
        "id": "evt_wallet_topup_replay",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_wallet_2500_replay",
                "customer": "cus_wallet_replay",
                "amount_paid": 2500,
                "metadata": {},
                "subscription": None,
            }
        },
    }
    _patch_webhook_construct_event(monkeypatch, event)

    # 1st delivery — applies.
    wr1 = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr1.status_code == 200, wr1.text

    # 2nd delivery — outer stripe_webhook_events dedup short-circuits
    # before the wallet helper even runs. Stripe still sees 200.
    wr2 = client.post(
        "/v1/billing/webhook",
        content=json.dumps(event).encode("utf-8"),
        headers={"stripe-signature": "t=1,v1=xx"},
    )
    assert wr2.status_code == 200, wr2.text
    assert wr2.json() == {"status": "duplicate_ignored"}

    # Balance bumped EXACTLY once.
    row = _wallet_row(autonomath_db_path, wallet_id)
    assert row is not None
    assert row["balance_yen"] == 2500

    # Ledger has exactly one topup row.
    txns = _topup_txns_for(autonomath_db_path, wallet_id)
    assert len(txns) == 1
    assert txns[0]["amount_yen"] == 2500


# ---------------------------------------------------------------------------
# 3. Graceful skip — Customer carries no metadata.jpcite_wallet_id
# ---------------------------------------------------------------------------


def test_wallet_topup_graceful_skip_when_metadata_missing(
    client, stripe_env, autonomath_db_path, monkeypatch
) -> None:
    """metadata.jpcite_wallet_id absent → wallet untouched, Stripe sees 200."""
    wallet_id = _provision_wallet(autonomath_db_path, balance_yen=0)
    # NO jpcite_wallet_id in customer metadata.
    _patch_customer_retrieve(monkeypatch, metadata={"some_other_key": "value"})

    event = {
        "id": "evt_wallet_skip_no_metadata",
        "type": "invoice.paid",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_wallet_skip_99999",
                "customer": "cus_wallet_no_metadata",
                "amount_paid": 99999,
                "metadata": {},
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

    # Wallet balance untouched, ledger empty.
    row = _wallet_row(autonomath_db_path, wallet_id)
    assert row is not None
    assert row["balance_yen"] == 0

    txns = _topup_txns_for(autonomath_db_path, wallet_id)
    assert txns == []


# ---------------------------------------------------------------------------
# 4. invoice.payment_succeeded event type also routes through the helper
# ---------------------------------------------------------------------------


def test_wallet_topup_via_invoice_payment_succeeded_event(
    client, stripe_env, autonomath_db_path, monkeypatch
) -> None:
    """Stripe accounts emitting invoice.payment_succeeded → wallet topup fires."""
    wallet_id = _provision_wallet(autonomath_db_path, balance_yen=1000)
    _patch_customer_retrieve(monkeypatch, metadata={"jpcite_wallet_id": str(wallet_id)})

    event = {
        "id": "evt_wallet_payment_succeeded",
        "type": "invoice.payment_succeeded",
        "livemode": False,
        "data": {
            "object": {
                "id": "in_wallet_8800",
                "customer": "cus_wallet_payment_succeeded",
                "amount_paid": 8800,
                "metadata": {},
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

    # 1000 + 8800 = 9800
    row = _wallet_row(autonomath_db_path, wallet_id)
    assert row is not None
    assert row["balance_yen"] == 9800

    txns = _topup_txns_for(autonomath_db_path, wallet_id)
    assert len(txns) == 1
    assert txns[0]["amount_yen"] == 8800
    assert "[wallet-stripe-evt:evt_wallet_payment_succeeded]" in (txns[0]["note"] or "")


# ---------------------------------------------------------------------------
# 5. Helper-level dedup line of defence (in case outer dedup is bypassed)
# ---------------------------------------------------------------------------


def test_wallet_helper_dedup_via_ledger_marker(stripe_env, autonomath_db_path, monkeypatch) -> None:
    """If the outer dedup is bypassed, ledger marker still prevents double-credit.

    Belt + braces: calling _handle_invoice_paid_for_wallet twice with the
    same event_id must apply the topup once and report 'duplicate' on the
    second call.
    """
    from jpintel_mcp.api import billing as billing_mod

    wallet_id = _provision_wallet(autonomath_db_path, balance_yen=100)
    _patch_customer_retrieve(monkeypatch, metadata={"jpcite_wallet_id": str(wallet_id)})

    obj = {
        "id": "in_wallet_direct_helper",
        "customer": "cus_direct_helper",
        "amount_paid": 1234,
    }

    r1 = billing_mod._handle_invoice_paid_for_wallet(
        obj=obj, event_id="evt_direct_dedup", etype="invoice.paid"
    )
    assert r1["status"] == "applied"
    assert r1["amount_yen"] == 1234

    r2 = billing_mod._handle_invoice_paid_for_wallet(
        obj=obj, event_id="evt_direct_dedup", etype="invoice.paid"
    )
    assert r2["status"] == "duplicate"

    row = _wallet_row(autonomath_db_path, wallet_id)
    assert row is not None
    assert row["balance_yen"] == 100 + 1234  # not doubled

    txns = _topup_txns_for(autonomath_db_path, wallet_id)
    assert len(txns) == 1
