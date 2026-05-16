# Smart methods round 2 - 01 product / agent economics

Date: 2026-05-15  
Status: product economics review only, no AWS execution  
Inputs:

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- `docs/_internal/aws_final_12_review_integrated_smart_methods_2026-05-15.md`

Scope:

- Review whether there are smarter product functions, AI-agent recommendation functions, pricing mechanisms, purchase-friction reducers, or repeat-usage mechanisms beyond the current smart-method plan.
- Do not restate `Budget Token Market v2`, `Output Composer`, `agent_purchase_decision`, `Source Operating System`, or `Pointer Rollback` unless needed to show how a new function attaches to them.
- Do not propose AWS commands, API calls, or resource creation.

## 0. Verdict

The current master plan is coherent, but it is still too "packet endpoint" centric in the economic layer.

The next smarter step is to make jpcite not only an agent-first packet compiler, but an agent-first outcome purchasing system:

```text
end-user task
-> agent task intake
-> cheapest sufficient outcome path
-> free decision object
-> capped approval
-> proof-carrying output
-> reusable receipt wallet
-> delta/watch/rebuy loop
```

This is not a new execution order. It is a product layer that makes each packet easier to recommend, easier to approve, and more likely to be used repeatedly.

## 1. What is already good enough

The following current ideas should remain the foundation:

- Free preview should answer whether to buy, not only what it costs.
- Paid outputs must have source receipts, claim refs, known gaps, no-hit caveats, and billing metadata.
- AI agents need a compact `agent_recommendation_card`.
- Proof pages should be `agent_decision_page`s, not full free replicas of paid output.
- `agent_routing_decision` should remain free.
- Payment should use capped approvals and idempotency.
- Public claims must come from the packet compiler, not free-form LLM output.

Round 2 does not replace these. It adds the missing economics layer around them.

## 2. Main gap found

The current plan lets an AI agent say:

```text
This packet is worth buying.
```

But a stronger product should let the AI agent say:

```text
For this user's actual task, this is the cheapest sufficient path.
It costs no more than this cap.
Buying a higher tier would add these specific claims.
Skipping is acceptable if these gaps do not matter.
If the user repeats this monthly, a watch/reuse flow is cheaper.
```

That moves the product from "packet purchase" to "task outcome purchase."

## 3. Adopted smart method A - Agent Task Intake

### Problem

Users rarely ask for packet names. They ask for jobs:

- "この取引先、大丈夫か確認して"
- "この会社が使える補助金を探して"
- "この事業に許認可が必要か見て"
- "今月の会計CSVから注意点を出して"
- "法改正で影響がありそうなものを見て"

If the AI agent must map these tasks to packets manually, recommendation quality varies.

### Adopt

Add `agent_task_intake` as a free control surface.

It should normalize the user's requested job into:

```json
{
  "task_type": "vendor_check | grant_search | permit_check | regulation_monitor | monthly_csv_review | procurement_search | tax_labor_review",
  "user_goal": "...",
  "known_inputs": [],
  "missing_inputs": [],
  "risk_sensitivity": "low | normal | high",
  "urgency": "now | soon | monitoring",
  "likely_packet_paths": [],
  "do_not_buy_yet_reason": null
}
```

This can sit before `agent_purchase_decision`.

### Why smarter

It reduces the agent's work from "choose a product from a catalog" to "submit a task and get a purchase path."

### Conflict check

No conflict with existing plan. It is a control function and does not create factual claims.

## 4. Adopted smart method B - Outcome Ladder

### Problem

The plan has packets, but not enough laddering.

For the same user task, there should be a clear progression:

```text
free route
-> cheapest baseline
-> focused packet
-> workflow bundle
-> watch / delta repeat
```

### Adopt

Create `outcome_ladder` for each task family.

Example for vendor check:

| Ladder step | Product | Price role | Agent message |
|---|---|---|---|
| Free | route + cost preview | trust building | "I can check what public sources would be used." |
| Low | `company_public_baseline` | first purchase | "This answers identity and public registration basics." |
| Medium | `invoice_vendor_public_check` | accounting workflow | "This adds invoice/vendor public checks." |
| High | `counterparty_public_dd_packet` | risk workflow | "This adds enforcement, licenses, public notices, and gaps." |
| Repeat | `vendor_watch_delta` | recurring | "Monitor changes and only charge for meaningful deltas." |

