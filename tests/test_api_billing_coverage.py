"""Coverage push for `src/jpintel_mcp/api/billing.py`.

Stream UU — focus on pure helpers + the invoice-paid wallet handler.
Stripe SDK calls are monkey-patched out so no network. NO LLM imports.
NO Stripe live calls. tmp_path + monkeypatch only.

Branches exercised:

* Stripe-obj accessors (`_stripe_obj_id` / `_stripe_value` for dict + attr paths).
* Subscription items walk + tier-price selection (Wave 21 / mig 087 path).
* Subscription-state extractor for webhook subscription.updated.
* Checkout state hash + redirect URL validator (allowlist enforcement).
* Wallet topup helper — schema-missing, no-wallet, no-customer, no-amount,
  duplicate-by-event-id, applied success.
* Credit-pack table bootstrap on a tmp SQLite.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

from jpintel_mcp.api import billing as bm

# ---------------------------------------------------------------------------
# Helper: build a fake Stripe Customer / Subscription / Invoice obj.
# ---------------------------------------------------------------------------


class _StripeAttrObj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# 1. _stripe_obj_id / _stripe_value handle both dict + attr-object shapes
# ---------------------------------------------------------------------------


def test_stripe_obj_id_dict() -> None:
    assert bm._stripe_obj_id({"id": "abc"}) == "abc"


def test_stripe_obj_id_attr_object() -> None:
    obj = _StripeAttrObj(id="zzz")
    assert bm._stripe_obj_id(obj) == "zzz"


def test_stripe_value_dict_and_attr() -> None:
    assert bm._stripe_value({"foo": 1}, "foo") == 1
    assert bm._stripe_value(_StripeAttrObj(bar="x"), "bar") == "x"
    # Missing keys return None on both shapes.
    assert bm._stripe_value({}, "nope") is None
    assert bm._stripe_value(_StripeAttrObj(), "missing") is None


# ---------------------------------------------------------------------------
# 2. _subscription_items walks the dict / .data list shape
# ---------------------------------------------------------------------------


def test_subscription_items_dict_shape() -> None:
    sub = {"items": {"data": [{"id": "si_1"}, {"id": "si_2"}]}}
    out = bm._subscription_items(sub)
    assert [i["id"] for i in out] == ["si_1", "si_2"]


def test_subscription_items_empty_when_no_items() -> None:
    assert bm._subscription_items({"items": None}) == []
    assert bm._subscription_items({}) == []


def test_select_tier_price_id_picks_configured_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configured jpcite metered price wins over an unrelated item."""
    monkeypatch.setattr(bm.settings, "stripe_price_per_request", "price_jpcite")
    sub = {
        "items": {
            "data": [
                {"price": {"id": "price_unrelated"}},
                {"price": {"id": "price_jpcite"}},
            ]
        }
    }
    assert bm._select_tier_price_id(sub) == "price_jpcite"


def test_select_tier_price_id_returns_none_when_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm.settings, "stripe_price_per_request", "price_jpcite")
    sub = {"items": {"data": [{"price": {"id": "price_unrelated"}}]}}
    assert bm._select_tier_price_id(sub) is None


def test_select_tier_price_id_none_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm.settings, "stripe_price_per_request", "")
    sub = {"items": {"data": [{"price": {"id": "price_jpcite"}}]}}
    assert bm._select_tier_price_id(sub) is None


# ---------------------------------------------------------------------------
# 3. _extract_subscription_state: webhook subscription.updated path
# ---------------------------------------------------------------------------


def test_extract_subscription_state_all_fields() -> None:
    s, cpe, cancel = bm._extract_subscription_state(
        {"status": "active", "current_period_end": 1700000000, "cancel_at_period_end": True}
    )
    assert s == "active"
    assert cpe == 1700000000
    assert cancel is True


def test_extract_subscription_state_partial() -> None:
    s, cpe, cancel = bm._extract_subscription_state({"status": "past_due"})
    assert s == "past_due"
    assert cpe is None
    assert cancel is None


def test_extract_subscription_state_non_dict() -> None:
    """Defensive: non-dict input still returns the 3-tuple of Nones."""
    s, cpe, cancel = bm._extract_subscription_state([])  # type: ignore[arg-type]
    assert (s, cpe, cancel) == (None, None, None)


