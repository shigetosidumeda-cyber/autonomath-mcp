# AWS smart methods round 3 review 12: AI execution experience, runbook, CLI

Date: 2026-05-15  
Role: Round3 additional smart-method validation 12/20  
Topic: AI execution experience, machine-readable execution plan, dry-run simulator, schema generator, autonomous preflight, approval/stop gates, rollback, operator-less guardrails, merge checklist  
Status: planning review only. AWS CLI/API/resource creation was not executed.  
Output constraint: this file only.

Planning references:

- Master plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- Round3 meta-architecture: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_01_meta_architecture.md`
- Round3 product packaging: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_02_product_packaging.md`
- Round3 agent MCP UX: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_03_agent_mcp_ux.md`
- Round3 evidence data model: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_04_evidence_data_model.md`
- Round3 source acquisition: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_05_source_acquisition.md`
- Round3 AWS factory/cost: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_06_aws_factory_cost.md`

Hard constraints carried forward:

- AWS account/profile/region are planning references only: `bookyou-recovery`, `993693061769`, `us-east-1`.
- This review must not run AWS commands, AWS APIs, or create resources.
- The credit face value remains `USD 19,493.94`; the intentional absolute control line remains `USD 19,300`.
- AWS is a short-lived artifact factory, not production runtime.
- Production must run without AWS after the run.
- Real user accounting CSV must not enter AWS.
- Request-time LLM fact generation remains off.
- No-hit remains `no_hit_not_absence`.
- Final state must be zero ongoing AWS bill, including no retained S3 archive.
- The execution premise is AI-first: humans define intent and approve boundaries, but AI agents should perform implementation/execution through machine-readable plans and self-checks.

## 0. Verdict

Conditional PASS with a major AI-execution improvement.

The current smart-method plan is strong but now complex. It has:

- `JPCIR`
- `Evidence Product Operating System`
- `Outcome Contract Catalog`
- `Agent Decision Protocol`
- `Official Evidence Ledger`
- `Evidence Lens`
- `Source Capability Contract`
- `AWS Artifact Factory Kernel`
- `Accepted Artifact Futures`
- `Spend Corridor Controller`
- `Release Capsule`
- `Zero-Bill Proof Ledger`

The remaining risk is no longer mainly architectural. The risk is autonomous execution drift:

- an AI executor runs the right idea in the wrong mode
- a schema is hand-edited but not reflected in generated surfaces
- a dry-run passes but does not model teardown debt or policy blocking
- an AWS job is prepared before its accepted-artifact contract exists
- a Release Capsule is assembled from artifacts that do not share the same `JPCIR` hash
- an emergency fix changes public text without updating the capability contract
- a local CLI or AI agent starts real AWS execution before the zero-bill and cost controls are ready
- an unattended AI loop continues after a stop condition because the stop gate was prose-only
- a rollback path exists in a document but not as an executable state transition

The smarter method is:

> Add an AI-first Execution Control Plane that compiles the plan into machine-readable manifests, dry-runs every stage, generates schemas, emits executable state machines, enforces approval/stop gates, and refuses to produce executable AWS instructions until all invariants pass.

This is not a different product strategy. It is the safety and speed layer that lets the existing strategy be implemented without drift.

## 1. Main new concepts

Adopt these AI-execution components:

1. `AI Execution Control Plane`
2. `Plan-as-Code Execution Manifest`
3. `Machine-Readable Execution Plan Compiler`
4. `No-Op AWS Command Compiler`
5. `JPCIR Schema Generator`
6. `Fixture Forge`
7. `Invariant Test Harness`
8. `Dry-Run Capsule Simulator`
9. `Spend and Teardown Simulator`
10. `AI Executor Instruction Bundle`
11. `Merge Envelope`
12. `Preflight Scorecard`
13. `Autonomous Action Ledger`
14. `Golden Failure Replay`
15. `Capability Surface Diff`
16. `Approval Gate Automaton`
17. `Stop Gate Automaton`
18. `Rollback State Machine`
19. `Autonomous Verification Loop`

These are tools/methods to reduce mistakes before any AWS execution.

## 1A. Correction: AI-first execution premise

The previous wording leaned too much toward human-run runbooks and operator prompts. That is not the intended execution model.

The correct premise is:

```text
Humans set goal, constraints, budget boundary, and final authorization.
AI agents execute implementation and future AWS operation through machine-readable plans.
The system itself performs preflight, dry-run, stop, rollback, and verification.
```

Therefore the artifact should not be a conventional human checklist. It should be a machine-readable execution control system with human-readable summaries as secondary outputs.

### 1A.1 Replace "human runbook" with "execution state machine"

Do not make the primary artifact:

```text
Step 1: human does X.
Step 2: human checks Y.
Step 3: human decides whether to continue.
```

Make the primary artifact:

```text
state: LOCAL_PREFLIGHT
allowed_actions: [...]
required_inputs: [...]
self_checks: [...]
transition_if_pass: NOOP_AWS_PLAN_READY
transition_if_fail: BLOCKED_WITH_FIX_PLAN
stop_gates: [...]
rollback_target: PREVIOUS_RELEASE_CAPSULE
audit_events: [...]
```

### 1A.2 Human-readable docs become compiled views

Markdown runbooks may still exist, but only as generated views of the machine-readable execution graph.

The canonical object is:

```text
execution_graph.yaml
```

The derived objects are:

```text
runbook.generated.md
operator_summary.generated.md
ai_executor_prompt.generated.md
preflight_report.generated.md
rollback_report.generated.md
```

If generated Markdown and execution graph disagree, the execution graph wins and the release fails.

## 2. Core diagnosis

### 2.1 What is already correct

The plan already decides the hard questions:

- product is output-first, not crawler-first
- growth is GEO-first, not SEO-first
- `agent_routing_decision` is free control, not paid packet
- AWS is a temporary factory, not runtime
- actual spend is controlled by `USD 19,300`, not exact credit face value
- real CSV stays out of AWS
- public proof pages must not leak paid value or raw artifacts
- no-hit is scoped and expiring
- source acquisition is driven by output gaps
- release is by validated capsule/pointer, not direct AWS artifact deployment

### 2.2 What is still weak

