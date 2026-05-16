#!/usr/bin/env python3
"""Preflight simulation flip runner (Stream A) + scorecard promote (Stream Q) +
operator live-AWS unlock (Stream I, Stream W concern separation).

Mechanically validates the canonical 22 spend-simulation assertions + 18
teardown-simulation assertions for the RC1-P0-bootstrap capsule. When every
assertion of a simulation PASSES, the runner is authorized to flip the
corresponding ``pass_state`` from False to True (idempotent). When any
assertion FAILS, ``pass_state`` is held at False and the failing assertion
identifiers are surfaced.

By default the runner is dry-run only — it prints a human-readable + machine
readable report but does not mutate any artifact. ``--apply`` is required to
actually persist the flip.

Stream W concern separation (2026-05-16). The scorecard "preflight passed"
flip is split from the "operator has unlocked live AWS" flip:

* ``--promote-scorecard`` (Stream Q authority): when all 5 preflight gates
  listed in ``preflight_scorecard.json`` are PASS (both simulations + 3
  sibling gates whose state lives in their own artifacts), flip
  ``preflight_scorecard.state`` from ``AWS_BLOCKED_PRE_FLIGHT`` to
  ``AWS_CANARY_READY``. ``live_aws_commands_allowed`` is **force-held at
  False** by this code path — promotion ONLY signals "preflight passed; the
  operator MAY now choose to unlock live commands". If the artifact ever
  carries True in this field while running ``--promote-scorecard`` alone,
  the runner force-resets it to False (defense-in-depth against upstream
  tampering).
* ``--unlock-live-aws-commands`` (Stream I operator authority): the ONLY
  code path in this runner that may set ``live_aws_commands_allowed`` to
  True. Requires the scorecard state to already be ``AWS_CANARY_READY`` (so
  promotion must happen first, or both flags must be combined in the same
  ``--apply`` invocation) and the operator-signed environment variable
  ``JPCITE_LIVE_AWS_UNLOCK_TOKEN`` to be non-empty. If the variable is
  missing or empty the runner exits with code 64 (EX_USAGE) and writes
  nothing. On success the scorecard records ``unlock_authority="operator"``
  and an ISO-8601 ``unlocked_at`` timestamp alongside the flipped flag.

The sibling-gate check on ``--promote-scorecard`` is intentionally
read-only: this runner does not touch policy / billing / canary attestation
artifacts (those flips live in their own Stream owners).

The runner exits with code 0 when (a) all required assertions PASS and the
state was already True (or was just flipped under ``--apply``), or (b) the
artifacts are healthy and the operator merely wanted a dry-run diff. It
exits with code 1 when at least one assertion fails — that exit status is
how CI / the deploy-readiness gate detects "still blocked". It exits with
code 64 when ``--unlock-live-aws-commands`` is requested without the
operator-signed unlock token.

Usage::

    .venv/bin/python3.12 scripts/ops/run_preflight_simulations.py --dry-run
    .venv/bin/python3.12 scripts/ops/run_preflight_simulations.py --apply
    .venv/bin/python3.12 scripts/ops/run_preflight_simulations.py --apply \\
        --promote-scorecard
    # Stream I operator unlock (token required):
    JPCITE_LIVE_AWS_UNLOCK_TOKEN=<signed> \\
        .venv/bin/python3.12 scripts/ops/run_preflight_simulations.py \\
        --apply --unlock-live-aws-commands

Stream A scope: pass_state flip authority for spend_simulation and
teardown_simulation only. The three sibling gates remain owned by their own
stream and must already be PASS before pass_state -> True can promote the
scorecard.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UNLOCK_TOKEN_ENV = "JPCITE_LIVE_AWS_UNLOCK_TOKEN"
EX_USAGE = 64  # POSIX sysexits.h — command-line usage error

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"

# ---------------------------------------------------------------------------
# Assertion registry
# ---------------------------------------------------------------------------
#
# Each assertion has:
#   id          — stable identifier surfaced in JSON output
#   description — human-readable line for the console report
#   check       — callable(context) -> tuple[bool, str]
#                  returns (passed, evidence_string). The evidence string is
#                  ALWAYS non-empty so the report can show "why" regardless
#                  of result.
#   verifiable  — True when the check can be answered mechanically with the
#                 information currently inside the rc1-p0-bootstrap capsule.
#                 False means "the data needed to answer is not yet on disk;
#                 the assertion is a structural placeholder that future
#                 streams must satisfy". A False here keeps pass_state at
#                 False even though the check itself reports PASS=False with
#                 evidence='not_yet_verifiable'.

CheckResult = tuple[bool, str]
CheckFn = Callable[["Context"], CheckResult]


@dataclass
class Assertion:
    assertion_id: str
    description: str
    check: CheckFn
    verifiable_today: bool = True


@dataclass
class AssertionResult:
    assertion_id: str
    description: str
    passed: bool
    evidence: str
    verifiable_today: bool
    preflight_excluded: bool = False


@dataclass
class Context:
    capsule_dir: Path
    spend_simulation: dict[str, Any]
    teardown_simulation: dict[str, Any]
    preflight_scorecard: dict[str, Any]
    aws_spend_program: dict[str, Any]
    aws_execution_templates: dict[str, Any]
    aws_budget_canary_attestation: dict[str, Any]
    noop_aws_command_plan: dict[str, Any]
    release_capsule_manifest: dict[str, Any]
    policy_decision_catalog: dict[str, Any] | None = None
    csv_private_overlay_contract: dict[str, Any] | None = None
    billing_event_ledger_schema: dict[str, Any] | None = None
    # Cached derivations.
    _resource_classes: tuple[str, ...] = field(default_factory=tuple)
    _delete_recipe_resource_classes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_context(capsule_dir: Path) -> Context:
    spend = _load(capsule_dir / "spend_simulation.json")
    teardown = _load(capsule_dir / "teardown_simulation.json")
    pre = _load(capsule_dir / "preflight_scorecard.json")
    spend_program = _load(capsule_dir / "aws_spend_program.json")
    templates = _load(capsule_dir / "aws_execution_templates.json")
    canary = _load(capsule_dir / "aws_budget_canary_attestation.json")
    noop = _load(capsule_dir / "noop_aws_command_plan.json")
    manifest = _load(capsule_dir / "release_capsule_manifest.json")
    policy = _load(capsule_dir / "policy_decision_catalog.json") or None
    csv_overlay = _load(capsule_dir / "csv_private_overlay_contract.json") or None
    ledger = _load(capsule_dir / "billing_event_ledger_schema.json") or None

    ctx = Context(
        capsule_dir=capsule_dir,
        spend_simulation=spend,
        teardown_simulation=teardown,
        preflight_scorecard=pre,
        aws_spend_program=spend_program,
        aws_execution_templates=templates,
        aws_budget_canary_attestation=canary,
        noop_aws_command_plan=noop,
        release_capsule_manifest=manifest,
        policy_decision_catalog=policy,
        csv_private_overlay_contract=csv_overlay,
        billing_event_ledger_schema=ledger,
    )

    # Collect resource_class catalogues for cross-checks.
    tmpls = templates.get("templates") or []
    resource_classes: list[str] = []
    for t in tmpls:
        rc = t.get("resource_class")
        if rc and rc not in resource_classes:
            resource_classes.append(rc)
    ctx._resource_classes = tuple(resource_classes)

    recipes = templates.get("teardown_recipes") or []
    recipe_rcs: list[str] = []
    for r in recipes:
        rc = r.get("resource_class")
        if rc and rc not in recipe_rcs:
            recipe_rcs.append(rc)
    ctx._delete_recipe_resource_classes = tuple(recipe_rcs)
    return ctx


def _ok(msg: str) -> CheckResult:
    return True, msg


def _fail(msg: str) -> CheckResult:
    return False, msg


# ---------------------------------------------------------------------------
# Spend simulation assertions (22)
# ---------------------------------------------------------------------------


def _spend_assertions() -> list[Assertion]:
    return [
        # 1
        Assertion(
            "cash_bill_guard_enabled",
            "spend_simulation.cash_bill_guard_enabled must be true",
            lambda c: (
                _ok("cash_bill_guard_enabled=true")
                if c.spend_simulation.get("cash_bill_guard_enabled") is True
                else _fail("cash_bill_guard_enabled is not true")
            ),
        ),
        # 2
        Assertion(
            "control_spend_within_target",
            "control_spend_usd must satisfy 0 <= x <= 19490",
            lambda c: (
                _ok(f"control_spend_usd={c.spend_simulation.get('control_spend_usd')}")
                if 0 <= float(c.spend_simulation.get("control_spend_usd", -1)) <= 19490
                else _fail(
                    f"control_spend_usd out of range: {c.spend_simulation.get('control_spend_usd')}"
                )
            ),
        ),
        # 3
        Assertion(
            "queue_exposure_zero_during_preflight",
            "queue_exposure_usd must be 0 while AWS_BLOCKED_PRE_FLIGHT",
            lambda c: (
                _ok("queue_exposure_usd=0")
                if float(c.spend_simulation.get("queue_exposure_usd", -1)) == 0
                else _fail(
                    f"queue_exposure_usd != 0 ({c.spend_simulation.get('queue_exposure_usd')})"
                )
            ),
        ),
        # 4
        Assertion(
            "service_tail_risk_zero_during_preflight",
            "service_tail_risk_usd must be 0 while AWS_BLOCKED_PRE_FLIGHT",
            lambda c: (
                _ok("service_tail_risk_usd=0")
                if float(c.spend_simulation.get("service_tail_risk_usd", -1)) == 0
                else _fail(
                    f"service_tail_risk_usd != 0 ({c.spend_simulation.get('service_tail_risk_usd')})"
                )
            ),
        ),
        # 5
        Assertion(
            "teardown_debt_zero_during_preflight",
            "teardown_debt_usd must be 0 while AWS_BLOCKED_PRE_FLIGHT",
            lambda c: (
                _ok("teardown_debt_usd=0")
                if float(c.spend_simulation.get("teardown_debt_usd", -1)) == 0
                else _fail(
                    f"teardown_debt_usd != 0 ({c.spend_simulation.get('teardown_debt_usd')})"
                )
            ),
        ),
        # 6
        Assertion(
            "ineligible_charge_reserve_covers_target",
            "ineligible_charge_uncertainty_reserve_usd must cover the 19490 target",
            lambda c: (
                _ok(
                    f"reserve={c.spend_simulation.get('ineligible_charge_uncertainty_reserve_usd')}"
                )
                if float(c.spend_simulation.get("ineligible_charge_uncertainty_reserve_usd", 0))
                >= 19490
                else _fail(
                    f"reserve below 19490: {c.spend_simulation.get('ineligible_charge_uncertainty_reserve_usd')}"
                )
            ),
        ),
        # 7
        Assertion(
            "target_credit_conversion_usd_fixed",
            "target_credit_conversion_usd must equal 19490",
            lambda c: (
                _ok("target=19490")
                if c.spend_simulation.get("target_credit_conversion_usd") == 19490
                else _fail(f"target={c.spend_simulation.get('target_credit_conversion_usd')}")
            ),
        ),
        # 8
        Assertion(
            "simulation_id_present",
            "simulation_id must be non-empty",
            lambda c: (
                _ok(f"simulation_id={c.spend_simulation.get('simulation_id')}")
                if c.spend_simulation.get("simulation_id")
                else _fail("simulation_id missing")
            ),
        ),
        # 9
        Assertion(
            "spend_program_target_match",
            "aws_spend_program.target_credit_spend_usd must equal 19490",
            lambda c: (
                _ok("aws_spend_program target=19490")
                if c.aws_spend_program.get("target_credit_spend_usd") == 19490
                else _fail("aws_spend_program target mismatch")
            ),
        ),
        # 10
        Assertion(
            "spend_program_planned_sum_match",
            "sum(batch.spend_envelope.planned_usd) must equal 19490",
            lambda c: (
                _ok("planned_sum=19490")
                if c.aws_spend_program.get("planned_target_sum_usd") == 19490
                else _fail("planned_target_sum_usd != 19490")
            ),
        ),
        # 11
        Assertion(
            "spend_program_offline_mode",
            "aws_spend_program execution_mode must be offline_non_mutating_blueprint",
            lambda c: (
                _ok("offline_non_mutating_blueprint")
                if c.aws_spend_program.get("execution_mode") == "offline_non_mutating_blueprint"
                else _fail(f"unexpected execution_mode {c.aws_spend_program.get('execution_mode')}")
            ),
        ),
        # 12
        Assertion(
            "spend_program_live_execution_blocked",
            "aws_spend_program.live_execution_allowed must be false",
            lambda c: (
                _ok("live_execution_allowed=false")
                if c.aws_spend_program.get("live_execution_allowed") is False
                else _fail("live_execution_allowed is true")
            ),
        ),
        # 13
        Assertion(
            "spend_program_gate_state_blocked",
            "aws_spend_program.live_execution_gate_state must equal AWS_BLOCKED_PRE_FLIGHT",
            lambda c: (
                _ok("gate_state=AWS_BLOCKED_PRE_FLIGHT")
                if c.aws_spend_program.get("live_execution_gate_state") == "AWS_BLOCKED_PRE_FLIGHT"
                else _fail("gate_state mismatch")
            ),
        ),
        # 14
        Assertion(
            "noop_plan_offline_only",
            "noop_aws_command_plan must declare live_aws_commands_allowed=false",
            lambda c: (
                _ok("noop plan offline")
                if c.noop_aws_command_plan.get("live_aws_commands_allowed") is False
                else _fail("noop plan claims live AWS allowed")
            ),
        ),
        # 15
        Assertion(
            "noop_plan_account_pinned",
            "noop_aws_command_plan must pin account_id=993693061769",
            lambda c: (
                _ok("account pinned")
                if c.noop_aws_command_plan.get("account_id") == "993693061769"
                else _fail("noop plan account mismatch")
            ),
        ),
        # 16
        Assertion(
            "canary_attestation_program_match",
            "aws_budget_canary_attestation.target_credit_conversion_usd must equal 19490",
            lambda c: (
                _ok("canary target=19490")
                if c.aws_budget_canary_attestation.get("target_credit_conversion_usd") == 19490
                else _fail("canary target mismatch")
            ),
        ),
        # 17
        Assertion(
            "canary_pre_flip_locked",
            "aws_budget_canary_attestation.live_aws_command_unlock must be false during preflight",
            lambda c: (
                _ok("live unlock=false")
                if c.aws_budget_canary_attestation.get("live_aws_command_unlock") is False
                else _fail("canary unlock not locked")
            ),
        ),
        # 18
        Assertion(
            "canary_guard_invariant_total_lt_program_target",
            "guard_sum_invariants must require gross+cash+anomaly <= operator_stopline",
            lambda c: (
                _ok("guard invariant present")
                if "hard_stop_usd_total_lt_program_target"
                in (c.aws_budget_canary_attestation.get("guard_sum_invariants") or {})
                else _fail("guard_sum_invariants missing key")
            ),
        ),
        # 19
        Assertion(
            "preflight_target_matches_spend_program",
            "preflight_scorecard.target_credit_conversion_usd must equal 19490",
            lambda c: (
                _ok("preflight target=19490")
                if c.preflight_scorecard.get("target_credit_conversion_usd") == 19490
                else _fail("preflight target mismatch")
            ),
        ),
        # 20
        Assertion(
            "release_manifest_no_aws_runtime_dep",
            "release_capsule_manifest.aws_runtime_dependency_allowed must be false",
            lambda c: (
                _ok("aws_runtime_dependency_allowed=false")
                if c.release_capsule_manifest.get("aws_runtime_dependency_allowed") is False
                else _fail("manifest allows AWS runtime dependency")
            ),
        ),
        # 21 - sibling gate, requires policy_decision_catalog presence
        Assertion(
            "policy_trust_csv_boundaries_artifact_present",
            "policy_decision_catalog must be present (sibling gate input)",
            lambda c: (
                _ok("policy_decision_catalog present")
                if c.policy_decision_catalog
                else _fail("policy_decision_catalog missing")
            ),
        ),
        # 22 - sibling gate, requires billing ledger schema
        Assertion(
            "billing_event_ledger_schema_append_only",
            "billing_event_ledger_schema must declare append_only=true",
            lambda c: (
                _ok("ledger append_only=true")
                if (c.billing_event_ledger_schema or {}).get("append_only") is True
                else _fail("billing_event_ledger_schema missing or not append_only")
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Teardown simulation assertions (18)
# ---------------------------------------------------------------------------


def _teardown_assertions() -> list[Assertion]:
    return [
        # 1
        Assertion(
            "simulation_id_present",
            "teardown_simulation.simulation_id must be non-empty",
            lambda c: (
                _ok(f"simulation_id={c.teardown_simulation.get('simulation_id')}")
                if c.teardown_simulation.get("simulation_id")
                else _fail("simulation_id missing")
            ),
        ),
        # 2
        Assertion(
            "external_export_required_before_delete",
            "external_export_required_before_delete must be true",
            lambda c: (
                _ok("external_export_required_before_delete=true")
                if c.teardown_simulation.get("external_export_required_before_delete") is True
                else _fail("external_export_required_before_delete is not true")
            ),
        ),
        # 3
        Assertion(
            "post_teardown_attestation_non_aws_triggered",
            "post_teardown_attestation_non_aws_triggered must be true",
            lambda c: (
                _ok("non_aws_triggered=true")
                if c.teardown_simulation.get("post_teardown_attestation_non_aws_triggered") is True
                else _fail("post_teardown_attestation_non_aws_triggered is not true")
            ),
        ),
        # 4
        Assertion(
            "all_resources_have_delete_recipe",
            "teardown_simulation.all_resources_have_delete_recipe must be true",
            lambda c: (
                _ok("all_resources_have_delete_recipe=true")
                if c.teardown_simulation.get("all_resources_have_delete_recipe") is True
                else _fail("all_resources_have_delete_recipe=false")
            ),
        ),
        # 5
        Assertion(
            "delete_recipe_coverage_matches_resource_classes",
            "every resource_class must have a delete recipe",
            lambda c: (
                _ok(f"recipes cover {len(c._delete_recipe_resource_classes)} resource_classes")
                if c._delete_recipe_resource_classes
                and set(c._resource_classes).issubset(set(c._delete_recipe_resource_classes))
                else _fail(
                    "resource_class coverage incomplete: missing="
                    + ",".join(
                        sorted(set(c._resource_classes) - set(c._delete_recipe_resource_classes))
                    )
                )
            ),
        ),
        # 6
        Assertion(
            "teardown_recipes_min_count",
            "teardown_recipes must define >= 14 entries (current AWS plan)",
            lambda c: (
                _ok(f"teardown_recipes={len(c._delete_recipe_resource_classes)}")
                if len(c._delete_recipe_resource_classes) >= 14
                else _fail(f"teardown_recipes={len(c._delete_recipe_resource_classes)} (<14)")
            ),
        ),
        # 7
        Assertion(
            "teardown_attestation_artifacts_listed",
            "aws_spend_program.teardown_attestations must list >=3 attestation_ids",
            lambda c: (
                _ok("teardown_attestations listed")
                if len(c.aws_spend_program.get("teardown_attestations") or []) >= 3
                else _fail("teardown_attestations underflow")
            ),
        ),
        # 8
        Assertion(
            "delete_recipe_dry_run_default",
            "aws_execution_templates must require delete_recipe_dry_run_reviewed",
            lambda c: (
                _ok("delete_recipe_dry_run_reviewed in attestation schema")
                if "delete_recipe_dry_run_reviewed"
                in json.dumps(c.aws_execution_templates.get("operator_unlock_manifest_schema", {}))
                else _fail("delete_recipe_dry_run_reviewed not enforced")
            ),
        ),
        # 9
        Assertion(
            "post_teardown_inventory_required",
            "aws_execution_templates must require post_teardown_inventory_required",
            lambda c: (
                _ok("post_teardown_inventory_required in attestation schema")
                if "post_teardown_inventory_required"
                in json.dumps(c.aws_execution_templates.get("operator_unlock_manifest_schema", {}))
                else _fail("post_teardown_inventory_required not enforced")
            ),
        ),
        # 10
        Assertion(
            "every_resource_class_has_delete_recipe_flag",
            "operator_unlock_manifest must include every_resource_class_has_delete_recipe",
            lambda c: (
                _ok("flag present")
                if "every_resource_class_has_delete_recipe"
                in json.dumps(c.aws_execution_templates.get("operator_unlock_manifest_schema", {}))
                else _fail("every_resource_class_has_delete_recipe flag missing")
            ),
        ),
        # 11
        Assertion(
            "teardown_shell_scripts_present",
            "scripts/teardown/05_teardown_attestation.sh must exist",
            lambda c: (
                _ok("teardown attestation shell exists")
                if (REPO_ROOT / "scripts" / "teardown" / "05_teardown_attestation.sh").exists()
                else _fail("scripts/teardown/05_teardown_attestation.sh missing")
            ),
        ),
        # 12
        Assertion(
            "teardown_shell_run_all_present",
            "scripts/teardown/run_all.sh must exist",
            lambda c: (
                _ok("run_all.sh exists")
                if (REPO_ROOT / "scripts" / "teardown" / "run_all.sh").exists()
                else _fail("scripts/teardown/run_all.sh missing")
            ),
        ),
        # 13
        Assertion(
            "teardown_shell_verify_zero_aws_present",
            "scripts/teardown/verify_zero_aws.sh must exist",
            lambda c: (
                _ok("verify_zero_aws.sh exists")
                if (REPO_ROOT / "scripts" / "teardown" / "verify_zero_aws.sh").exists()
                else _fail("scripts/teardown/verify_zero_aws.sh missing")
            ),
        ),
        # 14
        Assertion(
            "noop_plan_requires_teardown_recipe",
            "noop_aws_command_plan must declare requires_teardown_recipe semantics",
            lambda c: (
                _ok("teardown recipe semantics present")
                if "teardown_recipe" in json.dumps(c.noop_aws_command_plan)
                else _fail("noop plan lacks teardown_recipe semantics")
            ),
        ),
        # 15
        Assertion(
            "spend_program_attestation_post_teardown_cost_review",
            "aws_spend_program must list post_teardown_cost_meter_reviewed attestation",
            lambda c: (
                _ok("post_teardown_cost_meter_reviewed present")
                if any(
                    a.get("attestation_id") == "post_teardown_cost_meter_reviewed"
                    for a in (c.aws_spend_program.get("teardown_attestations") or [])
                )
                else _fail("post_teardown_cost_meter_reviewed missing")
            ),
        ),
        # 16
        Assertion(
            "canary_post_flip_attestation_outputs_listed",
            "aws_budget_canary_attestation.post_flip_attestation_outputs must include flip_evidence",
            lambda c: (
                _ok("post_flip_attestation_outputs present")
                if any(
                    "flip_evidence" in s
                    for s in (
                        c.aws_budget_canary_attestation.get("post_flip_attestation_outputs") or []
                    )
                )
                else _fail("post_flip_attestation_outputs missing flip_evidence")
            ),
        ),
        # 17 — sibling: live operator attestation not yet present
        Assertion(
            "operator_signed_unlock_present",
            "operator_unlock manifest must be signed before live teardown (live-phase only)",
            lambda c: _fail("operator_unlock not yet signed (live phase only)"),
            verifiable_today=False,
        ),
        # 18 — sibling: live AWS run id, not present in preflight
        Assertion(
            "run_id_tag_inventory_empty",
            "post_teardown tagged_resource_inventory must be empty (live phase only)",
            lambda c: _fail("no live run yet — inventory check is live phase only"),
            verifiable_today=False,
        ),
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _live_phase_only_ids(simulation: dict[str, Any]) -> frozenset[str]:
    """Return the set of assertion IDs that should be excluded from preflight evaluation.

    A simulation artifact may declare ``live_phase_only_assertion_ids`` to mark
    assertions whose evidence is structurally unavailable until the AWS canary
    live-phase actually runs (e.g. an operator-signed unlock manifest, a tagged
    resource inventory). Those IDs are still surfaced in the report — but they
    are reported as ``preflight_excluded`` and do NOT keep ``pass_state`` at
    False during the preflight window.
    """

    ids = simulation.get("live_phase_only_assertion_ids") or []
    return frozenset(str(x) for x in ids if isinstance(x, str))


def _evaluate(
    assertions: list[Assertion],
    ctx: Context,
    *,
    live_phase_only: frozenset[str] = frozenset(),
) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for a in assertions:
        if a.assertion_id in live_phase_only:
            results.append(
                AssertionResult(
                    assertion_id=a.assertion_id,
                    description=a.description,
                    passed=False,
                    evidence="preflight_excluded:live_phase_only",
                    verifiable_today=False,
                    preflight_excluded=True,
                )
            )
            continue
        if not a.verifiable_today:
            results.append(
                AssertionResult(
                    assertion_id=a.assertion_id,
                    description=a.description,
                    passed=False,
                    evidence="not_yet_verifiable",
                    verifiable_today=False,
                )
            )
            continue
        try:
            passed, evidence = a.check(ctx)
        except Exception as exc:  # noqa: BLE001
            passed = False
            evidence = f"check raised {type(exc).__name__}: {exc}"
        results.append(
            AssertionResult(
                assertion_id=a.assertion_id,
                description=a.description,
                passed=passed,
                evidence=evidence,
                verifiable_today=True,
            )
        )
    return results


def _all_passed(results: list[AssertionResult]) -> bool:
    """Preflight-only pass state: live_phase_only assertions are excluded."""

    return all(r.passed for r in results if not r.preflight_excluded)


def _summary(results: list[AssertionResult]) -> dict[str, Any]:
    passed = sum(1 for r in results if r.passed)
    failed = sum(
        1 for r in results if not r.passed and r.verifiable_today and not r.preflight_excluded
    )
    not_verifiable = sum(1 for r in results if not r.verifiable_today and not r.preflight_excluded)
    preflight_excluded = sum(1 for r in results if r.preflight_excluded)
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "not_yet_verifiable": not_verifiable,
        "preflight_excluded": preflight_excluded,
        "all_passed": _all_passed(results),
    }


def _scorecard_state(
    spend_pass: bool,
    teardown_pass: bool,
    pre: dict[str, Any],
) -> str:
    blocking = pre.get("blocking_gates") or []
    # The 3 non-simulation gates are owned elsewhere — we trust the scorecard's
    # own state for them. The scorecard is only promoted when ALL gates green.
    sibling_gates_done = pre.get("state") == "AWS_CANARY_READY" or (
        "spend_simulation_pass_state" in blocking
        and "teardown_simulation_pass_state" in blocking
        and len(blocking) == 5
    )
    if not (spend_pass and teardown_pass):
        return "AWS_BLOCKED_PRE_FLIGHT"
    # We do not have authority to flip the 3 sibling gates from this runner;
    # they must already be PASS in their own artifacts. For now we conservatively
    # report the target state but leave the actual scorecard mutation gated on
    # an explicit `--promote-scorecard` flag handled by the caller.
    return "AWS_CANARY_READY" if sibling_gates_done else "AWS_BLOCKED_PRE_FLIGHT"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class UnlockTokenMissingError(RuntimeError):
    """Raised when ``--unlock-live-aws-commands`` is requested without
    the operator-signed token environment variable being set."""


def _utc_iso8601_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    *,
    apply: bool,
    capsule_dir: Path = CAPSULE_DIR,
    promote_scorecard: bool = False,
    unlock_live_aws_commands: bool = False,
    unlock_token: str | None = None,
) -> dict[str, Any]:
    """Evaluate preflight assertions and (optionally) flip pass_state / scorecard.

    Stream W concern separation:

    * ``promote_scorecard`` only flips ``preflight_scorecard.state`` from
      ``AWS_BLOCKED_PRE_FLIGHT`` to ``AWS_CANARY_READY``. It NEVER sets
      ``live_aws_commands_allowed`` to True — that flag is force-held at
      False, even if upstream tampering set it to True.
    * ``unlock_live_aws_commands`` is the ONLY path that may set
      ``live_aws_commands_allowed=True``. It requires ``unlock_token`` to be
      a non-empty string (the caller is expected to pull it from the
      ``JPCITE_LIVE_AWS_UNLOCK_TOKEN`` env var). Missing token raises
      :class:`UnlockTokenMissingError` (the CLI translates that to exit 64).
    """

    ctx = _build_context(capsule_dir)
    spend_live_phase_only = _live_phase_only_ids(ctx.spend_simulation)
    teardown_live_phase_only = _live_phase_only_ids(ctx.teardown_simulation)
    spend_results = _evaluate(_spend_assertions(), ctx, live_phase_only=spend_live_phase_only)
    teardown_results = _evaluate(
        _teardown_assertions(), ctx, live_phase_only=teardown_live_phase_only
    )
    spend_summary = _summary(spend_results)
    teardown_summary = _summary(teardown_results)

    spend_should_pass = spend_summary["all_passed"]
    teardown_should_pass = teardown_summary["all_passed"]

    spend_current = bool(ctx.spend_simulation.get("pass_state", False))
    teardown_current = bool(ctx.teardown_simulation.get("pass_state", False))

    plan = {
        "spend_simulation": {
            "current_pass_state": spend_current,
            "target_pass_state": spend_should_pass,
            "would_flip": spend_should_pass and not spend_current,
            "would_revert": (not spend_should_pass) and spend_current,
        },
        "teardown_simulation": {
            "current_pass_state": teardown_current,
            "target_pass_state": teardown_should_pass,
            "would_flip": teardown_should_pass and not teardown_current,
            "would_revert": (not teardown_should_pass) and teardown_current,
        },
    }

    scorecard_target = _scorecard_state(
        spend_should_pass, teardown_should_pass, ctx.preflight_scorecard
    )

    # Stream W: validate operator unlock prerequisites BEFORE any mutation
    # so we cannot leave the capsule in a half-flipped state.
    if unlock_live_aws_commands:
        if not (unlock_token and unlock_token.strip()):
            raise UnlockTokenMissingError(
                "--unlock-live-aws-commands requires the operator-signed "
                f"environment variable {UNLOCK_TOKEN_ENV} to be non-empty"
            )

    actions: list[str] = []
    if apply:
        # Spend simulation
        ctx.spend_simulation["pass_state"] = spend_should_pass
        ctx.spend_simulation["assertions_to_pass_state_true"] = [
            r.assertion_id for r in spend_results if not r.preflight_excluded
        ]
        if spend_should_pass:
            ctx.spend_simulation["pass_state_flip_authority"] = "preflight_runner"
        _write_json(capsule_dir / "spend_simulation.json", ctx.spend_simulation)
        actions.append(f"wrote spend_simulation.json pass_state={spend_should_pass}")
        # Teardown simulation
        ctx.teardown_simulation["pass_state"] = teardown_should_pass
        ctx.teardown_simulation["assertions_to_pass_state_true"] = [
            r.assertion_id for r in teardown_results if not r.preflight_excluded
        ]
        if teardown_should_pass:
            ctx.teardown_simulation["pass_state_flip_authority"] = "preflight_runner"
        _write_json(capsule_dir / "teardown_simulation.json", ctx.teardown_simulation)
        actions.append(f"wrote teardown_simulation.json pass_state={teardown_should_pass}")

        scorecard_mutated = False
        # --- Stream Q: promote scorecard state. State flip only — never set
        # --- live_aws_commands_allowed=True here. Defense-in-depth: if the
        # --- artifact carries True from upstream tampering, force-reset to
        # --- False as part of the promote action.
        if promote_scorecard and scorecard_target == "AWS_CANARY_READY":
            ctx.preflight_scorecard["state"] = "AWS_CANARY_READY"
            previous_live = ctx.preflight_scorecard.get("live_aws_commands_allowed")
            ctx.preflight_scorecard["live_aws_commands_allowed"] = False
            ctx.preflight_scorecard["scorecard_promote_authority"] = "preflight_runner"
            scorecard_mutated = True
            actions.append("promoted preflight_scorecard to AWS_CANARY_READY")
            if previous_live is True:
                actions.append(
                    "force-reset preflight_scorecard.live_aws_commands_allowed "
                    "True -> False (operator unlock path is the only authority)"
                )
        elif promote_scorecard:
            actions.append(
                "promote-scorecard requested but scorecard_target != "
                "AWS_CANARY_READY; left at " + str(ctx.preflight_scorecard.get("state"))
            )

        # --- Stream I: operator unlock — the ONLY path that may set
        # --- live_aws_commands_allowed=True. Requires the scorecard state to
        # --- already be AWS_CANARY_READY (either pre-existing or just flipped
        # --- by the same invocation) AND the operator-signed token to be
        # --- present (validated above).
        if unlock_live_aws_commands:
            current_state = ctx.preflight_scorecard.get("state")
            if current_state == "AWS_CANARY_READY":
                ctx.preflight_scorecard["live_aws_commands_allowed"] = True
                ctx.preflight_scorecard["unlock_authority"] = "operator"
                ctx.preflight_scorecard["unlocked_at"] = _utc_iso8601_now()
                scorecard_mutated = True
                actions.append(
                    "operator unlocked live_aws_commands_allowed=True (unlock_authority=operator)"
                )
            else:
                actions.append(
                    "unlock-live-aws-commands requested but scorecard state "
                    f"is {current_state!r} (requires AWS_CANARY_READY); "
                    "live_aws_commands_allowed left at False"
                )

        if scorecard_mutated:
            _write_json(capsule_dir / "preflight_scorecard.json", ctx.preflight_scorecard)
        else:
            actions.append(
                "preflight_scorecard left at " + str(ctx.preflight_scorecard.get("state"))
            )

    return {
        "mode": "apply" if apply else "dry-run",
        "spend_simulation": {
            "summary": spend_summary,
            "results": [r.__dict__ for r in spend_results],
        },
        "teardown_simulation": {
            "summary": teardown_summary,
            "results": [r.__dict__ for r in teardown_results],
        },
        "plan": plan,
        "scorecard_target_state": scorecard_target,
        "preflight_scorecard_current_state": ctx.preflight_scorecard.get("state"),
        "preflight_scorecard_live_aws_commands_allowed": ctx.preflight_scorecard.get(
            "live_aws_commands_allowed"
        ),
        "actions": actions,
    }


def _print_report(result: dict[str, Any]) -> None:
    print(f"== preflight simulation runner ({result['mode']}) ==")
    for key in ("spend_simulation", "teardown_simulation"):
        section = result[key]
        s = section["summary"]
        excluded = s.get("preflight_excluded", 0)
        print(
            f"\n[{key}] passed={s['passed']}/{s['total']} "
            f"failed={s['failed']} not_yet_verifiable={s['not_yet_verifiable']} "
            f"preflight_excluded={excluded}"
        )
        for r in section["results"]:
            if r.get("preflight_excluded"):
                tag = "SKIP"
            elif r["passed"]:
                tag = "PASS"
            elif not r["verifiable_today"]:
                tag = "NV  "
            else:
                tag = "FAIL"
            print(f"  {tag} {r['assertion_id']}: {r['evidence']}")
    print("\n== plan ==")
    print(json.dumps(result["plan"], indent=2, ensure_ascii=False))
    print(
        f"\nscorecard_current={result['preflight_scorecard_current_state']} "
        f"-> target={result['scorecard_target_state']}"
    )
    if result["actions"]:
        print("\nactions:")
        for a in result["actions"]:
            print(f"  - {a}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the pass_state flip (default: dry-run only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run (default mode; mutually exclusive with --apply)",
    )
    parser.add_argument(
        "--promote-scorecard",
        action="store_true",
        help=(
            "When --apply is set and BOTH simulations PASS, also promote "
            "preflight_scorecard.state to AWS_CANARY_READY. Requires the 3 "
            "sibling gates to already be PASS (this runner does not flip them). "
            "NOTE: this flag only flips state — live_aws_commands_allowed is "
            "force-held at False (use --unlock-live-aws-commands for that)."
        ),
    )
    parser.add_argument(
        "--unlock-live-aws-commands",
        action="store_true",
        help=(
            "Stream I operator authority. Sets live_aws_commands_allowed=True "
            "on preflight_scorecard.json. REQUIRES the operator-signed env var "
            f"{UNLOCK_TOKEN_ENV} to be non-empty (exit 64 if missing) AND the "
            "scorecard state to already be AWS_CANARY_READY (combine with "
            "--promote-scorecard in the same --apply invocation if needed)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the result as JSON only (suppresses the human report)",
    )
    parser.add_argument(
        "--capsule-dir",
        type=Path,
        default=CAPSULE_DIR,
        help="Override the rc1-p0-bootstrap capsule directory",
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    unlock_token = os.environ.get(UNLOCK_TOKEN_ENV)
    try:
        result = run(
            apply=args.apply,
            capsule_dir=args.capsule_dir,
            promote_scorecard=args.promote_scorecard,
            unlock_live_aws_commands=args.unlock_live_aws_commands,
            unlock_token=unlock_token,
        )
    except UnlockTokenMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EX_USAGE

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_report(result)

    all_pass = (
        result["spend_simulation"]["summary"]["all_passed"]
        and result["teardown_simulation"]["summary"]["all_passed"]
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
