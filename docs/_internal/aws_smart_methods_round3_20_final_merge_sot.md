# AWS smart methods round 3 review 20/20: final merge SOT

Date: 2026-05-15

Scope:
- Integrate `aws_smart_methods_round3_01` through readable available Round3 files.
- AWS CLI/API/resource operations are prohibited and were not performed.
- This document is the only intended output for this review.

Input status:
- Found and reviewed: `round3_01` through `round3_18`.
- `round3_19` was not present locally at review time.
- This merge therefore uses the available Round3 evidence and explicitly avoids inventing a separate `round3_19` position.

Final verdict:
- **PASS with required merge.**
- The plan is now strong enough conceptually.
- The key remaining risk is not missing source families. The risk is implementation sprawl.
- The master plan should be merged around one compact operating model: `Outcome -> JPCIR -> Policy -> Evidence Lens -> Packet -> Agent Decision -> Consent/Billing -> Release Capsule -> AI Execution Graph -> AWS Artifact Factory`.

---

## 1. Final Master SOT Chapter To Append

Append this short SOT chapter to the master execution plan.

```text
Round3 Final SOT: Evidence Product OS, AI-executed

jpcite is the public-evidence transaction layer for AI agents in Japan.
It does not sell a large public-information database as the product.
It sells small, capped, official-source-backed outcome contracts that AI
agents can recommend, preview, consent, execute, retrieve, and explain to
end users.

The canonical architecture is Evidence Product OS implemented as a
JPCIR-centered compiler pipeline. P0 must not become a set of independent
services. P0 is schemas, validators, pure compiler passes, generated
surfaces, release capsule manifests, and machine-readable execution graphs.

The buying layer is Outcome Contract Catalog. The execution layer remains
packet/API/MCP. For every task, jpcite must recommend the cheapest sufficient
outcome, show the coverage ladder, explain why not to buy when appropriate,
require a scoped cap token before paid execution, and charge only accepted
artifacts.

The evidence layer is Official Evidence Ledger -> Evidence Lens -> Public
Packet Compiler. It is not a live production truth database. AWS may build
and query evidence during the temporary credit run, but production activates
only immutable Release Capsules containing policy-approved hot assets,
minimal Evidence Lenses, source receipts, claim refs, known gaps, no-hit
leases, proof surrogates, capability matrices, and trust manifests.

The policy layer is mandatory before public surfaces. Legal Policy Firewall,
Privacy Taint Lattice, Source Terms Contract, Public Proof Surrogate Compiler,
Mosaic Risk Guard, Legal Wording Compiler, Abuse Risk Control Plane, and
Trust Surface Compiler decide what can be captured, compiled, shown, sold,
or blocked. Unknown terms, sensitive taint, unsafe wording, paid leakage,
or source access risk must fail closed into blocked/gap artifacts.

The agent layer is Agent Decision Protocol:
task -> route -> preview decision -> consent -> scoped cap token -> execute
-> retrieve. P0 public MCP/OpenAPI should stay a four-tool facade:
route, preview, execute, get. Full/expert tools are not the default GEO
surface.

The release layer is Capsule Runtime. Production reads pointer-selected
Release Capsules, not AWS resources. All public surfaces, including llms,
.well-known, MCP, OpenAPI, proof pages, pricing, examples, trust receipts,
and no-hit wording, are generated from the active capsule/capability
contract. Rollback is a pointer switch and must not require AWS.

The AWS layer is a temporary Artifact Factory Kernel, not runtime
infrastructure. It spends the credit through accepted-artifact futures,
probabilistic budget leases, service risk escrows, spend corridor control,
rolling external exit bundles, and zero-bill proof ledgers. The spend goal is
maximum accepted artifact value under the USD 19,300 control line, not exact
USD 19,493.94 burn.

The execution layer assumes AI performs implementation and operation. Human
implementation tasks are removed. The canonical plan is a machine-readable
execution graph with AI executor instruction bundles, no-op AWS plans,
preflight scorecards, stop gates, rollback state machines, autonomous action
ledgers, and merge envelopes. If a gate cannot be satisfied by AI and
deterministic checks, the state becomes blocked/gap/deferred; it must not
silently become a manual implementation dependency.
```

