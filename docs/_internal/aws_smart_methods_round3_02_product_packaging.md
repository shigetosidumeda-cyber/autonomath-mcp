# AWS smart methods round 3 - 02 product packaging / economics

Date: 2026-05-15  
Owner lane: Round3 追加スマート化 2/20 / Product economics and packaging  
Status: planning review only. No AWS CLI/API execution. No AWS resource creation. No deployment.  
Output file: `docs/_internal/aws_smart_methods_round3_02_product_packaging.md` only.

## 0. Scope

This review starts from the already adopted product layer:

- `agent_purchase_decision`
- `agent_task_intake`
- `outcome_ladder`
- `coverage_ladder_quote`
- `freshness_buyup`
- `buyer_policy_profile`
- `watch_delta_product`
- `portfolio_batch_packet`
- `agent_recommendation_card`
- `proof page` as `agent_decision_page`

The question is not "which product should be released first."

The question is:

> Is there a smarter product, pricing, packaging, recurring revenue, bundle, and agent recommendation mechanism that makes jpcite easier for AI agents to recommend and easier for end users to buy cheaply?

## 1. Verdict

The current plan is coherent, but the product layer can be made smarter in one major way:

> Move from "packet catalog + price quote" to an `Outcome Contract Catalog`.

In the current plan, an AI agent can say:

```text
For this task, buy this packet. It costs up to this cap.
```

The smarter product should let the agent say:

```text
For your exact outcome, jpcite offers this cheapest sufficient outcome contract.
It includes these claims, these source families, this freshness level, this no-hit boundary,
this proof depth, this renewal option, and this hard cap.
More expensive options only add these specific coverage items.
If those extra items do not matter, do not buy the higher tier.
```

This is a better commercial mechanism because it converts "API usage" into "a scoped business outcome with a cap." It also reduces over-selling, improves trust, and makes recurring usage easier without relying on vague subscriptions.

## 2. Main product correction

The plan should not primarily sell:

- API calls
- source searches
- raw receipts
- broad packets
- subscriptions
- seats

It should sell:

- scoped outcome contracts
- accepted artifacts
- reusable public receipts
- delta statements
- workflow kits
- capped portfolios
- handoff binders

The internal meter can remain:

```text
3 JPY ex-tax per billable unit
```

But the external product shape should be:

```text
free decision
-> cheapest sufficient outcome contract
-> capped one-shot or capped recurring watch
-> accepted artifact
-> receipt reuse
-> renewal or delta follow-up
```

## 3. Adopted smart method A: Outcome Contract Catalog

### 3.1 Problem

`packet_type` is implementation-friendly, but it is not always buyer-friendly.

An end user does not naturally ask for:

```text
source_receipt_ledger
evidence_answer
counterparty_public_dd_packet
```

They ask for:

```text
この取引先を公的情報で確認して
この会社が使える補助金候補を出して
この業態で許認可の確認点を出して
今月のCSVから公的制度上の注意点を出して
```

The AI agent needs to map that task to a purchasable scope.

### 3.2 Adopt

Add an `outcome_contract_catalog` above the packet catalog.

The packet catalog remains the execution layer. The outcome contract catalog becomes the buying layer.

Example:

```json
{
  "outcome_contract_id": "vendor_public_baseline_v1",
  "display_name_ja": "取引先の公的基本確認",
  "task_family": "vendor_check",
  "primary_packet_type": "company_public_baseline",
  "allowed_claim_families": [
    "entity_identity",
    "invoice_registration_observation",
    "public_business_profile_observation"
  ],
  "excluded_claims": [
    "creditworthiness",
    "safety",
    "legal_opinion",
    "反社判定",
    "問題なし断定"
  ],
  "default_price_tier": "starter_330",
  "hard_cap_jpy_inc_tax": 330,
  "freshness_default": "reuse_or_selective_refresh",
  "proof_depth_default": "standard",
  "renewal_options": ["one_time", "watch_delta"],
  "required_inputs": ["company_name_or_corporate_number"],
  "optional_inputs": ["address_hint", "invoice_registration_number"],
  "agent_recommendation_position": "first_purchase_core"
}
```

### 3.3 Why this is smarter

It lets jpcite expose human and agent friendly products while preserving internal packet precision.

The agent no longer has to understand every packet. It can route:

```text
user task -> outcome contract -> packet path -> cap -> approval
```

### 3.4 Merge into execution plan

Add before the packet catalog implementation:

```text
P0-PACK-00 outcome_contract_catalog
  - compile buyer-facing outcome contracts from canonical packet catalog
  - map each outcome contract to packet_type, source families, allowed claims, excluded claims, default cap
  - generate docs/MCP/OpenAPI/pricing/proof surfaces from this catalog
```

### 3.5 Conflict check

No conflict if:

- outcome contracts never create factual claims by themselves
- execution still goes through packet compiler
- pricing still reconciles to 3 JPY ex-tax units
- outcome names do not imply final legal/accounting/tax/credit judgment

