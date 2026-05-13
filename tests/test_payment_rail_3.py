"""Wave 43.4.9+10 — smoke + contract tests for the 3 payment rails.

Covers:

- ACP endpoints (`/v1/billing/acp/*`) with a Stripe stub so the test does
  not hit the real Stripe API.
- x402 origin-side bridge (`/v1/billing/x402/issue_key`,
  `/v1/billing/x402/discovery`) with the edge function mocked out.
- MPP discovery (`/v1/billing/mpp/discovery`) — pure JSON contract.
- Rail aggregate discovery (`/v1/billing/rails/discovery`) — pure JSON.

NO real Stripe / RPC calls in this suite. NO LLM imports anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from jpintel_mcp.api import billing_v2
from jpintel_mcp.billing import acp_integration

_X402_QUOTE_SECRET = "quote-secret"
_X402_RECIPIENT = "0x" + "2" * 40
_X402_PAYER = "0x" + "1" * 40
_X402_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def _edge_like_quote_id(
    agent_id: str,
    *,
    chain: Any = "8453",
    expires_delta_s: int = 300,
) -> str:
    payload = {
        "v": 1,
        "u": "3000",
        "r": _X402_RECIPIENT,
        "p": _X402_PAYER,
        "a": agent_id,
        "e": int(time.time()) + expires_delta_s,
        "c": chain,
        "t": _X402_TOKEN,
    }
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    signature = hmac.new(
        _X402_QUOTE_SECRET.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{encoded}.{signature}"


# ---------- shared fixtures -----------------------------------------------


@pytest.fixture()
def autonomath_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway sqlite file used as autonomath.db for the tests.

    The fixture uses the canonical jpintel schema so payment rail tests
    do not drift from tables such as x402_tx_bind.
    """
    db_path = tmp_path / "autonomath_test.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_DB_PATH", str(db_path))
    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings as _settings
    from jpintel_mcp.db import session as db_session

    monkeypatch.setattr(_settings, "autonomath_db_path", db_path)
    monkeypatch.setattr(_settings, "db_path", db_path)
    db_session.init_db(db_path)
    return db_path


