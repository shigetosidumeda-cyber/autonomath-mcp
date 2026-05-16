# OpenAPI agent-safe subset design deep dive

Date: 2026-05-15  
Owner lane: OpenAPI agent-safe subset design  
Status: pre-implementation planning only. Do not treat this as shipped behavior until accepted.  
Constraint: documentation-only planning. No runtime implementation, generated OpenAPI, site asset, test, or application code is changed by this file.

## 0. Executive contract

jpcite の REST surface は full public OpenAPI で 306 paths あるが、AI agent に最初から見せるべき面はそれではない。Agent-safe OpenAPI は、AI が「どれを呼ぶか」で迷わず、費用・業法・根拠保持を破らず、最終回答前に evidence を取るための小さい contract とする。

Primary contract:

- Full OpenAPI は developer / SDK / backend integration 用の complete public contract。
- Agent-safe OpenAPI は ChatGPT Actions、function calling、answer engine、low-context agent import 用の safe facade。
- P0 は 12-16 paths に絞り、agent が最初の 1 call を選べる状態にする。
- GPT 30 path 対応は別 spec として 28 paths 以下を hard budget にする。残り 2 slots は緊急追加・compatibility 用に空ける。
- Agent-safe endpoint は read-oriented / evidence-oriented / bounded-cost / stable-schema / professional-fence-ready のものだけを含める。
- Billing / OAuth / webhook / admin / export / dashboard / integration mutation / account mutation / broad batch は full OpenAPI に残し、agent-safe から除外する。
- Every agent-safe operation description must encode routing, fence, cost, no-hit, and must-preserve rules in language an AI can follow.

Primary design question:

> Can a Custom GPT or generic AI agent import one small OpenAPI spec, decide the correct first endpoint, preview cost when needed, preserve source receipts and known gaps, and avoid final legal/tax/audit/credit/application claims?

If not, the subset is too large, too raw, or missing operation-level instructions.

## 1. Source snapshot checked

This pass checked repository artifacts only and used OpenAI official developer docs for current GPT Actions setup shape.

| Source | Observed fact used here |
|---|---|
| `docs/openapi/v1.json` | Full public OpenAPI snapshot contains 306 paths. |
| `docs/openapi/agent.json` | Current checked agent snapshot contains 34 paths. |
| `src/jpintel_mcp/api/openapi_agent.py` | Code-side projection contains explicit `AGENT_SAFE_PATHS`, route priorities, billing metadata, first-hop policy, evidence packet policy, must-preserve fields, and must-not-claim rules. |
| `tests/test_openapi_agent.py` | Tests assert agent-safe excludes billing/OAuth/admin-like surfaces and includes agent metadata for priority, route purpose, billing, cost preview, company first hop, evidence packet, advisor handoff, and professional fences. |
| `docs/for-agent-devs/why-bundle-jpcite_2026_05_11.md` | Public agent-dev copy already positions `openapi.agent.json` as 34 paths and mentions a 30-path slim variant for Custom GPT. |
| OpenAI GPT Actions getting-started docs | Current official flow has builders paste an OpenAPI schema into Actions, then write instructions that reference action names and parameters. Operation names, descriptions, and instructions therefore matter directly for routing. The official docs checked here did not provide a stable public path-count guarantee, so the 30-path budget is treated as a jpcite compatibility target, not as an OpenAI-sourced invariant. |

## 2. Recommended published spec layers

Do not publish a single "agent spec" and let every surface fight over it. Publish layers with explicit budgets and audiences.

| Layer | URL / file | Path budget | Audience | Purpose |
|---|---|---:|---|---|
| P0 strict | `openapi.agent.p0.json` | 12-16 | live agents, docs examples, registry reviewers | First-call routing and safe packet execution only. |
| GPT30 slim | `openapi.agent.gpt30.json` | <=28 | ChatGPT Custom GPT Actions and other limited importers | Fits conservative path budgets with 2 spare slots. |
| Agent standard | `openapi.agent.json` | <=34 for now, target <=30 | general AI import, function calling, answer engines | Small safe subset with core domain primitives. |
| Full public | `openapi.json` / `v1.json` | complete public surface | SDK, backend, Postman, internal QA | All public REST routes except private/admin/internal. |
| Internal/admin | not public or separate authenticated docs | no agent import | operator and product admin | Billing mutation, dashboards, webhooks, OAuth, exports, integration setup. |

