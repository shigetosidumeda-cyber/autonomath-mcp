# AWS smart methods round 3 review 13: implementation architecture

Date: 2026-05-15  
Role: Round3 additional smart-method validation 13/20  
Topic: Implementation architecture, module boundaries, schemas, tests, migration, feature flags, P0/P1/P2, AI-executable plan  
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
- Round3 pricing/billing/consent: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_07_pricing_billing_consent.md`
- Round3 CSV private overlay: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_08_csv_private_overlay.md`
- Round3 legal/policy/privacy: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_09_legal_policy_privacy.md`
- Round3 evaluation/GEO quality: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_10_evaluation_geo_quality.md`
- Round3 release runtime/capsule: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_11_release_runtime_capsule.md`
- Round3 AI execution runbook: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_12_developer_runbook.md`

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
- Implementation and execution are AI-first. Human-readable documents are compiled views, not the canonical execution system.

## 0. Verdict

Conditional PASS with one major implementation correction.

The plan is now conceptually strong, but it risks becoming too many named subsystems:

- Evidence Product OS
- JPCIR
- Official Evidence Ledger
- Evidence Lens
- Evidence Graph Compiler
- Output Composer
- Public Packet Compiler
- Proof-Carrying Packet Compiler
- Capability Contract Compiler
- Agent Surface Compiler
- Release Capsule
- AI Execution Control Plane
- AWS Artifact Factory Kernel

The smarter implementation method is:

> Keep the concepts, but implement them as one small compiler pipeline around `JPCIR`, not as separate services.

P0 should not build a graph database, workflow engine, policy engine, and release system separately. P0 should build:

1. typed records
2. transition validators
3. pure compile functions
4. generated release capsule
5. machine-readable execution graph
6. release gates

Everything else becomes a plugin, adapter, or future compiler pass.

## 1. Implementation principle

### 1.1 One spine, many passes

Canonical implementation spine:

```text
source/artifact/input
  -> JPCIR records
  -> policy decisions
  -> evidence lens
  -> packet plan
  -> public packet
  -> capability contract
  -> release capsule
  -> generated agent surfaces
```

Each arrow is a compiler pass with:

- input schema
- output schema
- deterministic function
- invariant checks
- negative tests
- trace record

### 1.2 Avoid service sprawl

Do not implement these as independent runtimes in P0:

- Evidence Graph service
- Output Composer service
- Policy service
- Release service
- Agent Surface service
- AWS Factory service

P0 implementation should be repo-local and mostly static:

- schema files
- fixture files
- pure TypeScript/Python/Go functions, depending on current repo stack
- CLI runners
- generated JSON/Markdown/static assets
- test gates

If the existing repo has one dominant language/framework, use it. Do not introduce a second stack unless required.

### 1.3 JPCIR is the only cross-module exchange object

Every module boundary should exchange:

```text
JPCIR record(s) + manifest + validation report
```

Not:

- ad hoc packet JSON
- undocumented CSV
- arbitrary Python dicts
- proof-page-only sidecars
- MCP-specific request objects
- OpenAPI-specific response objects

MCP/OpenAPI/proof pages are generated surfaces, not primary product models.

## 2. Minimal module boundary map

P0 module boundaries should be this small:

| Module | Responsibility | P0 form | Must not do |
|---|---|---|---|
| `jpcir` | schemas, record ids, canonicalization, validation | JSON Schema + validators | business decisions |
| `policy` | data class, terms, taint, proof visibility, billing eligibility | pure decision functions | free-form legal judgment |
| `evidence` | receipts, claims, support state, no-hit lease, conflict bundle | compiler passes over JPCIR | runtime truth DB |
| `composer` | choose cheapest sufficient outcome route and packet plan | deterministic planner | make factual claims |
| `packet` | compile public packets from approved evidence lens | pure compiler | fetch sources |
| `billing` | consent envelope, cap token, accepted artifact pricing | ledgers + validators | charge without accepted artifact |
| `capsule` | immutable release bundle and pointer metadata | manifest + hash mesh | mutable live DB |
| `surface` | MCP/OpenAPI/llms/.well-known/proof/pricing generation | generated static/runtime assets | define independent catalog facts |
| `execution` | machine-readable implementation/run graph | YAML/JSON graph + gates | depend on human checklist |
| `aws_factory` | future AWS plan artifacts and no-op command plan | plan compiler inputs | run AWS in planning mode |

