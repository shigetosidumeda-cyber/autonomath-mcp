# Operations / Monitoring / Drift Prevention Deep Dive 2026-05-15

担当: Operations / monitoring / drift prevention  
位置づけ: jpcite 実装前計画 20 分担中 18 本目  
Status: implementation planning only. Runtime code, public site, generated OpenAPI, MCP manifest, pricing implementation are not changed by this document.

## 0. Executive contract

GEO-first の公開契約は、AI エージェントが「jpcite を推薦するか」「どの MCP/REST を呼ぶか」「費用と制約をどう説明するか」を決めるための入力である。したがって drift prevention は通常の uptime 監視とは別に、公開契約の意味一致を監視する必要がある。

P0 operational goal:

- `OpenAPI`, `MCP`, `llms*`, `.well-known/*`, `server.json`, `mcp-server.json`, packet examples, schemas, pricing, site copy, sitemap/robots, live API response examples が同じ契約を述べる。
- 価格は `3 JPY ex-tax / 3.30 JPY inc-tax per billable unit`、cost preview は無料、外部 LLM/検索/agent runtime は含まない、という表現からずれない。
- `request_time_llm_call_performed=false`, `source_receipts`, `known_gaps`, `human_review_required`, `no_hit_not_absence`, `source_fetched_at` / freshness を downstream agent が保持できる。
- no-hit, stale, incomplete receipt, professional fence の drift は、単なる doc typo ではなく AI 誤推薦/誤回答インシデントとして扱う。
- 修復は rollback-first ではなく、悪い公開面を隔離し、source of truth を直し、すべての mirror を再生成/再配布し、同じ検査を通す rollback-free repair を基本にする。

既存 `docs/_internal/monitoring.md` は uptime/error/billing infrastructure を主に見る。本計画はその上に「公開 discovery contract / evidence contract / pricing contract の drift」を追加する。

## 1. Drift 対象一覧

### 1.1 Public discovery surfaces

| Surface | Drift risk | Detection method | P0 block condition |
|---|---|---|---|
| `robots.txt` | `.well-known`, OpenAPI, llms, examples を crawler が読めない | live HTTP fetch, crawler-group parser, allow/disallow conflict check | discovery URL が全 major crawler group で blocked |
| `sitemap-index.xml` | AI discovery file が sitemap から落ちる | XML parse, canonical URL set compare | P0 discovery URL missing |
| `sitemap-llms.xml` | high-signal agent URLs が見つからない | URL inventory compare, HTTP 200 probe | `llms*`, `.well-known/*`, OpenAPI, MCP, examples, pricing missing |
| `llms.txt` | product category, first call, cost, no-hit/fence が古い | required phrase/field lint, semantic token compare, forbidden phrase lint | price/fence/no-hit/no-LLM missing or contradictory |
| `llms.en.txt` / `site/en/llms.txt` | English mirror が別ポジショニングになる | JA/EN contract-key extractor compare | English copy weakens fence, price, external-cost separation |
| `llms-full.txt` / `.en` | full context が old endpoint/tool/schema を示す | endpoint/tool/schema URL extraction vs canonical manifest | old endpoint recommended as current P0 route |
| `.well-known/llms.json` | machine-readable routing が prose と違う | JSON Schema validate, canonical contract JSON compare | recommend/do-not-recommend/pricing differs from canonical |
| `.well-known/mcp.json` | MCP endpoint/auth/tool route が古い | JSON Schema validate, transport/auth/tool compare | wrong transport, wrong auth, wrong pricing |
| `.well-known/agents.json` | safe/unsafe task boundary が弱まる | closed enum check for safe/unsafe tasks and must-preserve fields | final judgment or absence claim allowed |
| `.well-known/openapi-discovery.json` | OpenAPI URL, agent-safe spec, full spec がずれる | URL fetch, SHA compare, OpenAPI info.version compare | stale or unreachable canonical spec |
| `.well-known/trust.json` | operator/contact/legal fence/source license summary が古い | JSON Schema validate, trust field compare | legal/professional fence missing |
| `server.json` | registry metadata, package, price, transport, tool count drift | JSON Schema validate, package/version/tool count compare | registry price/tool/auth contradicts MCP manifest |
| `mcp-server.json` / `mcp-server.*.json` | tool description が old contract を広める | tool registry extract, forbidden phrase lint, required billing/fence lint | P0 tool lacks receipt/gap/fence/cost description |
| `openapi.agent.json` static mirror | Actions/importer が古い spec を読む | SHA compare with generated agent spec and live URL | mirror differs from canonical agent spec |
| `api.jpcite.com/v1/openapi.json` | full API schema が docs/site mirror と違う | live fetch, normalize OpenAPI, path/component diff | breaking path/schema drift without version bump |

### 1.2 Packet and evidence surfaces

