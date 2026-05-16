# AWS smart methods round3 18/20: revenue strategy / founder-level critique

Date: 2026-05-15
Status: critique only, no AWS commands executed
Scope: revenue, GEO recommendation, repeat usage, over-design control, master-plan merge deltas
Input context: current master execution plan, Round2 smart-method addendum, Round3 smart-method files 01-12, user correction that implementation execution is AI-operated
Output constraint: this file only

## 0. Verdict

Conditional PASS, with one important correction.

The current plan is strategically strong, but it is at risk of becoming an impressive evidence infrastructure project before it becomes a revenue engine.

The smarter direction is not to add more source families or more internal graph concepts. The smarter direction is to make every planned capability answer one founder-level question:

> Will an AI agent confidently recommend this paid outcome to an end user, with a clear price, a bounded scope, and a reason to come back?

The plan should therefore be merged around four commercial primitives:

1. `Outcome Contract Catalog`
2. `Agent Decision Protocol`
3. `Evidence Product OS`
4. `Release Capsule`

Everything else is a supporting subsystem. If a subsystem does not improve one of:

- agent recommendation rate
- paid conversion rate
- repeat usage
- receipt reuse
- accepted artifact yield
- zero-bill safety

then it should be deferred, even if technically elegant.

## 1. Founder-level assessment

### 1.1 The business can work

The business can work because it is not selling "data access." It is selling cheap, bounded, source-backed outcomes that AI agents can explain.

The most compelling buyer narrative is:

> "Instead of letting the AI browse uncertain public pages and hallucinate a conclusion, use jpcite to buy a small, capped, official-source-backed packet with receipts, gaps, and no-hit caveats."

This is a real wedge because AI agents need:

- cheaper verification
- safe citations
- scoped paid actions
- low-latency reusable evidence
- non-hallucinated public facts
- a way to explain cost to the end user

The end user is not buying an API. The end user is buying an answer-shaped work product.

### 1.2 The biggest risk

The biggest risk is believing that broad official information collection automatically becomes revenue.

It does not.

Broad collection creates optionality, but revenue comes from repeated user tasks:

- "Can I trust this vendor enough to proceed?"
- "Is this invoice/vendor publicly valid?"
- "What grants or subsidies should I look at?"
- "What permits or registrations might this activity need?"
- "What changed that affects my business?"
- "What should I check this month from my accounting data?"

The plan must keep the first release focused on high-frequency, low-friction tasks, then use usage telemetry and gap telemetry to decide what to collect next.

### 1.3 The second biggest risk

The second biggest risk is overbuilding internal purity before proving agent recommendation.

Examples:

- a large evidence graph before a paid packet converts
- broad local government coverage before one vertical workflow works
- many MCP tools before the agent decision path is simple
- watch products before one-off purchases convert
- legal/tax nuance before safe "candidate/gap/checklist" wording is accepted

The correct posture is:

> Build the smallest proof-carrying outcome that an AI agent can recommend, then expand only where `accepted_artifact_yield` and paid conversion justify it.

## 2. The product should be outcome-first, not packet-first

### 2.1 Problem with packet-first thinking

Packet names are internal product modules. End users do not want to buy:

- `source_receipt_ledger`
- `evidence_answer`
- `permit_scope_checklist_packet`
- `regulation_change_impact_packet`

They want outcomes:

- "Check this company before I pay it."
- "Find usable grants for my company."
- "Tell me what changed and whether I need to act."
- "Check what public evidence exists for this vendor."
- "Convert this CSV into useful public-information checks."

Packets can remain the implementation and billing units, but the sales layer should be `Outcome Contract Catalog`.

### 2.2 Adopt: `Outcome Contract Catalog`

Adopt as P0.

Each outcome contract should define:

- `outcome_id`
- `buyer_task`
- `agent_trigger_phrases[]`
- `end_user_value`
- `cheapest_sufficient_route`
- `coverage_ladder[]`
- `included_packets[]`
- `optional_packets[]`
- `free_preview_payload`
- `paid_output_skeleton`
- `proof_surrogate_payload`
- `known_gap_choices[]`
- `pricing_floor`
- `pricing_ceiling`
- `cap_token_policy`
- `refund_or_void_policy`
- `repeat_use_path`
- `GEO_decision_page_url`
- `golden_agent_sessions[]`
- `source_family_requirements[]`
- `blocked_claims[]`

This should sit above individual packet APIs.

### 2.3 RC1 outcome contracts

RC1 should not launch too many outcomes. It should launch the outcomes that are easiest for agents to recommend.

Recommended RC1 paid outcomes:

| Outcome | Why it should be RC1 | Paid shape |
|---|---|---|
| `company_quick_public_check` | Very low user friction, broad applicability | company baseline + receipt ledger |
| `invoice_vendor_public_check` | Strong accounting/vendor workflow |法人番号/インボイス/gBizINFO confirmation with caveats |
| `public_evidence_answer` | General utility but bounded by receipts | evidence answer from accepted receipts |
| `counterparty_public_snapshot` | B2B sales/procurement use case | baseline + administrative/enforcement if available |

