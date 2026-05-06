"""Tests for DEEP-42 12 axis evolution dashboard aggregator (jpcite v0.3.4).

5 cases (per task spec):
  1. migration apply (idempotent, target_db=jpintel) creates the snapshot table + indexes + views
  2. 12 axis source aggregate produces 12 axes × signals with correct shape
  3. dashboard JSON valid (schema + 12 axes + 5 KPI plot keys)
  4. 5 KPI plot data series populated
  5. LLM API import 0 (text grep on aggregator script)

Tests use only stdlib + jinja2 + pytest (sister of test_aggregate_production_gate_status.py).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "cron" / "aggregate_evolution_dashboard.py"
MIGRATION_PATH = REPO_ROOT / "scripts" / "migrations" / "wave24_188_evolution_dashboard_snapshot.sql"
ROLLBACK_PATH = REPO_ROOT / "scripts" / "migrations" / "wave24_188_evolution_dashboard_snapshot_rollback.sql"
TEMPLATE_PATH = REPO_ROOT / "scripts" / "templates" / "evolution.html.j2"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "evolution-dashboard-weekly.yml"

sys.path.insert(0, str(SCRIPT_PATH.parent))
import aggregate_evolution_dashboard as agg  # noqa: E402


# ---------------------------------------------------------------------------
# 1. migration apply (idempotent)
# ---------------------------------------------------------------------------


def test_migration_apply_creates_table_and_views(tmp_path: Path) -> None:
    """Applying wave24_188 against a fresh sqlite produces the table + indexes + views.

    Re-applying must be a no-op (idempotent — entrypoint.sh re-runs every boot).
    """
    db = tmp_path / "jpintel.db"
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # First apply.
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(sql)
    finally:
        conn.close()
    # Second apply must succeed too (idempotent).
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(sql)
        # Verify table.
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evolution_dashboard_snapshot'"
        )
        assert cur.fetchone() is not None, "evolution_dashboard_snapshot missing"
        # Verify columns.
        cur = conn.execute("PRAGMA table_info(evolution_dashboard_snapshot)")
        cols = {row[1] for row in cur.fetchall()}
        assert {
            "id",
            "snapshot_date",
            "axis_id",
            "signal_id",
            "signal_value",
            "signal_value_json",
            "status",
            "computed_at",
        } <= cols
        # Verify indexes.
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='evolution_dashboard_snapshot'"
        )
        idx_names = {row[0] for row in cur.fetchall()}
        assert {"idx_eds_axis_date", "idx_eds_date", "idx_eds_status"} <= idx_names
        # Verify views.
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        )
        view_names = {row[0] for row in cur.fetchall()}
        assert {"v_evolution_dashboard_latest", "v_evolution_axis_status"} <= view_names
        # Verify CHECK constraint on status.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO evolution_dashboard_snapshot "
                "(snapshot_date, axis_id, signal_id, status) VALUES (?, ?, ?, ?)",
                ("2026-W19", "IA-01", "bogus", "INVALID"),
            )
            conn.commit()
        conn.rollback()
    finally:
        conn.close()
    # Verify migration first line declares target_db: jpintel.
    first = sql.splitlines()[0].strip().lower()
    assert first.startswith("-- target_db: jpintel"), first
    # Verify rollback exists and excludes from entrypoint loop (filename suffix).
    assert ROLLBACK_PATH.exists()
    assert ROLLBACK_PATH.name.endswith("_rollback.sql")


# ---------------------------------------------------------------------------
# 2. 12 axis source aggregate (graceful with missing sources)
# ---------------------------------------------------------------------------


def test_12_axis_aggregate_shape(tmp_path: Path) -> None:
    """build_snapshot returns exactly 12 axes; each carries signals; gracefully
    degrades when source DBs / analytics JSONs are absent."""
    snap = agg.build_snapshot(
        week_label="2026-W19",
        iso_date=__import__("datetime").date(2026, 5, 5),
        repo_root=tmp_path,
        jpintel_path=tmp_path / "missing-jpintel.db",
        autonomath_path=tmp_path / "missing-autonomath.db",
        analytics_dir=tmp_path / "missing-analytics",
        threshold_yml=tmp_path / "missing.yml",
    )
    assert len(snap.axes) == 12
    axis_ids = [a["id"] for a in snap.axes]
    expected = [f"IA-{n:02d}" for n in range(1, 13)]
    assert axis_ids == expected
    for axis in snap.axes:
        assert axis["status"] in {"healthy", "degraded", "broken"}
        assert axis["signal_count"] >= 1
        for s in axis["signals"]:
            assert s["status"] in {"healthy", "degraded", "broken"}
    # All sqlite/jsonl reads should return broken (DBs+JSONs missing).
    # Brokens for sqlite_count + analytics_json kinds since signals can't be fetched.
    broken_axes = [a for a in snap.axes if a["status"] == "broken"]
    assert len(broken_axes) >= 1, "at least one axis should be broken when sources are missing"


def test_12_axis_aggregate_with_real_sources(tmp_path: Path) -> None:
    """When jpintel.db has the programs table populated, IA-01 programs_count
    should resolve to a numeric scalar with status 'healthy' or 'degraded'."""
    db = tmp_path / "jpintel.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE programs (id INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO programs (id) VALUES (?)", [(i,) for i in range(1, 9001)]
        )
        conn.commit()
    finally:
        conn.close()
    analytics = tmp_path / "analytics"
    analytics.mkdir()
    (analytics / "moat_verify.json").write_text(
        json.dumps({"v_cobb_douglas": 1.2, "lambda_max": 0.05, "cascade_q": 0.07,
                    "bayesian_posterior": 0.92}),
        encoding="utf-8",
    )
    (analytics / "brand_mention.json").write_text(
        json.dumps({"self_vs_other_ratio": 0.6, "brand_reach_total": 1500}),
        encoding="utf-8",
    )
    snap = agg.build_snapshot(
        week_label="2026-W19",
        iso_date=__import__("datetime").date(2026, 5, 5),
        repo_root=tmp_path,
        jpintel_path=db,
        autonomath_path=tmp_path / "missing-autonomath.db",
        analytics_dir=analytics,
        threshold_yml=tmp_path / "missing.yml",
    )
    ia01 = next(a for a in snap.axes if a["id"] == "IA-01")
    progs = next(s for s in ia01["signals"] if s["signal_id"] == "programs_count")
    assert progs["signal_value"] == pytest.approx(9000.0)
    assert progs["status"] == "healthy"  # 9000 >= 8000 threshold
    ia10 = next(a for a in snap.axes if a["id"] == "IA-10")
    statuses = {s["signal_id"]: s["status"] for s in ia10["signals"]}
    assert statuses["v_cobb_douglas"] == "healthy"  # 1.2 >= 1.0
    assert statuses["lambda_max"] == "healthy"      # 0.05 >= 0.0
    ia12 = next(a for a in snap.axes if a["id"] == "IA-12")
    self_vs = next(s for s in ia12["signals"] if s["signal_id"] == "self_vs_other_ratio")
    assert self_vs["status"] == "healthy"  # 0.6 <= 0.7 healthy_le


# ---------------------------------------------------------------------------
# 3. dashboard JSON valid
# ---------------------------------------------------------------------------


def test_dashboard_json_valid(tmp_path: Path) -> None:
    """write_json + reload returns a structure with schema_version, axes, kpi_plots."""
    snap = agg.build_snapshot(
        week_label="2026-W19",
        iso_date=__import__("datetime").date(2026, 5, 5),
        repo_root=tmp_path,
        jpintel_path=tmp_path / "missing.db",
        autonomath_path=tmp_path / "missing-autonomath.db",
        analytics_dir=tmp_path / "missing-analytics",
        threshold_yml=tmp_path / "missing.yml",
    )
    out = tmp_path / "snap.json"
    agg.write_json(snap, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "deep42.v1"
    assert payload["snapshot_date"] == "2026-W19"
    assert len(payload["axes"]) == 12
    assert isinstance(payload["rows"], list)
    assert len(payload["rows"]) >= 12  # at least 1 signal/axis
    assert isinstance(payload["kpi_plots"], dict)
    assert len(payload["kpi_plots"]) == 5
    for key, series in payload["kpi_plots"].items():
        assert "/" in key
        assert isinstance(series, list)
        assert len(series) >= 1
        assert {"axis_id", "signal_id", "snapshot_date", "value", "status"} <= series[-1].keys()
    # Verify status values are within enum.
    for row in payload["rows"]:
        assert row["status"] in {"healthy", "degraded", "broken"}, row
    # Round-trip iso week parser.
    label, day = agg.parse_week_arg("2026-W19")
    assert label == "2026-W19"
    assert day.isocalendar().week == 19


# ---------------------------------------------------------------------------
# 4. 5 KPI plot data
# ---------------------------------------------------------------------------


def test_5_kpi_plot_data_series(tmp_path: Path) -> None:
    """collect_kpi_plots returns exactly 5 series with the expected (axis,signal) keys."""
    assert len(agg.KPI_PLOT_KEYS) == 5
    rows = [
        agg.SignalRow("IA-12", "self_vs_other_ratio", signal_value=0.55, status="healthy"),
        agg.SignalRow("IA-10", "v_cobb_douglas",   signal_value=1.1, status="healthy"),
        agg.SignalRow("IA-10", "lambda_max",       signal_value=0.02, status="healthy"),
        agg.SignalRow("IA-10", "cascade_q",        signal_value=0.06, status="healthy"),
        agg.SignalRow("IA-07", "pypi_downloads_weekly", signal_value=120.0, status="healthy"),
        # plus a non-KPI row to ensure filter works.
        agg.SignalRow("IA-01", "programs_count", signal_value=9000.0, status="healthy"),
    ]
    plots = agg.collect_kpi_plots(rows, current_week="2026-W19")
    assert len(plots) == 5
    keys = sorted(plots.keys())
    expected_keys = sorted(f"{a}/{s}" for a, s in agg.KPI_PLOT_KEYS)
    assert keys == expected_keys
    for series in plots.values():
        assert len(series) == 1
        latest = series[-1]
        assert latest["snapshot_date"] == "2026-W19"
        assert latest["value"] is not None
    # Missing KPI source -> series still present with value=None / status=broken.
    plots_missing = agg.collect_kpi_plots([], current_week="2026-W19")
    assert len(plots_missing) == 5
    for series in plots_missing.values():
        assert series[-1]["value"] is None
        assert series[-1]["status"] == "broken"


# ---------------------------------------------------------------------------
# 5. LLM API import = 0 (CI guard alignment)
# ---------------------------------------------------------------------------


def test_no_llm_api_imports() -> None:
    body = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden_modules = [
        r"^\s*import\s+anthropic\b",
        r"^\s*from\s+anthropic\b",
        r"^\s*import\s+openai\b",
        r"^\s*from\s+openai\b",
        r"^\s*import\s+google\.generativeai\b",
        r"^\s*from\s+google\.generativeai\b",
        r"^\s*import\s+claude_agent_sdk\b",
        r"^\s*from\s+claude_agent_sdk\b",
    ]
    for pattern in forbidden_modules:
        assert not re.search(pattern, body, flags=re.MULTILINE), pattern
    forbidden_envs = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]
    code_lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    code_text = "\n".join(code_lines)
    for env_var in forbidden_envs:
        assert env_var not in code_text, env_var
    # Template + workflow + migration should also be free of LLM env vars.
    for path in (TEMPLATE_PATH, WORKFLOW_PATH, MIGRATION_PATH):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for env_var in forbidden_envs:
            # workflow legitimately greps env names in a guard step; allow the
            # explicit "! grep" enforcement line.
            if env_var in text and path.suffix in {".yml", ".yaml"}:
                # Ensure the only occurrence is inside an enforcement grep.
                lines_with_env = [ln for ln in text.splitlines() if env_var in ln]
                for ln in lines_with_env:
                    assert "grep" in ln, f"unexpected env reference in {path.name}: {ln}"
            else:
                assert env_var not in text, f"{path.name} mentions {env_var}"
