# AWS final 12 review 12/12: cross synthesis

Date: 2026-05-15
Role: final cross-review for smarter functions, methods, and contradiction checks
AWS execution: none. No AWS CLI/API command, AWS resource creation, collection job, deployment, or deletion was performed.
Write scope: this file only.

## 0. Reviewed inputs

Primary plan:

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`

Available final-12 review files found locally:

- `docs/_internal/aws_final_12_review_01_cost_autonomy.md`
- `docs/_internal/aws_final_12_review_02_revenue_packets.md`
- `docs/_internal/aws_final_12_review_03_source_priority.md`
- `docs/_internal/aws_final_12_review_04_algorithm_safety.md`
- `docs/_internal/aws_final_12_review_05_release_zero_bill.md`
- `docs/_internal/aws_final_12_review_06_security_terms_privacy.md`

Process note:

- Files `aws_final_12_review_07` through `aws_final_12_review_11` were requested in the prompt but were not present in `docs/_internal` at review time.
- This is not treated as an AWS/product contradiction, but it is a process gap.
- Before implementation, run a document inventory once more. If 07-11 are later produced, reconcile them against this 12/12 synthesis and the master plan before running AWS.

## 1. Verdict

Conditional PASS.

The master plan is directionally correct and does not have a fatal architectural contradiction if the additions below are adopted.

The biggest remaining improvement is not a better execution order. The better plan is a smarter set of product and control-plane functions:

1. Turn AWS spending into a `budget token market`, not dashboard-based threshold watching.
2. Turn free preview into an `agent_purchase_decision` object, not a simple price estimate.
3. Turn source collection into an `output_gap_map` driven source operating system, not a broad crawl.
4. Turn algorithm outputs into internal candidates that must pass a deterministic public-output compiler.
5. Turn release into manifest/pointer/feature-flag controlled exposure, not direct deployment of AWS artifacts.
6. Turn zero-bill teardown into a machine-readable ledger, not an operator checklist.
7. Turn proof pages into agent decision pages, not human marketing pages.

If those changes are merged into the master plan, this becomes a substantially smarter and safer plan.

## 2. Highest-value smart improvements to adopt

### 2.1 Control-spend brain

Adopt.

The master plan currently has the right stopline concept, but the stop table still says "Visible usage." That wording should be replaced everywhere with `control_spend_usd`.

Required final definition:

```text
control_spend_usd =
  max(
    cost_explorer_unblended_actual_usd,
    budget_actual_or_forecast_usd,
    internal_operator_ledger_usd
  )
  + p95_running_cost_to_complete_usd
  + p95_queued_cost_to_complete_usd
  + p95_service_tail_risk_usd
  + stale_cost_penalty_usd
  + untagged_resource_penalty_usd
  + cleanup_reserve_usd
```

Why this is smarter:

- AWS billing dashboards lag.
- Cost Explorer is not a real-time kill switch.
- Running and queued jobs can still spend after visible cost looks safe.
- The user wants AWS to keep running even when Codex/Claude are unavailable.
- Therefore the control plane must reserve and forecast spend before submitting work.

### 2.2 Budget token market

Adopt.

Every AWS job must reserve budget before submission.

Required primitive:

```json
{
  "job_reserved_usd": 25.0,
  "max_runtime_minutes": 30,
  "max_items": 1000,
  "max_retries": 1,
  "queue_id": "revenue_first_sources",
  "accepted_artifact_target": "source_receipts",
  "kill_level_allowed": 1
}
```

Submit rule:

```text
submit only if:
  global.observed_usd
  + global.reserved_usd
  + global.penalties_usd
  + job_reserved_usd
  <= global.max_control_spend_usd

and:
  queue.observed_usd
  + queue.reserved_usd
  + job_reserved_usd
  <= queue.cap_usd

and:
  kill_level <= job.kill_level_allowed
  allow_new_work == true
```

This is the core design that lets AWS self-run without becoming self-spending.

### 2.3 Artifact value density scheduler

Adopt.

The plan should not just spend fast. It should continually move budget toward jobs with the highest expected product value per dollar.

Use:

```text
artifact_value_density =
  (
    paid_packet_revenue_weight
    * source_coverage_gain
    * proof_reusability_score
    * geo_discovery_gain
    * uniqueness_score
    * freshness_score
    * quality_pass_probability
    * terms_confidence
  )
  / p95_cost_to_complete_usd