---

## 2. Canonical Merge Model

The master plan should consolidate Round3 into these canonical layers.

| Layer | Canonical concept | What it replaces or absorbs |
|---|---|---|
| Product | `Outcome Contract Catalog` | packet-only sales framing |
| Representation | `JPCIR` | ad hoc packet/source/billing JSON between modules |
| Policy | `Policy Decision Firewall v2` | late legal/privacy review |
| Evidence | `Official Evidence Ledger -> Evidence Lens` | production graph DB or truth DB framing |
| Source | `Source Capability Contract` | broad crawl because a source family is important |
| Compilation | `Output Composer + Public Packet Compiler` | one-off hand-written output generation |
| Agent | `Agent Decision Protocol` | raw MCP/OpenAPI tool list |
| Billing | `Billing Contract Layer` | charge-per-call ambiguity |
| Release | `Release Capsule v2 + Capsule Runtime` | deploy generated files without activation contract |
| Trust | `Trust Surface Compiler` | hand-written trust badges/copy |
| Abuse | `Abuse Risk Control Plane` | generic rate limiting |
| Learning | `Privacy-Safe Learning Control Plane` | raw telemetry or no feedback loop |
| AWS | `Artifact Factory Kernel` | plain Batch jobs |
| Execution | `AI Execution Control Plane` | human runbook / manual implementation assumptions |

Non-negotiable invariants:
- `request_time_llm_fact_generation_enabled=false`
- `real_csv_to_aws_enabled=false`
- `live_aws_runtime_lookup_enabled=false`
- `public_raw_screenshot_archive_enabled=false`
- `generic_trust_credit_safety_score_enabled=false`
- `no_hit_absence_claim_enabled=false`
- `manual_public_surface_edit_as_sot=false`

---

## 3. Implementation Order Correction

Replace the broad implementation order with this AI-executable sequence.

### Phase 0: Inventory and Contract Freeze

1. Inventory current public/API/MCP/proof/pricing surfaces.
2. Freeze P0 external packet envelope.
3. Freeze P0 outcome contract fields.
4. Freeze canonical tool names; `jpcite_preview_cost` is canonical.
5. Mark `agent_routing_decision` as free control, not paid product.

Exit gates:
- all current surfaces are mapped to catalog/capability ids.
- no duplicate canonical names remain on public P0 surfaces.
- master invariants are in machine-readable form.

### Phase 1: JPCIR and Invariant Foundation

1. Define common JPCIR object header and checksum rules.
2. Define P0 schemas:
   - `demand_record`
   - `outcome_contract`
   - `source_candidate_record`
   - `source_capability_contract`
   - `source_terms_contract`
   - `evidence_observation_record`
   - `source_receipt`
   - `claim_ref`
   - `temporal_envelope`
   - `known_gap`
   - `no_hit_lease`
   - `policy_decision`
   - `evidence_lens`
   - `agent_purchase_decision`
   - `billing_contract`
   - `consent_envelope`
   - `scoped_cap_token`
   - `compiled_packet`
   - `release_capsule_manifest`
   - `capability_matrix`
   - `execution_manifest`
   - `execution_graph`
3. Build invariant registry.
4. Build schema validation and canonicalization harness.

Exit gates:
- positive and negative fixtures exist for every P0 schema.
- invalid no-hit, unsafe wording, raw CSV leakage, paid leakage, and missing cap token fixtures fail.

### Phase 2: Policy, Trust, Abuse, and CSV Boundaries

