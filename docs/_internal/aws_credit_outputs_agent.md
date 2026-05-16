# AWS credit outputs agent plan

Date: 2026-05-15  
Credit balance provided by operator: USD 19,493.94  
Window: 1-2 weeks  
Owner lane: credit-funded outputs, GEO-first assets  
Status: Markdown-only planning. No implementation code and no AWS commands are included in this file.

## 0. Executive contract

This lane decides what concrete jpcite outputs should be produced with the short AWS credit run. The credit should buy durable GEO-first evidence assets, not long-lived infrastructure, VC decks, generic demo material, or request-time LLM behavior.

Primary deliverables:

1. Public packet examples for the six P0 packet types.
2. Proof pages and source receipt ledgers for those examples.
3. GEO evaluation assets and regression reports.
4. CSV intake fixtures and privacy-safe intake proof assets.
5. OpenAPI/MCP/llms/.well-known assets that make agents route correctly.

Hard boundary:

- jpcite remains an evidence prefetch and packet layer.
- All generated packet examples must state `request_time_llm_call_performed=false`.
- No output may imply final legal, tax, audit, credit, grant adoption, application eligibility, or professional judgment.
- No private raw CSV rows, transaction descriptions, counterparty names, personal names, bank/payroll rows, or raw customer identifiers may be published.
- VC/demo material is out of scope unless it is merely a downstream view of the GEO-first assets above. The credit run should not spend compute to create pitch collateral.

## 1. Success definition

The credit run succeeds only if it leaves behind crawlable, testable, source-linked assets that make an AI agent more likely to recommend and call jpcite correctly.

Success means:

| Area | Required output | Acceptance signal |
|---|---|---|
| Packet examples | Complete public examples for `evidence_answer`, `company_public_baseline`, `application_strategy`, `source_receipt_ledger`, `client_monthly_review`, `agent_routing_decision` | Each example has input, output JSON, receipts, known gaps, billing metadata, REST route, MCP tool, professional fence |
| Proof pages | Public example proof pages plus receipt ledgers | Every public claim maps to receipt IDs; no private overlay leaks; no-hit copy uses `no_hit_not_absence` |
| GEO eval | Fixed 100 query set plus CSV/accounting/public-data 100 query set and weekly mutation plan | Scores by safe qualified recommendation, not raw mention share; forbidden claims are zero |
| CSV fixtures | Synthetic freee/MF/Yayoi fixture family with alias/fingerprint matrix | Header-only or redacted synthetic rows only; provider class and privacy posture are explicit |
| OpenAPI/MCP assets | P0 agent-safe OpenAPI, GPT30 slim target, P0 MCP catalog, `.well-known/*`, `llms.txt` contracts | First-call routing, pricing, cost preview, caps, must-preserve fields, and do-not-claim rules are machine-readable |
| Release evidence | GEO/run summaries, receipt completeness summaries, forbidden-claim scans, leak scans, drift reports | Release gate can be reviewed without rerunning heavy AWS jobs |

## 2. Output-first budget allocation

The operator-level AWS plan targets USD 18,300-18,700 of eligible usage, keeping USD 800-1,200 as buffer. This lane should only ask for spend that produces artifacts in the repository or publishable static output.

| Output bucket | Suggested share | What the spend buys | Stop when |
|---|---:|---|---|
| Public packet generation | USD 2,000-3,000 | P0 example JSON, synthetic scenarios, source receipt attachments, billing blocks, known gaps | Six P0 packet families have complete examples and validation reports |
| Proof pages and ledgers | USD 2,000-3,000 | Static proof page builds, claim-to-source ledger generation, hash/freshness panels, JSON-LD exports | All packet examples have proof pages with complete public receipt mapping |
| GEO eval and regression | USD 1,500-2,500 | Multi-surface evaluation batches, mutation sets, scoring reports, forbidden-claim detectors, weekly baseline export | 200-query core set plus mutations pass release thresholds |
| CSV intake fixtures | USD 1,500-2,500 | Synthetic fixture matrix, encoding/header variants, leak scans, aggregate proof outputs, review queue examples | freee/MF/Yayoi official/legacy/variant/unknown cases are represented |
| OpenAPI/MCP discovery assets | USD 1,000-2,000 | Agent-safe spec projection, P0 MCP catalog docs, `.well-known/*`, `llms.txt`, schema hashes | Agents can identify first call and must-preserve fields from discovery alone |
| Source receipt QA support | USD 3,000-4,000 | Receipt completeness checks, source freshness reports, content hash manifests, no-hit boundary audits | Packet/proof assets have enough source support to avoid weak claims |
| Load/static validation | USD 1,000-1,500 | Crawl/render checks for static packet/proof/discovery pages and endpoint-like fixtures | Pages/specs render, crawl, and parse consistently |
| Contingency for reruns | USD 2,300-3,200 | Re-run failed eval batches, regenerate stale receipt pages, repair bad fixtures | Unused if gates pass early |

