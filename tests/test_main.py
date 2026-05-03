"""Tests for api/main.py middleware: CORS hardening + X-Request-ID validation.

Background — 2026-04-25 CORS audit (a0a7316a311c3ffd9):
* P2: ``CORSMiddleware(allow_methods=["*"], allow_headers=["*"])`` was too
  permissive. Restricted to the 4 verbs we actually serve and the 6
  inbound headers we actually inspect, plus a 1h preflight cache.
* P3: ``_RequestContextMiddleware`` echoed the inbound ``X-Request-ID``
  header verbatim. A malicious client could inject ``\\nLOG_INJECT`` etc.
  into our structured logs / response headers. We now validate the
  inbound id against ``^[A-Za-z0-9-]{8,64}$`` and replace it with a
  fresh ``secrets.token_hex(8)`` if the format does not match.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


_TOKEN_HEX_8_RE = re.compile(r"^[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# CORS: methods / headers restriction
# ---------------------------------------------------------------------------


def test_cors_methods_restricted(client: TestClient) -> None:
    """OPTIONS preflight for PATCH must NOT advertise PATCH as allowed.

    Past state echoed ``allow_methods=["*"]`` which let browsers send any
    verb. We now whitelist GET/POST/DELETE/OPTIONS only.
    """
    resp = client.options(
        "/v1/programs",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    allow = resp.headers.get("access-control-allow-methods", "")
    # The middleware should not advertise PATCH (or "*") for our surface.
    assert "PATCH" not in allow.upper().split(", "), (
        f"PATCH leaked into Access-Control-Allow-Methods: {allow!r}"
    )
    assert "*" not in allow, (
        f"Wildcard method leaked into Access-Control-Allow-Methods: {allow!r}"
    )


def test_cors_allows_cost_cap_preflight(client: TestClient) -> None:
    """Browser paid bulk calls need the cost-cap/idempotency headers."""
    resp = client.options(
        "/v1/programs/batch",
        headers={
            "Origin": "https://jpcite.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "X-API-Key, X-Cost-Cap-JPY, Idempotency-Key, Content-Type"
            ),
        },
    )
    assert resp.status_code in {200, 204}
    allow_headers = resp.headers.get("access-control-allow-headers", "")
    assert "X-Cost-Cap-JPY" in allow_headers


def test_cors_exposes_cost_cap_short_circuit(client: TestClient) -> None:
    """Cost-cap errors must remain readable by browser clients."""
    resp = client.post(
        "/v1/unknown/bulk_preview",
        json={"items": ["x"]},
        headers={
            "Origin": "https://jpcite.com",
            "X-API-Key": "am_live_shape_only",
        },
    )
    assert resp.status_code == 400
    assert resp.headers.get("access-control-allow-origin") == "https://jpcite.com"
    exposed = resp.headers.get("access-control-expose-headers", "")
    assert "X-Cost-Cap-Required" in exposed
    assert resp.headers.get("X-Cost-Cap-Required") == "true"


# ---------------------------------------------------------------------------
# X-Request-ID: format validation
# ---------------------------------------------------------------------------


def test_request_id_invalid_format_replaced(client: TestClient) -> None:
    """Malformed inbound X-Request-ID must be discarded and replaced.

    A header carrying ``@``, newline, or log-injection payload should
    NEVER appear in the response — we synthesise a fresh
    ``secrets.token_hex(8)`` id instead.
    """
    bad = "bad@id\nLOG_INJECT"
    resp = client.get("/healthz", headers={"X-Request-ID": bad})
    out = resp.headers.get("x-request-id", "")
    assert out != bad, "malicious X-Request-ID echoed back into response"
    assert "\n" not in out and "@" not in out, (
        f"unsanitised id leaked: {out!r}"
    )
    # Format = secrets.token_hex(8) → 16 lowercase hex chars.
    assert _TOKEN_HEX_8_RE.fullmatch(out), (
        f"replacement id is not token_hex(8): {out!r}"
    )


def test_request_id_valid_format_echoed(client: TestClient) -> None:
    """A well-formed X-Request-ID (alnum + hyphen, 8–64 chars) is echoed."""
    good = "abc-123-valid-id"
    resp = client.get("/healthz", headers={"X-Request-ID": good})
    assert resp.headers.get("x-request-id") == good
