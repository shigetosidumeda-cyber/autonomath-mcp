"""Checkout Session タックス系 param のスモークテスト.

`src/jpintel_mcp/api/billing.py::create_checkout` が Stripe Tax + インボイス
制度の要件 (`automatic_tax`, `tax_id_collection`, `billing_address_collection`)
を `STRIPE_TAX_ENABLED=true` の環境で正しく Stripe に渡しているか、
Stripe SDK を monkeypatch したフェイクで検証する。

Pricing モデル: 単一の metered Price (¥3/req 税別・税込 ¥3.30、lookup_key=per_request_v3) 。
2026-04-23 の pivot 以降、tier は free / paid の 2 値のみ。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

SUCCESS_URL = "https://jpcite.com/success.html?session_id={CHECKOUT_SESSION_ID}"
CANCEL_URL = "https://jpcite.com/pricing.html?cancelled=1"


class _FakeSession:
    url = "https://checkout.stripe.test/session/abc"
    id = "cs_test_fake_123"


@pytest.fixture()
def _stripe_env(monkeypatch):
    """Inject dummy Stripe secret + Price ID + STRIPE_TAX_ENABLED=true.

    module-level `settings` singleton is mutated (not re-created) because
    `src/jpintel_mcp/api/billing.py` imports it at import time.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "stripe_tax_enabled", True, raising=False)
    yield settings


def _patch_checkout(monkeypatch) -> list[dict]:
    """Replace stripe.checkout.Session.create with a capture-list fake."""
    from jpintel_mcp.api import billing as billing_mod

    captured: list[dict] = []

    def _create(**kwargs):
        captured.append(kwargs)
        return _FakeSession()

    monkeypatch.setattr(billing_mod.stripe.checkout.Session, "create", _create)
    return captured


def test_checkout_enables_automatic_tax_when_flag_on(client: TestClient, _stripe_env, monkeypatch):
    """STRIPE_TAX_ENABLED=true → automatic_tax={"enabled": True} is sent."""
    captured = _patch_checkout(monkeypatch)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        },
    )
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    kwargs = captured[0]
    assert kwargs["automatic_tax"] == {"enabled": True}


def test_checkout_enables_tax_id_collection_when_flag_on(
    client: TestClient, _stripe_env, monkeypatch
):
    """T-号 / インボイス 買主番号入力欄を Checkout で表示できる状態か."""
    captured = _patch_checkout(monkeypatch)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        },
    )
    assert r.status_code == 200, r.text
    assert captured[0]["tax_id_collection"] == {"enabled": True}


def test_checkout_requires_billing_address_when_flag_on(
    client: TestClient, _stripe_env, monkeypatch
):
    """Stripe Tax は国判定に住所を要求する. billing_address_collection=required."""
    captured = _patch_checkout(monkeypatch)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        },
    )
    assert r.status_code == 200, r.text
    assert captured[0]["billing_address_collection"] == "required"


def test_checkout_preserves_subscription_mode_and_tos_consent(
    client: TestClient, _stripe_env, monkeypatch
):
    """タックス param 追加で既存の mode=subscription / TOS 導線が壊れていないか.

    2026-04-23: consent_collection は live mode で ToS URL 未設定 500 を招くため
    撤去済み. 代替として custom_text.submit.message で ToS / Privacy URL を
    submit ボタン直下に表示する運用に切替えた (billing.py 参照).
    """
    captured = _patch_checkout(monkeypatch)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        },
    )
    assert r.status_code == 200, r.text
    kwargs = captured[0]
    # subscription mode: Stripe auto-creates the Invoice object that hosts
    # the 適格請求書. invoice_creation param must NOT be sent here.
    assert kwargs["mode"] == "subscription"
    assert "invoice_creation" not in kwargs
    # ToS / Privacy 導線: custom_text.submit.message 内で tos.html を案内
    assert "consent_collection" not in kwargs
    assert "custom_text" in kwargs
    assert "submit" in kwargs["custom_text"]
    assert "tos.html" in kwargs["custom_text"]["submit"]["message"]
    assert kwargs["locale"] == "ja"
    # Metered price: NO `quantity` (Stripe 2024-11-20.acacia rejects
    # quantity for metered line items — usage_records drive billing).
    assert kwargs["line_items"] == [{"price": "price_metered_test"}]