RC1 free controls:

- `agent_task_intake`
- `jpcite_preview_cost`
- `jpcite_route_task`
- `cap_token_preview`
- `capability_matrix`
- `agent_decision_page`
- `no_hit_language_pack`

RC1 should not require CSV, grants, local government, full permits, or watch products to convert.

### 2.4 RC1.5 / RC2 outcome contracts

Recommended RC1.5:

- `grant_candidate_shortlist`
- `application_readiness_checklist`
- `permit_scope_precheck`

Recommended RC2:

- `csv_monthly_public_review`
- `tax_labor_event_radar`
- `regulation_change_watch`
- `vendor_portfolio_batch_check`
- `procurement_opportunity_radar`

Rationale: these are more valuable, but they need more source breadth, more UI clarity, and stronger caveats.

## 3. Strongest revenue loops

### 3.1 Loop A: one-off company/vendor check

This is the simplest wedge.

Flow:

1. AI agent hears: "この会社を確認して", "この請求書の相手先を確認して", "取引先を調べて".
2. Agent calls free preview.
3. jpcite returns cheapest sufficient route and expected evidence.
4. User approves a small cap.
5. jpcite returns receipts, gaps, and no-hit caveats.
6. Agent suggests batch or watch only if user has multiple counterparties.

Why this sells:

- immediate pain
- no large setup
- easy to explain
- repeatable for many companies
- receipt reuse reduces future cost

Smart feature needed:

- `Portfolio Batch Upgrade`: after one vendor check, show "check 20 vendors cheaper per vendor" only when the user has a credible batch intent.

### 3.2 Loop B: grants and readiness

This is high willingness-to-pay but high disappointment risk.

The product must avoid promising eligibility.

Sell:

- candidate shortlist
- missing information list
- readiness checklist
- deadline/source receipt
- application page/source link

Do not sell:

- "eligible"
- "guaranteed subsidy"
- "you can receive"
- application drafting as an official conclusion

Smart feature needed:

- `Grant Fit Ladder`: basic public candidate scan -> deeper criteria match -> readiness checklist -> watch.

### 3.3 Loop C: regulation / permit / tax-labor watch

This is the retention engine.

One-off packet revenue is helpful, but recurring value comes from changes:

- new grant
- deadline change
- law/regulation update
- permit procedure update
- tax/labor calendar event
- administrative disposition update for a watched company/vendor

Smart feature needed:

- `Watch Statement Product`: a recurring product that sends "what changed, what source changed, what action candidate exists, what remains unknown."

Do not make watch RC1 paid unless the one-off outcome converts. In RC1, expose watch as a preview/waitlist or limited trial.

### 3.4 Loop D: CSV private overlay

CSV is a strong differentiator, but only if it is framed correctly.

The user is not asking for "CSV analysis." The user is asking:

- "What public checks should I run based on this month's business activity?"
- "Which vendors should I verify?"
- "Are there grants or tax/labor events relevant to what happened this month?"

Smart feature needed:

- `Local-First CSV Fact Extractor`
- `PrivateFactCapsule`
- `CSV Outcome Contract Router`

Revenue risk:

If CSV requires trust-heavy upload and a complex privacy explanation, conversion may drop.

Mitigation:

Start with:

- header-only preview
- local-first extraction
- explicit "raw CSV is not stored"
- public-check recommendations generated from safe derived facts

## 4. Adopt / defer / reject decisions

### 4.1 Adopt now

| Feature | Decision | Why |
|---|---|---|
| `Outcome Contract Catalog` | Adopt P0 | Makes product sellable to agents and end users |
| `Agent Decision Protocol` | Adopt P0 | Converts discovery into purchase-ready action |
| `Cheapest Sufficient Route Solver` | Adopt P0 | Builds trust and reduces agent resistance |
| `Coverage Ladder Quote` | Adopt P0 | Allows upsell without dark patterns |
| `agent_purchase_decision` | Adopt P0 | Preview becomes sales engine |
| `agent_recommendation_card` | Adopt P0 | Directly improves GEO recommendation |
| `Capability Matrix Manifest` | Adopt P0 | Prevents agents recommending unavailable functions |
| `Public Proof Surrogate Compiler` | Adopt P0 | Shows value without leaking paid output |
| `Golden Agent Session Replay` | Adopt P0 | Validates real agent recommendation behavior |
| `Billing Contract Layer` | Adopt P0 | Makes paid action safe and explainable |
| `Scoped Cap Token v2` | Adopt P0 | Lets AI operate without uncapped spend |
| `Accepted Artifact Pricing` | Adopt P0 | Aligns billing with delivered value |
| `Policy Decision Firewall` | Adopt P0 | Required for trust and release safety |
| `No-Hit Lease Ledger` | Adopt P0-lite | Prevents dangerous no-hit reuse |
| `Release Capsule` | Adopt P0 | Enables safe production and rollback |
| `Runtime Dependency Firewall` | Adopt P0 | Enforces post-AWS runtime independence |
| `Zero-Bill Guarantee Ledger` | Adopt P0 | Required by user constraint |