### 2.1 Dependency direction

Allowed dependencies:

```text
jpcir
  <- policy
  <- evidence
  <- composer
  <- packet
  <- billing
  <- capsule
  <- surface
  <- execution
```

`aws_factory` can emit JPCIR-compatible artifact manifests, but production runtime must not depend on it.

Forbidden dependencies:

```text
surface -> aws_factory
packet -> surface
evidence -> packet
policy -> billing
jpcir -> any product module
runtime -> AWS SDK/S3/EventBridge/Batch/CloudWatch
```

## 3. P0 schemas

P0 should freeze only the schemas needed to ship RC1 and run AWS canary safely.

### 3.1 JPCIR base header

All JPCIR records share:

```yaml
jpcir_header:
  jpcir_version: "0.1"
  record_type: string
  record_id: string
  content_hash: string
  created_at: datetime
  producer:
    module_id: string
    module_version: string
    run_id: string
  source_lineage:
    input_record_ids: [string]
    input_hashes: [string]
  policy_lineage:
    policy_decision_ids: [string]
  visibility:
    class: public|tenant_private|internal|blocked
    public_surface_allowed: boolean
    paid_surface_allowed: boolean
  invariant_status:
    passed: boolean
    failed_invariant_ids: [string]
```

### 3.2 P0 record types

Required P0 record schemas:

```text
schemas/jpcir/jpcir_header.schema.json
schemas/jpcir/demand_record.schema.json
schemas/jpcir/source_candidate_record.schema.json
schemas/jpcir/evidence_observation_record.schema.json
schemas/jpcir/source_receipt_record.schema.json
schemas/jpcir/claim_ref_record.schema.json
schemas/jpcir/claim_derivation_record.schema.json
schemas/jpcir/no_hit_lease_record.schema.json
schemas/jpcir/known_gap_record.schema.json
schemas/jpcir/gap_coverage_matrix_record.schema.json
schemas/jpcir/conflict_bundle_record.schema.json
schemas/jpcir/policy_decision_record.schema.json
schemas/jpcir/evidence_lens_record.schema.json
schemas/jpcir/packet_plan_record.schema.json
schemas/jpcir/public_packet_record.schema.json
schemas/jpcir/agent_purchase_decision_record.schema.json
schemas/jpcir/billing_event_record.schema.json
schemas/jpcir/capability_contract_record.schema.json
schemas/jpcir/release_capsule_manifest.schema.json
schemas/jpcir/execution_graph.schema.json
schemas/jpcir/action_ledger_record.schema.json
```

### 3.3 Minimal P0 packet envelope

Every externally visible paid or free output must compile to:

```yaml
packet_envelope:
  packet_id: string
  packet_version: string
  packet_kind: free_control|paid_packet|proof_sidecar|decision_object
  outcome_contract_id: string
  request_time_llm_call_performed: false
  source_receipts: []
  claim_refs: []
  known_gaps: []
  gap_coverage_matrix: []
  no_hit_checks: []
  algorithm_trace: []
  conflict_bundles: []
  policy_decisions: []
  billing_metadata:
    chargeable: boolean
    price_quote_id: string|null
    consent_envelope_id: string|null
    scoped_cap_token_id: string|null
    accepted_artifact_pricing: boolean
  human_review_required: boolean
  disclaimer:
    no_hit_policy: "no_hit_not_absence"
```

### 3.4 Minimal Release Capsule manifest

```yaml
release_capsule:
  capsule_id: string
  capsule_version: string
  capsule_hash: string
  jpcir_manifest_hash: string
  capability_contract_hash: string
  catalog_hash: string
  policy_bundle_hash: string
  generated_surfaces:
    llms_txt: { path: string, hash: string }
    well_known: { path: string, hash: string }
    mcp_manifest: { path: string, hash: string }
    openapi_agent_safe: { path: string, hash: string }
    proof_pages: [{ path: string, hash: string }]
    pricing_pages: [{ path: string, hash: string }]
  hot_assets:
    evidence_lenses: [{ path: string, hash: string }]
    packet_examples: [{ path: string, hash: string }]
  blocked_assets:
    raw_screenshots_public: true
    raw_csv: true
    aws_runtime_reference: true
  activation_gates:
    invariant_report: string
    surface_hash_mesh_report: string
    runtime_dependency_firewall_report: string
    golden_agent_replay_report: string
    production_without_aws_smoke_report: string
```

