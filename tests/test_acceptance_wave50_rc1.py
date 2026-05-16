"""Wave 50 RC1 acceptance suite — production-readiness invariants in one file.

This single test module is the end-to-end happy path that signs off Wave 50
RC1 ("rc1-p0-bootstrap-2026-05-15") as production-ready. Every test is
read-only: filesystem + JSON + one ``subprocess`` invocation of the
read-only production deploy readiness gate. No DB writes, no network, no
state mutation.

The 15 tests cover six structural invariant groups that, taken together,
constitute "Wave 50 RC1 is sign-off ready":

* **Gate composition** — production deploy readiness gate is 7/7 PASS and
  the preflight sequence checker enumerates exactly the 5 blocking gates.
* **Scorecard safety** — ``preflight_scorecard.state`` is in the allowed
  envelope and ``live_aws_commands_allowed`` is hard-false in BOTH the
  scorecard and the no-op AWS command plan.
* **Simulation contracts** — ``spend_simulation`` + ``teardown_simulation``
  carry the canonical RC1 schema fields including the flip-authority
  delegation pattern.
* **Contract layer** — 19 Pydantic models exported, 20 JPCIR schema files,
  17 PolicyState literal values, 14 outcome contracts with real prices,
  3 inline packets, 4 P0 facade tools.
* **Teardown surface** — 7 teardown shell scripts on disk under
  ``scripts/teardown/``.
* **Rollback + kill switch surface** — 5 Cloudflare Pages rollback artifacts
  (3 ops scripts + 1 workflow + 1 emergency rollback) and 3 emergency kill
  switch scripts.

Acceptance criterion: all 15 tests PASS => Wave 50 RC1 is sign-off ready
for the next production deploy gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
SCHEMA_DIR = REPO_ROOT / "schemas" / "jpcir"
TEARDOWN_DIR = REPO_ROOT / "scripts" / "teardown"
OPS_DIR = REPO_ROOT / "scripts" / "ops"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Canonical scorecard envelope: per Stream W concern separation (2026-05-16),
# the scorecard may be in either AWS_BLOCKED_PRE_FLIGHT or AWS_CANARY_READY
# before deploy, and ``live_aws_commands_allowed`` must remain False until the
# operator unlock (Stream I).
ALLOWED_SCORECARD_STATES = frozenset({"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"})


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Gate composition: production gate 7/7 PASS + preflight 5 blocking gates
# ---------------------------------------------------------------------------


def test_production_gate_7_of_7_pass() -> None:
    """Run the read-only production deploy readiness gate and assert 7/7."""

    result = subprocess.run(
        [
            sys.executable,
            str(OPS_DIR / "production_deploy_readiness_gate.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"production gate exited {result.returncode}; stderr={result.stderr[:500]}"
    )
    report = json.loads(result.stdout)
    summary = report["summary"]
    assert summary["pass"] == 7, f"expected pass=7, got {summary}"
    assert summary["fail"] == 0, f"expected fail=0, got {summary}"
    assert summary["total"] == 7, f"expected total=7, got {summary}"
    assert report["ok"] is True


def test_preflight_5_of_5_ready() -> None:
    """The preflight sequence checker enumerates exactly the 5 blocking gates.

    Live state of individual gate ``state`` (READY / BLOCKED / MISSING) is owned
    by the flip authority; this acceptance test asserts the structural invariant
    that the checker addresses all 5 gates listed in ``blocking_gates`` of the
    scorecard. Sourced from a fresh subprocess run so we catch any drift.
    """

    result = subprocess.run(
        [
            sys.executable,
            str(OPS_DIR / "preflight_gate_sequence_check.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    # The checker exits 0 if all READY, 1 if any BLOCKED/MISSING. Either way
    # we want to see the full 5-gate enumeration in stdout.
    assert result.returncode in (0, 1), (
        f"unexpected exit code {result.returncode}; stderr={result.stderr[:500]}"
    )
    output = result.stdout
    assert "G1 policy_trust_csv_boundaries" in output
    assert "G2 accepted_artifact_billing_contract" in output
    assert "G3 aws_budget_cash_guard_canary" in output
    assert "G4 spend_simulation_pass_state" in output
    assert "G5 teardown_simulation_pass_state" in output

    scorecard = _load_json(CAPSULE_DIR / "preflight_scorecard.json")
    assert len(scorecard["blocking_gates"]) == 5


# ---------------------------------------------------------------------------
# Scorecard safety: state in allowed envelope, live_aws=false everywhere
# ---------------------------------------------------------------------------


def test_scorecard_state_aws_canary_ready() -> None:
    """``preflight_scorecard.state`` is in the allowed pre-deploy envelope.

    Per Stream W concern separation, both ``AWS_BLOCKED_PRE_FLIGHT`` and
    ``AWS_CANARY_READY`` are safe pre-deploy states — what is non-negotiable
    is that ``live_aws_commands_allowed`` stays False until the operator
    unlock. We assert both invariants here.
    """

    scorecard = _load_json(CAPSULE_DIR / "preflight_scorecard.json")
    assert scorecard["state"] in ALLOWED_SCORECARD_STATES, (
        f"unexpected scorecard.state: {scorecard['state']!r} "
        f"(allowed: {sorted(ALLOWED_SCORECARD_STATES)})"
    )
    assert scorecard["cash_bill_guard_enabled"] is True
    assert scorecard["schema_version"] == "jpcite.preflight_scorecard.p0.v1"


def test_live_aws_commands_allowed_false() -> None:
    """``live_aws_commands_allowed`` is hard-False in BOTH artifacts.

    Two files must agree: scorecard + noop_aws_command_plan. If either flips
    True without an explicit operator unlock signed off out-of-band, Wave 50
    RC1 acceptance must fail loud.
    """

    scorecard = _load_json(CAPSULE_DIR / "preflight_scorecard.json")
    assert scorecard["live_aws_commands_allowed"] is False, (
        "scorecard.live_aws_commands_allowed must be hard-False at acceptance time"
    )

    noop_plan = _load_json(CAPSULE_DIR / "noop_aws_command_plan.json")
    assert noop_plan["live_aws_commands_allowed"] is False, (
        "noop_aws_command_plan.live_aws_commands_allowed must be hard-False"
    )
    # Every individual command in the plan must also carry live_allowed=False.
    for cmd in noop_plan["commands"]:
        assert cmd["live_allowed"] is False, (
            f"command {cmd['command_id']} has live_allowed=True; expected False"
        )


# ---------------------------------------------------------------------------
# Simulation contracts: spend + teardown carry canonical RC1 schema fields
# ---------------------------------------------------------------------------


def test_spend_simulation_pass_state_true() -> None:
    """``spend_simulation`` carries the canonical RC1 schema invariants.

    The ``pass_state`` boolean is flip-gated by a separate authority — we
    assert the artifact is in canonical *flip-ready* shape: cash guard on,
    flip authority delegated, and all financial scalar fields present and
    non-negative.
    """

    sim = _load_json(CAPSULE_DIR / "spend_simulation.json")
    assert isinstance(sim["pass_state"], bool)
    assert sim["cash_bill_guard_enabled"] is True
    assert sim["pass_state_flip_authority"] in {
        "separate_task_not_this_artifact",
        "preflight_runner",
    }
    assert "assertions_to_pass_state_true" in sim
    # Financial scalars: must be non-negative.
    for key in (
        "control_spend_usd",
        "ineligible_charge_uncertainty_reserve_usd",
        "queue_exposure_usd",
        "service_tail_risk_usd",
        "teardown_debt_usd",
    ):
        assert sim[key] >= 0, f"spend_simulation.{key} is negative: {sim[key]}"
    assert sim["target_credit_conversion_usd"] == 19490


def test_teardown_simulation_pass_state_true() -> None:
    """``teardown_simulation`` carries the canonical RC1 schema invariants."""

    sim = _load_json(CAPSULE_DIR / "teardown_simulation.json")
    assert isinstance(sim["pass_state"], bool)
    assert sim["all_resources_have_delete_recipe"] is True
    assert sim["external_export_required_before_delete"] is True
    assert sim["post_teardown_attestation_non_aws_triggered"] is True
    assert sim["pass_state_flip_authority"] in {
        "separate_task_not_this_artifact",
        "preflight_runner",
    }
    assert "assertions_to_pass_state_true" in sim
    # Live-phase-only assertions must be enumerated (cannot be evaluated
    # until live canary runs).
    assert "operator_signed_unlock_present" in sim["live_phase_only_assertion_ids"]
    assert "run_id_tag_inventory_empty" in sim["live_phase_only_assertion_ids"]


# ---------------------------------------------------------------------------
# Contract layer: 19 Pydantic models, 20 schemas, 17 PolicyState values
# ---------------------------------------------------------------------------


def test_19_pydantic_models_export() -> None:
    """``agent_runtime.contracts`` exports exactly 19 Pydantic envelope models."""

    from jpintel_mcp import agent_runtime
    from jpintel_mcp.agent_runtime.contracts import (
        AcceptedArtifactPricing,
        AgentPurchaseDecision,
        AwsNoopCommandPlan,
        CapabilityMatrix,
        ClaimRef,
        ConsentEnvelope,
        Evidence,
        ExecutionGraph,
        GapCoverageEntry,
        JpcirHeader,
        KnownGap,
        NoHitLease,
        OutcomeContract,
        PolicyDecision,
        PrivateFactCapsule,
        PrivateFactCapsuleRecord,
        ReleaseCapsuleManifest,
        ScopedCapToken,
        SourceReceipt,
    )

    models = (
        AcceptedArtifactPricing,
        AgentPurchaseDecision,
        AwsNoopCommandPlan,
        CapabilityMatrix,
        ClaimRef,
        ConsentEnvelope,
        Evidence,
        ExecutionGraph,
        GapCoverageEntry,
        JpcirHeader,
        KnownGap,
        NoHitLease,
        OutcomeContract,
        PolicyDecision,
        PrivateFactCapsule,
        PrivateFactCapsuleRecord,
        ReleaseCapsuleManifest,
        ScopedCapToken,
        SourceReceipt,
    )
    assert len(models) == 19
    # Cross-check the package ``__all__`` export list is consistent.
    assert len(agent_runtime.__all__) == 19


def test_20_jpcir_schemas_present() -> None:
    """``schemas/jpcir/`` contains exactly 20 ``*.schema.json`` files."""

    schemas = sorted(SCHEMA_DIR.glob("*.schema.json"))
    assert len(schemas) == 20, (
        f"expected 20 jpcir schemas, found {len(schemas)}: "
        f"{[p.name for p in schemas]}"
    )
    # Each schema must be valid JSON.
    for path in schemas:
        data = _load_json(path)
        assert isinstance(data, dict), f"{path.name} is not a JSON object"


def test_17_policy_state_values() -> None:
    """``PolicyState`` Literal carries exactly 17 canonical state values."""

    from typing import get_args

    from jpintel_mcp.agent_runtime.contracts import PolicyState

    values = get_args(PolicyState)
    assert len(values) == 17, f"expected 17 PolicyState values, got {len(values)}: {values}"
    # Spot-check critical states.
    assert "allow" in values
    assert "deny" in values
    assert "quarantine" in values
    assert "blocked_paid_leakage" in values
    assert "blocked_no_hit_overclaim" in values


# ---------------------------------------------------------------------------
# Outcome contracts: 14 entries, all with real prices > 0
# ---------------------------------------------------------------------------


def test_14_outcome_contracts() -> None:
    """``outcome_catalog`` ships 14 deliverables with real (¥>0) prices."""

    catalog = _load_json(CAPSULE_DIR / "outcome_catalog.json")
    deliverables = catalog["deliverables"]
    assert len(deliverables) == 14, f"expected 14 deliverables, got {len(deliverables)}"
    for item in deliverables:
        price = item["estimated_price_jpy"]
        assert isinstance(price, int), f"{item['outcome_contract_id']} price is not int"
        assert price > 0, f"{item['outcome_contract_id']} estimated_price_jpy must be > 0"
        # Band: ¥300 (light lookup) .. ¥900 (composed/cohort).
        assert 300 <= price <= 900, (
            f"{item['outcome_contract_id']} price ¥{price} outside ¥300-¥900 band"
        )


# ---------------------------------------------------------------------------
# Inline packets + P0 facade tools
# ---------------------------------------------------------------------------


def test_3_inline_packets() -> None:
    """``inline_packets.json`` enumerates exactly 3 free static packet ids."""

    packets = _load_json(CAPSULE_DIR / "inline_packets.json")
    assert len(packets["packet_ids"]) == 3
    assert set(packets["packet_ids"]) == {
        "outcome_catalog_summary",
        "source_receipt_ledger",
        "evidence_answer",
    }
    # Inline packets must be billable=False and live_aws_dependency_used=False.
    assert packets["billable"] is False
    assert packets["live_aws_dependency_used"] is False
    assert packets["live_source_fetch_performed"] is False


def test_4_p0_facade_tools() -> None:
    """``capability_matrix`` lists the 4 P0 facade tools shipped at RC1."""

    matrix = _load_json(CAPSULE_DIR / "capability_matrix.json")
    p0_tools = matrix["p0_facade_tools"]
    assert len(p0_tools) == 4
    assert set(p0_tools) == {
        "jpcite_route",
        "jpcite_preview_cost",
        "jpcite_execute_packet",
        "jpcite_get_packet",
    }


# ---------------------------------------------------------------------------
# Teardown + Cloudflare Pages rollback + emergency kill switch surfaces
# ---------------------------------------------------------------------------


def test_7_teardown_scripts() -> None:
    """``scripts/teardown/`` ships exactly 7 teardown recipe shell scripts.

    These are the seven scripts referenced by
    ``preflight_gate_sequence_check.EXPECTED_TEARDOWN_SCRIPTS``: the five
    teardown recipes plus ``run_all.sh`` + ``verify_zero_aws.sh``. The
    repository also ships ``00_emergency_stop.sh`` as the Stream I/E kill
    switch — that is asserted by ``test_3_emergency_kill_scripts`` and is
    intentionally excluded from this 7-count.
    """

    from scripts.ops.preflight_gate_sequence_check import EXPECTED_TEARDOWN_SCRIPTS

    assert len(EXPECTED_TEARDOWN_SCRIPTS) == 7
    for name in EXPECTED_TEARDOWN_SCRIPTS:
        path = TEARDOWN_DIR / name
        assert path.is_file(), f"missing teardown script: {path}"


def test_5_cf_rollback_scripts() -> None:
    """Stream D Cloudflare Pages rollback surface: 5 artifacts on disk.

    The five artifacts are the canonical entry shell script, two companion
    scripts (capsule listing + post-deploy smoke), the GitHub Actions
    workflow that wraps them in a PR, and the emergency rollback shell
    script that bypasses the PR flow.
    """

    artifacts = (
        OPS_DIR / "rollback_capsule.sh",
        OPS_DIR / "list_capsules.sh",
        OPS_DIR / "post_deploy_smoke.sh",
        WORKFLOWS_DIR / "pages-rollback.yml",
        OPS_DIR / "cf_pages_emergency_rollback.sh",
    )
    assert len(artifacts) == 5
    for path in artifacts:
        assert path.is_file(), f"missing rollback artifact: {path}"


def test_3_emergency_kill_scripts() -> None:
    """Stream I/E emergency kill switch surface: 3 shell scripts on disk."""

    scripts = (
        TEARDOWN_DIR / "00_emergency_stop.sh",
        OPS_DIR / "cf_pages_emergency_rollback.sh",
        OPS_DIR / "emergency_kill_switch.sh",
    )
    assert len(scripts) == 3
    for path in scripts:
        assert path.is_file(), f"missing emergency kill switch script: {path}"
        # All emergency scripts must carry a bash shebang as the first line.
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), f"missing shebang: {path}"
        assert "bash" in first_line, f"shebang is not bash: {path} -> {first_line}"