Decision: P0 docs and Custom GPT setup should recommend GPT30 slim, not the 34-path standard spec. The 34-path spec can remain for richer agent surfaces, but it should not be the default for ChatGPT Actions.

## 3. P0 strict endpoint list

P0 strict is the list an agent should see first. The goal is not domain completeness; it is reliable first-call behavior.

### 3.1 P0 strict target

| # | Method | Path | Operation name | Agent role | Include rationale |
|---:|---|---|---|---|---|
| 1 | `POST` | `/v1/cost/preview` | `previewCost` | Cost preflight | Free control endpoint before broad/repeated/fanout/uncertain paid work. |
| 2 | `GET` | `/v1/usage` | `getUsageStatus` | Quota preflight | Lets anonymous or key users avoid failing mid-session. |
| 3 | `GET` | `/v1/meta/freshness` | `getMetaFreshness` | Freshness check | Lets agent inspect corpus recency before making freshness-sensitive claims. |
| 4 | `GET` | `/v1/intelligence/precomputed/query` | `prefetchIntelligence` | Compact first pass | Best low-friction answer prefetch for Japanese public evidence tasks. |
| 5 | `POST` | `/v1/evidence/packets/query` | `queryEvidencePacket` | Evidence before answer | Core route for source-linked facts, known gaps, and decision insights. |
| 6 | `GET` | `/v1/evidence/packets/{subject_kind}/{subject_id}` | `getEvidencePacket` | Resolved subject evidence | Safe detail route after agent has a known program/houjin subject. |
| 7 | `POST` | `/v1/artifacts/company_public_baseline` | `createCompanyPublicBaseline` | Japanese company first hop | First call for company/counterparty/client-folder/DD/audit prep. |
| 8 | `POST` | `/v1/artifacts/company_folder_brief` | `createCompanyFolderBrief` | Company follow-up | Converts baseline evidence into folder-ready public briefing without final judgment. |
| 9 | `POST` | `/v1/artifacts/company_public_audit_pack` | `createCompanyPublicAuditPack` | Audit/DD follow-up | Public-record workpaper input with explicit no statutory audit fence. |
| 10 | `GET` | `/v1/programs/search` | `searchPrograms` | Lightweight program discovery | Cheap candidate discovery when user has not provided enough profile for packet execution. |
| 11 | `POST` | `/v1/programs/prescreen` | `prescreenPrograms` | Profile-to-program screen | Candidate ranking with fit/gap fields; not final eligibility. |
| 12 | `GET` | `/v1/programs/{unified_id}` | `getProgram` | Program detail | Detail only after `searchPrograms` or `prescreenPrograms` returns a real ID. |
| 13 | `GET` | `/v1/source_manifest/{program_id}` | `getSourceManifest` | Program source ledger | Citation/provenance follow-up for a selected program. |
| 14 | `POST` | `/v1/citations/verify` | `verifyCitations` | Optional citation check | Verify URL/claim pairs before final answer when citations will be shown. |
| 15 | `GET` | `/v1/advisors/match` | `match_advisors_v1_advisors_match_get` | Evidence-to-expert handoff | Only after evidence/gaps exist; candidates, not completed referral or professional review. |

P0 strict target is 15 paths. That is small enough for Custom GPT, Claude/Cursor function routing, docs snippets, and registry manifests.

### 3.2 P0 packet facade preference

Where implementation allows, prefer packet facades over raw primitives:

