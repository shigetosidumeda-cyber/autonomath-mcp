"""Tests for Wave 46 §G — scripts/audit/check_lane_policy.py.

Covers:
- single-lane (no collision): rc=0, summary text marks lane as ok
- duplicate-lane collision (>=2 active locks): rc=0, output contains 'warn:'
- unknown / unparseable branch: rc=0 default, rc=2 with --strict
"""

from __future__ import annotations

import csv
import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit" / "check_lane_policy.py"

# load the module by file path (script not on sys.path by default)
_spec = importlib.util.spec_from_file_location("check_lane_policy", SCRIPT)
assert _spec is not None and _spec.loader is not None
clp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clp)


LEDGER_HEADER = [
    "agent_run_id",
    "timestamp_utc",
    "session",
    "lane",
    "write_paths",
    "violation_count",
    "override_reason",
    "operator_signoff",
]


def _write_ledger(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LEDGER_HEADER)
        for r in rows:
            w.writerow([r.get(c, "") for c in LEDGER_HEADER])


def _row(lane: str, run_id: str = "abc", violation_count: str = "0") -> dict[str, str]:
    return {
        "agent_run_id": run_id,
        "timestamp_utc": "2026-05-12T00:00:00Z",
        "session": "test",
        "lane": lane,
        "write_paths": "tools/offline/_inbox/x",
        "violation_count": violation_count,
        "override_reason": "",
        "operator_signoff": "",
    }


def test_branch_parse_simple() -> None:
    assert clp.parse_lane_from_branch("feat/jpcite_2026_05_12_wave46_ams_w43_bench") == "ams"
    assert (
        clp.parse_lane_from_branch("feat/jpcite_2026_05_12_wave46_rename_46g_lane_policy")
        == "rename"
    )


def test_branch_parse_compound_wave() -> None:
    # wave43_5 (two-segment) must still resolve lane
    assert clp.parse_lane_from_branch("feat/jpcite_2026_05_12_wave43_5_ams_monthly_cron") == "ams"


def test_branch_parse_unparseable() -> None:
    assert clp.parse_lane_from_branch("main") is None
    assert clp.parse_lane_from_branch("") is None
    assert clp.parse_lane_from_branch("feat/random-thing") is None


def test_single_lane_no_collision(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "AGENT_LEDGER.csv"
    _write_ledger(ledger, [_row("ams"), _row("dim19")])
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(
        [
            "--branch",
            "feat/jpcite_2026_05_12_wave46_ams_w43_bench",
            "--ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "lane: `ams`" in out
    assert "active locks for `ams`: **1**" in out
    assert "warn:" not in out


def test_duplicate_lane_warn(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "AGENT_LEDGER.csv"
    # 3 active locks for 'ams' -> collision
    _write_ledger(
        ledger,
        [
            _row("ams", run_id="r1"),
            _row("ams", run_id="r2"),
            _row("ams", run_id="r3"),
            _row("dim19", run_id="r4"),
        ],
    )
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(
        [
            "--branch",
            "feat/jpcite_2026_05_12_wave46_ams_collide_demo",
            "--ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0  # non-blocking
    assert "warn:" in out
    assert "lane `ams` has 3 active locks" in out
    assert "this PR" in out


def test_unparseable_branch_default_rc0(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "AGENT_LEDGER.csv"
    _write_ledger(ledger, [])
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(["--branch", "release/something-else", "--ledger", str(ledger)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unparseable" in out


def test_unparseable_branch_strict_rc2(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "AGENT_LEDGER.csv"
    _write_ledger(ledger, [])
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(["--branch", "release/x", "--ledger", str(ledger), "--strict"])
    assert rc == 2


def test_missing_ledger_treated_empty(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "does_not_exist.csv"
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(
        [
            "--branch",
            "feat/jpcite_2026_05_12_wave46_dim19_BOPQ",
            "--ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    # rows=0 path -> "first lane claim"
    assert "first lane claim" in out


def test_violation_rows_excluded(tmp_path: pathlib.Path, capsys) -> None:
    """A row with violation_count > 0 must NOT count toward active locks."""
    ledger = tmp_path / "AGENT_LEDGER.csv"
    _write_ledger(
        ledger,
        [
            _row("ams", run_id="ok"),
            _row("ams", run_id="bad", violation_count="3"),  # not counted
        ],
    )
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    rc = clp.main(
        [
            "--branch",
            "feat/jpcite_2026_05_12_wave46_ams_x",
            "--ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "active locks for `ams`: **1**" in out


def test_summarize_lanes_counter() -> None:
    rows = [_row("ams"), _row("ams"), _row("dim19"), _row("rename")]
    c = clp.summarize_lanes(rows)
    assert c["ams"] == 2
    assert c["dim19"] == 1
    assert c["rename"] == 1


def test_github_step_summary_path(tmp_path: pathlib.Path, monkeypatch) -> None:
    """When $GITHUB_STEP_SUMMARY is set, output appends there."""
    ledger = tmp_path / "AGENT_LEDGER.csv"
    _write_ledger(ledger, [_row("ams")])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = clp.main(
        [
            "--branch",
            "feat/jpcite_2026_05_12_wave46_ams_x",
            "--ledger",
            str(ledger),
        ]
    )
    assert rc == 0
    assert summary.exists()
    body = summary.read_text(encoding="utf-8")
    assert "lane: `ams`" in body


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))