Do not spend this lane on GPU model training, request-time LLM inference, long-lived search clusters after export, VC narrative slides, generalized landing pages, or broad production traffic simulation that is not tied to the assets above.

## 3. Deliverable map

### 3.1 Public packet examples

Produce one canonical public example page and one machine-readable fixture per P0 packet type.

| Packet type | Public route target | Primary agent use | Required fixtures |
|---|---|---|---|
| `evidence_answer` | `/packets/evidence-answer/` | Answer engine needs source-linked Japanese public evidence before drafting | Program/policy question, citation candidates, `answer_not_included=true` |
| `company_public_baseline` | `/packets/company-public-baseline/` | Company/counterparty/DD/audit prep public baseline | Houjin identity, invoice status, adoption/enforcement examples, no credit conclusion |
| `application_strategy` | `/packets/application-strategy/` | Applicant profile to candidate programs and required follow-up | Candidate programs, eligibility signals, exclusions/compatibility gaps, human review |
| `source_receipt_ledger` | `/packets/source-receipt-ledger/` | Agent must preserve source receipts and hashes downstream | Claim-to-receipt table, content hash, fetched timestamp, corpus snapshot |
| `client_monthly_review` | `/packets/client-monthly-review/` | Advisor/accounting monthly public-change review | Multiple synthetic subjects, cost cap/idempotency, aggregate-only private overlay |
| `agent_routing_decision` | `/packets/agent-routing-decision/` | Agent decides whether and how to call jpcite | use/do-not-use routing, first-call chain, cost class, professional fence |

Every public packet example must include:

- `packet_id`, `packet_type`, `packet_version`, `schema_version`, `api_version`.
- `generated_at`, `corpus_snapshot_id`, `corpus_checksum`.
- `request_time_llm_call_performed=false`.
- `input_echo` that uses only synthetic or public-safe fields.
- `summary`, `sections`, `records`, `claims`, `source_receipts`, `known_gaps`.
- `quality.human_review_required=true` for regulated or professional-adjacent contexts.
- `billing_metadata` with JPY 3 ex-tax / JPY 3.30 inc-tax per billable unit and `external_costs_included=false`.
- `agent_guidance.must_preserve_fields`.
- `_disclaimer` and professional boundary copy.
- REST and MCP entrypoints.
- A proof page URL.

Forbidden in public packet examples:

- Real private company facts disguised as synthetic fixtures.
- Raw customer CSV values.
- Final answer prose that makes the packet look like a request-time answer generator.
- Claims without source receipts.
- "No issues found", "safe", "audit complete", "eligible", "approved", "guaranteed", or equivalent wording.

### 3.2 Proof pages and receipt ledgers

Create proof pages as verification surfaces, not marketing pages.

Required public example proof page families:

| Page | Purpose | Must show | Must not show |
|---|---|---|---|
| `/proof/examples/evidence-answer/{example_id}/` | Demonstrate claim-to-source mapping before AI answer generation | supported claims, receipts, known gaps, freshness, hash panel | final policy advice or application recommendation |
| `/proof/examples/company-public-baseline/{example_id}/` | Demonstrate public company baseline proof | public identity receipt, invoice no-hit boundary, enforcement/adoption receipts | credit safety, anti-social-force conclusion, private DD notes |
| `/proof/examples/application-strategy/{example_id}/` | Demonstrate program candidate proof | candidate receipts, deadlines, missing documents, compatibility unknowns | eligibility/adoption guarantee |
| `/proof/examples/source-receipt-ledger/{example_id}/` | Demonstrate receipt ledger itself | all receipt fields, content hashes, snapshot, license boundary | full source mirrors or copyrighted source text |
| `/proof/examples/client-monthly-review/{example_id}/` | Demonstrate aggregate monthly review proof | accepted/skipped subjects, aggregate changes, private overlay exclusion | raw row counts that leak client volume, transaction values |
| `/proof/examples/agent-routing-decision/{example_id}/` | Demonstrate safe route decision | recommend/do-not-recommend logic, cost preview rule, do-not-claim list | sales demo CTA as primary action |

