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

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api import billing_v2
from jpintel_mcp.billing import acp_integration


# ---------- shared fixtures -----------------------------------------------


@pytest.fixture()
def autonomath_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway sqlite file used as autonomath.db for the tests.

    The api keys table from jpintel.db is also stubbed inside the same
    file so `issue_key` calls in the bridge endpoints land somewhere.
    """
    db_path = tmp_path / "autonomath_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL UNIQUE,
            key_last4 TEXT,
            tier TEXT NOT NULL,
            customer_id TEXT,
            stripe_subscription_id TEXT,
            stripe_subscription_status TEXT,
            parent_key_hash TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            revoked_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


@pytest.fixture()
def client(autonomath_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Minimal FastAPI app that mounts only the billing_v2 router."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_stub")
    monkeypatch.setenv("STRIPE_PRICE_PER_REQUEST", "price_stub")
    # Reload settings so the new env values stick.
    from jpintel_mcp.config import settings as _settings

    _settings.stripe_secret_key = "sk_test_stub"
    _settings.stripe_price_per_request = "price_stub"

    app = FastAPI()
    app.include_router(billing_v2.router)
    return TestClient(app)


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
        # Stub issue_key so we don't depend on a real jpintel.db schema +
        # billing.keys side effects beyond the api_keys row insert.
        def _fake_issue_key(conn: sqlite3.Connection, *, customer_id: str, tier: str, stripe_subscription_id: str | None) -> str:
            raw = f"am_test_{customer_id}_{tier}"
            h = hashlib.sha256(raw.encode()).hexdigest()
            conn.execute(
                "INSERT INTO api_keys (key_hash, key_last4, tier, customer_id, stripe_subscription_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (h, raw[-4:], tier, customer_id, stripe_subscription_id),
            )
            conn.commit()
            return raw

        with patch("jpintel_mcp.billing.acp_integration.issue_key", side_effect=_fake_issue_key):
            confirm = client.post(
                "/v1/billing/acp/confirm",
                json={"agent_token": token, "session_id": "cs_test_acp_2"},
            )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["api_key"].startswith("am_test_")
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
    """Portal link forwards locale='ja' per Wave 21 D3."""
    fake_portal = {"url": "https://billing.stripe.com/test_portal", "id": "bps_test"}
    called: dict[str, Any] = {}

    def _capture_create(**kwargs: Any) -> dict[str, Any]:
        called.update(kwargs)
        return fake_portal

    with patch("stripe.billing_portal.Session.create", side_effect=_capture_create):
        resp = client.post(
            "/v1/billing/acp/portal_link",
            json={"customer_id": "cus_portal_test"},
        )
    assert resp.status_code == 200
    assert resp.json()["portal_url"].startswith("https://billing.stripe.com/")
    assert called.get("locale") == "ja"
    assert called.get("customer") == "cus_portal_test"


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


def test_x402_issue_key_smoke(client: TestClient) -> None:
    """Origin bridge issues a metered key per settled tx_hash."""
    def _fake_issue_key(conn: sqlite3.Connection, *, customer_id: str, tier: str, stripe_subscription_id: str | None) -> str:
        raw = f"am_x402_{customer_id[-8:]}"
        h = hashlib.sha256(raw.encode()).hexdigest()
        conn.execute(
            "INSERT INTO api_keys (key_hash, key_last4, tier, customer_id, stripe_subscription_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (h, raw[-4:], tier, customer_id, stripe_subscription_id),
        )
        conn.commit()
        return raw

    with patch("jpintel_mcp.api.billing_v2.issue_key", side_effect=_fake_issue_key):
        resp = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0xabc123def456",
                "quote_id": "1700000000.deadbeef" + "0" * 24,
                "agent_id": "agent_x402_1",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api_key"].startswith("am_x402_")
    assert body["metering"]["unit_price_jpy"] == 3
    assert body["metering"]["model"] == "metered_per_request"


def test_x402_issue_key_idempotent_on_second_call(client: TestClient) -> None:
    """Same tx_hash cannot mint a second key."""
    def _fake_issue_key(conn: sqlite3.Connection, *, customer_id: str, tier: str, stripe_subscription_id: str | None) -> str:
        raw = f"am_idem_{customer_id[-8:]}"
        h = hashlib.sha256(raw.encode()).hexdigest()
        conn.execute(
            "INSERT INTO api_keys (key_hash, key_last4, tier, customer_id, stripe_subscription_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (h, raw[-4:], tier, customer_id, stripe_subscription_id),
        )
        conn.commit()
        return raw

    with patch("jpintel_mcp.api.billing_v2.issue_key", side_effect=_fake_issue_key):
        first = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0xdup_tx_hash_value",
                "quote_id": "1700000000.aaaa" + "0" * 28,
                "agent_id": "agent_dup",
            },
        )
        assert first.status_code == 200
        second = client.post(
            "/v1/billing/x402/issue_key",
            json={
                "tx_hash": "0xdup_tx_hash_value",
                "quote_id": "1700000000.aaaa" + "0" * 28,
                "agent_id": "agent_dup",
            },
        )
    assert second.status_code == 409
    assert second.json()["detail"] == "tx_already_redeemed"


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