### 4.2 Adopt as internal architecture, but do not expose

| Feature | Decision | Why |
|---|---|---|
| `Evidence Product OS` | Adopt internal | Good organizing model, bad public terminology |
| `JPCIR` | Adopt internal | Useful IR, but should not delay RC1 |
| `Official Evidence Ledger` | Adopt internal | Better than a truth DB |
| `Evidence Lens` | Adopt internal | Useful for packet compilation |
| `Claim Derivation DAG` | Adopt internal P0-lite | Needed for audit, but keep minimal |
| `Bitemporal Claim Graph` | Adopt limited | Important for laws/dates, but can be minimal in RC1 |
| `Proof Set Optimizer` | Adopt limited | Use simple minimal proof first |
| `Source Twin Registry` | Adopt P1 | Useful after source count grows |
| `Source Replacement Market` | Adopt P1 | Good but not necessary for RC1 |

### 4.3 Defer

| Feature | Decision | Why |
|---|---|---|
| Full geospatial products | Defer | Valuable but not first revenue wedge |
| Broad standards/certification coverage | Defer except high-demand verticals | Complex, slower conversion |
| Nationwide local government deep coverage | Defer broad crawl | Use archetypes and high-yield municipalities first |
| Court/dispute corpus expansion | Defer | High nuance, privacy/reputation risk |
| Full recurring watch billing | Defer paid full launch | Prove one-off conversion first |
| Heavy EvidenceQL | Defer | Internal query language can become overbuild |
| Complex portfolio sampling ladder | Defer | Useful after batch demand appears |
| Full CSV server fallback | Defer | Local-first and header-only are safer for initial conversion |
| OpenSearch benchmark | Defer unless concrete bottleneck | Adds cleanup/cost tail risk |

### 4.4 Reject

| Feature / behavior | Decision | Why |
|---|---|---|
| Public "trust score" | Reject | Too legally risky and misleading |
| Public "credit score" | Reject | Outside safe positioning |
| Public eligibility conclusion | Reject | Use candidate priority / needs review |
| "No issue" conclusion | Reject | No-hit is not absence |
| Screenshot-first corpus | Reject | Costly and weaker than official API/bulk |
| CAPTCHA / login / access-control bypass | Reject | Policy and legal risk |
| Permanent AWS archive | Reject | Violates zero-bill requirement |
| Live AWS runtime fallback | Reject | Violates post-run architecture |
| Broad public raw screenshot archive | Reject | Privacy/terms/leakage risk |
| Raw CSV upload as stored asset | Reject | Violates private overlay posture |
| Fully autonomous uncapped agent spending | Reject | Must use scoped cap tokens |

## 5. New smarter functions found in this critique

### 5.1 `Revenue Proof Record`

Every feature, source, packet, and AWS job should have a revenue proof record.

Schema:

```json
{
  "revenue_proof_id": "rpr_company_quick_public_check_v1",
  "artifact_or_feature_id": "company_quick_public_check",
  "buyer_task": "取引先を公的一次情報で確認したい",
  "agent_trigger_phrases": ["この会社を確認して", "請求書の相手先を確認して"],
  "paid_outcome_ids": ["company_quick_public_check"],
  "free_preview_value": "expected sources, price cap, known gaps, no-hit caveat",
  "conversion_hypothesis": "small capped price converts because user has immediate transaction risk",
  "repeat_use_hypothesis": "batch vendors and watch updates",
  "source_family_dependencies": ["corporate_identity", "business_registry_signal"],
  "proof_leakage_risk": "low",
  "legal_wording_risk": "medium",
  "p0_required": true,
  "defer_if_missing": ["agent_recommendation_card", "cap_token", "receipt ledger"]
}
```

Rule:

No P0 feature should be implemented without a `Revenue Proof Record`.

### 5.2 `Agent Recommendation Fit Score`

This is not a user-facing score. It is an internal release gate.

Components:

- `task_frequency`
- `agent_can_identify_need`
- `agent_can_explain_value`
- `agent_can_explain_price`
- `agent_can_explain_gaps`
- `source_receipt_reuse`
- `repeat_use_potential`
- `legal_wording_risk_inverse`
- `proof_leakage_risk_inverse`
- `implementation_complexity_inverse`

Use:

- rank outcome contracts
- reject overbuilt features
- decide AWS source expansion
- decide proof page priority

Do not expose this externally.

