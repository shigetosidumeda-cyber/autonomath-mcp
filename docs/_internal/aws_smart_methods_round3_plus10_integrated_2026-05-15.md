# AWS smart methods Round3 plus 10 integrated merge

Date: 2026-05-15

Scope:

- Integrates the additional 10-agent smart-method review requested after Round3.
- No AWS CLI/API commands were executed.
- No production resources were created.
- This document is a merge memo; the execution SOT remains `aws_jpcite_master_execution_plan_2026-05-15.md`.

## 1. Final Verdict

The smarter method is not "add more features to P0." The smarter method is to make P0 smaller, more compiler-like, and more agent-native:

```text
Outcome Contract Catalog
-> Agent Decision Protocol
-> JPCIR
-> Policy Decision Firewall
-> Evidence Lens
-> Public Packet Compiler
-> Billing Contract Layer
-> Release Capsule
-> AI Execution Control Plane
-> AWS Artifact Factory
```

This keeps the product thesis sharp:

- AI agents discover and recommend jpcite through GEO surfaces.
- End users buy bounded, source-backed outcomes, not a database or a tool list.
- Facts are compiled from receipts and rules, not request-time LLM assertions.
- AWS converts expiring credit into accepted artifacts, then disappears from runtime.
- AI executes implementation and future AWS operation through machine-readable gates.

## 2. Adopted Smart Changes

### 2.1 Product and GEO

Adopt `Outcome Contract Catalog` as the public product layer. Packets remain internal execution and billing units.

P0 preview returns `agent_purchase_decision_v2`, not a quote only. It must include:

- `cheapest_sufficient_route`
- `coverage_roi_curve`
- `anti_upsell_gate`
- `reason_to_buy`
- `reason_not_to_buy`
- `known_gaps_before_purchase`
- `no_hit_not_absence`
- expected output skeleton
- max price / cap requirement
- `agent_recommendation_card`

P0 public MCP/OpenAPI facade is four tools:

- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_execute_packet`
- `jpcite_get_packet`

Full MCP and full OpenAPI remain expert/developer surfaces, not the default GEO path.

### 2.2 Evidence and Algorithms

Adopt a small `JPCIR` compiler pipeline. Do not build a production graph DB in P0.

The evidence model is:

```text
Official Evidence Ledger -> packet-specific Evidence Lens -> Public Packet Compiler
```

`Output Composer` may choose route, bundle, follow-up question, cheapest sufficient outcome, or skip. It must not create factual claims.

`Public Packet Compiler` is the only component allowed to emit public claims. Every public claim needs:

- `claim_ref`
- `source_receipt`
- `temporal_envelope`
- `policy_decision`
- `support_state`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- no-hit/conflict handling where applicable

P0 may use a greedy minimal proof-set selector and JSON query specs. Full EvidenceQL, graph DB, broad source crawler, and recurring watch billing move to P1/P2.

### 2.3 AI-Only Execution

Implementation, validation, local release, rollback, and future AWS operation are AI-executed through machine-readable graphs.

`AI Execution Control Plane` must start at bootstrap, not after feature work. Otherwise early phases become prose/manual execution again.

Required execution artifacts before live AWS:

- `execution_manifest.yaml`
- `execution_graph.yaml`
- invariant registry
- JPCIR schemas and fixtures
- no-op AWS command plan
- spend simulator
- teardown simulator
- preflight scorecard
- stop gate automata
- rollback state machine
- autonomous verification loop
- autonomous action ledger

No state may require "ask a human to manually fix" as a completion path. Use `ai_fix_attempt`, `blocked`, `known_gap`, `deferred_p1`, or `rollback_pointer`.

### 2.4 Policy, Privacy, and Terms

Replace human/manual policy review with machine policy states:

```text
allow
allow_with_minimization
allow_internal_only
allow_paid_tenant_only
gap_artifact_only
blocked_policy_unknown
blocked_terms_unknown
blocked_terms_changed
blocked_access_method
blocked_privacy_taint
blocked_sensitive_context
blocked_mosaic_risk
blocked_wording
blocked_paid_leakage
blocked_no_hit_overclaim
quarantine
deny
```

`human_review_required` may remain only as an end-user/professional caveat in an output. It must not be a developer, operator, release, or AWS execution dependency.

Japanese public primary information is not automatically public-safe. Every public surface must classify:

- `administrative_info_class`
- `privacy_taint_level`
- `source_terms_contract_id`
- `policy_decision_id`
- `allowed_surfaces[]`
- `blocked_surfaces[]`
- `blocked_reason_codes[]`

Terms contracts are per access/use mode: API, bulk, HTML, Playwright, OCR, proof, reuse, and retention.

### 2.5 CSV Private Overlay

P0 adopts CSV schema and safety, not real CSV runtime.

P0 includes:

- `PrivateFactCapsule` schema
- `PrivateOverlayReceiptRecord`
- provider fingerprint/header-only preview
- synthetic fixtures
- formula-injection tests
- payroll/bank/person reject tests
- leak and suppression tests
- privacy receipt contract

Real CSV runtime is P1 behind feature flags. It must be local-first, with memory-only server fallback only after no-log/no-temp/no-Sentry/no-cache gates pass.

Raw CSV, raw rows, row-level normalized records, memo/counterparty values, invoice numbers, bank/card/payroll/person fields, and real private aggregates must never enter AWS, repo fixtures, logs, telemetry, support attachments, public proof pages, OpenAPI/MCP examples, JSON-LD, or Release Capsules.

### 2.6 Pricing and Billing

Do not sell API calls, packet names, seats, or broad subscriptions as the launch product. Sell small capped official-source-backed outcome contracts.

P0 billing path:

```text
agent_purchase_decision
-> consent_envelope
-> versioned scoped_cap_token
-> accepted_artifact_gate
-> billing_outcome_decision
-> append-only billing_event_ledger
```

Billing uses `accepted_artifact_pricing`. No accepted artifact means no charge or a scoped void/refund event.

No-hit is billable only when the contract explicitly includes a scoped no-hit observation, the user consented, the no-hit lease/caveat exists, and the output never implies absence, safety, compliance, creditworthiness, or permission.

### 2.7 Release and Runtime

Production runtime should use Release Capsule pointers on the existing non-AWS public deployment surface.

P0 runtime model:

- immutable `Release Capsule v2`
- `Capability Matrix v2`
- runtime pointer set
- generated `llms.txt`, `.well-known`, MCP facade, agent-safe OpenAPI, proof/decision pages, pricing, examples, no-hit language, and trust receipts
- surface parity hash mesh
- AWS dependency firewall
- pointer rollback

Rollback is a pointer switch. It must not require AWS restore, S3 access, source refetch, OCR, Playwright, or request-time factual LLM.

### 2.8 AWS Artifact Factory

AWS is a temporary accepted-artifact market, not a spend burn and not runtime infrastructure.

Spend rule:

```text
target USD 19,490 eligible credit conversion while cash_bill_guard can stop lower
```

Do not target exact `USD 19,493.94` if it creates cash exposure. The current user target is `USD 19,490`, which is close enough to require micro-spend lanes, stricter queue exposure control, and immediate drain/teardown once the target corridor is reached.

`control_spend_usd` must include:

- observed spend
- max(job reservation remaining, p95 job remaining)
- service tail risk
- teardown debt
- stale-cost penalty
- untagged resource penalty
- ineligible charge uncertainty reserve
- cleanup reserve
- external export reserve
- panic snapshot reserve

AWS may continue without Codex/Claude only in `Autonomous Operator Silence Mode`: no new services, no new source families, no cap increases, no OpenSearch/NAT creation, no policy override, and no stretch expansion outside sealed leases.

Official AWS constraints confirmed during the review:

- Cost Explorer and billing views can be delayed at least 24 hours, so they are not real-time primary controls.
- AWS Budgets Actions can apply IAM policies or SCPs at thresholds.
- SCPs are guardrails and do not grant permissions.
- Promotional credits only apply to eligible services; AWS Marketplace, certain support/training/certification/domain/upfront commitment charges can be ineligible.

## 3. Final P0 / P1 / P2 Cut

### P0

P0 is limited to:

- minimal `Outcome Contract Catalog`
- JPCIR base schemas and validators
- Invariant Registry
- minimal `Policy Decision Firewall v2`
- no-hit language pack
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `source_receipts[]`
- `claim_refs[]`
- minimal Public Packet Compiler
- minimal Agent Decision Protocol
- canonical `jpcite_preview_cost`
- Consent Envelope
- versioned Scoped Cap Token schema
- Accepted Artifact Pricing schema
- minimal Billing Contract Layer
- minimal Trust Surface Compiler
- minimal `agent_decision_page`
- Release Capsule manifest and pointer contract
- Surface Parity Checker
- Forbidden Language Linter
- minimal Golden Agent Session Replay
- AI Execution Control Plane bootstrap
- no-op AWS command plan compiler
- AWS artifact contract schemas
- spend and teardown simulator
- zero-AWS dependency scanner
- production-without-AWS smoke
- CSV non-AWS schema/synthetic/header-only tests

P0 public paid outcomes:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`
- `invoice_vendor_public_check` only if cheap and already supported

