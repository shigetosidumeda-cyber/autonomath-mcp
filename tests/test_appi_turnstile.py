"""M16: APPI disclosure intake must require a Cloudflare Turnstile token.

Background
----------
`POST /v1/privacy/disclosure_request` is anonymous-accessible (APPI §31
rights belong to the natural person, not a paid customer). Without a
captcha a hostile actor could mass-fire fake §31 requests and (a) drown
the operator inbox and (b) generate spurious row noise that would make
legitimate requests harder to triage.

The Turnstile dependency:
  - Skips the check when CLOUDFLARE_TURNSTILE_SECRET is unset (dev / CI).
  - Requires CF-Turnstile-Token header when the secret is set.
  - Calls https://challenges.cloudflare.com/turnstile/v0/siteverify and
    treats any non-success verdict as 401.

This test exercises the secret-set path. The siteverify HTTP call is
stubbed via httpx monkeypatch so we don't reach Cloudflare in tests.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _clear_appi_rows(seeded_db):
    """Each test starts with an empty intake table."""
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM appi_disclosure_requests")
        c.commit()
    finally:
        c.close()
    yield


@pytest.fixture()
def turnstile_secret_set(monkeypatch):
    """Activate the Turnstile check by setting the secret env var."""
    monkeypatch.setenv("CLOUDFLARE_TURNSTILE_SECRET", "1x0000000000000000000000000000000AA")
    yield


@pytest.fixture()
def email_recorder(monkeypatch):
    """Stub the email side-effect so happy-path tests don't reach Postmark."""
    captured: list[dict] = []

    def _fake_notify(**kwargs) -> None:
        captured.append(kwargs)

    from jpintel_mcp.api import appi_disclosure as mod

    monkeypatch.setattr(mod, "_notify_operator_and_requester", _fake_notify)
    return captured


def _valid_body() -> dict:
    return {
        "requester_email": "yamada@example.com",
        "requester_legal_name": "山田 太郎",
        "target_houjin_bangou": "8010001213708",
        "identity_verification_method": "drivers_license",
    }


# ---------------------------------------------------------------------------
# M16 contract
# ---------------------------------------------------------------------------


def test_missing_turnstile_token_returns_401(client, turnstile_secret_set):
    """When the secret is set and the token header is absent → 401."""
    r = client.post("/v1/privacy/disclosure_request", json=_valid_body())
    assert r.status_code == 401, r.text
    detail = r.json().get("detail", "").lower()
    assert "turnstile" in detail or "token" in detail


def test_invalid_turnstile_token_returns_401(
    client,
    turnstile_secret_set,
    monkeypatch,
):
    """Cloudflare siteverify says success=False → 401."""

    class _MockResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"success": False, "error-codes": ["invalid-input-response"]}

    class _MockClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, *, data=None, **_):
            assert "challenges.cloudflare.com" in url
            assert data["secret"]
            assert data["response"] == "invalid_token_xxx"
            return _MockResponse()

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", _MockClient)

    r = client.post(
        "/v1/privacy/disclosure_request",
        json=_valid_body(),
        headers={"CF-Turnstile-Token": "invalid_token_xxx"},
    )
    assert r.status_code == 401, r.text


def test_valid_turnstile_token_allows_request(
    client,
    turnstile_secret_set,
    monkeypatch,
    email_recorder,
):
    """siteverify success=True → handler runs to completion."""

    class _MockResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"success": True}

    class _MockClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, *, data=None, **_):
            return _MockResponse()

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", _MockClient)

    r = client.post(
        "/v1/privacy/disclosure_request",
        json=_valid_body(),
        headers={"CF-Turnstile-Token": "valid_token_xxx"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["request_id"].startswith("appi-")
    # Email side-effect fired exactly once on the happy path.
    assert len(email_recorder) == 1


def test_secret_unset_skips_turnstile(client, monkeypatch, email_recorder):
    """Dev / unconfigured deployment: secret missing → skip the check."""
    monkeypatch.delenv("CLOUDFLARE_TURNSTILE_SECRET", raising=False)
    r = client.post("/v1/privacy/disclosure_request", json=_valid_body())
    assert r.status_code == 201, r.text
    assert len(email_recorder) == 1