### 5.3 `GEO Revenue Simulation Harness`

Existing Golden Agent Session Replay should be made revenue-specific.

It should test:

- Did the agent discover jpcite?
- Did the agent choose jpcite over generic browsing?
- Did the agent explain the cheapest sufficient option?
- Did the agent avoid over-selling?
- Did the agent explain no-hit and known gaps?
- Did the agent ask for user consent before paid execution?
- Did the user-facing explanation include price and scope?
- Did the agent recommend a repeat/batch/watch upgrade only when justified?

Outputs:

- `agent_recommendation_rate`
- `agent_paid_consent_rate`
- `agent_overclaim_rate`
- `agent_oversell_rate`
- `agent_abstention_quality`
- `agent_repeat_prompt_rate`

This is more commercially useful than generic GEO visibility.

### 5.4 `Proof Value Split`

Proof pages must be valuable enough to sell but not so complete that they replace paid output.

Split:

- public proof page: what the packet does, example structure, source classes, caveats, price range, fake/synthetic or minimized examples
- paid output: actual compiled claims, full receipt ledger, scoped no-hit checks, gap matrix, reusable receipt ids

Add a release gate:

> A proof page fails if a reasonable agent can answer the user's paid task from the proof page alone.

### 5.5 `Outcome-to-Source Backlog Compiler`

The plan already has source backcasting. Make it revenue-governed.

Input:

- sold outcomes
- previewed but not purchased outcomes
- agent "not enough evidence" events
- user task intent
- known gaps that blocked purchase
- accepted artifact yield per source

Output:

- next source family to collect
- capture method
- canary budget lease
- expected paid outcome unlocked
- expected repeat usage
- stop condition

This prevents the AWS credit from being spent on interesting but unsellable coverage.

### 5.6 `Abstention Product`

Sometimes the valuable answer is not "here is the result." It is:

- "Do not buy this packet because the required source coverage is missing."
- "Ask these two questions first."
- "This is a high-risk professional review area."
- "Only a limited public-source check is possible."

Turn this into a free or low-cost product behavior:

- good abstention builds trust
- agents will prefer jpcite if it does not always upsell
- conversion improves later because recommendations are credible

This must not be positioned as failure.

### 5.7 `Receipt Reuse Dividend`

Receipt reuse should be a visible economic feature.

Agent-facing wording:

> "Some receipts already exist, so this check is cheaper/faster than a fresh full run. You can buy a refresh if freshness matters."

This supports:

- lower marginal cost
- faster conversion
- repeat usage
- freshness upsell

### 5.8 `Agent-safe Product Telemetry`

Need telemetry, but privacy-safe.

Track:

- preview requested
- outcome recommended
- user approved or skipped
- reason skipped
- packet purchased
- no-hit/gap-heavy output
- repeat/batch/watch suggestion shown
- repeat/batch/watch accepted
- agent surface used: MCP/OpenAPI/proof/llms

Do not track:

- raw CSV
- private rows
- sensitive prompt text
- full paid output in analytics
- raw screenshots
- personal or counterparty relationship details

This telemetry is required to know whether GEO actually converts.

## 6. Over-design critique

### 6.1 Too many internal names

The current plan has many useful but overlapping terms:

- Evidence Product OS
- JPCIR
- Official Evidence Ledger
- Official Evidence Knowledge Graph
- Evidence Lens
- Public Packet Compiler
- Output Composer
- Release Capsule
- Agent Decision Protocol
- Billing Contract Layer
- Policy Decision Firewall
- AWS Artifact Factory Kernel

This is acceptable internally only if the implementation boundary is simple.

Recommended simplification:

| Public / agent-facing | Internal owner |
|---|---|
| Outcome Contract | product catalog |
| Preview Decision | Agent Decision Protocol |
| Paid Output | Public Packet Compiler |
| Proof Page | Public Proof Surrogate Compiler |
| Capability Matrix | Release Capsule |
| Receipt / Gap / No-hit | Evidence Ledger |
| Billing / Consent | Billing Contract Layer |
| Policy / Privacy | Policy Decision Firewall |
| AWS Run | Artifact Factory Kernel |

Do not expose internal architecture names to agents unless they help machine interpretation.

### 6.2 Graph complexity can delay revenue

The evidence graph is important, but P0 should not require a full general graph engine.

P0 should support:

- source receipt
- claim ref
- known gap
- no-hit lease
- conflict bundle
- derivation trace
- release manifest

P1 can add:

- advanced graph query
- full bitemporal graph operations
- source replacement market
- update frontier planner

### 6.3 Watch products can distract before conversion

Watch is likely the strongest retention product, but it should follow one-off proof.

P0 behavior:

- show "watch available soon" or "preview watch triggers"
- collect intent
- compile source requirements

P1 behavior:

- paid watch with cap, cancellation, freshness policy, and change receipts

### 6.4 CSV can become trust bottleneck