1. Implement minimal Legal Policy Firewall v2.
2. Implement Privacy Taint Lattice.
3. Implement Source Terms Contract and revocation graph.
4. Implement Public Proof Surrogate Compiler.
5. Implement Mosaic Risk Guard.
6. Implement Legal Wording Compiler.
7. Implement Trust Surface Compiler language packs.
8. Implement Abuse Risk Control Plane P0:
   - preview exposure budget
   - paid output extraction guard
   - subject access ledger
   - cap token replay guard
   - source politeness decision
9. Implement CSV `PrivateFactCapsule`:
   - local-first parse preferred.
   - memory-only server fallback allowed only with no log/temp/db/AWS retention.
   - raw CSV, row-level details, payroll/bank/person files, and name-only joins are rejected for P0.

Exit gates:
- public proof cannot expose raw screenshots, raw DOM/HAR/OCR text, raw CSV, private joins, or paid conclusions.
- unknown terms or sensitive taint produce blocked/gap artifacts, not public claims.

### Phase 3: Evidence and Output Compiler

1. Implement Official Evidence Ledger as append-only/offline records.
2. Implement Evidence Lens Compiler.
3. Implement no-hit lease compiler.
4. Implement conflict bundle compiler.
5. Implement proof set optimizer minimal.
6. Implement Output Composer with no factual claim authority.
7. Implement Public Packet Compiler for RC1 packets.
8. Implement graph integrity gate.