| Desired P0 facade | Current/near equivalent | Why |
|---|---|---|
| `POST /v1/packets/evidence-answer` | `/v1/evidence/packets/query` | More explicit that jpcite returns evidence, not final prose. |
| `POST /v1/packets/company-public-baseline` | `/v1/artifacts/company_public_baseline` | Naming consistency across MCP/REST. |
| `POST /v1/packets/application-strategy` | `/v1/programs/prescreen` plus artifact route when shipped | Better than asking agents to chain raw search/detail. |
| `POST /v1/packets/source-receipt-ledger` | `/v1/source_manifest/{program_id}` plus packet receipts | More general than program-only source manifest. |
| `POST /v1/packets/expert-handoff` | `/v1/advisors/match` plus evidence packet summary | Keeps handoff bounded by evidence and gaps. |

Do not block P0 on renaming. If facade routes are not shipped, publish current stable routes with operation descriptions that state the intended agent role.

## 4. GPT30 slim endpoint list

GPT30 slim should be the default Custom GPT Action import. Keep it at 28 paths maximum.

### 4.1 GPT30 recommended 28

| Group | Method | Path | Include condition |
|---|---|---|---|
| Control | `POST` | `/v1/cost/preview` | Always. |
| Control | `GET` | `/v1/usage` | Always. |
| Control | `GET` | `/v1/meta/freshness` | Always. |
| Evidence | `GET` | `/v1/intelligence/precomputed/query` | Always. |
| Evidence | `POST` | `/v1/evidence/packets/query` | Always. |
| Evidence | `GET` | `/v1/evidence/packets/{subject_kind}/{subject_id}` | Always. |
| Citation | `POST` | `/v1/citations/verify` | Always. |
| Company | `GET` | `/v1/houjin/{bangou}` | Include because Japanese company routing often starts from 法人番号. |
| Company | `POST` | `/v1/artifacts/company_public_baseline` | Always. |
| Company | `POST` | `/v1/artifacts/company_folder_brief` | Include for folder-ready output. |
| Company | `POST` | `/v1/artifacts/company_public_audit_pack` | Include for DD/audit prep with fence. |
| Invoice | `GET` | `/v1/invoice_registrants/search` | Include for invoice/T-number workflows. |
| Invoice | `GET` | `/v1/invoice_registrants/{invoice_registration_number}` | Include detail after search or exact T-number. |
| Programs | `GET` | `/v1/programs/search` | Always. |
| Programs | `POST` | `/v1/programs/prescreen` | Always. |
| Programs | `GET` | `/v1/programs/{unified_id}` | Always. |
| Programs | `GET` | `/v1/source_manifest/{program_id}` | Include for source receipts. |
| Programs | `POST` | `/v1/funding_stack/check` | Include only with pair-count billing description and cost preview rule. |
| Laws | `GET` | `/v1/laws/search` | Include for legal-source discovery, with no legal advice fence. |
| Laws | `GET` | `/v1/laws/{unified_id}` | Include detail after real ID. |
| Laws | `GET` | `/v1/laws/{unified_id}/related-programs` | Include because agents often ask "which programs depend on this law". |
| Tax | `GET` | `/v1/tax_rulesets/search` | Include for tax-rule evidence discovery, with tax advice fence. |
| Tax | `GET` | `/v1/tax_rulesets/{unified_id}` | Include detail after real ID. |
| Court | `GET` | `/v1/court-decisions/search` | Include for source-linked court decision discovery. |
| Court | `GET` | `/v1/court-decisions/{unified_id}` | Include detail after real ID. |
| Enforcement | `GET` | `/v1/enforcement-cases/search` | Include for public administrative action discovery. |
| Enforcement | `GET` | `/v1/enforcement-cases/{case_id}` | Include detail after real ID. |
| Handoff | `GET` | `/v1/advisors/match` | Include only as last-step evidence-to-expert handoff. |

This is exactly 28 paths. Keep two slots free for emergency compatibility.

### 4.2 GPT30 paths intentionally excluded