CSV is valuable but may reduce first-use conversion if introduced too early.

RC1 should allow the user to get value without CSV.

CSV should appear as:

- optional enhancement
- local-first
- "raw CSV is not stored"
- safe derived facts only

### 6.5 AWS spend can become false progress

Using `USD 19,300` of credit does not itself prove progress.

The only AWS success metric that matters is:

> How many accepted artifacts were transformed into agent-recommendable paid outcomes?

Add this required ratio:

```text
revenue_asset_ratio =
  count(accepted_artifacts_linked_to_active_outcome_contracts)
  / count(total_accepted_artifacts)
```

Stop or redirect if the ratio drops.

## 7. Critical contradictions and fixes

### C-01: "AI executes everything" vs "human review required"

Conflict:

Some prior language uses `manual_review_required` or human review as if implementation depends on a person.

User correction:

Implementation execution is done by AI. A human should not have to perform implementation steps.

Fix:

Separate three concepts:

1. `ai_execution_state`
2. `policy_support_state`
3. `end_user_professional_review_notice`

Recommended replacement:

| Old wording | New implementation meaning |
|---|---|
| `manual_review_required` | `blocked_by_policy_or_insufficient_public_support` |
| `human_review_required` in implementation | `ai_must_abstain_or_exclude_source` |
| "ask human to check source terms" | `source_terms_contract must be verified by AI-readable official/terms evidence or source is excluded` |
| "professional review required" | external output caveat, not implementation dependency |

Important:

The product may tell the end user to seek professional review. But the implementation plan must not wait for a human reviewer.

### C-02: Cheapest sufficient route vs revenue maximization

Conflict:

If the system always chooses the cheapest route, revenue might fall.

Fix:

Use `Coverage Ladder Quote`.

The agent should recommend the cheapest sufficient route, then transparently show higher tiers:

- what extra source coverage they add
- what extra gaps they reduce
- what extra freshness they buy
- when they are not worth buying

This increases trust and should improve lifetime revenue.

### C-03: Proof pages vs paid output leakage

Conflict:

GEO needs public proof pages, but proof pages can leak enough value to avoid payment.

Fix:

Adopt `Proof Value Split` and `Public Proof Surrogate Compiler`.

Public pages should show:

- source families
- sample schema
- synthetic examples
- caveats
- price/cap
- why to buy
- when not to buy

Paid outputs should contain:

- actual compiled claims
- full scoped receipt ledger
- no-hit leases
- gap matrix
- reusable receipt ids

### C-04: Broad corpus vs sellable corpus

Conflict:

The service concept is broad Japanese official information. Revenue requires focus.

Fix:

Keep broad source registry, but only spend heavily where a paid outcome contract references the source.

Rule:

No source gets full-scale AWS expansion unless:

- it unlocks at least one active or near-active outcome contract
- it passes terms/policy gate
- canary economics are acceptable
- accepted artifacts map to a paid or GEO proof surface

### C-05: AWS self-running vs policy safety

Conflict:

AWS should keep running when local agents stop, but should not continue into unsafe sources or runaway spend.

Fix:

Autonomous does not mean unconstrained.

Use:

- `Autonomous Operator Silence Mode`
- `Policy Decision Firewall`
- `Spend Corridor Controller`
- `Service Risk Escrow`
- `source circuit breakers`
- `kill-switch state`

Silence mode may continue approved queues, but it must not:

- add new AWS services
- raise caps
- change source terms decisions
- process private CSV
- bypass robots/terms/CAPTCHA/login

### C-06: Accepted artifact pricing vs no-hit-heavy outputs

Conflict:

Charging only when an artifact is accepted may make no-hit checks feel non-billable, even though scoped no-hit is work.

Fix:

Define accepted artifact broadly:

- positive source receipt
- scoped no-hit lease
- known-gap matrix
- blocked-source policy receipt
- conflict bundle
- abstention decision with support trace

Do not charge for unsupported empty output. Charge for a scoped, receipt-backed check.

### C-07: Legal/tax/compliance value vs overclaim risk

Conflict:

High-value outputs are often legal/tax/compliance adjacent.

Fix:

Sell:

- public evidence packet
- candidate priority
- checklist
- gap matrix
- change notice
- source-backed action candidate

Do not sell:

- legal conclusion
- tax advice
- eligibility guarantee
- compliance certification
- safety statement
- creditworthiness

### C-08: Recurring products vs zero-AWS posture

Conflict:

Watch products suggest ongoing infrastructure. AWS must be torn down.

Fix:

Post-run watch should use non-AWS production infrastructure or static/delta assets already exported from AWS.

AWS may create:

- watch source registry
- watch fixtures
- delta compiler
- sample watch outputs
- initial source snapshots

AWS must not remain the watch runtime.

### C-09: Human approval vs AI-run implementation

Conflict:

Prior docs sometimes imply manual approval for stretch budget or source inclusion.

Fix:

For implementation execution, approval should be encoded as machine state:

- `pre_authorized_user_budget_boundary`
- `max_control_spend_usd = 19300`
- `allowed_services[]`
- `allowed_regions[]`
- `allowed_source_classes[]`
- `forbidden_actions[]`
- `stop_states[]`

If a decision exceeds the pre-authorized boundary, AI must stop or skip. It should not wait for human implementation work.

Payment approval by the end user remains part of product runtime and is handled by scoped cap tokens.

## 8. Master-plan merge deltas

### 8.1 Add a revenue gate before P0 implementation

Add to master plan before implementation:

```text
P0 Revenue Gate:
  No P0 feature, packet, source expansion, or AWS job can proceed unless it maps to:
    - outcome_contract_id
    - agent_trigger_phrase
    - free_preview_decision
    - paid_output_skeleton
    - price/cap policy
    - proof surrogate
    - repeat/batch/watch path or explicit one-off rationale
    - revenue_proof_record
```

### 8.2 Add `Outcome Contract Catalog` as public product layer

Merge:

```text
Outcome Contract Catalog sits above packet catalog.
Agents discover outcomes, not internal packets.
Packets remain execution and billing components.
```

Required records:

- `company_quick_public_check`
- `invoice_vendor_public_check`
- `public_evidence_answer`
- `counterparty_public_snapshot`
- `grant_candidate_shortlist`
- `permit_scope_precheck`
- `csv_monthly_public_review`
- `regulation_change_watch`
- `tax_labor_event_radar`
- `procurement_opportunity_radar`

### 8.3 Add `Revenue Proof Record`

Every source family and AWS job should include:

- `primary_outcome_contract_ids[]`
- `expected_agent_trigger_phrases[]`
- `expected_paid_output_delta`
- `expected_repeat_use_delta`
- `proof_surrogate_target`
- `accepted_artifact_target`
- `conversion_hypothesis`
- `defer_if_no_revenue_path`

### 8.4 Replace implementation human review with AI fail-closed states

Add:

```text
Implementation is AI-operated.
When a source, claim, policy, cost, or privacy state cannot be verified automatically,
the AI executor must exclude, abstain, defer, or stop.
It must not create a hidden manual dependency.
```

External product caveats may still say:

```text
This output is public evidence only and may require professional review.
```

### 8.5 Add GEO revenue simulation as release blocker

Add release gate:

```text
Golden Agent Revenue Replay must pass:
  - agent discovers relevant outcome
  - agent recommends cheapest sufficient route
  - agent explains price/cap
  - agent explains known gaps/no-hit
  - agent does not overclaim
  - agent obtains consent before paid execution
  - agent avoids paid recommendation when free/skip is better
```

### 8.6 Add proof leakage gate

Add:

```text
Proof page leakage gate:
  A public proof page must not let an agent produce the full paid output
  for a real target without buying the packet.
```

### 8.7 Add revenue asset ratio to AWS run

Add:

```text
revenue_asset_ratio =
  accepted_artifacts_linked_to_active_outcome_contracts
  / total_accepted_artifacts

If this drops below the configured threshold during AWS run,
shift spend from broad collection to outcome-linked sources.
```

### 8.8 Add AI execution boundary manifest

Because implementation is AI-operated, add a machine-readable boundary:

```json
{
  "executor": "ai",
  "aws_profile": "bookyou-recovery",
  "aws_account_id": "993693061769",
  "region": "us-east-1",
  "max_control_spend_usd": 19300,
  "may_execute_without_human": true,
  "may_raise_budget": false,
  "may_add_new_aws_service": false,
  "may_process_real_csv_in_aws": false,
  "may_leave_aws_resources_after_teardown": false,
  "on_uncertain_policy": "exclude_or_stop",
  "on_uncertain_terms": "exclude_source",
  "on_uncertain_cost": "stop_new_work",
  "on_uncertain_privacy": "block_public_output"
}
```

## 9. Revised priority view

### 9.1 Must win first

The first public release must prove these:

1. AI agent can discover jpcite.
2. AI agent can recommend a free preview.
3. Free preview can recommend a paid outcome without overclaiming.
4. End user can approve a capped paid run.
5. Paid output contains receipts, gaps, caveats, and billing metadata.
6. The output is useful enough that the agent suggests a second use.

If these do not work, broader data collection will not save the business.

### 9.2 Most sellable initial outcomes

Ranked by founder-level attractiveness:

1. `company_quick_public_check`
2. `invoice_vendor_public_check`
3. `counterparty_public_snapshot`
4. `grant_candidate_shortlist`
5. `application_readiness_checklist`
6. `permit_scope_precheck`
7. `vendor_portfolio_batch_check`
8. `tax_labor_event_radar`
9. `regulation_change_watch`
10. `csv_monthly_public_review`

