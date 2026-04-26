"""Sentry PII scrubbers — tests for src/jpintel_mcp/api/sentry_filters.py.

These scrubbers are wired into `sentry_sdk.init(before_send=..., before_send_transaction=...)`
inside `api/main.py::_init_sentry`. They are the last line of defence against
shipping an X-API-Key, Authorization header, Stripe signature, or billing
request body to Sentry's servers. A regression here is a compliance-level
incident (NYTimes-grade bad), so we unit-test the scrub logic end-to-end
against Sentry's event shape.

Sentry's own SDK isn't imported here — the scrubbers take plain dicts, so
the tests can hand-craft minimal Event / Transaction payloads without
bringing sentry_sdk along.
"""

from __future__ import annotations

from jpintel_mcp.api.sentry_filters import (
    _scrub_breadcrumbs,
    _scrub_request,
    sentry_before_send,
    sentry_before_send_transaction,
)

# ---------------------------------------------------------------------------
# _scrub_request — header / body / env scrubbing
# ---------------------------------------------------------------------------


def test_scrub_request_redacts_dict_headers_by_name_case_insensitive():
    req = {
        "headers": {
            "X-API-Key": "jpintel_super_secret_raw_key",
            "Authorization": "Bearer jpintel_another_secret",
            "Cookie": "jpintel_session=abc",
            "Stripe-Signature": "t=123,v1=deadbeef",
            "User-Agent": "curl/8.1",
        },
    }
    _scrub_request(req)
    assert req["headers"]["X-API-Key"] == "[scrubbed]"
    assert req["headers"]["Authorization"] == "[scrubbed]"
    assert req["headers"]["Cookie"] == "[scrubbed]"
    assert req["headers"]["Stripe-Signature"] == "[scrubbed]"
    # Non-sensitive header survives untouched.
    assert req["headers"]["User-Agent"] == "curl/8.1"


def test_scrub_request_redacts_list_headers_shape():
    """Sentry sometimes ships headers as [[name, value], ...]. Cover that path."""
    req = {
        "headers": [
            ["X-API-Key", "jpintel_raw"],
            ["Content-Type", "application/json"],
            ["authorization", "Bearer secret"],
        ],
    }
    _scrub_request(req)
    assert req["headers"][0] == ["X-API-Key", "[scrubbed]"]
    assert req["headers"][1] == ["Content-Type", "application/json"]
    assert req["headers"][2] == ["authorization", "[scrubbed]"]


def test_scrub_request_drops_cookies_and_env_wholesale():
    req = {"cookies": {"jpintel_session": "..."}, "env": {"REMOTE_ADDR": "1.2.3.4"}}
    _scrub_request(req)
    assert "cookies" not in req
    assert "env" not in req


def test_scrub_request_drops_body_on_billing_urls():
    """A /billing URL must never ship data / query_string to Sentry — might carry
    Stripe session_id / customer_id / webhook signed payload."""
    req = {
        "url": "https://api.example.com/v1/billing/checkout",
        "data": {"tier": "paid", "customer_email": "alice@example.com"},
        "query_string": "session_id=cs_test_xxx",
    }
    _scrub_request(req)
    assert "data" not in req
    assert "query_string" not in req


def test_scrub_request_keeps_body_on_non_billing_urls():
    """For /v1/programs, body and query_string stay — they're not PII."""
    req = {
        "url": "https://api.example.com/v1/programs?limit=10",
        "data": {"q": "設備投資"},
        "query_string": "limit=10",
    }
    _scrub_request(req)
    assert req["data"] == {"q": "設備投資"}
    assert req["query_string"] == "limit=10"


def test_scrub_request_none_input_is_noop():
    """Defensive: Sentry may hand us `request=None`."""
    # Should not raise.
    _scrub_request(None)


# ---------------------------------------------------------------------------
# _scrub_breadcrumbs — Stripe API URL scrubbing
# ---------------------------------------------------------------------------


def test_scrub_breadcrumbs_redacts_stripe_urls():
    """httplib breadcrumb to api.stripe.com gets path+method scrubbed.

    Without this, a breadcrumb URL like
    `https://api.stripe.com/v1/checkout/sessions/cs_live_a1b2c3/`
    would leak the live session id to Sentry.
    """
    bc = [
        {
            "category": "httplib",
            "data": {"url": "https://api.stripe.com/v1/checkout/sessions/cs_live_xxx",
                     "method": "POST"},
        },
        {
            "category": "httplib",
            "data": {"url": "https://example.com/v1/programs", "method": "GET"},
        },
    ]
    _scrub_breadcrumbs(bc)
    assert bc[0]["data"]["url"] == "https://api.stripe.com/[scrubbed]"
    assert "method" not in bc[0]["data"]
    # Non-stripe URL untouched.
    assert bc[1]["data"]["url"] == "https://example.com/v1/programs"
    assert bc[1]["data"]["method"] == "GET"