P0 RC1 paid outcomes:
- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`

P0 optional if already cheap:
- `invoice_vendor_public_check`
- selected vendor/public baseline variant

Exit gates:
- every public claim has `claim_ref`, `source_receipt`, `temporal_envelope`, `policy_decision`, and gap/no-hit/conflict handling.
- no-hit is lease-scoped and expiring.
- composer cannot fetch sources or create facts.

### Phase 4: Agent Decision, Billing, and Product Packaging

1. Implement Outcome Contract Catalog.
2. Implement `outcome_contract -> packet` mapping compiler.
3. Implement `agent_purchase_decision`.
4. Implement cheapest sufficient route solver.
5. Implement coverage ladder quote.
6. Implement `reason_not_to_buy`.
7. Implement Billing Contract Layer.
8. Implement Consent Envelope.
9. Implement Scoped Cap Token v2/v3.
10. Implement Accepted Artifact Pricing.
11. Implement receipt reuse dividend in pricing metadata.

Exit gates:
- preview explains buy, no-buy, ask-first, cheapest sufficient route, cap, known gaps, and no-hit caveat.
- paid execute rejects missing, expired, replayed, over-scope, or over-cap tokens.
- accepted artifact required before charge.
- no accepted artifact means no charge or scoped void/refund record.

### Phase 5: Capsule Runtime and Generated Surfaces

1. Define Release Capsule v2 schema.
2. Define pointer set schema.
3. Define Capability Matrix v2.
4. Define hot/cold static DB manifest.
5. Implement Agent Surface Compiler:
   - `llms.txt`
   - `.well-known`
   - MCP P0 facade
   - agent-safe OpenAPI
   - proof pages
   - pricing pages
   - examples
   - trust receipts
   - agent decision pages
6. Implement surface parity hash mesh.
7. Implement AWS dependency firewall.
8. Implement pointer rollback.
9. Implement zero-AWS posture manifest.

Exit gates:
- all public surfaces are generated from active capability contract/capsule.
- UI, MCP, OpenAPI, proof, pricing, and `.well-known` agree on packet id, price, cap, flags, no-hit, and caveats.
- runtime has no AWS dependency.

### Phase 6: AI Execution Control Plane

1. Build plan-as-code execution manifest.
2. Build execution graph compiler.
3. Build AI executor instruction bundle generator.
4. Build no-op AWS command plan compiler.
5. Build dry-run capsule simulator.
6. Build spend and teardown simulator.
7. Build preflight scorecard.
8. Build approval/stop gate automata.
9. Build rollback state machine.
10. Build autonomous verification loop.
11. Build autonomous action ledger.
12. Build merge envelope checker.

Exit gates:
- generated Markdown view hash equals execution graph hash.
- execution graph hash equals execution manifest hash.
- no live AWS command bundle exists before AWS-ready preflight.
- rollback targets are state-machine verified, not prose-only.

### Phase 7: RC1 Production Before Full AWS

1. Generate RC1 capsule from local fixtures and minimal accepted public evidence.
2. Run local preflight.
3. Run Golden Agent Session Replay.
4. Run forbidden language lint.
5. Run proof leakage scan.
6. Run production smoke without AWS.
7. Activate RC1 by pointer.

Exit gates:
- agent can recommend, not recommend, explain price, preserve cap, explain no-hit, explain known gaps, and avoid legal/credit/safety conclusions.
- RC1 can run without AWS.

### Phase 8: AWS Artifact Factory Kernel

Only after the AI Execution Control Plane says AWS is ready:

1. Create no-op command plan first.
2. Create accepted artifact futures.
3. Reserve probabilistic budget leases.
4. Assign service risk escrows.
5. Price teardown debt before resource creation.
6. Launch canary.
7. Launch standard self-running lane.
8. Continue unattended only within Autonomous Operator Silence Mode.
9. Export rolling external exit bundles.
10. Drain.
11. Teardown simulation.
12. Teardown.
13. Post-teardown audit.
14. Produce zero-bill proof ledger.

AWS spend rule:

```text
maximize accepted artifact value under USD 19,300 control_spend_usd
```

Do not target exact USD 19,493.94 if it creates cash exposure.

---

## 4. AI-Only Execution Graph Revision

The master plan must remove hidden human implementation dependencies.

### 4.1 Semantics Change

`human_review_required` must not mean "a human developer must perform a step."

Use these meanings:

| Field/state | Meaning after merge |
|---|---|
| `human_review_required` | end-user/professional review caveat in generated output |
| `manual_review_required` in source/policy | not releaseable automatically; convert to `blocked_policy_unknown` or `known_gap` |
| `operator_approval_required` | phase authorization token must exist; not a manual implementation task |
| `manual_fix_required` | forbidden in P0 execution graph; use `ai_fix_attempt`, `blocked`, `deferred`, or `rollback` |

### 4.2 Required Execution Graph Nodes

Minimum graph:

```yaml
execution_graph:
  graph_id: "jpcite_round3_p0_master"
  executor: "ai_only"
  aws_commands_allowed_initially: false
  phases:
    - id: "inventory_contract_freeze"
      outputs:
        - "surface_inventory.json"
        - "p0_external_contracts.json"
        - "invariant_registry.yaml"
    - id: "jpcir_schema_foundation"
      outputs:
        - "schemas/jpcir/*.schema.json"
        - "fixtures/jpcir/golden/*"
        - "fixtures/jpcir/negative/*"
    - id: "policy_trust_abuse_csv_boundaries"
      outputs:
        - "policy_decision.schema.json"
        - "trust_language_pack.json"
        - "abuse_gate_report.json"
        - "csv_private_fact_capsule.schema.json"
    - id: "evidence_output_compiler"
      outputs:
        - "evidence_lens.schema.json"
        - "proof_set_manifest.schema.json"
        - "compiled_packet_examples/*.json"
    - id: "agent_billing_product"
      outputs:
        - "outcome_contract_catalog.json"
        - "agent_purchase_decision.schema.json"
        - "billing_contract.schema.json"
        - "scoped_cap_token.schema.json"
    - id: "capsule_surface_runtime"
      outputs:
        - "release_capsule_manifest.json"
        - "capability_matrix.json"
        - "surface_hash_mesh_report.json"
        - "runtime_dependency_firewall_report.json"
    - id: "ai_execution_control_plane"
      outputs:
        - "execution_manifest.yaml"
        - "execution_graph.yaml"
        - "noop_aws_command_plan.json"
        - "preflight_scorecard.json"
        - "rollback_state_machine.json"
        - "autonomous_action_ledger.jsonl"
    - id: "rc1_pointer_activation"
      outputs:
        - "golden_agent_replay_report.json"
        - "release_eval_manifest.json"
        - "runtime_pointer.json"
    - id: "aws_artifact_factory"
      allowed_when:
        - "aws_execution_authorization_token_present"
        - "preflight_state >= AWS_CANARY_READY"
        - "noop_aws_plan_hash_accepted"
        - "spend_simulation_pass == true"
        - "teardown_simulation_pass == true"
      outputs:
        - "accepted_artifact_futures.jsonl"
        - "budget_leases.jsonl"
        - "exit_bundle_manifests.jsonl"
        - "zero_bill_proof_ledger.jsonl"
