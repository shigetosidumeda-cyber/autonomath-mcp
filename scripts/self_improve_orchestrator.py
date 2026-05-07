#!/usr/bin/env python3
"""Self-improvement orchestrator (P5-eta+).

Runs the 10 closed-loop pipelines in `jpintel_mcp.self_improve.*` in a fixed
order, aggregates per-loop JSON output, and writes one combined run record
to `analysis_wave18/self_improve_runs/<YYYY-MM-DD>.json` per invocation.

Cadence
-------
The orchestrator itself is invoked by cron at the *finest* schedule needed
(daily 03:30 JST today, just for Loop H — cache warming). Each loop owns
its own internal cadence by reading `should_run_today()` from a small
schedule check (T+30d). Pre-launch this just runs all 10 loops in dry_run.

Operator review
---------------
Default mode is `--dry-run`. No production write occurs unless the operator
re-runs with `--execute`. Even then the loop bodies are still scaffolding
(real ML wiring lands T+30d).

Usage
-----

    python scripts/self_improve_orchestrator.py             # dry-run all 10
    python scripts/self_improve_orchestrator.py --all       # explicit all-10 run
    python scripts/self_improve_orchestrator.py --execute   # operator-approved real run
    python scripts/self_improve_orchestrator.py --only loop_h_cache_warming  # single loop
    python scripts/self_improve_orchestrator.py --loop loop_h_cache_warming  # alias for --only
    python scripts/self_improve_orchestrator.py --no-write  # proposal-only, no JSON dump

Output JSON shape
-----------------
    {
      "ts": "2026-04-25T12:34:56+09:00",
      "dry_run": true,
      "loops_total": 10,
      "loops_succeeded": 10,
      "loops_failed": 0,
      "totals": {"scanned": 0, "actions_proposed": 0, "actions_executed": 0},
      "results": [{"loop": "...", "scanned": 0, ...}, ...]
    }

LLM use: NONE. Per `feedback_autonomath_no_api_use`, this orchestrator and
all 10 loops MUST stay LLM-free. Our ¥3/req economics break instantly if
self-improvement burns API tokens.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "analysis_wave18" / "self_improve_runs"

LOOPS: tuple[str, ...] = (
    "loop_a_hallucination_guard",
    "loop_b_testimonial_seo",
    "loop_c_personalized_cache",
    "loop_d_forecast_accuracy",
    "loop_e_alias_expansion",
    "loop_f_channel_roi",
    "loop_g_invariant_expansion",
    "loop_h_cache_warming",
    "loop_i_doc_freshness",
    "loop_j_gold_expansion",
)

JST = timezone(__import__("datetime").timedelta(hours=9), name="JST")


def _now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _run_one(name: str, dry_run: bool) -> dict[str, Any]:
    mod = importlib.import_module(f"jpintel_mcp.self_improve.{name}")
    # Loop H needs the compute_factories injection — without it the loop
    # short-circuits to the zeroed scaffold (`if not factories` branch in
    # loop_h_cache_warming.run). Build the {l4_tool_name: callable(params)}
    # map from the live API helpers so the warmer can rebuild bodies for
    # the Zipf-head queries. Other loops use the unparameterised contract.
    if name == "loop_h_cache_warming":
        from jpintel_mcp.self_improve._compute_factories import (
            build_compute_factories,
        )

        return mod.run(
            dry_run=dry_run,
            compute_factories=build_compute_factories(),
        )
    return mod.run(dry_run=dry_run)


def orchestrate(*, dry_run: bool, only: str | None = None) -> dict[str, Any]:
    selected = (only,) if only else LOOPS
    if only and only not in LOOPS:
        raise ValueError(f"unknown loop: {only!r}; expected one of {LOOPS}")

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    totals = {"scanned": 0, "actions_proposed": 0, "actions_executed": 0}
    for name in selected:
        try:
            r = _run_one(name, dry_run=dry_run)
            results.append(r)
            succeeded += 1
            for k in totals:
                totals[k] += int(r.get(k, 0))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append(
                {
                    "loop": name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=4),
                }
            )

    return {
        "ts": _now_jst_iso(),
        "dry_run": dry_run,
        "loops_total": len(selected),
        "loops_succeeded": succeeded,
        "loops_failed": failed,
        "totals": totals,
        "results": results,
    }


def _write_run(payload: dict[str, Any]) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now(JST).strftime("%Y-%m-%d")
    out = RUNS_DIR / f"{date_part}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run loops with dry_run=False (default is dry-run for safety).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Run a single loop by module name (e.g. loop_h_cache_warming).",
    )
    parser.add_argument(
        "--loop",
        type=str,
        default=None,
        dest="loop",
        help="Alias for --only. Run a single loop by module name.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Explicit flag to run all 10 self-improve loops sequentially "
            "(default behaviour when neither --only nor --loop is set)."
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Skip writing the run JSON to analysis_wave18/self_improve_runs/.",
    )
    args = parser.parse_args(argv)

    selected = args.only or args.loop
    if args.all and selected:
        parser.error("--all cannot be combined with --only / --loop")

    payload = orchestrate(dry_run=not args.execute, only=selected)

    if not args.no_write:
        out = _write_run(payload)
        payload["_written_to"] = str(out)

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["loops_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
