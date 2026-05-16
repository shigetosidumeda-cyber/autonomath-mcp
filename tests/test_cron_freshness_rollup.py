"""Tests for the Wave 37 cron freshness rollup + SLA breach detector.

Strategy:

  * Mock ``gh run list`` via monkeypatching ``fetch_latest_run`` /
    ``fetch_run_history`` — no network, no gh binary needed.
  * Build a tiny synthetic snapshot dict by hand and feed it to the
    breach detector.
  * Smoke the dashboard HTML extension for valid Schema.org JSON-LD
    and presence of the 19-cron heatmap container.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.cron import detect_freshness_sla_breach, rollup_freshness_daily

UTC = UTC
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Rollup script
# ---------------------------------------------------------------------------


def test_canonical_cron_count_matches_doc():
    """Canonical list must mirror docs/runbook/cron_schedule_master.md."""
    # Wave 37 ships 19 axis cohort crons (Lanes A=5, B=4, C=3, D=7 — total 19).
    assert len(rollup_freshness_daily.CANONICAL_CRONS) == 19


def test_canonical_lane_split():
    by_lane: dict[str, int] = {}
    for c in rollup_freshness_daily.CANONICAL_CRONS:
        by_lane[c.lane] = by_lane.get(c.lane, 0) + 1
    assert by_lane["A"] == 5
    assert by_lane["B"] == 4
    assert by_lane["C"] == 3
    assert by_lane["D"] == 7


def test_no_collisions_in_canonical_table():
    """No two daily crons may share the same UTC minute (Wave 37 rebalance)."""
    daily = [c for c in rollup_freshness_daily.CANONICAL_CRONS if c.lane in {"A", "B", "C"}]
    slots = [c.cron_utc for c in daily]
    assert len(set(slots)) == len(slots), f"collision in daily slots: {slots}"


def test_next_run_at_daily_wildcard():
    now = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
    nxt = rollup_freshness_daily.next_run_at("0 20 * * *", now=now)
    assert nxt is not None
    parsed = datetime.fromisoformat(nxt)
    assert parsed > now
    assert parsed.hour == 20 and parsed.minute == 0


def test_next_run_at_weekly_sunday():
    # Sunday cron, now=Friday → next should be the upcoming Sunday.
    now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)  # Friday
    nxt = rollup_freshness_daily.next_run_at("0 18 * * 0", now=now)
    assert nxt is not None
    parsed = datetime.fromisoformat(nxt)
    # cron DOW 0 = Sunday; Python Sunday weekday() == 6.
    assert parsed.weekday() == 6


def test_next_run_at_returns_none_on_bad_input():
    assert rollup_freshness_daily.next_run_at("bogus") is None
    assert rollup_freshness_daily.next_run_at("* * * * * *") is None
    assert rollup_freshness_daily.next_run_at("ab cd * * *") is None


def test_db_table_freshness_db_missing(tmp_path):
    out = rollup_freshness_daily.db_table_freshness(tmp_path / "ghost.db", ("foo",))
    assert out["foo"]["status"] == "db_missing"


def test_db_table_freshness_reads_max_last_verified(tmp_path):
    db = tmp_path / "tiny.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE programs (id INTEGER PRIMARY KEY, last_verified TEXT)")
    conn.execute(
        "INSERT INTO programs(id, last_verified) VALUES (1, '2026-05-10T00:00:00Z'), (2, '2026-05-12T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    out = rollup_freshness_daily.db_table_freshness(db, ("programs", "ghost_table"))
    assert out["programs"]["status"] == "ok"
    assert out["programs"]["timestamp_col"] == "last_verified"
    assert out["programs"]["max_timestamp"] == "2026-05-12T00:00:00Z"
    assert out["ghost_table"]["status"] == "table_missing"


def test_build_rollup_no_gh(monkeypatch):
    monkeypatch.setattr(rollup_freshness_daily, "gh_cli_available", lambda: False)
    snapshot = rollup_freshness_daily.build_rollup(now=datetime(2026, 5, 12, 1, 0, tzinfo=UTC))
    assert snapshot["gh_available"] is False
    assert snapshot["canonical_cron_count"] == 19
    assert len(snapshot["crons"]) == 19
    assert all(c["last_run"] is None for c in snapshot["crons"])


def test_build_rollup_writes_idempotent_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(rollup_freshness_daily, "gh_cli_available", lambda: False)
    monkeypatch.setattr(rollup_freshness_daily, "ANALYTICS_DIR", tmp_path)
    snapshot = rollup_freshness_daily.build_rollup(now=datetime(2026, 5, 12, 1, 0, tzinfo=UTC))
    out = rollup_freshness_daily.write_snapshot(snapshot, "2026-05-12")
    assert out.exists()
    # idempotent: re-running overwrites without error.
    out2 = rollup_freshness_daily.write_snapshot(snapshot, "2026-05-12")
    assert out2 == out
    assert (tmp_path / "freshness_rollup_latest.json").exists()


# ---------------------------------------------------------------------------
# SLA breach detector
# ---------------------------------------------------------------------------


def _snapshot_with(now: datetime, runs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at_utc": now.isoformat(),
        "gh_available": True,
        "canonical_cron_count": len(runs),
        "crons": runs,
    }


def test_detect_breach_stale():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=UTC)
    cron = {
        "workflow": "adoption-rss-daily",
        "lane": "A",
        "cron_utc": "0 20 * * *",
        "sla_hours": 24,
        "db": "jpintel",
        "last_run": {
            "created_at": (now - timedelta(hours=30)).isoformat(),
            "conclusion": "success",
        },
        "success_rate_24h_pct": 100.0,
        "tables": {},
    }
    breaches = detect_freshness_sla_breach.detect_breaches(_snapshot_with(now, [cron]), now=now)
    assert len(breaches) == 1
    assert breaches[0].severity == "stale"
    assert breaches[0].workflow == "adoption-rss-daily"


def test_detect_breach_failed():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=UTC)
    cron = {
        "workflow": "edinet-daily",
        "lane": "A",
        "cron_utc": "30 19 * * *",
        "sla_hours": 24,
        "db": "jpintel",
        "last_run": {"created_at": (now - timedelta(hours=5)).isoformat(), "conclusion": "failure"},
        "success_rate_24h_pct": 80.0,
        "tables": {},
    }
    breaches = detect_freshness_sla_breach.detect_breaches(_snapshot_with(now, [cron]), now=now)
    assert breaches[0].severity == "failed"


def test_detect_breach_low_success_rate():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=UTC)
    cron = {
        "workflow": "jpo-patents-daily",
        "lane": "C",
        "cron_utc": "30 23 * * *",
        "sla_hours": 24,
        "db": "jpintel",
        "last_run": {"created_at": (now - timedelta(hours=2)).isoformat(), "conclusion": "success"},
        "success_rate_24h_pct": 30.0,
        "tables": {},
    }
    breaches = detect_freshness_sla_breach.detect_breaches(_snapshot_with(now, [cron]), now=now)
    assert breaches[0].severity == "low_success_rate"


def test_detect_breach_never_ran():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=UTC)
    cron = {
        "workflow": "multilingual-weekly",
        "lane": "D",
        "cron_utc": "0 4 * * 0",
        "sla_hours": 168,
        "db": "jpintel",
        "last_run": None,
        "success_rate_24h_pct": None,
        "tables": {},
    }
    breaches = detect_freshness_sla_breach.detect_breaches(_snapshot_with(now, [cron]), now=now)
    assert breaches[0].severity == "never_ran"


def test_detect_breach_all_green_returns_empty():
    now = datetime(2026, 5, 12, 1, 0, tzinfo=UTC)
    cron = {
        "workflow": "adoption-rss-daily",
        "lane": "A",
        "cron_utc": "0 20 * * *",
        "sla_hours": 24,
        "db": "jpintel",
        "last_run": {"created_at": (now - timedelta(hours=2)).isoformat(), "conclusion": "success"},
        "success_rate_24h_pct": 100.0,
        "tables": {},
    }
    assert detect_freshness_sla_breach.detect_breaches(_snapshot_with(now, [cron]), now=now) == []


def test_format_telegram_all_green():
    payload = detect_freshness_sla_breach.format_telegram_payload([])
    assert payload == "[jpcite cron freshness] all green"


def test_format_telegram_breach_payload():
    breach = detect_freshness_sla_breach.Breach(
        workflow="adoption-rss-daily",
        severity="stale",
        detail="last run was 30h ago (SLA 24h)",
        sla_hours=24,
        last_run_at="2026-05-10T20:00:00+00:00",
        success_rate_pct=100.0,
    )
    payload = detect_freshness_sla_breach.format_telegram_payload([breach])
    assert "1 breach(es)" in payload
    assert "adoption-rss-daily" in payload
    assert "stale" in payload


def test_load_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        detect_freshness_sla_breach.load_snapshot(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------


def test_data_freshness_html_includes_wave37_heatmap():
    html_path = REPO_ROOT / "site" / "data-freshness.html"
    assert html_path.exists(), "site/data-freshness.html must exist"
    text = html_path.read_text(encoding="utf-8")
    # Wave 37 extension injects a 19-cron heatmap container + JSON-LD Dataset.
    assert 'id="cron-heatmap"' in text
    assert "Dataset" in text  # Schema.org Dataset for agent readers
    assert "freshness_rollup_latest.json" in text


def test_data_freshness_html_no_javascript_in_heatmap():
    """Wave 37 heatmap must be semantic HTML — no JS frameworks."""
    html_path = REPO_ROOT / "site" / "data-freshness.html"
    text = html_path.read_text(encoding="utf-8")
    # The heatmap block itself is server-rendered HTML.
    heatmap_start = text.find('id="cron-heatmap"')
    assert heatmap_start > 0
    heatmap_end = text.find("</section>", heatmap_start)
    heatmap_block = text[heatmap_start:heatmap_end]
    assert "<script" not in heatmap_block
    assert "import " not in heatmap_block