## 4. Adopted smart method B: Coverage ROI Curve

### 4.1 Problem

`coverage_ladder_quote` shows what higher tiers unlock. That is useful, but it is still tier-based.

A smarter agent needs to explain marginal value:

```text
Paying 660 yen more adds administrative disposition and license source coverage.
Paying more does not help if you only need invoice confirmation.
```

### 4.2 Adopt

Add `coverage_roi_curve` to free preview.

Example:

```json
{
  "coverage_roi_curve": [
    {
      "step": "baseline",
      "incremental_price_jpy_inc_tax": 330,
      "adds": ["corporate identity", "invoice registry observation"],
      "best_for": "basic accounting/vendor identity check",
      "agent_buy_reason": "cheapest sufficient route for identity and invoice status"
    },
    {
      "step": "dd_lite",
      "incremental_price_jpy_inc_tax": 660,
      "adds": ["selected public enforcement sources", "selected license/public business sources"],
      "best_for": "vendor onboarding with public-risk attention",
      "agent_buy_reason": "use only if the user needs broader public evidence"
    },
    {
      "step": "full_binder",
      "incremental_price_jpy_inc_tax": 2310,
      "adds": ["proof binder", "handoff summary", "expanded known gaps"],
      "best_for": "professional handoff or internal review",
      "agent_buy_reason": "not needed for quick screening"
    }
  ],
  "anti_upsell_gate": {
    "recommended_step": "baseline",
    "more_expensive_step_rejected_reason": "The user only asked for invoice/public identity confirmation."
  }
}
```

### 4.3 Why this is smarter

This makes jpcite economically trustworthy. AI agents can justify the cheapest sufficient path and reject unnecessary upsell.

### 4.4 Merge into execution plan

Add to `agent_purchase_decision`:

```json
{
  "coverage_roi_curve": [],
  "anti_upsell_gate": {
    "recommended_contract_id": "...",
    "rejected_more_expensive_options": []
  }
}
```

### 4.5 Conflict check

No conflict. It strengthens the existing "cheaply get the desired output" concept.

Release blocker:

- Any preview that always recommends the highest tier.
- Any preview that omits cheaper sufficient alternatives.

## 5. Adopted smart method C: Receipt Reuse Dividend

### 5.1 Problem

The plan already has receipt reuse. But the pricing effect is not explicit enough.

If users see that repeated usage gets cheaper because public receipts are reused, they have a reason to keep using jpcite.

### 5.2 Adopt

Add `receipt_reuse_dividend`.

This is not a discount coupon. It is a pricing explanation derived from lower work:

```json
{
  "reuse_quote": {
    "eligible_existing_receipts": 18,
    "receipts_reused": 12,
    "fresh_receipts_required": 4,
    "compile_units": 30,
    "fresh_capture_units": 40,
    "reuse_reduction_units": 35,
    "user_visible_message_ja": "既存の有効な公的receiptを再利用できるため、新規取得より安く実行できます。"
  }
}
```

### 5.3 Pricing rule

Price should be composed from:

```text
compile units
+ fresh source units
+ proof/binder units
+ batch coordination units
- reuse dividend units
```

But never show negative pricing. The minimum paid unit for a useful paid artifact remains the smallest configured tier, unless the product is free.

### 5.4 Why this is smarter

It creates compounding value:

- one customer's team gets cheaper future outputs
- repeat tasks become faster
- portfolio batches become cheaper
- watch products become more credible

### 5.5 Merge into execution plan

Add to pricing policy:

```json
{
  "reuse_policy": {
    "public_receipt_reuse_allowed": true,
    "private_overlay_reuse_allowed": "tenant_policy_only",
    "reuse_dividend_visible": true,
    "minimum_paid_tier_applies": true
  }
}
```

Add to `billing_metadata`:

```json
{
  "receipt_reuse": {
    "reused_receipt_count": 0,
    "fresh_receipt_count": 0,
    "reuse_reduction_units": 0
  }
}
```

### 5.6 Conflict check

Potential conflict:

- If reused public receipts came from AWS, zero-bill teardown must still delete AWS resources.

Resolution:

- Reusable receipts must live in the exported non-AWS asset bundle after teardown.
- The runtime must never reference S3 or AWS URLs.

## 6. Adopted smart method D: Safe Autopay Envelope

### 6.1 Problem

Repeated 99円/330円 approvals are too much friction.

But full auto-buy conflicts with user approval, cap safety, and agent trust.

### 6.2 Adopt

Upgrade `buyer_policy_profile` into `safe_autopay_envelope`.

This is not unlimited auto-buy. It is a pre-approved envelope with explicit scope.

Example:

