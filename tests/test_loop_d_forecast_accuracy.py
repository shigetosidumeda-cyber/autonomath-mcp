"""Tests for loop_d_forecast_accuracy.

Covers the launch-v1 happy path: synthesised (predicted_prob, actual,
predicted_at) tuples feed the loop, which computes per-tool Brier / ECE,
flags drift on a deteriorating tool, and writes a JSON report.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jpintel_mcp.self_improve import loop_d_forecast_accuracy as loop_d

if TYPE_CHECKING:
    from pathlib import Path


def _fake_predictions() -> list[dict[str, object]]:
    """Two tools: one well-calibrated, one drifting badly in the new half.

    Tool `predict_next_amendment_window` (well-calibrated):
        12 rows, pred ≈ actual on average, no drift expected.

    Tool `predict_adoption_rate` (drift):
        10 old rows where pred matches actual, 10 new rows where pred is
        completely wrong (predicts 0.9, actual 0). New-half Brier should
        be ~0.81, old-half Brier ~0.0 -> drift_alert=True.

    Tool `predict_low_n` (low confidence):
        4 rows — under N_MEDIUM=10, surfaces with confidence=low.
    """
    rows: list[dict[str, object]] = []

    # Well-calibrated tool: pred=0.5 with exactly 50% actual=1, perfectly
    # split across the old/new halves. Each half: 6 rows, 3 actual=1.
    # Old-half Brier == new-half Brier == 0.25 -> drift delta = 0.0,
    # well under DRIFT_DELTA=0.05.
    for i in range(12):
        actual = 1 if (i % 2) == 0 else 0
        # Spread dates so half are < 03-15 (old) and half are >= 03-15 (new)
        day = (i % 6) + 1 if i < 6 else (i % 6) + 16
        rows.append(
            {
                "tool": "predict_next_amendment_window",
                "predicted_prob": 0.5,
                "actual": actual,
                "predicted_at": f"2026-03-{day:02d}",
            }
        )

    # Drifting tool: old half perfect, new half catastrophic.
    for i in range(10):
        rows.append(
            {
                "tool": "predict_adoption_rate",
                "predicted_prob": 0.1,
                "actual": 0,
                "predicted_at": f"2026-01-{(i % 28) + 1:02d}",
            }
        )
    for i in range(10):
        rows.append(
            {
                "tool": "predict_adoption_rate",
                "predicted_prob": 0.9,
                "actual": 0,  # totally wrong in the new half
                "predicted_at": f"2026-04-{(i % 28) + 1:02d}",
            }
        )

    # Low-N tool — kept in report but tagged low.
    for i in range(4):
        rows.append(
            {
                "tool": "predict_low_n",
                "predicted_prob": 0.5,
                "actual": 1,
                "predicted_at": f"2026-04-{(i % 28) + 1:02d}",
            }
        )

    # Contamination: bad rows that must be filtered.
    rows.extend(
        [
            {"tool": "", "predicted_prob": 0.5, "actual": 1},  # empty tool
            {"tool": "predict_low_n", "predicted_prob": 1.5, "actual": 1},  # OOR
            {"tool": "predict_low_n", "predicted_prob": 0.5, "actual": 5},  # bad y
            {"tool": "predict_low_n", "predicted_prob": "abc", "actual": 1},  # str
        ]
    )
    return rows


def test_loop_d_computes_brier_ece_and_drift(tmp_path: Path):
    out_path = tmp_path / "forecast_accuracy_report.json"
    rows = _fake_predictions()

    result = loop_d.run(
        dry_run=False,
        predictions=rows,
        out_path=out_path,
    )

    # Standard scaffold shape.
    assert result["loop"] == "loop_d_forecast_accuracy"
    assert result["scanned"] == len(rows)
    # Only `predict_adoption_rate` should drift (new-half Brier 0.81 vs
    # old-half 0.01). The other two stay quiet.
    assert result["actions_proposed"] == 1
    assert result["actions_executed"] == 1

    # Inspect the report directly.
    body = out_path.read_text(encoding="utf-8")
    report = json.loads(body)
    assert report["window_total"] == len(rows)
    tools_by_name = {t["tool"]: t for t in report["tools"]}

    # Three tools survive (empty-string tool dropped at summarize).
    assert set(tools_by_name) == {
        "predict_next_amendment_window",
        "predict_adoption_rate",
        "predict_low_n",
    }

    # Drifting tool: drift_alert True, new_brier > old_brier by > 0.05.
    drift = tools_by_name["predict_adoption_rate"]
    assert drift["drift_alert"] is True
    assert drift["n"] == 20
    assert drift["new_brier"] is not None and drift["old_brier"] is not None
    assert (drift["new_brier"] - drift["old_brier"]) > 0.05
    assert drift["confidence"] == "medium"  # 20 -> medium (10..29)

    # Well-calibrated tool: no drift, Brier should be reasonably small.
    calm = tools_by_name["predict_next_amendment_window"]
    assert calm["drift_alert"] is False
    assert calm["n"] == 12
    assert calm["brier"] < 0.30  # not a coin flip

    # Low-N tool: kept, but confidence='low' tells operator not to act.
    low = tools_by_name["predict_low_n"]
    assert low["confidence"] == "low"
    assert low["n"] == 4  # contamination filtered, only 4 valid rows


def test_loop_d_no_predictions_returns_zeroed_scaffold():
    """Pre-launch: orchestrator hasn't wired forecast_predictions yet."""
    out = loop_d.run(dry_run=True)
    assert out == {
        "loop": "loop_d_forecast_accuracy",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }


def test_loop_d_brier_and_ece_pure_helpers():
    """Sanity-check the math helpers in isolation."""
    # Perfect predictor.
    assert loop_d.compute_brier([(1.0, 1), (0.0, 0), (1.0, 1)]) == 0.0
    # Coin flip (0.5, 0) and (0.5, 1) -> 0.25 each -> mean 0.25.
    assert loop_d.compute_brier([(0.5, 0), (0.5, 1)]) == 0.25
    # ECE on a perfect predictor is 0.
    assert loop_d.compute_ece([(1.0, 1), (0.0, 0)]) == 0.0
    # ECE on systematically over-confident predictions > 0.
    biased = [(0.9, 0)] * 5 + [(0.9, 0)] * 5
    assert loop_d.compute_ece(biased) > 0.5
