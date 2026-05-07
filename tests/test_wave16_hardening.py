"""Wave 16 abuse-defense P1 hardening: bcrypt dual-path + CSRF + CORS.

Three independent surfaces, one test file:

1. bcrypt dual-path (`api/deps.require_key`):
    - LEGACY: row with NULL `key_hash_bcrypt` still authenticates on HMAC
      `key_hash` PRIMARY KEY alone. Required so existing customer keys
      issued before migration 073 keep working.
    - NEW: row with non-NULL `key_hash_bcrypt` requires bcrypt verify in
      addition to HMAC match. Defense-in-depth against an exfiltrated DB.

2. CSRF double-submit cookie (`api/me`): /v1/me/billing-portal,
    /v1/me/rotate-key, /v1/session/logout require `X-CSRF-Token` header
    matching `am_csrf` cookie. Missing or mismatched -> 403.

3. CORS_ORIGINS whitelist (`api/middleware/origin_enforcement`): Origin
    header set + not on whitelist -> 403 BEFORE any router (covers regular
    + OPTIONS preflight). Same-origin (no Origin) and webhook callers pass.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _me_module():
    mod = sys.modules.get("jpintel_mcp.api.me")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.me")
    return mod


@pytest.fixture(autouse=True)
def _reset_session_rate_limit(client):
    mod = _me_module()
    mod._reset_session_rate_limit_state()
    mod._reset_billing_portal_rate_limit_state()
    yield
    mod._reset_session_rate_limit_state()
    mod._reset_billing_portal_rate_limit_state()


# ---------------------------------------------------------------------------
# (1) bcrypt dual-path
# ---------------------------------------------------------------------------


def test_bcrypt_new_key_writes_bcrypt_column_and_authenticates(client, seeded_db: Path):
    """New keys issued via `issue_key()` carry a non-NULL `key_hash_bcrypt`
    AND still authenticate end-to-end through `require_key`.
    """
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    raw = issue_key(
        conn,
        customer_id="cus_bcrypt_new",
        tier="paid",
        stripe_subscription_id="sub_bcrypt_new",
    )
    conn.commit()

    row = conn.execute(
        "SELECT key_hash_bcrypt FROM api_keys WHERE key_hash = ?",
        (hash_api_key(raw),),
    ).fetchone()
    conn.close()

    assert row is not None, "issued key not found"
    assert row["key_hash_bcrypt"], "new key MUST carry a non-NULL bcrypt hash"
    assert row["key_hash_bcrypt"].startswith(
        "$2"
    ), "bcrypt hash should start with $2 (bcrypt format)"
    # End-to-end: the key authenticates against `/v1/me` via X-API-Key
    # which routes through require_key + bcrypt verify.
    r = client.get("/v1/programs/search?q=test", headers={"X-API-Key": raw})
    # Either 200 results or 200 empty — a 401 here would mean bcrypt
    # verify rejected a freshly-issued key (regression).
    assert r.status_code != 401, f"freshly-issued key rejected by bcrypt dual-path: {r.text[:200]}"


def test_bcrypt_legacy_key_with_null_bcrypt_still_authenticates(client, seeded_db: Path):
    """A row whose `key_hash_bcrypt` is NULL (representing a key issued
    before migration 073) MUST still pass `require_key` on HMAC PRIMARY
    KEY match alone. Backwards compatibility is non-negotiable.
    """
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    raw = issue_key(
        conn,
        customer_id="cus_bcrypt_legacy",
        tier="paid",
        stripe_subscription_id="sub_bcrypt_legacy",
    )
    # Simulate a legacy row by NULLing the bcrypt column post-issuance.
    conn.execute(
        "UPDATE api_keys SET key_hash_bcrypt = NULL WHERE key_hash = ?",
        (hash_api_key(raw),),
    )
    conn.commit()
    conn.close()

    r = client.get("/v1/programs/search?q=test", headers={"X-API-Key": raw})
    assert (
        r.status_code != 401
    ), f"legacy NULL-bcrypt key rejected (backwards-compat broken): {r.text[:200]}"


# ---------------------------------------------------------------------------
# (2) CSRF double-submit cookie
# ---------------------------------------------------------------------------


@pytest.fixture()
def signed_in_client(client, seeded_db: Path):
    """Sign a paid key in via /v1/session and return (client, csrf_token)."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    raw = issue_key(
        conn,
        customer_id="cus_csrf",
        tier="paid",
        stripe_subscription_id="sub_csrf",
    )
    conn.commit()
    conn.close()

    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200, r.text
    assert "am_session" in client.cookies
    assert "am_csrf" in client.cookies, "session creation MUST set am_csrf companion cookie"
    return client, client.cookies["am_csrf"]