def test_checkout_skips_tax_params_when_flag_off(client: TestClient, monkeypatch):
    """STRIPE_TAX_ENABLED=false の dev/CI では タックス param を送らない."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy", raising=False)
    monkeypatch.setattr(settings, "stripe_price_per_request", "price_metered_test", raising=False)
    monkeypatch.setattr(settings, "stripe_tax_enabled", False, raising=False)

    captured = _patch_checkout(monkeypatch)

    r = client.post(
        "/v1/billing/checkout",
        json={
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        },
    )
    assert r.status_code == 200, r.text
    kwargs = captured[0]
    assert "automatic_tax" not in kwargs
    assert "tax_id_collection" not in kwargs
    assert "billing_address_collection" not in kwargs


# ---------------------------------------------------------------------------
# 適格請求書 (qualified invoice) Customer-level footer wiring
# ---------------------------------------------------------------------------
def test_apply_invoice_metadata_writes_custom_fields_and_footer(monkeypatch):
    """INVOICE_REGISTRATION_NUMBER + INVOICE_FOOTER_JA が両方 set のとき
    Stripe Customer.modify が登録番号 + 発行事業者 + footer を送る."""
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "invoice_registration_number", "T8010001213708", raising=False)
    monkeypatch.setattr(
        settings,
        "invoice_footer_ja",
        "適格請求書発行事業者登録番号: T8010001213708 / 軽減税率対象なし (標準10%)",
        raising=False,
    )

    captured: list[tuple[str, dict]] = []

    def _modify(customer_id, **kwargs):
        captured.append((customer_id, kwargs))
        return {"id": customer_id}

    monkeypatch.setattr(billing_mod.stripe.Customer, "modify", _modify)

    billing_mod._apply_invoice_metadata_safe("cus_test_qi")

    assert len(captured) == 1
    cust_id, kwargs = captured[0]
    assert cust_id == "cus_test_qi"
    inv = kwargs["invoice_settings"]
    fields = {f["name"]: f["value"] for f in inv["custom_fields"]}
    assert fields["登録番号"] == "T8010001213708"
    assert fields["発行事業者"] == "Bookyou株式会社"
    assert "T8010001213708" in inv["footer"]
    assert "軽減税率対象なし" in inv["footer"]


def test_apply_invoice_metadata_skips_when_env_unset(monkeypatch):
    """env が空 (dev/CI) の場合 Stripe Customer.modify は呼ばれない."""
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "invoice_registration_number", "", raising=False)
    monkeypatch.setattr(settings, "invoice_footer_ja", "", raising=False)

    called: list[tuple] = []

    def _modify(customer_id, **kwargs):
        called.append((customer_id, kwargs))

    monkeypatch.setattr(billing_mod.stripe.Customer, "modify", _modify)

    billing_mod._apply_invoice_metadata_safe("cus_test_skip")

    assert called == []


def test_apply_invoice_metadata_swallows_stripe_errors(monkeypatch):
    """Stripe SDK が落ちても webhook idempotency を壊さない."""
    from jpintel_mcp.api import billing as billing_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "invoice_registration_number", "T8010001213708", raising=False)
    monkeypatch.setattr(settings, "invoice_footer_ja", "適格請求書", raising=False)

    def _modify(customer_id, **kwargs):
        raise RuntimeError("simulated stripe outage")

    monkeypatch.setattr(billing_mod.stripe.Customer, "modify", _modify)

    # Must NOT raise — webhook idempotency requirement.
    billing_mod._apply_invoice_metadata_safe("cus_test_err")
