"""PERF-42 — unit tests for the CI runtime budget analyzer.

The analyzer powers ``scripts/ops/ci_budget_check.py`` (GHA budget gate) and
the ``make ci-budget-check`` Makefile target. The HTTP path is not exercised
here (GH REST API auth required); the pure ``evaluate()`` function over
job-shape dicts is the load-bearing logic and is what's covered below.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "ci_budget_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ci_budget_check", _SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_budget_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def _job(name: str, started_at: str, completed_at: str, status: str = "success") -> dict:
    return {
        "name": name,
        "started_at": started_at,
        "completed_at": completed_at,
        "conclusion": status,
    }


def test_within_budget_simple_two_jobs() -> None:
    mod = _load_module()
    jobs = [
        _job("ruff", "2026-05-17T10:00:00Z", "2026-05-17T10:01:30Z"),
        _job("mypy", "2026-05-17T10:00:00Z", "2026-05-17T10:05:00Z"),
    ]
    within, summary = mod.evaluate(jobs, budget_minutes=15, excludes=["ci-budget"])
    assert within is True
    # Wall = max(end) - min(start) = 5 min.
    assert summary["wall_clock_minutes"] == 5.0
    assert summary["within_budget"] is True


def test_over_budget_fails() -> None:
    mod = _load_module()
    jobs = [
        _job("ruff", "2026-05-17T10:00:00Z", "2026-05-17T10:01:30Z"),
        _job("pytest", "2026-05-17T10:00:00Z", "2026-05-17T10:20:00Z"),
    ]
    within, summary = mod.evaluate(jobs, budget_minutes=15, excludes=["ci-budget"])
    assert within is False
    assert summary["wall_clock_minutes"] == 20.0
    assert summary["within_budget"] is False


def test_excluded_jobs_do_not_count_toward_wall_clock() -> None:
    """The gate's own ci-budget job is excluded so it doesn't fight itself."""
    mod = _load_module()
    jobs = [
        _job("ruff", "2026-05-17T10:00:00Z", "2026-05-17T10:01:00Z"),
        # ci-budget runs LAST and would inflate wall clock; excluded.
        _job("ci-budget", "2026-05-17T10:01:00Z", "2026-05-17T10:25:00Z"),
    ]
    within, summary = mod.evaluate(jobs, budget_minutes=15, excludes=["ci-budget"])
    # Wall = 1 min (only ruff counts); ci-budget excluded.
    assert summary["wall_clock_minutes"] == 1.0
    assert within is True
    # Excluded job still in the rows, marked excluded.
    excluded_rows = [r for r in summary["jobs"] if r.get("excluded")]
    assert len(excluded_rows) == 1
    assert excluded_rows[0]["name"] == "ci-budget"


def test_in_flight_job_does_not_crash() -> None:
    """A job without completed_at is reported as in-flight (no division-by-zero)."""
    mod = _load_module()
    jobs = [
        _job("ruff", "2026-05-17T10:00:00Z", "2026-05-17T10:01:00Z"),
        {"name": "pytest-shard-0", "started_at": "2026-05-17T10:00:00Z", "completed_at": None},
    ]
    within, summary = mod.evaluate(jobs, budget_minutes=15, excludes=[])
    assert within is True  # only the completed ruff job counts toward wall clock
    in_flight = [r for r in summary["jobs"] if r.get("in_flight")]
    assert len(in_flight) == 1


def test_empty_jobs_zero_wall_clock() -> None:
    mod = _load_module()
    within, summary = mod.evaluate([], budget_minutes=15, excludes=[])
    assert within is True
    assert summary["wall_clock_seconds"] == 0.0
    assert summary["wall_clock_minutes"] == 0.0


def test_substring_exclude_matches_case_insensitive() -> None:
    mod = _load_module()
    jobs = [
        _job("pytest (3.12 shard 0/4)", "2026-05-17T10:00:00Z", "2026-05-17T10:10:00Z"),
        _job("CI-BUDGET runtime gate", "2026-05-17T10:10:00Z", "2026-05-17T10:30:00Z"),
    ]
    within, summary = mod.evaluate(jobs, budget_minutes=15, excludes=["ci-budget"])
    # Only pytest counts → wall = 10 min, within budget. The CI-BUDGET row is excluded
    # despite the uppercase / extra-text name (substring + case-insensitive match).
    assert within is True
    assert summary["wall_clock_minutes"] == 10.0
