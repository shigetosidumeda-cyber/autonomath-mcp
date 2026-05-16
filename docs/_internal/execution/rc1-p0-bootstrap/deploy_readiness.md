# RC1 P0 Bootstrap Deploy Readiness

Updated: 2026-05-15 JST
Capsule: `rc1-p0-bootstrap-2026-05-15`

## Current State

- Local agent runtime contracts are ready.
- Release capsule is a candidate, not production-switched.
- Public pointer artifacts exist, but AWS is still blocked.
- P0 agent facade exposes exactly 4 tools and hides the full catalog by default.
- Billing invariant is `charge_only_after_accepted_artifact`.
- Runtime must not depend on AWS; `aws_runtime_dependency_allowed` is `false`.
- Request-time LLM fact generation, real CSV runtime, and no-hit absence claims are disabled.

## Completed Artifacts

- `docs/_internal/execution/rc1-p0-bootstrap/README.md`
- `site/.well-known/jpcite-release.json`
- `site/releases/current/runtime_pointer.json`
- `site/releases/rc1-p0-bootstrap/release_capsule_manifest.json`
- `site/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json`
- `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`
- `site/releases/rc1-p0-bootstrap/noop_aws_command_plan.json`
- `site/releases/rc1-p0-bootstrap/spend_simulation.json`
- `site/releases/rc1-p0-bootstrap/teardown_simulation.json`
- `site/releases/rc1-p0-bootstrap/execution_graph.json`
- `site/releases/rc1-p0-bootstrap/capability_matrix.json`
- `site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json`
- `site/releases/rc1-p0-bootstrap/accepted_artifact_pricing.json`
- `site/releases/rc1-p0-bootstrap/jpcir_header.json`
- `schemas/jpcir/_registry.json`

## Commands Already Passed

Run from repo root `/Users/shigetoumeda/jpcite`:

```sh
.venv/bin/python scripts/check_agent_runtime_contracts.py
```

Result: `agent runtime contracts: ok`

```sh
.venv/bin/pytest -q tests/test_agent_runtime_contracts.py
```

Result: `7 passed in 0.65s`

Note: bare `python` and bare `pytest` are not available on this PATH; use `.venv/bin/python` and `.venv/bin/pytest`.

## Next Local Commands

Use these before any deploy or AWS canary decision:

```sh
.venv/bin/python scripts/check_agent_runtime_contracts.py
.venv/bin/pytest -q tests/test_agent_runtime_contracts.py
jq '.state, .live_aws_commands_allowed, .blocking_gates' site/releases/rc1-p0-bootstrap/preflight_scorecard.json
jq '.pass_state' site/releases/rc1-p0-bootstrap/spend_simulation.json site/releases/rc1-p0-bootstrap/teardown_simulation.json
```

If local contracts change, regenerate the capsule artifacts only through the established bootstrap path, then rerun the two pass commands above and re-check the JSON gates. Do not run production deploy, MCP/API export, generated site rebuilds, or AWS scripts from this runbook.

## AWS Blocked State

Current blocker file: `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`

- `state`: `AWS_BLOCKED_PRE_FLIGHT`
- `live_aws_commands_allowed`: `false`
- `cash_bill_guard_enabled`: `true`
- AWS profile/account/region: `bookyou-recovery` / `993693061769` / `us-east-1`
- Target credit conversion: USD `19490`
- Blocking gates:
  - `policy_trust_csv_boundaries`
  - `accepted_artifact_billing_contract`
  - `aws_budget_cash_guard_canary`
  - `spend_simulation_pass_state`
  - `teardown_simulation_pass_state`

Do not run live AWS resource creation, Batch, Bedrock, Textract, OpenSearch, paid queues, or command previews in `noop_aws_command_plan.json` while this state remains blocked.

## Conditions To Move To AWS Canary

All conditions must be true:

- `preflight_scorecard.json` changes to `state: AWS_CANARY_READY`.
- `preflight_scorecard.json` changes to `live_aws_commands_allowed: true`.
- `spend_simulation.json` changes to `pass_state: true`.
- `teardown_simulation.json` changes to `pass_state: true`.
- Every resource type in the canary has a delete recipe and post-teardown attestation path.
- Cash-bill guard is still enabled and the operator has verified budget/credit visibility.
- P0 facade still exposes only the 4 intended tools.
- Production/runtime still has no dependency on temporary AWS resources.
- Local contract checker and focused pytest command both pass after the state change.

First AWS canary, after the above only, should be identity/budget/inventory verification. Resource-creating canaries come after that check, with capped queues and run-id tags.

## Rollback And Zero-Bill Posture

- Rollback target: keep serving the previous release pointer or revert `site/releases/current/runtime_pointer.json` to the last known-good capsule; do not point production at partial AWS artifacts.
- Billing rollback: paid execution remains gated by scoped cap token, idempotency key, and accepted artifact; failed/no-hit/previews stay non-billable.
- Data rollback: do not import AWS-generated artifacts unless they have manifests, checksums, source receipts, known gaps, and quality gates.
- AWS cleanup posture: export required artifacts to non-AWS storage, verify checksums, then delete canary resources by run-id tag.
- Zero-bill condition: no Batch/ECS jobs, ECR images, S3 buckets, Glue/Athena tables, OpenSearch domains, CloudWatch log retention tails, Bedrock/Textract queues, or untagged resources remain.
- Stop condition: if cash-bill guard, budget visibility, or teardown attestation is missing, stop before creating resources and leave `AWS_BLOCKED_PRE_FLIGHT` in place.