# ---------------------------------------------------------------------------
# 4. _checkout_state_hash deterministic + _validate_checkout_redirect_url
# ---------------------------------------------------------------------------


def test_checkout_state_hash_deterministic() -> None:
    a = bm._checkout_state_hash("abc")
    b = bm._checkout_state_hash("abc")
    assert a == b
    assert len(a) == 64  # sha256 hex
    assert bm._checkout_state_hash("xyz") != a


def test_validate_checkout_redirect_url_rejects_off_allowlist() -> None:
    with pytest.raises(HTTPException) as ei:
        bm._validate_checkout_redirect_url(
            "https://attacker.example/success.html?session_id={CHECKOUT_SESSION_ID}",
            kind="success",
        )
    assert ei.value.status_code == 400


def test_validate_checkout_redirect_url_requires_session_id_token() -> None:
    """success_url MUST include {CHECKOUT_SESSION_ID} substitution token."""
    with pytest.raises(HTTPException) as ei:
        bm._validate_checkout_redirect_url(
            "https://jpcite.com/success.html",
            kind="success",
        )
    assert ei.value.status_code == 400


def test_validate_checkout_redirect_url_happy_path() -> None:
    url = bm._validate_checkout_redirect_url(
        "https://jpcite.com/success.html?session={CHECKOUT_SESSION_ID}",
        kind="success",
    )
    assert url.startswith("https://jpcite.com/")


def test_validate_portal_return_url_rejects_non_https() -> None:
    with pytest.raises(HTTPException):
        bm._validate_portal_return_url("http://jpcite.com/dashboard")


def test_validate_portal_return_url_happy_path() -> None:
    assert (
        bm._validate_portal_return_url("https://jpcite.com/dashboard.html")
        == "https://jpcite.com/dashboard.html"
    )


# ---------------------------------------------------------------------------
# 5. _credit_pack_db_path + _ensure_credit_pack_table (DB bootstrap)
# ---------------------------------------------------------------------------


def test_credit_pack_db_path_uses_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "am.db"))
    p = bm._credit_pack_db_path()
    assert p == tmp_path / "am.db"


