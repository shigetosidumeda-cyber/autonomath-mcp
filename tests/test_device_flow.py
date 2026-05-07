from __future__ import annotations

import copy
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


ORIGIN = "https://jpcite.com"
PRICE_ID = "price_metered_test"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


@pytest.fixture()
def stripe_env(monkeypatch):
    """Hydrate Stripe settings so device_flow._stripe_ready() doesn't 503."""
    from jpintel_mcp.api import device_flow as device_mod
    from jpintel_mcp.config import settings

    for target in (settings, device_mod.settings):
        monkeypatch.setattr(target, "stripe_secret_key", "sk_test_dummy", raising=False)
        monkeypatch.setattr(target, "stripe_webhook_secret", "whsec_dummy", raising=False)
        monkeypatch.setattr(target, "stripe_price_per_request", PRICE_ID, raising=False)
        monkeypatch.setattr(target, "env", "dev", raising=False)
    yield settings


def _authorize(client) -> dict:
    r = client.post(
        "/v1/device/authorize",
        json={},
        headers={"user-agent": "pytest-device-flow"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _checkout_session(auth: dict, *, session_id: str = "cs_device_ok") -> dict:
    return {
        "id": session_id,
        "status": "complete",
        "mode": "subscription",
        "payment_status": "no_payment_required",
        "livemode": False,
        "customer": "cus_device",
        "subscription": "sub_device",
        "metadata": {
            "device_code": auth["device_code"],
            "user_code": auth["user_code"],
        },
        "line_items": {"data": [{"price": {"id": PRICE_ID}}]},
    }


def _patch_session_retrieve(monkeypatch, session: dict, calls: list | None = None) -> None:
    from jpintel_mcp.api import device_flow as device_mod

    def _retrieve(session_id, **kwargs):
        if calls is not None:
            calls.append((session_id, kwargs))
        assert kwargs.get("expand") == ["line_items"]
        out = copy.deepcopy(session)
        out["id"] = session_id
        return out

    monkeypatch.setattr(device_mod.stripe.checkout.Session, "retrieve", _retrieve)


def _complete(client, auth: dict, session_id: str):
    return client.post(
        "/v1/device/complete",
        headers={"origin": ORIGIN},
        json={
            "user_code": auth["user_code"],
            "stripe_checkout_session_id": session_id,
        },
    )


def test_device_complete_validates_checkout_and_issues_paid_key(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    auth = _authorize(client)
    session = _checkout_session(auth, session_id="cs_device_happy")
    calls: list = []
    _patch_session_retrieve(monkeypatch, session, calls)

    r = _complete(client, auth, "cs_device_happy")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert calls == [("cs_device_happy", {"expand": ["line_items"]})]

    token = client.post(
        "/v1/device/token",
        json={"grant_type": GRANT_TYPE, "device_code": auth["device_code"]},
    )
    assert token.status_code == 200, token.text
    raw_key = token.json()["access_token"]
    assert raw_key.startswith("am_device_")

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            """SELECT dc.status, dc.stripe_checkout_session_id,
                      dc.stripe_customer_id, ak.key_hash, ak.tier,
                      ak.customer_id, ak.stripe_subscription_id,
                      ak.key_hash_bcrypt, ak.key_last4
               FROM device_codes dc
               JOIN api_keys ak ON ak.key_hash = dc.linked_api_key_id
               WHERE dc.user_code = ?""",
            (auth["user_code"],),
        ).fetchone()
    finally:
        c.close()

    assert row is not None
    assert row[0] == "activated"
    assert row[1] == "cs_device_happy"
    assert row[2] == "cus_device"
    assert row[3] == hash_api_key(raw_key)
    assert row[4] == "paid"
    assert row[5] == "cus_device"
    assert row[6] == "sub_device"
    assert row[7]
    assert row[8] == raw_key[-4:]


@pytest.mark.parametrize(
    ("case", "expected_status", "detail"),
    [
        ("status", 402, "not complete"),
        ("mode", 400, "not a subscription"),
        ("price", 402, "price mismatch"),
        ("livemode", 403, "livemode mismatch"),
        ("device_metadata", 403, "metadata mismatch"),
        ("user_metadata", 403, "metadata mismatch"),
        ("payment_status", 402, "not paid"),
    ],
)
def test_device_complete_rejects_untrusted_checkout_session_before_key_issue(
    client,
    stripe_env,
    monkeypatch,
    seeded_db: Path,
    case: str,
    expected_status: int,
    detail: str,
):
    auth = _authorize(client)
    session = _checkout_session(auth, session_id=f"cs_bad_{case}")
    session["subscription"] = f"sub_bad_{case}"
    if case == "status":
        session["status"] = "open"
    elif case == "mode":
        session["mode"] = "payment"
    elif case == "price":
        session["line_items"] = {"data": [{"price": {"id": "price_wrong"}}]}
    elif case == "livemode":
        session["livemode"] = True
    elif case == "device_metadata":
        session["metadata"]["device_code"] = "wrong-device-code"
    elif case == "user_metadata":
        session["metadata"]["user_code"] = "ZZZZ-9999"
    elif case == "payment_status":
        session["payment_status"] = "unpaid"
    _patch_session_retrieve(monkeypatch, session)

    r = _complete(client, auth, f"cs_bad_{case}")
    assert r.status_code == expected_status, r.text
    assert detail in r.json()["detail"]

    c = sqlite3.connect(seeded_db)
    try:
        device_row = c.execute(
            "SELECT status, linked_api_key_id FROM device_codes WHERE user_code = ?",
            (auth["user_code"],),
        ).fetchone()
        key_count = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            (f"sub_bad_{case}",),
        ).fetchone()[0]
    finally:
        c.close()

    assert device_row == ("pending", None)
    assert key_count == 0


def test_device_complete_is_idempotent_for_same_session(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    auth = _authorize(client)
    session = _checkout_session(auth, session_id="cs_device_idem")
    session["subscription"] = "sub_device_idem"
    calls: list = []
    _patch_session_retrieve(monkeypatch, session, calls)

    first = _complete(client, auth, "cs_device_idem")
    assert first.status_code == 200, first.text
    second = _complete(client, auth, "cs_device_idem")
    assert second.status_code == 200, second.text
    assert second.json() == {"ok": True}
    assert calls == [("cs_device_idem", {"expand": ["line_items"]})]

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_device_idem",),
        ).fetchone()[0]
    finally:
        c.close()
    assert count == 1


def test_device_complete_rejects_checkout_session_reuse_for_another_code(
    client, stripe_env, monkeypatch, seeded_db: Path
):
    first_auth = _authorize(client)
    first_session = _checkout_session(first_auth, session_id="cs_device_reuse")
    first_session["subscription"] = "sub_device_reuse_1"
    _patch_session_retrieve(monkeypatch, first_session)

    first = _complete(client, first_auth, "cs_device_reuse")
    assert first.status_code == 200, first.text

    second_auth = _authorize(client)
    second_session = _checkout_session(second_auth, session_id="cs_device_reuse")
    second_session["subscription"] = "sub_device_reuse_2"
    calls: list = []
    _patch_session_retrieve(monkeypatch, second_session, calls)

    second = _complete(client, second_auth, "cs_device_reuse")
    assert second.status_code == 409, second.text
    assert "already used" in second.json()["detail"]
    assert calls == []

    c = sqlite3.connect(seeded_db)
    try:
        second_device = c.execute(
            "SELECT status, linked_api_key_id FROM device_codes WHERE user_code = ?",
            (second_auth["user_code"],),
        ).fetchone()
        second_key_count = c.execute(
            "SELECT COUNT(*) FROM api_keys WHERE stripe_subscription_id = ?",
            ("sub_device_reuse_2",),
        ).fetchone()[0]
    finally:
        c.close()
    assert second_device == ("pending", None)
    assert second_key_count == 0


def test_device_complete_rejects_different_session_after_activation(
    client, stripe_env, monkeypatch
):
    auth = _authorize(client)
    session = _checkout_session(auth, session_id="cs_device_original")
    _patch_session_retrieve(monkeypatch, session)
    first = _complete(client, auth, "cs_device_original")
    assert first.status_code == 200, first.text

    second = _complete(client, auth, "cs_device_other")
    assert second.status_code == 409, second.text
    assert "different checkout session" in second.json()["detail"]