Example for grants:

| Ladder step | Product | Price role | Agent message |
|---|---|---|---|
| Free | route + needed facts | reduce friction | "A few facts are needed before paid search." |
| Low | `grant_candidate_shortlist_packet` | first purchase | "Find likely public program candidates." |
| Medium | `application_readiness_checklist_packet` | action output | "Turn candidates into application preparation tasks." |
| High | `grant_pursuit_workflow_recipe` | workflow | "Track deadlines, gaps, documents, and rechecks." |
| Repeat | `grant_watch_delta` | recurring | "Alert only when new or changed programs match." |

### Why smarter

AI agents can explain "start cheap" instead of pushing a large packet immediately. This lowers first-purchase friction and creates upgrade paths.

### Conflict check

No conflict. It extends `cheapest_sufficient_packet_selector`.

## 5. Adopted smart method C - Coverage Ladder Quote

### Problem

Free preview currently says price, known gaps, and whether to buy. It should also show exactly what more money unlocks.

### Adopt

Add `coverage_ladder_quote` to preview:

```json
{
  "task": "vendor_check",
  "recommended_tier": "baseline",
  "tiers": [
    {
      "tier": "free",
      "claims_unlocked": ["available sources", "estimated price", "missing inputs"],
      "claims_not_unlocked": ["registry status", "invoice status", "enforcement signals"]
    },
    {
      "tier": "baseline",
      "claims_unlocked": ["corporate identity", "invoice registration", "source receipt ledger"],
      "claims_not_unlocked": ["industry license", "administrative disposition sweep"]
    },
    {
      "tier": "dd",
      "claims_unlocked": ["license/public enforcement/procurement/public notice coverage"],
      "claims_not_unlocked": ["private creditworthiness", "legal opinion"]
    }
  ]
}
```

### Why smarter

It turns pricing into a coverage decision, not a blind purchase. This is especially useful for AI agents because they can justify a low-cost or higher-cost choice in plain language.

### Conflict check

No conflict. Must not reveal full paid results in preview.

## 6. Adopted smart method D - Freshness Buy-Up

### Problem

Some tasks can use cached official-source receipts. Others need a fresh recheck.

If the only mode is "fresh everything," cost and latency rise. If the only mode is cached, trust drops.

### Adopt

Add `freshness_buyup`:

```json
{
  "freshness_options": [
    {
      "mode": "reuse_existing_receipts",
      "max_age": "30d",
      "price_multiplier": "lowest",
      "best_for": "screening"
    },
    {
      "mode": "refresh_high_value_sources",
      "sources": ["invoice", "corporate_number", "selected_enforcement"],
      "price_multiplier": "medium",
      "best_for": "near-term vendor decision"
    },
    {
      "mode": "full_refresh",
      "price_multiplier": "highest",
      "best_for": "high-sensitivity decision"
    }
  ]
}
```

### Why smarter

The user can buy the right freshness level. This lowers first-purchase price while preserving a premium path for high-stakes tasks.

### Conflict check

Compatible with Receipt Wallet and known gaps. The output must clearly show receipt timestamps and stale coverage.

## 7. Adopted smart method E - Buyer Policy Profile

### Problem

Every purchase requiring a fresh approval creates friction. But full auto-buy is risky and conflicts with capped approval.

### Adopt

Add a minimal `buyer_policy_profile` that an AI agent can use to decide when to ask for approval:

```json
{
  "max_single_purchase": 500,
  "max_daily_purchase": 2000,
  "allowed_task_types": ["company_public_baseline", "invoice_vendor_public_check"],
  "require_confirmation_above": 300,
  "prefer_reuse_receipts": true,
  "freshness_preference": "reuse_or_selective_refresh",
  "forbidden_outputs": ["legal_opinion", "credit_score"]
}
```

This profile should store only purchase preferences and caps. It should not store raw CSV, sensitive business facts, or private prompts.

### Why smarter

It supports low-friction repeat buying without removing user control.

### Conflict check

Potential conflict: "user approval triggers capped paid execution."