```json
{
  "safe_autopay_envelope": {
    "enabled": true,
    "max_single_purchase_jpy_inc_tax": 330,
    "max_daily_jpy_inc_tax": 990,
    "max_monthly_jpy_inc_tax": 3300,
    "allowed_outcome_contract_ids": [
      "vendor_public_baseline_v1",
      "invoice_vendor_check_v1"
    ],
    "forbidden_contract_ids": [
      "counterparty_public_dd_full_v1",
      "csv_monthly_public_review_v1"
    ],
    "requires_fresh_user_confirmation_when": [
      "csv_overlay_involved",
      "professional_handoff_binder",
      "price_above_single_cap",
      "new_contract_family"
    ],
    "expires_at": "2026-06-15T00:00:00Z"
  }
}
```

### 6.3 Why this is smarter

It enables an AI agent to handle low-risk repeat purchases without nagging the user every time.

It also keeps the product safe because:

- the envelope is narrow
- it expires
- it has per-day and per-month caps
- higher-risk products still require approval

### 6.4 Merge into execution plan

Add to paid execution requirements:

```text
paid execution requires either:
  A. explicit user_approved_cap_token for this preview, or
  B. safe_autopay_envelope covering this exact outcome contract, tier, and cap
```

### 6.5 Conflict check

Potential conflict:

- Existing plan says paid execution needs approval token.

Resolution:

- `safe_autopay_envelope` is the approval token envelope. It must produce a derived `cap_token` for each execution.

Release blocker:

- Any paid execution without either explicit approval or envelope-derived cap token.

## 7. Adopted smart method E: Watch Statement Product

### 7.1 Problem

`watch_delta_product` is correct, but it can be hard to monetize if there is "no change."

Charging only when something changes creates unstable revenue.

Charging a subscription without an artifact creates trust and billing risk.

### 7.2 Adopt

Use `watch_statement_packet`.

Each watch period generates a scoped artifact:

```json
{
  "packet_type": "watch_statement_packet",
  "watch_id": "watch_...",
  "period": "2026-06",
  "scope_checked": [
    "invoice_registry",
    "corporate_number",
    "selected_administrative_disposition_sources"
  ],
  "changed_items": [],
  "unchanged_observations": [
    {
      "source_family": "invoice_registry",
      "support_state": "observed_no_material_change_within_scope",
      "no_hit_boundary": "no_hit_not_absence"
    }
  ],
  "new_known_gaps": [],
  "followup_buy_recommendation": null
}
```

### 7.3 Pricing rule

For watch products, the paid artifact is not "nothing changed."

The paid artifact is:

```text
scoped refresh statement + delta/gap summary + receipt updates
```

Charge only when the statement is accepted and contains the contracted scope, even if there is no material change.

### 7.4 Why this is smarter

This gives recurring revenue without pretending to prove absence.

The agent can say:

```text
今月の契約範囲では大きな変更は観測されていません。ただし不存在や安全の証明ではありません。
```

### 7.5 Merge into execution plan

Add P1 product:

```text
watch_statement_packet
  - vendor_watch_statement
  - grant_watch_statement
  - regulation_watch_statement
  - procurement_watch_statement
  - tax_labor_watch_statement
```

### 7.6 Conflict check

Potential conflict:

- no-hit must not become proof of absence.

Resolution:

- Use `observed_no_material_change_within_scope`, never "no change exists."
- Always include `scope_checked`, `known_gaps`, and no-hit boundary.

## 8. Adopted smart method F: One-Shot to Watch Conversion

### 8.1 Problem

One-shot packets create revenue but do not automatically create recurring behavior.

### 8.2 Adopt

Every eligible one-shot paid output should include `watch_conversion_offer`.

Example:

```json
{
  "watch_conversion_offer": {
    "eligible": true,
    "recommended_watch_contract_id": "vendor_watch_statement_v1",
    "why": "この取引先確認はインボイス登録、法人情報、行政処分sourceの変化監視に向いています。",
    "monthly_cap_jpy_inc_tax": 330,
    "first_watch_period_uses_existing_receipts": true,
    "requires_user_approval": true
  }
}
```

### 8.3 Why this is smarter

It turns the highest-frequency one-shot use cases into recurring revenue without forcing a subscription at signup.

### 8.4 Conflict check

No conflict if:

- it is opt-in
- it has a monthly cap
- it produces accepted watch statement artifacts
- it does not require AWS runtime after teardown

## 9. Adopted smart method G: Portfolio Sampling Ladder

### 9.1 Problem

`portfolio_batch_packet` is valuable, but batch runs can be too large or too expensive if the first quote is wrong.

### 9.2 Adopt

Add `portfolio_sampling_ladder`:

```text
free schema/intake preview
-> sample 10 subjects
-> coverage and unit estimate
-> full capped batch
-> watchlist seed
```

Example:

```json
{
  "portfolio_sampling_ladder": {
    "sample_packet": "vendor_portfolio_sample_public_check",
    "sample_subject_count": 10,
    "sample_cap_jpy_inc_tax": 990,
    "full_batch_estimate": {
      "subject_count": 250,
      "expected_cap_jpy_inc_tax": 9900,
      "expected_reuse_rate": 0.42
    },
    "batch_go_no_go": "recommend_full_batch",
    "reason": "Sample produced accepted artifacts for 9/10 subjects and source coverage was sufficient."
  }
}
```