The plan now has many powerful abstractions, but implementation could fail in routine ways:

| Risk | Example | Impact |
|---|---|---|
| naming drift | `jpcite_cost_preview` vs `jpcite_preview_cost` | MCP/OpenAPI/proof mismatch |
| schema drift | packet JSON accepts a field proof page does not understand | release blocker late in cycle |
| manual merge drift | master plan says `JPCIR`, code uses ad hoc records | AWS artifacts not importable |
| dry-run mismatch | dry-run checks only syntax, not value/teardown/policy | false go decision |
| budget false safety | visible AWS billing lags behind internal exposure | cash exposure risk |
| proof leakage | proof page shows full paid output | value leakage and policy risk |
| prose-only runbook ambiguity | AI executor infers that a step is "probably okay" | unsafe AWS launch |
| local/AWS boundary drift | local fixture code assumes AWS state exists | production dependency risk |
| emergency patch drift | hotfix is not backported to contract | catalog hash mismatch |
| over-smart automation | autonomous AI creates new work class while unattended | cost and terms risk |

### 2.3 AI-execution principle

The AI executor should not infer the plan from prose.

The plan should be compiled into:

- schemas
- manifests
- executable state graphs
- typed checklists
- dry-run reports
- generated AI instruction bundles
- approval/stop gate definitions
- rollback state machines
- merge gates
- release gates
- no-go reasons

If a step is unsafe, the execution control plane should produce a no-go report and a bounded fix plan, not a partially executable command.

## 3. Smart method 1: AI Execution Control Plane

### 3.1 Definition

`AI Execution Control Plane` is a local-first control layer for AI agents and CLI automation.

It should eventually provide commands like:

```text
jpcite-exec compile-graph
jpcite-plan lint
jpcite-plan generate-schemas
jpcite-exec generate-instructions
jpcite-plan simulate --mode no-aws
jpcite-plan simulate-spend
jpcite-plan simulate-teardown
jpcite-plan build-fixtures
jpcite-plan preflight
jpcite-plan merge-check
jpcite-plan release-capsule-check
jpcite-exec transition --dry-run
jpcite-exec verify-autonomous-state
```

This document does not implement those commands. It defines the smarter method.

### 3.2 Control-plane responsibilities

The control plane owns:

- plan manifest loading
- execution graph compilation
- `JPCIR` schema generation
- invariant registry checks
- accepted-artifact future validation
- AI executor instruction generation
- approval/stop gate enforcement
- rollback state machine validation
- autonomous verification scheduling
- no-op AWS command compilation
- simulator reports
- preflight checklists
- merge envelopes
- release capsule validation
- zero-bill teardown rehearsal

It must not own:

- live AWS API calls in planning mode
- production runtime
- real CSV ingestion
- manual legal conclusions
- automatic terms approval
- automatic source trust decisions

### 3.3 Why this is smarter

Without this layer, every smart component has to be remembered and hand-connected.

With this layer:

- AI executors consume a deterministic state graph instead of prose
- mistakes are surfaced before AWS work begins
- schemas become generated artifacts, not wiki text
- generated instructions remain in sync with the manifest
- the same source of truth can drive MCP, OpenAPI, proof pages, packet examples, and release checks

## 4. Smart method 2: Plan-as-Code Execution Manifest

### 4.1 Problem

The current master plan is a Markdown SOT. That is good for reasoning, but not enough for execution.

The implementation needs a machine-checkable plan object.

### 4.2 Adopt

Create a future manifest:

```text
plans/aws_credit_2026_05.execution.yaml
```

It should be generated or hand-authored from the master plan, then validated.

Minimum top-level structure:

```yaml
plan_id: aws_credit_2026_05
plan_version: 2026-05-15.r3
aws_context:
  profile: bookyou-recovery
  account_id: "993693061769"
  region: us-east-1
  mode: planning_only_until_preflight_passes
financial_controls:
  credit_face_value_usd: 19493.94
  intentional_absolute_control_line_usd: 19300
  target_exact_credit_face_value: false
  control_metric: control_spend_usd
product_controls:
  request_time_llm_call_performed: false
  real_user_csv_allowed_in_aws: false
  no_hit_semantics: no_hit_not_absence
surfaces:
  canonical_preview_tool: jpcite_preview_cost
  agent_routing_decision_billing: free_control
release:
  production_runtime_depends_on_aws: false
  release_unit: release_capsule
  rollback_method: pointer_switch
zero_bill:
  retain_s3_archive: false
  external_export_required_before_teardown: true
```

### 4.3 Required manifest sections

The manifest should include:

- `jpcir_records`
- `invariants`
- `outcome_contracts`
- `packet_catalog`
- `agent_decision_protocol`
- `source_capability_contracts`
- `accepted_artifact_futures`
- `spend_corridor`
- `service_risk_escrow`
- `release_capsules`
- `surface_compilers`
- `preflight_gates`
- `merge_gates`
- `teardown_recipes`
- `ai_executor_instruction_bundles`
- `approval_gates`
- `stop_gates`
- `rollback_state_machines`

### 4.4 Non-negotiable manifest rules

The manifest must fail validation if:

- it contains an AWS execution mode before preflight passes
- exact credit-face consumption is set to true
- `intentional_absolute_control_line_usd` exceeds `19300`
- real user CSV is allowed in AWS
- production runtime depends on AWS
- S3 final archive is retained after teardown
- no-hit wording differs from `no_hit_not_absence`
- `agent_routing_decision` is billable
- `jpcite_cost_preview` is used as canonical instead of `jpcite_preview_cost`
- a paid packet has no free preview
- a source has no terms/robots/license boundary
- an accepted artifact future lacks teardown recipe
- an AI execution state has no stop gate
- a rollback target is prose-only rather than state-machine addressable

## 5. Smart method 3: Machine-Readable Execution Plan Compiler

### 5.1 Problem

Human-readable runbooks go stale and are unsafe as the primary execution contract.

This plan has too many gates for an AI executor to infer from prose:

- product contracts
- schemas
- AWS kernel
- source acquisition
- release capsule
- zero-bill teardown

### 5.2 Adopt

Generate a machine-readable execution graph from the execution manifest.

