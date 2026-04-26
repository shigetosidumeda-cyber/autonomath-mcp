"""Unit tests for the D+3 / D+7 / D+14 / D+30 onboarding send helpers.

These tests do NOT run the scheduler — they call each `send_dayN` helper
directly with a mock-transport `PostmarkClient` and assert on the outbound
payload shape. Follows the pattern in `tests/test_email.py` for the D+0
welcome path.
"""

from __future__ import annotations

import json

import httpx

from jpintel_mcp.email.onboarding import (
    _DAY3_EXAMPLE_IDS,
    TEMPLATE_DAY3,
    TEMPLATE_DAY7,
    TEMPLATE_DAY14,
    TEMPLATE_DAY30,
    send_day3_activation,
    send_day7_value,
    send_day14_inactive_reminder,
    send_day30_feedback,
)
from jpintel_mcp.email.postmark import (
    POSTMARK_BASE_URL,
    PostmarkClient,
)


def _mock_http(captured: list[httpx.Request]) -> httpx.Client:
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"MessageID": "stub-1", "ErrorCode": 0})

    return httpx.Client(
        base_url=POSTMARK_BASE_URL,
        transport=httpx.MockTransport(_handler),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": "test-token",
        },
    )


def _client(captured: list[httpx.Request]) -> PostmarkClient:
    return PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured),
    )


# ---------------------------------------------------------------------------
# Day 3
# ---------------------------------------------------------------------------


def test_send_day3_activation_payload_shape():
    captured: list[httpx.Request] = []
    resp = send_day3_activation(
        to="alice@example.com",
        api_key_last4="abcd",
        tier="paid",
        usage_count=0,
        client=_client(captured),
    )
    assert resp.get("MessageID") == "stub-1"
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == TEMPLATE_DAY3
    assert body["Tag"] == "onboarding-day3"
    assert body["MessageStream"] == "outbound"

    model = body["TemplateModel"]
    assert set(model.keys()) == {"key_last4", "tier", "usage_count", "has_used_key", "examples"}
    assert model["key_last4"] == "abcd"
    assert model["tier"] == "paid"
    assert model["usage_count"] == 0
    assert model["has_used_key"] is False
    assert len(model["examples"]) == 3
    # The 3 pinned unified_ids must be present in order.
    ids = [e["unified_id"] for e in model["examples"]]
    assert ids == ["UNI-14e57fbf79", "UNI-40bc849d45", "UNI-08d8284aae"]


def test_send_day3_sets_has_used_key_when_usage_positive():
    captured: list[httpx.Request] = []
    send_day3_activation(
        to="a@example.com",
        api_key_last4="1111",
        tier="paid",
        usage_count=7,
        client=_client(captured),
    )
    body = json.loads(captured[0].content)
    assert body["TemplateModel"]["has_used_key"] is True
    assert body["TemplateModel"]["usage_count"] == 7


def test_send_day3_examples_match_module_pins():
    """Regression guard: the 3 pinned unified_ids are the product's activation
    examples and must not silently drift."""
    captured: list[httpx.Request] = []
    send_day3_activation(
        to="x@example.com",
        api_key_last4="0000",
        tier="paid",
        usage_count=0,
        client=_client(captured),
    )
    body = json.loads(captured[0].content)
    assert body["TemplateModel"]["examples"] == list(_DAY3_EXAMPLE_IDS)


# ---------------------------------------------------------------------------
# Day 7
# ---------------------------------------------------------------------------


def test_send_day7_value_payload_shape():
    captured: list[httpx.Request] = []
    send_day7_value(
        to="b@example.com",
        api_key_last4="wxyz",
        tier="paid",
        usage_count=42,
        client=_client(captured),
    )
    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == TEMPLATE_DAY7
    assert body["Tag"] == "onboarding-day7"
    model = body["TemplateModel"]
    assert set(model.keys()) == {"key_last4", "tier", "usage_count"}
    assert model["usage_count"] == 42


# ---------------------------------------------------------------------------
# Day 14 (conditional)
# ---------------------------------------------------------------------------


def test_send_day14_skips_when_active():
    """Day14 must NOT send when usage_count > 0."""
    captured: list[httpx.Request] = []
    resp = send_day14_inactive_reminder(
        to="c@example.com",
        api_key_last4="q000",
        tier="paid",
        usage_count=3,
        client=_client(captured),
    )
    assert resp == {"skipped": True, "reason": "active"}
    assert captured == []  # no HTTP call made


def test_send_day14_sends_when_inactive():
    captured: list[httpx.Request] = []
    send_day14_inactive_reminder(
        to="d@example.com",
        api_key_last4="1234",
        tier="paid",
        usage_count=0,
        client=_client(captured),
    )
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == TEMPLATE_DAY14
    assert body["Tag"] == "onboarding-day14"
    model = body["TemplateModel"]
    assert set(model.keys()) == {"key_last4", "tier", "usage_count"}
    assert model["usage_count"] == 0


# ---------------------------------------------------------------------------
# Day 30
# ---------------------------------------------------------------------------


def test_send_day30_feedback_payload_shape_inactive_branch():
    captured: list[httpx.Request] = []
    send_day30_feedback(
        to="e@example.com",
        api_key_last4="aaaa",
        tier="paid",
        usage_count=0,
        client=_client(captured),
    )
    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == TEMPLATE_DAY30
    assert body["Tag"] == "onboarding-day30"
    model = body["TemplateModel"]
    assert set(model.keys()) == {"key_last4", "tier", "usage_count", "has_used_key"}
    assert model["has_used_key"] is False


def test_send_day30_feedback_has_used_key_true_when_active():
    captured: list[httpx.Request] = []
    send_day30_feedback(
        to="f@example.com",
        api_key_last4="bbbb",
        tier="paid",
        usage_count=120,
        client=_client(captured),
    )
    body = json.loads(captured[0].content)
    assert body["TemplateModel"]["has_used_key"] is True
    assert body["TemplateModel"]["usage_count"] == 120


# ---------------------------------------------------------------------------
# Cross-cutting: all 4 helpers must honor the test-mode gate
# ---------------------------------------------------------------------------


def test_all_helpers_honor_test_mode():
    """env == 'test' blocks every helper without raising."""
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="test",
    )
    for fn in (
        send_day3_activation,
        send_day7_value,
        send_day30_feedback,
    ):
        resp = fn(
            to="z@example.com",
            api_key_last4="0000",
            tier="paid",
            usage_count=5,
            client=client,
        )
        assert resp == {"skipped": True, "reason": "test_mode"}

    # Day14 with usage=0 should also hit test_mode path (not the active-skip).
    resp = send_day14_inactive_reminder(
        to="z@example.com",
        api_key_last4="0000",
        tier="paid",
        usage_count=0,
        client=client,
    )
    assert resp == {"skipped": True, "reason": "test_mode"}