### 9.3 Why this is smarter

It lowers the risk of large batch purchases and gives AI agents a natural path:

```text
まず990円上限のsampleで確認して、結果が良ければ9,900円上限の全件へ進めます。
```

### 9.4 Conflict check

Must not upload raw CSV to AWS.

For CSV-derived portfolios:

- client or tenant runtime extracts safe identifiers
- raw rows are not stored
- small group suppression applies to summaries
- no public proof page contains private batch details

## 10. Adopted smart method H: Workflow Kits

### 10.1 Problem

Bundles can become pricing complexity if they are discounts. But users and agents think in workflows.

### 10.2 Adopt

Add `workflow_kit` as a recipe with a cap, not a discount plan.

Examples:

| Workflow kit | Included outcome contracts | Initial cap role |
|---|---|---|
| `vendor_onboarding_kit` | baseline, invoice check, selected public DD, watch offer | 990-3,300 JPY |
| `grant_sprint_kit` | candidate shortlist, readiness checklist, deadline watch | 3,300-9,900 JPY |
| `permit_startup_kit` | permit scope checklist, local source gaps, action queue | 3,300 JPY |
| `monthly_accounting_public_review_kit` | CSV-derived facts, invoice/vendor checks, tax/labor event radar | capped dynamic |
| `regulation_monitoring_kit` | change watch, impact packet, action queue | monthly cap |

### 10.3 JSON shape

```json
{
  "workflow_kit_id": "vendor_onboarding_kit_v1",
  "steps": [
    {
      "step_id": "baseline",
      "outcome_contract_id": "vendor_public_baseline_v1",
      "required": true
    },
    {
      "step_id": "public_dd_lite",
      "outcome_contract_id": "counterparty_public_dd_lite_v1",
      "required": false,
      "trigger": "user_requires_enforcement_or_license_coverage"
    },
    {
      "step_id": "watch",
      "outcome_contract_id": "vendor_watch_statement_v1",
      "required": false,
      "trigger": "user_wants_monitoring"
    }
  ],
  "cap_policy": {
    "requires_stepwise_approval": true,
    "max_total_jpy_inc_tax": 3300
  }
}
```

### 10.4 Why this is smarter

It packages repeatable business workflows without introducing "unlimited" or opaque subscriptions.

### 10.5 Conflict check

No conflict if:

- each step remains separately capped
- the kit is a recipe, not a bundled legal/accounting opinion
- over-scope steps require re-preview

## 11. Adopted smart method I: Proof Depth Buy-Up

### 11.1 Problem

Some users only need an AI-readable summary. Others need a professional handoff binder.

Charging only by packet type misses this value.

### 11.2 Adopt

Add `proof_depth` as a buy-up dimension:

| Proof depth | Use | Output |
|---|---|---|
| `summary` | AI conversation | concise claims, receipt ids, known gaps |
| `standard` | normal business use | source receipts, claim refs, gap matrix |
| `handoff_binder` | accountant/lawyer/internal review | structured appendix, action queue, downloadable evidence binder |

### 11.3 Example

```json
{
  "proof_depth_options": [
    {
      "depth": "summary",
      "price_role": "cheapest",
      "best_for": "AI agent can answer the user with citations"
    },
    {
      "depth": "standard",
      "price_role": "default",
      "best_for": "end user wants a saved packet"
    },
    {
      "depth": "handoff_binder",
      "price_role": "premium",
      "best_for": "handoff to professional review",
      "professional_fence": "not a final legal/accounting/tax opinion"
    }
  ]
}
```

### 11.4 Why this is smarter

It monetizes professional workflows without pretending to replace professionals.

### 11.5 Conflict check

Potential conflict:

- paid proof binder could leak raw source artifacts or private CSV.

Resolution:

- binder is compiled from public-safe receipts and tenant-safe derived facts only
- raw screenshots/DOM/HAR/OCR full text are not exposed unless policy allows
- public proof pages show only samples, not customer binders

## 12. Adopted smart method J: Agent Budget Wallet

### 12.1 Problem

Low-priced packets are hard to monetize through repeated card checkout.

### 12.2 Adopt

Use an `agent_budget_wallet` or monthly aggregated invoice for low-value repeated executions.

This is a payment rail, not a new price source.

```json
{
  "agent_budget_wallet": {
    "wallet_id": "wallet_...",
    "currency": "JPY",
    "available_cap_jpy_inc_tax": 3300,
    "per_execution_cap_jpy_inc_tax": 330,
    "allowed_agents": ["chatgpt", "claude", "codex", "custom_mcp_client"],
    "allowed_contract_families": ["vendor_check", "invoice_check"],
    "requires_receipt": true,
    "monthly_statement_required": true
  }
}
```

### 12.3 Why this is smarter

It supports:

- many small purchases
- agent-driven repeated checks
- monthly reconciliation
- hard caps
- lower checkout friction

### 12.4 Conflict check

No conflict if:

- actual usage still records units
- all paid calls produce accepted artifacts or no-charge reasons
- wallet balance/cap cannot be exceeded
- no hidden auto-renewal is implied

## 13. Adopted smart method K: Agent Objection Handler

### 13.1 Problem

AI agents need to explain not just why to buy, but also why common objections are handled.

### 13.2 Adopt

Add `agent_objection_handler` to preview and proof pages.

Example:

```json
{
  "agent_objection_handler": [
    {
      "objection": "AIで無料で調べられないの?",
      "answer_ja": "無料のAI回答では取得日時、source receipt、known gapsが弱くなりやすいです。jpciteは公的sourceの証跡付きpacketを返します。"
    },
    {
      "objection": "もっと安くできない?",
      "answer_ja": "この目的なら330円上限のbaselineが最安です。990円のDD packetは行政処分や許認可coverageが必要な場合だけ推奨します。"
    },
    {
      "objection": "これで安全と判断できる?",
      "answer_ja": "安全や信用の最終判断はできません。公的一次情報で観測できる範囲と不足を返します。"
    }
  ]
}
```

### 13.3 Why this is smarter

GEO-first growth depends on AI agents being able to sell accurately. This gives them safe conversion copy without hallucinated promises.

### 13.4 Conflict check

No conflict. Copy must be generated from approved copy blocks and policy gates.

## 14. Adopted smart method L: Contract Renewal Logic

### 14.1 Problem

Freshness buy-up and watch products need clear renewal semantics.

### 14.2 Adopt

Add `contract_renewal_logic`:

```json
{
  "renewal_logic": {
    "renewable": true,
    "default_renewal": "none",
    "renewal_types": [
      {
        "type": "refresh_same_scope",
        "trigger": "receipt_age_exceeds_policy",
        "requires_new_preview": true
      },
      {
        "type": "watch_statement",
        "trigger": "monthly_period",
        "requires_monthly_cap": true
      },
      {
        "type": "delta_followup",
        "trigger": "material_delta_detected",
        "requires_user_approval_unless_envelope_covers"
      }
    ]
  }
}
```

### 14.3 Why this is smarter

It converts one-time outputs into durable product relationships without forcing blanket subscriptions.

### 14.4 Conflict check

No conflict if renewal is opt-in and cap-bound.

## 15. Adopted smart method M: Product Telemetry Without Raw Prompts

### 15.1 Problem

To optimize packaging, jpcite needs to know what users and agents try to buy.

But raw prompts, raw CSV, and private business facts must not be logged.

### 15.2 Adopt

Add `product_packaging_telemetry`:

```json
{
  "event_type": "preview_decision",
  "task_family": "vendor_check",
  "recommended_contract_id": "vendor_public_baseline_v1",
  "recommended_action": "buy_packet",
  "cheapest_sufficient_tier": "starter_330",
  "higher_tier_rejected": true,
  "purchase_result": "approved | skipped | blocked | expired",
  "skip_reason_code": "too_expensive | missing_input | outside_scope | user_declined",
  "jurisdiction_bucket": "prefecture_level",
  "raw_prompt_stored": false,
  "raw_csv_stored": false
}
```

### 15.3 Why this is smarter

Future AWS/source expansion and product work can be demand-weighted:

- gaps that block purchases
- tiers users accept
- products agents recommend but users skip
- workflows that convert to watch products

### 15.4 Conflict check

No conflict if telemetry is aggregated and redacted.

Release blocker:

- any raw prompt, raw CSV, row-level private content, or customer-specific sensitive fact in public/product telemetry.

## 16. Adopted smart method N: Accepted Artifact Pricing

### 16.1 Problem

Users do not want to pay for failed lookups, invalid inputs, or blocked sources.

### 16.2 Adopt

Make the billing rule explicit:

```text
Charge for accepted artifacts, not attempts.
```

Accepted artifacts include:

- paid packet with supported claims and known gaps
- explicit no-hit receipt when the user specifically bought no-hit receipt
- watch statement packet with contracted scope checked
- portfolio sample packet with per-subject accepted artifacts
- handoff binder compiled from accepted packet artifacts

No-charge outcomes include:

- invalid input
- identity unresolved before paid work
- source blocked by policy before paid work
- cap exceeded before work
- no-hit-only without explicit no-hit receipt purchase
- policy firewall rejection

### 16.3 Merge into execution plan

Add catalog field:

```json
{
  "billing_acceptance_policy": {
    "bill_only_accepted_artifacts": true,
    "accepted_artifact_types": [],
    "no_charge_reason_codes": []
  }
}
```

### 16.4 Conflict check

No conflict. This strengthens trust and reduces disputes.

## 17. Product packaging matrix

### 17.1 P0 one-shot products

