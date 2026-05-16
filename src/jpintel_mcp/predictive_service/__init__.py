"""Wave 51 dim K — Predictive / proactive service registry.

This package implements the "push, not pull" predictive layer described
in ``feedback_predictive_service_design`` (Wave 43 origin, ratified for
Wave 51 dim K)::

    従来の MCP / REST は pull 型 (agent が叩いて初めて応答).
    状況変化を検出して関連顧客に push する predictive layer が必須.
    例: 「介護報酬改定 → 関連事業者 4,700 件に 24h 以内通知」
        「補助金公募開始 → 該当業種 + 該当規模の法人に通知」
        「行政処分 → 該当業界 watchlist に通知」

Three predictive axes (event types) supported:

* ``houjin_watch`` — 法人 amendment surface (M&A pillar).
* ``program_window`` — 補助金 / 制度 application window changes.
* ``amendment_diff`` — law / 通達 diff surface.

The registry persists events + subscriptions to two append-only JSONL
logs under ``logs/`` (same hygiene pattern as the dim N audit log).
:func:`due_events_for_subscriber` enforces the 24h notification KPI by
filtering ``scheduled_at <= now + 24h`` and intersecting against the
subscriber's ``watch_targets`` set.

Why this lives in its own package
---------------------------------
The package is **router-agnostic** so the same primitives serve:

* MCP tool surface (a future ``predictive_*`` family).
* REST surface (a future ``/v1/predictive/events`` router).
* ETL cron scripts (event detection emits via :func:`enqueue_event`).
* Offline operator scripts (digest preview, audit replay).
* Tests, without spinning up FastAPI or FastMCP.

Non-negotiable rules (from CLAUDE.md + the dim K design)
--------------------------------------------------------
* **No LLM imports.** No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk``. The CI guard
  ``tests/test_no_llm_in_production.py`` enforces this; never weaken it.
* **No live HTTP / no MCP / no webhook.** Delivery is a downstream
  concern; the registry only persists *what* should be delivered.
* **No DB ATTACH.** All persistence is JSONL — same rationale as the
  dim N audit log.
* **Append-only.** Events are never mutated post-write; truncation /
  tampering is detectable post-hoc.

Public surface
--------------
    Subscription              — Pydantic model for a watch-list row.
    PredictionEvent           — Pydantic model for a scheduled event.
    PredictionRegistry        — convenience facade over the JSONL store.
    enqueue_event(event)      — append one event to the log.
    register_subscription(s)  — append one subscription to the log.
    due_events_for_subscriber — query within 24h KPI window.
    subscribers_for_event     — reverse lookup, fan-out planning.
    read_events / read_subscriptions — operator-facing reads.
    DUE_WINDOW                — 24h ``timedelta`` constant.
    DEFAULT_EVENT_LOG_PATH    — ``logs/predictive_events.jsonl``.
    DEFAULT_SUBSCRIPTION_LOG_PATH — ``logs/predictive_subscriptions.jsonl``.
"""

from __future__ import annotations

from jpintel_mcp.predictive_service.models import (
    EventType,
    NotificationChannel,
    PredictionEvent,
    Subscription,
)
from jpintel_mcp.predictive_service.registry import (
    DEFAULT_EVENT_LOG_PATH,
    DEFAULT_SUBSCRIPTION_LOG_PATH,
    DUE_WINDOW,
    PredictionRegistry,
    due_events_for_subscriber,
    enqueue_event,
    read_events,
    read_subscriptions,
    register_subscription,
    subscribers_for_event,
)

__all__ = [
    "DEFAULT_EVENT_LOG_PATH",
    "DEFAULT_SUBSCRIPTION_LOG_PATH",
    "DUE_WINDOW",
    "EventType",
    "NotificationChannel",
    "PredictionEvent",
    "PredictionRegistry",
    "Subscription",
    "due_events_for_subscriber",
    "enqueue_event",
    "read_events",
    "read_subscriptions",
    "register_subscription",
    "subscribers_for_event",
]
