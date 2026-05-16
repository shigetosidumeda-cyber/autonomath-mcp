"""Append-only JSONL event registry for the Wave 51 dim K predictive service.

The registry is the canonical store for predictive events. It is
**append-only** (events are never mutated post-write) and **local-only**
(no HTTP / no DB ATTACH / no LLM inference). Two JSONL log files live
under ``logs/``:

* ``logs/predictive_events.jsonl`` — :class:`PredictionEvent` rows
* ``logs/predictive_subscriptions.jsonl`` — :class:`Subscription` rows

Why JSONL append-only
---------------------
Same rationale as the dim N audit log (see
``anonymized_query.audit_log``):

* Truncation / tampering detectable post-hoc (missing line N).
* Same-process atomic line write (POSIX <PIPE_BUF guarantee).
* No ATTACH risk against the 9.4 GB ``autonomath.db``.
* Stable path across Fly volume + GHA runner + dev shell.

The 24h notification KPI is enforced by
:func:`due_events_for_subscriber`, which filters
``scheduled_at <= now + 24h`` and intersects each event's
``target_id`` against the subscriber's ``watch_targets`` set. No live
delivery happens here — downstream cron / worker reads the registry
and dispatches via the subscriber's preferred channel.

Non-goals
---------
* **No live HTTP / no MCP / no webhook.** This module ships the
  *registry* only.
* **No LLM inference.** Event content is produced by upstream ETL.
* **No SQLite handles.** All persistence is JSONL under ``logs/``.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from jpintel_mcp.predictive_service.models import (
    PredictionEvent,
    Subscription,
)

#: Canonical default paths. Operator can override via the explicit
#: ``path=`` argument on every public function for per-test isolation.
DEFAULT_EVENT_LOG_PATH: Final[Path] = Path("logs") / "predictive_events.jsonl"
DEFAULT_SUBSCRIPTION_LOG_PATH: Final[Path] = (
    Path("logs") / "predictive_subscriptions.jsonl"
)

#: 24h KPI window from the dim K design — events with
#: ``scheduled_at <= now + DUE_WINDOW`` are returned by
#: :func:`due_events_for_subscriber`.
DUE_WINDOW: Final[timedelta] = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Time helpers — extracted so tests can pin the clock
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return wall-clock UTC. Override in tests via ``now=`` kwargs."""
    return datetime.now(tz=UTC)


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a UTC-aware ``datetime``.

    Accepts both ``...Z`` and ``...+00:00`` suffixes. Naive timestamps
    are rejected — predictive notifications are scheduled to the
    minute, so a naive 2 second window of timezone ambiguity is too
    much risk.
    """
    if not value:
        raise ValueError("ISO 8601 timestamp must be non-empty")
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"could not parse ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"ISO 8601 timestamp must be timezone-aware (got naive {value!r})"
        )
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------------------
# Append helpers — single-line atomic write, JSON-validated payload
# ---------------------------------------------------------------------------


def _ensure_json_serializable(payload: dict[str, object]) -> None:
    """Validate that ``payload`` is fully JSON-serializable.

    We could rely on ``json.dumps`` to raise at write time, but doing
    the check up front lets us reject the bad row before opening the
    log file — keeps the append-only log free of half-written lines if
    the encoder explodes mid-call.
    """
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"event payload must be JSON-serializable: {exc}"
        ) from exc


def _atomic_append_line(path: Path, line: str) -> None:
    """Append one newline-terminated line to ``path`` (parent dir auto-created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if not line.endswith("\n"):
            line = line + "\n"
        fh.write(line)
        fh.flush()
        with contextlib.suppress(OSError):
            os.fsync(fh.fileno())


# ---------------------------------------------------------------------------
# Public surface — pure functions over the JSONL registry
# ---------------------------------------------------------------------------


def enqueue_event(
    event: PredictionEvent,
    *,
    path: Path | str | None = None,
) -> PredictionEvent:
    """Append one :class:`PredictionEvent` to the event log.

    Pure function — returns the event exactly as persisted. Validates
    JSON-serializability of ``event.payload`` before opening the file so
    a corrupt row cannot land halfway.

    Parameters
    ----------
    event:
        The pre-validated :class:`PredictionEvent`. Construct via the
        Pydantic model so the watch-target shape contract is enforced
        before write.
    path:
        Optional override for :data:`DEFAULT_EVENT_LOG_PATH`. Tests
        should always pass an isolated ``tmp_path / "events.jsonl"``.

    Returns
    -------
    PredictionEvent
        The same event, byte-identical (frozen model is hashable).

    Raises
    ------
    ValueError
        If ``event.payload`` contains a non-JSON-serializable value.
    OSError
        If the log file cannot be opened for append.
    """
    _ensure_json_serializable(event.payload)
    line = event.model_dump_json()
    out_path = Path(path) if path is not None else DEFAULT_EVENT_LOG_PATH
    _atomic_append_line(out_path, line)
    return event


def register_subscription(
    subscription: Subscription,
    *,
    path: Path | str | None = None,
) -> Subscription:
    """Append one :class:`Subscription` to the subscription log.

    Symmetric to :func:`enqueue_event` for the *who-cares* side. The
    log is append-only — to *cancel* a subscription, append a new row
    via a downstream tombstone convention (out of scope for the
    registry's read API).
    """
    line = subscription.model_dump_json()
    out_path = (
        Path(path) if path is not None else DEFAULT_SUBSCRIPTION_LOG_PATH
    )
    _atomic_append_line(out_path, line)
    return subscription


def read_events(path: Path | str | None = None) -> list[PredictionEvent]:
    """Read all events back from the JSONL log.

    Skips blank lines and rejects malformed JSON / schema violations
    with a :class:`ValueError` carrying the offending line number — the
    caller usually wants to halt rather than silently drop a row that
    might be a regulatory amendment.
    """
    out_path = Path(path) if path is not None else DEFAULT_EVENT_LOG_PATH
    if not out_path.exists():
        return []
    rows: list[PredictionEvent] = []
    with out_path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rows.append(PredictionEvent.model_validate_json(stripped))
            except ValidationError as exc:
                raise ValueError(
                    f"malformed event row at {out_path}:{lineno}: {exc}"
                ) from exc
    return rows


def read_subscriptions(path: Path | str | None = None) -> list[Subscription]:
    """Read all subscriptions back from the JSONL log."""
    out_path = (
        Path(path) if path is not None else DEFAULT_SUBSCRIPTION_LOG_PATH
    )
    if not out_path.exists():
        return []
    rows: list[Subscription] = []
    with out_path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rows.append(Subscription.model_validate_json(stripped))
            except ValidationError as exc:
                raise ValueError(
                    f"malformed subscription row at {out_path}:{lineno}: {exc}"
                ) from exc
    return rows


def due_events_for_subscriber(
    subscriber_id: str,
    *,
    now: datetime | None = None,
    event_path: Path | str | None = None,
    subscription_path: Path | str | None = None,
) -> list[PredictionEvent]:
    """Return events due for ``subscriber_id`` within the 24h window.

    The filter is the intersection of:

    * ``event.target_id ∈ subscription.watch_targets``
    * ``event.scheduled_at <= now + 24h``

    where ``now`` defaults to wall-clock UTC. Tests should pin ``now``
    to a fixed timestamp to eliminate flakiness.

    Multiple subscription rows for the same ``subscriber_id`` are
    **unioned** — the latest row never "replaces" earlier ones because
    the log is append-only. Tombstoning is the consumer's contract.

    The returned list is sorted by ``scheduled_at`` ascending so the
    consumer can serve oldest-due first. Equal timestamps keep
    insertion order (Python's sort is stable).

    Parameters
    ----------
    subscriber_id:
        Opaque subscriber id. Must match :attr:`Subscription.subscriber_id`.
    now:
        Optional pinned wall-clock UTC for tests.
    event_path / subscription_path:
        Optional log overrides for per-test isolation.

    Returns
    -------
    list[PredictionEvent]
        Events ready to deliver. Empty list = nothing due (or subscriber
        not registered).
    """
    if not subscriber_id:
        raise ValueError("subscriber_id must be non-empty")
    current = now if now is not None else _utc_now()
    if current.tzinfo is None:
        raise ValueError("now= must be timezone-aware (UTC)")
    cutoff = current + DUE_WINDOW

    subs = [
        s
        for s in read_subscriptions(subscription_path)
        if s.subscriber_id == subscriber_id
    ]
    if not subs:
        return []

    watch_set: set[str] = set()
    for s in subs:
        watch_set.update(s.watch_targets)
    if not watch_set:
        return []

    out: list[PredictionEvent] = []
    for event in read_events(event_path):
        if event.target_id not in watch_set:
            continue
        scheduled = _parse_iso_utc(event.scheduled_at)
        if scheduled <= cutoff:
            out.append(event)
    out.sort(key=lambda e: _parse_iso_utc(e.scheduled_at))
    return out


def subscribers_for_event(
    event: PredictionEvent,
    *,
    subscription_path: Path | str | None = None,
) -> list[str]:
    """Reverse lookup — which subscribers match this event's target_id.

    Returns deduplicated subscriber ids in insertion order. Useful for
    fan-out planning: the caller decides how to schedule per-subscriber
    notifications without re-reading the entire subscription log.
    """
    subs = read_subscriptions(subscription_path)
    out: list[str] = []
    seen: set[str] = set()
    for s in subs:
        if event.target_id in s.watch_targets and s.subscriber_id not in seen:
            out.append(s.subscriber_id)
            seen.add(s.subscriber_id)
    return out


class PredictionRegistry:
    """Convenience facade — bundle event + subscription paths.

    Pure stateless wrapper around the module-level functions. Keeping
    the functional surface as the primary API (per ``feedback_*``
    pattern) lets callers ignore the class entirely; the class exists
    for callers who want one handle to inject into a downstream
    pipeline.
    """

    __slots__ = ("event_path", "subscription_path")

    def __init__(
        self,
        *,
        event_path: Path | str | None = None,
        subscription_path: Path | str | None = None,
    ) -> None:
        self.event_path = (
            Path(event_path) if event_path is not None else DEFAULT_EVENT_LOG_PATH
        )
        self.subscription_path = (
            Path(subscription_path)
            if subscription_path is not None
            else DEFAULT_SUBSCRIPTION_LOG_PATH
        )

    def enqueue(self, event: PredictionEvent) -> PredictionEvent:
        return enqueue_event(event, path=self.event_path)

    def subscribe(self, subscription: Subscription) -> Subscription:
        return register_subscription(
            subscription, path=self.subscription_path
        )

    def events(self) -> list[PredictionEvent]:
        return read_events(self.event_path)

    def subscriptions(self) -> list[Subscription]:
        return read_subscriptions(self.subscription_path)

    def due_for(
        self,
        subscriber_id: str,
        *,
        now: datetime | None = None,
    ) -> list[PredictionEvent]:
        return due_events_for_subscriber(
            subscriber_id,
            now=now,
            event_path=self.event_path,
            subscription_path=self.subscription_path,
        )

    def subscribers_for(self, event: PredictionEvent) -> list[str]:
        return subscribers_for_event(
            event, subscription_path=self.subscription_path
        )


def _module_self_check() -> dict[str, Any]:
    """Minimal in-memory self check — no side effects on disk.

    Useful for deploy-time sanity probes ("does the module import and
    construct correctly?") without writing to ``logs/``. Returns the
    constants the operator most often eye-balls.
    """
    return {
        "DEFAULT_EVENT_LOG_PATH": str(DEFAULT_EVENT_LOG_PATH),
        "DEFAULT_SUBSCRIPTION_LOG_PATH": str(DEFAULT_SUBSCRIPTION_LOG_PATH),
        "DUE_WINDOW_SECONDS": int(DUE_WINDOW.total_seconds()),
    }


__all__ = [
    "DEFAULT_EVENT_LOG_PATH",
    "DEFAULT_SUBSCRIPTION_LOG_PATH",
    "DUE_WINDOW",
    "PredictionRegistry",
    "due_events_for_subscriber",
    "enqueue_event",
    "read_events",
    "read_subscriptions",
    "register_subscription",
    "subscribers_for_event",
]