## 4. Compiler passes

### 4.1 P0 compiler pass list

P0 should implement exactly these passes first:

| Pass | Input | Output | Purpose |
|---|---|---|---|
| `normalize_demand` | task/input | `demand_record` | normalize user/agent intent |
| `policy_precheck` | any JPCIR | `policy_decision_record` | block unsafe visibility/terms/private data |
| `receipt_compile` | observations | `source_receipt_record` | make source-backed receipt |
| `claim_compile` | receipts | `claim_ref_record` | bind claims to receipts |
| `gap_compile` | plan + evidence | `known_gap_record`, `gap_coverage_matrix_record` | expose missing/stale/blocked coverage |
| `no_hit_compile` | checked source scope | `no_hit_lease_record` | scoped expiring no-hit |
| `evidence_lens_compile` | claims/gaps/no-hit/conflicts | `evidence_lens_record` | release-safe evidence view |
| `route_solve` | demand + capability contract | `agent_purchase_decision_record` | cheapest sufficient route |
| `packet_plan_compile` | purchase decision | `packet_plan_record` | execution plan for packet |
| `public_packet_compile` | evidence lens + packet plan | `public_packet_record` | final output |
| `billing_compile` | accepted packet | `billing_event_record` | accepted-artifact billing |
| `capability_contract_compile` | catalog + policy + packet schemas | `capability_contract_record` | public product SOT |
| `surface_compile` | release capsule | generated surfaces | MCP/OpenAPI/proof/llms |
| `capsule_assemble` | compiled assets | `release_capsule_manifest` | immutable release bundle |
| `execution_graph_compile` | implementation manifest | `execution_graph` | AI-executable implementation graph |

### 4.2 Pass contract

Every compiler pass must expose:

```yaml
compiler_pass:
  pass_id: string
  input_record_types: [string]
  output_record_types: [string]
  deterministic: true
  reads_network: false
  writes_database: false
  allowed_side_effects:
    - write_generated_file
    - write_validation_report
  invariants_required: [string]
  negative_tests_required: [string]
```

Network and AWS access should only exist in future acquisition/execution adapters, never in the core compilers.

## 5. AI-executable implementation graph

The implementation plan should be generated as a machine-readable graph.

### 5.1 Graph state model

```yaml
execution_graph:
  graph_id: "jpcite_p0_implementation_architecture_v1"
  mode: "local_implementation_planning"
  aws_commands_allowed: false
  states:
    - id: CONTRACT_FREEZE
      allowed_actions:
        - read_existing_catalog
        - generate_schema_stubs
        - generate_fixture_plan
      required_outputs:
        - schemas_manifest
        - invariant_registry
      transition_if_pass: JPCIR_VALIDATORS
      transition_if_fail: BLOCKED_FIX_CONTRACT

    - id: JPCIR_VALIDATORS
      allowed_actions:
        - implement_schema_validation
        - implement_canonical_hashing
        - add_positive_negative_fixtures
      required_outputs:
        - validation_report
        - canonicalization_report
      transition_if_pass: POLICY_FIREWALL_MINIMAL
      transition_if_fail: BLOCKED_FIX_VALIDATORS

    - id: POLICY_FIREWALL_MINIMAL
      allowed_actions:
        - implement_visibility_decisions
        - implement_taint_decisions
        - implement_forbidden_phrase_gate
      required_outputs:
        - policy_decision_report
      transition_if_pass: COMPILER_PASSES_MINIMAL
      transition_if_fail: BLOCKED_FIX_POLICY

    - id: COMPILER_PASSES_MINIMAL
      allowed_actions:
        - implement_receipt_claim_gap_nohit_compilers
        - implement_evidence_lens_compiler
        - implement_packet_plan_compiler
      required_outputs:
        - compiler_pass_report
      transition_if_pass: CAPABILITY_CONTRACT
      transition_if_fail: BLOCKED_FIX_COMPILERS

    - id: CAPABILITY_CONTRACT
      allowed_actions:
        - compile_capability_contract
        - compile_agent_purchase_decision
        - compile_surface_hash_mesh
      required_outputs:
        - capability_contract_record
        - agent_purchase_decision_fixture
      transition_if_pass: RELEASE_CAPSULE_LOCAL
      transition_if_fail: BLOCKED_FIX_CAPABILITY

    - id: RELEASE_CAPSULE_LOCAL
      allowed_actions:
        - assemble_release_capsule_fixture
        - run_runtime_dependency_firewall
        - run_golden_agent_replay_fixture
      required_outputs:
        - release_capsule_manifest
        - activation_gate_report
      transition_if_pass: READY_FOR_AWS_NOOP_PLAN
      transition_if_fail: BLOCKED_FIX_RELEASE

    - id: READY_FOR_AWS_NOOP_PLAN
      allowed_actions:
        - generate_noop_aws_command_plan
        - generate_aws_factory_contracts
      required_outputs:
        - noop_aws_plan
        - aws_artifact_contract_manifest
      transition_if_pass: WAIT_FOR_EXPLICIT_AWS_EXECUTION_AUTH
      transition_if_fail: BLOCKED_FIX_AWS_PLAN
```