| Outcome contract | Underlying packet | Default cap | Product role | Adopt |
|---|---|---:|---|---|
| `vendor_public_baseline_v1` | `company_public_baseline` | 330 JPY | first paid purchase | yes |
| `invoice_vendor_check_v1` | `invoice_vendor_public_check` | 330 JPY | high-frequency accounting check | yes |
| `evidence_answer_scoped_v1` | `evidence_answer` | 990 JPY | fallback for broad factual requests | yes |
| `source_receipt_ledger_v1` | `source_receipt_ledger` | 33-330 JPY | agent/developer/audit support | yes |

### 17.2 P1 workflow products

| Outcome contract | Underlying packets | Default cap | Product role | Adopt |
|---|---|---:|---|---|
| `counterparty_public_dd_lite_v1` | baseline + public DD sources | 990 JPY | vendor onboarding | yes |
| `grant_candidate_shortlist_v1` | grant shortlist | 3,300 JPY | SMB/士業 workflow | yes |
| `permit_scope_checklist_v1` | permit checklist | 3,300 JPY | regulated business setup | yes |
| `regulation_change_impact_v1` | change impact | 990-3,300 JPY | recurring watch path | yes |

### 17.3 P1/P2 recurring products

| Outcome contract | Artifact | Cap style | Product role | Adopt |
|---|---|---|---|---|
| `vendor_watch_statement_v1` | monthly scoped watch statement | monthly cap | recurring vendor monitoring | yes |
| `grant_watch_statement_v1` | program/due date delta statement | monthly cap | recurring opportunity discovery | yes |
| `regulation_watch_statement_v1` | legal/regulatory delta statement | monthly cap | recurring compliance workflow | yes |
| `tax_labor_watch_statement_v1` | tax/labor event statement | monthly cap | accounting/HR workflow | yes |

### 17.4 Batch and portfolio products

| Outcome contract | Artifact | Cap style | Product role | Adopt |
|---|---|---|---|---|
| `vendor_portfolio_sample_v1` | 10-subject sample packet | sample cap | de-risk large batch | yes |
| `vendor_portfolio_batch_v1` | per-subject accepted artifacts | batch cap | larger orders | yes |
| `invoice_vendor_batch_v1` | invoice/vendor checks | batch cap | accounting/BPO | yes |
| `portfolio_watch_seed_v1` | watchlist seed | cap + watch offer | recurring conversion | yes |

## 18. Explicit non-adoptions

These are rejected for P0/P1 because they create trust, billing, compliance, or operational risk.

| Idea | Decision | Reason |
|---|---|---|
| Unlimited subscription | reject | conflicts with cap safety and unknown source cost |
| Seat-first SaaS pricing | reject for launch | buyer is often an AI agent/task, not a human seat |
| Hidden monthly minimum | reject | weakens agent trust and "cheap output" concept |
| Automatic purchase without cap envelope | reject | violates approval/cap model |
| Legal/accounting/tax final opinion bundle | reject | outside professional fence |
| Creditworthiness/safety guarantee package | reject | unsupported and risky |
| Raw CSV storage premium plan | reject | conflicts with privacy concept |
| Public raw screenshot archive | reject | terms/privacy/leakage risk |
| High-value proof page full output | reject | cannibalizes paid output |
| Discounts disconnected from 3 JPY/unit | reject | creates pricing drift |
| Permanent AWS-backed watch runtime | reject | conflicts with zero-bill teardown |
| Generic trust score | reject | overclaims; use typed public evidence attention only |

## 19. Merge diff for the master execution plan

This section is the exact content that should be merged into the master execution plan by the main coordinator. This document itself does not edit the master plan because the requested output is this file only.

### 19.1 Add to product smart methods

Add after the Round2 product economics section:

```text
Round3 product packaging addendum:

Adopt outcome-contract based packaging above packet execution.
The packet catalog remains the execution layer; outcome_contract_catalog becomes the buyer/agent layer.

Required additions:
- outcome_contract_catalog
- coverage_roi_curve
- receipt_reuse_dividend
- safe_autopay_envelope
- watch_statement_packet
- one_shot_to_watch_conversion
- portfolio_sampling_ladder
- workflow_kit
- proof_depth_buyup
- agent_budget_wallet
- agent_objection_handler
- contract_renewal_logic
- product_packaging_telemetry
- accepted_artifact_pricing

The product promise becomes:
For each user task, jpcite recommends the cheapest sufficient source-backed outcome contract,
shows what higher tiers add, requires a cap/envelope, charges only accepted artifacts,
and offers watch/renewal only when scoped artifacts can be produced.
```

### 19.2 Add P0 implementation work items

```text
P0-PACK-00 outcome_contract_catalog
P0-PACK-01 outcome_contract -> packet mapping compiler
P0-PACK-02 agent_purchase_decision v2 schema
P0-PACK-03 coverage_roi_curve and anti_upsell_gate
P0-PACK-04 accepted_artifact_pricing policy
P0-PACK-05 receipt_reuse_dividend in pricing metadata
P0-PACK-06 safe_autopay_envelope and derived cap token
P0-PACK-07 product copy block and objection handler compiler
P0-PACK-08 pricing/catalog/proof/MCP/OpenAPI drift tests
```

