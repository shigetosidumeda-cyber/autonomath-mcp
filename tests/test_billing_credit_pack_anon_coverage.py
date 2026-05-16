"""Coverage tests for `jpintel_mcp.billing.credit_pack_anon` (lane #5).

Covers the pure-function surface of the anonymous credit-pack module:
pack size validation, metadata helpers, Stripe Checkout session creation
(via a fake stripe client). NO LLM, NO real Stripe network IO.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from jpintel_mcp.billing import credit_pack_anon as cpa

# ---------------------------------------------------------------------------
# pack_req_count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,expected",
    [(300, 100), (1_500, 500), (3_000, 1_000)],
)
def test_pack_req_count_returns_canonical_count(amount: int, expected: int) -> None:
    assert cpa.pack_req_count(amount) == expected


def test_pack_req_count_rejects_unknown_amount() -> None:
    with pytest.raises(ValueError, match="amount_jpy must be one of"):
        cpa.pack_req_count(500)


def test_pack_req_count_rejects_zero() -> None:
    with pytest.raises(ValueError):
        cpa.pack_req_count(0)


# ---------------------------------------------------------------------------
# create_anon_credit_pack_checkout
# ---------------------------------------------------------------------------


class _FakeSessions:
    """Mimic stripe.checkout.Session — captures the create() kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"id": "cs_test_anon_pack", "url": "https://stripe.test/checkout/anon"}


def _fake_stripe() -> Any:
    sessions = _FakeSessions()
    checkout = types.SimpleNamespace(Session=sessions)
    return types.SimpleNamespace(checkout=checkout, _sessions=sessions)


def test_create_checkout_session_returns_stripe_object() -> None:
    stripe = _fake_stripe()
    result = cpa.create_anon_credit_pack_checkout(
        stripe,
        300,
        success_url="https://example.com/ok",
        cancel_url="https://example.com/no",
    )
    assert result["id"] == "cs_test_anon_pack"
    call = stripe._sessions.calls[0]
    assert call["mode"] == "payment"
    assert call["success_url"] == "https://example.com/ok"
    assert call["cancel_url"] == "https://example.com/no"
    # Metadata kind tag must match the canonical constant.
    assert call["metadata"]["kind"] == cpa.ANON_CREDIT_PACK_METADATA_KIND
    assert call["metadata"]["amount_jpy"] == "300"
    assert call["metadata"]["req_count"] == "100"
    # payment_intent metadata mirrors session metadata.
    assert call["payment_intent_data"]["metadata"]["kind"] == cpa.ANON_CREDIT_PACK_METADATA_KIND


def test_create_checkout_session_idempotency_key_propagated() -> None:
    stripe = _fake_stripe()
    cpa.create_anon_credit_pack_checkout(
        stripe,
        1_500,
        success_url="https://example.com/ok",
        cancel_url="https://example.com/no",
        idempotency_key="anon-test-key-1",
    )
    assert stripe._sessions.calls[0]["idempotency_key"] == "anon-test-key-1"


def test_create_checkout_session_rejects_unknown_amount() -> None:
    stripe = _fake_stripe()
    with pytest.raises(ValueError):
        cpa.create_anon_credit_pack_checkout(
            stripe,
            999,
            success_url="https://example.com/ok",
            cancel_url="https://example.com/no",
        )
    assert stripe._sessions.calls == []


def test_create_checkout_line_items_use_jpy_unit_amount() -> None:
    stripe = _fake_stripe()
    cpa.create_anon_credit_pack_checkout(
        stripe,
        3_000,
        success_url="https://example.com/ok",
        cancel_url="https://example.com/no",
    )
    line = stripe._sessions.calls[0]["line_items"][0]
    assert line["quantity"] == 1
    assert line["price_data"]["currency"] == "jpy"
    assert line["price_data"]["unit_amount"] == 3_000


# ---------------------------------------------------------------------------
# metadata_req_count / is_anon_credit_pack_event
# ---------------------------------------------------------------------------