def test_ensure_credit_pack_table_creates_schema(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "x.db")
    try:
        bm._ensure_credit_pack_table(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(am_credit_pack_purchase)").fetchall()}
        # Spot-check key columns from the CREATE TABLE statement.
        assert {"id", "customer_id", "amount_jpy", "stripe_invoice_id", "status"} <= cols
        # CHECK on amount_jpy enforces 300k / 1M / 3M only.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_pack_purchase(customer_id, amount_jpy, status) "
                "VALUES (?, ?, ?)",
                ("cus_x", 12345, "pending"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. wallet topup helper — branch coverage of _handle_invoice_paid_for_wallet
# ---------------------------------------------------------------------------


def test_wallet_event_marker_format() -> None:
    assert bm._wallet_event_marker("evt_123") == "[wallet-stripe-evt:evt_123]"


def test_handle_invoice_paid_skipped_no_customer() -> None:
    out = bm._handle_invoice_paid_for_wallet(
        obj={"amount_paid": 1000}, event_id="evt_x", etype="invoice.paid"
    )
    assert out["status"] == "skipped_no_customer"


def test_handle_invoice_paid_skipped_no_amount() -> None:
    out = bm._handle_invoice_paid_for_wallet(
        obj={"customer": "cus_x"}, event_id="evt_x", etype="invoice.paid"
    )
    assert out["status"] == "skipped_no_amount"


def test_handle_invoice_paid_skipped_zero_amount() -> None:
    out = bm._handle_invoice_paid_for_wallet(
        obj={"customer": "cus_x", "amount_paid": 0}, event_id="evt_x", etype="invoice.paid"
    )
    assert out["status"] == "skipped_no_amount"


def test_handle_invoice_paid_skipped_no_wallet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No jpcite_wallet_id metadata on the Customer → graceful skip."""

    def _fake_retrieve(cid):
        return _StripeAttrObj(metadata={})

    monkeypatch.setattr(bm.stripe.Customer, "retrieve", _fake_retrieve)
    out = bm._handle_invoice_paid_for_wallet(
        obj={"customer": "cus_x", "amount_paid": 5000},
        event_id="evt_y",
        etype="invoice.paid",
    )
    assert out["status"] == "skipped_no_wallet"


def test_handle_invoice_paid_wallet_topup_applied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Happy path — wallet row exists, amount is credited, ledger row inserted."""
    # Tmp autonomath.db with wallet + ledger tables.
    db_path = tmp_path / "am.db"
    am_conn = sqlite3.connect(db_path)
    am_conn.row_factory = sqlite3.Row
    am_conn.execute(
        "CREATE TABLE am_credit_wallet ("
        "  wallet_id INTEGER PRIMARY KEY,"
        "  balance_yen INTEGER NOT NULL DEFAULT 0,"
        "  updated_at TEXT)"
    )
    am_conn.execute(
        "CREATE TABLE am_credit_transaction_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  wallet_id INTEGER NOT NULL,"
        "  amount_yen INTEGER NOT NULL,"
        "  txn_type TEXT NOT NULL,"
        "  note TEXT)"
    )
    am_conn.execute("INSERT INTO am_credit_wallet(wallet_id, balance_yen) VALUES (?, ?)", (1, 100))
    am_conn.commit()
    am_conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    # Patch the credit_wallet helpers the handler imports lazily.
    fake_module = types.ModuleType("jpintel_mcp.api.credit_wallet")

    def _open_am_rw():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(conn, name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    fake_module._open_am_rw = _open_am_rw  # type: ignore[attr-defined]
    fake_module._table_exists = _table_exists  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jpintel_mcp.api.credit_wallet", fake_module)

    # Stripe Customer carries the wallet pointer.
    def _fake_retrieve(cid):
        return _StripeAttrObj(metadata={"jpcite_wallet_id": "1"})

    monkeypatch.setattr(bm.stripe.Customer, "retrieve", _fake_retrieve)

    out = bm._handle_invoice_paid_for_wallet(
        obj={"customer": "cus_x", "amount_paid": 3000, "id": "in_1"},
        event_id="evt_w",
        etype="invoice.paid",
    )
    assert out["status"] == "applied"
    assert out["amount_yen"] == 3000
    assert out["wallet_id"] == 1

    # Verify side effect — balance is now 100 + 3000 and ledger has the marker.
    chk = sqlite3.connect(db_path)
    try:
        bal = chk.execute("SELECT balance_yen FROM am_credit_wallet WHERE wallet_id=?", (1,)).fetchone()
        assert bal[0] == 3100
        note = chk.execute("SELECT note FROM am_credit_transaction_log WHERE wallet_id=?", (1,)).fetchone()
        assert "wallet-stripe-evt:evt_w" in note[0]
    finally:
        chk.close()


def test_handle_invoice_paid_duplicate_when_marker_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Idempotency: re-firing the same event_id is a no-op (duplicate)."""
    db_path = tmp_path / "am.db"
    am_conn = sqlite3.connect(db_path)
    am_conn.executescript(
        """
        CREATE TABLE am_credit_wallet (wallet_id INTEGER PRIMARY KEY, balance_yen INTEGER, updated_at TEXT);
        CREATE TABLE am_credit_transaction_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          wallet_id INTEGER NOT NULL,
          amount_yen INTEGER NOT NULL,
          txn_type TEXT NOT NULL,
          note TEXT
        );
        INSERT INTO am_credit_wallet VALUES (2, 0, '2026-01-01T00:00:00Z');
        INSERT INTO am_credit_transaction_log(wallet_id, amount_yen, txn_type, note)
        VALUES (2, 7000, 'topup', 'stripe invoice.paid [wallet-stripe-evt:evt_dup]');
        """
    )
    am_conn.commit()
    am_conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    fake_module = types.ModuleType("jpintel_mcp.api.credit_wallet")

    def _open_am_rw():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    def _table_exists(conn, name):
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            is not None
        )

    fake_module._open_am_rw = _open_am_rw  # type: ignore[attr-defined]
    fake_module._table_exists = _table_exists  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jpintel_mcp.api.credit_wallet", fake_module)

    monkeypatch.setattr(
        bm.stripe.Customer,
        "retrieve",
        lambda cid: _StripeAttrObj(metadata={"jpcite_wallet_id": "2"}),
    )
    out = bm._handle_invoice_paid_for_wallet(
        obj={"customer": "cus_y", "amount_paid": 7000, "id": "in_2"},
        event_id="evt_dup",
        etype="invoice.paid",
    )
    assert out["status"] == "duplicate"
    assert out["wallet_id"] == 2
