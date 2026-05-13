"""Smoke + signature-verification tests for ``/v1/auth/google/{start,callback}``.

The router was added 2026-05-07 in parallel with the GitHub OAuth router.
Wave 2026-05-13 (R2 P1-1) replaced the previous "trust the TLS channel and
base64-decode the JWS middle segment" id_token reader with full JWKS RSA
signature verification. These tests cover both the OAuth flow plumbing AND
the hard-reject signature path so a future regression that re-loosens the
verifier surfaces in CI immediately.

  * ``/start`` happy path (302 redirect to accounts.google.com).
  * ``/start`` JSON-mode (Accept: application/json).
  * ``/start`` 503 when ``GOOGLE_OAUTH_CLIENT_ID`` is unset.
  * ``/callback`` 400 when state is unknown / mismatched.
  * ``/callback`` 400 when ``error=`` query is present.
  * ``/callback`` happy path with a real RSA-signed id_token + injected JWK.
  * ``/callback`` 400 when the id_token signature is FORGED (wrong key).
  * ``/callback`` 400 when the id_token header has no ``kid``.
  * ``/callback`` 502 when the kid is unknown AND the JWKS refresh fails.
  * JWKS cache hit: a second verify call reuses the cached JWK (no fetch).

Network calls are mocked at the ``urllib.request.urlopen`` layer.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import time
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures — ensure ``integration_sync_log`` exists on the test DB
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_integration_sync_log(seeded_db: Path) -> None:
    """The state nonce is persisted in ``integration_sync_log``.

    Migration 105 creates the table; this fixture re-applies the relevant
    CREATE statement idempotently so test runs that order this file before
    ``test_integrations.py`` (which has its own auto-fixture) still find
    the table.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_sync_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_hash    TEXT NOT NULL,
                provider        TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                saved_search_id INTEGER,
                status          TEXT NOT NULL,
                result_count    INTEGER NOT NULL DEFAULT 0,
                error_class     TEXT,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (provider, idempotency_key)
            )
            """
        )
        c.commit()
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _reset_jwks_cache() -> None:
    """Drop the module-level JWKS cache between tests so cache state from
    one case (e.g. an injected forged JWK) cannot leak into the next.
    """
    from jpintel_mcp.api import auth_google

    auth_google._reset_jwks_cache_for_tests()
    yield
    auth_google._reset_jwks_cache_for_tests()


# ---------------------------------------------------------------------------
# Helpers — build a real RS256-signed JWS + matching JWK
# ---------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _int_to_b64url(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return _b64url(value.to_bytes(length, "big"))


def _generate_rsa_key() -> rsa.RSAPrivateKey:
    """Generate a fresh 2048-bit RSA key. Per-test so cache pollution is
    impossible even if the autouse reset hook is misordered.
    """
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_from_public(public_key: rsa.RSAPublicKey, kid: str) -> dict[str, Any]:
    pub_numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _int_to_b64url(pub_numbers.n),
        "e": _int_to_b64url(pub_numbers.e),
    }


def _sign_jws(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    payload: dict[str, Any],
    alg: str = "RS256",
    omit_kid: bool = False,
) -> str:
    """Sign a RS256 JWS over the given payload. Returns the compact JWS."""
    header: dict[str, Any] = {"alg": alg, "typ": "JWT"}
    if not omit_kid:
        header["kid"] = kid
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    hash_for_alg = {"RS256": hashes.SHA256, "RS384": hashes.SHA384, "RS512": hashes.SHA512}[
        alg
    ]
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hash_for_alg())
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _install_jwk(jwk: dict[str, Any]) -> None:
    """Pre-load the JWKS cache so ``/callback`` does not hit the network."""
    from jpintel_mcp.api import auth_google

    with auth_google._jwks_cache_lock:
        auth_google._jwks_cache[jwk["kid"]] = {"jwk": jwk, "fetched_at": int(time.time())}


def _good_payload(client_id: str, *, email: str = "alice@example.com") -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": "https://accounts.google.com",
        "aud": client_id,
        "sub": "1234567890",
        "email": email,
        "email_verified": True,
        "name": "Alice Example",
        "picture": "https://example.com/pic.png",
        "iat": now,
        "exp": now + 600,
    }


class _FakeResp:
    """Minimal context-manager wrapping a byte payload."""

    def __init__(self, payload: bytes | object):
        if isinstance(payload, (bytes, bytearray)):
            self._bytes = bytes(payload)
        else:
            self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._bytes


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


def test_google_oauth_start_redirects_to_google(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    r = client.get("/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-google-client-id" in location
    assert "scope=openid+email+profile" in location
    assert "state=" in location


def test_google_oauth_start_json_mode(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "json-mode-cid")
    r = client.get(
        "/v1/auth/google/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "json-mode-cid" in body["authorize_url"]
    assert isinstance(body["state"], str) and len(body["state"]) >= 32
    assert body["expires_in"] == 600


def test_google_oauth_start_503_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    r = client.get(
        "/v1/auth/google/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 503, r.text


# ---------------------------------------------------------------------------
# /callback — error + state handling
# ---------------------------------------------------------------------------


def _begin_flow(client, monkeypatch, *, client_id: str = "cid") -> str:
    """Walk /start in JSON mode and return the issued state nonce."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csecret")
    r = client.get(
        "/v1/auth/google/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    return r.json()["state"]


def test_google_oauth_callback_invalid_state_400(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csecret")
    r = client.get(
        "/v1/auth/google/callback",
        params={"code": "code", "state": "this-nonce-was-never-issued"},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text


def test_google_oauth_callback_propagates_provider_error(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csecret")
    r = client.get(
        "/v1/auth/google/callback",
        params={"code": "x", "state": "y", "error": "access_denied"},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    assert "access_denied" in r.text


# ---------------------------------------------------------------------------
# /callback — happy path (signed id_token, JWK preloaded)
# ---------------------------------------------------------------------------


def test_google_oauth_callback_happy_path_signed_id_token(client, monkeypatch, seeded_db):
    """A genuine RS256 id_token signed by a key whose JWK is published
    in our cache must be accepted, and the state row consumed.
    """
    client_id = "cid"
    state = _begin_flow(client, monkeypatch, client_id=client_id)

    kid = "kid-happy-1"
    priv = _generate_rsa_key()
    jwk = _jwk_from_public(priv.public_key(), kid)
    _install_jwk(jwk)

    id_token = _sign_jws(priv, kid=kid, payload=_good_payload(client_id))

    token_response = _FakeResp(
        {
            "access_token": "ya29.test_access",
            "id_token": id_token,
            "token_type": "Bearer",
            "expires_in": 3599,
        }
    )

    with patch.object(urllib.request, "urlopen", return_value=token_response):
        r = client.get(
            "/v1/auth/google/callback",
            params={"code": "auth-code-123", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "google"
    assert body["identity"]["email"] in ("alice@example.com", "<email-redacted>")
    assert body["scopes"] == "openid email profile"

    # State row must be deleted (one-shot) so a replay would 400.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT 1 FROM integration_sync_log "
            "WHERE provider = 'google_oauth_state' AND idempotency_key = ?",
            (state,),
        ).fetchone()
    finally:
        c.close()
    assert row is None


# ---------------------------------------------------------------------------
# /callback — signature verification hard-reject paths (R2 P1-1)
# ---------------------------------------------------------------------------


def test_google_oauth_callback_rejects_forged_id_token(client, monkeypatch):
    """An id_token signed by an attacker-controlled key whose `kid`
    happens to match a JWK in our cache (but whose modulus differs!)
    MUST be rejected as InvalidSignature. This is the core regression
    guard for R2 P1-1.
    """
    client_id = "cid"
    state = _begin_flow(client, monkeypatch, client_id=client_id)

    kid = "kid-forge-1"
    real_priv = _generate_rsa_key()
    attacker_priv = _generate_rsa_key()  # different key, same kid claim
    real_jwk = _jwk_from_public(real_priv.public_key(), kid)
    _install_jwk(real_jwk)  # publish the GENUINE key

    # Attacker signs a token with the SAME header kid but with their own
    # private key — and even fills in plausible aud / iss / email_verified
    # claims that the legacy code would have happily accepted.
    forged_payload = _good_payload(client_id, email="attacker@example.com")
    forged_token = _sign_jws(attacker_priv, kid=kid, payload=forged_payload)

    token_response = _FakeResp(
        {
            "access_token": "ya29.attacker_access",
            "id_token": forged_token,
            "token_type": "Bearer",
        }
    )

    with patch.object(urllib.request, "urlopen", return_value=token_response):
        r = client.get(
            "/v1/auth/google/callback",
            params={"code": "auth-code-forged", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert r.status_code == 400, r.text
    assert "signature" in r.text.lower()
    # The fake email MUST NOT have been minted into a session cookie.
    assert "attacker@example.com" not in r.text


def test_google_oauth_callback_rejects_id_token_missing_kid(client, monkeypatch):
    """A JWS that drops the ``kid`` header MUST be rejected — otherwise an
    attacker could induce ambiguous key lookup against the cache.
    """
    client_id = "cid"
    state = _begin_flow(client, monkeypatch, client_id=client_id)

    kid = "kid-real-2"
    priv = _generate_rsa_key()
    jwk = _jwk_from_public(priv.public_key(), kid)
    _install_jwk(jwk)

    # Sign with the real key but OMIT the kid header.
    bad_token = _sign_jws(priv, kid=kid, payload=_good_payload(client_id), omit_kid=True)

    token_response = _FakeResp({"id_token": bad_token, "token_type": "Bearer"})

    with patch.object(urllib.request, "urlopen", return_value=token_response):
        r = client.get(
            "/v1/auth/google/callback",
            params={"code": "auth-code-nokid", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert r.status_code == 400, r.text
    assert "kid" in r.text.lower()


def test_google_oauth_callback_rejects_unknown_kid_when_jwks_unreachable(
    client, monkeypatch
):
    """If the id_token's kid is unknown AND a JWKS refresh fails (network
    down), the callback MUST fail closed rather than accepting the
    token's claims.
    """
    client_id = "cid"
    state = _begin_flow(client, monkeypatch, client_id=client_id)

    priv = _generate_rsa_key()
    unknown_kid = "kid-not-in-jwks"
    token = _sign_jws(priv, kid=unknown_kid, payload=_good_payload(client_id))

    token_response = _FakeResp({"id_token": token, "token_type": "Bearer"})

    call_count = {"token": 0, "jwks": 0}

    def _fake_urlopen(req, *_a, **_k):
        url = getattr(req, "full_url", str(req))
        if "googleapis.com/oauth2/v3/certs" in url:
            call_count["jwks"] += 1
            raise OSError("simulated jwks network failure")
        call_count["token"] += 1
        return token_response

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        r = client.get(
            "/v1/auth/google/callback",
            params={"code": "auth-code-unkkid", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert r.status_code == 502, r.text
    assert call_count["jwks"] >= 1
    assert "kid" in r.text.lower() or "jwks" in r.text.lower()


# ---------------------------------------------------------------------------
# JWKS cache behaviour
# ---------------------------------------------------------------------------


def test_jwks_cache_hit_avoids_second_fetch():
    """Once a JWK is cached, a second verify call MUST NOT trigger
    another JWKS fetch within the TTL window.
    """
    from jpintel_mcp.api import auth_google

    client_id = "cid-cache-test"
    priv = _generate_rsa_key()
    kid = "kid-cache-1"
    jwk = _jwk_from_public(priv.public_key(), kid)

    fetch_calls = {"n": 0}

    def _fake_refresh() -> None:
        fetch_calls["n"] += 1
        with auth_google._jwks_cache_lock:
            auth_google._jwks_cache[kid] = {
                "jwk": jwk,
                "fetched_at": int(time.time()),
            }

    with patch.object(auth_google, "_refresh_jwks_cache", side_effect=_fake_refresh):
        # First verify: cache empty → 1 refresh.
        token_1 = _sign_jws(priv, kid=kid, payload=_good_payload(client_id))
        auth_google._verify_id_token_signature(token_1)
        assert fetch_calls["n"] == 1

        # Second verify: cache populated → 0 additional refresh.
        token_2 = _sign_jws(priv, kid=kid, payload=_good_payload(client_id))
        auth_google._verify_id_token_signature(token_2)
        assert fetch_calls["n"] == 1


def test_jwks_cache_miss_refreshes_then_returns_jwk():
    """On miss, _lookup_jwk must call _refresh_jwks_cache and then return
    the freshly cached entry.
    """
    from jpintel_mcp.api import auth_google

    kid = "kid-miss-1"
    priv = _generate_rsa_key()
    jwk = _jwk_from_public(priv.public_key(), kid)

    def _fake_fetch():
        return [jwk]

    with patch.object(auth_google, "_fetch_google_jwks", side_effect=_fake_fetch):
        result = auth_google._lookup_jwk(kid)

    assert result is not None
    assert result["kid"] == kid
    assert result["n"] == jwk["n"]


def test_jwks_lookup_returns_none_when_refresh_fails_and_no_cache():
    """A cold cache + network error MUST yield None (caller fails closed)."""
    from jpintel_mcp.api import auth_google

    def _broken_fetch():
        raise OSError("simulated outage")

    with patch.object(auth_google, "_fetch_google_jwks", side_effect=_broken_fetch):
        result = auth_google._lookup_jwk("kid-cold")

    assert result is None