### 5.2 Machine-enforced no-AWS guard

For this review and the next implementation-prep stages:

```yaml
no_aws_guard:
  aws_cli_allowed: false
  aws_sdk_allowed: false
  network_to_aws_allowed: false
  allowed_aws_mentions:
    - profile name in docs
    - account id in docs
    - region in docs
    - no-op command templates
  fail_if:
    - process_exec_matches: "^aws "
    - import_matches: "boto3|botocore|@aws-sdk|aws-sdk"
    - env_var_required: "AWS_PROFILE"
```

The `No-Op AWS Command Compiler` may generate inert command templates only if they are clearly marked non-executable and are not run.

## 6. Feature flags

Feature flags should be schema-level and capsule-level, not only environment variables.

### 6.1 P0 flags

```yaml
feature_flags:
  jpcir_enabled:
    default: true
    release_required: true
  policy_firewall_enabled:
    default: true
    release_required: true
  agent_purchase_decision_enabled:
    default: true
    release_required: true
  release_capsule_runtime_enabled:
    default: true
    release_required: true
  public_packet_compiler_enabled:
    default: true
    release_required: true
  request_time_llm_fact_generation_enabled:
    default: false
    release_required: false
    hard_block_if_true: true
  real_csv_to_aws_enabled:
    default: false
    release_required: false
    hard_block_if_true: true
  live_aws_runtime_lookup_enabled:
    default: false
    release_required: false
    hard_block_if_true: true
  public_raw_screenshot_archive_enabled:
    default: false
    hard_block_if_true: true
```

### 6.2 Flag invariant

Release fails if:

- flags differ between catalog, MCP, OpenAPI, proof page, and Release Capsule manifest
- a public surface exposes a capability with disabled flag
- a paid packet can execute without `agent_purchase_decision_enabled`
- any hard-block flag is true

## 7. Tests

### 7.1 Test pyramid

P0 test order:

1. schema validation tests
2. canonicalization/hash tests
3. invariant registry tests
4. policy firewall tests
5. compiler pass golden tests
6. forbidden phrase tests
7. public/private leakage tests
8. no-hit lease tests
9. billing consent tests
10. capability hash mesh tests
11. release capsule activation tests
12. golden agent session replay tests
13. production-without-AWS smoke tests

### 7.2 Required negative fixtures

Create fixtures that must fail:

```text
fixtures/negative/raw_csv_in_public_packet.json
fixtures/negative/no_hit_as_absence.json
fixtures/negative/request_time_llm_fact.json
fixtures/negative/aws_url_in_release_capsule.json
fixtures/negative/mcp_openapi_catalog_hash_mismatch.json
fixtures/negative/paid_packet_without_consent.json
fixtures/negative/source_receipt_missing_hash.json
fixtures/negative/claim_without_receipt_or_gap.json
fixtures/negative/public_proof_reconstructs_paid_output.json
fixtures/negative/capability_without_policy_decision.json
fixtures/negative/release_capsule_mutable_pointer.json
fixtures/negative/forbidden_external_wording_safe.json
fixtures/negative/forbidden_external_wording_eligible.json
fixtures/negative/no_teardown_class_for_aws_artifact.json
```

### 7.3 Golden fixtures for RC1

P0 positive fixtures:

```text
fixtures/golden/company_public_baseline_minimal/
fixtures/golden/source_receipt_ledger_minimal/
fixtures/golden/evidence_answer_minimal/
fixtures/golden/agent_purchase_decision_cheapest_sufficient/
fixtures/golden/no_hit_not_absence_scoped/
fixtures/golden/release_capsule_rc1_static/
fixtures/golden/golden_agent_session_company_check/
```