```

### 4.3 Stop Gate Automata

Every phase must support these terminal transitions:

| Transition | Effect |
|---|---|
| `blocked_policy_unknown` | no public claim, create known gap |
| `blocked_terms_unknown` | no capture scale-up, create source replacement request |
| `blocked_privacy_taint` | no public surface, tenant-private only or reject |
| `blocked_paid_leakage` | no proof/preview release |
| `blocked_no_hit_overclaim` | no packet release |
| `blocked_runtime_aws_dependency` | no pointer activation |
| `blocked_spend_corridor` | AWS drain starts |
| `blocked_teardown_debt` | no resource creation |
| `rollback_pointer` | revert active capsule without AWS |
| `deferred_p1` | remove from RC1 graph, keep backlog record |

No execution state may say "ask a human to manually fix" as a required completion step.

### 4.4 AI Executor Rules

```yaml
ai_executor_rules:
  can:
    - "edit repo files through scoped patches"
    - "generate schemas, fixtures, manifests, reports, and compiled surfaces"
    - "run local tests, linters, simulators, and dry-runs"
    - "generate no-op AWS plans"
    - "run live AWS only when the execution graph reaches an AWS-authorized state"
    - "perform rollback through pointer switch when gates require it"
  cannot:
    - "run AWS CLI/API during planning-only reviews"
    - "invent new spend limits while unattended"
    - "store/upload real CSV to AWS"
    - "make request-time LLM factual claims"
    - "publish raw screenshots/DOM/HAR/OCR as public proof"
    - "hand-edit public surfaces after compilation"
    - "treat no-hit as absence/safety"
    - "create permanent AWS runtime dependency"
    - "continue past stop gates"