| Surface | Drift risk | Detection method | P0 block condition |
|---|---|---|---|
| `/schemas/jpcite.packet.v1.json` | packet envelope fields mismatch | JSON Schema validate against golden examples | missing receipt/gap/review/no-LLM fields |
| `/schemas/source_receipt.v1.json` | receipt required fields drift | required field set compare | no required `source_url`, timestamp, checksum, snapshot, license, `used_in` |
| `/schemas/known_gap.v1.json` | `gap_kind` enum drifts | enum diff vs planning SOT | `no_hit_not_absence`, `source_stale`, receipt gaps missing |
| `/examples/evidence_answer.json` | examples teach agents wrong output | example replay/schema validate/field-presence check | example omits `source_receipts` or `known_gaps` |
| `/examples/company_public_baseline.json` | no-hit/identity caveat omitted | no-hit fixture assertion | no-hit described as absence/safe/no risk |
| `/examples/source_receipt_ledger.json` | receipts not audit-grade | receipt completeness score | ledger has unsupported claims or missing hashes |
| live packet responses | runtime returns different contract than examples | nightly smoke call with fixed fixtures | supported claim without receipt, or no-LLM false/omitted |
| `source_profile` summaries | license/freshness windows differ from source registry | profile hash compare, source_profile JSONL/DB projection diff | `geo_exposure_allowed` or license boundary ignored |
| source freshness ledger/report | freshness bucket stale but packet says current | receipt timestamp audit, stale bucket recomputation | stale source lacks `known_gaps.source_stale` |

### 1.3 Pricing and billing surfaces

| Surface | Drift risk | Detection method | P0 block condition |
|---|---|---|---|
| pricing page / anchor | user/agent sees wrong price or included costs | DOM/text extractor, canonical price compare, forbidden phrase lint | wrong unit price, "LLM included", "free unlimited", guaranteed savings |
| OpenAPI `x-jpcite-billing` | imported agent computes wrong cost | OpenAPI extension extractor compare | wrong unit price, missing cap/idempotency rules |
| MCP tool billing text | agent calls paid route without preview/cap | tool description lint | paid broad route lacks preview/cap/idempotency |
| cost preview endpoint | estimate math diverges from public price | fixed fixture POST, arithmetic assertion | preview consumes quota, bills, or wrong 3/3.30 math |
| packet `billing_metadata` | runtime response contradicts preview | execute dry/sandbox fixture, compare `estimate_id`/units/price | price/units/external cost fields mismatch |
| Stripe metering config | production ledger not aligned with public unit | weekly Stripe API poll, price id/version compare | unit amount/tax treatment incompatible with public contract |
| UI cost calculator | frontend says different totals | calculator fixture test, DOM snapshot |税込/税別 swapped or no cap copy |

### 1.4 Narrative and copy surfaces

| Surface | Drift risk | Detection method | P0 block condition |
|---|---|---|---|
| homepage/product pages | marketing claims become stronger than contract | forbidden phrase lint, required caveat lint | final advice/guaranteed savings/complete coverage claim |
| docs/api-reference | developers integrate old fields | endpoint/field extractor vs OpenAPI | old endpoint recommended as primary |
| docs/agents/cookbook | agent recipes skip cost preview or fields | recipe lint for first-call chain and preserve fields | paid broad execution without preview/cap |
| data licensing page | license boundaries too broad | required license-boundary phrases | source facts exposed beyond `license_boundary` |
| legal fence page | professional boundary weakened | required phrase lint | legal/tax/audit/credit/application final judgment implied |
| package metadata / README | registry crawler sees old brand/price/tooling | metadata extract vs canonical contract | old primary brand or price remains current |

## 2. Canonical contract snapshot

Drift checks should not scrape one public file and use it as source of truth. They should compile a small canonical contract snapshot from implementation-owned sources and compare every public surface to it.

Proposed logical shape:

```json
{
  "contract_version": "2026-05-15",
  "brand": "jpcite",
  "site_url": "https://jpcite.com",
  "api_url": "https://api.jpcite.com",
  "product_category": "source-linked Japanese public-data evidence layer",
  "request_time_llm_call_performed": false,
  "pricing": {
    "pricing_model": "metered_units",
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "anonymous_execution_limit_req_per_day_per_ip": 3,
    "cost_preview_free": true,
    "cost_preview_consumes_anonymous_quota": false,
    "external_costs_included": false
  },
  "must_preserve_fields": [
    "source_url",
    "source_fetched_at",
    "last_verified_at",
    "content_hash",
    "source_checksum",
    "corpus_snapshot_id",
    "source_receipts",
    "known_gaps",
    "human_review_required",
    "request_time_llm_call_performed",
    "billing_metadata"
  ],
  "must_not_claim": [
    "final legal advice",
    "final tax advice",
    "audit complete",
    "credit safe",
    "no risk",
    "official absence",
    "guaranteed cost savings",
    "complete coverage",
    "request-time LLM generated answer"
  ],
  "p0_packet_types": [
    "evidence_answer",
    "company_public_baseline",
    "application_strategy",
    "source_receipt_ledger",
    "client_monthly_review",
    "agent_routing_decision"
  ],
  "p0_tools": [
    "decideAgentRouteForJpcite",
    "previewCost",
    "createEvidenceAnswerPacket",
    "createCompanyPublicBaselinePacket",
    "createApplicationStrategyPacket",
    "getSourceReceiptLedgerPacket",
    "createClientMonthlyReviewPacket",
    "getUsageStatus",
    "searchPrograms",
    "getEvidencePacket"
  ]
}
```