### 7.4 Test gates as machine-readable release blockers

```yaml
release_blockers:
  - id: TEST-001
    condition: "jpcir_schema_tests_failed"
    severity: no_go
  - id: TEST-002
    condition: "policy_firewall_tests_failed"
    severity: no_go
  - id: TEST-003
    condition: "claim_without_receipt_or_gap_detected"
    severity: no_go
  - id: TEST-004
    condition: "no_hit_not_absence_violation_detected"
    severity: no_go
  - id: TEST-005
    condition: "public_surface_hash_mesh_mismatch"
    severity: no_go
  - id: TEST-006
    condition: "release_capsule_contains_aws_runtime_reference"
    severity: no_go
  - id: TEST-007
    condition: "raw_csv_or_private_taint_public"
    severity: no_go
  - id: TEST-008
    condition: "paid_packet_executable_without_consent"
    severity: no_go
```

## 8. Migration plan

### 8.1 Migration goal

Move existing catalog/API/MCP/proof outputs from ad hoc structures to generated surfaces backed by JPCIR and capability contract.

### 8.2 Migration phases

```yaml
migration:
  phase_0_inventory:
    inputs:
      - existing packet catalog
      - existing MCP tool definitions
      - existing OpenAPI paths
      - existing proof pages
      - existing pricing metadata
    outputs:
      - surface_inventory.json
      - naming_drift_report.json
      - schema_gap_report.json

  phase_1_shadow_jpcir:
    behavior:
      - keep existing outputs
      - generate JPCIR sidecars
      - compare current output with compiled output
    release_effect: none

  phase_2_dual_surface_shadow:
    behavior:
      - generate llms/well-known/MCP/OpenAPI/proof from capability contract
      - keep generated surfaces internal
      - run hash mesh and golden agent replay
    release_effect: none

  phase_3_rc1_capsule:
    behavior:
      - activate Release Capsule for free decision surfaces
      - enable limited paid RC1 packets
      - block non-capsule packet execution
    release_effect: limited_production

  phase_4_remove_legacy_paths:
    behavior:
      - delete or disable ad hoc catalog/proof/API routes
      - enforce generated surface SOT
    release_effect: production_sot
```

### 8.3 Migration invariant

At no point may an old route expose:

- a paid packet without consent envelope
- a no-hit conclusion without no-hit lease
- a claim without receipt/gap
- a public proof page not tied to capsule hash
- a price not tied to capability contract

## 9. P0/P1/P2 implementation cut

### 9.1 P0: required before AWS full run and RC1

P0 scope:

- JPCIR base schemas and validators
- invariant registry
- policy firewall minimal
- forbidden phrase gate
- no-hit lease schema/compiler
- source receipt and claim ref compiler
- gap coverage matrix compiler
- evidence lens minimal
- agent purchase decision minimal
- capability contract minimal
- public packet compiler for RC1 packets
- billing consent/cap token/accepted artifact minimal
- release capsule manifest
- surface compiler for agent-safe OpenAPI/MCP/llms/.well-known/proof/pricing
- runtime dependency firewall
- golden agent replay minimal
- execution graph for AI implementation
- no-op AWS plan compiler

