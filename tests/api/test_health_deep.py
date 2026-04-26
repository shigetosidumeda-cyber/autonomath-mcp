"""Tests for jpintel_mcp.api._health_deep.

Smoke + structural tests against real DBs (cheap counts + a single PRAGMA).
The aggregate-logic test injects a forced 'fail' check via monkeypatching
the ordered CHECKS registry, so we don't need a fixture DB.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jpintel_mcp.api import _health_deep as hd

REQUIRED_TOP_LEVEL = {
    "status",
    "version",
    "checks",
    "timestamp_utc",
    "evaluated_at_jst",
}
ALLOWED_OVERALL = {"ok", "degraded", "unhealthy"}
ALLOWED_CHECK = {"ok", "warn", "fail"}


@pytest.fixture(autouse=True)
def _clear_deep_health_cache() -> None:
    """Reset the 30s response cache between tests.

    The cache is keyed by time only, so without resetting it a previous
    test's CHECKS-monkeypatched result would leak into the next test.
    """
    hd._CACHE["ts"] = 0.0
    hd._CACHE["doc"] = None


def test_smoke_top_level_keys() -> None:
    doc = hd.get_deep_health()
    assert isinstance(doc, dict)
    assert REQUIRED_TOP_LEVEL.issubset(doc.keys())
    assert doc["status"] in ALLOWED_OVERALL
    assert isinstance(doc["version"], str) and doc["version"]
    assert isinstance(doc["checks"], dict) and doc["checks"]


def test_each_check_shape() -> None:
    doc = hd.get_deep_health()
    expected_names = {name for name, _ in hd.CHECKS}
    assert set(doc["checks"].keys()) == expected_names
    for name, payload in doc["checks"].items():
        assert isinstance(payload, dict), name
        assert payload["status"] in ALLOWED_CHECK, (name, payload)
        assert "details" in payload and isinstance(payload["details"], str), name
        # value is optional but key must be present
        assert "value" in payload, name


def test_timestamps_iso8601_and_jst_offset() -> None:
    doc = hd.get_deep_health()
    utc_str = doc["timestamp_utc"]
    jst_str = doc["evaluated_at_jst"]
    # Must round-trip via fromisoformat
    utc_dt = datetime.fromisoformat(utc_str)
    jst_dt = datetime.fromisoformat(jst_str)
    assert utc_dt.tzinfo is not None
    assert jst_dt.tzinfo is not None
    # JST is +09:00 (no DST)
    assert jst_dt.utcoffset().total_seconds() == 9 * 3600
    # And the JST instant equals the UTC instant
    assert jst_dt.astimezone(ZoneInfo("UTC")) == utc_dt.astimezone(ZoneInfo("UTC"))


def test_aggregate_unhealthy_when_any_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def forced_fail() -> dict[str, object]:
        return {"status": "fail", "details": "forced", "value": None}

    def forced_ok() -> dict[str, object]:
        return {"status": "ok", "details": "forced", "value": 1}

    monkeypatch.setattr(
        hd,
        "CHECKS",
        (("forced_fail", forced_fail), ("forced_ok", forced_ok)),
    )
    doc = hd.get_deep_health()
    assert doc["status"] == "unhealthy"
    assert doc["checks"]["forced_fail"]["status"] == "fail"
    assert doc["checks"]["forced_ok"]["status"] == "ok"


def test_aggregate_degraded_when_warn_no_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forced_warn() -> dict[str, object]:
        return {"status": "warn", "details": "forced", "value": None}

    def forced_ok() -> dict[str, object]:
        return {"status": "ok", "details": "forced", "value": 1}

    monkeypatch.setattr(
        hd,
        "CHECKS",
        (("forced_warn", forced_warn), ("forced_ok", forced_ok)),
    )
    doc = hd.get_deep_health()
    assert doc["status"] == "degraded"


def test_aggregate_ok_when_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def forced_ok() -> dict[str, object]:
        return {"status": "ok", "details": "forced", "value": 1}

    monkeypatch.setattr(hd, "CHECKS", (("a", forced_ok), ("b", forced_ok)))
    doc = hd.get_deep_health()
    assert doc["status"] == "ok"


def test_individual_check_exception_does_not_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, object]:
        raise RuntimeError("kaboom")

    def forced_ok() -> dict[str, object]:
        return {"status": "ok", "details": "ok", "value": 1}

    monkeypatch.setattr(
        hd, "CHECKS", (("boom", boom), ("ok", forced_ok))
    )
    doc = hd.get_deep_health()  # must not raise
    assert doc["checks"]["boom"]["status"] == "fail"
    assert "kaboom" in doc["checks"]["boom"]["details"]
    assert doc["checks"]["ok"]["status"] == "ok"
    assert doc["status"] == "unhealthy"
