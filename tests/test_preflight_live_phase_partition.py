"""Stream Q: tests for live_phase_only_assertion_ids partitioning.

When teardown_simulation.json declares ``live_phase_only_assertion_ids``,
the preflight runner must:

1. classify those assertions as ``preflight_excluded`` (not ``not_yet_verifiable``)
2. exclude them from the ``failed`` / ``not_yet_verifiable`` summary counters
3. surface a positive ``preflight_excluded`` counter
4. let ``all_passed`` reach True when every NON-excluded assertion PASSes
5. omit excluded assertion IDs from the persisted
   ``assertions_to_pass_state_true`` array when ``--apply`` flips pass_state
"""

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
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _seed_capsule(tmp_path: Path) -> Path:
    src = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
    dst = tmp_path / "rc1-p0-bootstrap"
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file() and p.suffix == ".json":
            (dst / p.name).write_bytes(p.read_bytes())
    sub = src / "agent_surface"
    if sub.exists():
        sub_dst = dst / "agent_surface"
        sub_dst.mkdir(exist_ok=True)
        for p in sub.iterdir():
            if p.is_file():
                (sub_dst / p.name).write_bytes(p.read_bytes())
    return dst


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_teardown_live_phase_only_partition_dry_run(tmp_path, runner):
    """With live_phase_only_assertion_ids declared, dry-run reports 16 PASS / 0 FAIL / 2 preflight_excluded."""

    capsule = _seed_capsule(tmp_path)
    teardown_path = capsule / "teardown_simulation.json"
    teardown = _load(teardown_path)
    teardown["live_phase_only_assertion_ids"] = [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    teardown["all_resources_have_delete_recipe"] = True
    teardown_path.write_text(json.dumps(teardown), encoding="utf-8")

    result = runner.run(apply=False, capsule_dir=capsule)
    summary = result["teardown_simulation"]["summary"]
    assert summary["total"] == 18
    assert summary["passed"] == 16
    assert summary["failed"] == 0
    assert summary["not_yet_verifiable"] == 0
    assert summary["preflight_excluded"] == 2
    assert summary["all_passed"] is True


def test_teardown_live_phase_only_apply_flips_pass_state(tmp_path, runner):
    """With live_phase_only declared and every non-excluded PASS, --apply flips pass_state True."""

    capsule = _seed_capsule(tmp_path)
    teardown_path = capsule / "teardown_simulation.json"
    teardown = _load(teardown_path)
    teardown["live_phase_only_assertion_ids"] = [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    teardown["all_resources_have_delete_recipe"] = True
    teardown["pass_state"] = False
    teardown_path.write_text(json.dumps(teardown), encoding="utf-8")

    runner.run(apply=True, capsule_dir=capsule)
    after = _load(teardown_path)
    assert after["pass_state"] is True
    assert after["pass_state_flip_authority"] == "preflight_runner"

    ids = after["assertions_to_pass_state_true"]
    assert "operator_signed_unlock_present" not in ids
    assert "run_id_tag_inventory_empty" not in ids
    assert len(ids) == 16


def test_teardown_no_live_phase_only_legacy_behaviour(tmp_path, runner):
    """Absent live_phase_only_assertion_ids, the 2 NV assertions still block flip."""

    capsule = _seed_capsule(tmp_path)
    teardown_path = capsule / "teardown_simulation.json"
    teardown = _load(teardown_path)
    teardown.pop("live_phase_only_assertion_ids", None)
    teardown["all_resources_have_delete_recipe"] = True
    teardown_path.write_text(json.dumps(teardown), encoding="utf-8")

    result = runner.run(apply=False, capsule_dir=capsule)
    summary = result["teardown_simulation"]["summary"]
    assert summary["not_yet_verifiable"] >= 2
    assert summary["preflight_excluded"] == 0
    assert summary["all_passed"] is False


def test_preflight_excluded_evidence_tag(tmp_path, runner):
    """Excluded assertions are reported with the canonical evidence prefix."""

    capsule = _seed_capsule(tmp_path)
    teardown_path = capsule / "teardown_simulation.json"
    teardown = _load(teardown_path)
    teardown["live_phase_only_assertion_ids"] = [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    teardown_path.write_text(json.dumps(teardown), encoding="utf-8")

    result = runner.run(apply=False, capsule_dir=capsule)
    excluded = [r for r in result["teardown_simulation"]["results"] if r.get("preflight_excluded")]
    assert len(excluded) == 2
    for r in excluded:
        assert r["evidence"].startswith("preflight_excluded:")
        assert r["passed"] is False
        assert r["verifiable_today"] is False
