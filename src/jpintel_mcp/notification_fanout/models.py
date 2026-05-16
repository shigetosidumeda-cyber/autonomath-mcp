"""Pydantic models for the Wave 51 L5 notification_fanout layer.

Four canonical envelopes for the deterministic event-to-channel fanout
planner. Strict-by-default (extra='forbid' + frozen=True). NO LLM
imports, NO live HTTP / SMTP / Slack imports, NO DB.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FANOUT_SCHEMA_VERSION: Literal["jpcite.notification_fanout.v1"] = "jpcite.notification_fanout.v1"

DeliveryChannel = Literal["email", "slack", "webhook", "in_app"]
DeferReason = Literal["rate_capped", "sla_overflow", "no_target", "adapter_unavailable"]

_RUN_ID_RE: re.Pattern[str] = re.compile(r"^fanout@\d{4}_(0[1-9]|1[0-2])_([0-2]\d|3[01])$")
_EMAIL_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_SLACK_WEBHOOK_RE: re.Pattern[str] = re.compile(r"^https://hooks\.slack\.com/services/[A-Z0-9/]+$")
_HTTPS_RE: re.Pattern[str] = re.compile(
    r"^https://[a-zA-Z0-9.\-]+(?:/[A-Za-z0-9._~:/?#@!$&'()*+,;=\-]*)?$"
)
_IN_APP_TOKEN_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")


class _StrictModel(BaseModel):
    """Forbid extra fields and freeze attribute mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NotificationEvent(_StrictModel):
    """One source event we want to deliver to one or more subscribers."""

    event_id: str = Field(min_length=1, max_length=128)
    subscriber_id: str = Field(min_length=1, max_length=128)
    scheduled_at: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4096)
    severity: Literal["info", "warning", "critical"] = Field(default="info")
    payload: dict[str, object] = Field(default_factory=dict)


class ChannelTarget(_StrictModel):
    """*Which* channel + *which* address should receive *which* events."""

    target_id: str = Field(min_length=1, max_length=128)
    subscriber_id: str = Field(min_length=1, max_length=128)
    channel: DeliveryChannel
    address: str = Field(min_length=1, max_length=512)
    active: bool = Field(default=True)

    @model_validator(mode="after")
    def _validate_address_shape(self) -> ChannelTarget:
        """Enforce per-channel address shape contract."""
        if self.channel == "email":
            if not _EMAIL_RE.match(self.address):
                raise ValueError(f"channel='email' requires RFC 5322 address; got {self.address!r}")
        elif self.channel == "slack":
            if not _SLACK_WEBHOOK_RE.match(self.address):
                raise ValueError(
                    "channel='slack' requires https://hooks.slack.com/services/... URL"
                )
        elif self.channel == "webhook":
            if not _HTTPS_RE.match(self.address):
                raise ValueError(
                    "channel='webhook' requires https:// URL (plaintext HTTP rejected)"
                )
        elif self.channel == "in_app" and not _IN_APP_TOKEN_RE.match(self.address):
            raise ValueError("channel='in_app' requires 32-hex-char session token")
        return self


class FanoutPlan(_StrictModel):
    """Declarative knob bundle for one fanout run."""

    sla_hours: int = Field(ge=1, le=168, default=24)
    rate_caps: dict[str, int] = Field(
        default_factory=lambda: {
            "email": 1000,
            "slack": 500,
            "webhook": 1000,
            "in_app": 5000,
        },
    )
    severity_order: dict[str, int] = Field(
        default_factory=lambda: {"critical": 0, "warning": 1, "info": 2},
    )

    @field_validator("rate_caps")
    @classmethod
    def _validate_rate_cap_keys(cls, value: dict[str, int]) -> dict[str, int]:
        allowed: set[str] = {"email", "slack", "webhook", "in_app"}
        bad_keys = set(value) - allowed
        if bad_keys:
            raise ValueError(
                f"rate_caps contains unknown channels: {sorted(bad_keys)}; "
                f"allowed={sorted(allowed)}"
            )
        for ch, cap in value.items():
            if cap < 0 or cap > 1_000_000:
                raise ValueError(f"rate_caps[{ch!r}]={cap} must be in [0, 1_000_000]")
        return value

    @field_validator("severity_order")
    @classmethod
    def _validate_severity_keys(cls, value: dict[str, int]) -> dict[str, int]:
        allowed: set[str] = {"info", "warning", "critical"}
        bad_keys = set(value) - allowed
        if bad_keys:
            raise ValueError(
                f"severity_order contains unknown severities: {sorted(bad_keys)}; "
                f"allowed={sorted(allowed)}"
            )
        return value


class ScheduledDelivery(_StrictModel):
    """One concrete delivery slot scheduled in the fanout artifact."""

    event_id: str = Field(min_length=1)
    subscriber_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    channel: DeliveryChannel
    address: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    severity: Literal["info", "warning", "critical"]
    scheduled_at: str = Field(min_length=1)


class DeferredDelivery(_StrictModel):
    """One event that the planner intentionally deferred or dropped."""

    event_id: str = Field(min_length=1)
    subscriber_id: str = Field(min_length=1)
    channel: DeliveryChannel | None = Field(default=None)
    reason: DeferReason


class FanoutResult(_StrictModel):
    """Full snapshot of one fanout run."""

    schema_version: Literal["jpcite.notification_fanout.v1"] = FANOUT_SCHEMA_VERSION
    fanout_run_id: str = Field(min_length=1)
    run_at: str = Field(min_length=1)
    plan: FanoutPlan
    scheduled: tuple[ScheduledDelivery, ...]
    deferred: tuple[DeferredDelivery, ...]
    scheduled_count: int = Field(ge=0)
    deferred_count: int = Field(ge=0)
    counts_by_channel: dict[str, int]
    counts_by_defer_reason: dict[str, int]

    @field_validator("fanout_run_id")
    @classmethod
    def _validate_run_id_shape(cls, value: str) -> str:
        if not _RUN_ID_RE.fullmatch(value):
            raise ValueError(
                f"fanout_run_id must match 'fanout@<yyyy_mm_dd>' "
                f"(e.g. 'fanout@2026_05_17'); got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _counts_match(self) -> FanoutResult:
        if self.scheduled_count != len(self.scheduled):
            raise ValueError("scheduled_count must equal len(scheduled)")
        if self.deferred_count != len(self.deferred):
            raise ValueError("deferred_count must equal len(deferred)")
        if sum(self.counts_by_channel.values()) != self.scheduled_count:
            raise ValueError("sum(counts_by_channel) must equal scheduled_count")
        if sum(self.counts_by_defer_reason.values()) != self.deferred_count:
            raise ValueError("sum(counts_by_defer_reason) must equal deferred_count")
        allowed_channels: set[str] = {"email", "slack", "webhook", "in_app"}
        bad_channels = set(self.counts_by_channel) - allowed_channels
        if bad_channels:
            raise ValueError(f"counts_by_channel has unknown keys: {sorted(bad_channels)}")
        allowed_reasons: set[str] = {
            "rate_capped",
            "sla_overflow",
            "no_target",
            "adapter_unavailable",
        }
        bad_reasons = set(self.counts_by_defer_reason) - allowed_reasons
        if bad_reasons:
            raise ValueError(f"counts_by_defer_reason has unknown keys: {sorted(bad_reasons)}")
        return self


__all__ = [
    "FANOUT_SCHEMA_VERSION",
    "ChannelTarget",
    "DeferReason",
    "DeferredDelivery",
    "DeliveryChannel",
    "FanoutPlan",
    "FanoutResult",
    "NotificationEvent",
    "ScheduledDelivery",
]
