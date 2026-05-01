"""Smoke tests for sdk/github-action/action.yml.

Pure offline checks (feedback_autonomath_no_api_use): we never hit the live
API from CI. Only validate the action manifest's YAML, required keys,
description-length budgets, and example workflow shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_DIR = REPO_ROOT / "sdk" / "github-action"
ACTION_YML = ACTION_DIR / "action.yml"
EXAMPLE_WF = ACTION_DIR / "example" / ".github" / "workflows" / "check-subsidies.yml"


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --- action.yml --------------------------------------------------------------


def test_action_yml_exists() -> None:
    assert ACTION_YML.is_file(), "sdk/github-action/action.yml is missing"


def test_action_yml_parses() -> None:
    data = _load(ACTION_YML)
    assert isinstance(data, dict), "action.yml must parse to a mapping"


def test_action_yml_required_top_keys() -> None:
    data = _load(ACTION_YML)
    for key in ("name", "description", "runs", "inputs", "outputs"):
        assert key in data, f"action.yml missing top-level key: {key}"


def test_action_yml_is_composite() -> None:
    data = _load(ACTION_YML)
    assert data["runs"]["using"] == "composite", \
        "must be a composite action (no Docker / no JS bundle)"
    steps = data["runs"]["steps"]
    assert isinstance(steps, list) and steps, "composite action needs >=1 step"
    # constraint: keep entrypoint trivial — only shell steps allowed
    for step in steps:
        assert "shell" in step, f"composite step missing 'shell': {step}"


def test_action_description_length_budget() -> None:
    """GitHub Marketplace truncates >125-char descriptions on tiles.

    Keep the headline tight so the marketplace card stays legible.
    """
    data = _load(ACTION_YML)
    desc = data["description"]
    assert isinstance(desc, str)
    assert 20 <= len(desc) <= 125, \
        f"description must be 20-125 chars (Marketplace tile budget); got {len(desc)}"


def test_action_inputs_contract() -> None:
    data = _load(ACTION_YML)
    inputs = data["inputs"]
    assert "api_key" in inputs, "input 'api_key' missing"
    assert "query" in inputs, "input 'query' missing"
    assert "endpoint" in inputs, "input 'endpoint' missing"
    # query must be required, api_key must NOT be required (anon-tier path)
    assert inputs["query"].get("required") is True
    assert inputs["api_key"].get("required") in (False, None)
    # endpoint must default to programs/search
    assert inputs["endpoint"].get("default") == "programs/search"


def test_action_outputs_contract() -> None:
    data = _load(ACTION_YML)
    outputs = data["outputs"]
    for key in ("result", "count", "http_status"):
        assert key in outputs, f"output '{key}' missing"
        assert "value" in outputs[key], f"output '{key}' missing 'value' wiring"


def test_action_branding_present() -> None:
    """Marketplace listings require icon + color in branding."""
    data = _load(ACTION_YML)
    branding = data.get("branding")
    assert isinstance(branding, dict), "branding block required for Marketplace"
    assert branding.get("icon")
    assert branding.get("color")


def test_action_no_llm_imports() -> None:
    """feedback_autonomath_no_api_use: action must not call any LLM provider."""
    text = ACTION_YML.read_text(encoding="utf-8")
    forbidden = ("anthropic", "openai", "gemini.googleapis", "claude.ai/api")
    for token in forbidden:
        assert token not in text.lower(), \
            f"action.yml must not reference LLM provider: {token}"


# --- example workflow --------------------------------------------------------


def test_example_workflow_exists() -> None:
    assert EXAMPLE_WF.is_file(), \
        "example/.github/workflows/check-subsidies.yml missing"


def test_example_workflow_parses() -> None:
    data = _load(EXAMPLE_WF)
    assert isinstance(data, dict)


def test_example_workflow_uses_action() -> None:
    data = _load(EXAMPLE_WF)
    jobs = data.get("jobs") or {}
    assert jobs, "example workflow has no jobs"
    found = False
    for job in jobs.values():
        for step in job.get("steps", []):
            uses = step.get("uses", "")
            if uses.startswith("bookyou/jpcite-action@"):
                found = True
                with_blk = step.get("with") or {}
                assert "query" in with_blk, \
                    "example workflow must set 'query' input"
    assert found, "example workflow does not reference bookyou/jpcite-action"


# --- LICENSE / README presence ----------------------------------------------


def test_license_and_readme_exist() -> None:
    assert (ACTION_DIR / "LICENSE").is_file()
    assert (ACTION_DIR / "README.md").is_file()


def test_readme_has_5_step_section() -> None:
    text = (ACTION_DIR / "README.md").read_text(encoding="utf-8")
    assert "5-step" in text or "5 step" in text, \
        "README must include a 5-step usage section"
    # check the bookyou/jpcite-action handle is documented
    assert "bookyou/jpcite-action" in text


# --- pytest collection sanity ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [ACTION_YML, EXAMPLE_WF],
)
def test_yaml_files_round_trip(path: Path) -> None:
    """Re-dumping must not raise; catches subtle indentation bugs."""
    data = _load(path)
    yaml.safe_dump(data)
