# AWS smart methods round 3 review 07: pricing / billing / consent

Date: 2026-05-15  
Role: Round3 additional smart-method validation 7/20  
Topic: pricing, billing, consent, caps, refunds/free paths, accepted-artifact pricing, recurring watch billing  
Status: planning review only. AWS CLI/API/resource creation was not executed.  
Output constraint: this file only.

Planning references:

- Master plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- Round3 product packaging: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_02_product_packaging.md`
- Round3 agent/MCP UX: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_03_agent_mcp_ux.md`
- Round3 AWS factory/cost: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_06_aws_factory_cost.md`

Hard constraints carried forward:

- AWS account/profile/region are planning references only: `bookyou-recovery`, `993693061769`, `us-east-1`.
- No AWS CLI/API/resource operation is part of this review.
- GEO-first remains the commercial route.
- `agent_routing_decision` remains a free control.
- Paid work must always pass preview, user consent, scoped cap, idempotency, execution, retrieval, and billing receipt.
- Public/private real accounting CSV must not enter AWS.
- Request-time LLM fact generation remains off.
- no-hit is always `no_hit_not_absence`.
- Production must not depend on AWS runtime after the credit run.
- Zero-bill AWS teardown remains mandatory.

## 0. Verdict

Conditional PASS, with a stronger billing method.

The existing plan already has the right commercial primitives:

- `Outcome Contract Catalog`
- `Coverage ROI Curve`
- `Safe Autopay Envelope`
- `Accepted Artifact Pricing`
- `agent_purchase_decision`
- `Scoped Cap Token`
- `buyer_policy_profile`
- `watch_delta_product`

The smarter method is:

```text
Do not sell API calls, packet names, or broad subscriptions.
Sell consented outcome contracts that charge only when an accepted artifact is produced.
```

The pricing/billing layer should become a compiler-generated protocol:

```text
Outcome Contract Catalog
-> agent_purchase_decision
-> user consent envelope
-> scoped cap token
-> accepted artifact gate
-> charge/refund/free decision
-> user/agent billing receipt
-> optional bounded watch envelope
```

This keeps the promise:

> AI agents can help end users obtain cheap, source-backed public-information outputs without surprise billing, unsupported upsell, or hidden recurring spend.

## 1. Main correction

The current language can still drift toward:

```text
price quote -> cap token -> execute packet -> charge
```

That is not smart enough.

The correct model should be:

```text
agent task
-> cheapest sufficient outcome contract
-> explicit coverage and no-hit boundary
-> scoped consent
-> artifact acceptance test
-> charge only accepted artifact classes
```

This matters because the user is not buying computation. The user is buying a bounded business result:

- "この取引先の公的基本確認"
- "この会社が使えそうな補助金候補"
- "この業種・地域の許認可確認点"
- "この制度変更が自社に関係ありそうか"
- "この月次CSVから公的制度上の注意点"

The billing system must mirror that product reality.

## 2. Adopted smart method A: Billing Contract Layer

### 2.1 Problem

`Outcome Contract Catalog` defines what is sold, but the plan still needs a pricing/billing binding that is stricter than a human-readable catalog row.

Without a separate billing contract layer, these can drift:

- public proof price
- MCP preview price
- OpenAPI example price
- frontend price
- cap token scope
- actual invoice calculation
- refund/no-charge rules
- watch renewal terms

### 2.2 Adopt

Add a generated `billing_contract_catalog`.

It is compiled from:

- `outcome_contract_catalog`
- packet catalog
- pricing policy
- buyer policy profile rules
- accepted artifact classes
- no-hit policy
- refund/free policy
- watch policy

Example:

```json
{
  "billing_contract_id": "bc_vendor_public_baseline_v1_jpy",
  "outcome_contract_id": "vendor_public_baseline_v1",
  "price_model": "accepted_artifact_pricing",
  "currency": "JPY",
  "tax_display_mode": "show_ex_tax_and_inc_tax",
  "default_hard_cap_jpy_inc_tax": 330,
  "billable_unit_policy": {
    "internal_unit_price_jpy_ex_tax": 3,
    "external_price_is_cap_not_guaranteed_charge": true,
    "reconcile_units_to_cap": true
  },
  "billable_artifact_classes": [
    "accepted_public_observation",
    "accepted_scoped_no_hit_observation",
    "accepted_gap_coverage_matrix",
    "accepted_packet_summary"
  ],
  "free_artifact_classes": [
    "agent_purchase_decision",
    "unsupported_task_decline",
    "do_not_buy_recommendation",
    "duplicate_preview",
    "failed_acceptance_no_output"
  ],
  "refund_policy_id": "refund_no_accepted_artifact_v1",
  "watch_policy_id": "watch_delta_bounded_v1",
  "consent_required": true,
  "autopay_allowed": "only_if_safe_autopay_envelope_exists",
  "silent_scope_expansion_allowed": false
}
```

### 2.3 Why this is smarter

It creates one machine-readable source for:

- what can be charged
- when it can be charged
- what is free
- what must be refunded or voided
- what the agent must explain before consent
- what the cap token may authorize
- what recurring watch may do

This prevents the service from becoming "cheap-looking preview, surprising execution bill."

## 3. Adopted smart method B: Agent Purchase Decision as a Contract Offer

### 3.1 Problem

`agent_purchase_decision` could be implemented as a recommendation blob. That is too weak for paid execution.

For billing, it must be an offer-like object:

```text
What will be attempted?
What will not be attempted?
What can be charged?
What is the maximum charge?
What happens if no accepted artifact is produced?
What gaps remain?
What no-hit language must be used?
When does the offer expire?
```

### 3.2 Adopt

Make `agent_purchase_decision` the only source from which a paid cap token can be minted.

Required fields:

```json
{
  "decision_type": "agent_purchase_decision",
  "decision_id": "apd_...",
  "decision_hash": "sha256:...",
  "outcome_contract_id": "vendor_public_baseline_v1",
  "billing_contract_id": "bc_vendor_public_baseline_v1_jpy",
  "recommended_action": "buy_with_cap",
  "cheapest_sufficient_route": {
    "packet_type": "company_public_baseline",
    "why_sufficient": "basic public company and invoice observation",
    "why_not_more_expensive": "administrative disposition and permit sources are outside the stated task"
  },
  "coverage_roi_curve": [],
  "do_not_buy_if": [],
  "ask_first_if": [],
  "known_gaps_before_purchase": [],
  "no_hit_language_pack_id": "no_hit_not_absence_ja_v1",
  "billing_terms": {
    "price_model": "accepted_artifact_pricing",
    "max_price_jpy_inc_tax": 330,
    "no_charge_if": [
      "no_accepted_artifact",
      "policy_block_before_execution",
      "source_terms_block_before_execution"
    ],
    "partial_charge_allowed": true,
    "partial_charge_explanation_required": true
  },
  "consent_requirements": {
    "human_user_consent_required": true,
    "delegated_agent_consent_allowed": false,
    "safe_autopay_allowed": false
  },
  "expires_at": "2026-05-15T12:00:00Z"
}
```

### 3.3 Merge rule

Paid execution must reject any cap token that does not bind to:

- `decision_id`
- `decision_hash`
- `billing_contract_id`
- input hash
- packet/outcome scope
- allowed source families
- cap
- expiry
- idempotency key

## 4. Adopted smart method C: Consent Envelope

### 4.1 Problem

An AI agent can recommend purchase, but the service must not treat the agent's text as unlimited user consent.

The consent boundary must be explicit, machine-readable, and replayable.

### 4.2 Adopt

Add `consent_envelope`.

Example:

```json
{
  "consent_envelope_id": "ce_...",
  "decision_id": "apd_...",
  "decision_hash": "sha256:...",
  "consent_actor": {
    "type": "human_user",
    "agent_session_id": "optional_agent_session_ref"
  },
  "consented_scope": {
    "outcome_contract_id": "vendor_public_baseline_v1",
    "packet_types": ["company_public_baseline"],
    "input_hash": "sha256:...",
    "allowed_source_families": [
      "corporate_identity",
      "business_registry_signal"
    ],
    "excluded_claims": [
      "creditworthiness",
      "safety",
      "legal_opinion",
      "反社判定",
      "問題なし断定"
    ],
    "freshness_policy": "reuse_or_selective_refresh",
    "proof_depth": "standard"
  },
  "cap": {
    "max_price_jpy_inc_tax": 330,
    "max_attempts": 1,
    "expires_at": "2026-05-15T12:00:00Z"
  },
  "billing_acknowledgements": [
    "charge_only_for_accepted_artifact",
    "no_hit_not_absence",
    "known_gaps_may_remain",
    "not_legal_tax_credit_safety_opinion"
  ],
  "autopay": {
    "enabled": false
  }
}
```

### 4.3 Consent invariants

The service must block paid execution if:

- consent is missing
- consent expired
- input hash changed
- packet type changed
- source families expanded
- price cap increased
- outcome contract changed
- billing contract changed
- no-hit policy changed materially
- agent attempts recurring watch without a watch consent envelope

## 5. Adopted smart method D: Scoped Cap Token v2

### 5.1 Problem

A cap token that only says "up to 330 yen" is unsafe.

It must also say "for exactly this outcome, this input, this source scope, this billing contract, this consent, and this time window."

### 5.2 Adopt

The cap token should be derived from the consent envelope, not directly from preview.

Required claims:

```json
{
  "token_type": "jpcite_scoped_cap_token",
  "version": "v2",
  "decision_id": "apd_...",
  "consent_envelope_id": "ce_...",
  "billing_contract_id": "bc_...",
  "outcome_contract_id": "vendor_public_baseline_v1",
  "input_hash": "sha256:...",
  "max_price_jpy_inc_tax": 330,
  "allowed_packet_types": ["company_public_baseline"],
  "allowed_source_families": [
    "corporate_identity",
    "business_registry_signal"
  ],
  "blocked_source_families": [
    "private_csv",
    "credit_bureau",
    "non_public_source"
  ],
  "idempotency_key": "idem_...",
  "expires_at": "2026-05-15T12:00:00Z"
}
```

### 5.3 Security rule

Do not expose payment method details, processor tokens, secret keys, or full user billing identifiers to MCP/OpenAPI agent surfaces.

Agent-visible billing data should be limited to:

- outcome name
- cap
- charge/no-charge status
- accepted artifact count
- billing receipt ID
- refund/void status
- user-safe explanation

## 6. Adopted smart method E: Accepted Artifact Pricing

### 6.1 Problem

Charging for attempts can damage trust.

The user wants cheap outputs. The AI agent must be able to say:

```text
You only pay if jpcite produces an accepted artifact within the agreed scope.
```

### 6.2 Adopt

Add explicit `accepted_artifact_class`.

Suggested classes:

```text
accepted_public_observation
accepted_scoped_no_hit_observation
accepted_gap_coverage_matrix
accepted_packet_summary
accepted_delta_statement
accepted_watch_no_change_statement
accepted_action_checklist
accepted_receipt_ledger
```

Each class needs:

- acceptance criteria
- minimum support state
- required caveats
- public/private visibility
- whether it is billable
- whether it can be discounted by receipt reuse
- whether it can be used in watch products

Example:

```json
{
  "accepted_artifact_class": "accepted_scoped_no_hit_observation",
  "billable": "only_if_contract_explicitly_includes_no_hit_observation",
  "minimum_fields": [
    "source_family_id",
    "source_id",
    "query_scope",
    "observed_at",
    "staleness_ttl",
    "no_hit_policy",
    "no_hit_not_absence_caveat"
  ],
  "forbidden_external_claims": [
    "not_found_means_absent",
    "safe",
    "no_issue",
    "permission_not_required"
  ]
}
```

### 6.3 No accepted artifact = no charge

The default rule:

```text
If no accepted artifact is produced, the paid execution is void/no-charge.
```

Exceptions must be explicit in the billing contract. For example, a contract may charge for an accepted scoped no-hit observation only when:

- the preview clearly said no-hit observations are billable
- the user consent envelope acknowledged it
- the source scope was specific
- the result contains no-hit caveats
- the no-hit lease has expiry and checked scope

## 7. Adopted smart method F: Charge / Free / Refund Decision Engine

### 7.1 Problem

Refund rules are often implemented after billing. That is weaker than preventing incorrect charge events.

### 7.2 Adopt

Add a deterministic `billing_outcome_decision`.

States:

```text
free_preview
free_decline
no_charge_policy_block
no_charge_no_accepted_artifact
no_charge_duplicate_within_reuse_window
partial_charge_accepted_subset
full_charge_accepted_contract
auto_void
auto_refund
manual_billing_review
```

Example:

```json
{
  "billing_outcome_decision": {
    "status": "partial_charge_accepted_subset",
    "billing_contract_id": "bc_vendor_public_baseline_v1_jpy",
    "cap_jpy_inc_tax": 330,
    "charge_jpy_inc_tax": 180,
    "charge_basis": [
      {
        "accepted_artifact_id": "aa_...",
        "accepted_artifact_class": "accepted_public_observation",
        "unit_count": 60
      }
    ],
    "not_charged_basis": [
      {
        "reason": "source_terms_blocked_before_execution",
        "source_family_id": "business_registry_signal"
      }
    ],
    "agent_explanation_ja": "同意範囲内で受入済みになった公的観測分だけ課金しました。未取得部分は課金していません。"
  }
}
```

### 7.3 Free paths

Always free:

- route/catalog lookup
- cost preview
- `agent_purchase_decision`
- "do not buy" recommendation
- unsupported task decline
- policy/terms block before execution
- validation failure before paid run starts
- no accepted artifact, unless explicitly consented no-hit artifact was produced

Usually free or discounted:

- duplicate result inside a reuse window
- cached receipt reuse where no fresh acquisition was needed
- watch check that produces no meaningful delta, unless the user bought no-change statements
- failed source canary that only informs internal source registry

Billable only if consented and accepted:

- accepted packet output
- accepted receipt ledger
- accepted scoped no-hit observation
- accepted delta statement
- accepted action checklist
- accepted portfolio batch artifact

## 8. Adopted smart method G: Receipt Reuse Dividend

### 8.1 Problem

The service should be cheap because it reuses public official receipts. If the agent cannot see that reuse lowers cost, it loses a major selling point.

### 8.2 Adopt

Add `receipt_reuse_dividend` to preview and billing receipt.

Example:

```json
{
  "receipt_reuse_dividend": {
    "reuse_available": true,
    "fresh_fetch_needed": false,
    "estimated_savings_jpy_inc_tax": 120,
    "why_cheaper": "法人番号とインボイス観測は既存の有効receiptを再利用できます",
    "freshness_ttl": "P7D",
    "buy_freshness_option": {
      "available": true,
      "incremental_cap_jpy_inc_tax": 90,
      "agent_should_recommend_if": "ユーザーが最新反映を明示的に重視する場合のみ"
    }
  }
}
```

### 8.3 Merge rule

The cheapest sufficient route solver should prefer:

```text
valid reused receipt
-> selective refresh
-> full fresh acquisition
```

unless the buyer policy requires fresh evidence.

## 9. Adopted smart method H: Coverage ROI Billing

### 9.1 Problem

The `Coverage ROI Curve` explains value, but billing should also enforce it.

If the user consents to baseline coverage, execution should not silently run and bill DD-lite coverage.

### 9.2 Adopt

Each coverage step becomes a separate billable scope.

Example:

```json
{
  "coverage_step_id": "vendor_baseline",
  "max_price_jpy_inc_tax": 330,
  "source_families": [
    "corporate_identity",
    "business_registry_signal"
  ],
  "excluded_source_families": [
    "enforcement_disposition",
    "permit_registry"
  ]
}
```

Buy-up requires a new preview and consent unless the original consent envelope explicitly included bounded buy-up.

### 9.3 Anti-upsell invariant

The preview must include:

```text
cheapest_sufficient_route
anti_upsell_reason
buy_up_options
```

It should be a release blocker if public surfaces only show high-tier recommendations.

## 10. Adopted smart method I: Safe Autopay Envelope

### 10.1 Problem

Recurring watch products are commercially important, but they can conflict with "cheap" and "no surprise billing."

The service should not sell vague subscriptions.

### 10.2 Adopt

Recurring spend must use a `safe_autopay_envelope`.

Example:

```json
{
  "safe_autopay_envelope_id": "sae_...",
  "watch_contract_id": "watch_vendor_public_delta_v1",
  "buyer_policy_profile_id": "bpp_...",
  "allowed_outcomes": [
    "vendor_public_baseline_delta",
    "administrative_disposition_delta"
  ],
  "max_charge_per_event_jpy_inc_tax": 330,
  "max_charge_per_month_jpy_inc_tax": 990,
  "max_events_per_month": 3,
  "minimum_delta_threshold": {
    "charge_only_if": [
      "new_accepted_public_observation",
      "material_source_change",
      "new_known_gap_with_action"
    ],
    "do_not_charge_if": [
      "no_change",
      "source_temporarily_unavailable",
      "duplicate_delta",
      "format_change_without_claim_change"
    ]
  },
  "renewal": {
    "auto_renew": false,
    "explicit_reconfirm_required_after": "P30D"
  },
  "cancellation": {
    "user_can_cancel_any_time": true,
    "agent_can_cancel_if_delegated": true
  },
  "silent_scope_expansion_allowed": false
}
```

### 10.3 Watch products should be bounded

Allowed watch billing:

- per accepted delta
- monthly cap
- explicit source families
- explicit monitored entities/programs/topics
- expiration and renewal confirmation
- no-charge no-change checks by default

Forbidden watch billing:

- unlimited monthly subscription by default
- silent source family expansion
- silent cap increase
- charging for source failures
- charging for no-change unless explicitly bought as a no-change statement
- charging after consent expiry

## 11. Adopted smart method J: Watch Delta Product Pricing

### 11.1 Product shape

Watch should not be framed as "subscription to data."

It should be framed as:

```text
bounded delta statements for a specific outcome contract
```

Examples:

- `vendor_public_delta_statement`
- `grant_program_delta_statement`
- `regulation_change_delta_statement`
- `permit_procedure_delta_statement`
- `tax_labor_calendar_delta_statement`

### 11.2 Pricing options

Recommended defaults:

```text
free watch preview:
  show monitored scope, possible charge events, monthly cap