Resolution: pre-approved policy is the approval envelope. Anything outside it still requires explicit approval.

## 8. Adopted smart method F - Preview State Resume

### Problem

AI-agent conversations are interrupted. Users may inspect preview and return later. If the preview cannot be resumed, purchase conversion drops.

### Adopt

Add `preview_state_id`:

```json
{
  "preview_state_id": "ps_...",
  "expires_at": "2026-05-22T00:00:00Z",
  "frozen_price_cap": true,
  "frozen_source_plan": true,
  "missing_inputs": [],
  "resume_actions": ["approve", "ask_follow_up", "compare_tiers"]
}
```

### Why smarter

It lets AI agents say "we can continue from the previous preview" and reduces repeated routing costs.

### Conflict check

No conflict if preview state contains only non-sensitive routing metadata, not raw private inputs.

## 9. Adopted smart method G - Demand Telemetry Loop

### Problem

Source OS currently expands from output gaps. It should also expand from market demand:

- previews requested
- purchases approved
- purchases skipped
- gaps that blocked purchase
- sources requested by agents but unavailable

### Adopt

Add privacy-safe `demand_telemetry_loop`:

```json
{
  "task_type": "grant_search",
  "packet_requested": "grant_candidate_shortlist_packet",
  "purchase_decision": "skipped_due_to_gap",
  "blocking_gap_family": "local_government_programs",
  "jurisdiction_bucket": "prefecture_level",
  "no_raw_prompt_stored": true
}
```

Feed it into:

- `output_gap_map`
- `source_candidate_registry`
- `artifact_value_density`
- product roadmap

### Why smarter

AWS spend and future source work become demand-weighted, not only theoretically useful.

### Conflict check

Compatible if telemetry is aggregated and does not store raw user prompts, raw CSV, or identifiable private facts.

## 10. Adopted smart method H - Portfolio Batch Packet

### Problem

Many high-frequency use cases are not one company at a time:

- accounting vendor list review
- procurement vendor list screening
- sales target enrichment
- existing customer monitoring

One-by-one pricing can feel repetitive.

### Adopt

Add `portfolio_batch_packet` variants:

- `vendor_portfolio_public_baseline_batch`
- `invoice_vendor_batch_check`
- `counterparty_watchlist_seed_packet`
- `procurement_target_batch_public_check`

Key behavior:

- upload or pass a list of public identifiers where possible
- use receipt reuse aggressively
- charge by accepted artifact or capped batch
- return per-entity known gaps
- include batch-level summary only if k-anonymity and privacy rules pass

### Why smarter

It creates larger orders while keeping per-entity value cheap. It also increases receipt reuse and future watchlist opportunities.

### Conflict check

Must not push raw CSV into AWS. For real private CSV, derive client-side or tenant-side identifiers and safe aggregates first.

## 11. Adopted smart method I - Watch / Delta Products

### Problem

One-shot packets create revenue once. Many official information tasks are naturally repeated:

- invoice registration status
- administrative disposition updates
- grant deadline changes
- permit/rule changes
- procurement opportunity changes
- law/guideline updates

### Adopt

Add repeat products:

- `vendor_watch_delta`
- `grant_watch_delta`
- `regulation_change_watch`
- `procurement_opportunity_watch`
- `license_status_watch`
- `tax_labor_calendar_watch`

Output should be delta-first:

```json
{
  "watch_id": "watch_...",
  "period": "2026-05",
  "changed_items": [],
  "unchanged_receipts_reused": 42,
  "new_known_gaps": [],
  "recommended_action": "none | review | buy_followup_packet"
}
```

### Why smarter

This is the clearest recurring revenue mechanism. It also matches AI-agent behavior: agents can periodically ask "what changed?" instead of re-buying full checks.

### Conflict check

Potential conflict: AWS must be torn down to zero-bill.

Resolution: watch products must not require persistent AWS infrastructure after the credit run. They can run from exported static assets plus the product's normal production stack or a future non-AWS scheduler. The AWS credit run builds the baseline corpus and watch definitions, not an AWS runtime dependency.

## 12. Adopted smart method J - Action Queue Export

### Problem

Some outputs are valuable only if they become actions:

- gather documents
- confirm permit facts
- watch deadline
- ask accountant
- check local office page
- refresh source