Future canonical generated files:

```text
execution_graph/aws_credit_run.graph.yaml
execution_graph/local_preflight.graph.yaml
execution_graph/noop_aws_plan.graph.yaml
execution_graph/panic_stop.graph.yaml
execution_graph/rollback.graph.yaml
execution_graph/zero_bill_teardown.graph.yaml
```

Human-readable runbooks may be generated as views:

```text
docs/runbooks/aws_credit_run.generated.md
docs/runbooks/local_preflight.generated.md
docs/runbooks/panic_stop.generated.md
docs/runbooks/zero_bill_teardown.generated.md
```

### 5.3 Execution state schema

Each generated state should include:

- `state_id`
- `state_kind`
- `allowed_actions[]`
- `forbidden_actions[]`
- `required_inputs[]`
- `self_checks[]`
- `approval_gates[]`
- `stop_gates[]`
- `rollback_target_state`
- `transition_if_pass`
- `transition_if_fail`
- `transition_if_stop`
- `expected_artifacts[]`
- `audit_events[]`
- `max_scope`
- `aws_live_operations_allowed`
- `aws_noop_operations_allowed`
- `private_data_allowed`
- `human_approval_required`

Example:

```yaml
state_id: LOCAL_PREFLIGHT
state_kind: validation
aws_live_operations_allowed: false
aws_noop_operations_allowed: true
private_data_allowed: false
allowed_actions:
  - validate_manifest
  - generate_schemas
  - run_fixture_forge
  - run_dry_run_capsule
self_checks:
  - invariant_report_pass
  - fixture_leak_scan_pass
  - capability_surface_diff_pass
approval_gates:
  - none
stop_gates:
  - invariant_failure
  - raw_csv_path_detected
  - aws_live_command_detected
transition_if_pass: NOOP_AWS_PLAN_READY
transition_if_fail: BLOCKED_WITH_FIX_PLAN
rollback_target_state: null
```

### 5.4 Compiler rule

If the manifest changes, generated execution graphs must change or the merge fails.

This prevents the common failure where:

- code changed
- plan changed
- execution graph did not change

Generated Markdown is secondary. It is allowed to lag only in `DEGRADED_DOC_VIEW` state and must not be used for execution.

## 6. Smart method 4: No-Op AWS Command Compiler

### 6.1 Problem

The user eventually wants AWS to run in this terminal, but not before planning and guardrails are ready.

Developers need to see the exact command shape without causing resource creation.

### 6.2 Adopt

Create a no-op compiler that emits:

- intended command class
- required IAM role
- target service
- expected tags
- expected cost class
- expected teardown recipe
- required budget lease
- required accepted-artifact future
- forbidden live side effects

Example output:

```json
{
  "command_plan_id": "cmdp_batch_submit_j01_canary",
  "execution_mode": "no_op",
  "would_use_profile": "bookyou-recovery",
  "would_target_account_id": "993693061769",
  "would_target_region": "us-east-1",
  "service": "AWS Batch",
  "operation_class": "submit_job",
  "live_command_emitted": false,
  "requires_budget_lease": true,
  "requires_accepted_artifact_future": true,
  "requires_teardown_recipe": true,
  "blocked_until": [
    "preflight_scorecard_pass",
    "budget_token_market_initialized",
    "service_risk_escrow_initialized",
    "zero_bill_teardown_simulation_pass"
  ]
}
```

### 6.3 Safety rule

The compiler must have two separate outputs:

```text
no_op_command_plan.json
live_command_bundle.sh
```

In planning mode, only the no-op plan may be generated.

Live command bundle generation is allowed only after:

- explicit execution-mode switch
- preflight pass
- kill switch tested
- budget controls tested
- teardown simulation pass
- boundary approval record created

### 6.4 Why this is smarter

This lets AI executors and reviewers inspect exact AWS intent without touching AWS.

It also makes later execution safer because every future live command will already have:

- expected cost class
- tags
- teardown recipe
- budget lease
- accepted artifact future
- no-go conditions

## 7. Smart method 5: JPCIR Schema Generator

### 7.1 Problem

Round3 adds many schema concepts:

- `DemandRecord`
- `SourceCandidateRecord`
- `EvidenceObservationRecord`
- `SourceReceiptRecord`
- `ClaimDerivationRecord`
- `PolicyDecisionRecord`
- `PacketPlanRecord`
- `CompiledPacketRecord`
- `AgentPurchaseDecisionRecord`
- `ReleaseCapsuleManifest`
- `CapabilityMatrixRecord`
- `ZeroBillAttestationRecord`

If each is hand-authored independently, they will drift.

### 7.2 Adopt

Create a schema generator driven by:

```text
schemas/jpcir/_registry.yaml
```

Generated outputs:

```text
schemas/jpcir/*.schema.json
schemas/jpcir/*.example.json
schemas/jpcir/*.negative.example.json
docs/schema_reference/jpcir.generated.md
```

### 7.3 Required generator features

The generator must enforce:

- common object header
- `schema_id`
- `schema_version`
- `record_type`
- `record_id`
- `input_record_ids[]`
- `created_at`
- `content_hash`
- `policy_decision_ref`
- `visibility`
- `data_class`
- `retention_class`
- `zero_bill_export_class`

### 7.4 Schema generator gates

Fail if:

- a public object can contain raw CSV
- a public proof object can contain raw screenshot/HAR body/cookies/auth headers
- a claim lacks `support_state`
- a no-hit lacks scope and expiration
- a packet lacks `known_gaps[]`
- a packet lacks `gap_coverage_matrix[]`
- a paid packet lacks `billing_metadata`
- an agent decision lacks cheapest-sufficient route
- a Release Capsule lacks catalog hash mesh
- a zero-bill attestation lacks external export checksum

## 8. Smart method 6: Fixture Forge

### 8.1 Problem

Developers need test data before AWS produces real artifacts.

But fixture creation can accidentally smuggle private data or unsupported claims.

### 8.2 Adopt

Create a local fixture forge that generates synthetic and public-only fixtures:

```text
fixtures/jpcir/synthetic/
fixtures/jpcir/public_official_minimal/
fixtures/jpcir/negative/
fixtures/jpcir/golden_agent_sessions/
fixtures/jpcir/teardown_simulation/
```

