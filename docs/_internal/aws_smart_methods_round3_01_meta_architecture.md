# AWS smart methods round 3 review 01: meta-architecture

Date: 2026-05-15  
Role: Meta-architecture review  
Status: planning review only; no AWS CLI/API/resource operation executed  
Output file: `docs/_internal/aws_smart_methods_round3_01_meta_architecture.md`

## 0. Inputs reviewed

Primary inputs:

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- `docs/_internal/aws_final_12_review_integrated_smart_methods_2026-05-15.md`
- `docs/_internal/aws_smart_methods_round2_integrated_2026-05-15.md`

Assumed existing smart-method baseline:

- `Release Capsule`
- `Official Evidence Knowledge Graph`
- `Bitemporal Claim Graph`
- `No-Hit Lease Ledger`
- `Output Composer`
- `Public Packet Compiler`
- `AWS Artifact Factory Kernel`
- `Probabilistic Budget Leasing`
- `Policy Decision Firewall`
- `Capability Matrix Manifest`
- `Golden Agent Session Replay`
- `Zero-AWS Posture Attestation Pack`

## 1. Verdict

The current plan is coherent. No fatal contradiction was found.

However, the plan can be made materially smarter by adding one higher-level meta-architecture above the existing components:

> `jpcite Evidence Product Operating System`

This is not another packet, crawler, or AWS job layer. It is the system-level architecture that coordinates:

- end-user task demand
- AI agent purchase decisions
- public official evidence
- policy and terms gates
- AWS budget and artifact production
- packet compilation
- release capsule activation
- zero-bill teardown

The key improvement is to stop treating the existing smart components as separate modules that happen to exchange files. They should be connected through one shared contract:

> `JPCIR`: jpcite Product Compiler Intermediate Representation

`JPCIR` is the typed intermediate representation that moves through the whole service:

```text
agent task
-> demand record
-> output gap map
-> source candidate plan
-> evidence observation
-> claim derivation DAG
-> policy decision
-> packet plan
-> public packet
-> agent purchase decision
-> release capsule
-> capability matrix
-> zero-bill attestation
```

This is smarter than adding more individual features because it prevents drift between product, evidence, AWS execution, public proof, MCP/API, and release.

## 2. The proposed meta-architecture

Adopt this as the top-level architecture:

```text
jpcite Evidence Product Operating System

1. Demand Plane
   agent_task_intake
   buyer_policy_profile
   outcome_ladder
   agent_purchase_decision

2. Evidence Plane
   Official Evidence Knowledge Graph
   Source Twin Registry
   Bitemporal Claim Graph
   No-Hit Lease Ledger
   Claim Derivation DAG

3. Policy Plane
   Policy Decision Firewall
   data class / taint tracking
   source terms revocation graph
   public proof minimizer

4. Compilation Plane
   Output Composer
   Public Packet Compiler
   Proof-Carrying Packet Compiler
   Evidence Graph Compiler

5. Execution Plane
   AWS Artifact Factory Kernel
   Probabilistic Budget Leasing
   Canary Economics
   Service-Mix Firewall
   Rolling External Exit Bundle

6. Release Plane
   Release Capsule
   Dual Pointer Runtime
   Capability Matrix Manifest
   Agent Surface Compiler
   Zero-AWS Posture Attestation Pack

7. Audit Plane
   Decision Ledger
   lineage ledger
   cost ledger
   trust receipt
   release gate reports
```

The new concepts introduced by this review are:

1. `JPCIR`
2. `Evidence Product Operating System`
3. `Decision Ledger`
4. `Invariant Registry`
5. `Capability Contract Compiler`
6. `Value-Cost-Policy Optimizer`
7. `Twin Loop Architecture`
8. `Product Surface Single Source of Truth`
9. `Public Value Minimization Rule`
10. `Failure-to-Asset Pipeline`

Each is explained below.

## 3. New smart method 1: JPCIR

### 3.1 What it is

`JPCIR` is the typed intermediate representation between all major components.

Current risk:

- source jobs can produce artifacts that packet code cannot use
- packet schemas can drift from proof pages
- MCP/OpenAPI examples can drift from production
- AWS artifacts can be expensive but not releaseable
- policy checks can happen too late
- release capsules can expose a capability the compiler cannot safely satisfy