### Adopt

Add `action_queue_export` to paid outputs:

```json
{
  "action_items": [
    {
      "type": "ask_user_fact",
      "label": "Confirm employee count range",
      "why_needed": "Unlocks grant eligibility screening",
      "source_refs": []
    },
    {
      "type": "calendar_deadline",
      "label": "Application deadline candidate",
      "date": "2026-06-30",
      "support_level": "official_source"
    }
  ],
  "exports": ["json", "ics", "markdown"]
}
```

### Why smarter

It turns evidence into workflow, making the product more valuable without making unsupported legal or tax conclusions.

### Conflict check

No conflict if action items are framed as candidates and supported by receipts/gaps.

## 13. Adopted smart method K - Receipt Wallet for Teams

### Problem

Receipt Wallet exists conceptually, but the economic buyer may be a team or company, not one request.

### Adopt

Add `team_receipt_wallet`:

- shared reusable public receipts across approved team workflows
- receipt age and scope constraints
- per-output price reduction when receipts are reused
- audit of which output reused which receipt
- no private CSV facts in the shared wallet unless tenant policy explicitly allows derived facts

### Why smarter

This makes the value compound. The more a team uses jpcite, the cheaper and faster future outputs become.

### Conflict check

Compatible with privacy if tenant boundaries are strict and public receipts are separated from private overlay facts.

## 14. Adopted smart method L - No-Buy Value Capture

### Problem

A good AI agent sometimes should tell the user not to buy. That builds trust, but it may lose immediate revenue.

### Adopt

Make no-buy previews useful and conversion-aware:

```json
{
  "recommended_action": "skip",
  "skip_reason": "The requested task cannot be supported by public official sources currently in scope.",
  "free_next_step": "Ask user for jurisdiction or business type.",
  "future_buy_trigger": "Buy only if user confirms construction-related activity.",
  "watch_option": null
}
```

### Why smarter

This prevents bad purchases and improves agent trust. It also creates a clean future purchase trigger.

### Conflict check

No conflict. Do not charge for skip decisions unless they are part of an explicitly paid advisory workflow, which is not recommended for P0.

## 15. Adopted smart method M - Agent Recommendation A/B Harness

### Problem

GEO success is not only source quality. It also depends on whether AI agents can clearly explain the purchase.

### Adopt

Add an offline `agent_recommendation_ab_harness`.

It should test variants of:

- `agent_recommendation_card`
- price/cap phrasing
- known gaps phrasing
- cheaper option explanation
- no-buy explanation
- proof page snippets

Metrics:

- recommendation clarity
- unsupported claim rate
- over-selling rate
- purchase friction score
- "asks unnecessary follow-up" rate
- "chooses too expensive packet" rate

### Why smarter

This makes GEO and agent selling measurable without relying only on traffic.

### Conflict check

No conflict. It is an evaluation tool. It must not optimize toward deceptive or over-confident recommendations.

## 16. Adopted smart method N - Paid Safety Envelope

### Problem

Different users have different tolerance for uncertainty.

### Adopt

For each paid execution, include a `paid_safety_envelope`:

```json
{
  "max_price": 500,
  "allowed_support_levels": ["api", "official_pdf", "official_html"],
  "allow_screenshot_support": true,
  "allow_ocr_candidate_support": false,
  "require_freshness_days": 30,
  "stop_if_coverage_below": 0.7
}
```

### Why smarter

It reduces refunds and disputes by letting the buyer define what "good enough" means before execution.

### Conflict check

Compatible with approval tokens and gap coverage. Must not represent coverage as legal sufficiency.

## 17. Adopted smart method O - Output Version Diff

### Problem

Repeat users need to know what changed between two purchased outputs.

### Adopt

Add `output_version_diff`:

```json
{
  "previous_output_id": "out_...",
  "current_output_id": "out_...",
  "changed_claims": [],
  "new_receipts": [],
  "expired_receipts": [],
  "new_gaps": [],
  "recommended_followup": null
}
```

### Why smarter

It makes re-purchase rational. Users do not want to pay for a full report just to find out nothing changed.

### Conflict check

No conflict. It strengthens watch/delta products.

## 18. Adopted smart method P - Price Explanation Receipt