### 8.3 Fixture classes

| Class | Purpose | Real CSV allowed | AWS needed |
|---|---|---:|---:|
| `synthetic_csv_header_only` | CSV parser and privacy tests | no | no |
| `public_source_receipt_minimal` | source receipt schema tests | no | no |
| `no_hit_lease_example` | no-hit language tests | no | no |
| `policy_block_example` | Policy Decision Firewall tests | no | no |
| `proof_minimized_example` | public proof renderer tests | no | no |
| `agent_purchase_decision_example` | MCP/OpenAPI preview tests | no | no |
| `release_capsule_tiny` | pointer switch tests | no | no |
| `zero_bill_attestation_example` | teardown proof tests | no | no |

### 8.4 Fixture anti-patterns

Reject:

- copied customer CSV rows
- screenshots from login pages
- raw HAR bodies
- scraped text that terms do not allow to redistribute
- invented official claims
- no-hit examples that imply absence or safety
- eligibility examples using `eligible` as final external wording

## 9. Smart method 7: Invariant Test Harness

### 9.1 Problem

The plan has many "must never" rules. They should become executable tests.

### 9.2 Adopt

Create an invariant registry:

```text
contracts/invariants/jpcite_invariants.yaml
```

Invariant categories:

- business invariants
- billing invariants
- AWS safety invariants
- privacy invariants
- source policy invariants
- proof visibility invariants
- no-hit language invariants
- release invariants
- zero-bill invariants

### 9.3 P0 invariants

Minimum P0 invariant list:

```text
INV-001 request_time_llm_call_performed == false
INV-002 real_user_csv_allowed_in_aws == false
INV-003 no_hit_semantics == no_hit_not_absence
INV-004 agent_routing_decision is free_control
INV-005 canonical_preview_tool == jpcite_preview_cost
INV-006 production_runtime_depends_on_aws == false
INV-007 retain_s3_archive_after_teardown == false
INV-008 absolute_control_line_usd <= 19300
INV-009 every paid packet has free preview and cap
INV-010 every public claim has claim_refs[]
INV-011 every claim_ref has support_state
INV-012 every packet has known_gaps[]
INV-013 every packet has gap_coverage_matrix[]
INV-014 no public proof includes raw private data
INV-015 no public proof includes raw screenshot archive
INV-016 every accepted artifact future has acceptance tests
INV-017 every AWS resource class has teardown recipe
INV-018 every Release Capsule has catalog hash mesh
INV-019 every live execution plan has panic stop path
INV-020 every final AWS artifact has external export class
```

### 9.4 Test output

The harness should emit:

```text
reports/preflight/invariant_report.json
reports/preflight/invariant_report.md
```

Each failed invariant must include:

- failed object
- exact rule
- severity
- blocked stage
- suggested fix
- whether automatic fix is allowed

## 10. Smart method 8: Dry-Run Capsule Simulator

### 10.1 Problem

Dry-run should simulate the entire release path, not just parse commands.

### 10.2 Adopt

Build a local simulator that takes tiny fixtures through:

```text
DemandRecord
-> OutcomeContract
-> SourceCapabilityContract
-> EvidenceObservation
-> SourceReceipt
-> ClaimDerivation
-> PolicyDecision
-> EvidenceLens
-> CompiledPacket
-> AgentPurchaseDecision
-> ReleaseCapsule
-> CapabilityMatrix
-> AgentSurfaceCompiler output
-> GoldenAgentSessionReplay
-> ZeroBillAttestation
```

### 10.3 Simulator modes

| Mode | Purpose | AWS allowed |
|---|---|---:|
| `no_aws_minimal` | local end-to-end proof with tiny fixtures | no |
| `policy_block` | prove unsafe artifacts are blocked | no |
| `no_hit_scope` | prove no-hit is scoped and expiring | no |
| `proof_minimization` | prove public proof does not leak value | no |
| `release_pointer` | prove pointer switch and rollback | no |
| `zero_bill_rehearsal` | prove teardown proof can be assembled | no |
| `operator_silence` | prove unattended mode cannot create new work classes | no |

### 10.4 Simulator output

```text
reports/simulations/dry_run_capsule_report.json
reports/simulations/dry_run_capsule_report.md
artifacts/local/release_capsule_tiny/
```

The tiny capsule is not production data. It is only a structural acceptance fixture.

## 11. Smart method 9: Spend and Teardown Simulator

### 11.1 Problem

Cost safety cannot rely only on AWS billing visibility. Teardown safety cannot be proven after resources already exist.

### 11.2 Adopt

Add a local simulator for:

- budget leases
- accepted artifact futures
- service risk escrow
- spend corridor
- teardown debt
- panic snapshot reserve
- external export reserve
- post-teardown audit reserve

### 11.3 Simulation inputs

```yaml
credit_face_value_usd: 19493.94
control_line_usd: 19300
protected_reserves:
  cleanup_reserve: 350
  external_export_reserve: 250
  post_teardown_audit_reserve: 100
  ineligible_charge_uncertainty_reserve: 300
  emergency_panic_snapshot_reserve: 150
service_risk_escrow:
  nat_gateway: 0
  public_ipv4: small_fixed_limit
  cloudwatch_logs: capped
  textract: capped
  opensearch: pilot_only
  athena_scan: capped
```

### 11.4 Simulation checks

Fail if:

- a simulated lane can exceed `USD 19,300`
- cleanup reserve can be consumed by normal jobs
- service risk escrow is not reserved before job launch
- a resource class lacks teardown debt pricing
- panic snapshot reserve is zero
- a spend corridor lower bound causes artificial low-value burn
- an unattended mode can create new service classes

### 11.5 Smarter pacing rule

The simulator should distinguish:

```text
useful spend
committed exposure
reserved cleanup funds
tail risk
teardown debt
accepted artifact value
```

Do not optimize for visible AWS spend alone.

## 12. Smart method 10: AI Executor Instruction Bundle

### 12.1 Problem

Codex/Claude/local CLI agents will execute most implementation work. Prompt ambiguity can cause accidental AWS execution, unsafe edits, or unbounded autonomous loops.

