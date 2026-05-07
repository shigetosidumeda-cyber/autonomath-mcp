"""Sentry before_send / before_send_transaction scrubbers.

Goal: never ship raw API keys, billing bodies, Stripe customer IDs, or
authorization headers to Sentry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sentry_sdk._types import Event

_HEADERS_TO_STRIP = {
    "x-api-key",
    "authorization",
    "cookie",
    "stripe-signature",
    # Raw IP: Fly terminates TLS and forwards the client IP in these headers.
    # We already hash anon IPs for the rate limiter (api/anon_limit.py) — the
    # raw value must not reach Sentry. send_default_pii=False covers most of
    # this, but headers are the belt-and-suspenders path.
    "x-forwarded-for",
    "fly-client-ip",
    "x-real-ip",
}


def _scrub_request(request: dict[str, Any] | None) -> None:
    if not request:
        return

    headers = request.get("headers") or {}
    if isinstance(headers, dict):
        for k in list(headers.keys()):
            if k.lower() in _HEADERS_TO_STRIP:
                headers[k] = "[scrubbed]"
    elif isinstance(headers, list):
        for i, pair in enumerate(headers):
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                name = str(pair[0]).lower()
                if name in _HEADERS_TO_STRIP:
                    headers[i] = [pair[0], "[scrubbed]"]

    request.pop("cookies", None)
    request.pop("env", None)

    url = request.get("url") or ""
    if "/billing" in url:
        request.pop("data", None)
        request.pop("query_string", None)


def _scrub_breadcrumbs(breadcrumbs: list[dict[str, Any]] | None) -> None:
    if not breadcrumbs:
        return
    for bc in breadcrumbs:
        if bc.get("category") == "httplib":
            data = bc.get("data") or {}
            url = str(data.get("url", ""))
            if "api.stripe.com" in url:
                data["url"] = "https://api.stripe.com/[scrubbed]"
                data.pop("method", None)


def sentry_before_send(event: Event, hint: dict[str, Any]) -> Event | None:
    _scrub_request(event.get("request"))
    bc = event.get("breadcrumbs")
    if isinstance(bc, dict):
        _scrub_breadcrumbs(bc.get("values"))
    elif isinstance(bc, list):
        _scrub_breadcrumbs(bc)

    user = event.get("user")
    if isinstance(user, dict):
        user.pop("email", None)
        user.pop("ip_address", None)
        user.pop("username", None)

    return event


def sentry_before_send_transaction(event: Event, hint: dict[str, Any]) -> Event | None:
    _scrub_request(event.get("request"))
    txn = event.get("transaction") or ""
    if txn.startswith("/billing"):
        for span in event.get("spans") or []:  # type: ignore[union-attr]  # Event.spans is a typed union not a dict-accessor
            data = cast("dict[str, Any]", span.get("data") or {})  # span is dict at runtime
            data.pop("http.request.body", None)
            data.pop("http.response.body", None)
    return event