def test_csrf_billing_portal_rejects_missing_token(signed_in_client):
    """POST /v1/me/billing-portal without X-CSRF-Token -> 403."""
    client, _csrf = signed_in_client
    r = client.post("/v1/me/billing-portal")
    assert (
        r.status_code == 403
    ), f"CSRF check missed; expected 403 got {r.status_code}: {r.text[:200]}"


def test_csrf_billing_portal_rejects_mismatched_token(signed_in_client):
    """POST /v1/me/billing-portal with wrong X-CSRF-Token -> 403."""
    client, _csrf = signed_in_client
    r = client.post(
        "/v1/me/billing-portal",
        headers={"X-CSRF-Token": "not-the-real-token"},
    )
    assert r.status_code == 403


def test_csrf_rotate_key_rejects_missing_token(signed_in_client):
    """POST /v1/me/rotate-key without X-CSRF-Token -> 403 (must not rotate)."""
    client, _csrf = signed_in_client
    r = client.post("/v1/me/rotate-key")
    assert r.status_code == 403


def test_csrf_logout_rejects_missing_token(signed_in_client):
    """POST /v1/session/logout without X-CSRF-Token -> 403."""
    client, _csrf = signed_in_client
    r = client.post("/v1/session/logout")
    assert r.status_code == 403


def test_csrf_billing_portal_passes_with_matching_token(signed_in_client):
    """POST /v1/me/billing-portal with matching X-CSRF-Token -> NOT 403.
    (Stripe is unconfigured in the test env so a 503 is expected here;
    the point is the CSRF gate was satisfied and we got past it.)
    """
    client, csrf = signed_in_client
    r = client.post(
        "/v1/me/billing-portal",
        headers={"X-CSRF-Token": csrf},
    )
    # 503 (Stripe unconfigured) or 404 (no_customer) or 200 (real Stripe in
    # CI) — the rejection condition is 403. Anything else means CSRF passed.
    assert r.status_code != 403, f"CSRF rejected a matching token: {r.text[:200]}"


# ---------------------------------------------------------------------------
# (3) CORS_ORIGINS whitelist
# ---------------------------------------------------------------------------


def test_cors_origin_not_on_whitelist_returns_403(client, monkeypatch):
    """A cross-origin GET whose Origin is not on the whitelist -> 403."""
    # Pin the whitelist to production only for the duration of this test.
    from jpintel_mcp.config import settings

    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://autonomath.ai,https://api.jpcite.com",
        raising=False,
    )
    r = client.get("/v1/meta", headers={"Origin": "https://evil.example.com"})
    assert (
        r.status_code == 403
    ), f"non-whitelist Origin not blocked; expected 403 got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("error") == "origin_not_allowed"


def test_cors_origin_on_whitelist_passes(client, monkeypatch):
    """A request whose Origin IS on the whitelist passes the gate."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://autonomath.ai,https://api.jpcite.com",
        raising=False,
    )
    r = client.get("/v1/meta", headers={"Origin": "https://autonomath.ai"})
    assert r.status_code != 403, f"whitelisted Origin was blocked: {r.text[:200]}"


def test_cors_no_origin_header_passes(client, monkeypatch):
    """Same-origin / curl callers (no Origin header) MUST pass through."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://autonomath.ai,https://api.jpcite.com",
        raising=False,
    )
    r = client.get("/v1/meta")
    assert r.status_code != 403


def test_cors_preflight_options_blocked_for_non_whitelist_origin(client, monkeypatch):
    """OPTIONS preflight from a non-whitelist origin -> 403, NOT 200/204."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://autonomath.ai,https://api.jpcite.com",
        raising=False,
    )
    r = client.options(
        "/v1/me/billing-portal",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token,content-type",
        },
    )
    assert r.status_code == 403, (
        f"OPTIONS preflight from non-whitelist Origin not blocked; "
        f"got {r.status_code}: {r.text[:200]}"
    )


def test_cors_webhook_path_exempt_from_origin_check(client, monkeypatch):
    """Stripe webhook MUST NOT be blocked by the origin allow-list — the
    Stripe-Signature header is the auth, not Origin. (Stripe will not send
    an Origin header at all in practice but we exempt the path explicitly
    so an over-zealous browser plugin that injects one cannot brick the
    payment pipeline.)
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://autonomath.ai",
        raising=False,
    )
    # No Stripe-Signature here — we expect the webhook handler to reject
    # with its own 4xx (probably 400), but NOT with 403 from our CORS gate.
    r = client.post(
        "/v1/billing/webhook",
        headers={"Origin": "https://stripe-injected.example"},
        content=b"{}",
    )
    assert r.status_code != 403, f"webhook path was hit by origin gate (regression): {r.text[:200]}"