### 12.2 Adopt

Generate AI executor instruction bundles from the execution graph.

Future files:

```text
execution_bundles/00_planning_only.ai.json
execution_bundles/01_schema_generation.ai.json
execution_bundles/02_local_simulation.ai.json
execution_bundles/03_preflight_review.ai.json
execution_bundles/04_noop_aws_plan.ai.json
execution_bundles/05_live_aws_canary.ai.json
execution_bundles/06_autonomous_factory_monitor.ai.json
execution_bundles/07_panic_stop.ai.json
execution_bundles/08_release_capsule_review.ai.json
execution_bundles/09_zero_bill_teardown.ai.json
```

### 12.3 Instruction bundle schema

Every AI execution bundle should be JSON/YAML first, Markdown second.

```yaml
bundle_id: ai_exec_00_planning_only
state_id: PLANNING_ONLY
agent_role: planning_agent
allowed_actions:
  - read_local_docs
  - write_single_planning_doc
forbidden_actions:
  - aws_cli
  - aws_sdk
  - resource_creation
  - real_csv_processing
allowed_paths:
  - docs/_internal/aws_smart_methods_round3_12_developer_runbook.md
required_self_checks:
  - no_aws_command_detected
  - only_allowed_paths_changed
  - markdown_written
stop_gates:
  - attempted_aws_command
  - path_scope_violation
  - raw_private_data_detected
rollback:
  type: file_revert_or_patch_repair
audit_event_required: true
```

### 12.4 Planning-only AI rule

For planning-only tasks, the instruction bundle must machine-enforce:

```text
AWS CLI/API/resource creation is forbidden.
Do not run commands that call aws, boto3, CDK, Terraform, CloudFormation, ECS, Batch, S3, Cost Explorer, IAM, Budgets, or any AWS endpoint.
Output only the requested local document or local plan artifact.
```

The AI executor should self-scan intended commands before running them. If an intended command matches the AWS-deny pattern in planning mode, it must stop before execution.

### 12.5 Future live execution rule

For future live AWS phases, prompts must include:

- exact profile
- exact account ID
- exact region
- approved command bundle hash
- approved budget lease ID
- kill switch ID
- teardown recipe hash
- current preflight scorecard hash
- maximum live action scope
- stop gate set hash
- rollback state hash

If any of these is missing, the AI executor must stop.

### 12.6 Autonomous verification loop

Each AI bundle should define post-action verification:

```yaml
post_action_verification:
  must_run:
    - path_scope_check
    - invariant_delta_check
    - generated_artifact_hash_check
    - forbidden_command_log_check
  on_failure:
    transition: BLOCKED_WITH_FIX_PLAN
    live_execution_allowed: false
```

This prevents the AI from "finishing" a step without checking that it stayed within the state boundary.

## 13. Smart method 11: Preflight Scorecard

### 13.1 Problem

Preflight checklists can become long and subjective.

### 13.2 Adopt

Use a scorecard with hard blockers and soft warnings.

Future output:

```text
reports/preflight/preflight_scorecard.json
reports/preflight/preflight_scorecard.md
```

### 13.3 Hard blocker categories

| Code | Blocker |
|---|---|
| `PF-CONTRACT` | packet/catalog/JPCIR schemas not frozen |
| `PF-PRIVACY` | real CSV path can enter AWS |
| `PF-NOHIT` | no-hit language can imply absence/safety |
| `PF-BILLING` | cap/approval/idempotency missing for paid packets |
| `PF-AWS-COST` | budget lease/control spend simulator fails |
| `PF-AWS-RESOURCE` | teardown recipe missing |
| `PF-POLICY` | source terms/license/robots unresolved |
| `PF-PROOF` | proof page can leak paid/raw artifacts |
| `PF-AGENT` | golden agent replay recommends unsafe or too-expensive route |
| `PF-RELEASE` | release capsule hash mesh inconsistent |
| `PF-ZERO-BILL` | external export and teardown proof incomplete |

### 13.4 Preflight states

Use explicit states:

```text
NOT_READY
LOCAL_ONLY_READY
NOOP_AWS_PLAN_READY
AWS_CANARY_READY
STANDARD_LANE_READY
RELEASE_CAPSULE_READY
TEARDOWN_READY
ZERO_BILL_ATTESTED
```

No AI executor should infer readiness from partial green checks.

## 13A. Smart method 11A: Approval and Stop Gate Automata

### 13A.1 Problem

Approval and stop conditions cannot be prose. An AI executor must be able to evaluate them mechanically.

### 13A.2 Adopt

Represent approvals and stops as typed gates.

```yaml
approval_gate:
  gate_id: APPROVE_AWS_CANARY_LIVE_COMMAND_BUNDLE
  required_state: AWS_CANARY_READY
  required_inputs:
    - preflight_scorecard_hash
    - noop_command_plan_hash
    - budget_lease_policy_hash
    - teardown_simulation_report_hash
    - kill_switch_test_report_hash
  human_boundary_approval_required: true
  expires_after: 4h
  max_scope:
    service_classes:
      - batch
      - s3_ephemeral
      - cloudwatch_capped
    spend_ceiling_usd: 500
  forbidden_scope:
    - opensearch_cluster
    - nat_gateway
    - real_user_csv
```

```yaml
stop_gate:
  gate_id: STOP_RAW_PRIVATE_DATA_DETECTED
  severity: critical
  evaluator: fixture_and_artifact_leak_scan
  trigger_if:
    - raw_csv_detected == true
    - auth_header_detected == true
    - cookie_detected == true
  action:
    transition: PANIC_STOP_LOCAL_OR_AWS
    live_execution_allowed: false
    require_rollback: true
```

### 13A.3 Required stop gates

Minimum stop gates:

- AWS command attempted in planning mode
- AWS profile/account/region mismatch
- `control_spend_usd` simulation exceeds `USD 19,300`
- accepted-artifact future missing
- teardown recipe missing
- service risk escrow exceeded
- raw CSV/private data detected
- source terms unresolved
- no-hit wording unsafe
- proof page leaks paid/full/raw artifact
- Release Capsule hash mismatch
- production dependency on AWS detected
- external export checksum missing before teardown