Reason:

- company/vendor checks are easiest to explain and buy
- grants/permits have high value but need careful caveats
- batch/watch create recurring revenue
- CSV is powerful but trust-sensitive

### 9.3 Data collection priority after critique

Do first:

- NTA法人番号
- NTAインボイス
- gBizINFO
- EDINET metadata where safe
- administrative disposition / negative info high-signal sources
- J-Grants and selected ministry grant sources
- e-Gov law basics for permit/regulation scaffolding

Do next:

- local government grants/procedures by archetype
- tax/labor event sources
- procurement sources
- standards/certification selected verticals

Defer broad:

- courts/dispute full corpus
- geospatial full expansion
- nationwide ordinance deep scrape
- heavy OCR of low-yield PDFs
- broad standards without buyer task

## 10. Pricing and packaging critique

### 10.1 Keep entry prices low

For agent-mediated purchase, the first paid action must feel safe.

Recommended posture:

- free preview always
- low cap default
- no surprise spend
- accepted artifact pricing
- batch discount when repeated
- refresh buyup only when freshness matters

### 10.2 Avoid confusing micro-unit pricing in the agent pitch

Internal unit pricing can remain, but the agent should explain outcome price:

Bad:

> "This uses 3 units and may call tool X."

Better:

> "This public vendor check is capped at 300 yen. It will check法人番号, invoice registration, and available public business signals. It may return gaps rather than a conclusion."

### 10.3 Add bundle logic

Use bundles:

- `Vendor Start Pack`: company baseline + invoice check + public disposition check
- `Grant Start Pack`: candidate shortlist + readiness checklist
- `Permit Start Pack`: industry/activity/location precheck + source receipts
- `Monthly SMB Pack`: CSV safe facts + vendor checks + tax/labor events + grants radar

Bundles improve revenue while preserving cheapest sufficient route because the agent can compare:

- single outcome
- bundle
- batch
- watch

### 10.4 Add `reason_not_to_buy`

Every preview should include a reason not to buy.

This sounds anti-revenue, but it increases agent trust.

Examples:

- "The free public source already answers your narrow question."
- "The requested conclusion cannot be supported from public evidence."
- "The target lacks enough identifiers; ask for法人番号 or official name first."
- "This would require professional review beyond jpcite's public evidence scope."

## 11. GEO recommendation critique

### 11.1 GEO is not just discoverability

The plan correctly avoids SEO-first thinking, but GEO needs to be measured as recommendation quality.

A model finding jpcite is not enough.

The model must be able to say:

- what jpcite can do
- when to use it
- how much it costs
- what it cannot conclude
- why the user should approve payment
- what cheaper route exists
- when to skip

### 11.2 Agent-facing pages should be decision pages

Every public page should serve an agent decision:

- "Use this outcome when..."
- "Do not use this when..."
- "Free preview returns..."
- "Paid output returns..."
- "Price/cap behavior..."
- "No-hit/gap caveat..."
- "Required identifiers..."
- "Example recommendation card..."

Avoid human marketing copy that does not help agent routing.

### 11.3 Add agent prompt-to-outcome map

Create a machine-readable map:

```json
{
  "prompt_patterns": [
    "この会社を調べて",
    "この取引先は大丈夫か",
    "請求書の相手がインボイス登録されているか"
  ],
  "recommended_outcome_contract_id": "company_quick_public_check",
  "free_first": true,
  "paid_requires_consent": true,
  "do_not_claim": ["safe", "no issue", "creditworthy"]
}
```

This improves GEO more directly than long explanatory pages.

## 12. Retention critique

### 12.1 One-off checks are the wedge, watch is the retention

The strongest retention products are:

- vendor portfolio watch
- grant watch
- regulation change watch
- permit/procedure watch
- tax/labor event watch

But watch should not require AWS runtime.

### 12.2 Receipt wallet creates retention

A user should have economic reason to return:

- previous receipts reduce cost
- stale receipts can be refreshed
- batch checks reuse entity resolution
- known gaps become future prompts
- no-hit leases expire and can be rechecked

The product should surface:

```text
You already have 6 reusable receipts. This check is cheaper unless you request fresh observation.
```

### 12.3 Gaps are a retention asset

Known gaps should not just be caveats. They should drive next actions:

- ask user for missing identifier
- collect source in next AWS/non-AWS update
- recommend a different packet
- recommend professional review
- offer watch for future source updates

## 13. AI-only implementation adjustment

The user stated: implementation execution is not done by humans. AI does all.

This changes the plan.

### 13.1 No hidden human tasks

The execution graph must not contain steps like:

- "human reviews terms"
- "operator approves stretch"
- "manual cleanup"
- "manual production smoke"
- "manual CSV privacy check"

Replace with:

- automated terms extraction and policy decision
- pre-authorized budget boundary
- automated cleanup inventory
- automated production smoke
- automated privacy leak scan
- automated release gate