| Excluded from GPT30 | Reason |
|---|---|
| `/v1/stats/coverage`, `/v1/stats/freshness` | Useful for transparency, but `meta/freshness` is enough for Custom GPT routing. |
| `/v1/bids/search`, `/v1/bids/{unified_id}` | Valuable, but procurement is not core P0 for Custom GPT unless a procurement GPT is the target. Use a procurement-specific slim spec later. |
| `/v1/case-studies/search` | Useful supporting evidence, but not necessary for first-call routing. |
| `/v1/am/law_article` | More specialized than law search/detail and may confuse agents. |
| Artifact compatibility/application/houjin-DD routes if unshipped or unstable | Do not expose planned names until present in full OpenAPI and examples. |
| Any `/v1/me/*`, billing, OAuth, webhook, export, integration route | State/mutation/account surfaces are not agent-safe for generic Actions import. |

## 5. Agent standard endpoint list

Agent standard can remain close to the current 34-path `docs/openapi/agent.json`, but the target should be <=30 unless a consuming surface is known to handle more.

### 5.1 Current checked 34 paths

The checked snapshot contains these paths:

```text
/v1/advisors/match
/v1/am/law_article
/v1/artifacts/company_folder_brief
/v1/artifacts/company_public_audit_pack
/v1/artifacts/company_public_baseline
/v1/bids/search
/v1/bids/{unified_id}
/v1/case-studies/search
/v1/citations/verify
/v1/cost/preview
/v1/court-decisions/search
/v1/court-decisions/{unified_id}
/v1/enforcement-cases/search
/v1/enforcement-cases/{case_id}
/v1/evidence/packets/query
/v1/evidence/packets/{subject_kind}/{subject_id}
/v1/funding_stack/check
/v1/houjin/{bangou}
/v1/intelligence/precomputed/query
/v1/invoice_registrants/search
/v1/invoice_registrants/{invoice_registration_number}
/v1/laws/search
/v1/laws/{unified_id}
/v1/laws/{unified_id}/related-programs
/v1/meta/freshness
/v1/programs/prescreen
/v1/programs/search
/v1/programs/{unified_id}
/v1/source_manifest/{program_id}
/v1/stats/coverage
/v1/stats/freshness
/v1/tax_rulesets/search
/v1/tax_rulesets/{unified_id}
/v1/usage
```

### 5.2 Standard target adjustment

To converge agent standard with GPT30:

- Keep GPT30's 28 paths as the base.
- Add `/v1/stats/coverage` and `/v1/stats/freshness` only if the consuming agent benefits from corpus transparency.
- Add bids paths only in a procurement-oriented spec.
- Add case-studies only in subsidy/adoption-proof spec.
- Remove `/v1/am/law_article` from generic agent standard unless the law article endpoint has stronger descriptions than law detail.

Recommended generic standard target: 30 paths = GPT30 28 plus stats coverage/freshness.

## 6. Full OpenAPI separation criteria

An endpoint belongs in agent-safe only if it passes all inclusion criteria and no exclusion criteria.

### 6.1 Inclusion criteria

| Criterion | Required test |
|---|---|
| Evidence-oriented | Returns source-linked public facts, packets, receipts, freshness, known gaps, review flags, or safe search/detail records. |
| Read-oriented or bounded generation | Does not mutate account state, subscriptions, external systems, user private records, or persistent integrations. |
| Stable public contract | Path, schema, `operationId`, and examples are ready for external agents. |
| Agent-routable | A non-expert AI can decide when to call it from natural language. |
| Bounded cost | Single call is cheap or has explicit cost preview/cap/idempotency rules before broad work. |
| Professional fence ready | Output and description prevent final legal/tax/audit/credit/application claims. |
| No private credential flow | Does not require OAuth callback, session login, webhook secrets, billing portal flow, or dashboard context. |
| No hidden table knowledge | Agent does not need internal table names, migration history, source ETL details, or legacy brand concepts. |
| No dangerous side effect | Calling it cannot send email, create subscriptions, rotate keys, start external sync, purchase credits, top up wallet, or alter alerts. |

### 6.2 Exclusion criteria