### 13A.4 Gate rule

If a stop gate fires, the AI executor may only:

- write a stop report
- write a bounded fix plan
- execute approved rollback state if already in a live phase
- refuse further work that increases scope

It must not continue to the next state by reasoning that the issue is minor.

## 13B. Smart method 11B: Rollback State Machine

### 13B.1 Problem

Rollback cannot mean "undo manually if needed." AI execution needs addressable rollback states.

### 13B.2 Adopt

Every release or AWS phase should define rollback as state transitions.

```yaml
rollback_state:
  state_id: ROLLBACK_TO_PREVIOUS_RELEASE_CAPSULE
  allowed_from:
    - SHADOW_RELEASE_FAILED
    - GOLDEN_AGENT_REPLAY_FAILED
    - CAPABILITY_SURFACE_DIFF_FAILED
  actions:
    - switch_asset_pointer_to_previous_capsule
    - switch_contract_pointer_to_previous_contract_if_needed
    - mark_failed_capsule_quarantined
    - emit_rollback_attestation
  forbidden_actions:
    - edit_failed_capsule_in_place
    - delete_evidence_before_attestation
    - use_live_aws_lookup_fallback
  verification:
    - production_smoke_without_aws_pass
    - catalog_hash_mesh_consistent
    - failed_capsule_not_advertised
```

### 13B.3 Rollback invariants

- A Release Capsule is immutable.
- Rollback changes pointers, not capsule contents.
- Failed capsules are quarantined, not edited in place.
- Rollback cannot reintroduce AWS runtime dependency.
- Rollback cannot expose raw artifacts.
- Rollback must emit an attestation.

## 13C. Smart method 11C: Autonomous Verification Loop

### 13C.1 Problem

An AI executor can complete an action and miss verification unless the loop is explicit.

### 13C.2 Adopt

Every execution state should include pre-action and post-action checks.

```yaml
autonomous_verification:
  pre_action:
    - state_scope_loaded
    - forbidden_command_scan_pass
    - input_artifact_hashes_match
  post_action:
    - only_allowed_paths_changed
    - expected_artifacts_exist
    - invariant_delta_pass
    - surface_diff_pass_if_surface_changed
    - no_forbidden_aws_command_log
  on_post_action_failure:
    transition: BLOCKED_WITH_FIX_PLAN
```

### 13C.3 Verification rule

The AI executor should treat verification failure as execution failure, even if the underlying edit or command appeared to succeed.

## 14. Smart method 12: Merge Envelope

### 14.1 Problem

The plan says many things must be merged into the master plan and product implementation. Manual merge is risky.

### 14.2 Adopt

Every change should travel in a `merge_envelope`.

Example:

```json
{
  "merge_envelope_id": "me_round3_devex_20260515",
  "source_review_doc": "aws_smart_methods_round3_12_developer_runbook.md",
  "target_documents": [
    "aws_jpcite_master_execution_plan_2026-05-15.md"
  ],
  "target_code_areas": [
    "schemas/jpcir",
    "contracts/invariants",
    "tools/jpcite_plan",
    "execution_graph",
    "execution_bundles",
    "docs/runbooks"
  ],
  "new_concepts": [
    "AI Execution Control Plane",
    "Plan-as-Code Execution Manifest",
    "Machine-Readable Execution Plan Compiler",
    "Dry-Run Capsule Simulator",
    "Preflight Scorecard",
    "Approval Gate Automaton",
    "Stop Gate Automaton",
    "Rollback State Machine"
  ],
  "invariants_added": [
    "planning mode cannot emit live AWS command bundles",
    "generated execution graph must match manifest hash",
    "preflight scorecard must pass before AWS canary",
    "every executable state must have stop gates",
    "rollback must be an executable state transition"
  ],
  "contradictions_resolved": [
    "fast AWS execution vs preflight safety",
    "autonomous AWS run vs operator absence",
    "manual runbook vs schema drift",
    "AI autonomy vs bounded approvals"
  ]
}
```

### 14.3 Merge gate

The merge fails if:

- a concept is added to docs but not to manifest
- a schema is added but no fixture exists
- a fixture exists but no negative test exists
- an execution graph changes without manifest hash update
- an AI instruction bundle permits more than the current phase
- an executable state lacks stop gates
- a rollback target is not state-machine addressable
- master plan says one canonical name and generated surfaces use another

## 15. Smart method 13: Autonomous Action Ledger

### 15.1 Problem

When an AI agent performs a step, later verifiers need machine-readable evidence of why it acted, what it changed, what it checked, and whether it stayed within scope.

### 15.2 Adopt

Maintain a local `Autonomous Action Ledger` for plan execution.

Future file:

```text
reports/autonomous/autonomous_action_ledger.jsonl
```

Each entry:

```json
{
  "action_id": "aal_...",
  "time": "2026-05-15T00:00:00Z",
  "executor": "ai_agent_or_cli_automation",
  "state_id": "PLANNING_ONLY",
  "instruction_bundle_id": "ai_exec_00_planning_only",
  "mode": "planning_only",
  "allowed_scope": "write_one_markdown_file",
  "actual_scope": "write_one_markdown_file",
  "aws_operations_executed": false,
  "forbidden_command_scan_passed": true,
  "pre_action_self_check_passed": true,
  "post_action_verification_passed": true,
  "files_changed": [
    "docs/_internal/aws_smart_methods_round3_12_developer_runbook.md"
  ],
  "reason": "Round3 AI execution runbook review",
  "preflight_ref": null,
  "approval_ref": null
}
```

### 15.3 Why it is smarter

This lets the project prove:

- planning tasks did not touch AWS
- schema generation was local
- live execution was gated
- emergency actions were scoped
- final teardown was verified
- AI autonomy stayed inside allowed state transitions

## 16. Smart method 14: Golden Failure Replay

### 16.1 Problem

Golden happy-path sessions are not enough. The risky cases are failures.

### 16.2 Adopt

Create failure replays:

- missing source terms
- 403/429/CAPTCHA page
- source schema drift
- OCR low confidence
- no-hit with narrow scope
- conflicting public sources
- expensive route not worth buying
- paid proof leakage attempt
- real CSV path accidentally passed
- AWS budget lease exhausted
- service risk escrow depleted
- release capsule hash mismatch
- post-teardown AWS dependency detected