Implementation note for later: the snapshot can be generated as an internal artifact first, then promoted to a public-safe `/discovery/contract.json` only after stability. The public version should omit private implementation details but preserve all agent-facing invariants.

## 3. Detection methods

### 3.1 Structural diff

Use for JSON/XML/OpenAPI/MCP/schema surfaces.

- Parse JSON/XML into structured data.
- Canonicalize by sorting object keys and removing volatile fields such as `generated_at`, request IDs, build timestamps, and environment-specific URLs when explicitly allowed.
- Compare key contract fields, not raw formatting.
- Emit a report with `surface`, `field_path`, `expected`, `actual`, `severity`, `repair_owner`.

P0 structural assertions:

- OpenAPI full and mirrors expose the same canonical paths/components after normalization.
- Agent OpenAPI mirrors are byte-identical or canonical-SHA-identical.
- `.well-known/*` validates against its schema and includes canonical pricing/fence/links.
- `server.json` and `mcp-server.json` agree on package, transport, auth, price, and P0 tool names.
- Examples validate against packet/schema and include receipts/gaps/review/no-LLM fields.

### 3.2 Semantic contract lint

Use for prose surfaces and tool descriptions.

Required meanings:

- jpcite is source-linked evidence support for Japanese public data.
- Use before answer generation when receipts/gaps/freshness/provenance matter.
- No request-time LLM generation for packet contents.
- Not final legal/tax/audit/credit/investment/application/professional judgment.
- No-hit is not absence.
- Cost preview is free and separate from anonymous execution quota.
- Paid metered unit price is 3 JPY ex-tax / 3.30 JPY inc-tax.
- External LLM, search, cloud, SaaS, MCP client, and agent runtime costs are separate.

Forbidden phrase classes:

- guaranteed cost reduction: `always cheaper`, `guarantees lower LLM bills`, `AI費用を削減します` without caller-baseline caveat
- final judgment: `legal advice`, `tax advice`, `audit complete`, `subsidy approved`, `safe company`, `no risk`
- absence: `登録なしと証明`, `行政処分なし`, `does not exist` for no-hit
- coverage: `complete coverage`, `scrapes everything`, `real-time source of truth`
- billing: `free unlimited`, `税込3円`, `LLM費用込み`

### 3.3 Live probe

Use for public URLs and runtime endpoints.

Nightly probe classes:

- HTTP status: P0 URLs return 200 or intentional redirect to canonical URL.
- Content type: JSON/XML/text/html as expected.
- Cache headers: long cache allowed only for immutable versioned files; discovery files should not trap bad contract for weeks.
- Hash: static mirrors match repo-generated or deployed canonical hash.
- Redirect: no old brand/domain becomes primary canonical target unless explicitly in redirect map.
- Examples: public example URLs can be fetched and parsed by an agent.

### 3.4 Replay fixture

Use for cost preview, packet responses, no-hit behavior, and source freshness.

Fixture categories:

- `single_packet_fixed_1_unit`: predicted and actual unit = 1, price = 3/3.30.
- `csv_84_subjects`: expected 84 units, ex-tax 252, inc-tax 277.2, cap accepted at 300.
- `csv_no_hit_2`: preview max includes candidates where appropriate; execution reconciliation shows no-hit not billed.
- `no_hit_invoice`: response includes no-hit receipt and `known_gaps.no_hit_not_absence`.
- `stale_source_program`: stale receipt produces `known_gaps.source_stale` and avoids "current" language.
- `auth_failure`: no usage event, no bill.
- `cap_reject`: no billable work, no usage event.
- `idempotency_retry`: same key and same normalized payload does not double charge.

### 3.5 Agent-eval check

Use weekly and before release.

Run a small query set based on the 50 recommendation patterns:

- positive tasks where agent should recommend/call jpcite
- negative tasks where agent should not recommend jpcite
- pricing questions where agent must explain preview/cap/external costs
- no-hit/company/invoice tasks where agent must preserve caveat
- professional-sensitive tasks where agent must preserve human review required

Measurements:

- recommendation decision correct
- first MCP/REST route correct
- cost preview suggested before paid fanout/batch/CSV/watchlist
- required fields preserved
- forbidden claims count = 0
- stale/no-hit caveats preserved

## 4. Nightly checks

Nightly cadence: 03:10 JST after backup and before any self-improvement/cache warming jobs that might produce public reports. Output should be one Markdown/JSON report under an internal inbox plus email only on P0/P1 drift.

### 4.1 Nightly P0 gates