paid event:
  charge only accepted delta statements

no-change check:
  free by default
  billable only if the user explicitly bought an auditable no-change statement

monthly cap:
  required

renewal:
  explicit reconfirmation after short period in early product
```

### 11.3 Watch output must include

```json
{
  "watch_billing_receipt": {
    "watch_contract_id": "watch_vendor_public_delta_v1",
    "event_id": "wde_...",
    "charge_status": "no_charge_no_material_delta",
    "monthly_cap_remaining_jpy_inc_tax": 990,
    "next_allowed_check_after": "2026-05-16T00:00:00Z",
    "cancel_url_or_action": "available_in_account_or_agent_surface"
  }
}
```

## 12. Adopted smart method K: Billing Ledger

### 12.1 Problem

The plan has many ledgers: source, evidence, cost, zero-bill. Billing needs its own event ledger.

Do not mix customer billing with AWS spend accounting.

### 12.2 Adopt

Add append-only `billing_event_ledger`.

Events:

```text
preview_created
agent_purchase_decision_created
consent_envelope_created
cap_token_issued
execution_started
accepted_artifact_created
billing_outcome_decided
charge_authorized
charge_captured
charge_voided
refund_issued
watch_envelope_created
watch_event_evaluated
watch_cancelled
billing_manual_review_required
```

Each event should carry:

- event ID
- timestamp
- actor class
- decision ID
- consent envelope ID where relevant
- billing contract ID
- idempotency key
- amount if relevant
- reason code
- user-safe explanation
- audit-safe references

It must not carry:

- raw private CSV
- payment method secret
- raw full receipt text where not needed
- public screenshot body
- unnecessary personal data

## 13. Adopted smart method L: Billing Receipt for Agents

### 13.1 Problem

Agents need to explain the charge after execution. A generic invoice is not enough.

### 13.2 Adopt

Return `agent_billing_receipt_card`.

Example:

```json
{
  "agent_billing_receipt_card": {
    "charge_status": "charged",
    "amount_jpy_inc_tax": 330,
    "cap_jpy_inc_tax": 330,
    "why_charged": "同意された取引先公的基本確認の範囲で、受入済みの公的観測と証跡付き要約が生成されました。",
    "what_was_free": [
      "事前preview",
      "購入判断",
      "追加不要と判断した高額tier説明"
    ],
    "what_was_not_charged": [
      "同意範囲外の行政処分source",
      "許認可source"
    ],
    "remaining_gaps": [
      "この結果は信用力や安全性を証明しません"
    ],
    "no_hit_caveat": "no-hitは不存在や安全の証明ではありません"
  }
}
```

This becomes part of the packet response, not a separate human-only billing page.

## 14. Adopted smart method M: Refund / Void Rules

### 14.1 Default rules

Void/no-charge:

- execution never started
- consent expired before execution
- policy gate blocked before artifact production
- terms/robots/license gate blocked before artifact production
- input validation failed
- no accepted artifact
- idempotent duplicate within reuse window

Partial charge:

- some accepted artifacts produced
- other consented artifacts blocked or failed
- charge is below cap
- explanation lists charged and uncharged pieces

Auto-refund:

- charged amount exceeded cap
- charged scope differs from consent envelope
- packet contract version mismatch
- billing contract hash mismatch
- artifact later fails immediate post-charge acceptance audit
- forbidden phrase gate failed externally visible output

Manual review:

- payment processor inconsistency
- user disputes whether an artifact was accepted
- watch event classification is ambiguous
- policy revocation affects a recent charge

### 14.2 Artifact acceptance audit window

Add a short post-charge audit gate:

```text
accepted_at -> charge_authorized -> immediate acceptance recheck -> capture
```

For early production, prefer authorize-then-capture after acceptance check rather than capture-before-audit.

## 15. Adopted smart method N: Delegated Agent Consent

### 15.1 Problem

Some users may want agents to auto-buy cheap packets. That can be useful, but risky.

### 15.2 Adopt

Do not allow broad delegated consent at launch.

Allow only narrow delegated policies later:

```json
{
  "delegated_agent_consent_policy": {
    "enabled": true,
    "allowed_outcome_contracts": [
      "vendor_public_baseline_v1"
    ],
    "max_per_action_jpy_inc_tax": 330,
    "max_per_day_jpy_inc_tax": 990,
    "max_per_month_jpy_inc_tax": 3000,
    "requires_free_preview": true,
    "requires_cheapest_sufficient_route": true,
    "forbidden_if_known_gaps_include": [
      "requires_human_review",
      "legal_opinion_requested",
      "credit_or_safety_judgment_requested"
    ]
  }
}
```

P0 should require explicit human consent for paid execution. Delegated consent can be P1 after audit evidence exists.

## 16. Adopted smart method O: Tax / Display / Price Consistency

### 16.1 Problem

The plan uses internal `3 JPY ex-tax per billable unit` and external packet caps. These can drift.

### 16.2 Adopt

Every price surface should expose both:

- human-friendly cap
- machine reconciliation fields

Example:

```json
{
  "price_display": {
    "currency": "JPY",
    "max_price_ex_tax": 300,
    "max_price_inc_tax": 330,
    "tax_label": "消費税込",
    "final_charge_may_be_lower": true
  },
  "unit_reconciliation": {
    "unit_price_jpy_ex_tax": 3,
    "max_billable_units": 100,
    "accepted_units_charged": 80
  }
}
```

Release blocker:

```text
If MCP/OpenAPI/proof/frontend show inconsistent price/cap/tax fields, block release.
```

## 17. Contradiction checks

### 17.1 Accepted Artifact Pricing vs cheap user value

No contradiction.

It improves cheapness because failed attempts and unsupported tasks are not charged by default.

### 17.2 Accepted Artifact Pricing vs no-hit

Potential contradiction if no-hit is charged as "nothing found."

Resolution:

- no-hit may be billable only as an accepted scoped observation
- contract must explicitly include it
- consent must acknowledge it
- no-hit lease and caveat must be present
- wording must never imply absence or safety

### 17.3 Safe Autopay vs explicit consent

Potential contradiction.

Resolution:

- P0 paid execution requires explicit human consent
- safe autopay is only for bounded watch envelopes
- no silent source expansion
- no silent cap increase
- renewal confirmation required early

### 17.4 Coverage ROI Curve vs revenue maximization

No contradiction if the long-term business goal is agent trust.

The agent should prefer the cheapest sufficient route. Higher tiers are offered only as optional buy-ups with marginal value explained.

This may reduce short-term ARPU per transaction but should improve agent recommendation rate and repeat usage.

### 17.5 Billing ledger vs privacy

Potential contradiction if billing events store private inputs.

Resolution:

- billing ledger stores hashes, IDs, amounts, reason codes, and artifact references
- it must not store raw CSV, payment secrets, raw screenshots, or unnecessary personal data

### 17.6 Customer billing vs AWS credit spend

Potential contradiction if AWS credit cost is used to justify customer prices.

Resolution:

- customer billing is based on accepted outcome contracts
- AWS credit spend is internal artifact factory accounting
- do not expose "AWS cost" as the customer price basis
- do not let AWS credit exhaustion affect already consented customer caps

### 17.7 Watch products vs zero AWS bill

No contradiction if watch runtime uses post-AWS release capsules/static assets and normal production runtime, not retained AWS artifacts.

The AWS credit run may create watch-ready source profiles and evidence capsules, but it must not leave AWS resources running for watch products.

### 17.8 Refunds vs immutable audit

No contradiction.

Refunding or voiding a charge should not delete the audit trail. It creates a compensating billing event.

## 18. Merge into master execution plan

This file is the proposed merge delta. It does not edit the master plan directly.

### 18.1 Add to product/economics layer

Add:

```text
Billing Contract Layer
  - compile billing_contract_catalog from Outcome Contract Catalog
  - expose what is billable/free/refundable for each outcome
  - bind accepted artifact classes to price/cap/refund rules
