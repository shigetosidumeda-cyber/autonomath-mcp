"""Pydantic models for the Wave 51 dim K predictive service.

Two canonical envelopes:

* :class:`Subscription` — *which* customer wants to be notified about
  *which* watch targets (法人 / 制度 / amendment-diff topic).
* :class:`PredictionEvent` — *what* situation change has been detected
  and *when* the subscriber should see it.

Both models follow the same strict-by-default contract used elsewhere in
``agent_runtime.contracts`` (``extra='forbid'`` + ``frozen=True``) so a
typo in a registry payload fails loudly at the boundary rather than
silently corrupting the event store. The models live in their own
package so they can be imported from REST handlers, MCP tools, ETL cron
scripts, and offline operator scripts without dragging FastAPI / SQLite
handles or any LLM-API surface.

Non-goals
---------
* **No live HTTP.** This module never imports ``httpx`` / ``requests``
  / ``aiohttp``. Notification *delivery* is a downstream concern; the
  registry only persists what *should* be delivered.
* **No LLM inference.** No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk`` import. Event detection
  is rule-based and lives outside this package.
* **No DB.** Backing store is an append-only JSONL log under ``logs/``
  for the same reason the dim N audit log uses JSONL — Fly volume + GHA
  runner + dev shell all share a stable path with zero ATTACH risk.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Allowed event-type enum. Mirrors the three predictive axes documented
#: in ``feedback_predictive_service_design`` (Wave 43 → Wave 51 dim K):
#:
#: * ``houjin_watch`` — 法人 (corporate) record amendment surfaced via
#:   `houjin_watch` change-detection (M&A pillar).
#: * ``program_window`` — 補助金 / 制度 application window opening,
#:   closing, or renewing.
#: * ``amendment_diff`` — law / 通達 amendment diff surfaced via
#:   `am_amendment_diff` ETL.
EventType = Literal[
    "houjin_watch",
    "program_window",
    "amendment_diff",
]

#: Allowed delivery channels. The registry only records the *preferred*
#: channel; actual delivery is a downstream cron / worker concern.
NotificationChannel = Literal[
    "webhook",
    "mcp_resource",
    "email_digest",
]

# ---------------------------------------------------------------------------
# Watch-target id format
# ---------------------------------------------------------------------------

#: Stable shape for watch-target ids. Matches:
#:
#: * ``houjin:`` + 13 digit 法人番号 (NTA standard, 例: ``houjin:7000012050002``)
#: * ``program:`` + slug ``[a-z0-9_-]+``
#: * ``amendment:`` + slug ``[a-z0-9_-]+``
#:
#: The validator is strict so an ETL row that mistakenly passes a raw
#: 法人番号 (``"7000012050002"``) tripps the model before it can land in
#: the append-only registry.
_WATCH_TARGET_RE: re.Pattern[str] = re.compile(
    r"^(?:houjin:\d{13}|program:[a-z0-9_\-]+|amendment:[a-z0-9_\-]+)$"
)


def _validate_watch_target(value: str) -> str:
    """Reject malformed watch-target ids before they hit the registry."""
    if not _WATCH_TARGET_RE.match(value):
        raise ValueError(
            "watch_target must match houjin:<13 digit> | "
            f"program:<slug> | amendment:<slug>; got {value!r}"
        )
    return value


class Subscription(BaseModel):
    """A subscriber + the set of watch targets they care about.

    ``subscriber_id`` is intentionally opaque (any non-empty string) so
    the registry can serve API-key holders, MCP agents, and internal
    operator dashboards without coupling to a specific identity layer.
    The ``watch_targets`` tuple is **non-empty** and **deduplicated** —
    duplicates would inflate per-subscriber match counts and erode the
    "24h max notification latency" KPI from the dim K design.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    subscription_id: str = Field(
        min_length=1,
        description=(
            "Globally unique subscription id (operator chooses the "
            "namespace; jpcite generates ``sub_<uuid7>`` by convention "
            "but the model only enforces non-empty)."
        ),
    )
    subscriber_id: str = Field(
        min_length=1,
        description=(
            "Opaque subscriber identifier — API key id, MCP client id, "
            "or operator user id. Never a raw 法人番号 (those go in "
            "``watch_targets`` under the ``houjin:`` namespace)."
        ),
    )
    watch_targets: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Set of watch target ids. Each must match "
            "``houjin:<13 digit>`` | ``program:<slug>`` | "
            "``amendment:<slug>``. Deduplicated automatically."
        ),
    )
    channel: NotificationChannel = Field(
        default="mcp_resource",
        description=(
            "Preferred notification channel. Registry only records the "
            "preference; downstream delivery layer routes accordingly."
        ),
    )
    created_at: str = Field(
        min_length=1,
        description=(
            "ISO 8601 UTC timestamp of subscription creation. Required "
            "(not auto-filled) so the caller controls the canonical "
            "clock source — eliminates wall-clock skew between API and "
            "registry."
        ),
    )

    @field_validator("watch_targets", mode="before")
    @classmethod
    def _normalize_watch_targets(cls, value: object) -> tuple[str, ...]:
        # Raise ``ValueError`` (not ``TypeError``) so Pydantic surfaces the
        # failure as a ``ValidationError`` rather than letting the bare
        # exception escape the constructor.
        if isinstance(value, str):
            raise ValueError(
                "watch_targets must be a sequence of strings, not a single str"
            )
        if not isinstance(value, list | tuple):
            raise ValueError("watch_targets must be a list or tuple")
        seen: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("watch_targets entries must be strings")
            _validate_watch_target(item)
            if item not in seen:
                seen.append(item)
        if not seen:
            raise ValueError("watch_targets must be non-empty after dedup")
        return tuple(seen)