| Keep in full OpenAPI, exclude from agent-safe | Examples from full surface | Reason |
|---|---|---|
| Billing and payment mutation | `/v1/billing/checkout`, `/v1/billing/portal`, `/v1/wallet/topup`, `/v1/billing/refund_request` | Agents should not initiate payment/account flows from generic import. |
| OAuth/device/session/auth flows | `/v1/oauth/*`, `/v1/auth/*`, `/v1/session`, `/v1/device/*` | Requires user auth UI and sensitive token handling. |
| Account/private state | `/v1/me/*`, saved searches, watches, client profiles, dashboard | User-specific mutation and privacy surface. |
| Webhooks/subscribers/email | `/v1/me/webhooks/*`, `/v1/subscribers`, `/v1/email/unsubscribe` | Side effects and external delivery. |
| Integrations/orchestrators | `/v1/integrations/*`, `/v1/orchestrate/*` | Third-party connection and mutation. |
| Batch/export/CSV/PDF generation | `/v1/export`, `/v1/pdf_report/*`, `/v1/programs/batch`, bulk evaluate | Broad paid work; should be gated behind explicit production docs, not generic agent import. |
| Admin/operator/monitoring | admin, health internals, audit sitemap/seals if operator-oriented | Not first-call evidence for agents. |
| Experimental/gated/specialist endpoints | graph vec search, portfolio optimize, forecast, private preview, narrow industry endpoints | Too easy for agent to misuse or overstate. |
| Duplicate aliases | multiple paths for same intent | Burns path budget and confuses routing. |
| Final-judgment-like outputs | risk/safe/optimize paths without strong fence | Agent may convert signals into prohibited conclusions. |

Rule: if an endpoint needs a paragraph explaining why it is safe, it probably belongs in full OpenAPI, not the generic agent-safe subset.

## 7. Operation description rules

Every agent-safe operation description must follow the same structure. Do not rely only on global `info.description`; many tools surface operation descriptions independently.

### 7.1 Required description blocks

Use this order in every P0 operation:

```text
Use when: <closed list of user intents>.

Do not use when: <closed list of unsupported/final-judgment cases>.

Routing rule: <what to call before/after; when web search is allowed>.

Cost rule: <free or metered; preview/cap/idempotency requirements; anonymous quota behavior>.

Fence rule: <not final legal/tax/audit/credit/application/professional judgment; human review if sensitive>.

No-hit rule: <empty result is not proof of absence>.

Preserve in downstream answer: <fields>.
```

Descriptions should use consistent words because LLM tool routers pattern-match. Avoid marketing phrasing, legacy names, and internal implementation details.

### 7.2 Global routing rules to embed

These rules should appear in `info.description`, `x-jpcite-agent-call-order-policy`, and the relevant operation descriptions.

```text
When the user asks about Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or Japanese company public records, and the answer needs source URLs, fetched timestamps, provenance, known gaps, freshness, compatibility/exclusion evidence, or reviewer-ready output, call jpcite before drafting the final answer.

Use previewCost before broad, repeated, batch, CSV, watchlist, compatibility-pair fanout, or cost-sensitive execution. Use X-Cost-Cap-JPY and Idempotency-Key on paid POST execution. Use X-Client-Tag when the caller has a customer, project, client folder, or matter ID.

Use general web search after jpcite only for known_gaps, non-public context supplied by the user, or very recent changes outside the corpus. Do not use web search to overwrite source receipts without saying the corpus gap.
```

### 7.3 Global fence rules to embed

```text
jpcite returns source-linked evidence support. It does not call an external LLM at request time and does not generate final legal, tax, audit, credit, investment, application, subsidy approval, loan approval, safety, or professional judgment.

For sensitive surfaces, preserve _disclaimer, human_review_required, known_gaps, and source receipts. Tell the user that final judgment belongs to the appropriate qualified reviewer.

No-hit, low match count, missing field, null amount, or stale source does not prove absence, ineligibility, safety, compliance, approval, or no risk.
```

Canonical professional fences to name where relevant:

