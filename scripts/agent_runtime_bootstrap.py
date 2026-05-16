#!/usr/bin/env python3
"""Generate deterministic P0 agent-runtime bootstrap artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID, build_bootstrap_bundle


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _schema_for_object(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://jpcite.com/schemas/jpcir/{name}.schema.json",
        "title": name,
        **schema,
    }


def _build_jpcir_schemas() -> dict[str, dict[str, Any]]:
    # Pydantic's JSON Schema output is deterministic enough for local contract
    # checks, while the stable wrapper gives downstream agents a public $id.
    from jpintel_mcp.agent_runtime.contracts import (  # noqa: PLC0415
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
        ReleaseCapsuleManifest,
        ScopedCapToken,
        SourceReceipt,
        SpendSimulation,
        TeardownSimulation,
    )

    models = {
        "jpcir_header": JpcirHeader,
        "outcome_contract": OutcomeContract,
        "capability_matrix": CapabilityMatrix,
        "release_capsule_manifest": ReleaseCapsuleManifest,
        "agent_purchase_decision": AgentPurchaseDecision,
        "consent_envelope": ConsentEnvelope,
        "scoped_cap_token": ScopedCapToken,
        "private_fact_capsule": PrivateFactCapsule,
        "execution_graph": ExecutionGraph,
        "aws_noop_command_plan": AwsNoopCommandPlan,
        "spend_simulation": SpendSimulation,
        "teardown_simulation": TeardownSimulation,
        "source_receipt": SourceReceipt,
        "claim_ref": ClaimRef,
        "known_gap": KnownGap,
        "gap_coverage_entry": GapCoverageEntry,
        "no_hit_lease": NoHitLease,
        "policy_decision": PolicyDecision,
        "accepted_artifact_pricing": AcceptedArtifactPricing,
        "evidence": Evidence,
    }
    return {
        name: _schema_for_object(name, model.model_json_schema()) for name, model in models.items()
    }


def _build_resume_readme(bundle: dict[str, Any], manifest_sha256: str) -> str:
    return f"""# jpcite RC1 P0 Bootstrap Resume State

Generated: 2026-05-15
Capsule: `{CAPSULE_ID}`
Manifest SHA-256: `{manifest_sha256}`

## Current State

- Local AI execution control plane: ready
- Public release capsule pointer: candidate
- P0 agent facade: exactly 4 tools
- Live AWS commands: blocked
- AWS profile/account/region: `bookyou-recovery` / `993693061769` / `us-east-1`
- Target credit conversion: USD 19,490
- Cash-bill guard: required before any live AWS command

## Resume Rule

Any Codex or Claude Code session may continue implementing local contracts,
schemas, tests, facade wiring, packet generation, and deployment preparation.
Do not run live AWS resource creation, Batch, Bedrock, Textract, OpenSearch,
or paid queue commands until `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`
changes from `AWS_BLOCKED_PRE_FLIGHT` to `AWS_CANARY_READY` and the contract
checker passes.

## Next Implementation Order

1. Normalize JPCIR schemas and fixtures under `schemas/jpcir/`.
2. Wire the P0 facade to OpenAPI/MCP without exposing the full tool catalog by default.
3. Implement policy, terms, privacy, CSV-overlay, and no-hit fail-closed decisions.
4. Implement accepted-artifact billing ledger with scoped cap tokens and idempotency.
5. Pass no-op AWS command-plan, spend-simulation, and teardown-simulation checks.
6. Only then run AWS canaries and move to the live artifact factory.

## Generated Artifact Index

- `site/.well-known/jpcite-release.json`
- `site/releases/current/runtime_pointer.json`
- `site/releases/rc1-p0-bootstrap/release_capsule_manifest.json`
- `site/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json`
- `site/releases/rc1-p0-bootstrap/outcome_catalog.json`
- `site/releases/rc1-p0-bootstrap/accounting_csv_profiles.json`
- `site/releases/rc1-p0-bootstrap/algorithm_blueprints.json`
- `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json`
- `site/releases/rc1-p0-bootstrap/public_source_domains.json`
- `site/releases/rc1-p0-bootstrap/aws_spend_program.json`
- `site/releases/rc1-p0-bootstrap/aws_execution_templates.json`
- `site/releases/rc1-p0-bootstrap/packet_skeletons.json`
- `site/releases/rc1-p0-bootstrap/inline_packets.json`
- `site/releases/rc1-p0-bootstrap/execution_state.json`
- `site/releases/rc1-p0-bootstrap/noop_aws_command_plan.json`
- `site/releases/rc1-p0-bootstrap/spend_simulation.json`
- `site/releases/rc1-p0-bootstrap/teardown_simulation.json`
- `schemas/jpcir/_registry.json`