RC1 paid packets:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`

RC1 free controls:

- `agent_task_intake`
- `jpcite_preview_cost`
- `agent_purchase_decision`
- `capability_matrix`
- `proof_index`

### 9.2 P1: after RC1, before broad AWS import

P1 scope:

- full Evidence Lens compiler
- conflict bundle compiler
- proof set optimizer
- receipt reuse dividend
- coverage ladder quote
- buyer policy profile
- more packet families:
  - grants
  - permits
  - enforcement
  - tax/labor
  - procurement
- CSV private overlay with browser/local-first extractor
- private/public join planner
- release capsule progressive exposure lanes
- capability surface diff in CI

### 9.3 P2: after broad corpus baseline

P2 scope:

- update frontier planner
- source replacement market
- semantic delta compressor
- watch delta products
- portfolio batch packets
- advanced bitemporal graph queries
- automated source evolution canary
- richer GEO eval matrix
- optional non-AWS recurring update path with explicit budget approval

## 10. Contradiction review

### 10.1 Evidence Product OS vs minimal modules

Potential tension:

> The OS language sounds like a large platform.

Resolution:

> In implementation, Evidence Product OS is the architecture. P0 is a compiler pipeline and invariant harness. Do not create platform services until P1/P2 proves the need.

### 10.2 Official Evidence Graph vs zero-bill

Potential contradiction:

> A graph can imply a persistent database.

Resolution:

> P0 graph is represented as JPCIR JSONL/manifests and compiled Evidence Lens assets. No production graph DB. AWS graph processing may exist only during the temporary run and must export/delete.

### 10.3 Output Composer vs Public Packet Compiler

Potential ambiguity:

> Both appear to generate outputs.

Resolution:

> Output Composer chooses a route and packet plan. Public Packet Compiler turns approved evidence into final packet. Composer cannot create factual claims.

### 10.4 Agent Surface Compiler vs Capability Contract Compiler

Potential ambiguity:

> Both affect public agent surfaces.

Resolution:

> Capability Contract Compiler creates the product SOT. Agent Surface Compiler renders that SOT into MCP/OpenAPI/llms/proof/pricing surfaces.

### 10.5 AI executes everything vs approval gates

Potential tension:

> AI execution could conflict with budget/production safety.

Resolution:

> AI executes implementation and machine checks. Transition into real AWS execution or public production activation requires explicit gate objects. Gates are machine-readable and auditable, not human step-by-step runbooks.

### 10.6 Fast AWS spend vs implementation prerequisites

Potential tension:

> User wants AWS to run quickly and spend within about a week.

Resolution:

> Do not wait for full P1/P2 architecture. P0 must produce enough contract, no-op AWS plan, artifact contracts, and release capsule gates so AWS can run safely. AWS can manufacture JPCIR-compatible artifacts while production ships RC1 from a small capsule.

### 10.7 Free preview vs paid output leakage

Potential contradiction:

> Agent purchase decision needs enough detail to recommend buying, but not enough to replace the paid packet.

Resolution:

> Free preview exposes route, price, coverage ladder, reason to buy/not buy, known gaps, and sample receipts. It does not expose full claim set, full evidence lens, full packet body, or reconstructable paid output.

### 10.8 Schema-first vs speed

Potential tension:

> Schema-first can slow implementation.

Resolution:

> Use P0 schemas with permissive internal extension fields but strict public surfaces. Freeze external contracts first; let internal JPCIR carry `experimental` only if blocked from release capsule.

## 11. Merge diff into master plan

### 11.1 Add to section 18 or new section 19

Merge-ready wording:

```text
Implementation architecture must avoid subsystem sprawl. Evidence Product OS is implemented first as a JPCIR-centered compiler pipeline, not as multiple services. P0 modules are schemas, validators, pure compiler passes, generated surfaces, release capsule manifests, and machine-readable execution graphs. Official Evidence Graph remains an internal/offline evidence model; production receives only compiled Evidence Lens assets inside immutable Release Capsules.
```

### 11.2 Add P0 module boundary table

Add this module list to the master plan P0 implementation section:

```text
jpcir, policy, evidence, composer, packet, billing, capsule, surface, execution, aws_factory
```

Rules:

- module exchange is JPCIR only
- surfaces are generated, not authoritative
- production runtime has no AWS dependency
- composer cannot make factual claims
- packet compiler cannot fetch sources
- release capsule cannot contain raw/private/cold artifacts

### 11.3 Add P0 artifact list

Add:

```text
schemas/jpcir/*
invariants/registry.yaml
compilers/pass_manifest.yaml
fixtures/golden/*
fixtures/negative/*
execution_graph/p0_implementation.graph.yaml
reports/p0_preflight_report.json
capsules/rc1/release_capsule_manifest.json
surface_hash_mesh_report.json
runtime_dependency_firewall_report.json
golden_agent_replay_report.json
noop_aws_plan.json
```

### 11.4 Replace implementation order with smarter order

```text
1. Inventory existing public/API/MCP/proof/pricing surfaces.
2. Freeze P0 external packet envelope.
3. Define JPCIR header and P0 record schemas.
4. Implement canonicalization/hash/validator harness.
5. Implement invariant registry and forbidden phrase gates.
6. Implement minimal policy firewall.
7. Implement receipt/claim/gap/no-hit/evidence-lens compiler passes.
8. Implement agent_purchase_decision and cheapest sufficient route solver.
9. Implement capability contract compiler.
10. Implement public packet compiler for RC1 packets.
11. Implement billing consent/cap/accepted-artifact ledger.
12. Implement Release Capsule manifest and activation gates.
13. Implement Agent Surface Compiler from capability contract.
14. Implement execution_graph compiler and AI action ledger.
15. Generate no-op AWS plan and accepted artifact contracts.
16. Run local preflight and golden agent replay.
17. Ship RC1 capsule.
18. Start AWS guardrail/canary/full run after explicit AWS execution authorization.
```

### 11.5 Add release blockers

Add these blockers:

- Any public surface not generated from active capability contract.
- Any module crossing boundary with non-JPCIR ad hoc structure.
- Any factual claim generated by Output Composer.
- Any source fetch performed by Public Packet Compiler.
- Any paid packet executable without consent envelope and scoped cap token.
- Any Release Capsule without JPCIR/capability/catalog hash mesh.
- Any Release Capsule with AWS runtime dependency, raw CSV, raw screenshot archive, or cold evidence graph.
- Any no-hit without scoped expiring no-hit lease.
- Any generated surface disagreeing on packet id, price, flag, or no-hit policy.

## 12. Machine-readable merge envelope

```yaml
merge_envelope:
  review_id: "aws_smart_methods_round3_13_implementation_architecture"
  verdict: "conditional_pass"
  merge_required: true
  replaces:
    - "service-sprawl interpretation of Evidence Product OS"
    - "manual implementation runbook as canonical plan"
    - "ad hoc packet JSON between modules"
  adds:
    - "JPCIR-centered compiler pipeline"
    - "minimal module boundary map"
    - "P0 schema freeze"
    - "compiler pass contract"
    - "AI-executable implementation graph"
    - "schema-level and capsule-level feature flags"
    - "shadow migration from existing surfaces"
  no_go_if_missing:
    - "jpcir_header.schema.json"
    - "invariant_registry"
    - "policy_firewall_minimal"
    - "evidence_lens_record"
    - "agent_purchase_decision_record"
    - "capability_contract_record"
    - "release_capsule_manifest"
    - "surface_hash_mesh_report"
    - "runtime_dependency_firewall_report"
    - "execution_graph"
  p0_modules:
    - "jpcir"
    - "policy"
    - "evidence"
    - "composer"
    - "packet"
    - "billing"
    - "capsule"
    - "surface"
    - "execution"
    - "aws_factory"
  p0_flags_hard_false:
    - "request_time_llm_fact_generation_enabled"
    - "real_csv_to_aws_enabled"
    - "live_aws_runtime_lookup_enabled"
    - "public_raw_screenshot_archive_enabled"
  aws_execution_allowed_now: false
```

## 13. AI executor instruction bundle

When an AI implementation agent receives this plan, it should operate as follows:

```yaml
ai_executor_instruction_bundle:
  primary_goal: "Implement P0 JPCIR-centered compiler pipeline and release capsule gates."
  prohibited_actions:
    - "run AWS CLI/API/SDK"
    - "create AWS resources"
    - "store or upload real user CSV"
    - "add request-time LLM factual generation"
    - "create production AWS runtime dependency"
    - "hand-edit public surfaces without regenerating from capability contract"
  required_first_reads:
    - "master execution plan"
    - "round3_01_meta_architecture"
    - "round3_04_evidence_data_model"
    - "round3_11_release_runtime_capsule"
    - "round3_12_developer_runbook"
    - "this file"
  implementation_mode:
    - "smallest module boundary"
    - "schema first"
    - "pure compiler passes"
    - "negative fixtures before broad feature work"
    - "generated surfaces only"
    - "machine-readable execution graph"
  completion_evidence:
    - "tests pass"
    - "negative fixtures fail as expected"
    - "release capsule fixture validates"
    - "surface hash mesh matches"
    - "runtime dependency firewall passes"
    - "golden agent replay passes"
    - "no AWS command was executed"
```

## 14. Final recommendation

Adopt this review.

The current plan is strong enough conceptually, but implementation must be compressed into a compiler architecture. Otherwise the named ideas can turn into too many independent modules and slow the actual launch.

The smart implementation shape is:

```text
JPCIR schemas
  -> invariant and policy gates
  -> evidence compiler passes
  -> outcome/packet compiler passes
  -> capability contract
  -> release capsule
  -> generated agent surfaces
  -> AI execution graph
```

This preserves the advanced ideas while keeping RC1 implementable and safe. It also aligns with the user's premise that AI performs implementation/execution: the canonical artifact becomes a machine-readable graph and validation system, not a human checklist.