| Surface | Fence copy |
|---|---|
| Tax | `Not tax advice; final filing or tax position requires a licensed tax accountant review. // fence: 税理士法§52` |
| Legal/law/court | `Not legal advice or legal representation; final legal judgment requires qualified legal review. // fence: 弁護士法§72` |
| Audit/DD | `Public-record evidence only; not a statutory audit, audit opinion, fraud assurance, or credit safety judgment. // fence: 公認会計士法§47条の2 where applicable` |
| Applications/permits | `Evidence and checklist support only; not application代理 or approval guarantee. // fence: 行政書士法§1の2・§19 where applicable` |
| Registry/real estate/company registration | `Evidence support only; not registration代理 or final registry procedure advice. // fence: 司法書士法§3 where applicable` |
| Labor/social insurance | `Evidence support only; final labor/social insurance procedure requires qualified review. // fence: 社会保険労務士法§27 where applicable` |
| IP/patent | `Evidence support only; final patent/trademark procedure requires qualified review. // fence: 弁理士法§75 where applicable` |
| Labor standards / 36 agreement | `Evidence support only; final labor agreement/compliance judgment requires qualified review. // fence: 労働基準法§36 where applicable` |

### 7.4 Cost rules to embed

| Rule | Operation description language |
|---|---|
| Unit price | `Metered calls are currently JPY 3 ex-tax / about JPY 3.30 inc-tax per billable unit. External LLM/search/runtime costs are not included.` |
| Preview | `Call previewCost first when the workflow is broad, repeated, fanout-based, batch-like, or user asks about budget.` |
| Free preflight | `previewCost estimates planned jpcite units and yen; it does not execute or pay for planned calls.` |
| Cap | `For paid POST fanout/batch/packet execution, set X-Cost-Cap-JPY or body cap before work starts.` |
| Idempotency | `For paid POST retries, send Idempotency-Key; same key with different payload must be treated as conflict.` |
| Anonymous | `Anonymous use is only for small evaluation and may be exhausted by shared IPs. Production Custom GPTs should use a fixed API key.` |
| No double counting | `Validation, auth, quota, cap reject, idempotency conflict, and unsupported final-judgment reject should not be billed.` |
| Cost savings | `Do not claim external LLM cost reduction unless response explicitly supports it with caller baseline fields.` |

## 8. Endpoint-specific description guidance

### 8.1 `previewCost`

Description must say:

- Use before broad/repeated/fanout/cost-sensitive work.
- Does not execute planned calls.
- Does not itself represent final invoice if the stack changes.
- Preserve `predicted_total_yen`, `billing_units`, `unit_price_yen`, `iterations`, `breakdown`, `metered`, `disclaimer`.

Must not say:

- `preview executes the requested work`
- `final invoice is guaranteed if request changes`
- `external LLM costs are included`

### 8.2 `queryEvidencePacket` / `getEvidencePacket`

Description must say:

- Use before final answer generation when source-linked Japanese public evidence matters.
- jpcite returns evidence, not final narrative answer.
- Preserve `packet_id`, `records[].source_url`, `records[].source_fetched_at`, `source_checksum` or `content_hash`, `corpus_snapshot_id`, `quality.known_gaps`, `quality.human_review_required`, `verification`, `decision_insights`, `_disclaimer`.
- Use web search after this only for known gaps, user-provided private context, or very recent non-corpus changes.

Must not say:

- `coverage is exhaustive`
- `freshness is guaranteed after source_fetched_at`
- `human review is unnecessary`
- `packet proves absence`

### 8.3 `createCompanyPublicBaseline`

Description must say:

- First call for Japanese company research, counterparty check, client folder, DD/audit prep, sales/account prep, and public opportunity/risk review.
- Use before general web search for public company facts.
- Preserve entity resolution, identity confidence, source receipts, known gaps, mismatch flags, and review flags.

Must not say:

- `credit_safe`
- `no enforcement exists`
- `audit complete`
- `legal/tax review complete`
- `public record baseline is a private credit report`