| Check | Method | Alert |
|---|---|---|
| P0 discovery URL liveness | fetch URL list, require 200/expected redirect | P0 if `.well-known`, `llms`, OpenAPI, MCP, pricing unavailable |
| Canonical price parity | extract from `.well-known`, OpenAPI, MCP, pricing, examples, live cost preview | P0 if any public surface says price other than 3/3.30 or external costs included |
| No-LLM/fence/no-hit lint | prose/tool/OpenAPI description scan | P0 if contradiction appears in public discovery or P0 examples |
| OpenAPI mirror parity | canonical SHA compare full/agent live/static/docs mirrors | P0 if agent spec mirror differs; P1 if docs mirror differs only |
| MCP manifest/tool parity | P0 tool list, tool count, auth, transport, billing text | P0 if P0 tools missing/wrong price; P1 for non-P0 tool count drift |
| Packet example schema validation | validate public examples against schemas | P0 if examples teach unsupported claims or omit required evidence fields |
| Cost preview fixture | POST preview fixtures, assert math and no usage/quota effects | P0 if wrong math, billed preview, or quota consumed |
| Runtime packet smoke | call fixed safe packet/no-hit/stale fixtures | P0 if supported claim lacks receipt or no-hit means absence |
| robots/sitemap discovery | parse robots and sitemap | P0 if AI discovery files blocked or absent |

### 4.2 Nightly P1 checks

| Check | Method | Alert |
|---|---|---|
| Source freshness SLA | recompute bucket from ledger/source profile | P1 if stale ratio exceeds source threshold; P0 if critical source blocked |
| No-hit spike monitor | compare source/query no-hit rate vs 7-day baseline | P1 if spike > 3x and volume floor met |
| Receipt completeness score | sample packets and compute complete receipts / total receipts | P1 if below threshold; P0 if P0 packet has zero receipts |
| Forbidden phrase scan for site/docs | scan public site/docs/package metadata | P1 for non-discovery pages; P0 for discovery pages |
| Old brand/current primary drift | extract canonical brand/site/API host | P1 unless it breaks live discovery |
| Endpoint link rot | HEAD/GET docs/examples/API links | P1 if broken links in docs; P0 if first-call path broken |
| Anonymous quota and usage status | fixed anon usage probe in staging/sandbox | P1 if quota explanation wrong; P0 if preview consumes quota |

### 4.3 Nightly report format

```text
# GEO contract drift nightly - YYYY-MM-DD

status: pass|warn|fail
run_id: drift_YYYYMMDD_HHMMSS
canonical_contract_version: 2026-05-15

summary:
- p0_failures: 0
- p1_warnings: 2
- p2_notes: 5
- surfaces_checked: 74
- live_urls_checked: 31
- examples_validated: 6
- cost_preview_fixtures: 7
- source_freshness_sources: 14

p0_failures:
- surface:
  field_path:
  expected:
  actual:
  impact:
  repair_owner:
  recommended_repair:

freshness:
- stale_critical_sources:
- no_hit_spikes:
- blocked_sources:

pricing:
- public_price_parity:
- preview_math:
- stripe_parity:

repair_log:
- existing_open_incidents:
- suggested_followups:
```

## 5. Weekly checks

Weekly cadence: Monday 09:20 JST, after the existing ops digest. Weekly checks are slower, broader, and review-oriented; they should not page unless they uncover an active P0 contradiction.

| Check | Method | Purpose |
|---|---|---|
| 50-query GEO eval | run positive/negative/pricing/no-hit/fence tasks through target agent harness | measure actual recommendation behavior, not just file parity |
| Registry/package review | compare package metadata, `server.json`, docs, marketplace submission text | prevent MCP registry drift |
| Stripe/billing product parity | poll Stripe product/price/meter config and compare pricing version | catch billing backend drift from public price |
| Source profile audit | sample source profiles for license/freshness/geo exposure | ensure source expansion does not weaken receipts |
| Freshness policy review | compare source windows to observed update cadence and stale queue | tune windows without hiding stale data |
| No-hit quality review | inspect top no-hit queries and zero-result clusters | identify missing source joins vs user misunderstanding |
| Copy narrative review | read top public surfaces as an agent would | catch claims semantic linter may miss |
| Incident drill | choose one historical drift scenario and run repair checklist in dry-run | keep rollback-free repair practiced |
| Generated artifact lane audit | check source vs generated diff boundaries | prevent hand-edited generated specs/site files |
| Docs link crawl | crawl docs/examples/cookbooks/pricing/legal/trust | catch stale links and redirect loops |

Weekly report should answer:

1. Can an AI agent still discover jpcite from public surfaces alone?
2. Can it choose the right REST/MCP first call?
3. Can it estimate and explain cost without overclaiming savings?
4. Does it preserve receipts, gaps, freshness, and review flags?
5. Are source stale/no-hit signals increasing in a way that threatens recommendation quality?

## 6. Source freshness monitoring