```

Required behavior:

- In `RUNNING_STANDARD`, allow medium/high value density.
- In `WATCH`, freeze low-density jobs.
- In `SLOWDOWN`, continue only high-density jobs.
- In `RUNNING_STRETCH`, allow only short, preapproved, high-density, low-abort-cost jobs.
- In `NO_NEW_WORK`, no new source/render/OCR jobs.

This prevents the credit run from becoming a broad source lake that does not convert into paid packets.

### 2.4 Source operating system

Adopt.

The smarter data strategy is not "collect more public information." It is:

```text
paid output
  -> required claims
  -> output_gap_map
  -> source candidate registry
  -> source_profile gate
  -> capture method router
  -> canary collection
  -> accepted artifact measurement
  -> expand / suppress / manual review decision
```

Required new concepts:

- `output_gap_map`
- `source_candidate_registry`
- `capture_method_router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`

Source collection should expand only when it closes a packet gap or improves a proof/GEO surface.

### 2.5 Capture method router

Adopt.

Playwright/OCR should not be the default. They are useful but expensive and riskier.

Required method order:

1. official API
2. official bulk download
3. official CSV/XML/JSON/PDF
4. static HTML fetch
5. PDF text extraction
6. Playwright rendered observation
7. OCR/Textract candidate extraction
8. metadata-only or manual review

Important:

- Playwright is rendered observation, not access bypass.
- OCR is supporting evidence, not standalone truth for critical facts.
- CAPTCHA/login/403/429/error pages become known gaps, not no-hit evidence.

### 2.6 Free preview as purchase decision object

Adopt.

The most important revenue improvement is to make preview act as the AI agent's purchasing decision object.

Preview should return:

```json
{
  "preview_type": "agent_purchase_decision",
  "recommended_action": "buy_packet | ask_followup | skip_jpcite | use_free_guidance",
  "recommended_packet": "company_public_baseline",
  "cheaper_alternative_packet": "invoice_vendor_public_check",
  "why_buy": [],
  "why_not_buy": [],
  "required_inputs_now": [],
  "optional_inputs_that_improve_output": [],
  "expected_output_skeleton": {},
  "price_quote": {
    "jpy_inc_tax_max": 330,
    "cap_required": true
  },
  "approval": {
    "approval_token_required": true,
    "setup_url": "..."
  },
  "agent_recommendation_card": {
    "headline_ja": "公的source付きで会社確認できます",
    "cost_line_ja": "最大税込330円。承認したcapを超えません。",
    "caveat_line_ja": "no-hitは不存在や安全の証明ではありません。",
    "approval_question_ja": "この上限額でjpciteの有料packetを実行しますか？"
  }
}
```

This is smarter than a normal quote because it tells the AI agent:

- whether to recommend jpcite,
- which packet is cheapest and sufficient,
- what the user will get,
- what jpcite will not conclude,
- how to ask for approval.

### 2.7 Cheapest sufficient packet routing

Adopt.

The product promise is "end users can cheaply get the outputs they want through AI." Therefore route should prefer the cheapest sufficient packet, not the most comprehensive packet.

Examples:

| User task | Do not over-sell | Prefer |
|---|---|---|
| T番号確認 | `counterparty_public_dd_packet` | `invoice_vendor_public_check` |
| 会社の公的基本確認 | full DD | `company_public_baseline` |
| 補助金候補 | custom broad research | `grant_candidate_shortlist_packet` |
| 許認可の関係有無 | legal conclusion | `permit_scope_checklist_packet` with caveats |

Required route output:

```json
{
  "recommended_packet": "invoice_vendor_public_check",
  "not_recommended_packets": [
    {
      "packet": "counterparty_public_dd_packet",
      "reason": "ユーザー依頼はT番号確認だけなのでDD packetは過剰"
    }
  ]
}
```

### 2.8 Accepted-artifact billing

Adopt.

Charge only when an accepted paid artifact is actually created.

Billable only if:

- valid approval token exists,
- idempotency key exists,
- cap is respected,
- accepted packet output is generated,
- `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `gap_coverage_matrix[]`, and `billing_metadata` are present,
- no release blocker is triggered.