@pytest.fixture()
def client(autonomath_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Minimal FastAPI app that mounts only the billing_v2 router."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_stub")
    monkeypatch.setenv("STRIPE_PRICE_PER_REQUEST", "price_stub")
    monkeypatch.delenv("JPCITE_X402_ORIGIN_SECRET", raising=False)
    # Reload settings so the new env values stick.
    from jpintel_mcp.api import deps as deps_mod
    from jpintel_mcp.config import settings as _settings
    from jpintel_mcp.db import session as db_session

    monkeypatch.setattr(_settings, "stripe_secret_key", "sk_test_stub")
    monkeypatch.setattr(_settings, "stripe_price_per_request", "price_stub")
    for mod in (billing_v2, acp_integration, deps_mod, db_session):
        monkeypatch.setattr(mod, "settings", _settings, raising=False)
    monkeypatch.setattr(billing_v2, "connect_jpintel", db_session.connect)
    monkeypatch.setattr(deps_mod, "connect", db_session.connect)

    app = FastAPI()

    def _override_get_db():
        conn = db_session.connect(autonomath_db)
        try:
            yield conn
        finally:
            conn.close()

    async def _override_require_key(request: Request) -> deps_mod.ApiContext:
        raw = request.headers.get("x-api-key")
        if not raw:
            authorization = request.headers.get("authorization")
            if authorization:
                parts = authorization.split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    raw = parts[1].strip()
        if not raw:
            return deps_mod.ApiContext(key_hash=None, tier="free", customer_id=None)

        key_hash = deps_mod.hash_api_key(raw)
        with db_session.connect(autonomath_db) as conn:
            row = conn.execute(
                "SELECT tier, customer_id, stripe_subscription_id, id, parent_key_id "
                "FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        return deps_mod.ApiContext(
            key_hash=key_hash,
            tier=row["tier"],
            customer_id=row["customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
            key_id=row["id"],
            parent_key_id=row["parent_key_id"],
        )

    app.dependency_overrides[deps_mod.get_db] = _override_get_db
    app.dependency_overrides[deps_mod.require_key] = _override_require_key
    for meta in get_args(billing_v2.ApiContextDep):
        dep = getattr(meta, "dependency", None)
        if dep is not None:
            app.dependency_overrides[dep] = _override_require_key
    app.include_router(billing_v2.router)
    return TestClient(app)


def _issue_paid_test_key(customer_id: str = "cus_portal_test") -> str:
    from jpintel_mcp.api.deps import generate_api_key
    from jpintel_mcp.db.session import connect

    raw, key_hash = generate_api_key()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO api_keys(
                key_hash, customer_id, tier, stripe_subscription_id, created_at
            ) VALUES (?, ?, 'paid', ?, ?)
            """,
            (key_hash, customer_id, f"sub_{customer_id}", datetime.now(UTC).isoformat()),
        )
    return raw


# ---------- MPP discovery (pure JSON) -------------------------------------


def test_mpp_discovery_shape(client: TestClient) -> None:
    """MPP discovery returns the 3-component stack, is_tier=False, JPY."""
    resp = client.get("/v1/billing/mpp/discovery")
    assert resp.status_code == 200
    payload: dict[str, Any] = resp.json()
    assert payload["plan_name"] == "Managed Provider Plan"
    assert payload["is_tier"] is False
    component_ids = [c["id"] for c in payload["components"]]
    assert component_ids == ["volume_rebate", "credit_pack", "yearly_prepay"]
    assert payload["base_rate_jpy"] == 3
    assert payload["base_rate_tax_inclusive_jpy"] == 3.30
    assert "税理士事務所" in payload["target_buyer"]


def test_mpp_discovery_no_tier_keyword_in_payload(client: TestClient) -> None:
    """Anti-regression: MPP payload must never carry a tier vocabulary.

    A future copy edit that slips 'Pro' / 'Free' / 'tier' into the JSON
    breaks the metered-only contract. Catch that here.
    """
    resp = client.get("/v1/billing/mpp/discovery")
    body_text = resp.text
    for forbidden in ("Pro plan", "Free tier", "Starter plan", "tier-badge"):
        assert forbidden not in body_text


# ---------- rails aggregate discovery -------------------------------------


def test_rails_aggregate_discovery(client: TestClient) -> None:
    """Aggregate discovery surfaces all 3 rails with stable kinds."""
    resp = client.get("/v1/billing/rails/discovery")
    assert resp.status_code == 200
    payload: dict[str, Any] = resp.json()
    kinds = [r["kind"] for r in payload["rails"]]
    assert sorted(kinds) == ["acp", "mpp", "x402"]
    for rail in payload["rails"]:
        assert rail["discovery"].startswith("/v1/billing/")
        assert "currency" in rail


# ---------- ACP --------------------------------------------------------------


def test_acp_discovery_payload(client: TestClient) -> None:
    """ACP discovery returns protocol metadata + metered shape."""
    resp = client.get("/v1/billing/acp/discovery")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["protocol"] == "anthropic_commerce_protocol"
    assert payload["version"] == acp_integration.ACP_PROTOCOL_VERSION
    assert payload["pricing"]["unit_price_jpy"] == 3
    assert payload["contract"]["tier_count"] == 0
    assert payload["contract"]["keys_per_customer"] == 1


def test_acp_checkout_smoke(client: TestClient) -> None:
    """ACP checkout creates Stripe session + persists agent bind row."""
    fake_session = {
        "id": "cs_test_acp_1",
        "url": "https://checkout.stripe.com/test_acp_1",
    }
    with patch("stripe.checkout.Session.create", return_value=fake_session):
        resp = client.post(
            "/v1/billing/acp/checkout",
            json={
                "agent_id": "claude_agent_xyz",
                "email": "buyer@example.jp",
                "return_url": "https://jpcite.com/agent/return",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "cs_test_acp_1"
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert body["agent_token"].startswith("acp_")
    # Verify persistence in autonomath_db
    db_path = os.environ["AUTONOMATH_DB_PATH"]
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT agent_id, status, stripe_session_id FROM acp_session_bind WHERE stripe_session_id = ?",
        ("cs_test_acp_1",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "claude_agent_xyz"
    assert row[1] == "pending"


def test_acp_confirm_smoke(client: TestClient) -> None:
    """ACP confirm exchanges a paid session for an API key (once)."""
    fake_session_create = {
        "id": "cs_test_acp_2",
        "url": "https://checkout.stripe.com/test_acp_2",
    }
    fake_session_retrieve = {
        "id": "cs_test_acp_2",
        "payment_status": "paid",
        "customer": "cus_acp_test",
        "subscription": {"id": "sub_acp_test"},
    }
    with patch("stripe.checkout.Session.create", return_value=fake_session_create):
        chk = client.post(
            "/v1/billing/acp/checkout",
            json={
                "agent_id": "claude_agent_confirm",
                "email": "buyer2@example.jp",
                "return_url": "https://jpcite.com/agent/return",
            },
        )
    assert chk.status_code == 200
    token = chk.json()["agent_token"]

    with patch("stripe.checkout.Session.retrieve", return_value=fake_session_retrieve):
        confirm = client.post(
            "/v1/billing/acp/confirm",
            json={"agent_token": token, "session_id": "cs_test_acp_2"},
        )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["api_key"].startswith("jc_")
    assert body["customer_id"] == "cus_acp_test"
    assert body["subscription_id"] == "sub_acp_test"
    assert body["metering"]["unit_price_jpy"] == 3
    assert body["metering"]["model"] == "metered_per_request"


def test_acp_confirm_rejects_unpaid_session(client: TestClient) -> None:
    """A session not in `paid` state is rejected with 403."""
    fake_session_create = {
        "id": "cs_test_unpaid",
        "url": "https://checkout.stripe.com/test_unpaid",
    }
    fake_retrieve_unpaid = {
        "id": "cs_test_unpaid",
        "payment_status": "unpaid",
        "customer": "cus_acp_unpaid",
        "subscription": {"id": "sub_acp_unpaid"},
    }
    with patch("stripe.checkout.Session.create", return_value=fake_session_create):
        chk = client.post(
            "/v1/billing/acp/checkout",
            json={
                "agent_id": "claude_agent_unpaid",
                "email": "x@example.jp",
                "return_url": "https://jpcite.com/agent/return",
            },
        )
    token = chk.json()["agent_token"]

    with patch("stripe.checkout.Session.retrieve", return_value=fake_retrieve_unpaid):
        confirm = client.post(
            "/v1/billing/acp/confirm",
            json={"agent_token": token, "session_id": "cs_test_unpaid"},
        )
    assert confirm.status_code == 403


def test_acp_portal_link_jp_locale(client: TestClient) -> None:
    """Portal link uses the authenticated customer's Stripe id, not body input."""
    fake_portal = {"url": "https://billing.stripe.com/test_portal", "id": "bps_test"}
    called: dict[str, Any] = {}
    raw_key = _issue_paid_test_key("cus_portal_test")

    def _capture_create(**kwargs: Any) -> dict[str, Any]:
        called.update(kwargs)
        return fake_portal

    with patch("stripe.billing_portal.Session.create", side_effect=_capture_create):
        resp = client.post(
            "/v1/billing/acp/portal_link",
            json={"customer_id": "cus_attacker_ignored"},
            headers={"X-API-Key": raw_key},
        )
    assert resp.status_code == 200
    assert resp.json()["portal_url"].startswith("https://billing.stripe.com/")
    assert called.get("locale") == "ja"
    assert called.get("customer") == "cus_portal_test"


def test_acp_portal_link_requires_authenticated_customer(client: TestClient) -> None:
    with patch("stripe.billing_portal.Session.create") as create_mock:
        resp = client.post(
            "/v1/billing/acp/portal_link",
            json={"customer_id": "cus_portal_test"},
        )
    assert resp.status_code == 401
    create_mock.assert_not_called()


def test_acp_portal_link_rejects_untrusted_return_url(client: TestClient) -> None:
    raw_key = _issue_paid_test_key("cus_portal_safe")
    with patch("stripe.billing_portal.Session.create") as create_mock:
        resp = client.post(
            "/v1/billing/acp/portal_link",
            json={"return_url": "https://evil.example/after"},
            headers={"X-API-Key": raw_key},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "portal_return_url_not_allowed"
    create_mock.assert_not_called()


# ---------- x402 ------------------------------------------------------------


def test_x402_discovery_origin(client: TestClient) -> None:
    """Origin-side x402 discovery mirrors the edge."""
    resp = client.get("/v1/billing/x402/discovery")
    assert resp.status_code == 200
    body = resp.json()
    assert body["protocol"] == "x402"
    assert body["settlement_currency"] == "USDC"
    assert body["chain"]["id"] == "8453"
    assert body["pricing"]["unit_price_jpy"] == 3


def test_public_x402_issue_key_cannot_mint_paid_key(client: TestClient) -> None:
    with patch("jpintel_mcp.api.billing_v2.issue_trial_key") as issue_key_mock:
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0x" + "9" * 64,
                "quote_id": "1700000000.deadbeef" + "0" * 24,
                "agent_id": "agent_x402_public",
            },
        )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "x402_origin_unavailable"
    issue_key_mock.assert_not_called()


