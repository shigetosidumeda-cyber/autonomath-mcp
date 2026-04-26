"""P2.6.5 browser-hardening response headers.

Three contract tests pinning the SecurityHeadersMiddleware output:

1. HSTS — every response carries ``Strict-Transport-Security`` with
   the 1-year + includeSubDomains + preload directive.
2. CSP — every response carries ``Content-Security-Policy`` with the
   ``default-src 'self'`` baseline and ``frame-ancestors 'none'``
   clickjacking guard.
3. X-Frame-Options — every response carries ``X-Frame-Options: DENY``.

We pick ``/meta`` for the smoke endpoint because it is mounted
without ``AnonIpLimitDep`` so a single test invocation cannot trip
the anonymous quota gate (which would short-circuit before the
header middleware fires on a second call).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_response_carries_hsts_header(client: TestClient) -> None:
    """Every successful response includes the HSTS header.

    1 year max-age + includeSubDomains + preload — long-lived because
    autonomath.ai is HTTPS-only and we want browsers to refuse plain
    HTTP from the very first request.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    hsts = r.headers.get("Strict-Transport-Security")
    assert hsts is not None, "missing Strict-Transport-Security header"
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" in hsts


def test_response_carries_csp_header(client: TestClient) -> None:
    """Every response includes a CSP that enforces same-origin defaults.

    Asserts the two load-bearing directives:
      - ``default-src 'self'`` so any unexpected resource class is blocked.
      - ``frame-ancestors 'none'`` so the response cannot be iframed even
        if a downstream client ignores X-Frame-Options.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    csp = r.headers.get("Content-Security-Policy")
    assert csp is not None, "missing Content-Security-Policy header"
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_response_carries_x_frame_options_deny(client: TestClient) -> None:
    """Every response includes ``X-Frame-Options: DENY``.

    Redundant with the CSP ``frame-ancestors 'none'`` directive but kept
    so legacy browsers that don't honour CSP3 still refuse to embed our
    surfaces in a clickjack frame.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    xfo = r.headers.get("X-Frame-Options")
    assert xfo == "DENY", f"expected DENY, got {xfo!r}"