### 16.3 Required assertion

Each failure replay must end in one of:

```text
blocked_with_reason
deferred_with_question
preview_only
manual_review_required
safe_no_charge_failure_artifact
panic_stop_required
```

It must not silently degrade into an unsupported output.

## 17. Smart method 15: Capability Surface Diff

### 17.1 Problem

The same product capability appears in multiple places:

- packet catalog
- MCP tools
- OpenAPI operations
- proof pages
- `llms.txt`
- `.well-known`
- pricing metadata
- examples
- capability matrix

They can drift.

### 17.2 Adopt

Create a surface diff tool.

It compares:

```text
capability_matrix.json
mcp_manifest.json
openapi.agent-safe.json
packet_catalog.json
pricing_catalog.json
proof_page_sidecars/*.json
llms.txt
.well-known/*
```

### 17.3 Required checks

Fail if:

- a paid packet appears in one surface but not another without reason
- a tool advertises a packet not in capability matrix
- a proof page uses a different price/cap than catalog
- a preview example returns a different no-hit phrase
- `agent_routing_decision` appears as paid anywhere
- full REST paths are shown in agent-safe surface without intent
- MCP count/full OpenAPI count are inconsistent with current public text
- catalog hashes do not match

## 18. AI execution levels

### 18.1 Level 0: planning-only

Allowed:

- read docs
- write planning docs
- create local manifests
- create local schemas
- create local fixtures
- create local simulation reports

Forbidden:

- AWS CLI
- AWS SDK
- boto3
- CDK
- Terraform apply
- CloudFormation
- resource creation
- Cost Explorer API
- Budgets API
- IAM changes

### 18.2 Level 1: local implementation

Allowed:

- implement validators
- implement generators
- implement fixture forge
- implement dry-run simulator
- implement execution graph compiler
- implement AI instruction bundle generator
- run local tests

Still forbidden:

- live AWS operations
- real user CSV in test fixtures

### 18.3 Level 2: no-op AWS plan

Allowed:

- compile command plans
- compile execution state transitions
- verify tags, roles, regions, service classes
- simulate budget leases
- simulate teardown
- verify approval/stop gates

Forbidden:

- live command execution
- AWS API calls

### 18.4 Level 3: AWS canary later

Allowed only after explicit future approval and preflight pass:

- smallest approved canary
- approved profile/account/region only
- approved command bundle hash only
- budget lease and kill switch active
- approval gate active
- stop gate automata active
- rollback state machine active

This review does not authorize Level 3.

### 18.5 Level 4: autonomous standard lane later

Allowed only after canary proof:

- self-running lanes
- accepted-artifact futures only
- spend corridor active
- operator-less guardrails active
- autonomous verification loop active

This review does not authorize Level 4.

## 19. Preflight checklist for the eventual implementation

Before live AWS canary, require all of:

```text
[ ] execution manifest exists and validates
[ ] invariant registry exists and passes
[ ] JPCIR schemas generated
[ ] JPCIR examples and negative examples generated
[ ] fixture forge passes leak scan
[ ] dry-run capsule simulator passes
[ ] spend corridor simulator passes
[ ] teardown simulator passes
[ ] no-op AWS command plans generated
[ ] every command plan has teardown recipe
[ ] accepted artifact futures exist for canary work
[ ] service risk escrow configured
[ ] kill switch design tested locally
[ ] AI executor instruction bundles generated
[ ] execution graph hash matches manifest hash
[ ] every executable state has stop gates
[ ] rollback state machine validates
[ ] autonomous verification loop validates
[ ] preflight scorecard is AWS_CANARY_READY
[ ] no real CSV path exists in AWS plan
[ ] no public proof can expose raw screenshot/HAR/private data
[ ] golden failure replay passes
[ ] capability surface diff passes
[ ] autonomous action ledger initialized
```

If any item fails, do not run AWS.

## 20. Merge checklist for the master plan

This file does not edit the master plan. The coordinator should merge these deltas later.

### 20.1 Add section after current Round3 smart-method additions

Add:

```text
AI Execution Control Plane
```

Summary text:

```text
Before AWS execution, the plan must be compiled locally into a plan-as-code
execution manifest, execution state graph, JPCIR schemas, AI executor
instruction bundles, no-op AWS command plans, dry-run capsule simulations,
spend/teardown simulations, approval/stop gates, rollback state machines,
preflight scorecards, autonomous action ledgers, and merge envelopes. Live AWS
command bundles may not be generated until preflight passes. Planning mode can
emit no-op command plans only.
```

### 20.2 Add to immediate implementation order

Insert before AWS guardrail/control-plane scripts:

```text
Build AI Execution Control Plane minimal:
  - execution manifest validator
  - execution graph compiler
  - invariant registry
  - JPCIR schema generator
  - fixture forge
  - dry-run capsule simulator
  - spend/teardown simulator
  - no-op AWS command compiler
  - preflight scorecard
  - AI executor instruction generator
  - approval/stop gate evaluator
  - rollback state machine validator
  - autonomous verification loop
```

### 20.3 Add to release blockers

Add blockers:

- generated Markdown view hash differs from execution graph hash
- generated execution graph hash differs from execution manifest hash
- live AWS command bundle exists before preflight pass
- no-op command plan lacks teardown recipe
- AI instruction bundle allows broader actions than current phase
- executable state lacks stop gates
- rollback target is prose-only
- autonomous verification loop missing
- capability surface diff fails
- golden failure replay fails
- autonomous action ledger missing for live phase

### 20.4 Add to schema tasks

Add:

- `execution_manifest.schema.json`
- `execution_graph.schema.json`
- `merge_envelope.schema.json`
- `preflight_scorecard.schema.json`
- `autonomous_action_ledger_entry.schema.json`
- `noop_aws_command_plan.schema.json`
- `dry_run_capsule_report.schema.json`
- `teardown_simulation_report.schema.json`
- `ai_executor_instruction_bundle.schema.json`
- `approval_gate.schema.json`
- `stop_gate.schema.json`
- `rollback_state_machine.schema.json`

