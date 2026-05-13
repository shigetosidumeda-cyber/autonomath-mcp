"""Contract tests for EdgeHeaderSanitizationMiddleware (Defense-in-Depth).

Pin the trust model defined in
``src/jpintel_mcp/api/middleware/edge_header_sanitization.py`` so a future
refactor cannot regress the CF-* spoofing guard:

1. Direct-to-origin request with no trust signal — every ``CF-*`` header
   is stripped from ``request.scope["headers"]`` and downstream handlers
   see them as absent (``request.headers.get("cf-ipcountry") is None``).
2. Spoofed ``CF-IPCountry: KP`` from an untrusted caller is treated as
   if the header was never sent (KP example chosen because country-gated
   features would otherwise short-circuit on it).
3. Request carrying a valid signed ``X-Edge-Auth`` HMAC token preserves
   the CF-* headers — the trusted edge can still attribute the caller.
4. Request from a peer IP inside ``JPCITE_CF_TRUSTED_PEER_IPS`` preserves
   the CF-* headers — the per-deploy allowlist works without a signed
   header secret.
5. Replay protection: a signed token older than 300s is rejected.
6. Tamper protection: a signed token with the wrong HMAC is rejected.
7. ``cf-ja3-hash`` (consumed by ``anon_limit._ja3_hash`` for the 4-axis
   fingerprint) participates in the same gate so a direct caller cannot
   forge a JA3 fingerprint to fool the abuse fingerprint.
8. ``_strip_cf_headers_inplace`` unit-level: scope-mutation semantics.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from jpintel_mcp.api.middleware.edge_header_sanitization import (
    _CF_HEADERS_TO_STRIP,
    EdgeHeaderSanitizationMiddleware,
    _peer_is_trusted,
    _strip_cf_headers_inplace,
    _verify_signed_edge_header,
)


def _build_app() -> FastAPI:
    """Minimal FastAPI app mounting only the sanitizer + an echo route.

    Keeping the app surface small avoids depending on jpcite's full
    middleware stack (origin enforcement, anon limit, etc.). The echo
    route returns whatever the handler sees AFTER middleware mutation,
    which is the contract under test.
    """
    app = FastAPI()
    app.add_middleware(EdgeHeaderSanitizationMiddleware)

    @app.get("/_probe")
    async def _probe(request: Request) -> dict[str, object]:
        # Surface back to the test:
        # 1. Every CF-* header value the handler can still read (None if stripped).
        # 2. The strip count stashed on request.state by the middleware.
        cf_headers = {
            name.decode("ascii"): request.headers.get(name.decode("ascii"))
            for name in _CF_HEADERS_TO_STRIP
        }
        return {
            "cf_headers": cf_headers,
            "stripped_count": getattr(request.state, "edge_headers_stripped", None),
        }

    return app


@pytest.fixture()
def app_client() -> Iterator[TestClient]:
    """Fresh app + client per test so env mutations stay scoped."""
    yield TestClient(_build_app())


@pytest.fixture(autouse=True)
def _clear_edge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin a known clean env per test so the default-deny posture holds.

    Tests that want a secret or peer allowlist set it inline via
    monkeypatch.setenv.
    """
    monkeypatch.delenv("JPCITE_EDGE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("JPCITE_CF_TRUSTED_PEER_IPS", raising=False)


# ---------------------------------------------------------------------------
# Direct-to-origin: every CF-* header is stripped.
# ---------------------------------------------------------------------------


def test_direct_request_strips_all_cf_headers(app_client: TestClient) -> None:
    """Default-deny: an untrusted caller cannot have ANY CF-* header
    reach the handler."""
    spoofed = {
        "CF-Connecting-IP": "1.2.3.4",
        "CF-IPCountry": "KP",  # spoofed country
        "CF-Ray": "8a000000abcd-NRT",
        "CF-Visitor": '{"scheme":"https"}',
        "CF-Worker": "evil-edge.example",
        "CF-JA3-Hash": "deadbeef" * 4,
    }
    r = app_client.get("/_probe", headers=spoofed)
    assert r.status_code == 200, r.text
    body = r.json()
    # Every CF-* header MUST be invisible to the handler.
    for name, value in body["cf_headers"].items():
        assert value is None, f"header {name!r} leaked into handler: {value!r}"
    # And the middleware must have logged the strip count.
    assert body["stripped_count"] == len(spoofed)


def test_spoofed_cf_ipcountry_kp_is_invisible_to_handler(app_client: TestClient) -> None:
    """Pin the exact spec scenario: ``CF-IPCountry: KP`` from a direct
    caller is treated as if the header were absent."""
    r = app_client.get("/_probe", headers={"CF-IPCountry": "KP"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cf_headers"]["cf-ipcountry"] is None
    assert body["stripped_count"] == 1


def test_spoofed_cf_ja3_hash_is_stripped(app_client: TestClient) -> None:
    """Anon-limit fingerprint hardening: a direct caller cannot inject a
    fake JA3 hash and have ``anon_limit._ja3_hash`` trust it.

    The CF-JA3-Hash header is the 4th axis of the abuse fingerprint in
    ``src/jpintel_mcp/api/anon_limit.py``. If it leaks through, a
    direct caller can pick whatever JA3 they want — making the
    fingerprint useless. Pin the strip so a refactor cannot regress this.
    """
    r = app_client.get(
        "/_probe",
        headers={"CF-JA3-Hash": "0" * 32, "User-Agent": "curl/8.0"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cf_headers"]["cf-ja3-hash"] is None


def test_non_cf_headers_are_preserved(app_client: TestClient) -> None:
    """The sanitizer must not collateral-damage non-CF headers.

    Pin a few load-bearing headers that downstream middleware reads
    (User-Agent, Accept-Language, Fly-Client-IP, X-Forwarded-For,
    Authorization) so a future blanket-strip regression is caught.
    """

    app = FastAPI()
    app.add_middleware(EdgeHeaderSanitizationMiddleware)

    @app.get("/_echo")
    async def _echo(request: Request) -> dict[str, object]:
        return {
            "user_agent": request.headers.get("user-agent"),
            "accept_language": request.headers.get("accept-language"),
            "fly_client_ip": request.headers.get("fly-client-ip"),
            "xff": request.headers.get("x-forwarded-for"),
            "authorization": request.headers.get("authorization"),
        }

    client = TestClient(app)
    r = client.get(
        "/_echo",
        headers={
            "User-Agent": "claude-desktop/1.0",
            "Accept-Language": "ja,en-US;q=0.7",
            "Fly-Client-IP": "203.0.113.5",
            "X-Forwarded-For": "203.0.113.5, 198.51.100.1",
            "Authorization": "Bearer test-token",
            "CF-IPCountry": "KP",  # this one DOES get stripped
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_agent"] == "claude-desktop/1.0"
    assert body["accept_language"] == "ja,en-US;q=0.7"
    assert body["fly_client_ip"] == "203.0.113.5"
    assert body["xff"] == "203.0.113.5, 198.51.100.1"
    assert body["authorization"] == "Bearer test-token"


# ---------------------------------------------------------------------------
# Signed X-Edge-Auth path: CF-* headers preserved.
# ---------------------------------------------------------------------------


def _mint_edge_auth_token(secret: str, ts: int | None = None) -> str:
    """Helper: mint a valid v1 HMAC-SHA256 X-Edge-Auth token."""
    real_ts = int(time.time()) if ts is None else ts
    payload = f"v1:{real_ts}".encode()
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"v1:{real_ts}:{sig}"


def test_valid_signed_token_preserves_cf_headers(
    monkeypatch: pytest.MonkeyPatch,
    app_client: TestClient,
) -> None:
    """When the request carries a valid X-Edge-Auth HMAC, CF-* headers
    pass through (the trusted CF Pages Function minted them)."""
    secret = "test-secret-do-not-use-in-prod"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret)
    token = _mint_edge_auth_token(secret)
    r = app_client.get(
        "/_probe",
        headers={
            "X-Edge-Auth": token,
            "CF-IPCountry": "JP",
            "CF-Connecting-IP": "203.0.113.42",
            "CF-Ray": "8b000000efef-NRT",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Headers must survive the middleware unchanged.
    assert body["cf_headers"]["cf-ipcountry"] == "JP"
    assert body["cf_headers"]["cf-connecting-ip"] == "203.0.113.42"
    assert body["cf_headers"]["cf-ray"] == "8b000000efef-NRT"
    # And the strip count should be absent (trusted path skips state).
    assert body["stripped_count"] is None


def test_tampered_signed_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    app_client: TestClient,
) -> None:
    """A signed token with a swapped HMAC must fail verification and
    cause the request to fall through to the default strip path."""
    secret = "test-secret"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret)
    ts = int(time.time())
    # Build a token signed with the WRONG secret.
    payload = f"v1:{ts}".encode()
    bad_sig = hmac.new(b"wrong-secret", payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{bad_sig}"
    r = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": token, "CF-IPCountry": "KP"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cf_headers"]["cf-ipcountry"] is None


def test_replay_token_older_than_window_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    app_client: TestClient,
) -> None:
    """A token timestamped > 300s in the past is treated as a replay
    attempt and ignored; CF-* headers strip as if unsigned."""
    secret = "test-secret"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret)
    old_ts = int(time.time()) - 10_000  # 10000s ago, well past 300s window
    stale = _mint_edge_auth_token(secret, ts=old_ts)
    r = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": stale, "CF-IPCountry": "JP"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cf_headers"]["cf-ipcountry"] is None


def test_signed_token_with_no_secret_configured_is_ignored(
    app_client: TestClient,
) -> None:
    """If ``JPCITE_EDGE_AUTH_SECRET`` is unset, a presented token must
    NOT grant trust — otherwise an attacker could forge any payload."""
    # No secret in env (autouse fixture cleared it). Token cannot grant trust.
    payload = f"v1:{int(time.time())}".encode()
    sig = hmac.new(b"any-key", payload, hashlib.sha256).hexdigest()
    token = f"v1:{int(time.time())}:{sig}"
    r = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": token, "CF-IPCountry": "KP"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cf_headers"]["cf-ipcountry"] is None


# ---------------------------------------------------------------------------
# Peer-IP allowlist trust path.
# ---------------------------------------------------------------------------


def test_peer_ip_allowlist_match_preserves_cf_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the TCP peer is inside ``JPCITE_CF_TRUSTED_PEER_IPS``, CF-*
    headers pass through unchanged."""
    # Allowlist the TestClient peer's address space. TestClient uses
    # 'testclient' as the host string (not an IP), so we forge the scope
    # via a custom Starlette middleware test rig that injects a peer IP
    # the allowlist matches.
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    monkeypatch.setenv("JPCITE_CF_TRUSTED_PEER_IPS", "203.0.113.0/24")

    async def _probe(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "country": request.headers.get("cf-ipcountry"),
                "stripped": getattr(request.state, "edge_headers_stripped", None),
            }
        )

    app = Starlette(routes=[Route("/_probe", _probe)])
    app.add_middleware(EdgeHeaderSanitizationMiddleware)

    # Patch TestClient by injecting a custom ASGI client tuple via scope.
    # Easiest path: build a synthetic ASGI scope and call the middleware
    # directly via the Starlette TestClient with a base_url that the
    # ASGI server resolves to a synthetic peer. TestClient does not let
    # us override request.client directly, so we test the helper at the
    # unit layer (peer_is_trusted) and the full-rig integration via the
    # signed-token path. This test asserts the unit-layer guarantee.
    assert _peer_is_trusted("203.0.113.42") is True
    assert _peer_is_trusted("198.51.100.1") is False
    assert _peer_is_trusted(None) is False


def test_peer_ip_allowlist_empty_default_trusts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty ``JPCITE_CF_TRUSTED_PEER_IPS`` env var means no peer IP is
    trusted — the only trust path is the signed-header one."""
    monkeypatch.delenv("JPCITE_CF_TRUSTED_PEER_IPS", raising=False)
    assert _peer_is_trusted("127.0.0.1") is False
    assert _peer_is_trusted("203.0.113.42") is False
    assert _peer_is_trusted("::1") is False


def test_peer_ip_allowlist_ignores_malformed_cidr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in the env var must not crash boot or accidentally widen
    trust to everything. Malformed entries are silently dropped."""
    monkeypatch.setenv(
        "JPCITE_CF_TRUSTED_PEER_IPS",
        "not-a-cidr, 203.0.113.0/24, also-bad",
    )
    # Good entry still works.
    assert _peer_is_trusted("203.0.113.99") is True
    # Bad entries did not grant blanket trust.
    assert _peer_is_trusted("10.0.0.1") is False


# ---------------------------------------------------------------------------
# Scope-mutation unit semantics (so a subsequent middleware that builds
# its own Request() from scope sees the sanitised list).
# ---------------------------------------------------------------------------


def test_strip_cf_headers_inplace_mutates_scope_list() -> None:
    """Direct unit test of the scope-mutation primitive."""
    scope: dict[str, object] = {
        "headers": [
            (b"host", b"api.jpcite.com"),
            (b"cf-ipcountry", b"KP"),
            (b"cf-ray", b"deadbeef-NRT"),
            (b"user-agent", b"curl/8.0"),
            (b"cf-connecting-ip", b"1.2.3.4"),
        ]
    }
    stripped = _strip_cf_headers_inplace(scope)
    assert stripped == 3
    assert scope["headers"] == [
        (b"host", b"api.jpcite.com"),
        (b"user-agent", b"curl/8.0"),
    ]


def test_strip_cf_headers_inplace_handles_mixed_case_names() -> None:
    """ASGI normalises header names to lowercase, but defend against a
    future ASGI server that does not by comparing case-insensitively."""
    scope: dict[str, object] = {
        "headers": [
            (b"CF-IPCountry", b"KP"),
            (b"Cf-Ray", b"deadbeef"),
            (b"host", b"api.jpcite.com"),
        ]
    }
    stripped = _strip_cf_headers_inplace(scope)
    assert stripped == 2
    assert scope["headers"] == [(b"host", b"api.jpcite.com")]


def test_strip_cf_headers_inplace_noop_when_no_cf_headers() -> None:
    """When the request has no CF-* headers, the scope is untouched and
    the strip count is 0."""
    scope: dict[str, object] = {
        "headers": [
            (b"host", b"api.jpcite.com"),
            (b"user-agent", b"curl/8.0"),
        ]
    }
    original = list(scope["headers"])  # type: ignore[arg-type]
    stripped = _strip_cf_headers_inplace(scope)
    assert stripped == 0
    # List identity may differ but contents must be unchanged.
    assert scope["headers"] == original


# ---------------------------------------------------------------------------
# HMAC verification unit semantics.
# ---------------------------------------------------------------------------


def test_verify_signed_edge_header_accepts_fresh_token() -> None:
    secret = "test-secret"
    ts = int(time.time())
    payload = f"v1:{ts}".encode()
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{sig}"
    assert _verify_signed_edge_header(token, secret) is True


def test_verify_signed_edge_header_rejects_unknown_version() -> None:
    secret = "test-secret"
    ts = int(time.time())
    # Forge a "v9" prefix (not yet a supported algorithm).
    payload = f"v9:{ts}".encode()
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    token = f"v9:{ts}:{sig}"
    assert _verify_signed_edge_header(token, secret) is False


def test_verify_signed_edge_header_rejects_empty_secret() -> None:
    """Empty secret = signed path disabled. No token can grant trust."""
    ts = int(time.time())
    payload = f"v1:{ts}".encode()
    sig = hmac.new(b"any", payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{sig}"
    assert _verify_signed_edge_header(token, "") is False


def test_verify_signed_edge_header_rejects_malformed_token() -> None:
    assert _verify_signed_edge_header("", "secret") is False
    assert _verify_signed_edge_header("not-a-token", "secret") is False
    assert _verify_signed_edge_header("v1:notnumeric:abc", "secret") is False
    # Missing signature segment.
    assert _verify_signed_edge_header(f"v1:{int(time.time())}", "secret") is False


def test_verify_signed_edge_header_rejects_future_skew_beyond_60s() -> None:
    """Allow up to 60s of clock skew but no more."""
    secret = "test-secret"
    now = 1_000_000_000
    # 120s in the future — outside the skew tolerance.
    future_ts = now + 120
    payload = f"v1:{future_ts}".encode()
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    token = f"v1:{future_ts}:{sig}"
    assert _verify_signed_edge_header(token, secret, now=now) is False


def test_verify_signed_edge_header_accepts_modest_skew() -> None:
    """Up to 60s clock skew is tolerated."""
    secret = "test-secret"
    now = 1_000_000_000
    skewed_ts = now + 30  # 30s in the future, within tolerance
    payload = f"v1:{skewed_ts}".encode()
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    token = f"v1:{skewed_ts}:{sig}"
    assert _verify_signed_edge_header(token, secret, now=now) is True


# ---------------------------------------------------------------------------
# Sanity: exempt paths do not strip (paranoia regression guard).
# ---------------------------------------------------------------------------


def test_exempt_healthz_path_does_not_alter_request(app_client: TestClient) -> None:
    """``/healthz`` is exempt because monitoring should never be subtly
    affected by a CF-* strip. Add a probe route at /healthz to confirm."""
    app = FastAPI()
    app.add_middleware(EdgeHeaderSanitizationMiddleware)

    @app.get("/healthz")
    async def _healthz(request: Request) -> dict[str, object]:
        return {
            "country": request.headers.get("cf-ipcountry"),
            "stripped": getattr(request.state, "edge_headers_stripped", None),
        }

    client = TestClient(app)
    r = client.get("/healthz", headers={"CF-IPCountry": "JP"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Exempt — header is NOT stripped, state attribute is absent.
    assert body["country"] == "JP"
    assert body["stripped"] is None


# ---------------------------------------------------------------------------
# Integration sanity: env var read fresh on every request (allow rotation).
# ---------------------------------------------------------------------------


def test_secret_rotation_takes_effect_without_app_restart(
    monkeypatch: pytest.MonkeyPatch,
    app_client: TestClient,
) -> None:
    """Operator must be able to rotate JPCITE_EDGE_AUTH_SECRET without
    redeploying. Pin that the env var is read on each request."""
    secret_v1 = "secret-v1"
    secret_v2 = "secret-v2"
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret_v1)
    token_v1 = _mint_edge_auth_token(secret_v1)
    r1 = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": token_v1, "CF-IPCountry": "JP"},
    )
    assert r1.status_code == 200
    assert r1.json()["cf_headers"]["cf-ipcountry"] == "JP"
    # Rotate the secret mid-process; token_v1 must now stop working.
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", secret_v2)
    r2 = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": token_v1, "CF-IPCountry": "JP"},
    )
    assert r2.status_code == 200
    assert r2.json()["cf_headers"]["cf-ipcountry"] is None
    # A token signed with the NEW secret works.
    token_v2 = _mint_edge_auth_token(secret_v2)
    r3 = app_client.get(
        "/_probe",
        headers={"X-Edge-Auth": token_v2, "CF-IPCountry": "JP"},
    )
    assert r3.status_code == 200
    assert r3.json()["cf_headers"]["cf-ipcountry"] == "JP"