`JPCIR` solves this by requiring every stage to read and write a stable typed record, not ad hoc JSON.

### 3.2 Core JPCIR records

Minimum records:

```text
DemandRecord
BuyerPolicyProfile
OutputGapRecord
SourceCandidateRecord
CapturePlanRecord
EvidenceObservationRecord
SourceReceiptRecord
ClaimCandidateRecord
ClaimDerivationRecord
SupportStateRecord
NoHitLeaseRecord
PolicyDecisionRecord
PacketPlanRecord
CompiledPacketRecord
AgentPurchaseDecisionRecord
ReleaseCapsuleManifest
CapabilityMatrixRecord
ZeroBillAttestationRecord
```

### 3.3 Example shape

```json
{
  "jpcir_version": "2026-05-15.r3",
  "record_type": "PolicyDecisionRecord",
  "record_id": "pdr_...",
  "input_record_ids": ["claim_...", "receipt_...", "source_profile_..."],
  "decision": "allow_public_packet_claim",
  "data_class": "public_official_observation",
  "support_state": "direct_official_receipt",
  "visibility": {
    "api": "allowed",
    "mcp": "allowed",
    "proof_page": "minimized",
    "public_search": "summary_only"
  },
  "blocked_reasons": [],
  "required_caveats": ["no_hit_not_absence"],
  "created_at": "2026-05-15T00:00:00Z"
}
```

### 3.4 Why it is smarter

It makes the product a compiler system instead of a pile of output scripts.

Every later system can ask:

- which demand caused this artifact?
- which source receipt supports this claim?
- which policy decision allowed it?
- which packet uses it?
- which release capsule exposed it?
- which capability matrix advertised it?
- which zero-bill bundle preserved it after AWS teardown?

### 3.5 Merge into master plan

Add a new subsection before current `## 19. Immediate implementation order after this plan`:

```text
## 18.7 Round 3 meta-architecture: JPCIR and Evidence Product Operating System
```

Add:

- `JPCIR` is the mandatory typed intermediate representation.
- AWS jobs may only emit artifacts that can be converted into JPCIR records.
- Public packet generation may only read policy-approved JPCIR records.
- Release capsules may only expose capabilities derived from compiled JPCIR manifests.

Amend implementation order:

1. Define `JPCIR` record schemas and invariant registry.
2. Add validators for every JPCIR transition.
3. Only then patch packet contract/catalog.

Existing item 1 in section 19 becomes item 3 or 4.

### 3.6 Contradiction handling

Potential contradiction:

- Existing plan says `Official Evidence Knowledge Graph` is the internal evidence model.

Resolution:

- Keep it. `JPCIR` is not a replacement for the graph. It is the exchange format and compilation boundary.
- The graph stores and derives evidence; `JPCIR` records are the auditable products moving between systems.

## 4. New smart method 2: Evidence Product Operating System

### 4.1 What it is

The current architecture has many strong pieces. The missing top-level shape is an operating system that decides which piece should act and when.

Adopt:

```text
Evidence Product Operating System =
  Demand Plane
  Evidence Plane
  Policy Plane
  Compilation Plane
  Execution Plane
  Release Plane
  Audit Plane
```

### 4.2 Why it is smarter

Without this OS layer, each smart method can optimize locally:

- AWS optimizes for accepted artifacts
- source discovery optimizes for coverage
- output composer optimizes for purchase conversion
- proof compiler optimizes for safety
- release capsule optimizes for deploy stability

Those local goals can conflict.

The OS layer imposes one global objective:

```text
maximize source-backed paid output value
subject to:
  no unsupported claims
  no private CSV in AWS
  no request-time factual LLM
  no access bypass
  no exact credit-face-value spend target
  no ongoing AWS bill
  no public leakage beyond decision value
```

### 4.3 Merge into master plan

Add this as the first paragraph of the new section 18.7:

> The top-level architecture is `jpcite Evidence Product Operating System`. Existing components are planes inside this OS, not independent subsystems.

Then list the seven planes and state that all implementation tasks must identify which plane owns the contract.

### 4.4 Contradiction handling

Potential contradiction:

- The current plan presents AWS as a one-time artifact factory.
- An "operating system" might sound like permanent runtime infrastructure.

Resolution:

- The OS is a product architecture, not a permanent AWS runtime.
- Only the Execution Plane uses AWS temporarily.
- Demand, compilation, release, and serving continue outside AWS after teardown.

## 5. New smart method 3: Decision Ledger

### 5.1 What it is

`Decision Ledger` is an append-only ledger of important decisions across the whole system.

It records:

- why a packet was recommended
- why a source was expanded or suppressed
- why a claim was allowed or blocked
- why AWS budget was leased to a job
- why a release capsule was activated
- why a capability is visible, preview-only, paid, or blocked
- why AWS teardown is considered complete

### 5.2 Why it is smarter

The current plan has many ledgers:

- budget ledger
- artifact manifest
- source terms ledger
- no-hit ledger
- release gate report
- zero-bill ledger

That is good, but they can diverge.

The `Decision Ledger` becomes the parent ledger. Specialized ledgers remain, but every important action gets one decision record.

### 5.3 Example

```json
{
  "decision_id": "dec_...",
  "decision_type": "source_scale_up",
  "subject": "source_candidate:mlit_negative_info",
  "inputs": {
    "output_gap_ids": ["gap_vendor_disposition_001"],
    "canary_artifact_yield": 0.82,
    "cost_per_accepted_artifact_usd": 0.014,
    "terms_status": "allowed_with_minimized_public_output",
    "policy_decision_id": "pdr_..."
  },
  "decision": "scale_up",
  "limits": {
    "budget_lease_usd": 320,
    "max_parallel_shards": 80,
    "capture_methods": ["static_html", "pdf_text", "playwright_canary_only"]
  },
  "rollback_or_stop": "source_circuit_breaker"
}
```

### 5.4 Merge into master plan

Add under section 17.1 and 18.4:

- budget leases, source scale-up, service quarantine, panic snapshot, and teardown must each emit `DecisionLedger` records.

Add under release section:

- release activation and rollback must reference `DecisionLedger` records.

### 5.5 Contradiction handling

Potential contradiction:

- Extra ledger sounds like extra implementation overhead before AWS can start.

Resolution:

- Start with a minimal JSONL ledger.
- Do not block RC1 on a full database.
- Required fields only: `decision_id`, `decision_type`, `inputs`, `decision`, `owner_plane`, `created_at`, `blocking_invariants_checked[]`.

## 6. New smart method 4: Invariant Registry

### 6.1 What it is

`Invariant Registry` is a machine-checkable list of non-negotiable rules.

The master plan already states many rules in prose. They should become executable invariants.

Examples:

```text
INV-AWS-001: control_spend_usd must be < 19300 before new work.
INV-AWS-002: AWS resource must have teardown verification path before create.
INV-CSV-001: real user CSV bytes must not enter AWS.
INV-CLAIM-001: public claims require receipt support or explicit gap.
INV-NOHIT-001: no-hit must be scoped and leased.
INV-LLM-001: request-time LLM cannot create factual claims.
INV-PROOF-001: proof page must not expose full paid output.
INV-RELEASE-001: production must pass smoke without AWS.
INV-ZERO-001: S3 final archive is not allowed under zero-bill default.
INV-WORD-001: forbidden external wording blocks release.
```

### 6.2 Why it is smarter

This prevents later implementation from interpreting the plan loosely.

The system should fail closed before:

- AWS canary
- AWS full run
- artifact import
- packet compile
- proof page generation
- MCP/OpenAPI publication
- release capsule activation
- AWS teardown

### 6.3 Merge into master plan

Amend section 19:

New first task:

```text
1. Create the Invariant Registry and JPCIR schema validators.
```

Then existing contract/catalog work follows.

Add release blocker:

```text
NO-GO if invariant registry cannot be run locally without AWS.
```

### 6.4 Contradiction handling

Potential contradiction:

- Existing plan wants fast production.
- Invariant Registry could slow down.

Resolution:

- Implement only P0 invariants first.
- P0 invariants are mostly string/schema/path checks and do not require heavy infrastructure.
- This speeds production by reducing late-stage reversals.

## 7. New smart method 5: Capability Contract Compiler

### 7.1 What it is

The plan already has `Capability Matrix Manifest` and `Agent Surface Compiler`.

The smarter meta-layer is `Capability Contract Compiler`:

```text
Release Capsule + JPCIR manifests + policy decisions
-> capability contract
-> MCP tools
-> OpenAPI subset
-> llms.txt
-> .well-known
-> proof pages
-> pricing preview examples
-> agent decision pages
```

The contract is the source of truth. Public surfaces are generated from it.

### 7.2 Why it is smarter

It prevents a common failure:

- MCP says a packet is available
- OpenAPI has different params
- proof page says another price
- `llms.txt` recommends a blocked packet
- release capsule points to old examples

### 7.3 Merge into master plan

Refine section 18.5:

- `Agent Surface Compiler` should read from `Capability Contract`, not directly from ad hoc catalog files.
- `Capability Matrix Manifest` is a compiled output, not the human-authored source.

Add an implementation item:

```text
Generate all agent-facing surfaces from one capability contract.
Do not hand-maintain MCP/OpenAPI/proof/pricing examples separately.
```

### 7.4 Contradiction handling

Potential contradiction:

- Existing plan says catalog is important.

Resolution:

- Keep catalog, but make it one input to the capability contract.
- The public-facing capability matrix is compiled from catalog + policy + release capsule + pricing + invariant checks.

## 8. New smart method 6: Value-Cost-Policy Optimizer

### 8.1 What it is

The plan currently has:

- `Artifact Value Density Scheduler`
- `Budget Token Market v2`
- `Probabilistic Budget Leasing`
- `Canary Economics`
- source circuit breakers
- `Output Composer`

These should not be separate optimizers.

Adopt a single `Value-Cost-Policy Optimizer` that produces decision records for:

- which packet to recommend
- which source to refresh
- which AWS job to lease budget to
- which capture method to try
- whether to ask a follow-up question
- whether to stop, defer, or abstain

### 8.2 Objective

Use a constrained optimizer:

```text
maximize expected_accepted_output_value
subject to:
  policy_decision == allow
  control_spend_usd + reserved_risk <= 19300
  public_value_minimization == pass
  teardown_path_known == true
  no private CSV in AWS
  no unsupported public claim
```

### 8.3 Why it is smarter

It unifies product and AWS economics.

Without this, AWS might spend on artifacts that are valuable in theory but do not improve agent purchase decisions or paid packet conversion.

### 8.4 Merge into master plan

Refine section 17.1 and 17.2:

- `Artifact Value Density Scheduler` becomes a subroutine of `Value-Cost-Policy Optimizer`.
- `output_gap_map`, `Canary Economics`, and `agent_recommendation_gain` feed the optimizer.
- AWS jobs must include `expected_packet_unlock_ids[]` and `expected_agent_decision_improvement`.

Add required AWS job metadata:

```text
expected_packet_unlock_ids[]
expected_gap_reduction_ids[]
expected_agent_decision_improvement
policy_precheck_id
budget_lease_id
teardown_resource_class
```

### 8.5 Contradiction handling

Potential contradiction:

- "Optimizer" can sound like autonomous revenue maximization.

Resolution:

- It is constrained by policy first.
- Revenue-only optimization is explicitly rejected.
- The optimizer may recommend "skip" or "ask follow-up" when buying would not materially improve the answer.

## 9. New smart method 7: Twin Loop Architecture

### 9.1 What it is

Separate the service into two loops:

```text
Build Loop:
  AWS Artifact Factory Kernel
  source canaries
  evidence generation
  packet fixtures
  external exit bundles
  zero-bill teardown

Serve Loop:
  Release Capsule runtime
  capability contract
  agent purchase decisions
  public packet compiler
  static proof and API/MCP surfaces
  no AWS runtime dependency
```

The loops share `JPCIR`, invariant tests, and release capsules.

### 9.2 Why it is smarter

It removes a persistent tension:

- AWS should run aggressively for one week.
- Production should remain stable and not depend on AWS.

The Build Loop can be noisy, expensive, and high-throughput. The Serve Loop is small, deterministic, and cheap.

### 9.3 Merge into master plan

Add to section 0 or 18.7:

> The architecture has a temporary Build Loop and a durable Serve Loop. They share contracts and artifacts, not runtime infrastructure.

Amend implementation order:

- build Serve Loop validators and capsule activation before AWS full run
- AWS full run may continue while Serve Loop deploys RC1
- only imported release capsules cross the boundary

### 9.4 Contradiction handling