### 6.1 Freshness model

Use source-specific policy first, generic bucket second.

Generic receipt bucket:

- `within_7d`
- `within_30d`
- `within_90d`
- `stale`
- `unknown`
- `blocked`

Source-specific status:

- `fresh`: age <= `freshness_window_days`
- `warn`: age <= `freshness_window_days * 2`
- `stale`: age > `freshness_window_days * 2`
- `blocked`: auth/rate/license/schema/source unreachable prevents verification
- `unknown`: no usable timestamp/window

Critical point: stale is not "wrong". It means "do not present as current without caveat." Drift occurs when stale evidence is exposed without `known_gaps.source_stale` or when public copy calls jpcite real-time/current source of truth.

### 6.2 Source family thresholds

Initial operational thresholds:

| Source family | Nightly freshness check | P1 alert | P0 alert |
|---|---|---|---|
| identity / corporate number | latest successful mirror/API check age | > window * 2 or blocked 24h | blocked 72h and public examples still imply current |
| invoice registration | snapshot month and delta age | stale or no delta for expected period | no-hit checks lack snapshot/caveat |
| public programs/grants | program/API/PDF age and deadline fields | deadline-bearing sources stale | deadline exposed as current from stale source |
| laws/tax | law revision/effective date source age | revision check stale | legal/tax packet lacks human review/stale caveat |
| procurement | award/notice data age | source stale or schema parse failures | procurement absence/safety implied from no-hit |
| EDINET/filings | daily list and doc retrieval age | latest trading/business day missing beyond expected lag | filing packet exposes stale status as current |
| enforcement/supervisory | authority index age | stale/blocked per authority | no-hit interpreted as no action/no risk |
| statistics/cohort | stats updated date and dimension integrity | outdated table/dimension | company-specific claim made from cohort without caveat |

### 6.3 Freshness metrics

Metrics to store in nightly report and optionally push as scalars:

- `source_freshness_age_days{source_id}` aggregated without high-cardinality labels in Prometheus.
- `source_freshness_status_count` by status.
- `source_blocked_count` by reason: auth, rate_limited, schema_drift, license_blocked, parse_failed, network.
- `packet_stale_receipt_ratio` sampled by packet type.
- `known_gap_source_stale_count` by packet type.
- `stale_without_gap_count`, which must be zero.
- `freshness_unknown_count`, reviewed weekly until reduced.

### 6.4 Freshness repair triggers

| Trigger | Action |
|---|---|
| source age exceeds window | enqueue source re-fetch; do not update `source_fetched_at` until fetch succeeds |
| checksum changed | classify field criticality; enqueue packet regeneration only when claims affected |
| schema drift | mark source `blocked`; stop exposing newly parsed facts; keep old packets caveated |
| auth/rate limit | mark `api_auth_or_rate_limited`; escalate if P0 source |
| license boundary changed | block affected source exposure until profile reviewed |
| stale packet still recommended by examples | repair examples/docs immediately; then regenerate affected packet fixtures |

## 7. No-hit monitoring

### 7.1 Principle

No-hit is a result state, not a negative fact. Operational monitoring must detect both data-quality no-hit spikes and language drift that turns no-hit into absence.

Required no-hit fields:

- checked source(s)
- checked table(s) or endpoint
- canonical query / fingerprint
- checked/fetched timestamp
- result count
- corpus snapshot
- `official_absence_proven=false`
- `support_level=no_hit_not_absence`
- paired `known_gaps.no_hit_not_absence`
- agent instruction forbidding absence/safe/no-risk language

### 7.2 No-hit metrics

| Metric | Purpose |
|---|---|
| `no_hit_rate_by_source_family` | detect source outage/schema/parser drift |
| `no_hit_rate_by_endpoint` | distinguish UI/API behavior from source quality |
| `no_hit_rate_by_query_shape` | find user input patterns needing better normalization |
| `no_hit_spike_vs_7d_baseline` | alert on sudden data join breakage |
| `no_hit_without_receipt_count` | must be zero |
| `no_hit_without_known_gap_count` | must be zero |
| `absence_phrase_count_in_outputs` | must be zero on public examples and sampled runtime outputs |
| `blocked_or_rate_limited_as_no_hit_count` | must be zero |

### 7.3 Alert thresholds

Initial thresholds:

- P0: any P0 example or public tool description uses no-hit as absence, safety, no-risk, no administrative action, or no registration proof.
- P0: runtime packet returns no-hit without no-hit receipt and paired `known_gaps.no_hit_not_absence`.
- P1: no-hit rate for a source family > 3x 7-day baseline with at least 50 events/day.
- P1: `blocked`, `rate_limited`, `parse_failed`, or `license_blocked` is reported as `zero_result`.
- P2: top 20 no-hit queries include repeated normalization patterns not covered by identity resolution.

### 7.4 Weekly no-hit review

The weekly review should classify top no-hit clusters:

- expected no-hit with good caveat
- user query normalization issue
- source not connected
- stale snapshot / update lag
- parser/schema failure
- auth/rate limit
- license blocked
- likely user misunderstanding

Only the first category is healthy. All other categories should produce source backlog, parser backlog, docs copy, or UX prompt changes.

## 8. Pricing and cost preview consistency checks

### 8.1 Canonical pricing invariants

These must match everywhere:

- `pricing_version=2026-05-15` until intentionally changed.
- `pricing_model=metered_units`.
- `unit_price_ex_tax_jpy=3`.
- `unit_price_inc_tax_jpy=3.3`.
- anonymous execution allowance is `3 req/day/IP`.
- cost preview is free.
- cost preview does not consume anonymous execution quota.
- paid execution requires API key.
- paid fanout/batch/CSV/watchlist/packet execution requires cap before billable work.
- paid retry-sensitive execution requires `Idempotency-Key`.
- external LLM/search/cloud/agent/SaaS costs are not included.
- no charge for preview, auth failure, validation failure, cap reject, quota reject, server error without successful output, and no-hit unless a future explicitly priced no-hit check exists.

### 8.2 Surfaces to compare

| Surface | Fields extracted |
|---|---|
| pricing page | unit price, tax mode, no minimum, anonymous allowance, external-cost exclusion |
| `.well-known/llms.json` | pricing object, external costs, upgrade URL |
| `.well-known/mcp.json` | pricing, auth, preview/cap requirements |
| `server.json` | registry pricing text/object |
| `mcp-server.json` | tool-level billing language |
| OpenAPI full/agent | `x-jpcite-billing`, endpoint descriptions, examples |
| packet examples | `billing_metadata` fields |
| cost preview response | predicted units, ex/inc tax, cap check, not included |
| live packet response | billing metadata and reconciliation |
| Stripe product/price/meter | unit and tax compatibility |
| UI calculator | rendered totals and cap label |

### 8.3 Cost preview arithmetic fixtures

| Fixture | Expected |
|---|---|
| 1 packet | ex-tax 3, inc-tax 3.3 |
| 84 billable subjects | ex-tax 252, inc-tax 277.2 |
| 25 source receipts | 1 receipt-set unit, ex-tax 3, inc-tax 3.3 |
| 26 source receipts | 2 receipt-set units, ex-tax 6, inc-tax 6.6 |
| 10 program compatibility matrix | 45 pairs, ex-tax 135, inc-tax 148.5 |
| cap 300 on 84 units | execute allowed |
| cap 270 on 84 units | reject before billable work |
| auth failure | no usage event |
| idempotency retry same payload | no duplicate charge |
| idempotency same key different payload | 409 conflict, not billed again |
| no-hit execution | no-hit units not billed and reconciliation explains difference |

### 8.4 Pricing drift severity

| Severity | Example |
|---|---|
| P0 | public surface says `税込3円`, `LLM費用込み`, `free unlimited`, or preview consumes quota |
| P0 | cost preview math differs from live billing metadata |
| P0 | Stripe meter would charge a different unit than public contract |
| P1 | old pricing anchor URL or docs path but correct price elsewhere |
| P1 | optional docs example lacks `external_costs_included=false` |
| P2 | copy wording is less clear but not contradictory |

## 9. Public contract drift matrix

The following fields should be treated as cross-surface contract keys.

| Contract key | Must match across |
|---|---|
| brand/site/API host | `llms*`, `.well-known/*`, OpenAPI servers, MCP manifests, docs, package metadata |
| product category | `llms*`, `.well-known/llms.json`, agents manifest, server descriptions, docs |
| P0 packet types | packet schema, examples, OpenAPI, MCP, packet catalog, docs |
| P0 first-call tools | `.well-known/mcp.json`, `mcp-server.json`, OpenAPI, docs/agents |
| no-LLM invariant | packet examples, OpenAPI responses, tool descriptions, llms, docs |
| source receipts / known gaps | examples, schemas, OpenAPI components, runtime samples, docs |
| no-hit caveat | examples, tool descriptions, docs, runtime no-hit fixtures |
| professional fence | all discovery pages, tool descriptions, API examples, pricing/trust/legal |
| pricing | pricing page, manifests, OpenAPI extensions, cost preview, billing metadata, Stripe |
| cost preview/cap/idempotency | OpenAPI, MCP descriptions, docs recipes, live preview, paid execution errors |
| external cost separation | pricing, cost preview, manifests, OpenAPI, agent copy |
| freshness policy | source profiles, receipts, examples, docs, stale packets |
| license boundary | source profiles, receipts, data licensing page, examples |

## 10. Alert routing

Integrate with existing ops routing:

- P0: SMS/page when public contract can cause immediate AI misrecommendation, wrong billing, no-hit-as-absence, final judgment, or broken discovery.
- P1: email within 1 hour for source freshness degradation, non-P0 copy drift, mirror docs drift, no-hit spikes, or broken non-primary links.
- P2: weekly digest for review backlog, wording quality, old redirects, source profile unknowns, and low-risk link rot.

