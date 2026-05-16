#!/usr/bin/env python3
"""Preflight gate sequence checker for AWS_BLOCKED_PRE_FLIGHT -> AWS_CANARY_READY.

Reads the five blocking gates listed in ``preflight_scorecard.json`` and evaluates
each one independently. For every gate we report:

- ``READY``: artifacts present, schema-valid, and content-level invariants hold.
- ``BLOCKED``: artifacts exist but a content-level invariant fails
  (e.g. ``pass_state: false``).
- ``MISSING``: required artifact(s) absent on disk.

The checker is **read-only**. It never mutates ``preflight_scorecard.json`` —
that file's ``state`` is owned by a separate flip authority. Use this script to
decide whether the flip is safe to request.

The five gates and their dependency artifacts:

1. ``policy_trust_csv_boundaries`` — ``policy_decision_catalog.json`` +
   ``csv_private_overlay_contract.json`` exist and contain at least one entry /
   per-provider rule.
2. ``accepted_artifact_billing_contract`` —
   ``billing_event_ledger_schema.json`` + ``accepted_artifact_pricing.json``
   exist; every accepted_artifact pricing rule resolves to one of the 14
   ``outcome_contract`` ids and carries ``estimated_price_jpy`` > 0.
3. ``aws_budget_cash_guard_canary`` —
   ``aws_budget_canary_attestation.json`` exists and lists all four guards
   (``gross_burn_guard``, ``cash_exposure_backstop``, ``operator_stopline``,
   ``anomaly_monitor``).
4. ``spend_simulation_pass_state`` — ``spend_simulation.json`` exists, validates
   against ``schemas/jpcir/spend_simulation.schema.json``, and ``pass_state`` is
   ``true``.
5. ``teardown_simulation_pass_state`` — ``teardown_simulation.json`` exists,
   validates against ``schemas/jpcir/teardown_simulation.schema.json``,
   ``pass_state`` is ``true``, and the seven teardown recipe shell scripts are
   on disk under ``scripts/teardown/``.

Ordering assumption: gates G1, G2, G3 are *independent* (different artifact
families). G4 (spend) and G5 (teardown) are also independent of G1-G3 in terms
of artifact dependency, but the live AWS canary unlock (Stream I, not in scope
here) requires all five to be ``READY`` simultaneously. This checker therefore
evaluates the five gates in parallel and only sequences them in the report.

Exit codes:
  0 — All five gates ``READY``; ``AWS_CANARY_READY`` is achievable.
  1 — One or more gates ``BLOCKED`` or ``MISSING``; details printed.
  2 — Unexpected I/O or schema failure (treat as red).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
SCHEMA_DIR = REPO_ROOT / "schemas" / "jpcir"
TEARDOWN_DIR = REPO_ROOT / "scripts" / "teardown"

EXPECTED_GUARDS = (
    "gross_burn_guard",
    "cash_exposure_backstop",
    "operator_stopline",
    "anomaly_monitor",
)

EXPECTED_OUTCOMES = frozenset(
    {
        "company_public_baseline",
        "invoice_registrant_public_check",
        "application_strategy",
        "regulation_change_watch",
        "local_government_permit_obligation_map",
        "court_enforcement_citation_pack",
        "public_statistics_market_context",
        "client_monthly_review",
        "csv_overlay_public_check",
        "cashbook_csv_subsidy_fit_screen",
        "source_receipt_ledger",
        "evidence_answer",
        "foreign_investor_japan_public_entry_brief",
        "healthcare_regulatory_public_check",
    }
)

EXPECTED_TEARDOWN_SCRIPTS = (
    "01_identity_budget_inventory.sh",
    "02_artifact_lake_export.sh",
    "03_batch_playwright_drain.sh",
    "04_bedrock_ocr_stop.sh",
    "05_teardown_attestation.sh",
    "run_all.sh",
    "verify_zero_aws.sh",
)


@dataclass
class GateResult:
    """Per-gate evaluation outcome.

    ``state`` is one of ``READY``, ``BLOCKED``, ``MISSING``. ``missing_artifacts``
    lists artifact files that must be created before the gate is even evaluable.
    ``blockers`` lists content-level invariant failures (artifact exists but the
    payload is not yet promotable). ``evidence`` captures small diagnostic
    values for human review.
    """

    gate_id: str
    state: str
    missing_artifacts: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_with_schema(payload: dict[str, Any], schema_path: Path) -> list[str]:
    """Return a list of human-readable schema errors (empty when valid)."""

    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover - environment fallback
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(payload)]


def _check_policy_trust_csv_boundaries(capsule_dir: Path) -> GateResult:
    res = GateResult(gate_id="policy_trust_csv_boundaries", state="READY")
    pol = _load_json(capsule_dir / "policy_decision_catalog.json")
    csv = _load_json(capsule_dir / "csv_private_overlay_contract.json")

    if pol is None:
        res.missing_artifacts.append("policy_decision_catalog.json")
    if csv is None:
        res.missing_artifacts.append("csv_private_overlay_contract.json")

    if res.missing_artifacts:
        res.state = "MISSING"
        return res

    assert pol is not None and csv is not None  # narrow for mypy
    entries = pol.get("entries", [])
    per_provider = csv.get("per_provider_rules", [])
    res.evidence["policy_entries"] = len(entries)
    res.evidence["csv_provider_rules"] = len(per_provider)

    if not entries:
        res.blockers.append("policy_decision_catalog.entries is empty")
    if not per_provider:
        res.blockers.append("csv_private_overlay_contract.per_provider_rules is empty")

    global_contract = csv.get("global_contract", {})
    if global_contract.get("raw_csv_sent_to_aws") is not False:
        res.blockers.append(
            "csv_private_overlay_contract.global_contract.raw_csv_sent_to_aws must be false"
        )
    if global_contract.get("raw_csv_retained") is not False:
        res.blockers.append(
            "csv_private_overlay_contract.global_contract.raw_csv_retained must be false"
        )

    if res.blockers:
        res.state = "BLOCKED"
    return res


def _check_accepted_artifact_billing_contract(capsule_dir: Path) -> GateResult:
    res = GateResult(gate_id="accepted_artifact_billing_contract", state="READY")
    ledger = _load_json(capsule_dir / "billing_event_ledger_schema.json")
    pricing = _load_json(capsule_dir / "accepted_artifact_pricing.json")

    if ledger is None:
        res.missing_artifacts.append("billing_event_ledger_schema.json")
    if pricing is None:
        res.missing_artifacts.append("accepted_artifact_pricing.json")

    if res.missing_artifacts:
        res.state = "MISSING"
        return res

    assert ledger is not None and pricing is not None
    if ledger.get("append_only") is not True:
        res.blockers.append("billing_event_ledger_schema.append_only must be true")
    if pricing.get("billing_event_ledger_append_only") is not True:
        res.blockers.append(
            "accepted_artifact_pricing.billing_event_ledger_append_only must be true"
        )

    rules = pricing.get("deliverable_pricing_rules", [])
    res.evidence["deliverable_pricing_rules"] = len(rules)
    seen_outcomes: set[str] = set()
    for rule in rules:
        oc = rule.get("outcome_contract_id")
        price = rule.get("estimated_price_jpy", 0)
        if oc is None:
            res.blockers.append("pricing rule missing outcome_contract_id")
            continue
        seen_outcomes.add(oc)
        if not isinstance(price, int) or price <= 0:
            res.blockers.append(f"pricing rule {oc} estimated_price_jpy must be > 0")
        if rule.get("billable_only_after_accepted_artifact") is not True:
            res.blockers.append(
                f"pricing rule {oc} billable_only_after_accepted_artifact must be true"
            )

    missing_outcomes = EXPECTED_OUTCOMES - seen_outcomes
    if missing_outcomes:
        res.blockers.append(f"missing outcome_contract pricing rules: {sorted(missing_outcomes)}")

    if res.blockers:
        res.state = "BLOCKED"
    return res


def _check_aws_budget_cash_guard_canary(capsule_dir: Path) -> GateResult:
    res = GateResult(gate_id="aws_budget_cash_guard_canary", state="READY")
    att = _load_json(capsule_dir / "aws_budget_canary_attestation.json")
    if att is None:
        res.missing_artifacts.append("aws_budget_canary_attestation.json")
        res.state = "MISSING"
        return res

    guards = att.get("guards", [])
    seen = {g.get("guard_id") for g in guards}
    res.evidence["guard_ids"] = sorted(g for g in seen if isinstance(g, str))
    missing = [g for g in EXPECTED_GUARDS if g not in seen]
    if missing:
        res.blockers.append(f"missing guards: {missing}")

    if att.get("live_aws_command_unlock") is not False:
        res.blockers.append("live_aws_command_unlock must be false at this stage")
    if att.get("target_credit_conversion_usd") != 19490:
        res.blockers.append("target_credit_conversion_usd must be 19490")

    op = next((g for g in guards if g.get("guard_id") == "operator_stopline"), None)
    if op and op.get("hard_stop_usd") != 19490:
        res.blockers.append("operator_stopline.hard_stop_usd must equal 19490")

    if res.blockers:
        res.state = "BLOCKED"
    return res


def _check_spend_simulation_pass_state(capsule_dir: Path, schema_dir: Path) -> GateResult:
    res = GateResult(gate_id="spend_simulation_pass_state", state="READY")
    payload = _load_json(capsule_dir / "spend_simulation.json")
    if payload is None:
        res.missing_artifacts.append("spend_simulation.json")
        res.state = "MISSING"
        return res

    schema_path = schema_dir / "spend_simulation.schema.json"
    if not schema_path.exists():
        res.missing_artifacts.append("schemas/jpcir/spend_simulation.schema.json")
        res.state = "MISSING"
        return res

    errors = _validate_with_schema(payload, schema_path)
    if errors:
        res.blockers.extend(f"schema: {e}" for e in errors)

    pass_state = payload.get("pass_state")
    res.evidence["pass_state"] = pass_state
    res.evidence["assertions_to_pass_state_true"] = payload.get("assertions_to_pass_state_true", [])
    if pass_state is not True:
        res.blockers.append("spend_simulation.pass_state is not true")
    if not payload.get("assertions_to_pass_state_true"):
        res.blockers.append("spend_simulation.assertions_to_pass_state_true is empty")

    if res.blockers:
        res.state = "BLOCKED"
    return res


def _check_teardown_simulation_pass_state(
    capsule_dir: Path, schema_dir: Path, teardown_dir: Path
) -> GateResult:
    res = GateResult(gate_id="teardown_simulation_pass_state", state="READY")
    payload = _load_json(capsule_dir / "teardown_simulation.json")
    if payload is None:
        res.missing_artifacts.append("teardown_simulation.json")
        res.state = "MISSING"
        return res

    schema_path = schema_dir / "teardown_simulation.schema.json"
    if not schema_path.exists():
        res.missing_artifacts.append("schemas/jpcir/teardown_simulation.schema.json")
        res.state = "MISSING"
        return res

    errors = _validate_with_schema(payload, schema_path)
    if errors:
        res.blockers.extend(f"schema: {e}" for e in errors)

    pass_state = payload.get("pass_state")
    res.evidence["pass_state"] = pass_state
    res.evidence["all_resources_have_delete_recipe"] = payload.get(
        "all_resources_have_delete_recipe"
    )
    res.evidence["assertions_to_pass_state_true"] = payload.get("assertions_to_pass_state_true", [])

    if pass_state is not True:
        res.blockers.append("teardown_simulation.pass_state is not true")
    if payload.get("all_resources_have_delete_recipe") is not True:
        res.blockers.append("teardown_simulation.all_resources_have_delete_recipe is not true")
    if not payload.get("assertions_to_pass_state_true"):
        res.blockers.append("teardown_simulation.assertions_to_pass_state_true is empty")

    missing_scripts = [
        name for name in EXPECTED_TEARDOWN_SCRIPTS if not (teardown_dir / name).exists()
    ]
    res.evidence["teardown_scripts_present"] = [
        name for name in EXPECTED_TEARDOWN_SCRIPTS if (teardown_dir / name).exists()
    ]
    if missing_scripts:
        res.blockers.append(f"missing teardown scripts: {missing_scripts}")

    if res.blockers:
        res.state = "BLOCKED"
    return res


def run_sequence(
    capsule_dir: Path = CAPSULE_DIR,
    schema_dir: Path = SCHEMA_DIR,
    teardown_dir: Path = TEARDOWN_DIR,
) -> list[GateResult]:
    """Evaluate the five gates in canonical sequence order."""

    return [
        _check_policy_trust_csv_boundaries(capsule_dir),
        _check_accepted_artifact_billing_contract(capsule_dir),
        _check_aws_budget_cash_guard_canary(capsule_dir),
        _check_spend_simulation_pass_state(capsule_dir, schema_dir),
        _check_teardown_simulation_pass_state(capsule_dir, schema_dir, teardown_dir),
    ]


def _format_report(results: list[GateResult]) -> str:
    lines: list[str] = []
    lines.append("=== preflight gate sequence check ===")
    lines.append(f"capsule_dir = {CAPSULE_DIR.relative_to(REPO_ROOT)}")
    lines.append("")
    for idx, r in enumerate(results, start=1):
        lines.append(f"G{idx} {r.gate_id}: {r.state}")
        if r.missing_artifacts:
            lines.append(f"   missing_artifacts: {r.missing_artifacts}")
        if r.blockers:
            for b in r.blockers:
                lines.append(f"   blocker: {b}")
        if r.evidence:
            for k, v in r.evidence.items():
                lines.append(f"   {k}: {v}")
        lines.append("")

    ready = sum(1 for r in results if r.state == "READY")
    blocked = sum(1 for r in results if r.state == "BLOCKED")
    missing = sum(1 for r in results if r.state == "MISSING")
    lines.append(f"summary: READY={ready} BLOCKED={blocked} MISSING={missing}")
    if ready == 5:
        lines.append("verdict: AWS_CANARY_READY achievable — request flip from authority")
    else:
        not_ready = [r.gate_id for r in results if r.state != "READY"]
        lines.append(f"verdict: AWS_BLOCKED_PRE_FLIGHT — gates not ready: {not_ready}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns exit code 0/1/2 per module docstring."""

    try:
        results = run_sequence()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 2

    report = _format_report(results)
    print(report)

    if all(r.state == "READY" for r in results):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
