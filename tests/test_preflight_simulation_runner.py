"""Tests for scripts/ops/run_preflight_simulations.py (Stream A flip runner)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "ops" / "run_preflight_simulations.py"


def _load_runner():
    name = "run_preflight_simulations"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses needs cls.__module__ resolvable
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _seed_capsule(tmp_path: Path) -> Path:
    """Copy the live rc1-p0-bootstrap capsule into a temp dir so tests can mutate it.

    Resets the scorecard back to the canonical pre-promote shape (state =
    AWS_BLOCKED_PRE_FLIGHT, live_aws_commands_allowed = false) and the two
    simulation artifacts back to pass_state = false so that test assertions
    are deterministic regardless of the live capsule's current state.
    """

    src = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
    dst = tmp_path / "rc1-p0-bootstrap"
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file() and p.suffix == ".json":
            (dst / p.name).write_bytes(p.read_bytes())
    # agent_surface subdir is referenced indirectly; the runner does not read
    # it but the contract checker does — copy if present.
    sub = src / "agent_surface"
    if sub.exists():
        sub_dst = dst / "agent_surface"
        sub_dst.mkdir(exist_ok=True)
        for p in sub.iterdir():
            if p.is_file():
                (sub_dst / p.name).write_bytes(p.read_bytes())

    scorecard_path = dst / "preflight_scorecard.json"
    if scorecard_path.exists():
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        scorecard["state"] = "AWS_BLOCKED_PRE_FLIGHT"
        scorecard["live_aws_commands_allowed"] = False
        for transient_key in (
            "scorecard_promote_authority",
            "unlock_authority",
            "unlocked_at",
        ):
            scorecard.pop(transient_key, None)
        scorecard_path.write_text(
            json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for sim_name in ("spend_simulation.json", "teardown_simulation.json"):
        sim_path = dst / sim_name
        if sim_path.exists():
            sim = json.loads(sim_path.read_text(encoding="utf-8"))
            sim["pass_state"] = False
            sim_path.write_text(
                json.dumps(sim, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return dst


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_dry_run_does_not_mutate(tmp_path, runner):
    capsule = _seed_capsule(tmp_path)
    before_spend = _load(capsule / "spend_simulation.json")
    before_teardown = _load(capsule / "teardown_simulation.json")

    result = runner.run(apply=False, capsule_dir=capsule)
    assert result["mode"] == "dry-run"

    after_spend = _load(capsule / "spend_simulation.json")
    after_teardown = _load(capsule / "teardown_simulation.json")
    assert before_spend == after_spend
    assert before_teardown == after_teardown


def test_dry_run_reports_assertions(tmp_path, runner):
    capsule = _seed_capsule(tmp_path)
    result = runner.run(apply=False, capsule_dir=capsule)
    assert result["spend_simulation"]["summary"]["total"] == 22
    assert result["teardown_simulation"]["summary"]["total"] == 18
    # Both simulations should report ``all_passed`` consistently with their
    # current state. The live capsule is allowed to be fully PASS (Stream Q
    # established the canonical 16 PASS + 2 preflight_excluded partition for
    # teardown). When that is the case, the report flags it; otherwise it
    # surfaces the failing assertion IDs.
    assert isinstance(result["spend_simulation"]["summary"]["all_passed"], bool)
    assert isinstance(result["teardown_simulation"]["summary"]["all_passed"], bool)


def test_apply_writes_when_all_pass(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    # Force every assertion to PASS by stubbing the registries.
    pass_assertion = runner.Assertion(
        assertion_id="forced_pass",
        description="forced pass for test",
        check=lambda c: (True, "forced"),
    )

    monkeypatch.setattr(runner, "_spend_assertions", lambda: [pass_assertion] * 22)
    monkeypatch.setattr(runner, "_teardown_assertions", lambda: [pass_assertion] * 18)

    result = runner.run(apply=True, capsule_dir=capsule)
    after_spend = _load(capsule / "spend_simulation.json")
    after_teardown = _load(capsule / "teardown_simulation.json")
    assert after_spend["pass_state"] is True
    assert after_teardown["pass_state"] is True
    assert after_spend["pass_state_flip_authority"] == "preflight_runner"
    assert after_teardown["pass_state_flip_authority"] == "preflight_runner"
    assert len(after_spend["assertions_to_pass_state_true"]) == 22
    assert len(after_teardown["assertions_to_pass_state_true"]) == 18
    assert result["spend_simulation"]["summary"]["all_passed"] is True
    assert result["teardown_simulation"]["summary"]["all_passed"] is True


def test_apply_idempotent(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    pass_assertion = runner.Assertion(
        assertion_id="forced_pass",
        description="forced",
        check=lambda c: (True, "forced"),
    )
    monkeypatch.setattr(runner, "_spend_assertions", lambda: [pass_assertion] * 22)
    monkeypatch.setattr(runner, "_teardown_assertions", lambda: [pass_assertion] * 18)

    runner.run(apply=True, capsule_dir=capsule)
    first_spend = _load(capsule / "spend_simulation.json")
    first_teardown = _load(capsule / "teardown_simulation.json")

    runner.run(apply=True, capsule_dir=capsule)
    second_spend = _load(capsule / "spend_simulation.json")
    second_teardown = _load(capsule / "teardown_simulation.json")

    assert first_spend == second_spend
    assert first_teardown == second_teardown


def test_partial_failure_keeps_pass_state_false(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    pass_a = runner.Assertion(
        assertion_id="forced_pass",
        description="forced pass",
        check=lambda c: (True, "ok"),
    )
    fail_a = runner.Assertion(
        assertion_id="forced_fail",
        description="forced fail",
        check=lambda c: (False, "nope"),
    )
    spend_list = [pass_a] * 21 + [fail_a]
    teardown_list = [pass_a] * 17 + [fail_a]
    monkeypatch.setattr(runner, "_spend_assertions", lambda: spend_list)
    monkeypatch.setattr(runner, "_teardown_assertions", lambda: teardown_list)

    result = runner.run(apply=True, capsule_dir=capsule)
    after_spend = _load(capsule / "spend_simulation.json")
    after_teardown = _load(capsule / "teardown_simulation.json")
    assert after_spend["pass_state"] is False
    assert after_teardown["pass_state"] is False
    assert result["spend_simulation"]["summary"]["all_passed"] is False
    assert result["teardown_simulation"]["summary"]["all_passed"] is False


def test_scorecard_not_promoted_without_flag(tmp_path, runner, monkeypatch):
    capsule = _seed_capsule(tmp_path)
    pass_a = runner.Assertion(
        assertion_id="forced_pass",
        description="forced",
        check=lambda c: (True, "ok"),
    )
    monkeypatch.setattr(runner, "_spend_assertions", lambda: [pass_a] * 22)
    monkeypatch.setattr(runner, "_teardown_assertions", lambda: [pass_a] * 18)
    runner.run(apply=True, capsule_dir=capsule)
    scorecard = _load(capsule / "preflight_scorecard.json")
    # Without --promote-scorecard the scorecard state must NOT change.
    assert scorecard["state"] == "AWS_BLOCKED_PRE_FLIGHT"


def test_not_yet_verifiable_assertions_block_flip(tmp_path, runner):
    capsule = _seed_capsule(tmp_path)
    # Real registry includes 2 teardown assertions marked verifiable_today=False
    # for live-phase. When the artifact does NOT declare them as
    # live_phase_only, they remain not_yet_verifiable and therefore keep
    # teardown pass_state at False. We strip live_phase_only_assertion_ids to
    # exercise that legacy path.
    teardown_path = capsule / "teardown_simulation.json"
    teardown = json.loads(teardown_path.read_text(encoding="utf-8"))
    teardown.pop("live_phase_only_assertion_ids", None)
    teardown_path.write_text(json.dumps(teardown), encoding="utf-8")

    result = runner.run(apply=False, capsule_dir=capsule)
    nv = result["teardown_simulation"]["summary"]["not_yet_verifiable"]
    assert nv >= 2
    assert result["teardown_simulation"]["summary"]["all_passed"] is False
