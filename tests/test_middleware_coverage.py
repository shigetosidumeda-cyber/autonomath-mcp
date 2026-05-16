"""Stream SS — middleware coverage push (Wave 50 tick 18+).

Targets the 1286 uncovered LOC across ``src/jpintel_mcp/api/middleware/``
identified by the 2026-05-16 honest coverage re-measurement (Stream QQ).
Each test mounts a minimal FastAPI app with ONE middleware under test +
a thin echo route so the contract under test is observable without
loading the full jpcite middleware stack.

Coverage targets:

* :class:`EdgeHeaderSanitizationMiddleware` — strip / preserve paths +
  pure helpers (_strip_cf_headers_inplace / _verify_signed_edge_header /
  _peer_is_trusted / _trusted_peer_networks / _edge_auth_secret /
  _is_exempt_path).
* :class:`SecurityHeadersMiddleware` — setdefault semantics across the
  9 hardening headers.
* :class:`KillSwitchMiddleware` — env-driven 503 + allowlist +
  ``_kill_switch_reason`` / ``_kill_switch_since`` cached state.
* :class:`OriginEnforcementMiddleware` — same-origin pass /
  exempt-path / whitelist-hit / 403 deny.
* :class:`StaticManifestCacheMiddleware` — Cache-Control stamped only
  on manifest paths + 2xx status.
* :class:`HostDeprecationMiddleware` — RFC 8594 / 9745 / 8288 stamping
  on legacy host only.
* :class:`LanguageResolverMiddleware` — query > Accept-Language >
  default ``"ja"``.
* :class:`ClientTagMiddleware` + ``validate_client_tag`` — silent-drop
  invalid tags.
* :class:`DeprecationWarningMiddleware` — route flag + response header
  trigger + always-bypass paths.
* :class:`EnvelopeAdapterMiddleware` — X-Envelope-Version stamping +
  Vary merge.
* ``did_you_mean.suggest_query_keys`` — close-match / cutoff / case-
  insensitive echo.

The tests are designed to ALL pass without DB writes (no autouse
seeded_db dependency) so a CI smoke can re-run them under tight
timeouts. SOURCE FILES ARE NOT MODIFIED — coverage is lifted purely
from new test paths.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from jpintel_mcp.api.middleware.client_tag import (
    ClientTagMiddleware,
    validate_client_tag,
)
from jpintel_mcp.api.middleware.deprecation_warning import (
    DeprecationWarningMiddleware,
    _response_signals_deprecation,
)
from jpintel_mcp.api.middleware.did_you_mean import suggest_query_keys
from jpintel_mcp.api.middleware.edge_header_sanitization import (
    _CF_HEADERS_TO_STRIP,
    EdgeHeaderSanitizationMiddleware,
    _edge_auth_secret,
    _is_exempt_path,
    _peer_is_trusted,
    _strip_cf_headers_inplace,
    _trusted_peer_networks,
    _verify_signed_edge_header,
)
from jpintel_mcp.api.middleware.envelope_adapter import EnvelopeAdapterMiddleware
from jpintel_mcp.api.middleware.host_deprecation import (
    HostDeprecationMiddleware,
    _is_legacy_host,
)
from jpintel_mcp.api.middleware.kill_switch import (
    KillSwitchMiddleware,
    _kill_switch_active,
    _kill_switch_reason,
    _kill_switch_since,
    _reset_kill_switch_state,
)
from jpintel_mcp.api.middleware.language_resolver import (
    LanguageResolverMiddleware,
    resolve_lang,
)
from jpintel_mcp.api.middleware.origin_enforcement import (
    OriginEnforcementMiddleware,
)
from jpintel_mcp.api.middleware.security_headers import (
    SecurityHeadersMiddleware,
)
from jpintel_mcp.api.middleware.static_cache_headers import (
    StaticManifestCacheMiddleware,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _echo_app(*middlewares: type) -> FastAPI:
    """Build a minimal FastAPI app with the given middleware classes.

    Each is added in declared order; Starlette wraps LIFO so the FIRST
    middleware here runs LAST on the request and FIRST on the response.
    Keeping the stack small avoids dragging in the jpcite request-id
    binding, CORS, anon-quota and other layers.
    """
    app = FastAPI()
    for mw in middlewares:
        app.add_middleware(mw)

    @app.get("/_probe")
    async def _probe(request: Request) -> dict[str, object]:
        # Echo back what the handler can see after middleware mutation.
        return {
            "lang": getattr(request.state, "lang", None),
            "client_tag": getattr(request.state, "client_tag", None),
            "v2": getattr(request.state, "envelope_v2", None),
            "stripped": getattr(request.state, "edge_headers_stripped", None),
            "headers": dict(request.headers),
        }

    @app.get("/_meta")
    async def _meta() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/v1/openapi.json")
    async def _openapi_stub() -> dict[str, str]:
        return {"openapi": "3.1.0"}

    @app.get("/_legacy", deprecated=True)
    async def _legacy_route() -> dict[str, str]:
        return {"deprecated": "yes"}

    @app.get("/_dep_header")
    async def _dep_header() -> JSONResponse:
        return JSONResponse(
            content={"ok": True},
            headers={"Deprecation": "true"},
        )

    @app.get("/healthz")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# 1) did_you_mean.suggest_query_keys (pure stdlib helper)
# ---------------------------------------------------------------------------


def test_did_you_mean_close_match() -> None:
    out = suggest_query_keys(["perfecture"], ["prefecture", "tier", "limit"])
    assert out == {"perfecture": "prefecture"}


def test_did_you_mean_below_cutoff_omits() -> None:
    assert suggest_query_keys(["totally_random"], ["prefecture"]) == {}


def test_did_you_mean_case_insensitive_echo_canonical() -> None:
    # Caller sends mixed case; echo back canonical-cased declared key.
    out = suggest_query_keys(["PREFECTURE"], ["prefecture"])
    assert out == {"PREFECTURE": "prefecture"}


def test_did_you_mean_empty_inputs() -> None:
    assert suggest_query_keys([], ["prefecture"]) == {}
    assert suggest_query_keys(["x"], []) == {}


# ---------------------------------------------------------------------------
# 2) Language resolver — pure resolve_lang + middleware
# ---------------------------------------------------------------------------


def test_resolve_lang_query_priority() -> None:
    # Query overrides Accept-Language.
    assert resolve_lang("lang=en", "ja;q=1.0") == "en"


def test_resolve_lang_accept_language_q_priority() -> None:
    # Highest q wins among supported tags.
    assert resolve_lang("", "fr;q=1.0,ja;q=0.9,en;q=0.5") == "ja"


def test_resolve_lang_default_ja() -> None:
    assert resolve_lang("", None) == "ja"
    assert resolve_lang("", "fr;q=1.0,de;q=0.5") == "ja"


def test_resolve_lang_q_zero_excluded() -> None:
    # ``q=0`` means "do not use" — must be skipped, falls through to default.
    assert resolve_lang("", "en;q=0,fr;q=1.0") == "ja"


def test_resolve_lang_subtag_normalisation() -> None:
    # en-US / ja-JP must map to en / ja respectively.
    assert resolve_lang("", "en-US,en;q=0.9") == "en"
    assert resolve_lang("", "ja-JP") == "ja"


def test_language_resolver_middleware_stamps_request_state() -> None:
    app = _echo_app(LanguageResolverMiddleware)
    c = TestClient(app)
    r = c.get("/_probe?lang=en")
    assert r.status_code == 200
    assert r.json()["lang"] == "en"


def test_language_resolver_default_ja_when_no_signal() -> None:
    app = _echo_app(LanguageResolverMiddleware)
    c = TestClient(app)
    r = c.get("/_probe")
    assert r.status_code == 200
    assert r.json()["lang"] == "ja"


# ---------------------------------------------------------------------------
# 3) Client tag — silent drop on bad shape, stash on good
# ---------------------------------------------------------------------------


def test_validate_client_tag_accepts_alnum_underscore_dash() -> None:
    assert validate_client_tag("client_01") == "client_01"
    assert validate_client_tag("ABC-xyz_123") == "ABC-xyz_123"


def test_validate_client_tag_rejects_too_long() -> None:
    # 33 chars > 32 max → None.
    assert validate_client_tag("a" * 33) is None


def test_validate_client_tag_rejects_empty_and_whitespace() -> None:
    assert validate_client_tag("") is None
    assert validate_client_tag("   ") is None
    assert validate_client_tag(None) is None


def test_validate_client_tag_rejects_special_chars() -> None:
    assert validate_client_tag("client/02") is None
    assert validate_client_tag("client 02") is None
    assert validate_client_tag("クライアント") is None  # noqa: RUF001


def test_client_tag_middleware_stashes_valid_tag() -> None:
    app = _echo_app(ClientTagMiddleware)
    c = TestClient(app)
    r = c.get("/_probe", headers={"X-Client-Tag": "tenant_01"})
    assert r.status_code == 200
    assert r.json()["client_tag"] == "tenant_01"


def test_client_tag_middleware_silently_drops_invalid() -> None:
    app = _echo_app(ClientTagMiddleware)
    c = TestClient(app)
    r = c.get("/_probe", headers={"X-Client-Tag": "bad/tag"})
    assert r.status_code == 200
    # Silent drop → None, never 4xx.
    assert r.json()["client_tag"] is None


# ---------------------------------------------------------------------------
# 4) Security headers — all 9 headers landed via setdefault
# ---------------------------------------------------------------------------


def test_security_headers_stamps_hsts_csp_xfo() -> None:
    app = _echo_app(SecurityHeadersMiddleware)
    c = TestClient(app)
    r = c.get("/_meta")
    assert r.status_code == 200
    assert "Strict-Transport-Security" in r.headers
    assert "preload" in r.headers["Strict-Transport-Security"]
    assert "Content-Security-Policy" in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_security_headers_a11_directives_present() -> None:
    app = _echo_app(SecurityHeadersMiddleware)
    c = TestClient(app)
    r = c.get("/_meta")
    csp = r.headers.get("Content-Security-Policy", "")
    for tok in [
        "object-src 'none'",
        "form-action 'self'",
        "base-uri 'none'",
        "upgrade-insecure-requests",
    ]:
        assert tok in csp, f"missing CSP directive {tok!r}"
    assert "Permissions-Policy" in r.headers
    assert "payment=()" in r.headers["Permissions-Policy"]
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert r.headers.get("Cross-Origin-Resource-Policy") == "same-origin"
    assert r.headers.get("X-Permitted-Cross-Domain-Policies") == "none"


# ---------------------------------------------------------------------------
# 5) Kill switch — env-driven 503 + allowlist
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_ks_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure no test leaks ``KILL_SWITCH_GLOBAL`` into another."""
    monkeypatch.delenv("KILL_SWITCH_GLOBAL", raising=False)
    monkeypatch.delenv("KILL_SWITCH_REASON", raising=False)
    _reset_kill_switch_state()
    yield
    _reset_kill_switch_state()


