"""W2-9 M-1 — wave24 REST kwargs spread security gate.

`api/wave24_endpoints._dispatch_wave24_tool` previously spread the entire
POST body straight into the resolved wave24 tool's kwargs. If a tool body
ever introduced an internal-only parameter (e.g. `_internal_audit=True`,
`_skip_disclaimer=True`), a malicious caller could override it from the HTTP
surface — a quiet privilege-escalation vector that would only surface after
launch.

Fix: `_filter_kwargs_for_tool` introspects the tool's signature and drops
(a) any key not in the signature and (b) any key whose name starts with `_`
(internal-only by convention). Rejected keys are logged as
`wave24_kwargs_rejected` so probing is observable in production logs.

These tests verify:
  1. Underscore-prefixed kwargs supplied via REST are dropped before the
     tool sees them.
  2. Unknown kwargs (typos, future params, hostile injections) are dropped.
  3. Legitimate kwargs survive untouched.
  4. Tools that explicitly declare `**kwargs` still get underscore-prefixed
     keys filtered out (defence in depth).
  5. The rejected-key warning is emitted with the right structured payload.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api import wave24_endpoints as w

# --------------------------------------------------------------------------- #
# Unit-level: _filter_kwargs_for_tool against synthetic signatures.
# --------------------------------------------------------------------------- #


def _public_only_tool(houjin_bangou: str, limit: int = 10, offset: int = 0) -> dict:
    return {"houjin_bangou": houjin_bangou, "limit": limit, "offset": offset}


def _internal_param_tool(
    houjin_bangou: str,
    limit: int = 10,
    _internal_audit: bool = False,
    _skip_disclaimer: bool = False,
) -> dict:
    # Even though the function declares _internal_audit, REST callers must
    # NEVER be able to flip it. Underscore = internal by convention.
    return {
        "houjin_bangou": houjin_bangou,
        "limit": limit,
        "_internal_audit": _internal_audit,
        "_skip_disclaimer": _skip_disclaimer,
    }


def _var_kw_tool(houjin_bangou: str, **kwargs: Any) -> dict:
    return {"houjin_bangou": houjin_bangou, "kwargs": kwargs}


def test_filter_drops_unknown_keys() -> None:
    """Keys not in the tool signature are dropped silently (with a log line)."""
    payload = {"houjin_bangou": "1234567890123", "limit": 5, "bogus_field": "x"}
    out = w._filter_kwargs_for_tool("public_only_tool", _public_only_tool, payload)
    assert out == {"houjin_bangou": "1234567890123", "limit": 5}


def test_filter_drops_underscore_keys_even_when_declared() -> None:
    """Underscore-prefixed kwargs are dropped even if the tool declares them.

    This is the load-bearing security property: a tool author cannot accidentally
    create a REST-exposed internal flag by naming it `_x` in the signature.
    """
    payload = {
        "houjin_bangou": "1234567890123",
        "limit": 5,
        "_internal_audit": True,
        "_skip_disclaimer": True,
    }
    out = w._filter_kwargs_for_tool("internal_param_tool", _internal_param_tool, payload)
    assert out == {"houjin_bangou": "1234567890123", "limit": 5}
    assert "_internal_audit" not in out
    assert "_skip_disclaimer" not in out


def test_filter_drops_underscore_keys_for_var_kw_tool() -> None:
    """Even a tool that opts in via **kwargs must not receive _-prefixed keys."""
    payload = {
        "houjin_bangou": "1234567890123",
        "extra_public": "ok",
        "_internal_audit": True,
    }
    out = w._filter_kwargs_for_tool("var_kw_tool", _var_kw_tool, payload)
    # **kwargs tool keeps unknown public keys but still loses _-prefixed ones
    assert out == {"houjin_bangou": "1234567890123", "extra_public": "ok"}


def test_filter_keeps_legitimate_kwargs() -> None:
    payload = {"houjin_bangou": "1234567890123", "limit": 7, "offset": 14}
    out = w._filter_kwargs_for_tool("public_only_tool", _public_only_tool, payload)
    assert out == payload


def test_filter_logs_rejected_keys(caplog: pytest.LogCaptureFixture) -> None:
    payload = {
        "houjin_bangou": "1234567890123",
        "_internal_audit": True,
        "bogus_field": "x",
    }
    with caplog.at_level(logging.WARNING, logger="jpintel.api.wave24"):
        w._filter_kwargs_for_tool("internal_param_tool", _internal_param_tool, payload)
    matching = [r for r in caplog.records if r.message == "wave24_kwargs_rejected"]
    assert matching, "expected wave24_kwargs_rejected warning to be emitted"
    rec = matching[-1]
    assert getattr(rec, "tool", None) == "internal_param_tool"
    rejected = getattr(rec, "keys", [])
    assert "_internal_audit" in rejected
    assert "bogus_field" in rejected


def test_filter_no_log_when_nothing_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {"houjin_bangou": "1234567890123", "limit": 5}
    with caplog.at_level(logging.WARNING, logger="jpintel.api.wave24"):
        w._filter_kwargs_for_tool("public_only_tool", _public_only_tool, payload)
    assert not [r for r in caplog.records if r.message == "wave24_kwargs_rejected"]


# --------------------------------------------------------------------------- #
# Dispatch-level: feed payload through _dispatch_wave24_tool with a stubbed
# resolver and assert the tool only sees filtered kwargs.
# --------------------------------------------------------------------------- #


def test_dispatch_filters_internal_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_tool(
        houjin_bangou: str,
        limit: int = 10,
        _internal_audit: bool = False,
    ) -> dict[str, Any]:
        captured["houjin_bangou"] = houjin_bangou
        captured["limit"] = limit
        captured["_internal_audit"] = _internal_audit
        return {"results": [], "total": 0}

    monkeypatch.setattr(w, "_resolve_wave24_tool", lambda name: _fake_tool)

    result = w._dispatch_wave24_tool(
        "recommend_programs_for_houjin",
        houjin_bangou="1234567890123",
        limit=5,
        _internal_audit=True,
    )
    assert result == {"results": [], "total": 0}
    assert captured == {
        "houjin_bangou": "1234567890123",
        "limit": 5,
        "_internal_audit": False,  # default, NOT the True the caller tried to inject
    }


def test_dispatch_filters_unknown_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_tool(houjin_bangou: str, limit: int = 10) -> dict[str, Any]:
        captured["houjin_bangou"] = houjin_bangou
        captured["limit"] = limit
        return {"results": [], "total": 0}

    monkeypatch.setattr(w, "_resolve_wave24_tool", lambda name: _fake_tool)

    w._dispatch_wave24_tool(
        "recommend_programs_for_houjin",
        houjin_bangou="1234567890123",
        limit=5,
        future_param="not_yet_supported",
        rogue_field="hostile",
    )
    assert captured == {"houjin_bangou": "1234567890123", "limit": 5}


# --------------------------------------------------------------------------- #
# HTTP-level: full FastAPI round-trip through the POST body endpoints
# (recommend / enforcement_risk / match/capital / tax_change_impact).
# These four endpoints are the kwargs-spread sites and are the actual
# launch-blocking surfaces.
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[dict[str, Any]]]:
    """Replace `_resolve_wave24_tool` with a stub that captures every call.

    Returns a dict {tool_name: [kwargs_dict, ...]} so tests can assert on
    what the tool body actually received.
    """
    seen: dict[str, list[dict[str, Any]]] = {}

    def _build_stub(tool_name: str) -> Any:
        def _stub(**kwargs: Any) -> dict[str, Any]:
            seen.setdefault(tool_name, []).append(dict(kwargs))
            return {"results": [], "total": 0, "_billing_unit": 1}

        # Synthesize a permissive signature that matches the real REST wrappers'
        # public param shapes. Wave24 tools we care about for this gate are the
        # 4 POST-body endpoints; we forge realistic public params plus an
        # internal-only flag the caller will try to inject.
        if tool_name == "recommend_programs_for_houjin":

            def _stub(  # type: ignore[no-redef]
                houjin_bangou: str,
                limit: int = 10,
                offset: int = 0,
                _internal_audit: bool = False,
            ) -> dict[str, Any]:
                seen.setdefault(tool_name, []).append(
                    {
                        "houjin_bangou": houjin_bangou,
                        "limit": limit,
                        "offset": offset,
                        "_internal_audit": _internal_audit,
                    }
                )
                return {"results": [], "total": 0, "_billing_unit": 1}
        elif tool_name == "forecast_enforcement_risk":

            def _stub(  # type: ignore[no-redef]
                houjin_bangou: str,
                horizon_months: int = 12,
                _internal_audit: bool = False,
            ) -> dict[str, Any]:
                seen.setdefault(tool_name, []).append(
                    {
                        "houjin_bangou": houjin_bangou,
                        "horizon_months": horizon_months,
                        "_internal_audit": _internal_audit,
                    }
                )
                return {"results": [], "total": 0, "_billing_unit": 1}
        elif tool_name == "match_programs_by_capital":

            def _stub(  # type: ignore[no-redef]
                capital_yen: int,
                limit: int = 20,
                _internal_audit: bool = False,
            ) -> dict[str, Any]:
                seen.setdefault(tool_name, []).append(
                    {
                        "capital_yen": capital_yen,
                        "limit": limit,
                        "_internal_audit": _internal_audit,
                    }
                )
                return {"results": [], "total": 0, "_billing_unit": 1}
        elif tool_name == "simulate_tax_change_impact":

            def _stub(  # type: ignore[no-redef]
                houjin_bangou: str,
                fiscal_year: int | None = None,
                tax_ruleset_id: str | None = None,
                _internal_audit: bool = False,
            ) -> dict[str, Any]:
                seen.setdefault(tool_name, []).append(
                    {
                        "houjin_bangou": houjin_bangou,
                        "fiscal_year": fiscal_year,
                        "tax_ruleset_id": tax_ruleset_id,
                        "_internal_audit": _internal_audit,
                    }
                )
                return {"results": [], "total": 0, "_billing_unit": 1}

        return _stub

    monkeypatch.setattr(w, "_resolve_wave24_tool", _build_stub)
    return seen


@pytest.fixture
def wave24_client() -> TestClient:
    app = FastAPI()
    app.include_router(w.router)
    return TestClient(app)


def test_recommend_endpoint_drops_internal_kwargs(
    wave24_client: TestClient,
    stub_resolver: dict[str, list[dict[str, Any]]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /v1/am/recommend with `_internal_audit:True` must NOT propagate."""
    with caplog.at_level(logging.WARNING, logger="jpintel.api.wave24"):
        resp = wave24_client.post(
            "/v1/am/recommend",
            json={
                "houjin_bangou": "1234567890123",
                "limit": 5,
                "_internal_audit": True,
                "_skip_disclaimer": True,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "results" in body or "result_count" in body or "data" in body

    calls = stub_resolver.get("recommend_programs_for_houjin", [])
    assert calls, "tool stub never called"
    args = calls[-1]
    # The default value, NOT the True the caller tried to inject.
    assert args["_internal_audit"] is False
    assert args["houjin_bangou"] == "1234567890123"
    assert args["limit"] == 5

    matching = [r for r in caplog.records if r.message == "wave24_kwargs_rejected"]
    assert matching, "expected at least one wave24_kwargs_rejected log line"
    last = matching[-1]
    rejected = list(getattr(last, "keys", []))
    assert "_internal_audit" in rejected
    assert "_skip_disclaimer" in rejected


def test_enforcement_risk_endpoint_drops_internal_kwargs(
    wave24_client: TestClient,
    stub_resolver: dict[str, list[dict[str, Any]]],
) -> None:
    resp = wave24_client.post(
        "/v1/am/enforcement_risk",
        json={
            "houjin_bangou": "1234567890123",
            "horizon_months": 6,
            "_internal_audit": True,
        },
    )
    assert resp.status_code == 200, resp.text
    calls = stub_resolver.get("forecast_enforcement_risk", [])
    assert calls
    args = calls[-1]
    assert args["_internal_audit"] is False
    assert args["horizon_months"] == 6


def test_match_capital_endpoint_drops_internal_kwargs(
    wave24_client: TestClient,
    stub_resolver: dict[str, list[dict[str, Any]]],
) -> None:
    resp = wave24_client.post(
        "/v1/am/match/capital",
        json={
            "capital_yen": 5_000_000,
            "limit": 10,
            "_internal_audit": True,
            "rogue_field": "bypass",
        },
    )
    assert resp.status_code == 200, resp.text
    calls = stub_resolver.get("match_programs_by_capital", [])
    assert calls
    args = calls[-1]
    assert args["_internal_audit"] is False
    assert args["capital_yen"] == 5_000_000
    assert args["limit"] == 10


def test_tax_change_impact_endpoint_drops_internal_kwargs(
    wave24_client: TestClient,
    stub_resolver: dict[str, list[dict[str, Any]]],
) -> None:
    resp = wave24_client.post(
        "/v1/am/houjin/1234567890123/tax_change_impact",
        json={
            "tax_ruleset_id": "TAX-1",
            "_internal_audit": True,
        },
    )
    assert resp.status_code == 200, resp.text
    calls = stub_resolver.get("simulate_tax_change_impact", [])
    assert calls
    args = calls[-1]
    assert args["_internal_audit"] is False
    assert args["tax_ruleset_id"] == "TAX-1"
    assert args["houjin_bangou"] == "1234567890123"
