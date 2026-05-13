"""P2.6.5 browser-hardening response headers.

Contract tests pinning the SecurityHeadersMiddleware output:

1. HSTS — every response carries ``Strict-Transport-Security`` with
   the 1-year + includeSubDomains + preload directive.
2. CSP — every response carries ``Content-Security-Policy`` with the
   ``default-src 'self'`` baseline and ``frame-ancestors 'none'``
   clickjacking guard, plus the A11 (2026-05-13) hardened directives
   (``object-src``, ``form-action``, ``upgrade-insecure-requests``,
   ``base-uri 'none'``).
3. X-Frame-Options — every response carries ``X-Frame-Options: DENY``.
4. Referrer-Policy — strict-origin-when-cross-origin so the path /
   query is never leaked cross-origin.
5. Permissions-Policy — 22 sensitive features opted out (A11 2026-05-13
   hardening, was 3).
6. Cross-Origin-Opener-Policy — same-origin so window.opener cannot
   leak across origins (popup-phishing defence).
7. Cross-Origin-Resource-Policy — same-origin so third-party origins
   cannot embed our JSON responses as <img>/<script>/<style>/etc.
8. X-Permitted-Cross-Domain-Policies — none, disabling legacy
   Flash/Acrobat policy file discovery.

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

    Asserts the load-bearing directives (baseline + A11 2026-05-13 hardening):
      - ``default-src 'self'`` so any unexpected resource class is blocked.
      - ``frame-ancestors 'none'`` so the response cannot be iframed even
        if a downstream client ignores X-Frame-Options.
      - ``object-src 'none'`` (Flash/Acrobat/Java embed denied).
      - ``form-action 'self'`` (form POSTs cannot be exfiltrated).
      - ``base-uri 'none'`` (no relative-URL hijack).
      - ``upgrade-insecure-requests`` (force HTTPS on any stray http:// ref).
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    csp = r.headers.get("Content-Security-Policy")
    assert csp is not None, "missing Content-Security-Policy header"
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    # A11 2026-05-13 hardening directives.
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp
    assert "base-uri 'none'" in csp
    assert "upgrade-insecure-requests" in csp


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


def test_response_carries_referrer_policy(client: TestClient) -> None:
    """Every response carries ``Referrer-Policy: strict-origin-when-cross-origin``.

    Leak the origin only on same-scheme cross-origin upgrades; never the
    path / query / fragment.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    rp = r.headers.get("Referrer-Policy")
    assert rp == "strict-origin-when-cross-origin", (
        f"expected strict-origin-when-cross-origin, got {rp!r}"
    )


def test_response_carries_permissions_policy_full_optout(client: TestClient) -> None:
    """Every response carries the full Permissions-Policy A11 22-feature opt-out.

    A11 2026-05-13 hardening expanded the original 3-feature opt-out
    (geolocation / microphone / camera) to 22 features so an injected
    content payload cannot quietly summon PaymentRequest, USB, WebXR,
    fullscreen, or any other UA-feature that is not part of the product.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    pp = r.headers.get("Permissions-Policy")
    assert pp is not None, "missing Permissions-Policy header"
    # Spot-check the load-bearing 9 — assert none of them is allowed.
    for feature in (
        "camera=()",
        "microphone=()",
        "geolocation=()",
        "payment=()",
        "usb=()",
        "publickey-credentials-get=()",
        "screen-wake-lock=()",
        "display-capture=()",
        "xr-spatial-tracking=()",
    ):
        assert feature in pp, f"missing {feature} in Permissions-Policy: {pp!r}"


def test_response_carries_cross_origin_opener_policy_same_origin(
    client: TestClient,
) -> None:
    """Every response carries ``Cross-Origin-Opener-Policy: same-origin``.

    Severs window.opener cross-origin leak; popup-phishing defence. The
    API never pops to a third party so same-origin is the strict default.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    coop = r.headers.get("Cross-Origin-Opener-Policy")
    assert coop == "same-origin", f"expected same-origin, got {coop!r}"


def test_response_carries_cross_origin_resource_policy_same_origin(
    client: TestClient,
) -> None:
    """Every response carries ``Cross-Origin-Resource-Policy: same-origin``.

    Blocks third-party origins from embedding our JSON / HTML responses
    as <img>/<script>/<style>/<audio>/etc. Routes that must serve truly
    cross-origin clients (e.g. discovery manifests) can override the
    middleware via ``response.headers["Cross-Origin-Resource-Policy"] =
    "cross-origin"`` (the middleware uses ``setdefault`` so an explicit
    upstream value is never silently overridden).
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    corp = r.headers.get("Cross-Origin-Resource-Policy")
    assert corp == "same-origin", f"expected same-origin, got {corp!r}"


def test_response_carries_x_permitted_cross_domain_policies_none(
    client: TestClient,
) -> None:
    """Every response carries ``X-Permitted-Cross-Domain-Policies: none``.

    Disables legacy Flash / Acrobat cross-domain-policy file discovery on
    this origin. Cheap belt-and-suspenders against attack surfaces that
    still cling to obsolete plugins.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    xpcdp = r.headers.get("X-Permitted-Cross-Domain-Policies")
    assert xpcdp == "none", f"expected none, got {xpcdp!r}"


def test_response_does_not_leak_unsafe_eval(client: TestClient) -> None:
    """CSP does NOT contain ``'unsafe-eval'``.

    Negative-pin: any future regression that adds ``'unsafe-eval'`` to
    re-enable eval() in a third-party SDK must be caught here. The API
    has no legitimate use for eval; an LLM-generated dependency that
    needs eval is a red flag.
    """
    r = client.get("/meta")
    assert r.status_code == 200, r.text

    csp = r.headers.get("Content-Security-Policy") or ""
    assert "'unsafe-eval'" not in csp, (
        f"unexpected 'unsafe-eval' in CSP: {csp!r}"
    )