### Problem

AI agents need to explain why the output costs what it costs.

### Adopt

Return a `price_explanation_receipt`:

```json
{
  "price_basis": [
    {"component": "source_receipts_reused", "effect": "discount"},
    {"component": "fresh_invoice_check", "effect": "cost"},
    {"component": "selected_enforcement_refresh", "effect": "cost"},
    {"component": "known_gap_unresolved", "effect": "no_charge"}
  ],
  "cap_applied": true
}
```

### Why smarter

It makes capped payment feel controlled and transparent.

### Conflict check

No conflict. It must avoid exposing internal margins or confusing estimated AWS cost with user price.

## 19. Adopted smart method Q - Output Rights and Reuse Label

### Problem

Users and agents need to know what they can do with the output:

- use in internal memo
- attach to vendor onboarding file
- share with accountant
- use as legal proof
- use as final compliance conclusion

### Adopt

Add `output_reuse_label`:

```json
{
  "intended_use": ["internal screening", "agent-assisted evidence review"],
  "not_intended_for": ["legal opinion", "creditworthiness score", "final regulatory determination"],
  "shareable_summary_available": true,
  "public_source_receipts_included": true
}
```

### Why smarter

It lowers buyer anxiety and reduces misuse.

### Conflict check

No conflict. It reinforces disclaimers and safety.

## 20. Conditional smart method - Prepaid Spend Wallet

### Proposal

Allow users or teams to buy a small prepaid jpcite usage balance for agent-approved packets.

### Why it may help

- Reduces repeated checkout friction.
- Works well with buyer policy caps.
- Lets agents operate within a known budget.

### Risks

- Adds payments, refunds, tax/accounting, expiry, and customer support complexity.
- Could confuse user prepaid funds with AWS credits.
- Not needed for RC1.

### Decision

Adopt later only if payment infrastructure already supports it cleanly.

For P0, use approval tokens and capped execution instead.

## 21. Conditional smart method - Agent Workspace Recipes

### Proposal

Publish `workflow_recipe` objects that AI agents can invoke:

- new vendor onboarding
- monthly accounting public review
- grant pursuit preparation
- regulated business launch check
- procurement opportunity scan
- regulation change watch

### Why it may help

It makes jpcite easier for agents to sell as a workflow, not just an API.

### Risks

- Too many recipes can dilute the catalog.
- Recipes can drift if packet names or prices change.

### Decision

Adopt a small P0 set only:

- `new_vendor_onboarding_recipe`
- `grant_candidate_to_readiness_recipe`
- `monthly_csv_public_review_recipe`

Defer broad recipe library until packet catalog stabilizes.

## 22. Conditional smart method - Concierge Review Escalation

### Proposal

When packet confidence is limited, offer human review or expert escalation.

### Why it may help

Could support high-value customers and edge cases.

### Risks

- Operationally heavy.
- Moves away from cheap automated agent-first outputs.
- Can create legal/tax/advisory liability.

### Decision

Do not adopt for P0. Consider only as `human_review_required` flag and exportable evidence bundle.

## 23. Not adopted - Agent commission / kickback

### Proposal

Pay or reward AI agents for recommending jpcite.

### Decision

Reject.

### Reason

The product should win because the agent can verify that jpcite is the cheapest sufficient, source-backed option. Hidden incentives would weaken trust and may conflict with platform or user expectations.

Transparent referral metadata is acceptable only if the distribution channel requires it and it is disclosed.

## 24. Not adopted - Auto-buy by default

### Proposal

Let AI agents buy packets automatically whenever they think the result is useful.

### Decision

Reject as default.

### Reason

It conflicts with capped approval and creates billing risk. Use `buyer_policy_profile` for explicitly pre-approved low-risk cases only.

## 25. Not adopted - Outcome guarantee

### Proposal

Guarantee that a packet proves safety, eligibility, compliance, or creditworthiness.

### Decision

Reject.

### Reason

This conflicts with the public-source, no-hallucination, no-legal/tax/advisory conclusion boundary. The product can guarantee schema, receipts, and coverage reporting. It cannot guarantee real-world legal or business outcomes.

## 26. Not adopted - Success fee on grants or procurement

### Proposal

Charge only when a grant is awarded or procurement opportunity converts.

