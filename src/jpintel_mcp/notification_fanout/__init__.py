"""Wave 51 L5 — notification_fanout (AX Layer 6 cron input).

Router-agnostic deterministic event-to-channel fanout planner.
NO LLM imports, NO live HTTP / SMTP / Slack, NO DB.
"""

from __future__ import annotations

from jpintel_mcp.notification_fanout.fanout import (
    ChannelAdapter,
    ChannelRegistry,
    FakeChannelAdapter,
    build_fanout_plan,
    default_registry,
    horizon_hours,
)
from jpintel_mcp.notification_fanout.models import (
    FANOUT_SCHEMA_VERSION,
    ChannelTarget,
    DeferReason,
    DeferredDelivery,
    DeliveryChannel,
    FanoutPlan,
    FanoutResult,
    NotificationEvent,
    ScheduledDelivery,
)

__all__ = [
    "FANOUT_SCHEMA_VERSION",
    "ChannelAdapter",
    "ChannelRegistry",
    "ChannelTarget",
    "DeferReason",
    "DeferredDelivery",
    "DeliveryChannel",
    "FakeChannelAdapter",
    "FanoutPlan",
    "FanoutResult",
    "NotificationEvent",
    "ScheduledDelivery",
    "build_fanout_plan",
    "default_registry",
    "horizon_hours",
]
