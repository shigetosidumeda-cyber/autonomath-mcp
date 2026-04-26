"""Tests for program_lifecycle — O4 Wave 18 Amendment Lifecycle MCP tool.

Covers the 3 mandatory cases from the task spec
(analysis_wave18/_o4_lifecycle_2026-04-25.md, status precedence rules):

  1. sunset 90 日以内 → ``sunset_imminent``
  2. effective_until NULL (and effective_from in past, no lineage edge,
     version_seq=1) → ``active``
  3. unified_id 不在 → ``unknown`` + reason citing "not found in am_entities"

Run:

    .venv/bin/python -m pytest tests/test_program_lifecycle.py -x --tb=short
"""

from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping lifecycle tests. "
        "Set AUTONOMATH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_LIFECYCLE_ENABLED", "1")

# server must be imported first to break circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.lifecycle_tool import (  # noqa: E402
    _STATUS_LABEL_JA,
    _SUNSET_IMMINENT_DAYS,
    _program_lifecycle_impl,
)

# ---------------------------------------------------------------------------
# Test 1: sunset 90 日以内 → sunset_imminent
#
# Real fixture: `program:79_electricity_market_energy_retail:000016:7_8ed122708b`
# carries effective_from=2026-01 / effective_until=2026-03 (the only pair of
# parseable ISO effective_until rows in am_amendment_snapshot).
#
# To put it inside the [0, 90) day imminent window we evaluate as_of just 60
# days before the parsed effective_until (2026-03-01). 2026-01-01 → 59 days
# remaining → falls in the imminent bucket.
# ---------------------------------------------------------------------------


def test_sunset_imminent_fires_within_90_days() -> None:
    """effective_until - as_of < 90 days → status='sunset_imminent'."""
    unified_id = "program:79_electricity_market_energy_retail:000016:7_8ed122708b"
    # effective_until = 2026-03-01 (parsed from "2026-03"); 60 days back = 2026-01-01.
    as_of = datetime.date(2026, 1, 1)
    out = _program_lifecycle_impl(unified_id, as_of)

    assert out["unified_id"] == unified_id
    assert out["status"] == "sunset_imminent", out
    assert out["status_label_ja"] == _STATUS_LABEL_JA["sunset_imminent"]
    assert out["evidence"]["effective_dates"]["effective_until"] == "2026-03-01"
    # Reason must cite the deterministic threshold.
    assert "90" in out["reason"] or "imminent" in out["reason"]
    # Sanity: effective_until is in [0, 90) days from as_of.
    eu = datetime.date.fromisoformat(out["evidence"]["effective_dates"]["effective_until"])
    delta = (eu - as_of).days
    assert 0 <= delta < _SUNSET_IMMINENT_DAYS, delta


# ---------------------------------------------------------------------------
# Test 2: effective_until NULL → active (or amended fallback)
#
# Strict spec: a v1-only program with effective_from <= as_of and
# effective_until IS NULL and no successor_of/replaces edge yields `active`.
#
# Real-data caveat: every NULL-effective_until row in am_amendment_snapshot
# happens to be version_seq=2 (the table is pseudo-time-series), so step 5
# (`amended`) intercepts before step 6 (`active`). We discover a candidate
# row dynamically: prefer version_seq=1 if any exist (= clean active);
# else fall back to version_seq=2 + assert the `amended` path with
# effective_until NULL surfaced — which still demonstrates the
# "NULL-until is not sunset" branch (steps 3 & 4 do NOT trigger).
# ---------------------------------------------------------------------------


def _find_active_or_amended_candidate() -> tuple[str, str, datetime.date]:
    """Pick a real entity with effective_until NULL and a parseable
    effective_from in the past. Returns (entity_id, expected_status, as_of).

    Skips the test if no such row exists.
    """
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    try:
        # Prefer max(version_seq)=1 → expected `active`.
        row = conn.execute(
            """
            SELECT s.entity_id,
                   MAX(s.version_seq) AS max_v,
                   MIN(s.effective_from) AS first_eff_from
              FROM am_amendment_snapshot s
              LEFT JOIN am_relation r
                ON r.source_entity_id = s.entity_id
               AND r.relation_type IN ('replaces','successor_of')
             WHERE s.effective_until IS NULL
               AND s.effective_from LIKE '____-__-__'
               AND r.source_entity_id IS NULL
             GROUP BY s.entity_id
             ORDER BY max_v ASC
             LIMIT 1
            """,
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        pytest.skip(
            "no am_amendment_snapshot row with NULL effective_until + "
            "ISO effective_from + no lineage edge — fixture unavailable."
        )

    entity_id, max_v, first_eff_from = row
    eff_from = datetime.date.fromisoformat(first_eff_from)
    # as_of = today JST, but at least one day past effective_from.
    today = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=9)
    ).date()
    as_of = max(today, eff_from + datetime.timedelta(days=1))
    expected = "active" if max_v == 1 else "amended"
    return entity_id, expected, as_of


def test_effective_until_null_is_not_sunset() -> None:
    """effective_until IS NULL must yield `active` (v1) or `amended` (v2+).

    Critical assertion: it must NEVER be `sunset_imminent` or
    `sunset_scheduled` — those require a non-null effective_until.
    """
    entity_id, expected, as_of = _find_active_or_amended_candidate()
    out = _program_lifecycle_impl(entity_id, as_of)

    assert out["status"] == expected, out
    # Both paths must surface effective_until=None and not flag sunset.
    assert out["evidence"]["effective_dates"]["effective_until"] is None
    assert out["status"] not in ("sunset_imminent", "sunset_scheduled")
    if expected == "active":
        assert out["confidence"] in ("medium", "high")
    else:
        # amended path → low confidence (am_amendment_snapshot uniform hash).
        assert out["confidence"] == "low"
        assert "uniform hash" in out["reason"] or "amendment_snapshot" in out["reason"]


# ---------------------------------------------------------------------------
# Test 3: unified_id 不在 → unknown + reason
# ---------------------------------------------------------------------------


def test_unknown_when_unified_id_absent() -> None:
    """Non-existent canonical_id → status='unknown' + reason citing the miss."""
    bogus_id = "program:nonexistent:does_not_exist_xyzzy"
    as_of = datetime.date(2026, 4, 25)
    out = _program_lifecycle_impl(bogus_id, as_of)

    assert out["unified_id"] == bogus_id
    assert out["status"] == "unknown"
    assert out["status_label_ja"] == _STATUS_LABEL_JA["unknown"]
    assert out["confidence"] == "low"
    # Reason must be machine-readable for the LLM:
    assert "not found" in out["reason"].lower()
    assert "search_programs" in out["reason"] or "enum_values_am" in out["reason"]
    # Evidence triple is fully null (no amendment, no relation).
    assert out["evidence"]["amendment"] is None
    assert out["evidence"]["relation"] is None
    # Disclaimer present so downstream LLM honest-discloses.
    assert "_disclaimer" in out
    assert "amendment_snapshot" in out["_disclaimer"]
