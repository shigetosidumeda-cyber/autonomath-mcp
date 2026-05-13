"""Wave 10 API route smoke for revenue/customer surfaces.

These tests are intentionally shallow: they verify high-risk routes are mounted
and that unauthenticated callers hit auth/payment guards instead of 500s. They
avoid seeded corpus scans, Stripe calls, outbound webhook delivery, and export
materialization.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


MOUNTED_ROUTE_EXPECTATIONS: Mapping[str, tuple[str, set[str]]] = {
    "houjin_360": ("/v1/houjin/{houjin_bangou}/360", {"GET"}),
    "tax_chain": ("/v1/tax_rules/{rule_id}/full_chain", {"GET"}),
    "saved_searches": ("/v1/me/saved_searches", {"GET", "POST"}),
    "saved_searches_results": ("/v1/me/saved_searches/{saved_id}/results", {"GET"}),
    "client_profiles": ("/v1/me/client_profiles", {"GET"}),
    "client_profiles_bulk_import": ("/v1/me/client_profiles/bulk_import", {"POST"}),
    "credit_wallet_balance": ("/v1/wallet/balance", {"GET"}),
    "credit_wallet_topup": ("/v1/wallet/topup", {"POST"}),
    "billing_portal": ("/v1/billing/portal", {"POST"}),
    "me_billing_portal": ("/v1/me/billing-portal", {"POST"}),
    "billing_acp_portal_link": ("/v1/billing/acp/portal_link", {"POST"}),
    "billing_webhook": ("/v1/billing/webhook", {"POST"}),
    "customer_webhooks": ("/v1/me/webhooks", {"GET", "POST"}),
    "customer_webhook_test": ("/v1/me/webhooks/{webhook_id}/test", {"POST"}),
    "customer_webhook_deliveries": ("/v1/me/webhooks/{webhook_id}/deliveries", {"GET"}),
    "export_formats": ("/v1/export/formats", {"GET"}),
    "export_create": ("/v1/export", {"POST"}),
    "export_reissue": ("/v1/export/{export_id}", {"GET"}),
}

OPENAPI_ROUTE_EXPECTATIONS: Mapping[str, tuple[str, set[str]]] = {
    key: value
    for key, value in MOUNTED_ROUTE_EXPECTATIONS.items()
    if key != "billing_webhook"
}

GUARD_PROBES: tuple[tuple[str, str, str, dict[str, Any] | None, set[int]], ...] = (
    ("saved_searches", "GET", "/v1/me/saved_searches", None, {401}),
    ("client_profiles", "GET", "/v1/me/client_profiles", None, {401}),
    ("credit_wallet", "GET", "/v1/wallet/balance", None, {401}),
    (
        "billing_portal",
        "POST",
        "/v1/billing/portal",
        {"customer_id": "cus_smoke", "return_url": "https://jpcite.com/dashboard"},
        {401},
    ),
    ("me_billing_portal", "POST", "/v1/me/billing-portal", None, {401, 403}),
    ("customer_webhooks", "GET", "/v1/me/webhooks", None, {401}),
    ("customer_webhook_test", "POST", "/v1/me/webhooks/1/test", None, {401}),
    (
        "export",
        "POST",
        "/v1/export",
        {"dataset": "programs", "format": "csv", "limit": 1},
        {401, 402},
    ),
)


def _mounted_routes(client: TestClient) -> dict[str, set[str]]:
    mounted: dict[str, set[str]] = {}
    for route in client.app.routes:
        if isinstance(route, APIRoute):
            mounted.setdefault(route.path, set()).update(route.methods or set())
    return mounted


def _openapi_routes(client: TestClient) -> dict[str, set[str]]:
    schema = client.app.openapi()
    return {
        path: {method.upper() for method in operations}
        for path, operations in schema["paths"].items()
    }


def _json_body(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _assert_guard_envelope(body: Any) -> None:
    haystack = repr(body).lower()
    assert any(
        token in haystack
        for token in (
            "auth",
            "api key",
            "x-api-key",
            "scope",
            "csrf",
            "paid",
            "payment",
            "upgrade",
        )
    ), body


def test_revenue_customer_routes_are_mounted(client: TestClient) -> None:
    mounted = _mounted_routes(client)

    for label, (path, methods) in MOUNTED_ROUTE_EXPECTATIONS.items():
        assert path in mounted, f"{label} route not mounted: {path}"
        assert methods <= mounted[path], f"{label} route missing methods: {methods - mounted[path]}"


def test_public_revenue_customer_routes_are_in_openapi(client: TestClient) -> None:
    openapi = _openapi_routes(client)

    for label, (path, methods) in OPENAPI_ROUTE_EXPECTATIONS.items():
        assert path in openapi, f"{label} route missing from OpenAPI: {path}"
        missing = methods - openapi[path]
        assert methods <= openapi[path], f"{label} OpenAPI missing methods: {missing}"


@pytest.mark.parametrize(
    ("label", "method", "path", "json_body", "expected_statuses"),
    GUARD_PROBES,
)
def test_unauthenticated_revenue_customer_routes_stop_at_guard(
    client: TestClient,
    label: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None,
    expected_statuses: set[int],
) -> None:
    smoke = TestClient(client.app, raise_server_exceptions=False)
    response = smoke.request(method, path, json=json_body)
    body = _json_body(response)

    assert response.status_code in expected_statuses, (label, response.status_code, body)
    assert response.status_code < 500, (label, response.status_code, body)
    _assert_guard_envelope(body)


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "expected_statuses"),
    (
        ("GET", "/v1/export/formats", {}, {200}),
        ("GET", "/v1/billing/acp/discovery", {}, {200}),
        ("GET", "/v1/billing/x402/discovery", {}, {200}),
    ),
)
def test_public_revenue_routes_do_not_500(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, Any],
    expected_statuses: set[int],
) -> None:
    smoke = TestClient(client.app, raise_server_exceptions=False)
    response = smoke.request(method, path, **kwargs)
    body = _json_body(response)

    assert response.status_code in expected_statuses, (path, response.status_code, body)
    assert response.status_code < 500, (path, response.status_code, body)


def test_billing_webhook_bad_signature_does_not_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_route_smoke")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_route_smoke")
    smoke = TestClient(client.app, raise_server_exceptions=False)
    response = smoke.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "bad"},
    )
    body = _json_body(response)

    assert response.status_code == 400, (response.status_code, body)
    assert response.status_code < 500, (response.status_code, body)
