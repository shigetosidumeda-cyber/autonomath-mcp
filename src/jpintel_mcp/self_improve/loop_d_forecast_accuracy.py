"""Loop D: industry trend -> forecast accuracy calibration.

Cadence: monthly (15th of month, 09:00 JST)
Inputs: `am_application_round` (1,256 rows of historical adoption data),
        `programs` (program metadata + budget),
        `forecast_predictions` (our own prior predictions; M3-degraded
        heuristic such as `predict_next_amendment_window` — pure rule, no
        ML, no Bayesian per CONSTITUTION 13.2)
Outputs: `data/forecast_accuracy_report.json` — per-tool Brier score, ECE
        (Expected Calibration Error), drift_alert flag. Operator review
        artefact only; the live tool keeps serving its current prediction
        regardless. NO new predictions written; NO calibration weights
        auto-promoted (loop_d only *measures*, the operator decides
        whether to retire / re-tune the heuristic).
Cost ceiling: ~3 CPU minutes / month, ≤ 100k row scans, 0 external API calls,
              0 LLM calls (pure numpy-free numeric — math.fsum + bucketing).

Method (T+30d):
  1. Pull (tool, predicted_prob, actual_outcome, predicted_at) tuples from
     the orchestrator-supplied corpus. The schema sketch is:
         tool             str    -- e.g. "predict_next_amendment_window"
         predicted_prob   float  -- in [0, 1] (the heuristic's confidence)
         actual           int    -- 0 / 1 (did the predicted event occur?)
         predicted_at     str    -- YYYY-MM-DD; used for drift bucketing
     Production wiring will pull this from a `forecast_predictions` table
     once it exists; pre-launch this stays an injectable kwarg so tests +
     orchestrator can pass synthetic rows.
  2. Per-tool Brier score: mean((p - actual)^2). Lower is better; 0.0 is
     perfect, 0.25 is a coin flip, 1.0 is maximally wrong.
  3. Per-tool ECE with 10 equal-width probability bins on [0, 1]: weighted
     average over bins of |mean_predicted - mean_actual| × (bin_size /
     total). Pure stdlib, no scikit-learn (per launch dep budget).
  4. Drift detection: split per-tool corpus into "old" (older than median
     `predicted_at`) and "new" (newer half). Compute Brier on each half;
     if `new_brier - old_brier > DRIFT_DELTA` (default 0.05), raise
     `drift_alert=True`. Operator alert is the JSON file landing in the
     review queue — no email / SMS / paging.
  5. Emit `data/forecast_accuracy_report.json` with shape:
        {
          "computed_at": "2026-04-25T...",
          "window_total": int,
          "tools": [
            {
              "tool": "...",
              "n": int,
              "brier": float,
              "ece": float,
              "drift_alert": bool,
              "old_brier": float | null,
              "new_brier": float | null,
              "confidence": "high" | "medium" | "low"
            },
            ...
          ]
        }
     Confidence mirrors loop_a / loop_g: n >= 30 -> high, 10..29 -> medium,
     < 10 -> low. Below 10 we still emit the row (operator may still want
     the signal) but the confidence label tells them not to act yet.

LLM use: NONE. Pure math.fsum + dict bucketing.

Memory note: AutonoMath is `feedback_action_bias` + `feedback_no_fake_data`
— this loop measures how trustworthy our heuristic predictions actually
are, so the operator can retire ones that drift. The output is
*informational only* — never auto-promotes calibration weights, never
silences a tool. Per `feedback_autonomath_no_api_use` we never call the
Anthropic API from inside this loop.

Launch v1 (this module):
    Provides `compute_brier`, `compute_ece`, `summarize_tool`,
    `write_report_json`, and a `run()` that accepts an optional
    `predictions` kwarg so tests can inject fixtures without spinning up
    a real `forecast_predictions` table. When callers pass nothing,
    `run()` returns the zeroed scaffold — same posture as loop_a /
    loop_b / loop_e / loop_g.

Cron wiring is intentionally out-of-scope (handled by
`scripts/self_improve_orchestrator.py`).
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Repo layout: src/jpintel_mcp/self_improve/loop_d_forecast_accuracy.py
# climb four parents to reach the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "data" / "forecast_accuracy_report.json"

# Calibration bin count for ECE. Ten equal-width bins on [0, 1] is the
# Naeini et al. (2015) convention; smaller buckets exaggerate noise on
# small N, larger buckets erase miscalibration.
ECE_BINS = 10

# Brier delta beyond which we raise `drift_alert=True`. 0.05 is half the
# distance between "perfect" (0.0) and "coin flip" (0.25), conservative
# enough that small samples don't trip it but cheap enough to catch real
# regressions on the monthly cadence.
DRIFT_DELTA = 0.05

# Confidence thresholds — kept in sync with loop_b / loop_g (≥5 ≈ high).
# Brier / ECE need more samples to stabilize than hit-counters, so we use
# a higher floor: 30 = high, 10..29 = medium, < 10 = low.
N_HIGH = 30
N_MEDIUM = 10


def _coerce_pred(p: Any) -> float | None:
    """Coerce a predicted probability to float in [0, 1]. None on failure."""
    try:
        x = float(p)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    if x < 0.0 or x > 1.0:
        return None
    return x


def _coerce_actual(a: Any) -> int | None:
    """Coerce an actual outcome to {0, 1}. None on failure."""
    try:
        x = int(a)
    except (TypeError, ValueError):
        return None
    if x not in (0, 1):
        return None
    return x


def compute_brier(pairs: list[tuple[float, int]]) -> float:
    """Mean-squared error between predicted_prob and actual outcome.

    Brier = mean((p - y)^2). Pure function. Returns 0.0 for empty input
    (caller should branch on n=0 *before* calling — this is a safety net,
    not a meaningful score).
    """
    if not pairs:
        return 0.0
    return math.fsum((p - y) ** 2 for p, y in pairs) / len(pairs)


def compute_ece(pairs: list[tuple[float, int]], *, bins: int = ECE_BINS) -> float:
    """Expected Calibration Error with `bins` equal-width buckets on [0,1].

    ECE = sum_b (|B_b| / N) * |mean_pred(B_b) - mean_actual(B_b)|

    Pure function. Returns 0.0 for empty input (same safety-net posture
    as compute_brier).
    """
    if not pairs:
        return 0.0
    n = len(pairs)
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in pairs:
        # Edge case: p == 1.0 lands in the final bin, not bins+1.
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, y))
    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        mean_p = math.fsum(p for p, _ in bucket) / len(bucket)
        mean_y = math.fsum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(mean_p - mean_y)
    return ece


def _confidence_label(n: int) -> str:
    if n >= N_HIGH:
        return "high"
    if n >= N_MEDIUM:
        return "medium"
    return "low"


def summarize_tool(
    tool: str, rows: list[dict[str, Any]], *, drift_delta: float = DRIFT_DELTA
) -> dict[str, Any]:
    """Compute Brier / ECE / drift summary for a single tool.

    Args:
        tool: tool label (purely informational, copied through).
        rows: list of dicts each carrying predicted_prob / actual /
            predicted_at. Bad rows (out-of-range probs, non-binary actuals)
            are filtered out *before* the math runs.
        drift_delta: Brier-delta threshold for the drift alert.

    Pure function: no I/O.
    """
    pairs: list[tuple[float, int, str | None]] = []
    for r in rows:
        p = _coerce_pred(r.get("predicted_prob"))
        y = _coerce_actual(r.get("actual"))
        if p is None or y is None:
            continue
        ts = r.get("predicted_at")
        ts_str = ts if isinstance(ts, str) else None
        pairs.append((p, y, ts_str))

    n = len(pairs)
    if n == 0:
        return {
            "tool": tool,
            "n": 0,
            "brier": None,
            "ece": None,
            "drift_alert": False,
            "old_brier": None,
            "new_brier": None,
            "confidence": "low",
        }

    py_pairs = [(p, y) for p, y, _ in pairs]
    brier = compute_brier(py_pairs)
    ece = compute_ece(py_pairs)

    # Drift: split on median predicted_at. Rows missing predicted_at are
    # excluded from the drift split (we will not invent a timestamp). If
    # fewer than 6 timestamped rows survive, drift is not computable —
    # leave old/new None and drift_alert False.
    timestamped = [(p, y, ts) for p, y, ts in pairs if ts is not None]
    drift_alert = False
    old_brier: float | None = None
    new_brier: float | None = None
    if len(timestamped) >= 6:
        timestamped.sort(key=lambda t: t[2])  # ts string compare = lexical date
        median_idx = len(timestamped) // 2
        old_pairs = [(p, y) for p, y, _ in timestamped[:median_idx]]
        new_pairs = [(p, y) for p, y, _ in timestamped[median_idx:]]
        old_brier = compute_brier(old_pairs)
        new_brier = compute_brier(new_pairs)
        if (new_brier - old_brier) > drift_delta:
            drift_alert = True

    return {
        "tool": tool,
        "n": n,
        "brier": round(brier, 6),
        "ece": round(ece, 6),
        "drift_alert": drift_alert,
        "old_brier": None if old_brier is None else round(old_brier, 6),
        "new_brier": None if new_brier is None else round(new_brier, 6),
        "confidence": _confidence_label(n),
    }


def summarize(
    predictions: list[dict[str, Any]], *, drift_delta: float = DRIFT_DELTA
) -> dict[str, Any]:
    """Group predictions by tool and produce the full report dict.

    Pure function: no I/O.
    """
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in predictions:
        tool = r.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        by_tool[tool.strip()].append(r)

    tool_summaries = [
        summarize_tool(t, rows, drift_delta=drift_delta)
        for t, rows in sorted(by_tool.items())
    ]
    return {
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window_total": len(predictions),
        "tools": tool_summaries,
    }


def write_report_json(report: dict[str, Any], path: Path) -> int:
    """Write report JSON. Returns bytes written."""
    body = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n", encoding="utf-8")
    return len((body + "\n").encode("utf-8"))


def run(
    *,
    dry_run: bool = True,
    predictions: list[dict[str, Any]] | None = None,
    out_path: Path | None = None,
    drift_delta: float = DRIFT_DELTA,
) -> dict[str, int]:
    """Score forecast predictions and emit the operator review report.

    Args:
        dry_run: When True, do not write `forecast_accuracy_report.json` —
            still compute Brier / ECE / drift, still report
            `actions_proposed`. Same contract as loop_a / loop_b / loop_g.
        predictions: Optional injection of (tool, predicted_prob, actual,
            predicted_at) rows. When None, the function returns the zeroed
            scaffold — production wiring (read from `forecast_predictions`)
            lives in the orchestrator, keeping this module dependency-free
            for tests.
        out_path: Override for the JSON output path. Defaults to
            `data/forecast_accuracy_report.json`.
        drift_delta: Override the Brier-delta drift threshold (default
            0.05).

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.

        - `actions_proposed` counts *tool summaries with drift_alert=True*.
          That is the operator-actionable signal — a non-drift summary is
          informational, drift means "consider retiring this heuristic".
        - `actions_executed` counts the JSON write (0 / 1).
    """
    out_p = out_path if out_path is not None else REPORT_PATH

    if not predictions:
        # Pre-launch / orchestrator hasn't wired forecast_predictions yet —
        # keep the dashboard green. Same posture as loop_a's empty-YAML.
        return {
            "loop": "loop_d_forecast_accuracy",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    report = summarize(predictions, drift_delta=drift_delta)
    proposed = sum(1 for t in report["tools"] if t["drift_alert"])

    actions_executed = 0
    if not dry_run and report["tools"]:
        write_report_json(report, out_p)
        actions_executed = 1

    return {
        "loop": "loop_d_forecast_accuracy",
        "scanned": len(predictions),
        "actions_proposed": proposed,
        "actions_executed": actions_executed,
    }


# Re-export for symmetry with statistics import (silences ruff F401 if any
# downstream needs the median fn — currently we use string-sort for ts
# bucketing which is robust without datetime parsing).
_ = statistics

if __name__ == "__main__":
    print(json.dumps(run(dry_run=True)))