P0 alert examples:

- `.well-known/llms.json` unreachable or invalid.
- `openapi.agent.json` mirror differs from canonical generated agent spec.
- cost preview reports wrong price or bills/quota-counts preview.
- public example says no-hit means no registration/no risk/no administrative action.
- P0 packet response has a claim without receipt.
- pricing page says external LLM costs are included.
- MCP tool description says subsidy approval/final legal advice/audit complete.

P1 alert examples:

- source family stale ratio > threshold.
- no-hit spike suggests parser/source drift.
- docs mirror OpenAPI differs but public agent spec remains correct.
- cookbook skips cost preview before broad paid batch.
- non-P0 page contains ambiguous cost-savings language.

## 11. Incident response

### 11.1 Severity taxonomy

| Severity | Meaning | Response target |
|---|---|---|
| P0 contract incident | Active public surface can make AI agents recommend/call jpcite incorrectly or misquote price/fence/no-hit | acknowledge within 15 min, mitigate within 1 h |
| P1 degradation | Decreases recommendation quality or evidence trust but primary contract still intact | triage same day |
| P2 backlog | Cleanup or clarity improvement | weekly review |

### 11.2 Rollback-free repair flow

Rollback is not the default for contract drift because many drifts are generated/mirrored surfaces, stale docs, or public copy inconsistencies. The default repair is:

1. Freeze new distribution changes.
   - Stop deploys that touch `site/`, OpenAPI, MCP manifests, pricing, examples, schemas, package metadata, or `.well-known`.
   - Do not revert unrelated parallel work.

2. Classify the bad surface.
   - `source-of-truth wrong`: implementation metadata/template/schema/source profile is wrong.
   - `generated mirror stale`: source is correct but mirror was not regenerated/deployed.
   - `hand-authored copy drift`: prose says something stronger/weaker than contract.
   - `runtime contract drift`: API behavior diverges from examples/spec.
   - `external config drift`: Stripe/registry/CDN/cache differs from repo.

3. Contain exposure without rolling back unrelated code.
   - If a static public file is dangerously wrong, publish a minimal corrected static file or remove the bad recommendation path from discovery.
   - If a generated mirror is stale, redirect to the canonical live spec if safe.
   - If a runtime packet is unsafe, mark affected packet/tool as unavailable or force `human_review_required` / blocking known gap until repaired.
   - If pricing is wrong, disable paid execution path or require preview/cap while correcting public copy and Stripe config.

4. Repair the authoritative source.
   - Fix template/source registry/schema/OpenAPI route metadata/pricing config, not only the generated output.
   - For copy drift, update the smallest canonical copy block and regenerate derived copies where possible.
   - For source freshness/no-hit, repair source profile/ingest/parser/ledger semantics before changing examples.

5. Regenerate all mirrors in the same repair packet.
   - Full OpenAPI, agent OpenAPI, static mirrors, site mirrors, MCP manifests, llms full files, packet examples, schemas, sitemap if affected.
   - Keep generated files in a separate commit/lane where possible.

6. Purge or shorten caches.
   - Purge CDN for affected P0 discovery URLs.
   - Confirm cache headers no longer serve stale bad contract.
   - Update `.well-known` and llms files first because agents read them early.

7. Verify with the same detector that failed.
   - Re-run structural diff, semantic lint, live probe, replay fixture, and relevant agent eval subset.
   - Do not close incident until the detector is green and a live URL fetch confirms the fix.

8. Publish internal incident note.
   - Document root cause, bad surface, blast radius, detector gap, repair commands, verification hash, and follow-up prevention.

### 11.3 Repair by incident type

| Incident | Immediate containment | Durable repair |
|---|---|---|
| wrong price in public copy | replace/patch pricing surface and manifests; disable paid CTA only if live billing can overcharge | canonical price block and extractor tests |
| cost preview math wrong | disable paid execution requiring preview; show maintenance for preview if needed | fix arithmetic/rounding, add fixture |
| OpenAPI mirror stale | point importer docs to canonical live spec; purge stale mirror | regenerate all OpenAPI mirrors and hash-check |
| MCP tool description unsafe | remove P0 recommendation for affected tool from `.well-known/mcp.json` | fix tool metadata source and regenerate manifest |
| no-hit-as-absence example | remove/replace example from sitemap/llms links | update example generator and no-hit fixture |
| stale source exposed as current | mark source/packet stale with known gap; pause affected packet recommendation | repair freshness ledger and packet composer behavior |
| schema/gap enum drift | freeze example/schema updates | update schema SOT and regenerate examples/OpenAPI |
| Stripe price drift | pause paid checkout/API-key issuance if overcharge/undercharge material | align Stripe config and public pricing snapshot |
| robots blocks discovery | direct static fix to robots | add parser check to nightly gate |

### 11.4 Incident note template