Potential contradiction:

- Some watch products imply continuous updates.

Resolution:

- Watch products can run from post-AWS static/delta assets or future non-AWS/low-cost refreshes.
- During this credit run, AWS builds the first evidence baseline and delta machinery.
- Do not promise AWS-backed continuous watch after teardown.

## 10. New smart method 8: Product Surface Single Source of Truth

### 10.1 What it is

Adopt one source for all product-facing surfaces:

```text
Capability Contract
-> MCP
-> OpenAPI
-> proof pages
-> pricing page
-> examples
-> llms.txt
-> .well-known
-> release notes
-> internal tests
```

### 10.2 Why it is smarter

This directly supports GEO. AI agents penalize uncertainty and mismatch.

If every public surface has the same:

- packet id
- price cap
- approval token behavior
- no-hit caveat
- known gap policy
- sample skeleton
- capability status
- catalog hash

then agents can safely recommend the service.

### 10.3 Merge into master plan

Refine section 18.5:

- `Drift-Free Catalog Hash Mesh` should be generated by Product Surface SOT.
- Public examples are compiled artifacts, not handwritten examples.

Add release blocker:

```text
NO-GO if MCP/OpenAPI/proof/pricing/llms/.well-known are generated from different sources or have mismatched hashes.
```

### 10.4 Contradiction handling

Potential contradiction:

- Existing repo may have separate files for these surfaces.

Resolution:

- Keep separate output files.
- Make them generated from one contract.
- Hand-edited emergency patches must fail drift checks unless backported to the contract.

## 11. New smart method 9: Public Value Minimization Rule

### 11.1 What it is

The plan already says proof pages should become `agent_decision_page`s and not leak full paid output.

Make this a meta-architecture rule:

> Public surfaces should reveal enough value for a rational AI agent to recommend purchase, but not enough to substitute for the paid packet.

### 11.2 Practical rule

For each packet:

```text
free public proof page:
  allowed:
    packet purpose
    source families used
    example skeleton
    caveats
    coverage ladder
    price cap
    why buy / why not buy
    one or two synthetic examples

  forbidden:
    full current answer
    full raw screenshot
    full raw OCR
    row-level data
    paid claim set
    reconstructable complete output
```

### 11.3 Why it is smarter

It solves the GEO/product tension:

- AI agents need enough information to recommend.
- The business needs paid conversion.

### 11.4 Merge into master plan

Add to section 17.4 and 18.6:

- `public_value_minimization` is a policy decision.
- `agent_decision_page` must pass a substitution-risk check.

Add to release blockers:

```text
NO-GO if free public surfaces can reconstruct a paid packet for current real targets.
```

### 11.5 Contradiction handling

Potential contradiction:

- Public proof pages need evidence.

Resolution:

- Show source classes, skeletons, synthetic examples, and minimized evidence graph.
- Do not show full target-specific paid claim sets.

## 12. New smart method 10: Failure-to-Asset Pipeline

### 12.1 What it is

The plan already has `failure-value ledger`.

Make it a first-class pipeline:

```text
failed fetch
failed schema parse
terms blocked
low OCR quality
source conflict
no-hit lease
stale source
forbidden wording candidate
agent replay failure
release drift failure
-> accepted non-claim asset
```

Not every failure should become a claim, but many failures are valuable assets.

### 12.2 Valuable failure assets

Examples:

- `blocked_source_terms_record`
- `source_schema_change_record`
- `playwright_blocked_observation_record`
- `ocr_quality_gap_record`
- `no_hit_scope_record`
- `agent_replay_failure_case`
- `catalog_drift_failure_case`
- `packet_abstention_fixture`
- `source_refresh_needed_record`

### 12.3 Why it is smarter

The AWS credit run can still produce durable value even when sources are messy.

This matters because Japanese public information sources will have:

- PDFs
- inconsistent HTML
- old Excel files
- local government pages
- changing URLs
- ambiguous terms
- dead links
- OCR noise

### 12.4 Merge into master plan

Add to AWS artifact list in section 1:

- non-claim failure assets
- abstention fixtures
- source blocked/terms gap records
- schema drift records

Add to `AWS Artifact Factory Kernel`:

- every failed job must emit either a retryable failure, a blocked asset, a gap asset, or a discarded noisy event with reason.