### 8.4 `company_folder_brief` and `company_public_audit_pack`

Description must say:

- Follow-up after company baseline.
- Public-record workpaper/folder inputs only.
- Preserve evidence ledger, risk/gap register, questions to ask, next actions, mismatch flags, review controls, human review flags.

Must not say:

- `statutory audit complete`
- `audit opinion issued`
- `fraud absence confirmed`
- `professional review complete`

### 8.5 `programs/search`, `programs/prescreen`, `programs/{unified_id}`

Description must say:

- `searchPrograms` is discovery; use when the agent needs real candidate IDs.
- `prescreenPrograms` ranks candidates from a profile; it is not final eligibility.
- `getProgram` is detail after a real `unified_id` is known.
- Preserve `unified_id`, `title`, `source_url`, `source_fetched_at`, `deadline`, amount caveats, `known_gaps`, compatibility/exclusion rules.

Must not say:

- `eligible`
- `approved`
- `application success likely`
- `missing axis means no requirement`
- `null amount means zero grant`

### 8.6 Law, tax, court, enforcement endpoints

Description must say:

- Use for source discovery/detail, not legal/tax judgment.
- Search first, detail after real ID.
- Preserve official source, fetched timestamp, statute/case identifiers, known gaps, and jurisdiction caveats.
- For enforcement, no-hit does not prove no enforcement or no risk.

Must not say:

- `legal advice`
- `tax advice`
- `compliant`
- `no liability`
- `no enforcement risk`

### 8.7 `advisors/match`

Description must say:

- Use only after source-linked evidence, candidate programs, known gaps, and caveats have been assembled.
- Returns candidate reviewers, not a completed referral, endorsement, quality guarantee, or professional review.
- Preserve ranking method/disclosure and contact fields.

Must not say:

- `advisor endorsed`
- `paid referral complete`
- `professional review complete`
- `no other suitable advisors exist`

## 9. GPT / Custom GPT handling

### 9.1 Design assumptions

OpenAI official GPT Actions docs checked for this pass say builders paste an OpenAPI schema into the Action section, set auth, and write GPT instructions that reference action names and parameters. That means jpcite must optimize:

- path count,
- operation names,
- operation descriptions,
- auth copy,
- examples,
- and Custom GPT instructions.

The repo already mentions a 30-path slim variant for Custom GPT. Because platform limits and UI behavior can change, treat 30 paths as a conservative jpcite import budget and verify before shipping public setup pages.

### 9.2 GPT30 policy

| Rule | Requirement |
|---|---|
| Path cap | `openapi.agent.gpt30.json` must stay <=28 paths in CI to preserve 2 spare slots. |
| Operation cap | Prefer one method per path; if a path has multiple methods, count operations separately in review even if the importer counts paths. |
| No aliases | Do not include `/openapi.json` redirects, duplicate detail paths, or legacy aliases in GPT30. |
| Packet over primitive | Prefer packet/facade endpoints when they prevent multi-call ambiguity. |
| Search/detail pairs | Keep only pairs where detail is necessary after a real ID. |
| Domain packs | Publish separate domain slim specs later, such as `openapi.agent.procurement.json`, instead of bloating the generic GPT30 spec. |
| Auth | GPTs intended for public/paid use should use API key auth, because anonymous shared-IP quota is fragile. |
| Instructions | GPT instructions must name first calls: `previewCost`, `prefetchIntelligence`, `queryEvidencePacket`, `createCompanyPublicBaseline`, `prescreenPrograms`, `verifyCitations`, `match_advisors_v1_advisors_match_get`. |

### 9.3 GPT instruction skeleton