Not billed:

- invalid input,
- identity unresolved,
- preview required,
- source blocked before execution,
- no-hit-only without explicit no-hit receipt,
- gate failure,
- duplicate idempotency replay.

This makes AI-agent-mediated charging much easier to trust.

### 2.9 Public-output compiler

Adopt as mandatory.

The algorithm documents can contain internal candidate labels and intermediate scores. Public outputs must not.

All API/MCP/proof outputs must pass through a deterministic compiler that enforces:

- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]`
- `algorithm_trace[]`
- `score_set[]`
- no generic `score`
- no external `eligible`
- no external `safe`, `no issue`, `permission not required`, `proved absent`, `credit score`
- OCR/Playwright support-level gates
- private CSV separation
- source terms/robots validity

This is the strongest hallucination-prevention improvement. Do not add more model freedom. Add stricter publication control.

### 2.10 Release control plane

Adopt.

Production should be controlled by manifests and pointers, not by directly exposing AWS artifacts.

Required files:

```text
release_manifest.json
active_dataset_pointer.json
packet_catalog.json
pricing_catalog.json
mcp_manifest.json
openapi_agent_safe.json
rollback_manifest.json
checksum_manifest.txt
quality_gate_report.jsonl
import_gate_report.json
```

Required release architecture:

```text
AWS candidate artifact
-> external export slice
-> quarantine validation
-> accepted bundle
-> staging shadow release
-> production candidate manifest
-> active pointer switch
```

Rollback must be a pointer/flag switch. It must not require AWS, S3, OpenSearch, Athena, Glue, or Batch.

### 2.11 Three-layer feature flags

Adopt.

Do not use a single on/off flag per feature. Split exposure:

| Layer | Meaning |
|---|---|
| visibility | proof/catalog/tool is visible |
| executability | API/MCP execution is accepted |
| billability | paid execution is allowed |
| cap | maximum units/JPY/subjects/time |
| dependency | AWS dependency allowed |

Production invariant:

```text
runtime.aws_dependency.allowed=false
```

### 2.12 Two-bundle archive

Adopt.

AWS zero-bill and proof safety require two export classes:

1. `public_safe_bundle`
   - source profiles
   - receipts
   - claim refs
   - known gaps
   - proof sidecars
   - packet examples
   - no raw screenshots/HAR/OCR dumps

2. `restricted_evidence_archive`
   - raw public snapshots
   - screenshots
   - OCR candidates
   - large capture logs
   - git outside
   - public static path outside
   - access owner and retention policy required

Production must depend only on `public_safe_bundle`, runtime DB, and proof sidecars.

## 3. Contradictions checked and resolutions

### 3.1 "Use all USD 19,493.94" versus zero cash billing

Potential contradiction:

- User wants to use roughly all of the AWS credit.
- User also requires no further AWS billing.

Resolution:

- Treat `USD 19,300` as the maximum `control_spend_usd`.
- Do not try to burn the final `USD 193.94`.
- The difference is the safety margin for delayed billing, ineligible charges, running exposure, cleanup, logs, telemetry, and estimation error.

Master plan change:

- Wherever the plan says the goal is to consume the full credit, clarify: "maximize useful conversion up to the `USD 19,300` control line; never target exact face value."

### 3.2 Self-running AWS versus uncontrolled spend

Potential contradiction:

- AWS should continue running when Codex/Claude/local terminal is unavailable.
- AWS must not overspend.

Resolution:

- AWS can self-run only under the token market.
- Every job must reserve budget before submission.
- `kill_level` must be monotonic.
- Submitters, workers, and stretch jobs must read the control table before starting work.
- Budget Actions are backup brakes, not the primary steering wheel.

### 3.3 Fast spend versus safe teardown

Potential contradiction:

- User wants the credit consumed quickly, ideally within about one week.
- User also wants zero-bill after the run.

Resolution:

- Use many bounded, checkpoint-first shards.
- Keep cleanup/export budget reserved from the beginning.
- Stop new work at `18,900` unless preapproved stretch tokens are available.
- Use short high-value stretch jobs only.
- Move to export/teardown at `19,300` control spend.

### 3.4 Broad source scope versus production readiness

Potential contradiction:

- The source universe should be broad: laws, systems, industry rules, permits, gazette, local governments, courts, statistics, standards, tax/labor, enforcement.
- Production cannot wait for full broad corpus completion.

Resolution:

- P0 is not "important public information."
- P0 is "source-profile-gated, receiptable, terms-clear source that directly supports a paid output."
- Broad sources can be collected as P1/P2 candidates, but RC1 production should use small accepted bundles.

### 3.5 Playwright "fetch difficult pages" versus access bypass

Potential contradiction:

- User expects Playwright/screenshots to help with pages that are hard to fetch.
- The service must not bypass access restrictions or create terms/security risk.

Resolution:

- Playwright is allowed only as public rendered observation.
- No CAPTCHA solving, login use, cookie reuse, stealth plugin, proxy rotation, hidden API reverse engineering, or 403/429 retry loops.
- Blocked states become `known_gap`, not no-hit evidence.

### 3.6 Algorithmic output versus legal/tax/compliance overclaim

Potential contradiction:

- The product should produce high-value outputs.
- It must not make final legal, tax, safety, credit, eligibility, or compliance decisions.

Resolution:

- Use typed score sets and candidate priority.
- Ban public `eligible`, `safe`, `no issue`, `permission not required`, `credit score`, `proved absent`.
- Include `human_review_required` and `known_gaps`.
- Require public-output compiler and adversarial tests.

### 3.7 CSV value versus privacy

Potential contradiction:

- CSV overlay can increase value.
- Real private CSV must not enter AWS and must not leak into public proof/API/MCP examples.

Resolution:

- AWS credit run uses only synthetic/header-only/redacted fixtures and public official CSV.
- Runtime private overlay later must be tenant-private, memory-first, suppression-gated, and separated from public source receipts.
- Public examples must contain no real CSV-derived facts.

### 3.8 Proof pages versus giving away paid value

Potential contradiction:

- GEO requires rich proof pages.
- Full proof output can leak paid value.

Resolution:

- Proof pages should be agent decision pages.
- Show when to recommend, when not to recommend, output skeleton, price/cap, no-hit policy, and short safe examples.
- Do not expose high-value hit outputs, full raw receipts, raw screenshots, raw OCR text, raw DOM, or full HAR.

### 3.9 `source_receipt_ledger` as product versus weak end-user CTA

Potential contradiction:

- `source_receipt_ledger` is central to trust.
- It is abstract for end users.

Resolution:

- Keep it as RC1 paid/developer/audit packet.
- Do not make it the main human CTA.
- Lead with `company_public_baseline` and `invoice_vendor_public_check`.
- Include a compact receipt ledger inside every paid packet.

### 3.10 Final S3 archive versus zero-bill

Potential contradiction:

- Keeping S3 is convenient.
- Zero-bill requires no ongoing AWS charges.

Resolution:

- Default End State A only: no S3 archive.
- Export outside AWS, verify checksums, assetize, smoke without AWS, then delete S3 and all run resources.

## 4. Adopt into the master plan

These are the concrete deltas that should be merged into the master plan before implementation.

### D-01: Replace stopline wording

Current issue:

- Stopline table says `Visible usage`.

Change to:

```text
Line | control_spend_usd | Required behavior
```

Add the `control_spend_usd` formula from section 2.1.

### D-02: Add budget token market section

Add a section under spend controls:

- global budget bucket,
- queue buckets,
- atomic reservation,
- reservation refund,
- P95 running/queued exposure,
- monotonic kill level,
- preapproved stretch token,
- cleanup reserve.

### D-03: Add required job manifest fields

Every AWS job must declare:

- `job_id`
- `queue_id`
- `job_class`
- `source_family_id`
- `source_profile_id`
- `accepted_artifact_target`
- `max_runtime_minutes`
- `max_items`
- `max_retries`
- `job_reserved_usd`
- `p95_cost_to_complete_usd`
- `kill_level_allowed`
- `data_class`
- `private_user_data_present`
- `capture_method`
- `terms_receipt_id`
- `robots_receipt_id`

No `accepted_artifact_target`, no spend.

### D-04: Add artifact value scheduler

Add:

- value density formula,
- hourly dynamic rebalancing,
- accepted artifact yield metrics,
- low-yield source suppression,
- high-yield source expansion,
- source-aware circuit breakers.

### D-05: Add source operating system

Add:

- `output_gap_map`,
- `source_candidate_registry`,
- `source selection features`,
- `capture_method_router`,
- `expand_suppress_controller`,
- `source suppression as known gap`.

This should sit between "Public source scope" and "AWS architecture."

### D-06: Add purchase decision preview

Replace simple cost preview with `agent_purchase_decision`.

Required fields:

- `recommended_action`
- `recommended_packet`
- `cheaper_alternative_packet`
- `not_recommended_packets`
- `why_buy`
- `why_not_buy`
- `blocking_questions`
- `optional_questions`
- `expected_output_skeleton`
- `price_quote`
- `approval_token_required`
- `agent_recommendation_card`
- `do_not_buy_reasons`
- `next_best_action`

### D-07: Add cheapest sufficient packet router

Add route rule:

```text
Choose the cheapest packet that satisfies task fit, coverage threshold, forbidden-judgment safety, and explainable known gaps.
```

This supports the core product promise: cheap outputs through AI agents.

### D-08: Add paid safety envelope

Every paid execution requires:

- `preview_id`
- `pricing_version`
- `packet_version`
- `dataset_version`
- `cost_cap_jpy_inc_tax`
- `user_approved_cap_token`
- `idempotency_key`
- `max_units`
- `max_subjects`
- `no_hit_billing_policy`
- `refund_or_free_policy_for_empty_result`

### D-09: Add accepted-artifact billing policy

Charge only if:

```text
accepted_artifact_created = true
```

Do not bill invalid input, source block, identity unresolved, no-hit-only without explicit receipt, or gate failure.

### D-10: Add checked-scope receipt as optional micro product

No-hit-only should not bill by default. However, if explicitly requested and preview-approved, a small `checked_scope_receipt` can be sold.

External wording:

```text
指定した公的sourceと期間で確認した範囲の証跡です。不存在・安全・問題なしの証明ではありません。
```

### D-11: Add public-output compiler

Before any public API/MCP/proof/JSON-LD/llms output:

- normalize external labels,
- convert scores to `score_set[]`,
- bind every claim to receipts,
- compile no-hit scope,
- require `gap_coverage_matrix[]`,
- strip internal-only algorithm fields,
- block forbidden wording,
- block raw CSV/screenshot/OCR/HAR/DOM exposure,
- block private overlay as public claim.

### D-12: Add adversarial public-output tests

Required fixtures:

- invoice no-hit misread as unregistered,
- company no-hit misread as non-existent,
- disposition no-hit misread as no issue,
- grant candidate misread as eligible,
- permit rule not triggered misread as permission not required,
- low public-evidence attention misread as safe,
- OCR date/deadline digit error,
- Playwright 403/429 capture attempt,
- LLM candidate plausible but unsupported,
- CSV formula injection,
- private CSV-like string in logs.

### D-13: Add release control plane

Add:

- `release_manifest.json`,
- `active_dataset_pointer.json`,
- `rollback_manifest.json`,
- manifest hash checks,
- catalog drift firewall,
- pointer-switch rollback.

### D-14: Add RC1a/RC1b/RC1c split

RC1 should not be a single gate.

```text
RC1a: static proof + pricing/docs + GEO discovery, no paid execution
RC1b: free controls + minimal MCP/API, no paid execution
RC1c: limited paid packets with low cap
```

This improves production speed without increasing AWS/product risk.

### D-15: Add transactional artifact import

Add pipeline:

```text
candidate
-> quarantine
-> validation
-> accepted bundle
-> staging shadow
-> production pointer
```

AWS artifact is never production source of truth.

### D-16: Add production smoke without AWS earlier

Run `production_without_AWS` smoke:

- before RC1a production,
- before RC1c paid production,
- before RC2/RC3 import,
- before S3 deletion.

Check for:

- `amazonaws.com`,
- S3 bucket names,
- OpenSearch endpoints,
- AWS env dependencies,
- MCP/OpenAPI AWS URLs,
- proof asset AWS URLs,
- rollback asset location.

### D-17: Add two-bundle export model

Add:

- `public_safe_bundle`,
- `restricted_evidence_archive`,
- `discard_bundle`.

Only `public_safe_bundle` can enter production/static assets.

### D-18: Add data class manifest gate

Every artifact needs:

- `artifact_id`
- `artifact_class`
- `data_class`
- `private_user_data_present`
- `source_profile_id`
- `terms_receipt_id`
- `robots_receipt_id`
- `public_publish_allowed`
- `public_claim_support_allowed`
- `retention_class`
- `export_destination_class`

### D-19: Add HAR/OCR/screenshot safety gates

HAR:

- metadata only,
- no body,
- no cookies,
- no auth headers,
- no tokens,
- no storage dumps.

OCR:

- no public full-text dump,
- no critical claim supported only by OCR,
- confidence/bbox/source hash required.

Screenshot:

- each side `<=1600px`,
- raw screenshot not public by default,
- public PII review/suppression required.

### D-20: Add task recipe catalog

AI agents need workflow recipes, not just tools.

Initial recipes:

- `vendor_onboarding_public_check`
- `grant_application_prep`
- `regulated_business_precheck`
- `monthly_accounting_public_review`
- `policy_change_watch_setup`

Each recipe declares:

- steps,
- approval points,
- stop conditions,
- paid packet candidates,
- free fallback,
- forbidden final judgments.

## 5. Do not adopt

### N-01: Do not target exact credit face value

Do not try to spend exactly `USD 19,493.94`.

Reason:

- Directly conflicts with zero cash billing.
- Delayed billing and ineligible charges create tail risk.

### N-02: Do not use billing dashboard as the primary controller

Do not make Cost Explorer/Budgets visible spend the steering wheel.

Use:

- internal reservation ledger,
- resource ledger,
- P95 exposure,
- Cost Explorer as reconciliation and backup signal.

### N-03: Do not broaden into an undirected source lake

Do not spend heavily on "interesting public information" unless it closes a paid output gap or creates proof/GEO value.

### N-04: Do not make Playwright a bypass tool

Do not use:

- CAPTCHA solving,
- login,
- stealth plugin,
- proxy rotation,
- hidden API reverse engineering,
- 403/429 retry loops.

### N-05: Do not publish raw screenshots, DOM, HAR, or OCR text

These are evidence/archive materials, not public proof payloads by default.

### N-06: Do not put real CSV into AWS

Do not process or store:

- real user CSV bytes,
- real rows,
- real memo/counterparty values,
- real aggregates,
- real profile hashes,
- suppression patterns from real users.

### N-07: Do not use request-time LLM for public claims

Do not let LLM output become `claim_refs[]`.

Offline LLM/Bedrock assistance can produce candidate facts only if they are validated by public-source receipts before public emission.

### N-08: Do not externally show `eligible`, `safe`, or generic scores

Do not expose:

- `eligible`,
- `not eligible`,
- `safe`,
- `no issue`,
- `permission not required`,
- `credit score`,
- generic `score`.

Use:

- `candidate_priority`,
- `public_evidence_attention`,
- `evidence_quality`,
- `coverage_gap`,
- `needs_review`,
- `not_enough_public_evidence`,
- `no_hit_not_absence`.

### N-09: Do not lead sales with `source_receipt_ledger`

Keep it, but do not make it the main CTA for end users.

Lead with:

- `company_public_baseline`,
- `invoice_vendor_public_check`,
- `counterparty_public_dd_packet`,
- `grant_candidate_shortlist_packet`,
- `permit_scope_checklist_packet`.

### N-10: Do not bill no-hit-only by default

No-hit-only should be free unless the user explicitly requested and approved a checked-scope receipt.

### N-11: Do not keep final S3 archive

If zero ongoing AWS bill is mandatory, final S3 archive is not acceptable.

Export outside AWS, verify, assetize, then delete.

### N-12: Do not bring CSV paid runtime into RC1

RC1 should be public-source-only. CSV runtime belongs later after privacy/suppression/runtime gates.

AWS can prepare synthetic CSV fixtures, adapters, leak scanners, and schema tests.

## 6. Final smart feature stack

The final system should be thought of as seven layers.

### Layer 1: Product contract

Defines:

- packet envelope,
- source receipt schema,
- claim refs,
- known gaps,
- gap coverage matrix,
- no-hit checks,
- algorithm trace,
- score set,
- pricing/cap/billing envelope.

### Layer 2: Agent purchase layer

Defines:

- route,
- preview,
- agent purchase decision,
- recommendation card,
- cheapest sufficient packet,
- approval token,
- task recipes.

### Layer 3: Source operating system

Defines:

- output gap maps,
- source candidate registry,
- source profile gate,
- terms/robots/license gate,
- capture method router,
- expand/suppress controller.

### Layer 4: AWS artifact factory

Defines:

- EventBridge/Step Functions/Batch/SQS/DynamoDB self-run,
- budget token market,
- P95 cost exposure,
- artifact value density,
- source circuit breakers,
- checkpoint-first workers,
- export pipeline.

### Layer 5: Deterministic publication compiler

Defines:

- evidence binding,
- label normalization,
- typed score compilation,
- no-hit scope compilation,
- gap matrix enforcement,
- OCR/Playwright support checks,
- forbidden phrase scanner,
- privacy redaction.

### Layer 6: Release control plane

Defines:

- release manifest,
- active dataset pointer,
- three-layer flags,
- transactional import,
- shadow release,
- catalog drift firewall,
- pointer rollback.

### Layer 7: Zero-bill and assetization

Defines:

- public safe bundle,
- restricted evidence archive,
- production smoke without AWS,
- zero-bill guarantee ledger,
- cleanup inventory,
- post-teardown billing checks.

## 7. Revised master-plan decision summary

The final answer to "is there a smarter method/function/design?" is yes.

The smarter design is:

```text
AI-agent purchase decision layer
  + output-gap-driven source OS
  + token-market AWS artifact factory
  + deterministic public-output compiler
  + manifest/pointer release control plane
  + two-bundle archive and zero-bill ledger