class PredictionEvent(BaseModel):
    """A detected change scheduled for delivery to matching subscribers.

    Events are append-only — once written to the registry they are
    never mutated. The ``payload`` dict is intentionally untyped (``str
    -> object``) so the same event store can carry domain-specific
    fields (e.g. ``{"diff_id": "...", "law_id": "..."}``) without
    proliferating one Pydantic model per detector. The contract is:
    ``payload`` MUST be JSON-serializable; the registry validates via
    ``json.dumps`` on write.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(
        min_length=1,
        description=(
            "Globally unique event id. Operator chooses the namespace; "
            "convention is ``evt_<uuid7>``."
        ),
    )
    event_type: EventType = Field(
        description=(
            "One of houjin_watch / program_window / amendment_diff "
            "(dim K design)."
        ),
    )
    target_id: str = Field(
        min_length=1,
        description=(
            "Watch-target id this event pertains to. Must match the "
            "same shape as ``Subscription.watch_targets`` entries so "
            "subscriber matching is a set-membership test, not a "
            "fuzzy join."
        ),
    )
    scheduled_at: str = Field(
        min_length=1,
        description=(
            "ISO 8601 UTC timestamp at which subscribers should see "
            "the event. The 24h KPI is enforced by "
            ":func:`due_events_for_subscriber` which filters "
            "``scheduled_at <= now + 24h``."
        ),
    )
    detected_at: str = Field(
        min_length=1,
        description=(
            "ISO 8601 UTC timestamp when the ETL / detector observed "
            "the change. Distinct from ``scheduled_at`` so the operator "
            "can backdate scheduled notifications (e.g. roll out a "
            "regulatory amendment within business hours)."
        ),
    )
    payload: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Free-form JSON-serializable payload. The registry "
            "validates JSON-serializability on write; the model does "
            "not enforce field shape so new detectors can ship without "
            "schema migrations."
        ),
    )

    @field_validator("target_id")
    @classmethod
    def _validate_target_id_shape(cls, value: str) -> str:
        return _validate_watch_target(value)


__all__ = [
    "EventType",
    "NotificationChannel",
    "PredictionEvent",
    "Subscription",
]