def test_public_x402_issue_key_rejected_when_origin_secret_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    with patch("jpintel_mcp.api.billing_v2.issue_trial_key") as issue_key_mock:
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0x" + "8" * 64,
                "quote_id": "1700000000.deadbeef" + "0" * 24,
                "agent_id": "agent_x402_public",
            },
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "x402_origin_auth_failed"
    issue_key_mock.assert_not_called()


def test_x402_issue_key_bridge_is_not_public_openapi(client: TestClient) -> None:
    schema = client.app.openapi()
    assert "/v1/billing/x402/issue_key" not in schema["paths"]


def test_x402_issue_key_smoke(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    autonomath_db: Path,
) -> None:
    """Origin bridge issues a bounded one-request key per settled tx_hash."""
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)
    agent_id = "agent_x402_1"
    tx_hash = "0x" + "a" * 64

    resp = client.post(
        "/v1/billing/x402/issue_key",
        json={
            "tx_hash": tx_hash,
            "quote_id": _edge_like_quote_id(agent_id),
            "agent_id": agent_id,
        },
        headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api_key"].startswith("jc_")
    assert body["metering"]["unit_price_jpy"] == 3
    assert body["metering"]["model"] == "x402_one_request"
    assert body["metering"]["request_cap"] == 1

    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(body["api_key"])
    with sqlite3.connect(autonomath_db) as conn:
        row = conn.execute(
            """
            SELECT tier, stripe_subscription_id, monthly_cap_yen, trial_requests_used
            FROM api_keys
            WHERE key_hash = ?
            """,
            (key_hash,),
        ).fetchone()
        tx_row = conn.execute(
            "SELECT api_key_hash FROM x402_tx_bind WHERE tx_hash = ?",
            (tx_hash,),
        ).fetchone()
    assert row is not None
    assert row[0] == "trial"
    assert row[1] is None
    assert row[2] == 3
    assert row[3] == 0
    assert tx_row is not None
    assert tx_row[0] == key_hash


def test_x402_issue_key_idempotent_on_second_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same tx_hash cannot mint a second key."""
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)
    agent_id = "agent_dup"
    tx_hash = "0x" + "d" * 64
    quote_id = _edge_like_quote_id(agent_id)

    first = client.post(
        "/v1/billing/x402/issue_key",
        json={
            "tx_hash": tx_hash,
            "quote_id": quote_id,
            "agent_id": agent_id,
        },
        headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/billing/x402/issue_key",
        json={
            "tx_hash": tx_hash,
            "quote_id": quote_id,
            "agent_id": agent_id,
        },
        headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "tx_already_redeemed"


def test_x402_issue_key_rejects_malformed_quote(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)

    with patch("jpintel_mcp.api.billing_v2.issue_trial_key") as issue_key_mock:
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0x" + "b" * 64,
                "quote_id": "not-a-signed-edge-quote",
                "agent_id": "agent_bad_quote",
            },
            headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_quote_id"
    issue_key_mock.assert_not_called()


def test_x402_issue_key_rejects_agent_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)

    with patch("jpintel_mcp.api.billing_v2.issue_trial_key") as issue_key_mock:
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0x" + "c" * 64,
                "quote_id": _edge_like_quote_id("agent_signed"),
                "agent_id": "agent_attacker",
            },
            headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_quote_id"
    issue_key_mock.assert_not_called()


@pytest.mark.parametrize("chain", [8453, "1", "8454", "84532", "base-sepolia", " 8453"])
def test_x402_issue_key_rejects_non_base_chain_before_mint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    chain: Any,
) -> None:
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)

    with patch("jpintel_mcp.api.billing_v2.issue_trial_key") as issue_key_mock:
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0x" + "e" * 64,
                "quote_id": _edge_like_quote_id("agent_bad_chain", chain=chain),
                "agent_id": "agent_bad_chain",
            },
            headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_quote_id"
    issue_key_mock.assert_not_called()


def test_x402_issue_key_rejects_invalid_tx_hash(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_X402_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("JPCITE_X402_QUOTE_SECRET", _X402_QUOTE_SECRET)
    monkeypatch.setenv("JPCITE_X402_ADDRESS", _X402_RECIPIENT)

    resp = client.post(
        "/v1/billing/x402/issue_key",
        json={
            "tx_hash": "0xshort",
            "quote_id": _edge_like_quote_id("agent_bad_tx"),
            "agent_id": "agent_bad_tx",
        },
        headers={"X-JPCITE-X402-Origin-Secret": "origin-secret"},
    )

    assert resp.status_code == 422


def test_trial_quota_uses_row_cap(autonomath_db: Path) -> None:
    """x402's one-request trial key must not inherit the generic 200 cap."""
    from jpintel_mcp.api.deps import ApiContext, _enforce_quota

    key_hash = "trial_cap_key"
    with sqlite3.connect(autonomath_db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO api_keys(
                key_hash, tier, monthly_cap_yen, trial_expires_at,
                trial_requests_used, created_at
            ) VALUES (?, 'trial', 3, ?, 0, ?)
            """,
            (
                key_hash,
                "2099-01-01T00:00:00+00:00",
                datetime.now(UTC).isoformat(),
            ),
        )
        ctx = ApiContext(key_hash=key_hash, tier="trial", customer_id=None)
        _enforce_quota(conn, ctx)
        with pytest.raises(HTTPException) as exc_info:
            _enforce_quota(conn, ctx)
    assert getattr(exc_info.value, "status_code", None) == 429
    assert exc_info.value.detail["trial_request_cap"] == 1


def test_pages_functions_are_mounted_at_public_paths() -> None:
    """Pages Functions must live at the public routes they protect."""

    expected_exports = {
        Path("functions/api/[[path]].ts"): "../api_proxy",
        Path("functions/api/_middleware.ts"): "../anon_rate_limit_edge",
        Path("functions/x402/[[path]].ts"): "../x402_handler",
        Path("functions/webhook/[customer_key].ts"): "../webhook_router",
        Path("functions/webhook/v2/[customer_key].ts"): "../../webhook_router_v2",
    }
    for path, target in expected_exports.items():
        src = path.read_text(encoding="utf-8")
        assert target in src, f"{path} must export the handler mounted for its public route"


def test_x402_edge_only_burns_terminal_origin_duplicates() -> None:
    """Pending origin reservations must remain retryable at the edge."""

    src = Path("functions/x402_handler.ts").read_text(encoding="utf-8")
    assert "issueResp.ok || issueResp.status === 409" not in src
    assert 'detail === "tx_already_redeemed"' in src
    assert "tx_redemption_in_progress" not in src


def test_x402_edge_public_errors_do_not_expose_config_names() -> None:
    src = Path("functions/x402_handler.ts").read_text(encoding="utf-8")
    assert "String(err)" not in src
    assert "x402_rpc_not_configured" not in src
    assert "x402_origin_auth_not_configured" not in src


def test_x402_edge_quote_binds_agent_and_payer() -> None:
    src = Path("functions/x402_handler.ts").read_text(encoding="utf-8")
    assert 'const agentId = normalizeAgentId(String(body.agent_id ?? ""))' in src
    assert 'const payerAddress = normalizeAddress(String(body.payer_address ?? ""))' in src
    assert (
        'if (!agentId || !payerAddress) return paymentRequiredRaw("quote_identity_required")' in src
    )
    assert "p: payerAddress" in src
    assert "a: agentId" in src
    assert "agentId !== quote.a" in src
    assert 'addressFromTopic(String(topics[1] ?? "")) !== quote.p' in src
    assert "agent_id: agentId" in src
    assert "same quote_id and agent_id" in src
    assert "payer_signature_required" not in src
    assert "payer_signature_verification_unavailable" in src
    assert "reviewed EIP-191/EIP-712 secp256k1 recovery verifier" in src


def test_x402_edge_public_verify_amplification_guards() -> None:
    src = Path("functions/x402_handler.ts").read_text(encoding="utf-8")
    assert "const MAX_X402_JSON_BODY_BYTES = 8 * 1024" in src
    assert "readJsonBodyCapped(request)" in src
    assert "request_body_too_large" in src
    assert "const RPC_FETCH_TIMEOUT_MS = 1200" in src
    assert "AbortController" in src
    assert "signal: controller.signal" in src
    assert "tx_fail:${txHash}" in src
    assert "MAX_FAILED_VERIFY_ATTEMPTS_PER_BUCKET" in src
    assert "verify_attempts_limited" in src
    assert "MAX_VERIFY_RPC_ATTEMPTS_PER_SOURCE_BUCKET" in src
    assert "verify_rpc_attempts_limited" in src
    assert "MAX_QUOTE_ATTEMPTS_PER_BUCKET" in src
    assert "quote_attempts_limited" in src
    assert "function clientSourceBucket(request: Request): string" in src
    assert 'request.headers.get("CF-Connecting-IP")' in src
    assert 'request.headers.get("X-Forwarded-For")' not in src
    assert 'guardBucketKey("quote", [clientBucket])' in src
    assert 'guardBucketKey("verify", [clientBucket])' in src
    assert 'guardBucketKey("verify", [clientBucket, agentId, quoteId])' in src
    assert src.index('guardBucketKey("verify", [clientBucket])') < src.index(
        "fetchRpcReceipt(rpcUrl, txHash)"
    )
    assert "request.json()" not in src


# ---------- contract guards (anti-regression) -----------------------------


def test_no_tier_column_in_acp_table(autonomath_db: Path) -> None:
    """ACP table must never have a tier column — metered-only contract."""
    # Trigger table creation via a no-op connect.
    from jpintel_mcp.billing.acp_integration import _ensure_acp_table

    conn = sqlite3.connect(str(autonomath_db))
    _ensure_acp_table(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(acp_session_bind)").fetchall()]
    conn.close()
    forbidden = {"tier", "plan", "annual_flag", "seat_count", "free_quota"}
    assert not (forbidden & set(cols)), f"forbidden columns appeared: {set(cols) & forbidden}"


def test_no_llm_imports_in_payment_rail_files() -> None:
    """LLM imports must not appear in any of the 3-rail files."""
    files = [
        Path("src/jpintel_mcp/billing/acp_integration.py"),
        Path("src/jpintel_mcp/api/billing_v2.py"),
        Path("functions/x402_handler.ts"),
        Path("docs/billing/mpp_naming.md"),
    ]
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "claude_agent_sdk",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    )
    for fp in files:
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{fp}: forbidden token {needle!r}"