def test_kill_switch_inactive_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _echo_app(KillSwitchMiddleware)
    c = TestClient(app)
    monkeypatch.delenv("KILL_SWITCH_GLOBAL", raising=False)
    r = c.get("/_meta")
    assert r.status_code == 200
    assert _kill_switch_active() is False
    assert _kill_switch_reason() is None
    assert _kill_switch_since() is None


def test_kill_switch_allowlist_paths_pass_even_when_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    monkeypatch.setenv("KILL_SWITCH_REASON", "ddos-test")
    app = _echo_app(KillSwitchMiddleware)
    c = TestClient(app)
    # /healthz is allowlisted — must still return 200.
    r = c.get("/healthz")
    assert r.status_code == 200
    # Reason + since helpers expose the operator forensic state.
    assert _kill_switch_reason() == "ddos-test"
    assert _kill_switch_since() is not None  # cached on first read


def test_kill_switch_reason_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    monkeypatch.setenv("KILL_SWITCH_REASON", "   ")
    # Whitespace-only reason falls back to None.
    assert _kill_switch_reason() is None


# ---------------------------------------------------------------------------
# 6) Origin enforcement — same-origin pass, exempt path pass, deny 403
# ---------------------------------------------------------------------------


def test_origin_enforcement_no_origin_header_pass() -> None:
    app = _echo_app(OriginEnforcementMiddleware)
    c = TestClient(app)
    # No Origin header → same-origin / server-to-server, must pass.
    r = c.get("/_meta")
    assert r.status_code == 200