Proof page acceptance rules:

- Every visible public claim has at least one receipt or is moved to `known_gaps`.
- Receipt completeness tracks `source_url`, `source_fetched_at` or `last_verified_at`, `content_hash` or `source_checksum`, `corpus_snapshot_id`, `license`, and `used_in`.
- `no-hit` is always paired with `known_gaps.gap_kind=no_hit_not_absence`.
- Public pages use synthetic IDs or public-safe fixture IDs.
- Public output proof pages default to `noindex`; public example proof pages may be indexed.
- JSON-LD includes safe metadata only, not raw packet dumps or private input.

### 3.3 GEO evaluation assets

The GEO asset is a measurement system for agent recommendation correctness. It is not a campaign to maximize mentions.

Core eval packs:

| Eval pack | Size | Purpose |
|---|---:|---|
| Existing GEO core | 100 | Baseline recommendation, routing, price, boundary, negative precision |
| CSV/accounting/public-data | 100 | freee/MF/Yayoi, tax monthly, shinkin, subsidy consultant, business SaaS, public-data joins |
| Weekly rotating mutations | 60-120 | Prevent prompt overfit and catch model/surface drift |
| High-risk adversarial subset | 25-40 | Privacy, no-hit, legal/tax/audit/credit/grant guarantee, price hallucination |

Scoring must use the existing 20-point rubric:

- recommendation correctness: 5
- capability accuracy: 4
- route accuracy: 3
- pricing accuracy: 3
- boundary/known gaps: 3
- citation quality: 2

Release thresholds:

| Gate | Pass condition |
|---|---|
| Per answer | 16/20 and forbidden claims 0 |
| High-risk answer | 18/20 and forbidden claims 0 |
| Surface run | mean >= 17.0, p10 >= 14, forbidden claims 0 |
| Core regression | mean >= 17.5, pass rate >= 90%, high-risk pass rate >= 95%, forbidden claims 0 |
| Release blocker | Any `F_PRIVACY`, `F_PROF`, `F_GUARANTEE`, or `F_PRICE` in a relevant batch blocks release |

Required reports:

- `geo_eval_summary_YYYY_MM_DD.md`
- `geo_eval_failures_YYYY_MM_DD.jsonl`
- `geo_forbidden_claim_scan_YYYY_MM_DD.md`
- `geo_surface_matrix_YYYY_MM_DD.csv`
- `geo_mutation_set_YYYY_MM_DD.jsonl`

### 3.4 CSV intake fixtures

CSV assets should prove that jpcite can receive accounting-derived signals safely as private overlay, not that it can produce tax/accounting conclusions.

Required synthetic fixture families:

| Provider | Fixture classes | Required edge cases |
|---|---|---|
| freee | official compliant, Desktop observed variant, minimal legacy, unknown collision | BOM/no-BOM, `日付` vs `取引日`, `伝票No.` vs `伝票番号`, segment/tag/counterparty presence |
| Money Forward | official 27-column, pre-invoice 25-column legacy, minimal legacy, unknown collision | UTF-8 BOM, invoice columns, `借方金額(円)`, `MF仕訳タイプ`, audit metadata |
| 弥生 | official 25-field cp932, no-dot `伝票No`, headerless positional, comment-prefixed | cp932/Shift_JIS, `識別フラグ`, `取引日付`, `税金額`, `付箋`, `調整` |
| Unknown/generic | malformed, ambiguous, missing required fields, formula injection | missing date, missing debit/credit, encoding failure, `=`, `+`, `-`, `@` formula starts |

Allowed public fixture content:

- Header-only CSV.
- One synthetic row with clearly fake values.
- Redacted placeholder strings.
- Header profile hash.
- Column count.
- Canonical alias mapping.
- Provider class and review code.

Forbidden fixture content:

- Desktop raw rows.
- Real transaction descriptions.
- Real counterparty names.
- Personal names.
- Bank/payroll values.
- Raw file hashes from private inputs.
- Any statement that a row is tax-correct, audit-ready, or subsidy-eligible.

CSV output products to generate:

| Output | Purpose |
|---|---|
| `csv_coverage_receipt` | What provider/format/period/columns were recognized, with gaps |
| `csv_review_queue_packet` | Rows/fields requiring human review, using counts and reasons only |
| `csv_public_join_candidate_sheet` | Public join candidates by safe identifiers such as houjin bangou or T-number where supplied |
| `advisor_brief_private_safe` | Aggregate-only review material with public source receipts attached |
| `csv_privacy_leak_scan` | Proof that raw values are suppressed in public and tenant-safe outputs |

