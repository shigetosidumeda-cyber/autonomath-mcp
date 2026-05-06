"""Lock-in test: all 10 self-improve loops are wired into the orchestrator.

Per `project_jpintel_1000h_plan` P3.1.5 the weekly cron must run every
self-improvement loop, not just loop_a. This test guards three regressions:

    1. The orchestrator's LOOPS tuple matches the package-level LOOP_NAMES.
    2. Every loop name resolves to an importable module exposing `run`.
    3. The .github/workflows/self-improve-weekly.yml workflow file invokes
       the orchestrator with `--all` (i.e. it sweeps every loop) and runs
       under the protected `30 0 * * 1` cron (Mon 09:30 JST).
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH_PATH = REPO_ROOT / "scripts" / "self_improve_orchestrator.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "self-improve-weekly.yml"


def _load_orchestrator():
    spec = importlib.util.spec_from_file_location("self_improve_orchestrator", ORCH_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_ten_loops_discovered_and_wired_to_weekly_cron() -> None:
    from jpintel_mcp.self_improve import LOOP_NAMES

    # 1. Orchestrator's loop tuple must match the package's authoritative list.
    orch = _load_orchestrator()
    assert orch.LOOPS == LOOP_NAMES, (
        "scripts/self_improve_orchestrator.LOOPS drifted from "
        "jpintel_mcp.self_improve.LOOP_NAMES — re-sync before launch"
    )
    assert len(orch.LOOPS) == 10, f"expected exactly 10 self-improve loops, got {len(orch.LOOPS)}"

    # 2. Each loop is importable and exposes the expected run() callable.
    for name in orch.LOOPS:
        mod = importlib.import_module(f"jpintel_mcp.self_improve.{name}")
        assert hasattr(mod, "run"), f"{name} missing run()"
        assert callable(mod.run), f"{name}.run is not callable"

    # 3. Workflow file invokes the orchestrator with --all and the
    #    protected Mon 09:30 JST schedule.
    wf = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/self_improve_orchestrator.py --all" in wf, (
        "self-improve-weekly.yml must invoke the orchestrator with --all "
        "so every loop runs sequentially (P3.1.5)"
    )
    assert "30 0 * * 1" in wf, (
        "self-improve-weekly.yml cron schedule drifted from Mon 00:30 UTC "
        "(= Mon 09:30 JST). Memory: launch cron must stay protected."
    )
    # Sanity: --no-write keeps it proposal-only until T+30d real-mode flip.
    assert "--no-write" in wf, (
        "self-improve-weekly.yml must keep --no-write until T+30d to avoid "
        "premature side effects on production tables"
    )