def test_origin_enforcement_allows_jpcite_apex() -> None:
    app = _echo_app(OriginEnforcementMiddleware)
    c = TestClient(app)
    r = c.get("/_meta", headers={"Origin": "https://jpcite.com"})
    assert r.status_code == 200


def test_origin_enforcement_rejects_unknown_origin() -> None:
    app = _echo_app(OriginEnforcementMiddleware)
    c = TestClient(app)
    r = c.get("/_meta", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "origin_not_allowed"
    assert body["origin"] == "https://evil.example"
    # Vary: Origin set so an upstream cache cannot serve a successful
    # response from one origin to another.
    assert "Origin" in r.headers.get("Vary", "")


def test_origin_enforcement_health_exempt() -> None:
    app = _echo_app(OriginEnforcementMiddleware)
    c = TestClient(app)
    # Exempt path → no Origin gate.
    r = c.get("/healthz", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 7) Static manifest cache — stamp on manifest paths only
# ---------------------------------------------------------------------------


def test_static_manifest_cache_stamps_manifest_path() -> None:
    app = _echo_app(StaticManifestCacheMiddleware)
    c = TestClient(app)
    r = c.get("/v1/openapi.json")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "max-age=300" in cc
    assert "s-maxage=600" in cc


def test_static_manifest_cache_skips_non_manifest_path() -> None:
    app = _echo_app(StaticManifestCacheMiddleware)
    c = TestClient(app)
    r = c.get("/_meta")
    assert r.status_code == 200
    # Non-manifest paths must NOT get the Cache-Control stamp.
    assert "max-age=300" not in r.headers.get("Cache-Control", "")


# ---------------------------------------------------------------------------
# 8) Host deprecation — RFC 8594 / 9745 / 8288 headers on legacy host
# ---------------------------------------------------------------------------


def test_host_deprecation_legacy_host_stamps_headers() -> None:
    app = _echo_app(HostDeprecationMiddleware)
    c = TestClient(app)
    r = c.get("/_meta", headers={"Host": "api.zeimu-kaikei.ai"})
    assert r.status_code == 200
    assert r.headers.get("Deprecation") == "true"
    assert "Sunset" in r.headers
    link = r.headers.get("Link", "")
    assert "api.jpcite.com" in link
    assert 'rel="successor-version"' in link


def test_host_deprecation_canonical_host_no_stamping() -> None:
    app = _echo_app(HostDeprecationMiddleware)
    c = TestClient(app)
    r = c.get("/_meta", headers={"Host": "api.jpcite.com"})
    assert r.status_code == 200
    # Canonical host → no migration signal.
    assert r.headers.get("Deprecation") is None
    assert r.headers.get("Sunset") is None


def test_is_legacy_host_strip_port() -> None:
    # Helper handles optional :port suffix.
    class _FakeRequest:
        def __init__(self, host: str) -> None:
            self.headers = {"host": host}

    assert _is_legacy_host(_FakeRequest("api.zeimu-kaikei.ai:443")) is True
    assert _is_legacy_host(_FakeRequest("api.jpcite.com")) is False
    assert _is_legacy_host(_FakeRequest("")) is False


# ---------------------------------------------------------------------------
# 9) Envelope adapter — X-Envelope-Version stamping + Vary merge
# ---------------------------------------------------------------------------


def test_envelope_adapter_stamps_v1_by_default() -> None:
    app = _echo_app(EnvelopeAdapterMiddleware)
    c = TestClient(app)
    r = c.get("/_meta")
    assert r.status_code == 200
    assert r.headers.get("X-Envelope-Version") == "v1"
    vary = r.headers.get("Vary", "")
    assert "Accept" in vary
    assert "X-Envelope-Version" in vary


def test_envelope_adapter_stamps_request_state() -> None:
    app = _echo_app(EnvelopeAdapterMiddleware)
    c = TestClient(app)
    r = c.get("/_probe")
    assert r.status_code == 200
    # v2 defaults to False when no Accept header opts in.
    assert r.json()["v2"] is False


# ---------------------------------------------------------------------------
# 10) Deprecation warning — route flag + response-header triggers
# ---------------------------------------------------------------------------


def test_deprecation_warning_route_flag_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    app = _echo_app(DeprecationWarningMiddleware)
    c = TestClient(app)
    with caplog.at_level("WARNING", logger="autonomath.api.deprecation"):
        r = c.get("/_legacy")
    assert r.status_code == 200
    # Structured warning logged via the Sentry-aligned logger name.
    assert any(
        "deprecated_endpoint_hit" in rec.getMessage() for rec in caplog.records
    ), "expected structured deprecation warning log"


def test_deprecation_warning_response_header_trigger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _echo_app(DeprecationWarningMiddleware)
    c = TestClient(app)
    with caplog.at_level("WARNING", logger="autonomath.api.deprecation"):
        r = c.get("/_dep_header")
    assert r.status_code == 200
    assert any(
        "deprecated_endpoint_hit" in rec.getMessage() for rec in caplog.records
    )


def test_deprecation_warning_healthz_bypass(caplog: pytest.LogCaptureFixture) -> None:
    app = _echo_app(DeprecationWarningMiddleware)
    c = TestClient(app)
    with caplog.at_level("WARNING", logger="autonomath.api.deprecation"):
        r = c.get("/healthz")
    assert r.status_code == 200
    # Liveness probe bypassed → no deprecation log.
    assert not any(
        "deprecated_endpoint_hit" in rec.getMessage() for rec in caplog.records
    )


def test_response_signals_deprecation_helper() -> None:
    # Direct unit test on the helper used by the middleware.
    r1 = JSONResponse(content={"ok": 1}, headers={"Deprecation": "true"})
    r2 = JSONResponse(content={"ok": 1}, headers={"Sunset": "Wed, 31 Dec 2026"})
    r3 = JSONResponse(content={"ok": 1})
    assert _response_signals_deprecation(r1) is True
    assert _response_signals_deprecation(r2) is True
    assert _response_signals_deprecation(r3) is False


# ---------------------------------------------------------------------------
# 11) Edge header sanitization — strip + signed + peer-allowlist paths
# ---------------------------------------------------------------------------


def test_edge_header_strip_direct_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """No trust signal → every CF-* header stripped from request.scope."""
    monkeypatch.delenv("JPCITE_EDGE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("JPCITE_CF_TRUSTED_PEER_IPS", raising=False)
    app = _echo_app(EdgeHeaderSanitizationMiddleware)
    c = TestClient(app)
    r = c.get(
        "/_probe",
        headers={
            "cf-ipcountry": "KP",
            "cf-connecting-ip": "1.1.1.1",
            "cf-ja3-hash": "abc",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # All stripped — handler sees them as absent.
    seen = body["headers"]
    assert "cf-ipcountry" not in seen
    assert "cf-connecting-ip" not in seen
    assert "cf-ja3-hash" not in seen
    # Stripped count stashed on request.state for observability.
    assert body["stripped"] == 3


def test_edge_header_exempt_path_passes_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_EDGE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("JPCITE_CF_TRUSTED_PEER_IPS", raising=False)
    app = _echo_app(EdgeHeaderSanitizationMiddleware)
    c = TestClient(app)
    # /healthz is exempt — CF headers preserved.
    r = c.get(
        "/healthz",
        headers={"cf-ipcountry": "JP"},
    )
    assert r.status_code == 200


def test_edge_header_signed_token_preserves_cf_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", "test-secret")
    ts = str(int(time.time()))
    payload = f"v1:{ts}".encode()
    sig = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{sig}"

    app = _echo_app(EdgeHeaderSanitizationMiddleware)
    c = TestClient(app)
    r = c.get(
        "/_probe",
        headers={"cf-ipcountry": "JP", "x-edge-auth": token},
    )
    assert r.status_code == 200
    body = r.json()
    # Signed → headers preserved, no strip count stashed.
    assert body["headers"].get("cf-ipcountry") == "JP"


def test_edge_header_signed_token_replay_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", "test-secret")
    # Token from 1000s ago > 300s replay window → rejected.
    old_ts = str(int(time.time()) - 1000)
    payload = f"v1:{old_ts}".encode()
    sig = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
    token = f"v1:{old_ts}:{sig}"

    assert _verify_signed_edge_header(token, "test-secret") is False


def test_edge_header_signed_token_wrong_secret() -> None:
    ts = str(int(time.time()))
    payload = f"v1:{ts}".encode()
    sig = hmac.new(b"WRONG", payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{sig}"
    assert _verify_signed_edge_header(token, "right-secret") is False


def test_edge_header_signed_token_malformed_structure() -> None:
    # Unknown version.
    assert _verify_signed_edge_header("v9:123:abc", "s") is False
    # Wrong segment count.
    assert _verify_signed_edge_header("v1:abc", "s") is False
    assert _verify_signed_edge_header("", "s") is False
    # Empty secret short-circuits to False.
    assert _verify_signed_edge_header("v1:123:abc", "") is False
    # Non-numeric timestamp.
    assert _verify_signed_edge_header("v1:abc:def", "s") is False


def test_edge_header_signed_token_future_clock_skew() -> None:
    # +120s into the future > 60s tolerance → rejected.
    future_ts = str(int(time.time()) + 120)
    payload = f"v1:{future_ts}".encode()
    sig = hmac.new(b"s", payload, hashlib.sha256).hexdigest()
    token = f"v1:{future_ts}:{sig}"
    assert _verify_signed_edge_header(token, "s") is False


def test_peer_is_trusted_with_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_CF_TRUSTED_PEER_IPS", "10.0.0.0/8, 172.16.0.0/12")
    assert _peer_is_trusted("10.5.5.5") is True
    assert _peer_is_trusted("172.20.1.1") is True
    assert _peer_is_trusted("8.8.8.8") is False
    # Bad input → False.
    assert _peer_is_trusted("") is False
    assert _peer_is_trusted("not-an-ip") is False
    assert _peer_is_trusted(None) is False


def test_peer_is_trusted_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_CF_TRUSTED_PEER_IPS", raising=False)
    # Default-deny — no peer is trusted by IP.
    assert _peer_is_trusted("10.5.5.5") is False


def test_trusted_peer_networks_skips_malformed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "JPCITE_CF_TRUSTED_PEER_IPS",
        "10.0.0.0/8, NOT-A-CIDR, , 192.168.1.0/24",
    )
    nets = _trusted_peer_networks()
    # 2 valid CIDRs, 2 skipped (malformed + empty).
    assert len(nets) == 2


def test_edge_auth_secret_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_EDGE_AUTH_SECRET", "  hush  ")
    assert _edge_auth_secret() == "hush"
    monkeypatch.delenv("JPCITE_EDGE_AUTH_SECRET", raising=False)
    assert _edge_auth_secret() == ""


def test_is_exempt_path() -> None:
    assert _is_exempt_path("/healthz") is True
    assert _is_exempt_path("/readyz") is True
    assert _is_exempt_path("/v1/programs/search") is False


def test_strip_cf_headers_inplace_returns_count() -> None:
    scope = {
        "headers": [
            (b"host", b"x"),
            (b"cf-ipcountry", b"KP"),
            (b"cf-ja3-hash", b"deadbeef"),
            (b"user-agent", b"ua"),
        ],
    }
    n = _strip_cf_headers_inplace(scope)
    assert n == 2
    names = {k for k, _v in scope["headers"]}
    assert b"cf-ipcountry" not in names
    assert b"cf-ja3-hash" not in names
    assert b"host" in names
    assert b"user-agent" in names


def test_strip_cf_headers_inplace_empty_scope() -> None:
    # No-op on empty header list.
    scope = {"headers": []}
    assert _strip_cf_headers_inplace(scope) == 0


def test_signed_token_with_caller_ip_binding() -> None:
    # Caller-ip-bound token: payload includes the IP, signature must match.
    ts = str(int(time.time()))
    caller_ip = "203.0.113.7"
    payload = f"v1:{ts}:{caller_ip}".encode()
    sig = hmac.new(b"s", payload, hashlib.sha256).hexdigest()
    token = f"v1:{ts}:{caller_ip}:{sig}"
    assert _verify_signed_edge_header(token, "s", caller_ip=caller_ip) is True
    # Wrong caller IP → reject.
    assert _verify_signed_edge_header(token, "s", caller_ip="1.2.3.4") is False
    # Legacy (no caller_ip) token: only old format works without binding.
    legacy_payload = f"v1:{ts}".encode()
    legacy_sig = hmac.new(b"s", legacy_payload, hashlib.sha256).hexdigest()
    legacy_token = f"v1:{ts}:{legacy_sig}"
    # Caller demands binding but token has none → reject.
    assert _verify_signed_edge_header(legacy_token, "s", caller_ip=caller_ip) is False


# ---------------------------------------------------------------------------
# 12) CF-header set sanity (regression guard)
# ---------------------------------------------------------------------------


def test_cf_headers_to_strip_includes_canonical_set() -> None:
    # Spot-check that the canonical CF-* family is covered. A future
    # refactor that drops one of these would silently re-open the spoof
    # surface.
    must = {
        b"cf-connecting-ip",
        b"cf-ipcountry",
        b"cf-ray",
        b"cf-visitor",
        b"cf-worker",
        b"cf-ja3-hash",
        b"cf-ja4",
    }
    missing = must - _CF_HEADERS_TO_STRIP
    assert not missing, f"CF-* strip set missing: {missing}"
