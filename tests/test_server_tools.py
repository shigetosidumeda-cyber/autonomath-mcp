"""MCP one-shot tool handler tests for new tools added 2026-04-25.

Covers `subsidy_roadmap_3yr` (and future co-located one-shot tools). The
@mcp.tool() decorator keeps the wrapped callable as a plain Python function,
so we call it directly without spinning up an MCP transport.

Seeded `programs` rows in conftest.py have `application_window_json = NULL`,
which `subsidy_roadmap_3yr` ignores by design (it filters them out). To
exercise the tool we inject a small fixture-scoped batch of rows with
populated windows + funding_purpose. Each test re-seeds inside the test so
state doesn't leak between cases.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jpintel_mcp.mcp.server import (
    _jst_fy_quarter,
    _project_next_opens,
    regulatory_prep_pack,
    subsidy_roadmap_3yr,
)


def _today_jst() -> str:
    return (datetime.now(UTC) + timedelta(hours=9)).date().isoformat()


def _seed_roadmap_programs(db_path: Path) -> None:
    """Insert programs with structured application windows for roadmap tests.

    All ids prefixed UNI-roadmap-* so we can clean them per-test. Mix of
    near (Q1 same year), mid (Q3 same year), far (next FY), and past windows.
    """
    today = datetime.fromisoformat(_today_jst()).date()
    near = today + timedelta(days=15)
    mid = today + timedelta(days=180)
    far = today + timedelta(days=720)
    past = today - timedelta(days=400)

    rows = [
        # near: starts 15 days from now, equipment, corporation, S, 東京都
        (
            "UNI-roadmap-near",
            "Roadmap 設備支援 (近)",
            "S",
            "東京都",
            "国",
            "subsidy",
            1000.0,
            ["corporation"],
            ["設備投資"],
            {
                "start_date": near.isoformat(),
                "end_date": (near + timedelta(days=60)).isoformat(),
                "cycle": "annual",
            },
        ),
        # mid: 6 months out, green, sole prop, A, no prefecture
        (
            "UNI-roadmap-mid",
            "Roadmap GX 補助金 (中)",
            "A",
            None,
            "国",
            "subsidy",
            500.0,
            ["sole_proprietor"],
            ["環境対応"],
            {
                "start_date": mid.isoformat(),
                "end_date": (mid + timedelta(days=30)).isoformat(),
                "cycle": "annual",
            },
        ),
        # far: 2 years out, equipment, B
        (
            "UNI-roadmap-far",
            "Roadmap 投資補助 (遠)",
            "B",
            "東京都",
            "都道府県",
            "subsidy",
            800.0,
            ["corporation"],
            ["設備投資"],
            {"start_date": far.isoformat(), "end_date": None, "cycle": "annual"},
        ),
        # past start, annual cycle → projected next year
        (
            "UNI-roadmap-rolled",
            "Roadmap 年次更新",
            "A",
            "東京都",
            "都道府県",
            "subsidy",
            200.0,
            ["corporation"],
            ["人件費"],
            {"start_date": past.isoformat(), "end_date": None, "cycle": "annual"},
        ),
        # past start + non-annual → excluded
        (
            "UNI-roadmap-dead",
            "Roadmap 旧制度",
            "C",
            None,
            "国",
            "subsidy",
            100.0,
            ["corporation"],
            ["設備投資"],
            {"start_date": past.isoformat(), "end_date": past.isoformat(), "cycle": "rolling"},
        ),
    ]
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        for r in rows:
            uid, name, tier, pref, auth, kind, amt, ttypes, fpurp, window = r
            conn.execute(
                """INSERT OR REPLACE INTO programs(
                    unified_id, primary_name, aliases_json,
                    authority_level, authority_name, prefecture, municipality,
                    program_kind, official_url,
                    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                    excluded, exclusion_reason,
                    crop_categories_json, equipment_category,
                    target_types_json, funding_purpose_json,
                    amount_band, application_window_json,
                    enriched_json, source_mentions_json, updated_at,
                    source_url
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    name,
                    None,
                    auth,
                    None,
                    pref,
                    None,
                    kind,
                    f"https://example.gov.jp/{uid}",
                    amt,
                    None,
                    None,
                    None,
                    tier,
                    None,
                    None,
                    None,
                    0,
                    None,
                    None,
                    None,
                    json.dumps(ttypes, ensure_ascii=False),
                    json.dumps(fpurp, ensure_ascii=False),
                    None,
                    json.dumps(window, ensure_ascii=False),
                    None,
                    None,
                    now,
                    f"https://primary.gov.jp/{uid}",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _cleanup(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM programs WHERE unified_id LIKE 'UNI-roadmap-%'")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def roadmap_db(seeded_db: Path):
    _seed_roadmap_programs(seeded_db)
    yield seeded_db
    _cleanup(seeded_db)


# ---------------------------------------------------------------------------
# Pure helpers — no DB.
# ---------------------------------------------------------------------------


def test_jst_fy_quarter_q1_april_to_june():
    assert _jst_fy_quarter("2026-04-01") == "FY2026 Q1"
    assert _jst_fy_quarter("2026-06-30") == "FY2026 Q1"


def test_jst_fy_quarter_q4_jan_belongs_to_prior_fy():
    # Jan-Mar 2027 belongs to FY2026 Q4.
    assert _jst_fy_quarter("2027-01-15") == "FY2026 Q4"
    assert _jst_fy_quarter("2027-03-31") == "FY2026 Q4"


def test_jst_fy_quarter_q3_oct():
    assert _jst_fy_quarter("2026-10-01") == "FY2026 Q3"
    assert _jst_fy_quarter("2026-12-31") == "FY2026 Q3"


def test_project_next_opens_rolls_past_annual_to_future():
    # 2014 start, 2026 anchor → must roll forward to >= 2026.
    rolled = _project_next_opens("2014-02-14", "annual", "2026-04-25")
    assert rolled is not None
    assert rolled >= "2026-04-25"


def test_project_next_opens_returns_none_for_rolling():
    assert _project_next_opens("2020-01-01", "rolling", "2026-04-25") is None


def test_project_next_opens_handles_feb_29():
    # 2020-02-29 is a leap day; rolling to non-leap year must drop to 02-28.
    rolled = _project_next_opens("2020-02-29", "annual", "2026-04-25")
    assert rolled is not None
    assert rolled.endswith("-02-28")


# ---------------------------------------------------------------------------
# subsidy_roadmap_3yr — DB-backed.
# ---------------------------------------------------------------------------


def test_subsidy_roadmap_happy_path(client, roadmap_db):
    res = subsidy_roadmap_3yr(industry="製造業")
    assert "timeline" in res
    assert res["industry"] == "E"  # 製造業 → E
    assert res["from_date"] == _today_jst()
    ids = {entry["program_id"] for entry in res["timeline"]}
    # Past+rolling should be excluded; near/mid/far/rolled should be present.
    assert "UNI-roadmap-near" in ids
    assert "UNI-roadmap-rolled" in ids
    assert "UNI-roadmap-dead" not in ids
    # Sorted ascending by opens_at.
    opens_dates = [e["opens_at"] for e in res["timeline"] if e["opens_at"]]
    assert opens_dates == sorted(opens_dates)


def test_subsidy_roadmap_horizon_12_months_excludes_far_window(client, roadmap_db):
    """horizon_months=12 should drop the +720d 'far' entry (~24 months)."""
    res = subsidy_roadmap_3yr(industry="A", horizon_months=12)
    # `far` is +720 days, beyond a 12-month horizon (~12*31=372 days).
    if "timeline" in res:
        ids = {entry["program_id"] for entry in res["timeline"]}
        assert "UNI-roadmap-far" not in ids
    # All quarter buckets must be within 12 months from today.
    today = datetime.fromisoformat(_today_jst()).date()
    cutoff = (today + timedelta(days=12 * 31)).year + 1
    for entry in res.get("timeline", []):
        # Anchor (opens_at or deadline) must be < cutoff_year.
        anchor = entry["opens_at"] or entry["application_deadline"]
        if anchor:
            assert anchor[:4] < str(cutoff + 1)


def test_subsidy_roadmap_funding_purpose_green_narrows_results(client, roadmap_db):
    res = subsidy_roadmap_3yr(industry="A", funding_purpose="green")
    ids = {entry["program_id"] for entry in res.get("timeline", [])}
    # Only the GX-tagged 'mid' row and any other 環境対応 row should appear.
    assert "UNI-roadmap-mid" in ids
    assert "UNI-roadmap-near" not in ids  # 設備投資 — not green
    assert "UNI-roadmap-rolled" not in ids  # 人件費


def test_subsidy_roadmap_empty_returns_nested_error_envelope(client, roadmap_db):
    # Pick a prefecture/purpose combo that yields zero rows.
    res = subsidy_roadmap_3yr(
        industry="A",
        prefecture="沖縄県",
        funding_purpose="export",  # no seeded row matches
    )
    assert "error" in res
    assert isinstance(res["error"], dict)
    assert res["error"]["code"] == "empty_roadmap"
    assert "hint" in res["error"]
    assert "message" in res["error"]


def test_subsidy_roadmap_total_ceiling_sums_correctly(client, roadmap_db):
    res = subsidy_roadmap_3yr(industry="製造業", limit=50)
    assert "timeline" in res
    expected = sum(e["max_amount_yen"] or 0 for e in res["timeline"])
    assert res["total_ceiling_yen"] == expected
    # Sanity check: amount_max_man_yen 1000 → 10_000_000 yen.
    near_entry = next(
        (e for e in res["timeline"] if e["program_id"] == "UNI-roadmap-near"),
        None,
    )
    assert near_entry is not None
    assert near_entry["max_amount_yen"] == 10_000_000


def test_subsidy_roadmap_past_from_date_clamped_with_hint(client, roadmap_db):
    res = subsidy_roadmap_3yr(industry="A", from_date="2020-01-01")
    assert res["from_date"] == _today_jst()
    assert "hint" in res
    assert "clamp" in res["hint"]


# ---------------------------------------------------------------------------
# Prefecture typo gate: both tools must surface input_warnings (not silent
# 0-row filter). Mirrors the BUG-2 pattern used by the 8 search tools.
# ---------------------------------------------------------------------------


def test_subsidy_roadmap_unknown_prefecture_surfaces_input_warnings(client, roadmap_db):
    # 'Tokio' is the canonical typo → must NOT silently filter to 0 rows.
    res = subsidy_roadmap_3yr(industry="製造業", prefecture="Tokio")
    # Must surface the warning either as a successful response with data,
    # or alongside the empty_roadmap envelope. Both paths carry it now.
    container = res if "input_warnings" in res else res.get("error", {})
    warnings = res.get("input_warnings") or []
    if not warnings and "input_warnings" in container:
        warnings = container["input_warnings"]
    assert warnings, f"expected input_warnings, got {res!r}"
    pref_warning = next((w for w in warnings if w.get("field") == "prefecture"), None)
    assert pref_warning is not None
    assert pref_warning["code"] == "unknown_prefecture"
    assert pref_warning["value"] == "Tokio"


def test_regulatory_prep_pack_unknown_prefecture_surfaces_input_warnings(client):
    res = regulatory_prep_pack(industry="製造業", prefecture="東京府")
    # 東京府 is a real-world typo (it was 東京府 prior to 1943; not a current
    # prefecture). Tool must surface the warning, not silently no-op.
    warnings = res.get("input_warnings") or []
    if not warnings:
        warnings = res.get("error", {}).get("input_warnings") or []
    assert warnings, f"expected input_warnings, got {res!r}"
    pref_warning = next((w for w in warnings if w.get("field") == "prefecture"), None)
    assert pref_warning is not None
    assert pref_warning["code"] == "unknown_prefecture"
    assert pref_warning["value"] == "東京府"