### 12.5 Contradiction handling

Potential contradiction:

- The system sells outputs, not failures.

Resolution:

- Failure assets are not sold as final user outputs.
- They improve `known_gaps[]`, source suppression, release tests, and future packet reliability.

## 13. How the new meta-architecture maps to existing components

| Existing component | Keep? | New parent / refinement |
|---|---:|---|
| `Release Capsule` | Yes | Release Plane unit; generated from JPCIR/capability contract |
| `Official Evidence Knowledge Graph` | Yes | Evidence Plane store; exchanges via JPCIR |
| `Output Composer` | Yes | Compilation Plane recommender; cannot make claims |
| `Public Packet Compiler` | Yes | Compilation Plane claim compiler; reads policy-approved JPCIR |
| `AWS Artifact Factory Kernel` | Yes | Execution Plane; temporary Build Loop only |
| `Policy Decision Firewall` | Yes | Policy Plane; emits PolicyDecisionRecord |
| `Capability Matrix Manifest` | Yes | Compiled output from Capability Contract |
| `Budget Token Market v2` | Yes | Subsystem of Value-Cost-Policy Optimizer |
| `No-Hit Lease Ledger` | Yes | Evidence Plane + policy input |
| `Golden Agent Session Replay` | Yes | Release Plane gate and Demand Plane fixture source |

## 14. Required master-plan merge

### 14.1 Add new section

Add the following to the master plan before `## 19. Immediate implementation order after this plan`:

```text
## 18.7 Round 3 meta-architecture

The top-level architecture is `jpcite Evidence Product Operating System`.
It contains Demand, Evidence, Policy, Compilation, Execution, Release, and Audit planes.

All planes exchange typed `JPCIR` records.
The `Decision Ledger` records why major actions were taken or blocked.
The `Invariant Registry` makes non-negotiable plan constraints executable.
The `Capability Contract Compiler` generates the public agent-facing surfaces from one contract.
The `Value-Cost-Policy Optimizer` unifies packet value, source expansion, and AWS budget leasing.
The architecture has a temporary Build Loop and durable Serve Loop.
Public surfaces follow the Public Value Minimization Rule.
Failures become non-claim assets where useful.
```

### 14.2 Amend implementation order

Replace current section 19 order with this shape:

1. Define P0 `Invariant Registry`.
2. Define P0 `JPCIR` schemas.
3. Define `Decision Ledger` minimal JSONL format.
4. Define `Capability Contract` schema.
5. Patch product contract/catalog to emit/read JPCIR-compatible packet envelope, pricing, receipts, gaps, no-hit, algorithm trace, and `gap_coverage_matrix[]`.
6. Add validators for JPCIR transitions, invariants, forbidden wording, AWS runtime dependency, raw CSV leakage, no-hit misuse, and pricing drift.
7. Build artifact import/manifest/checksum validators.
8. Build static proof renderer and `agent_decision_page` renderer.
9. Add free catalog/routing/cost-preview surfaces as `agent_purchase_decision`.
10. Add limited paid RC1 packets.
11. Generate MCP/OpenAPI/llms/.well-known/proof/pricing from `Capability Contract`.
12. Create AWS guardrail/control-plane scripts around `AWS Artifact Factory Kernel`.
13. Run AWS canary.
14. Start self-running standard lane.
15. Release RC1 while AWS continues.
16. Import RC2/RC3 release capsules.
17. Export final artifacts through Rolling External Exit Bundle.
18. Teardown AWS to zero-bill posture.
19. Produce Zero-AWS Posture Attestation Pack.

### 14.3 Add new release blockers

Add these NO-GO conditions:

- `JPCIR` validators cannot run locally without AWS.
- Invariant Registry cannot run locally without AWS.
- public surfaces are not generated from one capability contract.
- MCP/OpenAPI/proof/pricing/llms/.well-known hashes disagree.
- a release capsule exposes a capability that lacks policy-approved JPCIR support.
- free public surfaces can reconstruct a current paid packet.
- AWS job lacks `expected_packet_unlock_ids[]`, `policy_precheck_id`, or teardown class.
- failed AWS jobs disappear without becoming retryable, blocked, gap, or discarded-with-reason records.

## 15. Contradiction review

### 15.1 `JPCIR` vs `Official Evidence Knowledge Graph`