### 19.3 Add P1 implementation work items

```text
P1-PACK-01 watch_statement_packet
P1-PACK-02 one_shot_to_watch_conversion_offer
P1-PACK-03 workflow_kit recipes
P1-PACK-04 portfolio_sampling_ladder
P1-PACK-05 proof_depth_buyup and handoff binder
P1-PACK-06 agent_budget_wallet / monthly aggregated invoice support
P1-PACK-07 product_packaging_telemetry aggregation
```

### 19.4 Update AWS artifact jobs

Existing pricing jobs J90-J97 remain useful, but should be expanded:

| Job | Change |
|---|---|
| J90 Pricing matrix compiler | rename or extend to `Outcome Contract and Pricing Matrix Compiler` |
| J91 Cost preview fixture factory | include `agent_purchase_decision_v2`, `coverage_roi_curve`, `anti_upsell_gate` |
| J92 Billing reconciliation simulator | include accepted artifact/no-charge scenarios |
| J93 Agent recommendation corpus | include objection handling, no-buy, cheapest sufficient route |
| J94 Pricing drift test data | include outcome contract catalog and proof depth |
| J96 Bundle/cap policy generator | shift from discounts to workflow kits and cap envelopes |
| J97 Revenue scenario workbook | include one-shot to watch conversion and reuse dividend |

Add new jobs:

| Job | Name | Output |
|---|---|---|
| J98 | Outcome contract fixture generator | outcome contract examples for every P0/P1 task family |
| J99 | Coverage ROI curve simulator | marginal coverage/price curves and anti-upsell examples |
| J100 | Receipt reuse pricing simulator | reuse dividend fixtures and billing metadata examples |
| J101 | Watch statement economics simulator | watch statement examples, no-change scope examples, renewal quotes |
| J102 | Portfolio sampling simulator | sample-to-full-batch go/no-go fixtures |
| J103 | Agent budget wallet scenario generator | cap envelope, declined, expired, over-cap, monthly statement examples |
| J104 | Objection handling corpus generator | approved Japanese agent sales and skip explanations |

### 19.5 Update release gates

Add release blockers:

```text
- preview recommends highest tier without cheaper sufficient alternative check
- outcome contract implies legal/accounting/tax/credit/safety final judgment
- paid execution lacks explicit cap token or safe_autopay_envelope-derived cap token
- product page price differs from catalog/MCP/OpenAPI
- proof page exposes full paid output or private data
- watch statement says "no change exists" instead of scoped observation
- subscription/recurring copy implies unlimited or uncapped usage
- receipt reuse pricing references AWS/S3 after teardown
- product telemetry stores raw prompt, raw CSV, or private row-level facts
```

## 20. Contradiction review

### C-01: Subscription revenue vs cap safety

Issue:

Recurring revenue can drift into unlimited or vague subscriptions.

Resolution:

Use watch statement artifacts and monthly cap envelopes. Do not sell unlimited access.

Status: resolved if implemented as `watch_statement_packet`.

### C-02: Cheap output concept vs higher-tier bundles

Issue:

Bundles could push users to overbuy.

Resolution:

Use `coverage_roi_curve` and `anti_upsell_gate`. Higher tiers must explain exact incremental coverage.

Status: resolved.

### C-03: Accepted artifact pricing vs no-change watches

Issue:

No-change watch periods may look like charging for nothing.

Resolution:

The artifact is a scoped watch statement with receipts, gaps, and period coverage. It must not claim absence.

Status: resolved with careful language.

### C-04: Receipt reuse discounts vs canonical 3 JPY/unit

Issue:

Reuse dividend could become a second pricing system.

Resolution:

Reuse dividend changes unit count, not unit price. Unit price remains 3 JPY ex-tax.

Status: resolved.

### C-05: Safe autopay vs required user approval

Issue:

Autopay could bypass user approval.

Resolution:

The envelope is the approval. Each execution still gets a derived cap token and must fit exact scope.

Status: resolved.

### C-06: Portfolio batch vs CSV privacy

Issue:

Batch products may tempt raw CSV upload/storage.

Resolution:

Real CSV remains tenant/client-side. Only safe identifiers and aggregates can enter packet execution. AWS credit run uses synthetic/header-only/redacted fixtures only.

Status: resolved.

### C-07: Proof depth buy-up vs public proof leakage

Issue:

Premium proof binders can leak too much if reused as public examples.

Resolution:

Public proof pages use synthetic or public-safe samples. Customer binders are never public proof pages.

Status: resolved.

### C-08: Agent objection handling vs unsafe marketing

Issue:

Agent sales copy may overpromise.

Resolution:

Generate objection answers from approved copy blocks and Policy Decision Firewall.

Status: resolved.

### C-09: Watch products vs zero-AWS teardown

Issue:

Watch products could depend on AWS running.

Resolution:

AWS credit run builds baseline assets and fixtures. Production watch must run from exported assets and normal non-AWS runtime, or a future explicitly approved runtime. No permanent AWS runtime.

