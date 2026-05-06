"""W9-3 finding: HTTP fallback error paths must satisfy the
MASTER_PLAN §I envelope contract.

Pre-fix, ``_http_fallback.http_call()`` and friends returned bare error
dicts of the form::

    {"error": "remote_http_error", "status_code": 502, ...}

— bypassing the canonical 6-key envelope surface
(``total / limit / offset / results / _billing_unit / _next_calls``).
W9-2 had already aligned ``make_error()`` (autonomath_tools/error_envelope)
on the contract, but ``_http_fallback`` callers never went through that
helper; they wrote dicts inline.

Post-fix, every HTTP fallback error path:
- emits ``error`` as a ``{"code": ..., "message": ..., ...}`` dict (not
  a bare string),
- carries the full §I envelope,
- never bills (``_billing_unit == 0``) and offers no compound walk
  (``_next_calls == []``).

These tests pin the contract for every error helper in
``jpintel_mcp.mcp._http_fallback``.
"""

from __future__ import annotations

import httpx
import pytest

# Six fields the envelope contract requires on every response.
REQUIRED_ENVELOPE_FIELDS = (
    "results",
    "total",
    "limit",
    "offset",
    "_billing_unit",
    "_next_calls",
)


@pytest.fixture(autouse=True)
def _reset_mode():
    """Each test starts with a fresh fallback-mode cache + new client."""
    from jpintel_mcp.mcp import _http_fallback

    _http_fallback.reset_fallback_mode()
    _http_fallback._close_client()  # type: ignore[attr-defined]
    yield
    _http_fallback.reset_fallback_mode()
    _http_fallback._close_client()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# remote_only_error — used by 56 unwired tools
# --------------------------------------------------------------------------- #


def test_remote_only_error_envelope_required_fields() -> None:
    from jpintel_mcp.mcp._http_fallback import remote_only_error

    out = remote_only_error("search_acceptance_stats_am")

    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out, f"remote_only_error missing envelope field: {field}"
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []
    assert out["results"] == []
    assert out["total"] == 0


def test_remote_only_error_error_block_is_dict_with_code() -> None:
    from jpintel_mcp.mcp._http_fallback import remote_only_error

    out = remote_only_error("rule_engine_check")
    assert isinstance(out["error"], dict)
    assert out["error"]["code"] == "remote_only_via_REST_API"
    assert "message" in out["error"]
    # Tool name + REST hints live inside the error block now (not at top
    # level) so the envelope keys remain the canonical 6.
    assert out["error"]["tool"] == "rule_engine_check"
    assert "rest_api_base" in out["error"]
    assert "remediation" in out["error"]


# --------------------------------------------------------------------------- #
# http_call → remote_http_error (4xx surface)
# --------------------------------------------------------------------------- #


def test_http_call_4xx_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """An upstream 4xx response (other than 429) must be wrapped in the
    full §I envelope, not a bare ``{error: "remote_http_error", ...}``."""
    from jpintel_mcp.mcp import _http_fallback

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    _http_fallback._client = httpx.Client(  # type: ignore[attr-defined]
        base_url="https://api.example.test",
        transport=httpx.MockTransport(_handler),
    )

    out = _http_fallback.http_call("/v1/programs/search", retry=0)

    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out, f"4xx path missing envelope field: {field}"
    assert isinstance(out["error"], dict)
    assert out["error"]["code"] == "remote_http_error"
    assert out["error"]["status_code"] == 404
    assert out["error"]["path"] == "/v1/programs/search"
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []


def test_http_call_5xx_after_retry_exhausted_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistent 5xx (no more retries) is also a remote_http_error."""
    from jpintel_mcp.mcp import _http_fallback

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "service down"})

    _http_fallback._client = httpx.Client(  # type: ignore[attr-defined]
        base_url="https://api.example.test",
        transport=httpx.MockTransport(_handler),
    )

    out = _http_fallback.http_call("/v1/programs/search", retry=0)

    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out
    assert out["error"]["code"] == "remote_http_error"
    assert out["error"]["status_code"] == 503
    assert out["_billing_unit"] == 0


# --------------------------------------------------------------------------- #
# http_call → remote_unreachable (transport error after retries)
# --------------------------------------------------------------------------- #


def test_http_call_transport_error_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All retries exhausted via ConnectError → remote_unreachable
    envelope with the full §I surface."""
    from jpintel_mcp.mcp import _http_fallback

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS lookup failed")

    _http_fallback._client = httpx.Client(  # type: ignore[attr-defined]
        base_url="https://api.example.test",
        transport=httpx.MockTransport(_handler),
    )

    out = _http_fallback.http_call("/v1/programs/search", retry=0)

    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out, f"remote_unreachable missing envelope field: {field}"
    assert isinstance(out["error"], dict)
    assert out["error"]["code"] == "remote_unreachable"
    assert out["error"]["path"] == "/v1/programs/search"
    assert "ConnectError" in out["error"]["detail"]
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []


# --------------------------------------------------------------------------- #
# http_call → quota_exceeded (429 surface)
# --------------------------------------------------------------------------- #


def test_http_call_429_quota_exceeded_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 from upstream is converted to the customer-friendly
    quota_exceeded envelope. Same §I contract as every other error
    path — error is a dict; ``_billing_unit`` is 0."""
    from jpintel_mcp.mcp import _http_fallback
    from jpintel_mcp.mcp import auth as auth_mod

    monkeypatch.setattr(
        auth_mod,
        "handle_quota_exceeded",
        lambda: "device-flow upgrade instructions",
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {"code": "quota_exceeded"},
                "upgrade_url": "https://jpcite.com/pricing.html#api-paid",
                "direct_checkout_url": "https://jpcite.com/v1/billing/checkout",
                "trial_signup_url": "https://jpcite.com/trial.html",
            },
        )

    _http_fallback._client = httpx.Client(  # type: ignore[attr-defined]
        base_url="https://api.example.test",
        transport=httpx.MockTransport(_handler),
    )

    out = _http_fallback.http_call("/v1/programs/search", retry=0)

    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out, f"quota_exceeded missing envelope field: {field}"
    assert isinstance(out["error"], dict)
    assert out["error"]["code"] == "quota_exceeded"
    assert out["error"]["status_code"] == 429
    assert out["error"]["upgrade_url"] == "https://jpcite.com/pricing.html#api-paid"
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []


# --------------------------------------------------------------------------- #
# Direct helper sanity checks
# --------------------------------------------------------------------------- #


def test_envelope_error_helper_is_exported_and_works() -> None:
    """``_envelope_error`` is the new canonical builder for every error
    surface in this module. Pin its shape so other call sites can rely
    on it."""
    from jpintel_mcp.mcp._http_fallback import _envelope_error

    out = _envelope_error("test_code", "test message", extra={"x": 1})
    assert out["error"] == {"code": "test_code", "message": "test message", "x": 1}
    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []


def test_envelope_error_helper_no_extra() -> None:
    from jpintel_mcp.mcp._http_fallback import _envelope_error

    out = _envelope_error("internal", "boom")
    assert out["error"] == {"code": "internal", "message": "boom"}
    for field in REQUIRED_ENVELOPE_FIELDS:
        assert field in out


def test_envelope_error_helper_extra_does_not_clobber_envelope() -> None:
    """Extras merge into the ``error`` block, not the top-level
    envelope, so they cannot break ``_billing_unit`` / ``_next_calls``
    / ``results`` invariants."""
    from jpintel_mcp.mcp._http_fallback import _envelope_error

    out = _envelope_error(
        "internal",
        "boom",
        extra={"_billing_unit": 999, "_next_calls": ["evil"], "results": ["pwn"]},
    )
    assert out["_billing_unit"] == 0
    assert out["_next_calls"] == []
    assert out["results"] == []
    # Extras live inside error block.
    assert out["error"]["_billing_unit"] == 999
    assert out["error"]["_next_calls"] == ["evil"]
    assert out["error"]["results"] == ["pwn"]