```

---

## 5. What To Cut, Reject, Or Defer

### 5.1 Reject Completely

These should be removed from the executable plan.

| Rejected idea | Reason |
|---|---|
| exact USD 19,493.94 spend target | conflicts with no-cash-bill requirement |
| permanent AWS archive/S3 after teardown | conflicts with zero-bill posture |
| production graph DB / runtime OpenSearch / runtime Athena / runtime Glue | conflicts with AWS-independent production |
| request-time factual LLM generation | conflicts with no-hallucination concept |
| CAPTCHA solving, stealth/proxy scraping, access-control bypass | violates official-source trust boundary |
| arbitrary website scraping API | outside product scope |
| public raw screenshot/DOM/HAR/OCR archive | terms/privacy/paid leakage risk |
| public proof pages that leak paid output | cannibalizes paid product |
| raw CSV storage, real CSV to AWS, support accepting real CSV attachments | violates privacy contract |
| name-only counterparty matching in P0 | false match/privacy risk |
| payroll/bank/person file support in P0 | outside safety boundary |
| generic legal/trust/credit/safety/eligibility score | unsupported conclusion risk |
| uncapped autonomous paid actions | billing trust risk |
| default delegated autopay in RC1 | consent and abuse risk |
| manual editing of MCP/OpenAPI/proof/pricing after compile | drift risk |
| one giant shell script for all planning/AWS/teardown | unsafe and untestable |
| live AWS commands embedded in Markdown runbooks | bypasses execution graph |
| prose-only rollback instructions | not AI-safe |

### 5.2 Defer To P1/P2

These are valuable but should not block RC1.

| Defer | Why |
|---|---|
| broad source expansion not tied to active outcome | data-project risk |
| full recurring watch billing | prove one-shot conversion first |
| broad CSV runtime and private warehouse | privacy/compliance load |
| full graph visualization/query UI | not needed for paid RC1 |
| complex EvidenceQL/query language | JSON query specs are enough for P0 |
| low-yield screenshot/OCR expansion | must pass canary economics first |
| nationwide all-page local-government crawl | use archetypes/canaries first |
| full portfolio/competitor batch UI | abuse controls needed first |
| advanced learning dashboard | aggregate metrics first |
| formal legal review workflow UI | use deterministic fail-closed ledgers first |

### 5.3 Keep But Rename Or Clarify

| Existing phrase | Merge correction |
|---|---|
| `Knowledge Graph` | `Official Evidence Ledger -> Evidence Lens`; not production truth DB |
| `truth maintenance` | `Conflict-Aware Evidence Maintenance` |
| `legal attestation` in UI | `公開ポリシー確認`; machine object can remain internal |
| `human_review_required` | output caveat, not developer workflow |
| `manual review` | `blocked/gap/deferred` unless explicitly about end-user professional review |
| `source quality score` | typed operational metrics only |
| `trust score` | forbidden; use trust vector/gaps/caveats |
| `cache` | evidence receipts/lenses with freshness/no-hit leases |

---

## 6. Source And AWS Merge Rules

Source acquisition should follow this rule:

```text
Do not scale a source because it is important.
Scale it only if it satisfies a missing capability for a sellable outcome,
passes source terms/policy gates, and produces accepted artifacts at measured
product yield.
```

Required source controls:
- `Source Capability Contract`
- `Evidence Aperture Router`
- `Public Corpus Yield Compiler`
- `Delta-First Acquisition`
- `Municipality Archetype Engine`
- `Gazette/Event Normalizer`
- `Regulatory Source Spine`
- `Source Replacement Market`

Capture aperture order:
1. link-only
2. metadata-only
3. section fact
4. rendered observation
5. OCR candidate

Rule:
- choose the shallowest aperture sufficient for the claim.
- Playwright/OCR is a high-cost public observation method, not a bypass mechanism.
- repeated failed retries are forbidden; produce gap/replacement records.

AWS factory controls:
- every AWS job must have `accepted_artifact_contract`.
- every job must have `target_packet_ids`.
- every job must price teardown debt before resource creation.
- every job must have an exit bundle class.
- every expensive service needs service risk escrow.
- failures count only if they create structured blocked/gap/retry evidence.

Control spend formula:

```text
control_spend_usd =
  observed_spend_usd
  + max(job_reservation_remaining, p95_job_remaining)
  + service_tail_risk_usd
  + teardown_debt_usd
  + stale_cost_penalty_usd
  + untagged_resource_penalty_usd
  + ineligible_charge_uncertainty_reserve_usd
  + cleanup_reserve_usd
  + external_export_reserve_usd
  + panic_snapshot_reserve_usd
```

---

## 7. Product And Revenue Merge Rules

The final commercial rule:

```text
A feature exists only if it helps an AI agent recommend, price, execute,
repeat, or safely decline a paid public-evidence outcome.
```

Immediate product focus:
1. `Outcome Contract Catalog`
2. `agent_purchase_decision`
3. one or two paid company/vendor outcomes
4. proof surrogate pages that do not leak paid output
5. Golden Agent Revenue Replay
6. AWS accepted artifacts tied to those outcomes first
7. source expansion only when gaps block recommendation or repeat usage

P0 product behavior:
- preview is a purchase decision object, not a quote only.
- preview must include cheapest sufficient route.
- higher tiers must show exact marginal coverage.
- preview must include `reason_not_to_buy`.
- no paid execution without scoped cap token.
- no accepted artifact, no charge.
- receipt reuse should lower cost or improve speed when possible.

P0 MCP facade:
- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_execute_packet`
- `jpcite_get_packet`

Full tools remain expert/internal surfaces, not the default GEO recommendation path.