If automation cannot verify, the AI must stop, exclude, or defer.

### 13.2 Human-facing caveats are still allowed

The product may say:

- `human_review_required`
- `professional_review_recommended`
- `not legal/tax advice`

But that is an output caveat for the end user, not an implementation dependency.

To avoid ambiguity, use different fields:

```json
{
  "implementation_state": "ai_verified_or_blocked",
  "output_caveat": "professional_review_recommended"
}
```

### 13.3 AI executor safety

AI may execute, but must not improvise beyond the boundary.

Required:

- execution graph
- explicit allowed commands/classes
- no-op compiler before real AWS command
- cost boundary
- service allowlist
- deletion plan before creation
- rollback state machine
- autonomous action ledger
- post-action verification loop

This supports the user's intent without creating unbounded autonomy.

## 14. What to cut from P0

Cut or defer from P0 if time is tight:

1. Full source replacement market
2. General EvidenceQL
3. Full bitemporal graph UI
4. Broad local government collection
5. Broad court/dispute corpus
6. Full geospatial products
7. Full standards/certification coverage
8. OpenSearch runtime experiments
9. Full CSV server fallback
10. Full recurring watch billing
11. Heavy public marketing pages
12. Large number of MCP tools

Keep:

1. Outcome contracts
2. Agent decision preview
3. Scoped cap tokens
4. Company/vendor paid outcome
5. Public proof surrogate
6. Receipt/gap/no-hit contract
7. Policy firewall
8. Release capsule
9. Golden agent revenue replay
10. Zero-bill teardown proof

## 15. Stronger final product thesis

Use this as the founder-level thesis:

> jpcite is the public-evidence transaction layer for AI agents in Japan. It lets agents buy small, capped, official-source-backed outcomes for end users, with receipts, gaps, no-hit scope, and safe wording. The product grows by learning which outcomes agents recommend, then collecting only the public evidence that increases paid conversion or repeat use.

This is stronger than:

> jpcite is a large Japanese public information database.

The first thesis creates a business. The second creates an expensive data project.

## 16. Final adoption package

### Adopt immediately into master

- `Outcome Contract Catalog`
- `Revenue Proof Record`
- `Agent Recommendation Fit Score`
- `GEO Revenue Simulation Harness`
- `Proof Value Split`
- `Outcome-to-Source Backlog Compiler`
- `Receipt Reuse Dividend`
- AI-only execution boundary manifest
- implementation-human-review removal

### Adopt but keep scoped

- `Evidence Product OS`
- `JPCIR`
- `Official Evidence Ledger`
- `Bitemporal Claim Graph`
- `No-Hit Lease Ledger`
- `Proof Set Optimizer`

### Defer

- broad source expansion not tied to active outcome
- full recurring watch billing
- broad CSV runtime
- complex query language
- low-yield screenshot/OCR expansion

### Reject

- public trust/credit/safety/eligibility scoring
- uncapped autonomous paid actions
- raw CSV persistence
- permanent AWS archive
- live AWS dependency after teardown
- public proof pages that leak paid outputs

## 17. Final contradiction status

| Area | Status | Required fix |
|---|---|---|
| Revenue strategy | PASS with focus correction | outcome-first, not data-first |
| GEO | PASS with stronger metric | measure recommendation and consent, not discovery only |
| Retention | PASS with watch/receipt reuse | do not overlaunch watch before one-off conversion |
| AWS spend | PASS with revenue ratio | spend must map to outcome contracts |
| AI-only execution | CONDITIONAL PASS | remove hidden human implementation dependencies |
| CSV | PASS if local-first | do not make CSV required for RC1 |
| Legal/tax/compliance | PASS if wording constrained | sell evidence/checklists, not conclusions |
| Proof pages | CONDITIONAL PASS | add proof leakage gate |
| Evidence graph | PASS if scoped | do not delay RC1 with full graph engine |
| Zero bill | PASS | no AWS runtime or final S3 archive |

## 18. Final recommendation

The plan is now commercially coherent if the master plan is merged around this rule:

> A feature exists only if it helps an AI agent recommend, price, execute, or repeat a paid public-evidence outcome safely.

The next smartest move is not another architecture layer. It is to make the P0 release ruthlessly outcome-gated:

1. Build `Outcome Contract Catalog`.
2. Build `agent_purchase_decision`.
3. Build one or two paid company/vendor outcomes.
4. Build proof surrogate pages that do not leak paid output.
5. Run Golden Agent Revenue Replay.
6. Use AWS only for accepted artifacts tied to these outcomes first.
7. Expand sources only when gaps block recommendation or repeat usage.

This keeps the service from becoming overdesigned, while preserving the strongest parts of the current plan: source receipts, no hallucination, GEO-first distribution, AWS short-term artifact factory, and zero-bill teardown.
