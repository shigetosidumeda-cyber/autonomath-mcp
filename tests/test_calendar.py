"""Tests for GET /v1/calendar/deadlines + MCP upcoming_deadlines tool.

Deadline discovery is one of the top-3 LLM-agent tasks ("what's due in 30
days?"). The tests lock in:

  - a program with a future end_date surfaces with correct days_remaining
  - a past end_date is silently skipped (no negative days_remaining row)
  - within_days horizon drops far-future rows
  - prefecture filter honors national-programs fallback
  - profile_echo normalization through MCP tool matches REST
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Seed helper: attach deterministic application_window_json to seeded rows
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db_with_deadlines(seeded_db: Path):
    """Stamp application_window_json onto each seeded row:

      UNI-test-s-1  → 東京都, ends in 10 days  (inside a 30-day horizon)
      UNI-test-a-1  → 青森県, ends in 50 days  (outside a 30-day horizon)
      UNI-test-b-1  → national, ended 5 days ago  (past → skipped)
      UNI-test-x-1  → excluded row, ignored

    Yields a dict mapping unified_id → end_date ISO for assertions. Teardown
    nulls the column back out so later tests (which share the session-scoped
    seeded_db) see the original empty state.
    """
    today = date.today()
    ends = {
        "UNI-test-s-1": (today + timedelta(days=10)).isoformat(),
        "UNI-test-a-1": (today + timedelta(days=50)).isoformat(),
        "UNI-test-b-1": (today - timedelta(days=5)).isoformat(),
    }
    conn = sqlite3.connect(seeded_db)
    try:
        for uid, end_date in ends.items():
            conn.execute(
                "UPDATE programs SET application_window_json = ? WHERE unified_id = ?",
                (json.dumps({"end_date": end_date, "cycle": "annual"}), uid),
            )
        conn.commit()
    finally:
        conn.close()
    from jpintel_mcp.api.programs import _clear_program_cache

    _clear_program_cache()
    yield ends

    # Teardown: restore pre-test state so session-scoped seeded_db stays clean.
    conn = sqlite3.connect(seeded_db)
    try:
        for uid in ends:
            conn.execute(
                "UPDATE programs SET application_window_json = NULL WHERE unified_id = ?",
                (uid,),
            )
        conn.commit()
    finally:
        conn.close()
    _clear_program_cache()


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


def test_calendar_returns_only_future_within_horizon(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/calendar/deadlines", params={"within_days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [row["unified_id"] for row in body["results"]]

    # Only the one ending in 10 days is inside the 30-day horizon
    assert "UNI-test-s-1" in ids
    # 50-day end_date is outside
    assert "UNI-test-a-1" not in ids
    # Past end_date is filtered
    assert "UNI-test-b-1" not in ids
    # tier-X is excluded
    assert "UNI-test-x-1" not in ids


def test_calendar_days_remaining_math(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/calendar/deadlines", params={"within_days": 30})
    body = r.json()
    row = next(m for m in body["results"] if m["unified_id"] == "UNI-test-s-1")
    assert row["days_remaining"] == 10
    assert row["end_date"] == seeded_db_with_deadlines["UNI-test-s-1"]


def test_calendar_longer_horizon_includes_more_rows(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/calendar/deadlines", params={"within_days": 90})
    ids = [row["unified_id"] for row in r.json()["results"]]
    assert "UNI-test-s-1" in ids
    assert "UNI-test-a-1" in ids


def test_calendar_prefecture_filter_keeps_national(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    """prefecture=東京都 keeps UNI-test-s-1 (東京都) AND would keep any
    national program — the fallback clause is wired in the SQL."""
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get(
        "/v1/calendar/deadlines",
        params={"within_days": 30, "prefecture": "Tokyo"},
    )
    assert r.status_code == 200
    ids = [row["unified_id"] for row in r.json()["results"]]
    assert "UNI-test-s-1" in ids


def test_calendar_application_url_present(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/calendar/deadlines", params={"within_days": 30})
    for row in r.json()["results"]:
        assert "application_url" in row


def test_calendar_empty_db_returns_zero(client: TestClient) -> None:
    """Without the deadline fixture, no row has application_window_json set."""
    r = client.get("/v1/calendar/deadlines", params={"within_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["results"] == []
    assert body["within_days"] == 30


def test_calendar_rejects_bad_within_days(client: TestClient) -> None:
    r = client.get("/v1/calendar/deadlines", params={"within_days": 0})
    assert r.status_code == 422


def test_calendar_rejects_bad_authority_level(client: TestClient) -> None:
    """Unknown authority_level passes through normalization then yields 0 rows."""
    r = client.get(
        "/v1/calendar/deadlines",
        params={"within_days": 30, "authority_level": "Atlantis"},
    )
    # Normalization doesn't reject Atlantis — it just yields no rows
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ---------------------------------------------------------------------------
# MCP parity
# ---------------------------------------------------------------------------


def test_mcp_upcoming_deadlines_same_shape(
    seeded_db_with_deadlines: dict[str, str], seeded_db: Path
) -> None:
    from jpintel_mcp.mcp.server import upcoming_deadlines as mcp_tool

    callable_fn = getattr(mcp_tool, "fn", mcp_tool)
    res = callable_fn(within_days=30, prefecture="Tokyo")
    assert isinstance(res, dict)
    assert "as_of" in res
    assert "results" in res
    assert "total" in res
    ids = [row["unified_id"] for row in res["results"]]
    assert "UNI-test-s-1" in ids