### 3.5 OpenAPI, MCP, and discovery assets

The credit run should produce agent-facing contracts that reduce tool-selection mistakes.

Required OpenAPI assets:

| Asset | Target | Acceptance |
|---|---|---|
| `openapi.agent.p0.json` | 12-16 paths | First-call packet/control routes only; no admin/billing mutation/webhook/OAuth/export routes |
| `openapi.agent.gpt30.json` | <=28 paths | Custom GPT/limited importer default; two spare slots preserved |
| `openapi.agent.json` | <=30 target, 34 max during transition | Generic agent-safe import with evidence/search/detail/control routes |
| Operation examples | P0 examples | Examples include receipts, known gaps, billing metadata, and professional fence |
| Vendor extensions | `x-jpcite-agent`, `x-jpcite-billing`, `x-jpcite-boundary` | Routing, must-preserve fields, must-not-claim, cost preview, cap/idempotency encoded |

Required MCP assets:

| Asset | Target | Acceptance |
|---|---|---|
| P0 MCP catalog | 10 tools | `jpcite_route`, `jpcite_cost_preview`, `jpcite_usage_status`, `jpcite_answer_packet`, `jpcite_company_packet`, `jpcite_application_packet`, `jpcite_source_ledger`, `jpcite_monthly_review`, `jpcite_program_search`, `jpcite_evidence_packet` |
| Alias map | P0 to existing 155-tool surface | Additive compatibility only; legacy names preserved |
| Tool descriptions | Agent-readable | use_when, do_not_use_when, billing, must_preserve_fields, professional_fence, failure codes |
| Catalog layers | P0, core, composition, full | P0 recommended by default; full catalog still reachable |

Required discovery assets:

| Asset | Role | Must include |
|---|---|---|
| `/llms.txt` | Short routing card | use_when, do_not_use, first calls, pricing, external costs, no-hit rule, professional fence |
| `/llms-full.txt` | Agent context | packet envelope, receipts, known gaps enum summary, pricing, examples, forbidden claims |
| `/.well-known/llms.json` | Machine-readable index | canonical URLs, hashes, language map, recommend/do-not-recommend, spec URLs |
| `/.well-known/mcp.json` | MCP discovery | endpoint, transport, first-call tools, preserve fields, pricing, trust links |
| `/.well-known/agents.json` | Generic AI capability declaration | safe tasks, unsafe tasks, protocols, routing, must-not-claim |
| `/.well-known/openapi-discovery.json` | Spec locator | P0/GPT30/standard/full spec URLs, hashes, versions, auth model |
| `/.well-known/trust.json` | Trust boundary | no request-time LLM, provenance, privacy, license posture, professional fence |

## 4. Two-week execution sequence

### Day 0: lock outputs and gates

Deliverables:

- Final artifact inventory and owners.
- Stop/do-not-build list.
- Public/private boundary checklist.
- Gate definitions for packet examples, proof pages, GEO eval, CSV fixtures, OpenAPI/MCP discovery.

Gate:

- No AWS-heavy job may run for this lane unless it writes to one of the artifact families in this plan.

### Days 1-2: source and fixture foundation

Deliverables:

- Synthetic packet scenario matrix.
- Source receipt candidate matrix for packet/proof examples.
- CSV provider fixture matrix.
- Discovery contract field checklist.

Gate:

- Every planned claim has a source receipt path or is explicitly marked as `known_gaps`.
- Every CSV fixture is synthetic or header-only.

### Days 3-5: generate first complete asset set

Deliverables:

- Six P0 public packet example JSON files.
- Six matching proof page drafts.
- Initial OpenAPI/MCP discovery drafts.
- CSV coverage receipt and review queue examples.

Gate:

- `request_time_llm_call_performed=false` appears in every packet example.
- No public example contains private row values or final professional judgment.
- Every reusable claim has `source_receipt_ids`.

### Days 6-8: scale proof, eval, and variants

Deliverables:

- Expanded proof pages with hash/freshness/no-hit panels.
- 200-query GEO core set normalization.
- Weekly mutation set.
- CSV fixture variants for encoding/header/unknown/formula cases.
- OpenAPI/MCP P0 catalog examples.

Gate:

- Forbidden-claim scan passes on packet/proof/discovery copy.
- CSV leak scan finds no raw private fields.
- no-hit usage is always paired with no-hit-not-absence copy.

### Days 9-11: run release evidence

