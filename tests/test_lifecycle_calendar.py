"""Tests for unified_lifecycle_calendar — O4 lifecycle calendar MCP tool.

Covers the 3 mandatory cases from the design doc
(analysis_wave18/_o4_lifecycle_2026-04-25.md §6.1):

  1. 2026-09-30 周辺の tax_sunset 検出 — インボイス 2割特例 (経過措置)
     is the canonical fixture per CLAUDE.md, am_tax_rule rev 2026-04-25.
  2. granularity='half_year' で 6ヶ月単位 (会計年度 H1/H2) bucket。
  3. 範囲 > 1 年 → out_of_range (422 相当) error envelope。

Run:

    .venv/bin/python -m pytest tests/test_lifecycle_calendar.py -x --tb=short
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping "
        "lifecycle_calendar tests. Set AUTONOMATH_DB_PATH to a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED", "1")

# server must load first to seed the @mcp.tool decorator before
# lifecycle_calendar_tool's module-level decoration runs.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.lifecycle_calendar_tool import (  # noqa: E402
    _MAX_WINDOW_DAYS,
    _bucket_key,
    _unified_lifecycle_calendar_impl,
)


# ---------------------------------------------------------------------------
# Case 1 — 2026-09-30 周辺 tax_sunset 検出 (インボイス 2割特例 経過措置)
# ---------------------------------------------------------------------------


def test_invoice_2wari_tokurei_sunset_detected_on_2026_09_30() -> None:
    """The インボイス 2割特例 (経過措置) tax sunset (2026-09-30) MUST appear
    in a window that brackets that date with kind=tax_sunset."""
    res = _unified_lifecycle_calendar_impl(
        start_date="2026-08-01",
        end_date="2026-10-31",
        granularity="month",
    )

    # Envelope shape
    assert "calendar" in res
    assert "total_events" in res
    assert "_disclaimer" in res
    assert isinstance(res["calendar"], list)
    assert "error" not in res or not res["error"]

    # Must surface at least one tax_sunset event in 2026-09 bucket.
    tax_events_2026_09 = [
        ev
        for bucket in res["calendar"]
        if bucket["period"] == "2026-09"
        for ev in bucket["events"]
        if ev["kind"] == "tax_sunset"
    ]
    assert len(tax_events_2026_09) >= 1, (
        f"expected at least 1 tax_sunset event in 2026-09 bucket; "
        f"got buckets={[b['period'] for b in res['calendar']]}"
    )

    # 2割特例 specifically MUST be present — this is the CLAUDE.md fixture.
    matches = [e for e in res["results"] if "2割特例" in e["title"]]
    assert len(matches) >= 1, (
        f"インボイス 2割特例 (経過措置) sunset on 2026-09-30 not found. "
        f"results titles: {[r['title'] for r in res['results']]}"
    )
    m = matches[0]
    assert m["date"] == "2026-09-30"
    assert m["kind"] == "tax_sunset"
    assert m["severity"] in ("critical", "warning", "info")
    # Must carry the primary 一次資料 source_url (mof.go.jp, not aggregator).
    assert m["source_url"] and "mof.go.jp" in m["source_url"]


# ---------------------------------------------------------------------------
# Case 2 — granularity='half_year' で 6ヶ月単位 bucket
# ---------------------------------------------------------------------------


def test_half_year_bucketing_collapses_to_fiscal_halves() -> None:
    """Exactly one full Japanese 会計年度 (4/1..3/31) must yield at most
    2 buckets (H1=4-9月, H2=10-3月) and every event date must fall in
    its declared half."""
    res = _unified_lifecycle_calendar_impl(
        start_date="2026-04-01",
        end_date="2027-03-31",
        granularity="half_year",
    )

    assert "error" not in res or not res["error"]
    assert res["window"]["granularity"] == "half_year"

    # Bucket label sanity — only "2026-H1" / "2026-H2" allowed for this
    # window (full FY2026). The Jan-Mar tail of 2027 is FY2026 H2 per
    # Japanese fiscal year convention.
    bucket_labels = {b["period"] for b in res["calendar"]}
    allowed = {"2026-H1", "2026-H2"}
    assert bucket_labels.issubset(allowed), (
        f"unexpected half_year bucket labels: {bucket_labels - allowed}"
    )

    # Spot-check the bucket boundaries directly via _bucket_key.
    import datetime
    assert _bucket_key(datetime.date(2026, 4, 1), "half_year") == "2026-H1"
    assert _bucket_key(datetime.date(2026, 9, 30), "half_year") == "2026-H1"
    assert _bucket_key(datetime.date(2026, 10, 1), "half_year") == "2026-H2"
    # Jan-Mar 2027 → FY2026 H2 (NOT 2027-H1).
    assert _bucket_key(datetime.date(2027, 3, 31), "half_year") == "2026-H2"
    assert _bucket_key(datetime.date(2027, 4, 1), "half_year") == "2027-H1"

    # Every event must be in its declared bucket.
    import datetime as _dt
    for bucket in res["calendar"]:
        for ev in bucket["events"]:
            d = _dt.date.fromisoformat(ev["date"])
            assert _bucket_key(d, "half_year") == bucket["period"], (
                f"event {ev['title']} ({ev['date']}) misplaced in "
                f"bucket {bucket['period']}"
            )

    # The tax_sunset インボイス 2割特例 (2026-09-30) must land in 2026-H1.
    matches = [e for e in res["results"] if "2割特例" in e["title"]]
    assert matches, "2割特例 sunset missing under half_year bucketing"
    h1 = [b for b in res["calendar"] if b["period"] == "2026-H1"][0]
    titles_h1 = {e["title"] for e in h1["events"]}
    assert any("2割特例" in t for t in titles_h1), (
        f"2割特例 should be in 2026-H1 bucket; got {titles_h1}"
    )


# ---------------------------------------------------------------------------
# Case 3 — 範囲 > 1 年 → out_of_range (422 相当) error envelope
# ---------------------------------------------------------------------------


def test_window_over_one_year_returns_out_of_range_error() -> None:
    """end_date - start_date > 366 days MUST return an error envelope with
    code='out_of_range' (severity=hard) — the API layer maps this to 422."""
    res = _unified_lifecycle_calendar_impl(
        start_date="2026-01-01",
        end_date="2027-06-30",  # 545 days
        granularity="month",
    )

    # Hard error envelope must be present.
    assert "error" in res, f"expected error envelope; got {list(res.keys())}"
    err = res["error"]
    assert err["code"] == "out_of_range", (
        f"expected code='out_of_range'; got {err['code']}"
    )
    assert err["severity"] == "hard"
    # The message must mention the cap so the LLM caller can self-correct.
    assert str(_MAX_WINDOW_DAYS) in err["message"] or "1-year" in err["message"]
    # Field hint must point at end_date.
    assert err.get("field") == "end_date"
    # Envelope keys still present for tolerant consumers.
    assert res["total"] == 0
    assert res["results"] == []