def test_scrub_breadcrumbs_ignores_non_httplib_category():
    bc = [{"category": "log", "data": {"url": "https://api.stripe.com/v1/x"}}]
    _scrub_breadcrumbs(bc)
    # Not in httplib category — left alone.
    assert bc[0]["data"]["url"] == "https://api.stripe.com/v1/x"


def test_scrub_breadcrumbs_none_input_is_noop():
    _scrub_breadcrumbs(None)
    _scrub_breadcrumbs([])


# ---------------------------------------------------------------------------
# sentry_before_send — the installed hook, end-to-end
# ---------------------------------------------------------------------------


def test_before_send_runs_request_and_breadcrumb_scrubbers():
    event = {
        "request": {
            "headers": {"X-API-Key": "raw"},
            "cookies": {"x": 1},
        },
        "breadcrumbs": [
            {"category": "httplib", "data": {"url": "https://api.stripe.com/v1/x"}}
        ],
    }
    out = sentry_before_send(event, {})
    assert out is event
    assert event["request"]["headers"]["X-API-Key"] == "[scrubbed]"
    assert "cookies" not in event["request"]
    assert event["breadcrumbs"][0]["data"]["url"] == "https://api.stripe.com/[scrubbed]"


def test_before_send_breadcrumbs_as_dict_values_shape():
    """Sentry's newer transport wraps breadcrumbs as {'values': [...]}."""
    event = {
        "request": {},
        "breadcrumbs": {
            "values": [
                {"category": "httplib",
                 "data": {"url": "https://api.stripe.com/v1/y", "method": "POST"}}
            ]
        },
    }
    sentry_before_send(event, {})
    assert event["breadcrumbs"]["values"][0]["data"]["url"] == "https://api.stripe.com/[scrubbed]"


def test_before_send_strips_user_pii_from_event():
    """send_default_pii=False already blocks most of this — belt-and-suspenders."""
    event = {
        "user": {
            "email": "alice@example.com",
            "ip_address": "203.0.113.9",
            "username": "alice",
            "id": "opaque-id-kept",
        }
    }
    sentry_before_send(event, {})
    assert "email" not in event["user"]
    assert "ip_address" not in event["user"]
    assert "username" not in event["user"]
    # Opaque identifiers MAY remain — they are not customer PII.
    assert event["user"]["id"] == "opaque-id-kept"


def test_before_send_returns_event_unchanged_when_no_sensitive_keys():
    event = {"level": "error", "message": "harmless"}
    out = sentry_before_send(event, {})
    assert out is event
    assert event == {"level": "error", "message": "harmless"}


# ---------------------------------------------------------------------------
# sentry_before_send_transaction — span body scrubbing on billing txns
# ---------------------------------------------------------------------------


def test_before_send_transaction_scrubs_billing_span_bodies():
    """On a /billing transaction, every span drops http.request.body /
    http.response.body — Stripe webhook payloads carry signatures + customer ids."""
    txn_event = {
        "transaction": "/billing/webhook",
        "request": {"headers": {"stripe-signature": "t=1,v1=xx"}},
        "spans": [
            {
                "op": "http.client",
                "data": {
                    "http.request.body": b"evt-body",
                    "http.response.body": b"stripe-response",
                    "http.method": "POST",
                },
            },
            {
                "op": "db.query",
                "data": {"db.statement": "SELECT 1"},
            },
        ],
    }
    out = sentry_before_send_transaction(txn_event, {})
    assert out is txn_event
    assert "http.request.body" not in txn_event["spans"][0]["data"]
    assert "http.response.body" not in txn_event["spans"][0]["data"]
    # Unrelated data keys survive.
    assert txn_event["spans"][0]["data"]["http.method"] == "POST"
    # Non-http span untouched.
    assert txn_event["spans"][1]["data"]["db.statement"] == "SELECT 1"


def test_before_send_transaction_non_billing_keeps_bodies():
    txn_event = {
        "transaction": "/v1/programs",
        "request": {},
        "spans": [
            {"op": "http.client", "data": {"http.request.body": b"keep-me"}}
        ],
    }
    sentry_before_send_transaction(txn_event, {})
    # /programs is not sensitive — bodies pass through.
    assert txn_event["spans"][0]["data"]["http.request.body"] == b"keep-me"


def test_before_send_transaction_runs_request_scrubber_too():
    """Even for non-billing transactions, request headers must be scrubbed."""
    txn_event = {
        "transaction": "/v1/programs",
        "request": {"headers": {"X-API-Key": "raw"}},
    }
    sentry_before_send_transaction(txn_event, {})
    assert txn_event["request"]["headers"]["X-API-Key"] == "[scrubbed]"
