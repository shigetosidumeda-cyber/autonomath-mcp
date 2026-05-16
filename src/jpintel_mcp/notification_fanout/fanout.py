"""Wave 51 L5 — notification_fanout core (deterministic event-to-channel planner)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from jpintel_mcp.notification_fanout.models import (
    ChannelTarget,
    DeferredDelivery,
    DeliveryChannel,
    FanoutPlan,
    FanoutResult,
    NotificationEvent,
    ScheduledDelivery,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


@runtime_checkable
class ChannelAdapter(Protocol):
    """Runtime contract for a delivery adapter (NOT used by the planner)."""

    channel: DeliveryChannel

    def send(self, delivery: ScheduledDelivery) -> None:
        """Dispatch one delivery. NEVER called from the planner."""
        ...


class ChannelRegistry:
    """In-process registry mapping channel name → adapter."""

    __slots__ = ("_adapters",)

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        if adapter.channel in self._adapters:
            raise ValueError(
                f"channel {adapter.channel!r} already registered; "
                "construct a fresh ChannelRegistry to rebind"
            )
        self._adapters[adapter.channel] = adapter

    def has(self, channel: DeliveryChannel) -> bool:
        return channel in self._adapters

    def get(self, channel: DeliveryChannel) -> ChannelAdapter:
        try:
            return self._adapters[channel]
        except KeyError as exc:
            raise KeyError(
                f"no adapter registered for channel {channel!r}; "
                f"registered={sorted(self._adapters)}"
            ) from exc

    def channels(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


class FakeChannelAdapter:
    """Test-only adapter that records calls without performing I/O."""

    __slots__ = ("channel", "calls")

    def __init__(self, channel: DeliveryChannel) -> None:
        self.channel: DeliveryChannel = channel
        self.calls: list[ScheduledDelivery] = []

    def send(self, delivery: ScheduledDelivery) -> None:
        self.calls.append(delivery)


def default_registry() -> ChannelRegistry:
    """Return a registry with stub adapters for all 4 channels."""
    registry = ChannelRegistry()
    registry.register(FakeChannelAdapter("email"))
    registry.register(FakeChannelAdapter("slack"))
    registry.register(FakeChannelAdapter("webhook"))
    registry.register(FakeChannelAdapter("in_app"))
    return registry


def _parse_iso_utc(value: str) -> datetime:
    if not value:
        raise ValueError("ISO 8601 timestamp must be non-empty")
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"could not parse ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"ISO 8601 timestamp must be timezone-aware (got naive {value!r})")
    return parsed.astimezone(UTC)


def horizon_hours(scheduled_at: str, *, run_at: datetime) -> float:
    """Return the SLA horizon in hours: ``scheduled_at - run_at``."""
    if run_at.tzinfo is None:
        raise ValueError("run_at= must be timezone-aware (UTC)")
    scheduled = _parse_iso_utc(scheduled_at)
    delta = scheduled - run_at
    return delta.total_seconds() / 3600.0


def _derive_run_id(run_at: datetime) -> str:
    d = run_at.astimezone(UTC).date()
    return f"fanout@{d.year:04d}_{d.month:02d}_{d.day:02d}"


def _aggregate(
    scheduled: Sequence[ScheduledDelivery],
    deferred: Sequence[DeferredDelivery],
) -> tuple[dict[str, int], dict[str, int]]:
    counts_channel: dict[str, int] = {
        "email": 0,
        "slack": 0,
        "webhook": 0,
        "in_app": 0,
    }
    counts_reason: dict[str, int] = {
        "rate_capped": 0,
        "sla_overflow": 0,
        "no_target": 0,
        "adapter_unavailable": 0,
    }
    for s in scheduled:
        counts_channel[s.channel] = counts_channel.get(s.channel, 0) + 1
    for d in deferred:
        counts_reason[d.reason] = counts_reason.get(d.reason, 0) + 1
    return counts_channel, counts_reason


def build_fanout_plan(
    events: Iterable[NotificationEvent],
    targets: Iterable[ChannelTarget],
    *,
    run_at: datetime,
    plan: FanoutPlan | None = None,
    registry: ChannelRegistry | None = None,
    fanout_run_id: str | None = None,
) -> FanoutResult:
    """Run the full fanout planner and return a :class:`FanoutResult`."""
    if run_at.tzinfo is None:
        raise ValueError("run_at= must be timezone-aware (UTC)")
    effective_plan = plan if plan is not None else FanoutPlan()
    effective_registry = registry if registry is not None else default_registry()
    derived_run_id = fanout_run_id if fanout_run_id is not None else _derive_run_id(run_at)

    target_list: list[ChannelTarget] = [t for t in targets if t.active]
    targets_by_subscriber: dict[str, list[ChannelTarget]] = {}
    for target in target_list:
        targets_by_subscriber.setdefault(target.subscriber_id, []).append(target)
    for subscriber_id in targets_by_subscriber:
        targets_by_subscriber[subscriber_id].sort(key=lambda t: (t.channel, t.target_id))

    severity_order = effective_plan.severity_order
    event_list: list[NotificationEvent] = list(events)
    event_list.sort(key=lambda e: (severity_order.get(e.severity, 99), e.scheduled_at, e.event_id))

    scheduled: list[ScheduledDelivery] = []
    deferred: list[DeferredDelivery] = []
    per_channel_count: dict[str, int] = {
        "email": 0,
        "slack": 0,
        "webhook": 0,
        "in_app": 0,
    }

    for event in event_list:
        hh = horizon_hours(event.scheduled_at, run_at=run_at)
        if hh > float(effective_plan.sla_hours):
            deferred.append(
                DeferredDelivery(
                    event_id=event.event_id,
                    subscriber_id=event.subscriber_id,
                    channel=None,
                    reason="sla_overflow",
                )
            )
            continue
        matching_targets = targets_by_subscriber.get(event.subscriber_id, [])
        if not matching_targets:
            deferred.append(
                DeferredDelivery(
                    event_id=event.event_id,
                    subscriber_id=event.subscriber_id,
                    channel=None,
                    reason="no_target",
                )
            )
            continue
        for target in matching_targets:
            channel = target.channel
            if not effective_registry.has(channel):
                deferred.append(
                    DeferredDelivery(
                        event_id=event.event_id,
                        subscriber_id=event.subscriber_id,
                        channel=channel,
                        reason="adapter_unavailable",
                    )
                )
                continue
            cap = effective_plan.rate_caps.get(channel, 0)
            if per_channel_count[channel] >= cap:
                deferred.append(
                    DeferredDelivery(
                        event_id=event.event_id,
                        subscriber_id=event.subscriber_id,
                        channel=channel,
                        reason="rate_capped",
                    )
                )
                continue
            scheduled.append(
                ScheduledDelivery(
                    event_id=event.event_id,
                    subscriber_id=event.subscriber_id,
                    target_id=target.target_id,
                    channel=channel,
                    address=target.address,
                    subject=event.subject,
                    severity=event.severity,
                    scheduled_at=event.scheduled_at,
                )
            )
            per_channel_count[channel] = per_channel_count.get(channel, 0) + 1

    counts_channel, counts_reason = _aggregate(scheduled, deferred)

    return FanoutResult(
        fanout_run_id=derived_run_id,
        run_at=run_at.astimezone(UTC).isoformat(),
        plan=effective_plan,
        scheduled=tuple(scheduled),
        deferred=tuple(deferred),
        scheduled_count=len(scheduled),
        deferred_count=len(deferred),
        counts_by_channel=counts_channel,
        counts_by_defer_reason=counts_reason,
    )


__all__ = [
    "ChannelAdapter",
    "ChannelRegistry",
    "FakeChannelAdapter",
    "build_fanout_plan",
    "default_registry",
    "horizon_hours",
]
