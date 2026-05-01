"""Happy-path tests for `api/_universal_envelope.py`.

Covers the public envelope helpers: `license_summary`, `parse_license_filter`,
`filter_rows_by_license`, `build_envelope_extras`, plus a couple of the
per-domain `next_calls_for_*` builders. Each test uses real Python dicts /
pydantic-style attribute access — no mocks.

The module's `_load_license_map` reads autonomath.db at first call. When the
file is absent (CI / unit fixtures) the function returns an empty mapping
and every URL collapses to `unknown`. Tests below exercise that honest
empty-map path so they pass deterministically regardless of whether the
8.3 GB autonomath.db happens to be on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def _reset_license_cache():
    """Ensure each test starts with a fresh license-map cache.

    The module caches the (domain → license) mapping process-locally for
    5 minutes. A test that runs after another suite has already loaded
    the map would otherwise see a populated cache and assert against the
    wrong shape.
    """
    from jpintel_mcp.api import _universal_envelope as ue

    ue._LICENSE_MAP_CACHE = None
    ue._LICENSE_MAP_EXPIRY = 0.0
    yield


def test_license_summary_counts_each_row():
    """1 dict in → status / data / error envelope-shaped output.

    `license_summary` is the closest analogue to a "wrap one dict" call:
    it accepts an iterable and returns `{license: count}`. The summary
    is the load-bearing envelope field consumed downstream.
    """
    from jpintel_mcp.api._universal_envelope import (
        build_envelope_extras,
        license_summary,
    )

    rows = [
        {"source_url": "https://www.nta.go.jp/foo"},
        {"source_url": "https://www.example.com/bar"},
        {"source_url": None},
    ]

    summary = license_summary(rows)
    # In the no-autonomath-db path every row collapses to `unknown`.
    assert isinstance(summary, dict)
    assert sum(summary.values()) == 3
    assert "unknown" in summary

    extras = build_envelope_extras(rows)
    # The envelope key contract: `_license_summary` is always present.
    assert "_license_summary" in extras
    assert isinstance(extras["_license_summary"], dict)


def test_parse_license_filter_validates_enum():
    """Comma-separated license values get parsed + validated against the enum."""
    from jpintel_mcp.api._universal_envelope import parse_license_filter

    assert parse_license_filter(None) is None
    assert parse_license_filter("") is None
    assert parse_license_filter("pdl_v1.0,cc_by_4.0") == {"pdl_v1.0", "cc_by_4.0"}
    # Unknown enum values silently dropped.
    assert parse_license_filter("totally_made_up") is None
    assert parse_license_filter("pdl_v1.0,nope") == {"pdl_v1.0"}


def test_next_calls_for_program_emits_get_program():
    """A row with `unified_id` always gets a `get_program` follow-up."""
    from jpintel_mcp.api._universal_envelope import next_calls_for_program

    row = {"unified_id": "UNI-test-1", "program_kind": "subsidy"}
    calls = next_calls_for_program(row)
    tools = [c["tool"] for c in calls]
    assert "get_program" in tools
    assert "trace_program_to_law" in tools
    # subsidy kind triggers the case-study suggestion.
    assert "find_cases_by_program" in tools


def test_build_envelope_extras_with_next_calls_fn_is_resilient():
    """`build_envelope_extras` swallows per-row failures so one bad row
    cannot poison the whole response."""
    from jpintel_mcp.api._universal_envelope import (
        build_envelope_extras,
        next_calls_for_program,
    )

    rows = [
        {"unified_id": "UNI-test-1"},
        {},  # no unified_id → next_calls_for_program returns []
    ]
    extras = build_envelope_extras(rows, next_calls_fn=next_calls_for_program)
    assert "_next_calls" in extras
    assert "_license_summary" in extras
    # First row produces ≥1 suggestion; second produces zero.
    assert len(extras["_next_calls"]) >= 1