Free controls:

- `agent_routing_decision`
- `jpcite_preview_cost`

### P1

P1 includes:

- live AWS canary and self-running standard lane
- Accepted Artifact Futures
- Budget Token Market
- Service Risk Escrow
- Rolling External Exit Bundles
- Source Capability Contract runtime
- Evidence Aperture Router
- Public Corpus Yield Compiler
- selected grants, permits, enforcement, tax/labor, procurement outcomes
- local-first CSV runtime / PrivateFactCapsule runtime
- watch statement compiler and bounded delta billing
- broader Golden Agent Replay
- workflow kits and receipt reuse optimization

### P2

P2 includes:

- full Evidence Graph / EvidenceQL
- broad municipality, courts, standards, geospatial, gazette baselines
- broad portfolio/competitor batch products
- watch portfolio batching
- advanced privacy-safe learning loops
- full legal/privacy dashboard and public correction portal

## 4. Rejected Or Deferred

Reject completely:

- exact credit face-value burn as a target
- permanent AWS archive or S3 retention after teardown
- request-time factual LLM generation
- CAPTCHA solving, stealth/proxy scraping, or access-control bypass
- public raw screenshot/DOM/HAR/OCR archive
- charge-per-attempt billing
- uncapped autopay in RC1
- public proof pages that leak paid output
- raw real CSV storage or real CSV to AWS
- name-only counterparty matching in P0
- payroll/bank/person file support in P0
- generic legal/trust/credit/safety/eligibility scores
- manual public-surface edits as source of truth
- prose-only rollback

Defer:

- full CSV private overlay runtime
- watch billing runtime
- full graph DB / EvidenceQL
- broad source expansion not tied to active outcomes and gaps
- portfolio/competitor batch products
- advanced learning loops

## 5. Master Plan Merge Rules

The master plan must treat this Round3 plus 10 merge as overriding older broad P0/P0-B language.

If an older section implies:

- AWS canary before AI execution preflight
- broad P0 source expansion
- human/manual implementation dependency
- full MCP/OpenAPI as default agent surface
- proof pages leaking paid output
- zero-AWS attestation while AWS factory is running

then the Round3 contradiction-killer rule wins.

The final implementation order is:

1. Freeze outcome contracts and P0 envelope.
2. Build JPCIR and invariants.
3. Build policy/trust/privacy gates.
4. Build evidence/output compiler.
5. Build agent decision and billing contract.
6. Build Release Capsule runtime and generated surfaces.
7. Build AI Execution Control Plane and no-op AWS plan.
8. Ship RC1 without AWS runtime.
9. Enter live AWS only after explicit preflight.
10. Run AWS as sealed accepted-artifact factory.
11. Import RC2/RC3 through capsule pointers.
12. Export outside AWS and outside git.
13. Teardown AWS.
14. Produce non-AWS-triggered post-teardown attestations.

## 6. External AWS References Checked

- AWS Cost Explorer documentation: Cost Explorer refreshes cost data at least once every 24 hours. https://docs.aws.amazon.com/console/billing/costexplorer
- AWS Billing home documentation: Billing home data comes from Cost Explorer and can be refreshed at least once every 24 hours when available. https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/view-billing-dashboard.html
- AWS Budgets documentation: Budgets Actions can apply IAM policies or SCPs at thresholds. https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS Organizations documentation: SCPs set maximum available permissions and do not grant permissions. https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html
- AWS Promotional Credit Terms: promotional credits apply only to eligible services and exclude several categories unless authorized. https://aws.amazon.com/awscredits/
