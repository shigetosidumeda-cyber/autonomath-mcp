"""Tests for loop_i_doc_freshness.

Covers the launch-v1 happy path: a synthesized in-memory program list
plus a mocked HTTP client feeds the loop, which classifies stale + broken
rows, writes a report, and proposes (without sending) an operator alert
for tier S/A broken sources.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

import pytest

from jpintel_mcp.self_improve import loop_i_doc_freshness as loop_i

if TYPE_CHECKING:
    from pathlib import Path


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Minimal async HTTP stub returning canned status codes per URL."""

    def __init__(self, status_by_url: dict[str, int]) -> None:
        self._status = status_by_url
        self.head_calls: list[str] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def head(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.head_calls.append(url)
        return _FakeResponse(self._status.get(url, 200))

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:  # pragma: no cover
        return _FakeResponse(self._status.get(url, 200))


def _fake_rows() -> list[dict[str, Any]]:
    """Synthetic programs slice covering all four classification buckets.

    Buckets:
        fresh        -> recent fetch + 200 status      (1 row)
        stale-only   -> fetch >60d ago, no probe       (2 rows)
        known-broken -> source_last_check_status=404   (1 row, tier S)
        probe-broken -> no status, HEAD returns 503    (1 row, tier A)
    """
    now = dt.datetime.now(dt.UTC)
    fresh = (now - dt.timedelta(days=3)).isoformat(timespec="seconds")
    stale = (now - dt.timedelta(days=120)).isoformat(timespec="seconds")
    return [
        {
            "unified_id": "fresh-1",
            "tier": "S",
            "source_url": "https://example.gov/fresh",
            "source_fetched_at": fresh,
            "source_last_check_status": 200,
        },
        {
            "unified_id": "stale-1",
            "tier": "B",
            "source_url": "https://example.gov/stale-1",
            "source_fetched_at": stale,
            "source_last_check_status": 200,
        },
        {
            "unified_id": "stale-2",
            "tier": "C",
            "source_url": "https://example.gov/stale-2",
            "source_fetched_at": None,
            "source_last_check_status": None,
        },
        {
            "unified_id": "broken-known-S",
            "tier": "S",
            "source_url": "https://example.gov/broken-known",
            "source_fetched_at": fresh,
            "source_last_check_status": 404,
        },
        {
            "unified_id": "broken-probe-A",
            "tier": "A",
            "source_url": "https://example.gov/broken-probe",
            "source_fetched_at": fresh,
            "source_last_check_status": None,
        },
    ]


def test_loop_i_classifies_stale_and_broken(tmp_path: Path) -> None:
    rows = _fake_rows()
    report_path = tmp_path / "source_freshness_report.json"

    fake_client = _FakeAsyncClient({"https://example.gov/broken-probe": 503})

    def factory() -> _FakeAsyncClient:
        return fake_client

    # dry_run=True -> no email send. probe=True -> HEAD the no-status row.
    result = loop_i.run(
        dry_run=True,
        rows=rows,
        report_path=report_path,
        probe=True,
        client_factory=factory,
    )

    assert result["loop"] == "loop_i_doc_freshness"
    assert result["scanned"] == 5
    # actions_proposed = count of tier S/A broken rows (known-S + probe-A = 2)
    assert result["actions_proposed"] == 2
    assert result["actions_executed"] == 0  # dry_run blocks send

    # Report file should exist with expected shape.
    body = json.loads(report_path.read_text(encoding="utf-8"))
    assert body["rows_scanned"] == 5
    # stale-1 (>120d) + stale-2 (NULL fetched_at) -> 2 stale
    assert body["stale_count"] == 2
    # broken-known-S + broken-probe-A -> 2 broken
    assert body["broken_count"] == 2
    assert body["per_tier"]["S"]["broken"] == 1
    assert body["per_tier"]["A"]["broken"] == 1
    assert body["per_tier"]["B"]["stale"] == 1
    assert body["per_tier"]["C"]["stale"] == 1

    # High-priority list must contain both S/A broken ids and nothing else.
    hp_ids = {hp["unified_id"] for hp in body["high_priority_broken"]}
    assert hp_ids == {"broken-known-S", "broken-probe-A"}

    # HEAD probe touched both rows that lacked source_last_check_status
    # (stale-2 returns 200 -> not broken; broken-probe-A returns 503 -> broken).
    assert set(fake_client.head_calls) == {
        "https://example.gov/broken-probe",
        "https://example.gov/stale-2",
    }


def test_loop_i_default_dry_run_returns_scaffold_shape(tmp_path: Path) -> None:
    """Empty input -> orchestrator-friendly zeroed dict + report still written."""
    report_path = tmp_path / "report.json"
    result = loop_i.run(dry_run=True, rows=[], report_path=report_path)
    assert result == {
        "loop": "loop_i_doc_freshness",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }
    assert report_path.exists()
    body = json.loads(report_path.read_text(encoding="utf-8"))
    assert body["rows_scanned"] == 0
    assert body["stale_count"] == 0
    assert body["broken_count"] == 0


def test_send_freshness_alert_skips_when_no_high_priority() -> None:
    """No tier S/A broken -> no Postmark send attempted."""
    report = {
        "high_priority_broken": [],
        "stale_count": 5,
        "broken_count": 0,
        "per_tier": {},
    }
    result = loop_i.send_freshness_alert(report)
    assert result["sent"] is False
    assert result["reason"] == "no_high_priority_broken"


@pytest.mark.parametrize(
    "ts,expect_stale",
    [
        (None, True),
        ("", True),
        ("not-a-date", True),
        ((dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat(), False),
        ((dt.datetime.now(dt.UTC) - dt.timedelta(days=90)).isoformat(), True),
    ],
)
def test_find_stale_rows_handles_varied_timestamp_shapes(
    ts: str | None, expect_stale: bool
) -> None:
    rows = [{"unified_id": "x", "tier": "B", "source_fetched_at": ts}]
    stale = loop_i.find_stale_rows(rows)
    assert (len(stale) == 1) is expect_stale
