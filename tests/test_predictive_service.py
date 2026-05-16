"""Wave 51 dim K — tests for the predictive_service router-agnostic module.

Covers the *registry-only* primitives under
``src/jpintel_mcp/predictive_service/``:

    * Subscription Pydantic model — watch_targets shape / dedup / channel
    * PredictionEvent Pydantic model — event_type enum / target_id shape
    * enqueue_event — append-only persistence + JSON payload validation
    * register_subscription — symmetric append for the watch side
    * due_events_for_subscriber — 24h window filter, dedup union
    * subscribers_for_event — reverse lookup fan-out
    * PredictionRegistry facade — same surface, bundled paths
    * No live HTTP / no LLM imports — checked structurally

Every persistence test uses ``tmp_path`` so we never touch the real
``logs/`` directory.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from jpintel_mcp.predictive_service import (
    DEFAULT_EVENT_LOG_PATH,
    DEFAULT_SUBSCRIPTION_LOG_PATH,
    DUE_WINDOW,
    PredictionEvent,
    PredictionRegistry,
    Subscription,
    due_events_for_subscriber,
    enqueue_event,
    read_events,
    read_subscriptions,
    register_subscription,
    subscribers_for_event,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_subscription(
    *,
    subscription_id: str = "sub_001",
    subscriber_id: str = "api_key_tenant_a",
    watch_targets: tuple[str, ...] = (
        "houjin:7000012050002",
        "program:it-donyu-2026",
    ),
    channel: str = "mcp_resource",
    created_at: str = "2026-05-16T00:00:00Z",
) -> Subscription:
    return Subscription(
        subscription_id=subscription_id,
        subscriber_id=subscriber_id,
        watch_targets=watch_targets,
        channel=channel,  # type: ignore[arg-type]
        created_at=created_at,
    )


def _valid_event(
    *,
    event_id: str = "evt_001",
    event_type: str = "program_window",
    target_id: str = "program:it-donyu-2026",
    scheduled_at: str = "2026-05-16T12:00:00Z",
    detected_at: str = "2026-05-16T10:00:00Z",
    payload: dict[str, object] | None = None,
) -> PredictionEvent:
    return PredictionEvent(
        event_id=event_id,
        event_type=event_type,  # type: ignore[arg-type]
        target_id=target_id,
        scheduled_at=scheduled_at,
        detected_at=detected_at,
        payload=payload if payload is not None else {"window": "2026-05-20"},
    )


# ---------------------------------------------------------------------------
# Subscription model — happy path + invariants
# ---------------------------------------------------------------------------


def test_subscription_happy_path_accepts_all_required_fields() -> None:
    sub = _valid_subscription()

    assert sub.subscription_id == "sub_001"
    assert sub.subscriber_id == "api_key_tenant_a"
    assert sub.watch_targets == (
        "houjin:7000012050002",
        "program:it-donyu-2026",
    )
    assert sub.channel == "mcp_resource"
    assert sub.created_at == "2026-05-16T00:00:00Z"


def test_subscription_is_frozen_and_forbids_extra_fields() -> None:
    sub = _valid_subscription()

    # extra='forbid' — unknown field rejected on construction.
    with pytest.raises(ValidationError):
        Subscription(  # type: ignore[call-arg]
            subscription_id="sub_x",
            subscriber_id="x",
            watch_targets=("program:abc",),
            channel="mcp_resource",
            created_at="2026-05-16T00:00:00Z",
            unknown_field="boom",
        )

    # frozen=True — assignment after construction rejected.
    with pytest.raises(ValidationError):
        sub.channel = "webhook"  # type: ignore[misc]


def test_subscription_rejects_empty_watch_targets() -> None:
    with pytest.raises(ValidationError):
        Subscription(
            subscription_id="sub_empty",
            subscriber_id="x",
            watch_targets=(),
            channel="mcp_resource",
            created_at="2026-05-16T00:00:00Z",
        )


def test_subscription_dedups_watch_targets() -> None:
    sub = _valid_subscription(
        watch_targets=(
            "program:abc",
            "program:abc",
            "houjin:7000012050002",
        )
    )
    assert sub.watch_targets == ("program:abc", "houjin:7000012050002")


def test_subscription_rejects_string_for_watch_targets() -> None:
    with pytest.raises(ValidationError):
        Subscription(
            subscription_id="sub_x",
            subscriber_id="x",
            watch_targets="program:abc",  # type: ignore[arg-type]
            channel="mcp_resource",
            created_at="2026-05-16T00:00:00Z",
        )


@pytest.mark.parametrize(
    "bad_watch_target",
    [
        "7000012050002",  # raw houjin without prefix
        "houjin:12345",  # too few digits
        "houjin:12345678901234",  # too many digits
        "Program:abc",  # capitalized namespace
        "program:ABC",  # uppercase slug
        "program: spaces",  # space in slug
        "random:thing",  # unknown namespace
        "",
    ],
)
def test_subscription_rejects_malformed_watch_target(
    bad_watch_target: str,
) -> None:
    with pytest.raises(ValidationError):
        Subscription(
            subscription_id="sub_x",
            subscriber_id="x",
            watch_targets=(bad_watch_target,),
            channel="mcp_resource",
            created_at="2026-05-16T00:00:00Z",
        )


@pytest.mark.parametrize(
    "good_watch_target",
    [
        "houjin:7000012050002",
        "program:it-donyu-2026",
        "program:smb_grant_v2",
        "amendment:law-r07-038",
        "amendment:tax-rule-2026-04",
    ],
)
def test_subscription_accepts_canonical_watch_target_shapes(
    good_watch_target: str,
) -> None:
    sub = Subscription(
        subscription_id="sub_x",
        subscriber_id="x",
        watch_targets=(good_watch_target,),
        channel="mcp_resource",
        created_at="2026-05-16T00:00:00Z",
    )
    assert sub.watch_targets == (good_watch_target,)


@pytest.mark.parametrize(
    "channel",
    ["webhook", "mcp_resource", "email_digest"],
)
def test_subscription_accepts_three_canonical_channels(channel: str) -> None:
    sub = _valid_subscription(channel=channel)
    assert sub.channel == channel


def test_subscription_rejects_unknown_channel() -> None:
    with pytest.raises(ValidationError):
        Subscription(
            subscription_id="sub_x",
            subscriber_id="x",
            watch_targets=("program:abc",),
            channel="sms",  # type: ignore[arg-type]
            created_at="2026-05-16T00:00:00Z",
        )


# ---------------------------------------------------------------------------
# PredictionEvent model — happy path + invariants
# ---------------------------------------------------------------------------


def test_prediction_event_happy_path_accepts_all_required_fields() -> None:
    event = _valid_event()

    assert event.event_id == "evt_001"
    assert event.event_type == "program_window"
    assert event.target_id == "program:it-donyu-2026"
    assert event.scheduled_at == "2026-05-16T12:00:00Z"
    assert event.detected_at == "2026-05-16T10:00:00Z"
    assert event.payload == {"window": "2026-05-20"}


@pytest.mark.parametrize(
    "good_event_type",
    ["houjin_watch", "program_window", "amendment_diff"],
)
def test_prediction_event_accepts_three_canonical_event_types(
    good_event_type: str,
) -> None:
    event = _valid_event(event_type=good_event_type)
    assert event.event_type == good_event_type


def test_prediction_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        PredictionEvent(
            event_id="evt_x",
            event_type="ipo_signal",  # type: ignore[arg-type]
            target_id="program:abc",
            scheduled_at="2026-05-16T00:00:00Z",
            detected_at="2026-05-16T00:00:00Z",
            payload={},
        )


def test_prediction_event_rejects_malformed_target_id() -> None:
    with pytest.raises(ValidationError):
        PredictionEvent(
            event_id="evt_x",
            event_type="program_window",
            target_id="random:thing",
            scheduled_at="2026-05-16T00:00:00Z",
            detected_at="2026-05-16T00:00:00Z",
            payload={},
        )


def test_prediction_event_is_frozen_and_forbids_extra_fields() -> None:
    event = _valid_event()

    with pytest.raises(ValidationError):
        event.event_id = "evt_modified"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        PredictionEvent(  # type: ignore[call-arg]
            event_id="evt_x",
            event_type="program_window",
            target_id="program:abc",
            scheduled_at="2026-05-16T00:00:00Z",
            detected_at="2026-05-16T00:00:00Z",
            payload={},
            unknown_field=1,
        )


# ---------------------------------------------------------------------------
# enqueue_event / register_subscription — append-only persistence
# ---------------------------------------------------------------------------


def test_enqueue_event_writes_jsonl_line(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "events.jsonl"
    event = _valid_event()

    returned = enqueue_event(event, path=log)
    assert returned == event

    raw_lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert len(raw_lines) == 1
    parsed = json.loads(raw_lines[0])
    assert parsed["event_id"] == "evt_001"
    assert parsed["event_type"] == "program_window"
    assert parsed["target_id"] == "program:it-donyu-2026"


def test_enqueue_event_is_append_only(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "events.jsonl"

    enqueue_event(_valid_event(event_id="evt_a"), path=log)
    enqueue_event(_valid_event(event_id="evt_b"), path=log)
    enqueue_event(_valid_event(event_id="evt_c"), path=log)

    events = read_events(log)
    assert [e.event_id for e in events] == ["evt_a", "evt_b", "evt_c"]


def test_enqueue_event_rejects_non_json_payload(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "events.jsonl"

    # set() is not JSON-serializable
    bad_event = PredictionEvent.model_construct(
        event_id="evt_bad",
        event_type="amendment_diff",
        target_id="amendment:foo",
        scheduled_at="2026-05-16T00:00:00Z",
        detected_at="2026-05-16T00:00:00Z",
        payload={"diff_ids": {1, 2, 3}},  # type: ignore[dict-item]
    )

    with pytest.raises(ValueError, match="JSON-serializable"):
        enqueue_event(bad_event, path=log)

    # File must not have been touched — append-only contract.
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_register_subscription_writes_jsonl_line(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "subs.jsonl"
    sub = _valid_subscription()

    register_subscription(sub, path=log)

    raw = log.read_text(encoding="utf-8").splitlines()
    parsed = json.loads(raw[0])
    assert parsed["subscriber_id"] == "api_key_tenant_a"
    assert "houjin:7000012050002" in parsed["watch_targets"]


def test_read_events_returns_empty_when_log_missing(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "nonexistent.jsonl"
    assert read_events(log) == []


def test_read_subscriptions_returns_empty_when_log_missing(
    tmp_path: pathlib.Path,
) -> None:
    log = tmp_path / "nonexistent.jsonl"
    assert read_subscriptions(log) == []


def test_read_events_skips_blank_lines(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "events.jsonl"
    enqueue_event(_valid_event(event_id="evt_1"), path=log)

    # Manually append a blank line — registry must tolerate it.
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n   \n")

    enqueue_event(_valid_event(event_id="evt_2"), path=log)

    events = read_events(log)
    assert [e.event_id for e in events] == ["evt_1", "evt_2"]


def test_read_events_raises_on_malformed_row(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "events.jsonl"
    enqueue_event(_valid_event(event_id="evt_1"), path=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"event_id": "evt_bad", "event_type": "not_in_enum"}\n')

    with pytest.raises(ValueError, match="malformed event row"):
        read_events(log)


# ---------------------------------------------------------------------------
# due_events_for_subscriber — 24h KPI window
# ---------------------------------------------------------------------------


def test_due_events_for_subscriber_returns_within_24h_window(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    register_subscription(
        _valid_subscription(
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )
    enqueue_event(
        _valid_event(
            event_id="evt_in_window",
            target_id="program:abc",
            scheduled_at="2026-05-16T05:00:00Z",
        ),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "api_key_tenant_a",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert [e.event_id for e in due] == ["evt_in_window"]


def test_due_events_for_subscriber_excludes_beyond_24h(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    register_subscription(
        _valid_subscription(watch_targets=("program:abc",)),
        path=sub_log,
    )
    # 24h + 1 minute in the future — must be excluded.
    enqueue_event(
        _valid_event(
            event_id="evt_future",
            target_id="program:abc",
            scheduled_at="2026-05-17T00:01:00Z",
        ),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "api_key_tenant_a",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert due == []


def test_due_events_for_subscriber_excludes_non_matching_target(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    register_subscription(
        _valid_subscription(watch_targets=("program:abc",)),
        path=sub_log,
    )
    enqueue_event(
        _valid_event(
            event_id="evt_other",
            target_id="program:xyz",
            scheduled_at="2026-05-16T05:00:00Z",
        ),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "api_key_tenant_a",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert due == []


def test_due_events_for_subscriber_unions_multiple_subscription_rows(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    # Two append-only subscription rows for the same subscriber, each
    # contributing a different watch target. Their union should fire.
    register_subscription(
        _valid_subscription(
            subscription_id="sub_a",
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )
    register_subscription(
        _valid_subscription(
            subscription_id="sub_b",
            watch_targets=("houjin:7000012050002",),
        ),
        path=sub_log,
    )

    enqueue_event(
        _valid_event(
            event_id="evt_program",
            target_id="program:abc",
            scheduled_at="2026-05-16T05:00:00Z",
        ),
        path=evt_log,
    )
    enqueue_event(
        _valid_event(
            event_id="evt_houjin",
            event_type="houjin_watch",
            target_id="houjin:7000012050002",
            scheduled_at="2026-05-16T06:00:00Z",
        ),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "api_key_tenant_a",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert sorted(e.event_id for e in due) == ["evt_houjin", "evt_program"]


def test_due_events_for_subscriber_sorted_ascending_by_scheduled_at(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    register_subscription(
        _valid_subscription(watch_targets=("program:abc",)),
        path=sub_log,
    )

    # Enqueue out of order.
    enqueue_event(
        _valid_event(
            event_id="evt_late",
            target_id="program:abc",
            scheduled_at="2026-05-16T20:00:00Z",
        ),
        path=evt_log,
    )
    enqueue_event(
        _valid_event(
            event_id="evt_early",
            target_id="program:abc",
            scheduled_at="2026-05-16T01:00:00Z",
        ),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "api_key_tenant_a",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert [e.event_id for e in due] == ["evt_early", "evt_late"]


def test_due_events_for_subscriber_returns_empty_for_unregistered_subscriber(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"
    evt_log = tmp_path / "events.jsonl"

    register_subscription(
        _valid_subscription(watch_targets=("program:abc",)),
        path=sub_log,
    )
    enqueue_event(
        _valid_event(target_id="program:abc"),
        path=evt_log,
    )

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = due_events_for_subscriber(
        "unknown_subscriber",
        now=now,
        event_path=evt_log,
        subscription_path=sub_log,
    )
    assert due == []


def test_due_events_for_subscriber_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        due_events_for_subscriber(
            "x",
            now=datetime(2026, 5, 16, 0, 0, 0),  # naive
        )


def test_due_events_for_subscriber_rejects_empty_subscriber_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        due_events_for_subscriber("")


# ---------------------------------------------------------------------------
# subscribers_for_event — reverse lookup fan-out
# ---------------------------------------------------------------------------


def test_subscribers_for_event_returns_matching_ids(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"

    register_subscription(
        _valid_subscription(
            subscription_id="sub_a",
            subscriber_id="tenant_a",
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )
    register_subscription(
        _valid_subscription(
            subscription_id="sub_b",
            subscriber_id="tenant_b",
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )
    register_subscription(
        _valid_subscription(
            subscription_id="sub_c",
            subscriber_id="tenant_c",
            watch_targets=("program:xyz",),
        ),
        path=sub_log,
    )

    event = _valid_event(target_id="program:abc")
    subs = subscribers_for_event(event, subscription_path=sub_log)
    assert subs == ["tenant_a", "tenant_b"]


def test_subscribers_for_event_dedups_repeat_subscriber_rows(
    tmp_path: pathlib.Path,
) -> None:
    sub_log = tmp_path / "subs.jsonl"

    register_subscription(
        _valid_subscription(
            subscription_id="sub_a",
            subscriber_id="tenant_dup",
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )
    register_subscription(
        _valid_subscription(
            subscription_id="sub_b",
            subscriber_id="tenant_dup",
            watch_targets=("program:abc",),
        ),
        path=sub_log,
    )

    event = _valid_event(target_id="program:abc")
    subs = subscribers_for_event(event, subscription_path=sub_log)
    assert subs == ["tenant_dup"]


# ---------------------------------------------------------------------------
# PredictionRegistry facade
# ---------------------------------------------------------------------------


def test_prediction_registry_facade_roundtrip(tmp_path: pathlib.Path) -> None:
    registry = PredictionRegistry(
        event_path=tmp_path / "events.jsonl",
        subscription_path=tmp_path / "subs.jsonl",
    )

    sub = _valid_subscription(watch_targets=("program:abc",))
    event = _valid_event(target_id="program:abc")

    registry.subscribe(sub)
    registry.enqueue(event)

    now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
    due = registry.due_for("api_key_tenant_a", now=now)
    assert [e.event_id for e in due] == ["evt_001"]

    fanout = registry.subscribers_for(event)
    assert fanout == ["api_key_tenant_a"]

    assert len(registry.events()) == 1
    assert len(registry.subscriptions()) == 1


def test_prediction_registry_uses_default_paths_when_none_provided() -> None:
    registry = PredictionRegistry()
    assert registry.event_path == DEFAULT_EVENT_LOG_PATH
    assert registry.subscription_path == DEFAULT_SUBSCRIPTION_LOG_PATH


# ---------------------------------------------------------------------------
# Constants + module hygiene
# ---------------------------------------------------------------------------


def test_due_window_is_24h() -> None:
    # Constant under test reads naturally as the LHS; SIM300 Yoda is noisier here.
    assert DUE_WINDOW == timedelta(hours=24)  # noqa: SIM300


def test_default_paths_point_at_logs_directory() -> None:
    assert DEFAULT_EVENT_LOG_PATH.parent.name == "logs"
    assert DEFAULT_SUBSCRIPTION_LOG_PATH.parent.name == "logs"
    assert DEFAULT_EVENT_LOG_PATH.name == "predictive_events.jsonl"
    assert (
        DEFAULT_SUBSCRIPTION_LOG_PATH.name == "predictive_subscriptions.jsonl"
    )


def test_module_imports_no_llm_or_http_client() -> None:
    """Structural CI guard: predictive_service must not pull LLM / HTTP libs.

    Mirrors the project-wide CI guard in
    ``tests/test_no_llm_in_production.py`` but scoped to the dim K
    package so a regression here is caught before the project-wide
    scan runs.
    """
    package_root = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "jpintel_mcp"
        / "predictive_service"
    )
    banned = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
        "import httpx",
        "from httpx",
        "import requests",
        "from requests",
        "import aiohttp",
        "from aiohttp",
    )
    for py in package_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text, (
                f"{py.relative_to(package_root)} must not contain {needle!r}"
            )
