"""Tests for the global unhandled-exception handler in api.main.create_app.

Ensures:
- Routes that raise a non-HTTPException return status 500 with a JSON body
  containing ``detail`` and ``request_id``, plus an x-request-id response header.
- A caller-supplied x-request-id is echoed back on the 500 response.
- FastAPI's normal HTTPException handling is not swallowed (404 stays 404,
  body is not the generic 500 payload).
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _app_with_boom():
    """Build a fresh app and register a test-only route that raises."""
    from jpintel_mcp.api.main import create_app

    app = create_app()

    def _boom() -> int:
        return 1 // 0  # ZeroDivisionError -> unhandled

    # Use add_api_route (least invasive, no router decorator).
    app.router.add_api_route("/_test_boom", _boom, methods=["GET"])
    return app


def test_unhandled_exception_returns_500_json_with_request_id(seeded_db):
    app = _app_with_boom()
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/_test_boom")
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "internal server error"
    assert "request_id" in body
    assert body["request_id"]
    # Response header must carry the same request id.
    assert r.headers.get("x-request-id") == body["request_id"]


def test_unhandled_exception_propagates_caller_request_id(seeded_db):
    app = _app_with_boom()
    client = TestClient(app, raise_server_exceptions=False)

    rid = "test-rid-abcdef0123456789"
    r = client.get("/_test_boom", headers={"x-request-id": rid})
    assert r.status_code == 500
    body = r.json()
    assert body["request_id"] == rid
    assert r.headers.get("x-request-id") == rid


def test_http_exception_is_not_converted_to_500(client):
    # /v1/programs/{id} with a missing id raises HTTPException(404).
    # The global Exception handler must NOT convert this to 500.
    r = client.get("/v1/programs/no-such-id-xyz")
    assert r.status_code == 404
    body = r.json()
    # FastAPI's default HTTPException body shape is {"detail": "..."}.
    assert body.get("detail") != "internal server error"