```

This is better than the current master plan because it changes the system from:

```text
collect public data -> generate packets -> deploy
```

into:

```text
identify sellable output gaps
  -> buy only high-value public evidence with AWS tokens
  -> compile safe claim packets
  -> let AI agents recommend the cheapest sufficient paid output
  -> expose through controlled manifests and flags
  -> export/delete AWS without production dependency
```

That is the cleanest version of the concept:

> End users use AI to get cheap, source-backed Japanese public-information outputs. AI agents can discover, preview, recommend, get approval, execute capped paid packets, and preserve receipts/gaps without request-time hallucination.

## 8. Implementation readiness conditions

Do not start full AWS until these are true:

1. Master plan is patched with `control_spend_usd`.
2. Budget token market schema exists.
3. Required job manifest fields are fixed.
4. Packet/public-output contract is fixed.
5. Public-output compiler exists or its tests are defined.
6. Preview decision object schema is fixed.
7. Packet catalog canonical names are fixed.
8. Source candidate registry and source profile gate are fixed.
9. Data class manifest gate exists.
10. Release manifest and active dataset pointer are fixed.
11. External export destination and two-bundle policy are fixed.
12. Production smoke without AWS is defined.
13. Zero-bill cleanup role and deny policies are designed so cleanup is not blocked.

GO for AWS canary only after:

- guardrails exist,
- kill switch is tested,
- budget token reservation works,
- cleanup dry-run works,
- source profile gate works,
- no private CSV can enter AWS,
- export can be verified outside AWS.

GO for RC1a production only after:

- static proof pages pass,
- no AWS URL/dependency is present,
- forbidden wording scan passes,
- no-hit wording scan passes,
- raw CSV leak scan passes,
- rollback assets are outside AWS.

GO for RC1c paid only after:

- paid safety envelope works,
- approval token works,
- idempotency works,
- accepted-artifact billing works,
- low caps are enforced,
- billing metadata is correct,
- per-packet rollback flag exists.

## 9. Remaining open item

The only process-level inconsistency is that `aws_final_12_review_07` through `aws_final_12_review_11` were not present locally when this final synthesis was written.

Recommended handling:

1. Do not run AWS on the assumption that missing docs contained no blockers.
2. Before implementation, run a final inventory of `docs/_internal/aws_final_12_review_*.md`.
3. If 07-11 appear, compare them against sections 2-8 of this document.
4. If they introduce a conflict, update the master plan and this synthesis before AWS canary.

This does not change the product conclusion. The currently available evidence supports conditional PASS with the required smart-function additions above.