---

## 8. Release And Evaluation Gates

Release Capsule activation must be blocked if any of these fail:

- capability contract missing or hash drift.
- surface parity hash mesh mismatch.
- MCP/OpenAPI/proof/pricing/llms/.well-known disagree.
- UI and JSON disagree on price/cap/no-hit/caveats.
- forbidden phrase appears in public surface.
- public proof leaks paid output/private data/raw screenshot/raw OCR.
- no-hit lacks lease scope and caveat.
- paid execution lacks consent envelope or scoped cap token.
- release capsule contains raw CSV, raw screenshot archive, full cold graph, or AWS dependency.
- Golden Agent Session Replay fails recommendation, non-recommendation, price explanation, no-hit, known gaps, CSV privacy, consent, or zero-AWS explanation.
- production smoke without AWS fails.
- zero-AWS posture says attested while AWS resources remain required by runtime.

Golden Agent Replay must test:
- agent recommends the cheapest sufficient route.
- agent declines or asks first when coverage/gaps/cost do not justify purchase.
- agent preserves price cap and charge policy.
- agent never turns no-hit into absence/safety.
- agent never makes final legal/tax/credit/professional conclusions.
- agent does not ask user for card details directly.

---

## 9. Privacy-Safe Learning Merge

Adopt `Privacy-Safe Learning Control Plane`, but only with aggregate and allowlisted telemetry.

Allowed telemetry:
- packet type
- outcome contract
- preview displayed
- approval granted
- paid executed
- known gap category
- no-hit category
- price cap band
- error category
- source canary yield metrics

Forbidden telemetry:
- raw user prompt
- raw CSV
- company lists from private tasks
- personal data
- full result text
- raw source screenshot text
- secrets or credentials

Learning output cannot mutate production directly. It may create candidate capsules, source priority proposals, pricing proposals, and Golden Replay additions. Candidate changes must pass the same gates before pointer activation.

---

## 10. Final Contradiction Table

| Area | Status | Final resolution |
|---|---|---|
| Use most AWS credit vs no cash bill | Resolved | maximize accepted artifact value under USD 19,300 control spend |
| AWS self-running vs safe stop | Resolved | Autonomous Operator Silence Mode plus stop gates |
| Fast spend vs valuable outputs | Resolved | accepted-artifact futures only |
| Broad public data vs revenue | Resolved | outcome-to-source backcasting |
| Evidence graph vs zero-bill | Resolved | offline ledger, production Evidence Lens only |
| AI-only implementation vs review gates | Resolved | gates are deterministic or fail-closed, not human implementation tasks |
| `human_review_required` vs AI all execution | Resolved | output caveat only; execution uses blocked/gap/deferred states |
| CSV value vs privacy | Resolved | PrivateFactCapsule, local-first, no raw retention/AWS |
| GEO discovery vs paid leakage | Resolved | agent decision pages with public value minimization |
| Trust UX vs overpromising | Resolved | trust vector, no generic trust badge/score |
| Watch products vs zero AWS | Resolved | watch is post-teardown non-AWS/runtime capability; AWS builds baseline fixtures only |
| Legal/compliance products vs advice | Resolved | sell evidence/checklists/candidates, not legal conclusions |
| Source politeness vs speed | Resolved | parallel allowed sources and compiler/eval spend, not abusive fetch |
| Learning loop vs privacy | Resolved | aggregate allowlist and candidate-capsule-only application |

No blocking contradiction remains if this merge is applied.

---

## 11. Merge Envelope