```

### 18.2 Add to agent decision protocol

Replace any weak preview shape with:

```text
route
-> agent_purchase_decision as contract offer
-> consent_envelope
-> scoped_cap_token_v2
-> execute
-> accepted artifact gate
-> billing_outcome_decision
-> agent_billing_receipt_card
```

Canonical MCP flow:

```text
jpcite_route
jpcite_preview_cost
jpcite_create_consent_or_cap
jpcite_execute_packet
jpcite_get_packet
jpcite_get_billing_receipt
```

If P0 must stay at 4 tools, fold consent/cap creation into `jpcite_preview_cost` response plus `jpcite_execute_packet` precondition, but keep the internal records separate.

### 18.3 Add to schemas

New records:

```text
BillingContractRecord
AgentPurchaseDecisionRecord.billing_terms
ConsentEnvelopeRecord
ScopedCapTokenRecord.v2
AcceptedArtifactClassRecord
BillingOutcomeDecisionRecord
BillingEventLedgerRecord
AgentBillingReceiptCard
SafeAutopayEnvelopeRecord
WatchBillingReceiptRecord
DelegatedAgentConsentPolicyRecord
ReceiptReuseDividendRecord
```

### 18.4 Add to release blockers

Block release if:

- paid execution can run without `agent_purchase_decision`
- paid execution can run without consent envelope
- cap token is amount-only and not scope-bound
- price/cap differs across MCP/OpenAPI/proof/frontend
- no accepted artifact can still produce a charge without explicit contract exception
- no-hit is charged without explicit scoped no-hit consent
- safe autopay can silently expand source scope or cap
- watch can charge after consent expiry
- billing ledger stores raw private data or payment secrets
- refund/void states are not represented in the ledger
- agent-facing billing receipt omits no-hit caveat or known gaps

### 18.5 Add to P0/P1 split

P0:

- billing contract catalog for RC1 outcomes
- agent purchase decision as contract offer
- explicit human consent
- scoped cap token v2
- accepted artifact pricing
- no accepted artifact = no charge
- billing event ledger
- agent billing receipt card
- price/cap consistency release gate

P1:

- safe autopay envelope
- watch delta billing
- delegated agent consent
- receipt reuse dividend optimization
- partial charge/refund automation beyond simple void

P2:

- portfolio-level billing optimization
- organization policy-based auto-buy
- advanced proration
- multi-tenant billing analytics

## 19. Suggested minimal P0 contract for RC1

For RC1, keep billing narrow.

Paid outcomes:

- `vendor_public_baseline_v1`
- `source_receipt_ledger_v1`
- `evidence_answer_v1`

Free controls:

- catalog
- route
- preview
- `agent_purchase_decision`
- do-not-buy recommendation
- unsupported task decline

Required P0 behavior:

```text
1. Agent calls preview.
2. Preview returns cheapest sufficient route, coverage ROI curve, max cap, do-not-buy conditions, no-hit caveat, known gaps.
3. Human approves exact scope.
4. Service creates consent envelope and scoped cap token.
5. Execution compiles packet.
6. Accepted artifact gate decides charge/no-charge.
7. Billing receipt explains what was charged and not charged.
```

Do not launch RC1 paid execution if the system cannot explain:

```text
what the user bought
why it was sufficient
what was not included
why the final charge happened
why any missing result was not charged
```

## 20. Final recommendation

Adopt this pricing/billing/consent model.

The most important change is to treat billing as part of the product compiler, not as a payment afterthought.

The service should be able to tell an AI agent:

```text
This is the cheapest sufficient outcome.
This is the maximum price.
This is exactly what the user is consenting to.
This is what will be free.
This is what will be charged only if accepted.
This is what no-hit means.
This is how to cancel or avoid recurring spend.
This is the billing receipt after execution.
```

That is the commercially smart version because it aligns all parties:

- the end user gets cheap bounded outputs
- the AI agent can recommend safely
- jpcite can charge for real accepted value
- unsupported or failed work does not damage trust
- recurring revenue remains bounded and explainable
- the AWS artifact factory remains internal and does not leak into customer billing