No contradiction.

Correction:

- Evidence graph is the internal model.
- `JPCIR` is the exchange and compilation representation.

### 15.2 `Evidence Product OS` vs "AWS is one-time"

No contradiction if clearly scoped.

Correction:

- The OS is the product architecture.
- AWS is only the temporary Execution Plane in the Build Loop.

### 15.3 `Decision Ledger` vs fast production

Conditional risk.

Correction:

- Start with minimal append-only JSONL.
- Do not require full event-sourcing infrastructure for RC1.

### 15.4 `Capability Contract Compiler` vs existing catalog

No contradiction.

Correction:

- Catalog remains an input.
- Capability Contract is the compiled product-facing SOT.

### 15.5 `Value-Cost-Policy Optimizer` vs anti-upsell

Potential contradiction if implemented as revenue maximizer.

Correction:

- Policy and user cap constraints come first.
- Optimizer may choose skip, ask follow-up, or cheapest sufficient route.
- `reason_not_to_buy` remains required.

### 15.6 `Twin Loop Architecture` vs watch/delta products

Potential contradiction.

Correction:

- This AWS credit run builds baseline and delta machinery.
- Do not imply continuous AWS-backed watch after zero-bill teardown.
- Future watch can use static assets, low-cost non-AWS jobs, or explicitly approved future infra.

### 15.7 `Public Value Minimization` vs GEO discovery

No contradiction.

Correction:

- GEO surfaces should be rich enough for purchase decisions, not complete enough to replace paid packets.

### 15.8 `Failure-to-Asset Pipeline` vs sellable outputs

No contradiction.

Correction:

- Failure assets are internal quality/gap assets, not paid final outputs.

### 15.9 `Invariant Registry` vs planning flexibility

No contradiction.

Correction:

- P0 invariants only first.
- Additional invariants can be added as the implementation hardens.

### 15.10 `Product Surface SOT` vs manual emergency fixes

Potential operational tension.

Correction:

- Emergency public fixes are allowed only if backported to the capability contract before release is marked healthy.

## 16. Concrete P0 artifact list from this review

Create these before AWS full run:

```text
schemas/jpcir/demand_record.schema.json
schemas/jpcir/source_candidate_record.schema.json
schemas/jpcir/evidence_observation_record.schema.json
schemas/jpcir/source_receipt_record.schema.json
schemas/jpcir/claim_derivation_record.schema.json
schemas/jpcir/policy_decision_record.schema.json
schemas/jpcir/packet_plan_record.schema.json
schemas/jpcir/compiled_packet_record.schema.json
schemas/jpcir/agent_purchase_decision_record.schema.json
schemas/jpcir/release_capsule_manifest.schema.json
schemas/jpcir/capability_matrix_record.schema.json

data/invariants/p0_invariant_registry.json
data/capability_contract/rc1_capability_contract.json
data/decision_ledger/README.md
tools/validate_jpcir_transition.*
tools/validate_invariants.*
tools/compile_agent_surfaces.*
tools/check_public_value_minimization.*
```

Path names are suggestions. The implementation should adapt to the repo layout before creating files.

## 17. Minimal RC1 version

Do not overbuild the full OS before launch.

RC1 can use:

- JSON Schema for JPCIR
- JSONL for Decision Ledger
- static JSON for Invariant Registry
- static JSON for Capability Contract
- local scripts for validation and compilation
- pointer file for Release Capsule activation

Do not require:

- graph database
- streaming event bus
- complex optimizer service
- permanent AWS control database after teardown
- full UI for every ledger

## 18. Final recommendation

Adopt the round 3 meta-architecture.

The plan should be framed as:

> jpcite is an Evidence Product Operating System for AI agents. It compiles end-user tasks into cheapest sufficient, policy-safe, proof-carrying Japanese public-information outputs. AWS is a temporary Build Loop that manufactures evidence assets under budget leases. Production is a durable Serve Loop that activates verified Release Capsules without AWS runtime dependency.

This is smarter than the current plan in one important way:

- Current plan has excellent components.
- Round 3 makes those components share one typed representation, one decision ledger, one invariant registry, and one capability contract.

That reduces implementation drift, makes AWS spend more directly tied to sellable outputs, improves GEO trust, and makes zero-bill teardown safer.