### 20.5 Add to AWS execution gates

Add:

```text
No live AWS command may be emitted until:
  preflight_state >= AWS_CANARY_READY
  execution_graph_hash == execution_manifest_hash
  no_op_command_plan_hash is approved
  teardown_simulation_pass == true
  spend_simulation_pass == true
  ai_instruction_bundle_scope == phase_scope
  approval_gate_active == true
  stop_gate_automata_active == true
  rollback_state_machine_valid == true
  autonomous_verification_loop_valid == true
```

## 21. Contradiction check

### 21.1 "Move fast" vs "more preflight"

Status: resolved.

The execution control plane adds local checks before AWS, but it makes live execution faster because fewer decisions are inferred during the run.

Rule:

```text
Do not skip local automation to save a few hours if skipping it risks burning thousands of dollars into unusable artifacts.
```

### 21.2 "AWS should keep running without Codex/Claude" vs "AI instruction bundles"

Status: resolved.

AI instruction bundles govern setup, panic, review, and bounded future execution states. They do not keep AWS alive. Once launched, autonomous AWS is controlled by the factory kernel, budget leases, spend corridor, service risk escrow, stop gates, and kill switch.

### 21.3 "Output only this file" vs "merge to master plan"

Status: resolved.

This review does not edit the master plan. It includes exact merge instructions for the coordinator.

### 21.4 "No AWS commands" vs "No-Op AWS Command Compiler"

Status: resolved.

No-op command compilation means producing local JSON command plans, not invoking AWS CLI/API or creating resources.

### 21.5 "Runbook should be human-readable" vs "machine-readable execution graph"

Status: resolved.

Generated runbooks can exist, but they are compiled views. The execution graph is canonical and machine-readable.

### 21.6 "Schema generator" vs "manual expert judgment"

Status: resolved.

Schemas enforce structure. They do not replace policy gates for source terms, legal sensitivity, or product positioning.

### 21.7 "Accepted artifact futures" vs "AI dry-run fixtures"

Status: resolved.

Dry-run fixtures are structural. Accepted artifact futures govern future AWS spend. They use similar schema shapes but different execution modes.

### 21.8 "Capability surface diff" vs emergency public fixes

Status: resolved.

Emergency fixes are allowed only in a degraded state. The release cannot be marked healthy until the contract and generated surfaces are back in sync.

### 21.9 "Autonomous action ledger" vs privacy

Status: resolved.

The ledger records operational metadata only. It must not store raw prompts, raw CSV, customer facts, secrets, or AWS credentials.

### 21.10 "Spend simulator" vs actual AWS billing"

Status: resolved.

The simulator is not a substitute for AWS billing controls. It is an additional preflight layer. Live execution still needs internal spend ledger, budget actions, service caps, and later billing observation.

## 22. Non-adoptions

Do not adopt:

- one giant shell script that performs planning, validation, AWS launch, and teardown
- live AWS commands embedded in Markdown runbooks
- prompts that rely on an agent to "be careful" without machine checks
- manual schema edits without generated fixtures
- positive-only fixtures
- dry-run that only checks CLI syntax
- cost simulator that ignores teardown debt
- runbooks that mention exact command names before the no-op compiler generates them
- AI instruction bundles that include secrets or credentials
- AI execution states without stop gates
- rollback instructions that are prose-only
- permanent AWS archive as proof of completion
- "all green except billing" preflight state

## 23. Proposed future local file layout

Suggested future implementation layout:

```text
plans/
  aws_credit_2026_05.execution.yaml

contracts/
  invariants/
    jpcite_invariants.yaml

schemas/
  jpcir/
    _registry.yaml
    *.schema.json
    *.example.json
    *.negative.example.json
  execution/
    execution_manifest.schema.json
    execution_graph.schema.json
    merge_envelope.schema.json
    preflight_scorecard.schema.json
    noop_aws_command_plan.schema.json
    ai_executor_instruction_bundle.schema.json
    approval_gate.schema.json
    stop_gate.schema.json
    rollback_state_machine.schema.json

tools/
  jpcite_plan/
    compile_plan
    lint_plan
    generate_schemas
    forge_fixtures
    simulate_capsule
    simulate_spend
    simulate_teardown
    compile_noop_aws_commands
    preflight
    merge_check
    surface_diff
  jpcite_exec/
    compile_graph
    generate_instructions
    transition_dry_run
    verify_autonomous_state
    evaluate_stop_gates
    validate_rollback

fixtures/
  jpcir/
    synthetic/
    negative/
    golden_agent_sessions/

docs/
  runbooks/
    *.generated.md

execution_bundles/
  *.ai.json

execution_graph/
  *.graph.yaml

reports/
  preflight/
  simulations/
  autonomous/
```

This is a proposed layout only; no files besides this review were created.

## 24. Final recommendation

Adopt the AI Execution Control Plane before live AWS work.

The smartest next method is not another source family or another packet type. The plan already has enough high-value product and data ideas. The bottleneck is making AI execution deterministic, local-first, generated, simulated, stop-gated, rollbackable, and merge-safe.

Minimum adoption set:

1. `Plan-as-Code Execution Manifest`
2. `Machine-Readable Execution Graph`
3. `JPCIR Schema Generator`
4. `Invariant Test Harness`
5. `Dry-Run Capsule Simulator`
6. `Spend and Teardown Simulator`
7. `No-Op AWS Command Compiler`
8. `Preflight Scorecard`
9. `AI Executor Instruction Bundle`
10. `Approval Gate Automaton`
11. `Stop Gate Automaton`
12. `Rollback State Machine`
13. `Autonomous Verification Loop`
14. `Autonomous Action Ledger`
15. `Merge Envelope`
16. `Capability Surface Diff`

This keeps the current master plan intact while making it much harder for an AI executor or CLI automation to accidentally:

- launch AWS too early
- spend without accepted-artifact value
- leak private data
- publish unsupported claims
- drift MCP/OpenAPI/proof/pricing surfaces
- miss zero-bill teardown requirements
- continue after a stop gate
- perform a rollback that is not state-machine verified

Final status:

```text
PASS with required merge additions.
No AWS operation executed.
Only this review file was added.
```
