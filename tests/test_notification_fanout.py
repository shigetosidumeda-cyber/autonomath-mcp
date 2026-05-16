"""Wave 51 L5 — tests for the notification_fanout module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jpintel_mcp.notification_fanout import (
    FANOUT_SCHEMA_VERSION,
    ChannelRegistry,
    ChannelTarget,
    DeferredDelivery,
    FakeChannelAdapter,
    FanoutPlan,
    FanoutResult,
    NotificationEvent,
    ScheduledDelivery,
    build_fanout_plan,
    default_registry,
    horizon_hours,
)

RUN_AT = datetime(2026, 5, 17, 4, 0, 0, tzinfo=UTC)


def _evt(
    *,
    event_id: str,
    subscriber_id: str = "sub_alpha",
    scheduled_at: str = "2026-05-17T12:00:00+00:00",
    subject: str = "Test event",
    body: str = "Test body",
    severity: str = "info",
    payload: dict[str, object] | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_id=event_id,
        subscriber_id=subscriber_id,
        scheduled_at=scheduled_at,
        subject=subject,
        body=body,
        severity=severity,  # type: ignore[arg-type]
        payload=payload or {},
    )


def _email_target(
    *,
    target_id: str = "tgt_email_1",
    subscriber_id: str = "sub_alpha",
    address: str = "alice@example.com",
    active: bool = True,
) -> ChannelTarget:
    return ChannelTarget(
        target_id=target_id,
        subscriber_id=subscriber_id,
        channel="email",
        address=address,
        active=active,
    )


def _slack_target(
    *,
    target_id: str = "tgt_slack_1",
    subscriber_id: str = "sub_alpha",
    address: str = "https://hooks.slack.com/services/T000/B000/XXX",
) -> ChannelTarget:
    return ChannelTarget(
        target_id=target_id, subscriber_id=subscriber_id, channel="slack", address=address
    )


def _webhook_target(
    *,
    target_id: str = "tgt_webhook_1",
    subscriber_id: str = "sub_alpha",
    address: str = "https://example.com/hook",
) -> ChannelTarget:
    return ChannelTarget(
        target_id=target_id, subscriber_id=subscriber_id, channel="webhook", address=address
    )


def _in_app_target(
    *,
    target_id: str = "tgt_inapp_1",
    subscriber_id: str = "sub_alpha",
    address: str = "0" * 32,
) -> ChannelTarget:
    return ChannelTarget(
        target_id=target_id, subscriber_id=subscriber_id, channel="in_app", address=address
    )


def test_schema_version_pinned() -> None:
    assert FANOUT_SCHEMA_VERSION == "jpcite.notification_fanout.v1"


def test_email_target_rejects_invalid_address() -> None:
    with pytest.raises(ValidationError, match="email"):
        ChannelTarget(target_id="t1", subscriber_id="s1", channel="email", address="not-email")


def test_slack_target_rejects_non_slack_url() -> None:
    with pytest.raises(ValidationError, match="slack"):
        ChannelTarget(
            target_id="t1", subscriber_id="s1", channel="slack", address="https://example.com/wh"
        )


def test_webhook_target_rejects_plaintext_http() -> None:
    with pytest.raises(ValidationError, match="webhook"):
        ChannelTarget(
            target_id="t1", subscriber_id="s1", channel="webhook", address="http://example.com/h"
        )


def test_in_app_target_rejects_non_hex_token() -> None:
    with pytest.raises(ValidationError, match="in_app"):
        ChannelTarget(target_id="t1", subscriber_id="s1", channel="in_app", address="not-hex")


def test_in_app_target_accepts_canonical_hex32() -> None:
    target = ChannelTarget(target_id="t1", subscriber_id="s1", channel="in_app", address="a" * 32)
    assert target.channel == "in_app"


def test_fanout_plan_rejects_unknown_rate_cap_channel() -> None:
    with pytest.raises(ValidationError, match="unknown channels"):
        FanoutPlan(rate_caps={"smoke_signal": 10})


def test_fanout_plan_rejects_negative_rate_cap() -> None:
    with pytest.raises(ValidationError, match="must be in"):
        FanoutPlan(rate_caps={"email": -1})


def test_fanout_plan_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError, match="unknown severities"):
        FanoutPlan(severity_order={"emergency": 0})


def test_fanout_plan_defaults_match_design_doc() -> None:
    plan = FanoutPlan()
    assert plan.sla_hours == 24
    assert plan.rate_caps == {"email": 1000, "slack": 500, "webhook": 1000, "in_app": 5000}
    assert plan.severity_order == {"critical": 0, "warning": 1, "info": 2}


def test_horizon_hours_naive_run_at_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        horizon_hours("2026-05-17T12:00:00+00:00", run_at=datetime(2026, 5, 17, 4, 0, 0))


def test_horizon_hours_positive_future_event() -> None:
    h = horizon_hours("2026-05-17T12:00:00+00:00", run_at=RUN_AT)
    assert h == pytest.approx(8.0)


def test_horizon_hours_z_suffix_accepted() -> None:
    h = horizon_hours("2026-05-17T12:00:00Z", run_at=RUN_AT)
    assert h == pytest.approx(8.0)


def test_registry_has_returns_true_after_register() -> None:
    registry = ChannelRegistry()
    registry.register(FakeChannelAdapter("email"))
    assert registry.has("email") is True
    assert registry.has("slack") is False


def test_registry_rejects_double_register() -> None:
    registry = ChannelRegistry()
    registry.register(FakeChannelAdapter("email"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeChannelAdapter("email"))


def test_registry_get_raises_on_missing_channel() -> None:
    registry = ChannelRegistry()
    with pytest.raises(KeyError, match="no adapter registered"):
        registry.get("slack")


def test_default_registry_has_all_4_channels() -> None:
    registry = default_registry()
    for ch in ("email", "slack", "webhook", "in_app"):
        assert registry.has(ch) is True  # type: ignore[arg-type]
    assert registry.channels() == ("email", "in_app", "slack", "webhook")


def test_fanout_happy_path_email_only() -> None:
    result = build_fanout_plan([_evt(event_id="e1")], [_email_target()], run_at=RUN_AT)
    assert isinstance(result, FanoutResult)
    assert result.scheduled_count == 1
    assert result.deferred_count == 0
    assert result.scheduled[0].channel == "email"


def test_fanout_all_4_channels_for_one_event() -> None:
    targets = [_email_target(), _slack_target(), _webhook_target(), _in_app_target()]
    result = build_fanout_plan([_evt(event_id="e1")], targets, run_at=RUN_AT)
    assert result.scheduled_count == 4
    assert [s.channel for s in result.scheduled] == ["email", "in_app", "slack", "webhook"]


def test_fanout_derives_run_id_from_run_at() -> None:
    result = build_fanout_plan([_evt(event_id="e1")], [_email_target()], run_at=RUN_AT)
    assert result.fanout_run_id == "fanout@2026_05_17"


def test_fanout_run_id_override_accepted() -> None:
    result = build_fanout_plan(
        [_evt(event_id="e1")],
        [_email_target()],
        run_at=RUN_AT,
        fanout_run_id="fanout@2026_05_18",
    )
    assert result.fanout_run_id == "fanout@2026_05_18"


def test_fanout_run_id_invalid_override_rejected() -> None:
    with pytest.raises(ValidationError, match="fanout_run_id must match"):
        build_fanout_plan(
            [_evt(event_id="e1")],
            [_email_target()],
            run_at=RUN_AT,
            fanout_run_id="daily@2026_05_17",
        )


def test_fanout_sla_overflow_deferred() -> None:
    event = _evt(event_id="e_stale", scheduled_at="2026-05-18T05:00:00+00:00")
    result = build_fanout_plan([event], [_email_target()], run_at=RUN_AT)
    assert result.scheduled_count == 0
    assert result.deferred[0].reason == "sla_overflow"
    assert result.deferred[0].channel is None


def test_fanout_no_target_deferred() -> None:
    event = _evt(event_id="e_orphan", subscriber_id="sub_unknown")
    result = build_fanout_plan([event], [_email_target()], run_at=RUN_AT)
    assert result.scheduled_count == 0
    assert result.deferred[0].reason == "no_target"


def test_fanout_adapter_unavailable_deferred() -> None:
    registry = ChannelRegistry()
    registry.register(FakeChannelAdapter("email"))
    result = build_fanout_plan(
        [_evt(event_id="e1")], [_slack_target()], run_at=RUN_AT, registry=registry
    )
    assert result.deferred[0].reason == "adapter_unavailable"
    assert result.deferred[0].channel == "slack"


def test_fanout_rate_cap_defers_surplus() -> None:
    plan = FanoutPlan(rate_caps={"email": 2, "slack": 500, "webhook": 1000, "in_app": 5000})
    events = [_evt(event_id="e1"), _evt(event_id="e2"), _evt(event_id="e3")]
    result = build_fanout_plan(events, [_email_target()], run_at=RUN_AT, plan=plan)
    assert result.scheduled_count == 2
    assert result.deferred[0].reason == "rate_capped"


def test_fanout_inactive_target_skipped_silently() -> None:
    result = build_fanout_plan([_evt(event_id="e1")], [_email_target(active=False)], run_at=RUN_AT)
    assert result.scheduled_count == 0
    assert result.deferred[0].reason == "no_target"


def test_fanout_severity_ordering_critical_first() -> None:
    plan = FanoutPlan(rate_caps={"email": 1, "slack": 500, "webhook": 1000, "in_app": 5000})
    events = [
        _evt(event_id="e_info", severity="info"),
        _evt(event_id="e_warn", severity="warning"),
        _evt(event_id="e_crit", severity="critical"),
    ]
    result = build_fanout_plan(events, [_email_target()], run_at=RUN_AT, plan=plan)
    assert result.scheduled[0].event_id == "e_crit"


def test_fanout_byte_identical_re_run() -> None:
    events = [
        _evt(event_id="e1", severity="warning"),
        _evt(event_id="e2", severity="info"),
        _evt(event_id="e3", severity="critical"),
    ]
    targets = [_email_target(), _slack_target()]
    a = build_fanout_plan(events, targets, run_at=RUN_AT)
    b = build_fanout_plan(events, targets, run_at=RUN_AT)
    assert a.model_dump_json() == b.model_dump_json()


def test_fanout_empty_input_yields_empty_artifact() -> None:
    result = build_fanout_plan([], [], run_at=RUN_AT)
    assert result.scheduled_count == 0
    assert result.deferred_count == 0


def test_fanout_naive_run_at_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_fanout_plan([], [], run_at=datetime(2026, 5, 17, 4, 0, 0))


def test_fanout_result_count_mismatch_rejected() -> None:
    with pytest.raises(ValidationError, match="scheduled_count"):
        FanoutResult(
            fanout_run_id="fanout@2026_05_17",
            run_at="2026-05-17T04:00:00+00:00",
            plan=FanoutPlan(),
            scheduled=(),
            deferred=(),
            scheduled_count=99,
            deferred_count=0,
            counts_by_channel={"email": 0, "slack": 0, "webhook": 0, "in_app": 0},
            counts_by_defer_reason={
                "rate_capped": 0,
                "sla_overflow": 0,
                "no_target": 0,
                "adapter_unavailable": 0,
            },
        )


def test_fanout_result_channel_count_sum_mismatch_rejected() -> None:
    with pytest.raises(ValidationError, match="sum"):
        FanoutResult(
            fanout_run_id="fanout@2026_05_17",
            run_at="2026-05-17T04:00:00+00:00",
            plan=FanoutPlan(),
            scheduled=(),
            deferred=(),
            scheduled_count=0,
            deferred_count=0,
            counts_by_channel={"email": 1, "slack": 0, "webhook": 0, "in_app": 0},
            counts_by_defer_reason={
                "rate_capped": 0,
                "sla_overflow": 0,
                "no_target": 0,
                "adapter_unavailable": 0,
            },
        )


def test_fanout_result_unknown_defer_reason_key_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown keys"):
        FanoutResult(
            fanout_run_id="fanout@2026_05_17",
            run_at="2026-05-17T04:00:00+00:00",
            plan=FanoutPlan(),
            scheduled=(),
            deferred=(),
            scheduled_count=0,
            deferred_count=0,
            counts_by_channel={"email": 0, "slack": 0, "webhook": 0, "in_app": 0},
            counts_by_defer_reason={"squirrel_attack": 0},
        )


def test_fake_adapter_records_calls_without_io() -> None:
    fake = FakeChannelAdapter("email")
    delivery = ScheduledDelivery(
        event_id="e1",
        subscriber_id="sub_alpha",
        target_id="tgt_email_1",
        channel="email",
        address="alice@example.com",
        subject="Hi",
        severity="info",
        scheduled_at="2026-05-17T12:00:00+00:00",
    )
    assert fake.calls == []
    fake.send(delivery)
    assert fake.calls == [delivery]


def test_deferred_delivery_channel_may_be_none() -> None:
    row = DeferredDelivery(
        event_id="e1", subscriber_id="sub_alpha", channel=None, reason="sla_overflow"
    )
    assert row.channel is None