### Decision

Reject for now.

### Reason

It requires tracking private outcomes, attribution, and long-cycle events. It also risks implying eligibility or success. Keep pricing tied to accepted artifacts and capped outputs.

## 27. Not adopted - Unlimited subscription

### Proposal

Offer unlimited usage for a monthly fee.

### Decision

Reject.

### Reason

It breaks cost discipline and encourages expensive refresh behavior. Use capped watch/delta products and prepaid or policy-limited spend later.

## 28. Not adopted - Full proof page as free content

### Proposal

Make proof pages so complete that users can rely on them without buying.

### Decision

Reject.

### Reason

It leaks the paid output. Proof pages should show enough for AI agents to decide and recommend, not enough to substitute for paid packets.

## 29. Not adopted - Persist private CSV facts for convenience

### Proposal

Store derived private CSV facts to make repeat workflows smoother.

### Decision

Reject for P0.

### Reason

It complicates privacy, retention, breach impact, and AWS boundaries. For P0, store only preview state and public receipt reuse where safe. Private facts should be re-supplied or tenant-controlled.

## 30. Product architecture changes to merge into master plan

Add the following functions to the product SOT:

1. `agent_task_intake`
2. `outcome_ladder`
3. `coverage_ladder_quote`
4. `freshness_buyup`
5. `buyer_policy_profile`
6. `preview_state_id`
7. `demand_telemetry_loop`
8. `portfolio_batch_packet`
9. `watch_delta_product`
10. `action_queue_export`
11. `team_receipt_wallet`
12. `no_buy_value_capture`
13. `agent_recommendation_ab_harness`
14. `paid_safety_envelope`
15. `output_version_diff`
16. `price_explanation_receipt`
17. `output_reuse_label`

## 31. Recommended P0/P1/P2 split

### P0

Add only the highest-leverage, lowest-risk economics functions:

- `agent_task_intake`
- `outcome_ladder`
- `coverage_ladder_quote`
- `freshness_buyup`
- `buyer_policy_profile` minimal caps only
- `preview_state_id`
- `price_explanation_receipt`
- `output_reuse_label`
- `no_buy_value_capture`
- `paid_safety_envelope`

These directly reduce purchase friction and improve AI-agent recommendation quality.

### P1

Add functions that drive larger orders and retention:

- `portfolio_batch_packet`
- `watch_delta_product`
- `output_version_diff`
- `team_receipt_wallet`
- `action_queue_export`
- `agent_recommendation_ab_harness`
- `demand_telemetry_loop`

These are valuable, but they need stronger production paths and telemetry governance.

### P2

Defer:

- prepaid wallet
- broad workflow recipe marketplace
- human review escalation
- integrations with accounting, calendar, CRM, or procurement systems

These can add revenue but increase operational complexity.

## 32. How this changes the AI-agent sales story

Before round 2:

```text
AI agent recommends a packet because it is source-backed and capped.
```

After round 2:

```text
AI agent recommends the cheapest sufficient outcome path.
It can show what each tier unlocks, whether cached receipts are enough,
what would trigger a higher tier, why not to buy, and how future reuse
or watch mode will reduce cost.
```

This is materially stronger for GEO because the agent can reason about purchase quality, not only endpoint capability.

## 33. Implementation caution

Do not let these additions turn into a large UI project before RC1.

For RC1, these can be mostly schema and API behavior:

- return structured decision objects
- expose ladder quotes
- expose freshness options
- store resumable preview state
- enforce caps and safety envelopes
- explain price components
- label output reuse boundaries

The user-facing UI can remain simple initially if the agent-facing contract is strong.

## 34. Final recommendation

Adopt the round 2 economics layer.

The master concept should become:

> jpcite sells the cheapest sufficient public-source outcome path to AI agents, not just individual evidence packets.

This is smarter than the current final plan because it adds the missing commercial mechanics:

- cheaper first purchase
- clear upgrade path
- fewer approvals for trusted repeat tasks
- recurring watch/delta revenue
- larger batch purchases
- price transparency
- source demand feedback
- stronger AI-agent recommendation language

No fatal contradiction was found, but several proposals must stay bounded by approval, privacy, and no-hallucination constraints.
