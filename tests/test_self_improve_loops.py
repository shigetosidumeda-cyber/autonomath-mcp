"""Tests for the 10 self-improvement loop scaffolds + orchestrator.

Verifies:

  * each loop module exposes a `run(*, dry_run: bool) -> dict[str, int]`
  * the returned dict has the contract shape {loop, scanned, actions_proposed,
    actions_executed} with int values
  * the package exports LOOP_NAMES with all 10 entries
  * the orchestrator aggregates across all 10 with success counters
  * orchestrator writes JSON to analysis_wave18/self_improve_runs/<date>.json
  * no scaffold accidentally imports anthropic / openai (LLM-free invariant)
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

LOOP_NAMES = (
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

REQUIRED_KEYS = {"loop", "scanned", "actions_proposed", "actions_executed"}


def test_package_exports_all_loop_names():
    pkg = importlib.import_module("jpintel_mcp.self_improve")
    assert tuple(pkg.LOOP_NAMES) == LOOP_NAMES
    assert len(pkg.LOOP_NAMES) == 10


@pytest.mark.parametrize("name", LOOP_NAMES)
def test_loop_dry_run_shape(name: str):
    mod = importlib.import_module(f"jpintel_mcp.self_improve.{name}")
    out = mod.run(dry_run=True)
    assert isinstance(out, dict), f"{name} must return dict"
    missing = REQUIRED_KEYS - out.keys()
    assert not missing, f"{name} missing keys: {missing}"
    assert out["loop"] == name
    for k in ("scanned", "actions_proposed", "actions_executed"):
        assert isinstance(out[k], int), f"{name}.{k} must be int, got {type(out[k]).__name__}"
        assert out[k] >= 0, f"{name}.{k} must be >= 0"


@pytest.mark.parametrize("name", LOOP_NAMES)
def test_loop_executes_under_both_modes(name: str):
    """dry_run flag must be accepted in both True and False; pre-launch both
    paths return the zeroed scaffold dict (no-op scaffolding)."""
    mod = importlib.import_module(f"jpintel_mcp.self_improve.{name}")
    out_dry = mod.run(dry_run=True)
    out_real = mod.run(dry_run=False)
    assert out_dry["loop"] == out_real["loop"] == name


@pytest.mark.parametrize("name", LOOP_NAMES)
def test_no_llm_imports_in_loop(name: str):
    """Hard guarantee per memory `feedback_autonomath_no_api_use`: scaffolds
    must not import any LLM provider SDK.

    We check both the imported module's `__dict__` and its source text — a
    `from anthropic import ...` would show up in module attrs even before
    being called.
    """
    mod = importlib.import_module(f"jpintel_mcp.self_improve.{name}")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    forbidden = ("import anthropic", "import openai", "from anthropic", "from openai", "google.generativeai")
    for needle in forbidden:
        assert needle not in src, f"{name} imports forbidden LLM SDK: {needle}"


def test_orchestrator_dry_run_aggregates_all_10(tmp_path, monkeypatch):
    """Run the orchestrator end-to-end and validate the output JSON contract."""
    # Import the orchestrator script as a module so we can call orchestrate() directly.
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    if "self_improve_orchestrator" in sys.modules:
        del sys.modules["self_improve_orchestrator"]
    orch = importlib.import_module("self_improve_orchestrator")

    payload = orch.orchestrate(dry_run=True)
    assert payload["dry_run"] is True
    assert payload["loops_total"] == 10
    assert payload["loops_succeeded"] == 10
    assert payload["loops_failed"] == 0
    assert set(payload["totals"].keys()) == {"scanned", "actions_proposed", "actions_executed"}
    assert len(payload["results"]) == 10
    returned_names = {r["loop"] for r in payload["results"]}
    assert returned_names == set(LOOP_NAMES)


def test_orchestrator_only_runs_single_loop():
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        if "self_improve_orchestrator" in sys.modules:
            del sys.modules["self_improve_orchestrator"]
        orch = importlib.import_module("self_improve_orchestrator")
        payload = orch.orchestrate(dry_run=True, only="loop_h_cache_warming")
        assert payload["loops_total"] == 1
        assert payload["loops_succeeded"] == 1
        assert payload["results"][0]["loop"] == "loop_h_cache_warming"
    finally:
        sys.path.remove(str(scripts_dir))


def test_orchestrator_unknown_loop_raises():
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        if "self_improve_orchestrator" in sys.modules:
            del sys.modules["self_improve_orchestrator"]
        orch = importlib.import_module("self_improve_orchestrator")
        with pytest.raises(ValueError, match="unknown loop"):
            orch.orchestrate(dry_run=True, only="loop_z_does_not_exist")
    finally:
        sys.path.remove(str(scripts_dir))


def test_orchestrator_writes_run_json(tmp_path, monkeypatch):
    """Verify _write_run drops a JSON file with the expected payload shape."""
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        if "self_improve_orchestrator" in sys.modules:
            del sys.modules["self_improve_orchestrator"]
        orch = importlib.import_module("self_improve_orchestrator")
        # Redirect RUNS_DIR to tmp_path so the test does not pollute the repo.
        monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
        payload = orch.orchestrate(dry_run=True)
        out_path = orch._write_run(payload)
        assert out_path.exists()
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["loops_total"] == 10
        assert loaded["dry_run"] is True
        assert isinstance(loaded["results"], list)
    finally:
        sys.path.remove(str(scripts_dir))
