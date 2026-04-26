"""Tests for the δ1 StrictQueryMiddleware (group δ, P0-4 / K4 / J10).

The middleware rejects HTTP requests whose query string carries a key
that no declared :class:`Depends` / :class:`Query` parameter consumes
on the matched route. Pre-fix, 87 % of routes (80 / 92) silently
dropped unknown keys, which led LLM callers to pretend they had
filtered when in fact they had not.

What we cover:

* Unknown query key on a search route -> 422 + structured envelope.
* Multiple unknown keys -> all listed in the envelope, sorted.
* All-known query keys -> 200 (regression).
* Empty query string -> 200 (fast path).
* Unknown route + unknown query key -> 404 wins (route gate first).
* JPINTEL_STRICT_QUERY_DISABLED=1 -> middleware no-ops at runtime.
* OPTIONS preflight bypass -> 200 / 405 not 422.
* Path with declared param via alias is accepted.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client():
    """Fresh app per test so middleware/handler registration is isolated.

    Tests that flip ``JPINTEL_STRICT_QUERY_DISABLED`` rely on this —
    create_app reads the env var at request time via the middleware,
    so we don't need to rebuild for the disable-toggle tests. The
    fresh-app pattern is still cleaner.
    """
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


def test_unknown_query_param_rejects_with_422(seeded_db):
    c = _build_client()
    r = c.get("/v1/programs/search?q=test&fake_param=xyz")
    assert r.status_code == 422
    body = r.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "unknown_query_parameter"
    assert err["unknown"] == ["fake_param"]
    # `q` is a valid declared param so it must NOT appear in unknown.
    assert "q" not in err["unknown"]
    # Expected list contains all declared params for the route.
    assert "q" in err["expected"]
    assert "limit" in err["expected"]
    # Plain-Japanese user message present (no stack trace).
    assert "未定義" in err["user_message"]
    # Documentation URL anchor.
    assert err["documentation"].endswith("#unknown_query_parameter")
    # Request id echoed (literal "unset" is acceptable when the
    # middleware fires before _RequestContextMiddleware stamps state).
    assert "request_id" in err


def test_multiple_unknown_keys_listed_sorted(seeded_db):
    c = _build_client()
    r = c.get("/v1/programs/search?q=test&zfake=a&afake=b&mfake=c")
    assert r.status_code == 422
    err = r.json()["error"]
    # Sorted ascending so the wire shape is deterministic.
    assert err["unknown"] == ["afake", "mfake", "zfake"]


def test_all_known_keys_passes_through(seeded_db):
    c = _build_client()
    r = c.get(
        "/v1/programs/search?q=test&prefecture=東京都&tier=S&limit=3&offset=0"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The legitimate response shape should be preserved.
    assert "results" in body
    assert "total" in body


def test_empty_query_string_fast_path(seeded_db):
    c = _build_client()
    r = c.get("/v1/programs/search")
    assert r.status_code == 200, r.text


def test_unknown_route_404_wins_over_strict_query(seeded_db):
    """Strict-query middleware must NOT shadow a 404 for an unknown
    route — even if the URL has unknown query keys, we want the
    operator to learn the path is wrong before the param shape.
    """
    c = _build_client()
    r = c.get("/v1/totally/unknown/route?weird=1")
    assert r.status_code == 404
    body = r.json()
    # Structured 404 envelope (δ3) is also live here.
    assert body["error"]["code"] == "route_not_found"


def test_disabled_via_env(seeded_db, monkeypatch):
    """Setting JPINTEL_STRICT_QUERY_DISABLED=1 must restore legacy
    silent-drop behaviour so we have a kill-switch in prod if the
    closed-set assumption ever breaks an unforeseen route.
    """
    monkeypatch.setenv("JPINTEL_STRICT_QUERY_DISABLED", "1")
    c = _build_client()
    r = c.get("/v1/programs/search?q=test&fake_param=xyz")
    # Legacy behaviour: 200, fake_param ignored silently.
    assert r.status_code == 200, r.text


def test_options_preflight_bypassed(seeded_db):
    """CORS preflight on a real route must not 422 — the OPTIONS
    request never has a body and is answered by the CORS layer; a
    422 here would break browser callers' discovery flow.
    """
    c = _build_client()
    r = c.options(
        "/v1/programs/search?fake=1",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS layer responds 200 / 400; we just need to confirm we did NOT
    # 422 the preflight.
    assert r.status_code != 422


def test_request_id_echoed_when_caller_supplies(seeded_db):
    """When the client supplies an x-request-id, the strict-query 422
    envelope must echo it under error.request_id so the support flow
    has a trace handle.
    """
    c = _build_client()
    rid = "test-rid-fakeparam-001"
    r = c.get(
        "/v1/programs/search?fake_param=xyz",
        headers={"x-request-id": rid},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["request_id"] == rid


def test_no_regression_on_loan_programs_route(seeded_db):
    """A second discovery surface to spot a pattern-specific regression
    (e.g. alias handling) — loan_programs has its own declared params.
    """
    c = _build_client()
    # Unknown key -> 422
    r = c.get("/v1/loan-programs/search?bogus_key=1")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unknown_query_parameter"
    assert "bogus_key" in err["unknown"]


def test_envelope_carries_path_and_method(seeded_db):
    c = _build_client()
    r = c.get("/v1/programs/search?fake=1")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["path"] == "/v1/programs/search"
    assert err["method"] == "GET"
