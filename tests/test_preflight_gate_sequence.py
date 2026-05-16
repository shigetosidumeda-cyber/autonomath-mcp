"""Tests for ``scripts/ops/preflight_gate_sequence_check.py``.

The checker is read-only; we exercise it against the live repo capsule
(``site/releases/rc1-p0-bootstrap``) for sanity, and against a mock capsule
directory that we mutate per-scenario to flip individual gates between
``READY``, ``BLOCKED``, and ``MISSING`` deterministically.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.preflight_gate_sequence_check import (
    EXPECTED_GUARDS,
    EXPECTED_OUTCOMES,
    EXPECTED_TEARDOWN_SCRIPTS,
    GateResult,
    _check_accepted_artifact_billing_contract,
    _check_aws_budget_cash_guard_canary,
    _check_policy_trust_csv_boundaries,
    _check_spend_simulation_pass_state,
    _check_teardown_simulation_pass_state,
    run_sequence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
SCHEMA_DIR = REPO_ROOT / "schemas" / "jpcir"
TEARDOWN_DIR = REPO_ROOT / "scripts" / "teardown"


@pytest.fixture()
def mock_capsule(tmp_path: Path) -> Path:
    """Clone the real capsule directory into ``tmp_path`` so we can mutate freely."""

    dst = tmp_path / "capsule"
    dst.mkdir()
    for name in (
        "policy_decision_catalog.json",
        "csv_private_overlay_contract.json",
        "billing_event_ledger_schema.json",
        "accepted_artifact_pricing.json",
        "aws_budget_canary_attestation.json",
        "spend_simulation.json",
        "teardown_simulation.json",
    ):
        shutil.copy(REAL_CAPSULE_DIR / name, dst / name)
    return dst


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_capsule_runs_without_exceptions() -> None:
    """Smoke test against the actual repo capsule. We do not assert on which
    gates are READY/BLOCKED — the live state is owned by the deploy capsule
    and changes over time. We only assert the checker produces five results
    and never crashes."""

    results = run_sequence()
    assert len(results) == 5
    expected_ids = [
        "policy_trust_csv_boundaries",
        "accepted_artifact_billing_contract",
        "aws_budget_cash_guard_canary",
        "spend_simulation_pass_state",
        "teardown_simulation_pass_state",
    ]
    assert [r.gate_id for r in results] == expected_ids
    for r in results:
        assert isinstance(r, GateResult)
        assert r.state in {"READY", "BLOCKED", "MISSING"}


def test_g1_ready_with_real_capsule(mock_capsule: Path) -> None:
    res = _check_policy_trust_csv_boundaries(mock_capsule)
    assert res.state == "READY", res.blockers + res.missing_artifacts
    assert res.evidence["policy_entries"] >= 1
    assert res.evidence["csv_provider_rules"] >= 1


def test_g1_missing_when_artifact_absent(mock_capsule: Path) -> None:
    (mock_capsule / "policy_decision_catalog.json").unlink()
    res = _check_policy_trust_csv_boundaries(mock_capsule)
    assert res.state == "MISSING"
    assert "policy_decision_catalog.json" in res.missing_artifacts


def test_g1_blocked_when_csv_sent_to_aws(mock_capsule: Path) -> None:
    csv_path = mock_capsule / "csv_private_overlay_contract.json"
    payload = _read_json(csv_path)
    payload["global_contract"]["raw_csv_sent_to_aws"] = True
    _write_json(csv_path, payload)
    res = _check_policy_trust_csv_boundaries(mock_capsule)
    assert res.state == "BLOCKED"
    assert any("raw_csv_sent_to_aws" in b for b in res.blockers)


def test_g2_ready_with_real_capsule(mock_capsule: Path) -> None:
    res = _check_accepted_artifact_billing_contract(mock_capsule)
    assert res.state == "READY", res.blockers + res.missing_artifacts
    assert res.evidence["deliverable_pricing_rules"] == 14


def test_g2_blocked_when_outcome_missing(mock_capsule: Path) -> None:
    pricing_path = mock_capsule / "accepted_artifact_pricing.json"
    payload = _read_json(pricing_path)
    payload["deliverable_pricing_rules"] = payload["deliverable_pricing_rules"][:5]
    _write_json(pricing_path, payload)
    res = _check_accepted_artifact_billing_contract(mock_capsule)
    assert res.state == "BLOCKED"
    assert any("missing outcome_contract pricing rules" in b for b in res.blockers)


def test_g2_blocked_when_price_zero(mock_capsule: Path) -> None:
    pricing_path = mock_capsule / "accepted_artifact_pricing.json"
    payload = _read_json(pricing_path)
    payload["deliverable_pricing_rules"][0]["estimated_price_jpy"] = 0
    _write_json(pricing_path, payload)
    res = _check_accepted_artifact_billing_contract(mock_capsule)
    assert res.state == "BLOCKED"
    assert any("estimated_price_jpy" in b for b in res.blockers)


def test_g3_ready_with_real_capsule(mock_capsule: Path) -> None:
    res = _check_aws_budget_cash_guard_canary(mock_capsule)
    assert res.state == "READY", res.blockers + res.missing_artifacts
    assert set(res.evidence["guard_ids"]) == set(EXPECTED_GUARDS)


def test_g3_blocked_when_guard_missing(mock_capsule: Path) -> None:
    att_path = mock_capsule / "aws_budget_canary_attestation.json"
    payload = _read_json(att_path)
    payload["guards"] = payload["guards"][:2]
    _write_json(att_path, payload)
    res = _check_aws_budget_cash_guard_canary(mock_capsule)
    assert res.state == "BLOCKED"
    assert any("missing guards" in b for b in res.blockers)


def test_g3_blocked_when_live_unlock_true(mock_capsule: Path) -> None:
    att_path = mock_capsule / "aws_budget_canary_attestation.json"
    payload = _read_json(att_path)
    payload["live_aws_command_unlock"] = True
    _write_json(att_path, payload)
    res = _check_aws_budget_cash_guard_canary(mock_capsule)
    assert res.state == "BLOCKED"
    assert any("live_aws_command_unlock" in b for b in res.blockers)


def test_g4_blocked_by_default_pass_state_false(mock_capsule: Path) -> None:
    # The live capsule may have spend_simulation.pass_state flipped to True by
    # the preflight runner. To exercise the legacy "blocked when False" path
    # we reset pass_state in the temporary fixture.
    spend_path = mock_capsule / "spend_simulation.json"
    payload = _read_json(spend_path)
    payload["pass_state"] = False
    payload["assertions_to_pass_state_true"] = []
    payload["pass_state_flip_authority"] = "separate_task_not_this_artifact"
    _write_json(spend_path, payload)
    res = _check_spend_simulation_pass_state(mock_capsule, SCHEMA_DIR)
    assert res.state == "BLOCKED"
    assert res.evidence["pass_state"] is False


def test_g4_ready_when_pass_state_true_with_assertions(mock_capsule: Path) -> None:
    spend_path = mock_capsule / "spend_simulation.json"
    payload = _read_json(spend_path)
    payload["pass_state"] = True
    payload["assertions_to_pass_state_true"] = [
        "control_spend_within_budget",
        "queue_exposure_acceptable",
        "service_tail_risk_capped",
    ]
    _write_json(spend_path, payload)
    res = _check_spend_simulation_pass_state(mock_capsule, SCHEMA_DIR)
    assert res.state == "READY", res.blockers
    assert res.evidence["pass_state"] is True


def test_g5_blocked_by_default_pass_state_false(mock_capsule: Path) -> None:
    # The live capsule may have teardown_simulation.pass_state flipped to True by
    # the preflight runner. To exercise the legacy "blocked when False" path
    # we reset pass_state in the temporary fixture.
    teardown_path = mock_capsule / "teardown_simulation.json"
    payload = _read_json(teardown_path)
    payload["pass_state"] = False
    payload["assertions_to_pass_state_true"] = []
    payload["pass_state_flip_authority"] = "separate_task_not_this_artifact"
    # Stream R schema sync: live_phase_only_assertion_ids must round-trip
    # through the BLOCKED path without affecting the legacy contract.
    payload["live_phase_only_assertion_ids"] = [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    _write_json(teardown_path, payload)
    res = _check_teardown_simulation_pass_state(mock_capsule, SCHEMA_DIR, TEARDOWN_DIR)
    assert res.state == "BLOCKED"
    assert res.evidence["pass_state"] is False
    assert set(res.evidence["teardown_scripts_present"]) == set(EXPECTED_TEARDOWN_SCRIPTS)


def test_g5_ready_when_pass_state_true_and_scripts_present(mock_capsule: Path) -> None:
    teardown_path = mock_capsule / "teardown_simulation.json"
    payload = _read_json(teardown_path)
    payload["pass_state"] = True
    payload["all_resources_have_delete_recipe"] = True
    payload["assertions_to_pass_state_true"] = [
        "delete_recipe_for_each_resource",
        "external_export_completed_before_delete",
    ]
    # Stream R schema sync: assertions that are only evaluable during the AWS
    # canary live phase are classified as preflight_excluded by the runner so
    # they must not keep pass_state at False during the preflight window.
    payload["live_phase_only_assertion_ids"] = [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    _write_json(teardown_path, payload)
    # Sanity round-trip: artifact retains the new schema field exactly as
    # written, with no field deletion or coercion by the checker harness.
    written = _read_json(teardown_path)
    assert written["live_phase_only_assertion_ids"] == [
        "operator_signed_unlock_present",
        "run_id_tag_inventory_empty",
    ]
    res = _check_teardown_simulation_pass_state(mock_capsule, SCHEMA_DIR, TEARDOWN_DIR)
    assert res.state == "READY", res.blockers


def test_g5_blocked_when_teardown_script_missing(mock_capsule: Path, tmp_path: Path) -> None:
    fake_teardown = tmp_path / "fake_teardown"
    fake_teardown.mkdir()
    # Only create 3 of the 7 expected scripts.
    for name in EXPECTED_TEARDOWN_SCRIPTS[:3]:
        (fake_teardown / name).write_text("#!/bin/bash\n", encoding="utf-8")

    teardown_path = mock_capsule / "teardown_simulation.json"
    payload = _read_json(teardown_path)
    payload["pass_state"] = True
    payload["all_resources_have_delete_recipe"] = True
    payload["assertions_to_pass_state_true"] = ["delete_recipe_for_each_resource"]
    _write_json(teardown_path, payload)

    res = _check_teardown_simulation_pass_state(mock_capsule, SCHEMA_DIR, fake_teardown)
    assert res.state == "BLOCKED"
    assert any("missing teardown scripts" in b for b in res.blockers)


def test_expected_outcomes_count_is_14() -> None:
    """Pin the outcome-contract count so accidental schema drift fails fast."""

    assert len(EXPECTED_OUTCOMES) == 14


def test_expected_teardown_scripts_count_is_7() -> None:
    assert len(EXPECTED_TEARDOWN_SCRIPTS) == 7