def test_metadata_req_count_reads_dict() -> None:
    obj = {"metadata": {"req_count": "100"}}
    assert cpa.metadata_req_count(obj) == 100


def test_metadata_req_count_reads_object() -> None:
    obj = types.SimpleNamespace(metadata={"req_count": "500"})
    assert cpa.metadata_req_count(obj) == 500


def test_metadata_req_count_returns_none_when_absent() -> None:
    assert cpa.metadata_req_count({"metadata": {}}) is None
    assert cpa.metadata_req_count({}) is None
    assert cpa.metadata_req_count(types.SimpleNamespace()) is None


def test_metadata_req_count_returns_none_on_non_integer() -> None:
    obj = {"metadata": {"req_count": "abc"}}
    assert cpa.metadata_req_count(obj) is None


def test_is_anon_credit_pack_event_true_when_kind_matches() -> None:
    obj = {"metadata": {"kind": cpa.ANON_CREDIT_PACK_METADATA_KIND}}
    assert cpa.is_anon_credit_pack_event(obj) is True


def test_is_anon_credit_pack_event_false_when_kind_mismatches() -> None:
    obj = {"metadata": {"kind": "credit_pack"}}
    assert cpa.is_anon_credit_pack_event(obj) is False


def test_is_anon_credit_pack_event_false_when_metadata_missing() -> None:
    assert cpa.is_anon_credit_pack_event({}) is False
    assert cpa.is_anon_credit_pack_event(types.SimpleNamespace(metadata=None)) is False


# ---------------------------------------------------------------------------
# default URL helpers respect env override
# ---------------------------------------------------------------------------


def test_default_success_url_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_CREDIT_PACK_SUCCESS_URL", "https://custom.example/yes")
    assert cpa.default_success_url() == "https://custom.example/yes"


def test_default_cancel_url_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_CREDIT_PACK_CANCEL_URL", "https://custom.example/cancel")
    assert cpa.default_cancel_url() == "https://custom.example/cancel"


def test_default_success_url_falls_back_to_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_CREDIT_PACK_SUCCESS_URL", raising=False)
    assert cpa.default_success_url().startswith("https://jpcite.com/")


def test_default_cancel_url_falls_back_to_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_CREDIT_PACK_CANCEL_URL", raising=False)
    assert cpa.default_cancel_url().startswith("https://jpcite.com/")


# ---------------------------------------------------------------------------
# Purchase request / response models
# ---------------------------------------------------------------------------


def test_purchase_request_accepts_valid_amount() -> None:
    req = cpa.AnonCreditPackPurchaseRequest(amount_jpy=300)
    assert req.amount_jpy == 300
    assert req.return_url is None


def test_purchase_request_rejects_unknown_amount() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        cpa.AnonCreditPackPurchaseRequest(amount_jpy=500)  # type: ignore[arg-type, unused-ignore]


def test_purchase_response_serializes() -> None:
    resp = cpa.AnonCreditPackPurchaseResponse(
        checkout_url="https://stripe.example/checkout",
        req_count=100,
        amount_jpy=300,
    )
    payload = resp.model_dump()
    assert payload["checkout_url"] == "https://stripe.example/checkout"
    assert payload["req_count"] == 100
    assert payload["amount_jpy"] == 300


# ---------------------------------------------------------------------------
# Pack lineup invariants (regression guard against silent pricing drift)
# ---------------------------------------------------------------------------


def test_pack_sizes_are_exactly_three() -> None:
    assert frozenset({300, 1_500, 3_000}) == cpa.ANON_PACK_SIZES_JPY


def test_pack_req_count_consistent_with_three_yen_per_req() -> None:
    """Every pack must price at exactly ¥3/req — no hidden discount tier."""
    for amount in cpa.ANON_PACK_SIZES_JPY:
        assert cpa.ANON_PACK_REQ_COUNT[amount] * 3 == amount