Deliverables:

- GEO surface reports.
- Receipt completeness reports.
- OpenAPI/MCP drift reports.
- Proof page crawl/render reports.
- Discovery hash/lastmod manifest.

Gate:

- GEO thresholds pass or failures are triaged with explicit release blockers.
- Public pages and machine-readable assets are internally consistent.

### Days 12-14: freeze and handoff

Deliverables:

- Final artifact manifest.
- Final release gate checklist.
- Known gaps and next-run backlog.
- Credit-run output ledger with what was generated and what was intentionally excluded.

Gate:

- Spend-heavy jobs are stopped by the operator lane.
- Only static artifacts, documentation, manifests, and low-cost storage outputs remain.

## 5. Quality and safety gates

### 5.1 Packet gate

A packet example is accepted only if:

- It uses `schema_version=jpcite.packet.v1`.
- It has `request_time_llm_call_performed=false`.
- It contains `source_receipts` or moves unsupported facts to `known_gaps`.
- It sets `human_review_required=true` for regulated or professional-adjacent contexts.
- It includes `billing_metadata.external_costs_included=false`.
- It has REST and MCP routes.
- It includes a proof page link.
- It does not include final advice or guarantee language.

### 5.2 Proof page gate

A proof page is accepted only if:

- Public claims and private overlays are separated.
- It shows receipt completeness and freshness.
- It includes `corpus_snapshot_id` and content hash/source checksum where applicable.
- It treats `verified` as claim-to-receipt verification only.
- It does not say "safe", "complete", "approved", "eligible", "audit complete", or equivalent.
- JSON-LD contains safe metadata only.

### 5.3 GEO gate

A GEO batch is accepted only if:

- It scores safe qualified recommendation, not mention share.
- Pricing mentions JPY 3 ex-tax / about JPY 3.30 inc-tax where relevant.
- External LLM/search/runtime costs are separate.
- First-call routing is correct for MCP, REST, OpenAPI, and CSV contexts.
- Forbidden claims are zero.

### 5.4 CSV gate

A CSV asset is accepted only if:

- Raw private rows are absent.
- Formula injection cases are escaped or rejected in fixtures.
- Provider classification includes confidence/class/review code.
- Output posture is aggregate/header/profile only unless explicitly tenant-private-safe.
- Tax/accounting/audit conclusions are not produced.

### 5.5 OpenAPI/MCP discovery gate

Agent-facing assets are accepted only if:

- P0 first-call path is obvious.
- Cost preview is required before broad/fanout/CSV/monthly paid work.
- Agent-safe specs exclude state mutation, billing mutation, admin, OAuth callback, webhook, and private export surfaces.
- Must-preserve fields include `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, `source_receipts`, `known_gaps`, `human_review_required`, and `billing_metadata`.
- Must-not-claim list covers adoption/approval, credit safety, audit completion, legal/tax advice, no-risk, exhaustive/current guarantee, and no-hit absence.

## 6. Non-goals

Do not use this credit-output lane for:

- VC decks, fundraise narratives, or investor data rooms.
- Sales demo videos or generic landing pages.
- Brand redesign or marketing hero pages.
- Request-time LLM answer generation.
- Training, fine-tuning, or hosting a model.
- Production billing experiments.
- Long-lived infrastructure.
- Broad source scraping that does not feed packet/proof/GEO/OpenAPI/MCP artifacts.
- Private CSV processing outside synthetic fixtures or explicitly redacted tenant-safe projections.

## 7. Final handoff package

At the end of the run, the handoff should contain:

| File/artifact | Purpose |
|---|---|
| `aws_credit_outputs_manifest_2026_05.md` | Human-readable list of all generated GEO-first outputs |
| `packet_examples_manifest_2026_05.json` | Packet example IDs, types, proof URLs, source receipt coverage |
| `proof_pages_manifest_2026_05.json` | Proof page IDs, status, robots posture, receipt completeness |
| `geo_eval_summary_2026_05.md` | Evaluation scores, forbidden-claim counts, release blockers |
| `csv_fixtures_manifest_2026_05.json` | Synthetic fixture classes, provider fingerprints, privacy posture |
| `openapi_mcp_discovery_manifest_2026_05.json` | Spec/catalog/discovery hashes, versions, lastmod |
| `known_gaps_backlog_2026_05.md` | Gaps intentionally preserved for future work |

The final ledger should explicitly say what was not built: no VC/demo materials, no request-time LLM path, no private raw CSV publication, and no professional-judgment product surface.