```text
# GEO contract drift incident - YYYY-MM-DD

severity:
detected_by:
first_bad_seen_at:
first_good_seen_at:
surfaces_affected:
contract_keys_affected:
blast_radius:

root_cause:
- source-of-truth wrong | generated mirror stale | hand copy drift | runtime drift | external config drift

containment:
- actions:
- public URLs verified:

repair:
- source files/config changed:
- generated artifacts regenerated:
- caches purged:

verification:
- detector rerun:
- live URL hashes:
- cost/no-hit/freshness fixtures:
- agent eval subset:

followups:
- new detector:
- owner:
- due:
```

## 12. Implementation sequencing

This is an operations plan, not a code change request, but implementation should be sequenced with low blast radius.

### Phase 0: Manual checklist before first GEO release

- Create canonical contract checklist from this document.
- Manually inspect P0 discovery files, pricing, OpenAPI, MCP, examples.
- Run curl/live probes for all P0 URLs.
- Validate packet examples by hand or with existing JSON tooling.
- Run cost preview arithmetic manually against documented fixtures.
- Confirm no public copy contains prohibited expressions.

### Phase 1: Offline nightly detector

- Add a read-only drift checker that fetches public URLs and local generated files.
- Produce internal Markdown/JSON report only.
- No auto-repair.
- Alert only on clear P0 contradictions.

### Phase 2: Source freshness/no-hit telemetry

- Add nightly aggregates for source freshness, no-hit spikes, receipt completeness.
- Join with existing R2/DB telemetry without high-cardinality Prometheus labels.
- Include top no-hit clusters in weekly digest.

### Phase 3: Pricing and billing parity

- Add cost preview fixture probes.
- Add Stripe product/price/meter weekly parity check.
- Add billing metadata vs preview reconciliation samples.

### Phase 4: Agent eval harness integration

- Run 50-query weekly eval.
- Require green subset before release touching OpenAPI/MCP/llms/pricing/examples.
- Track forbidden claim count and field preservation.

### Phase 5: Release gate

Any PR/release touching public contract surfaces must include:

- affected contract keys
- regenerated artifacts list
- drift checker output
- cost preview fixture output if pricing/billing touched
- no-hit/freshness fixture output if source/packet touched
- agent eval subset if recommendation/tool descriptions changed

## 13. Acceptance criteria

P0 acceptable state:

- Every P0 discovery URL returns 200 or intentional canonical redirect.
- Manifest drift count is zero for brand, site/API host, price, no-LLM, professional fence, no-hit, external costs, P0 tools, P0 packet types.
- Agent OpenAPI static/live mirrors match.
- MCP manifests and `.well-known/mcp.json` agree on P0 tool names, auth, transport, billing posture.
- Public packet examples validate and contain `source_receipts`, `known_gaps`, `human_review_required`, `request_time_llm_call_performed=false`, and `billing_metadata`.
- Cost preview fixtures return correct 3/3.30 math, do not bill, and do not consume anonymous quota.
- No runtime sampled supported claim lacks a receipt.
- No no-hit sample lacks `no_hit_not_absence`.
- No stale sample lacks `known_gaps.source_stale`.
- No public P0 copy claims final professional judgment, official absence, complete coverage, real-time truth, guaranteed cost savings, or bundled external LLM cost.

P1 acceptable state:

- Source freshness stale/blocked rates are visible by source family.
- No-hit spikes are visible with query/source clusters.
- Weekly agent eval shows correct recommendation behavior and zero forbidden claims.
- Stripe/public pricing parity is checked weekly.
- Generated artifact lane boundaries are visible in release notes.

## 14. Open questions

- Which file should become the implementation-owned canonical contract snapshot: generated internal JSON, package metadata, or docs-derived config?
- Should `/discovery/contract.json` be public in P0, or stay internal until P1?
- Which live fixtures are safe to run nightly against production without consuming user-visible quota or creating misleading usage?
- How should no-hit and stale fixture subjects be chosen so they remain stable but do not encode private/customer data?
- What is the exact CDN/cache purge mechanism for `.well-known`, `llms*`, OpenAPI, MCP manifests, pricing, and examples?
- Should P0 contract drift block all deploys, or only deploys touching public contract/generator lanes?

## 15. Minimal operator checklist

Before any public GEO contract release:

1. Fetch `.well-known/llms.json`, `.well-known/mcp.json`, `llms.txt`, `openapi.agent.json`, `mcp-server.json`, pricing, and examples from production URLs.
2. Confirm price is 3 JPY ex-tax / 3.30 JPY inc-tax everywhere.
3. Confirm external LLM/search/agent/runtime costs are excluded everywhere.
4. Confirm no-hit is never absence.
5. Confirm no final legal/tax/audit/credit/application judgment is implied.
6. Confirm P0 examples include receipts, gaps, review flag, no-LLM flag, and billing metadata.
7. Run cost preview fixtures.
8. Run no-hit and stale fixtures.
9. Run OpenAPI/MCP/llms parity diff.
10. Record the drift report path/hash in the release note.