Status: resolved.

### C-10: Product telemetry vs privacy

Issue:

Demand telemetry can become raw prompt logging.

Resolution:

Only record task family, contract id, price tier, decision codes, broad jurisdiction buckets, and aggregate conversion. No raw prompts or raw CSV.

Status: resolved.

## 21. Required schema additions

### 21.1 `outcome_contract`

```json
{
  "outcome_contract_id": "string",
  "version": "string",
  "task_family": "string",
  "display_name_ja": "string",
  "primary_packet_type": "string",
  "allowed_claim_families": ["string"],
  "excluded_claims": ["string"],
  "source_family_requirements": ["string"],
  "default_price_tier": "string",
  "hard_cap_jpy_inc_tax": 0,
  "freshness_policy": {},
  "proof_depth_options": [],
  "renewal_options": [],
  "safe_autopay_eligible": false,
  "watch_eligible": false,
  "portfolio_eligible": false,
  "professional_fence": "string"
}
```

### 21.2 `agent_purchase_decision_v2`

```json
{
  "preview_type": "agent_purchase_decision_v2",
  "recommended_action": "buy | ask_followup | skip | use_free_guidance",
  "recommended_outcome_contract_id": "string",
  "recommended_packet_type": "string",
  "cheapest_sufficient": true,
  "coverage_roi_curve": [],
  "anti_upsell_gate": {},
  "price_quote": {},
  "cap_requirement": {},
  "approval_path": {},
  "safe_autopay_applicability": {},
  "receipt_reuse_quote": {},
  "watch_conversion_offer": {},
  "agent_recommendation_card": {},
  "agent_objection_handler": []
}
```

### 21.3 `billing_metadata` extension

```json
{
  "pricing_version": "string",
  "outcome_contract_id": "string",
  "unit_price_jpy_ex_tax": 3,
  "billable_units": 0,
  "jpy_inc_tax": 0,
  "cap_jpy_inc_tax": 0,
  "accepted_artifact": true,
  "no_charge_reason": null,
  "receipt_reuse": {},
  "proof_depth": "summary | standard | handoff_binder",
  "watch_statement_period": null
}
```

## 22. Launch recommendation

### 22.1 RC1 product surface

RC1 should expose:

- free `agent_task_intake`
- free `agent_purchase_decision_v2`
- free `coverage_roi_curve`
- `vendor_public_baseline_v1`
- `invoice_vendor_check_v1` behind feature flag if not fully ready
- `source_receipt_ledger_v1`
- `evidence_answer_scoped_v1`
- explicit no-charge reason codes
- hard cap and approval token
- product/pricing/proof drift tests

### 22.2 RC1.1 product surface

Add:

- `safe_autopay_envelope`
- `agent_budget_wallet` or monthly aggregated invoice path
- `receipt_reuse_dividend`
- `one_shot_to_watch_conversion_offer`

### 22.3 RC2 product surface

Add:

- `watch_statement_packet`
- `portfolio_sampling_ladder`
- `workflow_kit`
- `proof_depth_buyup`

### 22.4 RC3 product surface

Add:

- broader vertical workflow kits
- organization policy profiles
- multi-agent wallet controls
- portfolio batch and watchlist products

## 23. Final adoption list

Adopt into master plan:

1. `Outcome Contract Catalog`
2. `Coverage ROI Curve`
3. `Receipt Reuse Dividend`
4. `Safe Autopay Envelope`
5. `Watch Statement Product`
6. `One-Shot to Watch Conversion`
7. `Portfolio Sampling Ladder`
8. `Workflow Kits`
9. `Proof Depth Buy-Up`
10. `Agent Budget Wallet`
11. `Agent Objection Handler`
12. `Contract Renewal Logic`
13. `Product Packaging Telemetry`
14. `Accepted Artifact Pricing`

Reject:

1. Unlimited plans
2. Seat-first launch pricing
3. Hidden minimums
4. Auto-buy without cap envelope
5. Professional final-judgment products
6. Raw CSV storage plans
7. Full paid output on proof pages
8. Permanent AWS-backed recurring runtime
9. Generic trust/credit/safety scores
10. Discounts that bypass the canonical unit meter

## 24. Final conclusion

The smarter product strategy is:

> jpcite should not sell packets as isolated API calls. It should sell capped outcome contracts that AI agents can recommend, compare, approve, renew, and monitor.

The key improvement is not another source family or another packet name. It is the economic control layer around the packet:

```text
agent task
-> outcome contract
-> cheapest sufficient route
-> coverage ROI curve
-> cap or safe autopay envelope
-> accepted artifact
-> receipt reuse dividend
-> watch statement or workflow kit
```

This keeps the original concept intact:

- end users get cheap source-backed outputs
- AI agents can recommend with confidence
- jpcite avoids hallucinated final judgments
- pricing remains capped and explainable
- recurring revenue appears through scoped artifacts, not vague subscriptions
- production can still be AWS-independent after the credit run

This review is therefore a **PASS with required merge additions**.