```yaml
merge_envelope:
  review_id: "aws_smart_methods_round3_20_final_merge_sot"
  verdict: "pass_with_required_merge"
  aws_commands_executed: false
  output_file_only: true
  readable_inputs:
    - "aws_smart_methods_round3_01_meta_architecture.md"
    - "aws_smart_methods_round3_02_product_packaging.md"
    - "aws_smart_methods_round3_03_agent_mcp_ux.md"
    - "aws_smart_methods_round3_04_evidence_data_model.md"
    - "aws_smart_methods_round3_05_source_acquisition.md"
    - "aws_smart_methods_round3_06_aws_factory_cost.md"
    - "aws_smart_methods_round3_07_pricing_billing_consent.md"
    - "aws_smart_methods_round3_08_csv_private_overlay.md"
    - "aws_smart_methods_round3_09_legal_policy_privacy.md"
    - "aws_smart_methods_round3_10_evaluation_geo_quality.md"
    - "aws_smart_methods_round3_11_release_runtime_capsule.md"
    - "aws_smart_methods_round3_12_developer_runbook.md"
    - "aws_smart_methods_round3_13_implementation_architecture.md"
    - "aws_smart_methods_round3_14_freshness_watch.md"
    - "aws_smart_methods_round3_15_trust_accountability_ui.md"
    - "aws_smart_methods_round3_16_abuse_risk_controls.md"
    - "aws_smart_methods_round3_17_metrics_learning_loop.md"
    - "aws_smart_methods_round3_18_revenue_strategy_critique.md"
  missing_input:
    - "aws_smart_methods_round3_19_*.md"
  merge_required:
    - "append final master SOT chapter"
    - "replace implementation order with AI-executable compiler sequence"
    - "add AI-only execution graph semantics"
    - "move human/manual review from implementation dependency to fail-closed output states"
    - "adopt Outcome Contract Catalog above packet catalog"
    - "adopt JPCIR-centered compiler pipeline"
    - "adopt Release Capsule v2/Capsule Runtime"
    - "adopt AWS Artifact Factory Kernel accepted-artifact futures"
    - "adopt Trust/Policy/Abuse/Learning control planes as gates"
  reject:
    - "exact USD 19,493.94 spend target"
    - "permanent AWS archive"
    - "production AWS runtime dependency"
    - "request-time factual LLM"
    - "raw CSV retention/AWS upload"
    - "public paid output leakage"
    - "generic trust/credit/safety score"
    - "manual public-surface edits as SOT"
  p0_must_ship_before_live_aws:
    - "JPCIR schemas"
    - "invariant registry"
    - "policy/trust/abuse gates"
    - "outcome contract catalog"
    - "agent purchase decision"
    - "scoped cap token"
    - "release capsule schema"
    - "surface compiler"
    - "execution graph"
    - "no-op AWS plan"
    - "spend/teardown simulator"
    - "rollback state machine"
  p0_must_ship_before_paid_rc1:
    - "cheapest sufficient route"
    - "coverage ladder quote"
    - "accepted artifact pricing"
    - "proof surrogate compiler"
    - "forbidden language linter"
    - "Golden Agent Session Replay"
    - "production smoke without AWS"
```

---

## 12. Final Recommendation

Merge Round3 by making the plan narrower and more executable, not broader.

The strongest final shape is:

```text
Outcome Contract Catalog
  -> JPCIR
  -> Policy/Trust/Abuse gates
  -> Official Evidence Ledger
  -> Evidence Lens
  -> Public Packet Compiler
  -> Agent Decision Protocol
  -> Billing Contract / Scoped Cap Token
  -> Release Capsule v2
  -> Agent Surface Compiler
  -> AI Execution Control Plane
  -> AWS Artifact Factory Kernel
  -> Zero-Bill Proof Ledger
```

This is smarter than continuing to add source families or standalone packet ideas because it makes every new idea answer four questions:

1. Does it help an AI agent recommend or decline a paid outcome?
2. Can it be represented as JPCIR and compiled into a Release Capsule?
3. Can policy/trust/privacy/abuse gates prove it is safe to expose?
4. Can AI execute, verify, rollback, and teardown it without hidden human implementation work?

If the answer is no, it should be rejected, deferred, or converted into a gap/source-backlog artifact.

Final state:
- no AWS commands executed.
- no AWS resources created.
- no master plan edited by this review.
- this file is the final Round3 20/20 merge SOT output.