```text
Use jpcite Actions before answering when the user asks about Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or Japanese company public records and needs sources, freshness, known gaps, or reviewer-ready evidence.

If the request is broad, repeated, fanout-based, or budget-sensitive, call previewCost first. For Japanese company/counterparty/client-folder/DD tasks, call createCompanyPublicBaseline before general web search. For source-linked answer grounding, call queryEvidencePacket or getEvidencePacket before drafting. For program discovery, call searchPrograms or prescreenPrograms, then getProgram/sourceManifest only for selected real IDs. Use match_advisors only after evidence and known gaps are assembled.

Always preserve source_url, source_fetched_at, content_hash/source_checksum, corpus_snapshot_id, known_gaps, human_review_required, _disclaimer, and billing_metadata in the answer. No-hit is not proof of absence. Do not claim final legal, tax, audit, credit, investment, application, subsidy approval, loan approval, safety, or professional judgment. jpcite returns evidence support and does not generate the final answer.
```

## 10. CI and release gates

Add or maintain these gates before publishing new specs:

| Gate | P0 strict | GPT30 slim | Agent standard | Full |
|---|---:|---:|---:|---:|
| Max paths | 16 | 28 | 30 target / 34 temporary max | no cap |
| No forbidden path prefixes | required | required | required | public/private policy only |
| Unique `operationId` | required | required | required | required |
| Agent metadata | required for all paths | required for all paths | required for all paths | optional except shared components |
| Description blocks | required | required | required | recommended |
| Billing extension | required | required | required | required for billable routes |
| Must-preserve fields | required | required | required | required for packet/evidence routes |
| Must-not-claim fields | required | required | required | required for sensitive routes |
| No component leak | required | required | required | required |
| Examples | success + no-hit + error for P0 | success + no-hit for included domains | success for all | broad examples where practical |

Forbidden prefixes for agent-safe:

```text
/v1/admin
/v1/auth
/v1/billing
/v1/compliance
/v1/device
/v1/email
/v1/export
/v1/integrations
/v1/me
/v1/oauth
/v1/orchestrate
/v1/pdf_report
/v1/privacy
/v1/session
/v1/signup
/v1/subscribers
/v1/wallet
/v1/widget
```

Some paths outside these prefixes can still be excluded if they mutate state, trigger external delivery, expose private/account state, or require expert routing beyond a generic agent.

## 11. Migration plan

### Phase 0: Document current state

- Keep `docs/openapi/agent.json` as current checked standard snapshot.
- Publish internal note that current standard is 34 paths and is not the preferred Custom GPT import.
- Document the GPT30 28-path target and P0 strict 15-path target.

### Phase 1: Generate P0 and GPT30 specs

- Add export targets for `openapi.agent.p0.json` and `openapi.agent.gpt30.json`.
- Use the same sanitizer as full and agent exports.
- Add path-count tests:
  - P0 `<=16`
  - GPT30 `<=28`
  - standard `<=34` initially, with warning above 30
- Add deny-prefix tests for all agent-safe specs.

### Phase 2: Strengthen operation descriptions

- Normalize descriptions to the block structure in section 7.
- Add endpoint-specific examples for no-hit and fence-sensitive outputs.
- Add `x-jpcite-agent` object with `recommend_when`, `do_not_recommend_when`, `must_preserve_fields`, `must_not_claim`, `web_search_after`, and `cost_rule`.

### Phase 3: Public discovery sync

- Update `llms.txt`, `.well-known/openapi-discovery.json`, docs agent quickstart, and Custom GPT setup copy to recommend GPT30 slim.
- Keep full OpenAPI for SDK generation.
- Clearly state that agent-safe subset is intentionally incomplete and full public REST remains available for developers.

## 12. Final recommendation

Use this as the P0 decision:

- P0 strict: 15 paths, packet/control/company/program/citation/handoff only.
- GPT30 slim: 28 paths, default Custom GPT import.
- Agent standard: converge from current 34 to 30 by removing generic bids/case-studies/am-law-article from the default spec or moving them to domain-specific slim specs.
- Full OpenAPI: keep 302-path public developer contract, but never present it as the first import for live AI agents.

The agent-safe subset should be judged by routing accuracy and risk containment, not by coverage. Any endpoint that makes an AI more likely to guess, over-call, over-spend, mutate state, or make a professional conclusion belongs in full OpenAPI only.