## Blocking Gates

{json.dumps(bundle["preflight_scorecard"]["blocking_gates"], ensure_ascii=False, indent=2)}
"""


def build_artifact_map(repo_root: Path) -> dict[Path, Any | str]:
    bundle = build_bootstrap_bundle()
    capsule_dir = repo_root / "site" / "releases" / "rc1-p0-bootstrap"
    manifest_bytes = _json_bytes(bundle["release_capsule_manifest"])
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    well_known_release = {
        **bundle["runtime_pointer"],
        **{
            "schema_version": "jpcite.well_known_release.p0.v1",
            "manifest_path": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
            "manifest_sha256": manifest_sha256,
            "p0_facade_path": "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
            "runtime_pointer_path": "/releases/current/runtime_pointer.json",
        },
    }

    artifact_map: dict[Path, Any | str] = {
        capsule_dir / "jpcir_header.json": bundle["jpcir_header"],
        capsule_dir / "release_capsule_manifest.json": bundle["release_capsule_manifest"],
        capsule_dir / "outcome_contract_catalog.json": bundle["outcome_contract_catalog"],
        capsule_dir / "outcome_catalog.json": bundle["outcome_catalog"],
        capsule_dir / "accounting_csv_profiles.json": bundle["accounting_csv_profiles"],
        capsule_dir / "algorithm_blueprints.json": bundle["algorithm_blueprints"],
        capsule_dir / "outcome_source_crosswalk.json": bundle["outcome_source_crosswalk"],
        capsule_dir / "packet_skeletons.json": bundle["packet_skeletons"],
        capsule_dir / "inline_packets.json": bundle["inline_packets"],
        capsule_dir / "public_source_domains.json": bundle["public_source_domains"],
        capsule_dir / "aws_spend_program.json": bundle["aws_spend_program"],
        capsule_dir / "aws_execution_templates.json": bundle["aws_execution_templates"],
        capsule_dir / "capability_matrix.json": bundle["capability_matrix"],
        capsule_dir / "accepted_artifact_pricing.json": bundle["accepted_artifact_pricing"],
        capsule_dir / "agent_purchase_decision.example.json": bundle["agent_purchase_decision"],
        capsule_dir / "consent_envelope.example.json": bundle["consent_envelope_example"],
        capsule_dir / "scoped_cap_token.example.json": bundle["scoped_cap_token_example"],
        capsule_dir / "execution_graph.json": bundle["execution_graph"],
        capsule_dir / "execution_state.json": bundle["execution_state"],
        capsule_dir / "agent_surface" / "p0_facade.json": bundle["p0_facade"],
        capsule_dir / "noop_aws_command_plan.json": bundle["noop_aws_command_plan"],
        capsule_dir / "spend_simulation.json": bundle["spend_simulation"],
        capsule_dir / "teardown_simulation.json": bundle["teardown_simulation"],
        capsule_dir / "preflight_scorecard.json": bundle["preflight_scorecard"],
        repo_root / "site" / "releases" / "current" / "runtime_pointer.json": bundle[
            "runtime_pointer"
        ],
        repo_root / "site" / ".well-known" / "jpcite-release.json": well_known_release,
        repo_root
        / "docs"
        / "_internal"
        / "execution"
        / "rc1-p0-bootstrap"
        / "README.md": _build_resume_readme(bundle, manifest_sha256),
    }

    schema_dir = repo_root / "schemas" / "jpcir"
    schemas = _build_jpcir_schemas()
    registry = {
        "schema_version": "jpcite.jpcir_schema_registry.p0.v1",
        "capsule_id": CAPSULE_ID,
        "schemas": [
            {
                "name": name,
                "path": f"schemas/jpcir/{name}.schema.json",
                "public_id": schema["$id"],
            }
            for name, schema in sorted(schemas.items())
        ],
    }
    artifact_map[schema_dir / "_registry.json"] = registry
    for name, schema in schemas.items():
        artifact_map[schema_dir / f"{name}.schema.json"] = schema

    return artifact_map


def write_artifacts(repo_root: Path) -> list[Path]:
    written: list[Path] = []
    for path, payload in build_artifact_map(repo_root).items():
        if isinstance(payload, str):
            _write_text(path, payload)
        else:
            _write_json(path, payload)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    artifact_map = build_artifact_map(repo_root)
    if args.write:
        written = write_artifacts(repo_root)
        print(f"wrote {len(written)} P0 bootstrap artifacts")
        for path in written:
            print(path.relative_to(repo_root))
    else:
        print(json.dumps([str(path.relative_to(repo_root)) for path in artifact_map], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
