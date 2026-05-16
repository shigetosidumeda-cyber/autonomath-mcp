# jpcite AWS / product master execution plan

Date: 2026-05-15  
Status: execution-ready plan, no AWS commands executed in this document  
Scope: jpcite product plan, AWS credit run, public official data corpus, packet outputs, GEO discovery, production release, zero-bill teardown  
AWS profile: `bookyou-recovery`  
AWS account: `993693061769`  
AWS region: `us-east-1`  
Credit face value: `USD 19,493.94`  
Target credit conversion line: `USD 19,490`  
Cash-bill guard: stop below target if exact conversion creates any non-credit cash exposure

## 0. Final decision

This is the execution SOT for the current plan.

The service should not be positioned as "cached public data search." The value is:

> AI agents can cheaply buy source-backed Japanese public-information outputs for end users, with receipts, gaps, no-hit caveats, pricing metadata, and no request-time hallucination.

AWS is a one-time, short-lived artifact factory. It should quickly convert the expiring credit into durable jpcite assets, then be fully torn down so no ongoing AWS bill remains.

Non-negotiable decisions:

1. Use AWS in `us-east-1` under profile `bookyou-recovery`, account `993693061769`.
2. Target `USD 19,490` of eligible credit conversion, while treating any cash-bill exposure as a higher-priority stop condition.
3. Make AWS self-running after launch. Codex, Claude Code, or local terminal rate limits must not stop the queued AWS run.
4. AWS must still stop itself at spend/quality/terms/kill-switch lines.
5. Production must not depend on AWS runtime services after the run.
6. Export valuable artifacts outside AWS before teardown.
7. Delete S3 and all run resources at the end. A final S3 archive is not compatible with "no further AWS bill."
8. Public/private accounting CSV from real users never enters AWS in this credit run.
9. Request-time LLM remains off: `request_time_llm_call_performed=false`.
10. No-hit means `no_hit_not_absence`, never "safe", "not found means absent", "no issue", or "permission not required."

## 1. What AWS is for

AWS will create durable assets, not a permanent runtime.

AWS should produce:

- `source_profile` candidates
- source family coverage ledgers
- license / terms / robots ledgers
- official source snapshots where allowed
- Playwright rendered observation receipts for public pages where allowed
- 1600px-or-smaller screenshot receipts
- OCR / Textract candidate extraction for public documents only
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]`
- `algorithm_trace[]`
- packet example JSON
- proof page sidecars
- agent-safe OpenAPI examples
- MCP example inputs and outputs
- `llms.txt` and `.well-known` discovery candidates
- GEO evaluation reports
- pricing / cost preview examples
- release gate reports
- checksum and cleanup ledgers

AWS must not produce or retain:

- production runtime dependencies
- raw private CSV
- row-level private CSV
- private CSV aggregates from real users
- raw public screenshots exposed directly to public proof pages
- HAR body/cookies/auth headers
- login/CAPTCHA/bot-challenge bypass outputs
- unsupported legal, tax, compliance, safety, credit, or eligibility conclusions

## 2. The business route

The main growth route is GEO, not SEO.

The intended loop:

1. AI agents discover jpcite through `llms.txt`, `.well-known`, MCP manifest, agent-safe OpenAPI, and proof pages.
2. They call free catalog / routing / cost-preview surfaces.
3. They tell the end user which packet is worth buying, how much it costs, and what gaps remain.
4. User approval triggers capped paid MCP/API execution.
5. The output returns machine-readable evidence, receipts, gaps, caveats, and billing metadata.

Important pricing correction:

- `agent_routing_decision` is a free control, not a paid packet.
- RC1 paid packets should include at least `company_public_baseline`, `source_receipt_ledger`, and `evidence_answer`.
- Every paid packet needs free preview, cap, approval token, and idempotency.

## 3. Output-first priorities

The corpus should be prioritized by sellable outputs, not by "what can be scraped."

Highest-priority paid outputs:

| Priority | Output | Why it sells | Key sources |
|---:|---|---|---|
| 1 | `company_public_baseline` | Low-friction proof of value for any company query | NTA法人番号, インボイス, gBizINFO, EDINET metadata |
| 2 | `invoice_vendor_public_check` | Common accounting / vendor workflow | NTA法人番号, インボイス, gBizINFO |
| 3 | `counterparty_public_dd_packet` | B2B risk / procurement / sales support | registry, license, enforcement, procurement, EDINET |
| 4 | `administrative_disposition_radar_packet` | Clear public evidence value | ministry notices, MLIT negative info, FSA, CAA, JFTC |
| 5 | `grant_candidate_shortlist_packet` | Direct small-business utility | J-Grants, ministries, local governments, eligibility rules |
| 6 | `application_readiness_checklist_packet` | Converts search into action | public program requirements, forms, deadlines |
| 7 | `permit_scope_checklist_packet` | High-value regulated-industry workflow | laws, permits, registries, local procedures |
| 8 | `regulation_change_impact_packet` | Repeatable monitoring value | e-Gov law XML, gazette, notices, guidelines, public comments |
| 9 | `tax_labor_event_radar_packet` | SMB/accounting monthly workflow | NTA, eLTAX, Japan Pension Service, MHLW, labor insurance |
| 10 | `procurement_opportunity_radar_packet` | Clear ROI for vendors | p-portal, JETRO, local procurement, award data |
| 11 | `csv_monthly_public_review_packet` | Strong CSV overlay value | private derived facts + public official facts |
| 12 | `standards_certification_check_packet` | Import/product/IT/compliance value | JISC, PSE/PSC, MIC技適, CAA, PMDA, PPC, NITE |

P0/P1 split:

- P0: minimal sellable RC1 only: `Outcome Contract Catalog`, JPCIR schemas, receipts, gaps, no-hit, policy states, billing/cap contracts, four-tool GEO facade, Release Capsule, AI Execution Control Plane, and RC1 paid outcomes.
- P1: live AWS canary/full artifact factory, source expansion tied to outcome gaps, selected grants/vendor/permit/enforcement/tax-labor/procurement outputs, and local-first CSV private overlay runtime.
- P2: broad local government, gazette, courts/decisions, geospatial, standards, certifications, full evidence graph/EvidenceQL, advanced learning loops, and portfolio/competitor products.

Older `P0-B` source-expansion language is superseded. Broad source work is not P0 unless it is already tied to a P0 outcome, an explicit gap, and an accepted-artifact target.

## 4. Public source scope

The public official corpus should be broad, but only P0 where it unlocks paid outputs.

Source families:

- `corporate_identity`: NTA法人番号, NTAインボイス
- `business_registry_signal`: gBizINFO, selected registries
- `law_regulation`: e-Gov law XML/API, laws, ordinances where allowed
- `gazette_notice`: 官報, notices, announcements, public comments
- `permit_registry`: permits, registrations, standard processing periods
- `grant_program`: J-Grants, ministries, local programs, subsidies, grants
- `procurement`: procurement notices, awards, bidding eligibility
- `enforcement_disposition`: administrative dispositions, recalls, warnings, negative information
- `tax_labor_social`: NTA, eLTAX, pension, labor insurance, minimum wage, MHLW grants
- `court_dispute_decision`: courts, JFTC decisions, labor relations, administrative appeals
- `statistics_geospatial`: e-Stat, GSI, national land data, hazard, city planning, real estate data
- `standards_certification`: JIS/JISC, MIC technical conformity, PSE/PSC, food labeling, PMDA, PPC, NITE
- `local_government`: local ordinances, procedures, subsidies, permits, procurement

Required metadata for each source family:

- `source_family_id`
- `publisher`
- `official_domain`
- `access_mode`
- `terms_status`
- `robots_status`
- `license_boundary`
- `redistribution_policy`
- `staleness_ttl`
- `primary_paid_output_ids[]`
- `allowed_capture_methods[]`
- `blocked_capture_methods[]`
- `policy_state`
- `source_terms_contract_id`
- `administrative_info_class`
- `privacy_taint_level`

## 5. Algorithms

The system must generate outputs algorithmically from receipts and rules, not by free-form model assertion.

Core algorithm engine:

- Evidence graph: source profile -> source document -> source receipt -> claim ref -> packet claim.
- Decision tables: for permit, eligibility, tax/labor, and procedure checks.
- Constraint satisfaction: for grants, permits, industry requirements, deadlines, location, company facts.
- Typed score sets: public evidence attention, evidence quality, coverage gap, freshness, not generic "risk score."
- Difference detection: law XML, notices, public comments, program updates, procedure changes.
- Conflict detection: inconsistent source facts should be surfaced, not hidden.
- Gap matrix: every packet must show which source families are covered, missing, stale, blocked, policy-blocked, or deferred.

Forbidden external wording:

- `eligible`
- `safe`
- `no issue`
- `no violation`
- `permission not required`
- `credit score`
- `trustworthy`
- `proved absent`

Allowed external wording:

- `candidate_priority`
- `public_evidence_attention`
- `evidence_quality`
- `coverage_gap`
- `needs_review`
- `not_enough_public_evidence`
- `no_hit_not_absence`
- `professional_review_caveat`

## 6. CSV private overlay

CSV is valuable, but the AWS credit run must not process real user accounting CSV.

AWS credit run allowed:

- synthetic CSV fixtures
- header-only synthetic fixtures
- provider alias maps
- redacted reviewed fixtures only where no real values remain
- public official CSV from public sources
- leak scan fixtures
- formula injection tests

AWS credit run forbidden:

- real user CSV bytes
- row-level records
- raw rows
- raw/private aggregates
- private profile hashes
- suppression patterns from real users
- counterparty names, memo fields, invoice numbers, bank details, payroll/person fields

Runtime private overlay later:

- memory-only raw parsing
- tenant-private aggregate facts
- `private_overlay_receipts[]`
- `public_claim_support=false`
- external `k_min=5`
- counterparty-like facts `k_min=10`
- payroll / bank / personal identifier files rejected in P0; any later aggregate-only support requires tenant-private policy state and professional-review caveat

Public proof, JSON-LD, MCP examples, and OpenAPI examples must not contain real CSV-derived data.

## 7. Playwright / screenshot / OCR

Playwright is allowed as rendered observation for public pages, not as access bypass.

Allowed:

- public pages visible without login
- rendered tables
- official search result pages
- public PDFs/images where direct extraction is weak
- screenshot receipt with each side `<= 1600px`
- sanitized DOM
- metadata-only HAR
- OCR/Textract candidate extraction from allowed public artifacts

Forbidden:

- CAPTCHA solving
- login credential use
- proxy rotation for evasion
- stealth plugins
- residential proxies
- cookie reuse
- hidden API reverse engineering
- robots-disallowed path capture
- repeated 403/429 retry loops
- saving HAR body, cookies, auth headers, tokens, local/session storage

Capture priority:

1. official API
2. official bulk download
3. official CSV/XML/JSON/PDF
4. direct HTML fetch
5. Playwright rendered capture
6. OCR

OCR is supporting evidence only. Dates, money, corporate numbers, permit numbers, article numbers, and deadline facts require stronger source receipt or a fail-closed gap/blocked policy state.

## 8. AWS architecture

AWS must become self-running early in the live AWS phase, but only after the AI Execution Control Plane, no-op AWS command plan, spend simulator, teardown simulator, and sealed command-bundle gates pass.

Control plane:

- EventBridge Scheduler for sentinel/orchestrator ticks
- Step Functions Standard for run state
- AWS Batch for worker execution
- SQS for job handoff and backpressure
- DynamoDB control table for run state, spend line, approvals, kill switch
- CloudWatch alarms and logs with short retention
- Budgets Actions for DenyNewWork / EmergencyDenyCreates
- Lambda kill switch for drain/stop/deny triggers
- S3 temporary run bucket only
- ECR temporary worker images
- Glue/Athena temporary QA
- OpenSearch temporary benchmark only

Avoid:

- NAT Gateway unless explicitly required
- multi-region resources
- long-running OpenSearch
- QuickSight
- Support upgrade
- Marketplace subscriptions
- Savings Plans / RI
- production S3 dependency

All run resources require tags:

- `Project=jpcite`
- `Run=aws-credit-2026-05`
- `Owner=bookyou`
- `ZeroBillRequired=true`
- `Environment=credit-run`

## 9. Spend controls

The user target is now `USD 19,490` of eligible credit conversion. This is intentionally close to the `USD 19,493.94` face value, but AWS billing delay, service eligibility, taxes, and rounding mean exact settlement cannot be guaranteed by visible dashboards. The AI execution target is therefore:

```text
target_credit_conversion_usd = 19,490
cash_bill_guard = stop below target if any non-credit exposure appears
```

Cash-charge avoidance still wins over forcing the final few dollars.

Stoplines:

| Line | Visible usage | Required behavior |
|---|---:|---|
| Canary | 100-300 | Only canary, no scale |
| Watch | 17,500 | Freeze low-yield scale-up, keep only accepted-artifact lanes |
| Slowdown | 18,700 | Stop large new OCR/render/OpenSearch unless high-yield and short-tail |
| No-new-large-work | 19,200 | No new large source jobs; validate, export, cleanup, and micro-stretch only |
| Machine-gated micro-stretch | 19,200-19,450 | Only short pre-approved high-yield jobs inside sealed budget/service/source limits |
| Target close | 19,450-19,490 | Drain queues, accept completed artifacts, export, teardown preparation |
| Absolute target | 19,490 | Kill switch, deny creates, export, teardown unless stopping lower is needed to avoid cash bill |

Additional stop conditions:

- untagged spend appears
- unexpected service spend exceeds `USD 100`
- queued exposure can exceed `USD 19,490`
- Cost Explorer or billing telemetry is unavailable
- cleanup dry-run cannot enumerate resources
- source terms or robots drift to `blocked_terms_unknown` or `blocked_terms_changed`
- accepted artifact yield falls below threshold
- private data leak signal appears

## 10. One-week execution sequence

The goal is to consume the useful budget within one week where possible, without sacrificing gates.

The day labels below apply only after the future live AWS phase is explicitly opened. Before Day 0, complete section 20 steps 1-24: AI execution bootstrap, P0 contracts, Release Capsule, local RC1, no-op AWS plan, spend simulation, teardown simulation, and machine preflight.

Day -1:

- Freeze this SOT.
- Confirm AWS credit in billing console.
- Confirm service eligibility.
- Confirm account/profile/region.
- Confirm external export destination.
- Confirm production static asset path.

Day 0:

- Create guardrails, roles, permission boundaries, budgets, tags, kill switch.
- Create AWS self-running control plane.
- Run cleanup dry-run.
- Run stop drill.
- Run `USD 100-300` canary.

Day 1:

- P1 accepted-artifact backbone high-parallel run.
- NTA法人番号, NTAインボイス, e-Gov law, source_profile, receipts, no-hit ledger.
- Generate RC2/RC3 candidate packet/proof fixtures.

Day 2:

- Continue P1 backbone.
- Start outcome-gap-tied revenue-first sources.
- Grants, gBizINFO, EDINET metadata, procurement, enforcement, tax/labor public calendars.
- Start RC2 import validation.

Day 3:

- RC2 staging target.
- Validate generated proof pages, free controls, MCP facade, and agent-safe OpenAPI against the active Release Capsule contract.
- AWS continues only as an artifact factory behind production, not as runtime.

Day 4:

- Selected P1 expansion only where outcome gaps and accepted-artifact targets exist.
- Local government selected sources.
- permit/procedure pages.
- Playwright canary for approved sources only.
- OCR/Textract for allowed public PDFs.

Day 5:

- Watch/slowdown evaluation.
- Move spend to high-yield accepted-artifact jobs.
- GEO adversarial eval.
- proof page expansion.
- algorithm trace fixtures.

Day 6:

- No-new-work approach.
- Final stretch only if clean.
- Package accepted artifacts.
- Export outside AWS in slices.

Day 7:

- Final export.
- Assetization.
- Production smoke without AWS.
- Teardown start.

Day 8-14 fallback:

- Only if terms/rate/quality delays require it.
- No new work past `USD 19,490`, and stop earlier if any cash-bill risk appears.
- Finish selected source profiles, QA, export, teardown, post-teardown checks.

## 11. Release train

Production should not wait for full AWS corpus completion.

Order:

1. Contract freeze
2. AI Execution Control Plane bootstrap
3. JPCIR / policy / billing / Release Capsule contracts
4. Generated P0 agent surfaces
5. Local RC1 capsule import
6. RC1 staging
7. RC1 production without AWS runtime
8. No-op AWS command plan, spend simulation, and teardown simulation
9. Explicit live AWS phase transition
10. AWS guardrails and canary export
11. AWS standard / stretch run continues inside sealed limits
12. RC2 import/deploy through Release Capsule pointers
13. RC3 import/deploy through Release Capsule pointers
14. Final export outside AWS and outside git
15. Zero-bill teardown
16. Non-AWS-triggered post-teardown billing checks

Feature flags:

- `proof_pages.static.enabled`
- `api.packet.preview_cost.enabled`
- `api.packet.route.enabled`
- `api.packet.company_public_baseline.enabled`
- `api.packet.evidence_answer.enabled`
- `api.packet.source_receipt_ledger.enabled`
- `mcp.agent_first.enabled`
- `mcp.p0_facade.enabled`
- `mcp.full_catalog.visible`
- `billing.free_preview.enabled`
- `billing.paid_execution.enabled`
- `csv_overlay.preview.enabled`
- `csv_overlay.paid.enabled`
- `runtime.aws_dependency.allowed`

`runtime.aws_dependency.allowed=false` in production.

For P0 GEO, `mcp.p0_facade.enabled=true` and `mcp.full_catalog.visible=false` on the default agent route. Full catalog surfaces may remain expert/developer-only.

RC1:

- static proof pages
- free catalog/routing/cost preview
- limited paid `company_public_baseline`, `source_receipt_ledger`, `evidence_answer`
- MCP discovery
- agent-safe OpenAPI
- low caps

RC2:

- grants
- vendor public check
- procurement
- admin disposition
- permit checklist
- regulation change limited

RC3:

- CSV private overlay preview
- tax/labor event radar
- broad local government
- standards/certification
- geospatial selected packets
- broader proof/GEO pages

## 12. Quality gates

Fail closed. AWS artifacts are candidates until gates pass.

Gate layers:

1. `source_profile_gate`
2. `terms_robots_gate`
3. `capture_gate`
4. `receipt_gate`
5. `claim_gate`
6. `gap_coverage_gate`
7. `product_gate`
8. `privacy_gate`
9. `billing_gate`
10. `GEO_discovery_gate`
11. `production_without_AWS_gate`
12. `external_export_gate`
13. `zero_bill_teardown_gate`

Required statuses:

- `pass`
- `pass_with_warnings`
- `pass_with_known_gaps`
- `gap_artifact_only`
- `blocked_policy_unknown`
- `blocked_terms_unknown`
- `blocked_terms_changed`
- `blocked_access_method`
- `blocked_privacy_taint`
- `blocked_wording`
- `blocked_paid_leakage`
- `metadata_only`
- `link_only`
- `quarantine`
- `block`

Only `pass`, `pass_with_warnings`, and `pass_with_known_gaps` can support public paid packets. `metadata_only` and `link_only` can support navigation, not claims.

## 13. Assetization

Before deleting AWS, valuable artifacts must be exported and verified.

Export package:

- `run_manifest.json`
- `artifact_manifest.jsonl`
- `dataset_manifest.jsonl`
- `source_profiles.jsonl`
- `source_documents.jsonl`
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `known_gaps.jsonl`
- `gap_coverage_matrix.jsonl`
- `no_hit_checks.jsonl`
- `quality_gate_reports.jsonl`
- `license_terms_ledger.jsonl`
- `algorithm_traces.jsonl`
- `packet_examples/*.json`
- `proof_page_sidecars/*.json`
- `geo_eval_report.json`
- `cost_artifact_ledger.json`
- `checksum_manifest.txt`
- `cleanup_ledger.md`
- `assetization_gate_report.json`

Storage split:

| Layer | Purpose | Location policy |
|---|---|---|
| Contract assets | schemas, catalog, source profiles, pricing | repo, small only |
| Import staging | manifests and verified slices | repo/data path chosen before implementation |
| Static runtime DB | minimal deployable data | actual static path fixed by deploy pipeline |
| Local archive | large full export, raw public snapshots, screenshots, OCR evidence | outside AWS and outside git |

Do not assume `public/assets/db` exists. Final static path must be confirmed from the current deploy pipeline before implementation, likely under a `site/static/assets/db/...` equivalent or a source path that builds there.

Required export gate:

- external non-AWS destination exists
- checksums verified
- import target path fixed
- production smoke passes without AWS
- rollback assets outside AWS
- cleanup ledger generated

## 14. Zero-bill teardown

End State A is the only default:

> Zero ongoing AWS bill.

Delete in this order:

1. EventBridge schedules/rules
2. Step Functions new transitions
3. Batch queues disabled
4. Batch jobs canceled/terminated
5. Batch compute environment desired/max to zero
6. ECS/Fargate tasks
7. EC2/Spot/ASG
8. OpenSearch
9. NAT Gateway / EIP / ENI / Load Balancer
10. EBS / snapshots / AMI
11. ECR images/repositories
12. Glue databases/tables/crawlers/jobs
13. Athena outputs/workgroups
14. CloudWatch logs/dashboards/alarms
15. Lambda / SQS / DynamoDB control resources
16. Step Functions / EventBridge / S3 notifications
17. S3 object versions/delete markers/multipart uploads/buckets
18. run-specific Budgets Actions / IAM emergency policies / roles
19. final resource inventory
20. post-teardown billing checks

Post-teardown checks:

- same day
- next day
- 3 days later
- month-end or after billing finalizes

## 15. Go / No-Go

GO for AWS canary if:

- AWS account/profile/region confirmed
- credit eligibility confirmed
- AI Execution Control Plane exists
- no-op AWS command plan hash accepted
- spend simulation passes
- teardown simulation passes
- guardrails created
- cleanup dry-run passes
- export destination confirmed
- source/receipt contract frozen
- cost telemetry visible
- sealed live-AWS phase transition exists

GO for standard AWS if:

- canary under `USD 300` passes
- kill switch tested
- Step Functions / Batch / EventBridge self-run works
- `source_profile_gate` works
- no private CSV enters AWS
- `terms_robots_gate` exists
- accepted artifacts can be exported
- service risk escrows exist
- no new services, source families, or cap increases can occur during Autonomous Operator Silence Mode

GO for RC1 production if:

- production has no AWS runtime dependency
- static proof pages pass
- agent-safe OpenAPI/MCP subset passes
- pricing/cost preview/cap/idempotency pass
- forbidden phrase scan passes
- raw CSV leak scan passes
- no-hit wording scan passes
- rollback can happen without AWS

NO-GO if:

- exact `USD 19,493.94` visible usage is treated as target
- cleanup role cannot delete resources
- S3 is required for production
- public examples contain real CSV-derived data
- Playwright bypass behavior appears
- OCR-only facts are paid claims
- `eligible`, `safe`, `no issue`, `permission not required`, or generic `risk score` appear externally
- source terms are unknown but public claims are generated
- Release Capsule contains AWS runtime dependency, AWS URL, SDK/env dependency, S3 reference, raw artifact, or private data
- public surface leaks paid output beyond preview exposure budget
- agent surface recommends a higher route while a cheaper sufficient route exists
- `agent_routing_decision` is charged
- `jpcite_cost_preview` appears instead of `jpcite_preview_cost`
- `attested_zero_aws` appears while AWS factory resources are still required or present
- source/job lacks `outcome_contract_id`, `gap_id`, `accepted_artifact_target`, or teardown recipe
- live AWS command bundle exists before preflight pass
- a manual checklist is required for release
- public proof contains real CSV-derived relationship, raw screenshot archive, raw DOM/HAR/OCR text, cookies, auth material, or private fact raw values

## 16. What changed from earlier plans

Adopted corrections:

- `USD 19,490` is the target credit conversion line, not the full `USD 19,493.94` credit face value.
- AWS self-running control plane is required before full spend.
- `agent_routing_decision` is free control.
- RC1 paid set includes `company_public_baseline`.
- Source scope is broad but not all P0.
- Every source family needs `primary_paid_output_ids[]`.
- Every AWS job needs `accepted_artifact_target`.
- `eligible` is not externally displayed.
- Generic `score` is replaced by typed `score_set`.
- `gap_coverage_matrix[]` is required.
- `private-overlay bucket` wording is replaced by `csv-fixture-lab` for AWS credit run.
- Playwright is rendered observation, not bypass.
- Screenshots are receipt aids, not raw public proof payloads.
- S3 final archive is not default. It violates zero-bill.

## 17. Final smart-method addendum

The final 12-agent review changed the plan from "better sequencing" to "smarter functions." Adopt these as part of the execution SOT.

### 17.1 AWS execution brain

Replace dashboard-style spend watching with an internal control metric:

```text
control_spend_usd =
  max(cost_explorer_actual, budget_actual_or_forecast, internal_operator_ledger)
  + p95_running_cost_to_complete
  + p95_queued_cost_to_complete
  + p95_service_tail_risk
  + teardown_debt_usd
  + stale_cost_penalty
  + untagged_resource_penalty
  + ineligible_charge_uncertainty_reserve_usd
  + cleanup_reserve
  + external_export_reserve_usd
  + panic_snapshot_reserve_usd
```

Use `control_spend_usd` for stop decisions. Do not rely on visible dashboard usage alone. The practical target is `USD 19,490` eligible credit conversion, but `cash_bill_guard` overrides the target if the final corridor becomes unsafe.

Adopt:

- `Budget Token Market v2`: every AWS job reserves budget before submit.
- `Artifact Value Density Scheduler`: allocate spend by paid packet unlock, proof reuse, GEO gain, freshness, quality pass probability, and P95 cost.
- source circuit breakers: stop sources with bad terms, low accepted artifact yield, high 403/429, poor OCR quality, or low packet value.
- cost anomaly quarantine: isolate unexpected services, untagged spend, NAT/EIP/OpenSearch/log growth, or runaway queues.
- checkpoint-first workers: shard work so aborted jobs keep accepted artifacts.
- ROI-based stretch: final spend is only for short, high-value, low-abort-cost jobs.

Implementation warning: avoid double counting reserved budget tokens and P95 queued exposure. The implementation must define one authoritative exposure formula before AWS canary.

### 17.2 Source operating system

Do not just list more sources. Drive source discovery from paid output gaps.

Adopt:

- `output_gap_map`
- `source_candidate_registry`
- `capture_method_router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`
- `source_freshness_monitor`
- `source_terms_classifier`
- `Playwright canary router`
- `failed_source_ledger`

Core loop:

```text
paid output -> required claim -> output gap -> candidate source -> source_profile gate
-> capture method router -> canary -> accepted artifact yield -> expand / suppress
```

Capture method order remains:

1. official API
2. official bulk download
3. official CSV/XML/JSON/PDF
4. static HTML fetch
5. PDF text extraction
6. Playwright rendered observation
7. OCR/Textract candidate extraction
8. metadata-only / fail-closed policy gap

### 17.3 Output composer and public packet compiler

The product should not be just a set of packet endpoints.

Adopt:

- `Output Composer`: chooses the cheapest sufficient packet, bundle, follow-up question, or skip decision.
- `Public Packet Compiler`: the only component allowed to produce public packet claims.
- `decision_object`: free preview result for AI agents.
- `agent_recommendation_card`: short explanation the AI agent can show the end user.
- `workflow_recipe`: task-level product bundle.
- `question_generation`: ask only questions that unlock material packet value.
- `bundle_quote`: priced multi-packet option.
- `receipt_reuse_plan` / `Receipt Wallet`: reuse receipts to reduce price and latency.
- `delta_to_action`: convert public-source changes into action candidates.
- `evidence_graph_view`: compact proof graph for agents and proof pages.
- `agent_facing_summary`: concise, source-backed summary.

Boundary:

`Output Composer` makes purchase/execution recommendations. It must not create factual public claims. Public claims require `Public Packet Compiler`, source receipts, claim refs, known gaps, and gap coverage.

### 17.4 Agent purchase decision

Free preview should return an `agent_purchase_decision`, not only a price estimate.

Required preview fields:

- recommended action: buy, ask follow-up, use free guidance, or skip
- cheapest sufficient packet
- max price / cap token / approval token
- expected output skeleton
- known gaps before purchase
- no-hit caveat
- cheaper alternatives
- reason to buy
- reason not to buy
- `agent_recommendation_card`

Proof pages should become `agent_decision_page`s: enough evidence for an AI agent to recommend the packet, but not enough to leak the full paid output.

### 17.5 Algorithm safety upgrades

Adopt:

- proof-carrying packet compiler
- sentence-level evidence binding
- `no_hit_scope_compiler`
- explicit support levels for API, HTML, screenshot, OCR, and LLM candidate output
- hard-schema quarantine for LLM candidates
- meaning-aware forbidden phrase gate
- typed score families only

Every externally visible claim must have either receipt support or an explicit gap. Empty `known_gaps[]` alone is not enough; `gap_coverage_matrix[]` must show the scope checked.

### 17.6 Release and zero-bill assetization

Production should be controlled by verified asset bundles and pointers, not by direct AWS artifact deployment.

Adopt:

- release control plane
- transactional artifact import
- shadow release
- pointer rollback
- static DB manifest
- assetization tiers
- production smoke without AWS
- zero-bill guarantee ledger
- post-teardown cost attestations from outside AWS
- catalog drift firewall

Post-teardown checks must not rely on AWS EventBridge/Lambda that would keep billing surfaces alive.

## 18. Round 2 smart-method addendum

The second smart-method review found additional improvements. These should be treated as refinements to section 17, not as a replacement for it.

### 18.1 Product economics layer

Adopt:

- `agent_task_intake`: normalize the end user's task before selecting packets.
- `outcome_ladder`: present basic / deeper / full coverage outcomes instead of internal packet complexity.
- `coverage_ladder_quote`: show what extra source coverage each higher tier buys.
- `freshness_buyup`: let the agent decide whether a fresher paid refresh is worth it.
- `buyer_policy_profile`: encode max spend, allowed outputs, CSV policy, and required source classes.
- `watch_delta_product`: recurring delta outputs for grants, regulations, permits, vendors, tax/labor changes.
- `portfolio_batch_packet`: cheaper batch checks over many companies/vendors/programs.

This changes the sales posture from "buy this packet" to "for this task, this is the cheapest sufficient route; paying more adds these receipts."

### 18.2 Official evidence graph

Adopt:

- `Official Evidence Knowledge Graph`: an evidence graph, not a universal truth database.
- `Bitemporal Claim Graph`: distinguish observed time from legal/effective/business validity time.
- `Source Twin Registry`: model source behavior, formats, update rhythm, capture methods, quality, and terms.
- `Semantic Delta Compressor`: convert raw changes into action-level deltas.
- `Update Frontier Planner`: decide what to refresh next.
- `Claim Derivation DAG`: track how receipts become claims.
- `Conflict-Aware Truth Maintenance`: preserve conflicts instead of overwriting them.
- `Schema Evolution Firewall`: block incompatible source changes from production.
- `Reversible Entity Resolution Graph`: entity joins must remain explainable and reversible.
- `No-Hit Lease Ledger`: no-hit observations expire and are scoped.
- `Evidence Graph Compiler`: compile internal evidence into public-safe packet inputs.

Reject one global truth graph, permanent no-hit cache, screenshot-first corpus, ML/LLM source-trust decisions, and automatic schema changes in production.

### 18.3 Proof-quality math

Adopt:

- `support_state` and `support_trace[]`
- evidence support lattice
- coverage optimization
- budgeted set cover for source selection
- value-of-information decision with anti-upsell gate
- contradiction calculus
- temporal validity calculus
- interval arithmetic for dates, amounts, thresholds, and deadlines
- monotonic decision logic for no-hit and gaps
- proof minimality
- abstention/defer logic

Do not expose public eligibility probability, generic confidence score, or LLM-as-judge final truth.

### 18.4 AWS artifact factory kernel

Adopt:

- `AWS Artifact Factory Kernel`: single control kernel for run state, budget leases, jobs, artifacts, and teardown readiness.
- `Probabilistic Budget Leasing`: budget tokens become expiring leases with P95/P99 risk margins and reclaim/refund.
- `Canary Economics`: scale each source/method only after accepted artifact per dollar is measured.
- Spot-interruption-tolerant MapReduce.
- `Checkpoint Compaction`: continuously turn partial work into accepted artifacts.
- `Service-Mix Firewall`: service-level caps for NAT, OpenSearch, Textract, CloudWatch, Athena, and unknown services.
- `Teardown Simulation`: do not create a resource unless its deletion path is known.
- `Rolling External Exit Bundle`: export accepted artifacts outside AWS throughout the run.
- `Panic Snapshot`: emergency export of ledgers/manifests/accepted artifacts before teardown.
- delta-first corpus acquisition.
- failure-value ledger.
- cost-to-release critical path multiplier.
- teardown-first resource architecture.

This reframes AWS from "Batch job execution" to a short-lived, self-budgeting artifact factory.

### 18.5 Release capsule runtime

Adopt:

- `Release Capsule`: immutable unit of production activation.
- `Dual Pointer Runtime`: separate contract pointer and asset bundle pointer.
- `Capability Matrix Manifest`: tells agents what is recommendable, executable, billable, preview-only, or blocked.
- `Agent Surface Compiler`: generate `llms.txt`, `.well-known`, MCP, OpenAPI, proof pages, examples, pricing, and no-hit policy from one capsule.
- `Hot/Cold Static DB Split`: runtime stays small; audit/archive stays separate.
- `Evidence Capsule Cache`: reuse common proof-carrying assets.
- `Golden Agent Session Replay`: GEO/recommendation release gate.
- `Runtime Dependency Firewall`: block AWS URLs, SDK/env dependencies, S3 references, raw artifacts, and private data in runtime.
- `Progressive Exposure Lanes`: discovery, free decision, limited paid, and full paid can roll out independently.
- `Drift-Free Catalog Hash Mesh`: all public surfaces expose matching catalog/version hashes.
- `Privacy-Preserving Product Telemetry`: packet-level funnel events only.
- `Zero-AWS Posture Attestation Pack`: non-AWS evidence that AWS runtime is gone after teardown.

Reject live AWS lookup fallback, S3 final public archive, full paid outputs on proof pages, raw analytics logging, and schema-breaking release by pointer switch alone.

### 18.6 Trust and policy layer

Adopt:

- `Policy Decision Firewall`: central policy gate for data class, terms, visibility, proof, and packet eligibility.
- taint tracking from ingest through proof/API/MCP.
- source terms revocation graph.
- public proof minimizer.
- agent trust manifest.
- trust receipt.
- abuse prevention gate.

These additions preserve the core promise: official-source outputs without private-data leakage, access bypass, or unsupported claims.

## 19. Round3 plus 10 contradiction-killer rules

Round3 19 is the controlling contradiction-killer merge for Round3. Round3 20 remains supporting synthesis, but it did not include Round3 19 at review time. The additional 10-agent review then tightened product, policy, runtime, billing, CSV, and AWS execution boundaries.

If older sections imply broader P0 scope, manual implementation dependency, AWS canary before AI preflight, or full MCP/OpenAPI as the default GEO route, this section governs.

Non-negotiable invariants:

- GEO-first: prioritize AI-agent discovery, recommendation, consent, execution, retrieval, and explanation surfaces over SEO article volume.
- Outcome-first: public product catalog is `Outcome Contract Catalog`; packets are internal execution/API/MCP units.
- Cheapest sufficient route: agents must recommend the lowest-cost route that satisfies the user task and explain when not to buy.
- Public claims require public official evidence receipts, claim refs, known gaps, no-hit lease scope, and policy decisions.
- Request-time factual LLM generation remains disabled: `request_time_llm_fact_generation_enabled=false`.
- No-hit is scoped observation only: `no_hit_not_absence`.
- Real/private CSV never enters AWS. P0 CSV work is schema, synthetic fixtures, header-only fixtures, and leak tests only.
- AWS is a disposable artifact factory, not runtime. S3 and all run resources are deleted after external export.
- AI performs implementation, validation, local release, rollback, and future AWS execution through machine-readable gates.
- Human step-by-step implementation checklists, manual public-surface edits, and manual policy review are not SOT.
- Live AWS execution requires an explicit phase transition, accepted no-op AWS command plan hash, spend simulation pass, teardown simulation pass, active stop gates, and sealed command bundle.
- Release Capsule is the production publish unit. Public surfaces are generated from the active capsule/capability matrix.

Canonical vocabulary:

- `jpcite_preview_cost` is canonical; `jpcite_cost_preview` is invalid on public P0 surfaces.
- `agent_routing_decision` is a free control output, never a paid packet.
- `human_review_required` means end-user/professional review caveat, not developer workflow.
- `manual_review_required` in source/policy becomes `blocked_policy_unknown`, `blocked_terms_unknown`, `known_gap`, or `deferred_p1`.
- `manual_policy_review_required` is replaced by `policy_unresolved_fail_closed`.
- During AWS factory execution the posture is `zero_aws_pending`; only after external export, checksum verification, teardown, resource inventory, and production smoke without AWS may it become `attested_zero_aws`.

P0 is limited to:

- `Outcome Contract Catalog`
- JPCIR base schemas and validators
- Invariant Registry
- minimal `Policy Decision Firewall v2`
- `Source Terms Contract`
- `Administrative Information Risk Taxonomy`
- `Privacy Taint Lattice`
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
- append-only billing event ledger schema
- minimal Trust Surface Compiler
- minimal `agent_decision_page`
- Release Capsule manifest and pointer switch contract
- Capability Matrix v2
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

P0 public agent surface:

- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_execute_packet`
- `jpcite_get_packet`

P0 public paid outcomes:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`
- `invoice_vendor_public_check` only if cheap and already supported

Free controls:

- `agent_routing_decision`
- `jpcite_preview_cost`

P1 includes:

- live AWS canary and self-running standard lane
- Accepted Artifact Futures
- Budget Token Market
- Service Risk Escrow
- Source Capability Contract runtime
- Evidence Aperture Router
- Public Corpus Yield Compiler
- selected grants, permits, enforcement, tax/labor, procurement outputs
- local-first CSV private overlay runtime
- watch statement compiler and bounded delta billing
- workflow kits and receipt reuse optimization

P2 includes:

- full evidence graph DB / EvidenceQL
- broad municipality, court, standards, geospatial, and gazette corpora
- advanced learning loops
- portfolio/competitor batch products
- full legal/privacy dashboard and public correction portal

Rejected for executable plan:

- exact `USD 19,493.94` spend target
- permanent AWS archive/S3 after teardown
- production AWS runtime lookup fallback
- request-time factual LLM generation
- CAPTCHA solving, stealth/proxy scraping, or access-control bypass
- public raw screenshot/DOM/HAR/OCR archive
- public proof pages that leak paid output
- raw real CSV storage or real CSV transfer to AWS
- name-only counterparty matching in P0
- payroll/bank/person file support in P0
- charge-per-attempt billing
- uncapped autopay in RC1
- generic legal/trust/credit/safety/eligibility score
- prose-only rollback

## 20. Immediate implementation order after this plan

Do not run live AWS until steps 1-24 are complete and machine gates pass.

1. Freeze minimal `Outcome Contract Catalog`.
2. Freeze P0 packet envelope.
3. Define JPCIR base header and P0 record schemas.
4. Implement Invariant Registry.
5. Implement minimal `Policy Decision Firewall v2`.
6. Implement `Source Terms Contract`, `Administrative Information Risk Taxonomy`, and `Privacy Taint Lattice`.
7. Implement no-hit, known gaps, and `gap_coverage_matrix[]` contracts.
8. Implement source receipt and claim ref validators.
9. Implement minimal Public Packet Compiler.
10. Implement minimal Agent Decision Protocol.
11. Implement canonical `jpcite_preview_cost`.
12. Implement Consent Envelope and versioned Scoped Cap Token schemas.
13. Implement Accepted Artifact Pricing and billing outcome decision schemas.
14. Implement minimal Trust Surface Compiler and `agent_decision_page`.
15. Implement Release Capsule manifest, Capability Matrix v2, and pointer switch contract.
16. Implement Surface Parity Checker.
17. Implement Forbidden Language Linter.
18. Implement minimal Golden Agent Session Replay.
19. Implement AI Execution Control Plane bootstrap and execution graph.
20. Implement no-op AWS command plan compiler.
21. Implement AWS artifact contract schemas, spend simulator, and teardown simulator.
22. Run local release gates: policy, privacy, proof leakage, billing, no-hit, forbidden wording, and surface parity.
23. Ship RC1 capsule without AWS runtime dependency.
24. Enter live AWS phase only after explicit phase transition and machine preflight pass.
25. Run AWS canary.
26. Start self-running AWS standard lane only inside sealed budget/service/source limits.
27. Import RC2/RC3 bundles through Release Capsule pointers.
28. Export final artifacts outside AWS and outside git.
29. Teardown AWS to zero-bill posture.
30. Produce non-AWS-triggered post-teardown attestations.

AWS spend rule:

```text
maximize accepted artifact value toward USD 19,490 eligible credit conversion, while cash_bill_guard can stop lower
```

`control_spend_usd` must include observed spend, max(job reservation remaining, p95 job remaining), service tail risk, teardown debt, stale-cost penalty, untagged resource penalty, ineligible charge uncertainty reserve, cleanup reserve, external export reserve, and panic snapshot reserve.

Post-teardown attestations must not depend on AWS EventBridge, Lambda, S3, CloudWatch, or any AWS runtime service kept alive for the attestation.

## 21. Reference plan documents

Primary inputs:

- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `docs/_internal/aws_final_12_review_integrated_smart_methods_2026-05-15.md`
- `docs/_internal/aws_smart_methods_round2_integrated_2026-05-15.md`
- `docs/_internal/aws_smart_methods_round3_plus10_integrated_2026-05-15.md`
- `docs/_internal/aws_smart_methods_round3_19_contradiction_killer.md`
- `docs/_internal/aws_smart_methods_round3_20_final_merge_sot.md`
- `docs/_internal/aws_final_consistency_10_final_sot.md`
- `docs/_internal/aws_final_consistency_01_global.md`
- `docs/_internal/aws_final_consistency_02_aws_autonomous_billing.md`
- `docs/_internal/aws_final_consistency_03_source_scope.md`
- `docs/_internal/aws_final_consistency_04_revenue_packets_pricing.md`
- `docs/_internal/aws_final_consistency_05_algorithm_safety.md`
- `docs/_internal/aws_final_consistency_06_release_train.md`
- `docs/_internal/aws_final_consistency_07_csv_privacy_security.md`
- `docs/_internal/aws_final_consistency_08_playwright_terms.md`
- `docs/_internal/aws_final_consistency_09_post_aws_assets.md`
- `docs/_internal/aws_scope_expansion_25_fast_spend_scheduler.md`
- `docs/_internal/aws_scope_expansion_26_data_quality_gates.md`
- `docs/_internal/aws_scope_expansion_27_packet_taxonomy.md`
- `docs/_internal/aws_scope_expansion_28_production_release_train.md`
- `docs/_internal/aws_scope_expansion_29_post_aws_assetization.md`

Earlier review and expansion documents remain as supporting detail, but this file is the execution SOT.
