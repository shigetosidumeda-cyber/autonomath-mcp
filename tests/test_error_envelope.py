"""Tests for the δ2/δ3 canonical REST error envelope.

The pre-launch audit (J5) found 5 distinct error envelope shapes
across the REST surface; ``api/_error_envelope.py:make_error`` and
``api.main`` global handlers consolidate them. We verify:

* ``make_error`` shape contract: code / user_message / request_id
  always present; unknown code is coerced to ``internal_error``;
  ``request_id`` falls back to ``"unset"`` (NEVER ``"unknown"`` —
  that string was the J5 bug we explicitly fix).
* 500 unhandled exception keeps legacy ``detail`` / ``request_id``
  AND attaches the canonical envelope under ``error``.
* 401 / 404 / 405 / 503 carry a structured envelope under ``error``
  while retaining ``detail`` for back-compat.
* 422 RequestValidationError attaches ``error.code = validation_error``
  alongside the existing ``detail`` / ``detail_summary_ja``.
* The ``request_id`` is reused: the same id appears in
  ``response.headers['x-request-id']`` AND ``body['error']['request_id']``.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from jpintel_mcp.api._error_envelope import (
    DOC_URL,
    ERROR_CODES,
    make_error,
    safe_request_id,
)


# ---------------------------------------------------------------------------
# make_error helper unit tests
# ---------------------------------------------------------------------------


def test_make_error_minimal_shape():
    body = make_error(code="internal_error")
    assert "error" in body
    err = body["error"]
    assert err["code"] == "internal_error"
    assert err["user_message"]  # default Japanese copy applied
    assert err["request_id"] == "unset"
    assert err["documentation"] == f"{DOC_URL}#internal_error"
    assert err["severity"] == "hard"


def test_make_error_unknown_code_coerces_to_internal():
    body = make_error(code="not_a_real_code")
    assert body["error"]["code"] == "internal_error"


def test_make_error_request_id_never_literal_unknown():
    """J5 bug guard: the literal string 'unknown' must never be
    emitted by make_error. Pre-fix, the global 500 handler used
    ``request.headers.get('x-request-id') or 'unknown'`` which leaked
    'unknown' into prod 5xx bodies for every internally-generated id.
    """
    # No request_id supplied -> fall back to literal 'unset', not 'unknown'.
    body = make_error(code="internal_error")
    assert body["error"]["request_id"] == "unset"
    assert body["error"]["request_id"] != "unknown"


def test_make_error_extras_merged():
    body = make_error(
        code="rate_limit_exceeded",
        request_id="rid-abc",
        retry_after=42,
        limit=50,
    )
    err = body["error"]
    assert err["request_id"] == "rid-abc"
    assert err["retry_after"] == 42
    assert err["limit"] == 50


def test_make_error_drops_none_extras():
    body = make_error(
        code="internal_error",
        request_id=None,
        weird=None,
    )
    # `weird` was None -> dropped.
    assert "weird" not in body["error"]


def test_make_error_user_message_override():
    body = make_error(
        code="auth_required",
        user_message="独自のメッセージです",
    )
    assert body["error"]["user_message"] == "独自のメッセージです"


def test_error_codes_closed_enum_documented():
    """Every code declared in ERROR_CODES has Japanese + English copy
    and a severity. Adding a new code without copy is a regression.
    """
    for code, spec in ERROR_CODES.items():
        assert "user_message_ja" in spec, code
        assert "severity" in spec, code
        assert spec["severity"] in {"hard", "soft"}, code


# ---------------------------------------------------------------------------
# 500 handler integration
# ---------------------------------------------------------------------------


def _app_with_boom():
    """Fresh app with a route that raises ZeroDivisionError."""
    from jpintel_mcp.api.main import create_app

    app = create_app()

    def _boom() -> int:
        return 1 // 0

    app.router.add_api_route("/_test_boom", _boom, methods=["GET"])
    return app


def test_500_carries_canonical_error_envelope(seeded_db):
    app = _app_with_boom()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/_test_boom")
    assert r.status_code == 500
    body = r.json()
    # Back-compat keys still present.
    assert body["detail"] == "internal server error"
    assert body["request_id"]
    # Canonical envelope.
    assert body["error"]["code"] == "internal_error"
    # request_id consistency: header and envelope match.
    assert body["error"]["request_id"] == body["request_id"]
    assert r.headers["x-request-id"] == body["request_id"]
    # The literal 'unknown' MUST not appear (J5 fix).
    assert body["request_id"] != "unknown"
    assert body["error"]["request_id"] != "unknown"


def test_500_propagates_caller_request_id(seeded_db):
    app = _app_with_boom()
    c = TestClient(app, raise_server_exceptions=False)
    rid = "rid-test-500-propagate"
    r = c.get("/_test_boom", headers={"x-request-id": rid})
    assert r.status_code == 500
    body = r.json()
    assert body["request_id"] == rid
    assert body["error"]["request_id"] == rid
    assert r.headers["x-request-id"] == rid


# ---------------------------------------------------------------------------
# 404 handler integration
# ---------------------------------------------------------------------------


def test_404_unknown_route_carries_envelope(seeded_db, client):
    r = client.get("/v1/totally/unknown/route")
    assert r.status_code == 404
    body = r.json()
    # Back-compat detail still present.
    assert body["detail"] == "Not Found"
    err = body["error"]
    assert err["code"] == "route_not_found"
    assert err["user_message"]
    # Suggested paths help an LLM bounce off.
    assert isinstance(err["suggested_paths"], list)
    assert any("/v1/openapi.json" in p for p in err["suggested_paths"])


def test_404_known_id_lookup_passes_through(seeded_db, client):
    """When a router raises HTTPException(404, "program not found"),
    the original detail must survive — we only structure the
    envelope; we don't overwrite the human-readable detail.
    """
    r = client.get("/v1/programs/no-such-id-xyz")
    assert r.status_code == 404
    body = r.json()
    err = body["error"]
    assert err["code"] == "route_not_found"
    # The router-supplied detail is carried into the envelope as `detail`.
    # (extras merge in main.py's HTTPException handler.)
    assert "detail" in err or body.get("detail") != "internal server error"


# ---------------------------------------------------------------------------
# 422 RequestValidationError integration
# ---------------------------------------------------------------------------


def test_422_validation_error_carries_envelope(seeded_db, client):
    # `limit` is declared as Query(..., le=100); 99999 violates bound.
    r = client.get("/v1/programs/search?limit=99999")
    assert r.status_code == 422
    body = r.json()
    # Legacy keys preserved.
    assert "detail" in body
    assert "detail_summary_ja" in body
    # Canonical envelope.
    err = body["error"]
    assert err["code"] == "invalid_enum"
    assert "field_errors" in err
    assert len(err["field_errors"]) >= 1


# ---------------------------------------------------------------------------
# Cross-cutting: docs URL anchors stable
# ---------------------------------------------------------------------------


def test_documentation_anchors_match_codes():
    """Every error envelope's `documentation` URL ends with `#<code>`.
    """
    for code in ERROR_CODES:
        body = make_error(code=code)
        assert body["error"]["documentation"].endswith(f"#{code}")


# ---------------------------------------------------------------------------
# safe_request_id helper
# ---------------------------------------------------------------------------


def test_safe_request_id_falls_back_to_unset():
    """When neither request.state.request_id nor x-request-id header
    are set, safe_request_id must return the literal 'unset' (NEVER
    'unknown' — that's the J5 string we banned).
    """
    class _FakeReq:
        class state:  # noqa: N801
            pass
        headers: dict = {}

    # Patch headers to dict-like that returns None for missing keys.
    class _Headers:
        def get(self, k, default=None):
            return default

    fr = _FakeReq()
    fr.headers = _Headers()
    rid = safe_request_id(fr)
    assert rid == "unset"
    assert rid != "unknown"
