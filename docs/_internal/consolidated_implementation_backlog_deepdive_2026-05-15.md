# Consolidated implementation backlog deep dive

Date: 2026-05-15
Status: implementation-ready backlog, pre-code
Owner lane: Consolidated epic decomposition / implementation-ready backlog
Scope: consolidate the 2026-05-15 deep-dive specs into one P0/P1/P2 implementation backlog.

This document is the implementation intake layer after the 40-spec planning pass. It deduplicates overlapping specs into epics, identifies hard dependencies, and defines acceptance gates before runtime code work starts.

## 0. Executive backlog

Implement the GEO-first packet product in this order:

1. Freeze one packet contract and one runtime catalog.
2. Build source receipt, claim, known-gap, no-hit, and quality primitives.
3. Add deterministic pricing and free cost preview before any paid execution.
4. Add privacy-preserving CSV analyze/preview before CSV packet generation.
5. Implement P0 packet composers as thin service layers over existing data.
6. Expose the same catalog through REST, MCP, OpenAPI, public pages, proof pages, `llms.txt`, and `.well-known`.
7. Add cross-surface drift tests and release blockers.

The central implementation invariant:

> Packet names, fields, pricing units, source receipt rules, known-gap enums, REST routes, MCP tool names, OpenAPI examples, public page URLs, and discovery metadata must originate from one catalog or be drift-tested against it.

## 1. P0 epic list

P0 is the minimum implementation set required before the product can be truthfully presented to AI agents as a source-backed, priced, safe packet API.

| Epic | Purpose | Primary outputs | Depends on | Blocks |
| --- | --- | --- | --- | --- |
| P0-E1 Packet contract and catalog | Define one stable envelope and one packet registry. | Common schema, six P0 entries, examples, slug/route/tool/price/url metadata. | None | All other P0 epics |
| P0-E2 Source receipts, claims, known gaps | Make every reusable claim source-backed or explicitly gapped. | `source_receipts`, `claim_refs`, `known_gaps`, `no_hit_not_absence`, quality scoring. | P0-E1 | P0-E5, P0-E8 |
| P0-E3 Pricing policy and cost preview | Prevent billing surprise and duplicate charges. | Pricing registry, `POST /v1/cost/preview`, cap/idempotency policy. | P0-E1 | P0-E4, P0-E6, P0-E7 |
| P0-E4 CSV privacy and intake preview | Allow accounting CSV value without raw/private leakage. | Analyze/preview flow, aggregate-only derived facts, rejection/redaction rules. | P0-E1, P0-E3 | `client_monthly_review` |
| P0-E5 P0 packet composers | Produce implementation-ready packet outputs. | Six composers: `evidence_answer`, `company_public_baseline`, `application_strategy`, `source_receipt_ledger`, `client_monthly_review`, `agent_routing_decision`. | P0-E1, P0-E2, P0-E3, P0-E4 for CSV packet | REST/MCP/site |
| P0-E6 REST packet facade | Expose P0 packets through one API surface. | Catalog, preview, packet endpoints, existing error envelope, guard order. | P0-E1, P0-E3, P0-E5 | OpenAPI, site examples |
| P0-E7 MCP agent-first tools | Expose the same packets to agent clients. | MCP wrappers, manifest entries, sample args, output metadata. | P0-E1, P0-E3, P0-E5 | Agent discovery |
| P0-E8 Public proof and discovery surfaces | Make packet value discoverable and verifiable by agents. | Packet pages, proof pages, pricing page, OpenAPI agent subset, `llms.txt`, `.well-known`. | P0-E1, P0-E2, P0-E3, P0-E6, P0-E7 | Release readiness |
| P0-E9 Drift, privacy, billing, and release gates | Block inconsistent or unsafe release. | CI target, static scans, operator checklist, release blockers. | P0-E1 through P0-E8 | Release |

## 2. P0 epic detail

### P0-E1 Packet contract and catalog

Purpose:

- Turn the planning contracts into one additive runtime contract without breaking existing Evidence Packet or ArtifactResponse clients.
- Establish the catalog as the source of truth for packet type, route, MCP tool, pricing unit, public page, examples, known-gap set, and preserve fields.

Implementation file candidates:

- `src/jpintel_mcp/models/packet_contract.py`
- `schemas/packet_contract.v1.json`
- `src/jpintel_mcp/services/packet_catalog.py`
- `src/jpintel_mcp/api/packets.py`
- `tests/fixtures/p0_packets/*.json`

Acceptance:

- Six P0 packet types exist: `evidence_answer`, `company_public_baseline`, `application_strategy`, `source_receipt_ledger`, `client_monthly_review`, `agent_routing_decision`.
- Every example validates against the common envelope.
- `request_time_llm_call_performed=false` is required.
- `billing_metadata`, `source_receipts`, `known_gaps`, `quality`, `fence`, and `agent_guidance` exist on every packet.
- Legacy fields are preserved or aliased; no existing response shape is removed.

Tests:

- `tests/test_p0_packet_contract.py`
- `tests/test_p0_packet_catalog.py`
- `tests/test_openapi_response_models.py` for compatibility

Docs/site updates:

- Public packet catalog can be generated from catalog metadata.
- `docs/api-reference.md`, `docs/mcp-tools.md`, `docs/pricing.md`, packet examples, and discovery files must not hand-copy packet constants without a drift test.

### P0-E2 Source receipts, claims, known gaps

Purpose:

- Make jpcite's GEO value concrete: a packet is useful because claims carry source accountability, not because the prose sounds confident.
- Standardize source profile, source document, source receipt, claim ref, no-hit, and known-gap semantics.

Implementation file candidates:

- `src/jpintel_mcp/ingest/schemas/public_source_foundation.py`
- `src/jpintel_mcp/services/source_profile_registry.py`
- `src/jpintel_mcp/services/source_receipts.py`
- `src/jpintel_mcp/services/known_gaps.py`
- `src/jpintel_mcp/services/quality_gaps.py`
- `src/jpintel_mcp/services/evidence_packet.py`
- `data/source_profile_registry.jsonl`
- `scripts/etl/backfill_source_profile_registry.py`
- Migration candidate: `scripts/migrations/291_geo_source_receipts_foundation.sql`

Acceptance:

- Every externally reusable claim has at least one `source_receipt_id`; unsupported facts move to `known_gaps`.
- Complete receipts include source URL or identifier, fetched/verified time, content hash or checksum, corpus snapshot, license boundary, support level, freshness, `used_in`, and `claim_refs`.
- Missing receipt fields create `source_receipt_missing_fields` gap.
- `no_hit` is never exposed as absence; use `no_hit_not_absence`.
- Private CSV-derived claims use a private namespace and never enter public source foundation tables.

Tests:

- `tests/test_p0_source_receipts_contract.py`
- `tests/test_p0_source_receipt_ledger_packet.py`
- `tests/test_known_gaps_contract.py`
- `tests/test_quality_gaps.py`

Docs/site updates:

- Proof pages show receipt completeness, stale/unknown source status, no-hit caveats, and known gaps.
- Public examples must preserve `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, `license_boundary`, and `known_gaps`.

### P0-E3 Pricing policy and cost preview

Purpose:

- Give humans and agents a free, machine-readable estimate before paid execution.
- Ensure retry, cap, auth, and validation controls run before metering.

Implementation file candidates:

- `src/jpintel_mcp/services/pricing_policy.py`
- `src/jpintel_mcp/api/cost.py`
- `src/jpintel_mcp/api/middleware/cost_cap.py`
- `src/jpintel_mcp/billing/stripe_usage.py`
- `src/jpintel_mcp/billing/stripe_edge_cases.py`
- `src/jpintel_mcp/billing/keys.py`

Acceptance:

- `POST /v1/cost/preview` is free, does not consume anonymous 3/day/IP execution quota, and creates no billable usage.
- Paid broad execution requires API key, hard cap, and `Idempotency-Key` before billable work starts.
- Same idempotency key plus same normalized payload returns the same execution result; same key plus different payload returns `409 idempotency_conflict` without billing.
- Cap compares against conservative税込 max estimate before work starts.
- External LLM, agent runtime, search, cloud, SaaS connector, and MCP client costs are explicitly excluded.
- Pricing constants are centralized under `pricing_version=2026-05-15`.

Tests:

- `tests/test_p0_cost_preview.py`
- `tests/test_usage_billing_idempotency.py`
- `tests/test_billing_risk_controls.py`
- Static scan for duplicate or forbidden pricing copy.

Docs/site updates:

- Pricing page and packet pages show free preview, unit price, tax display, external cost exclusion, cap behavior, and no-charge rejection states.
- MCP and OpenAPI examples include preview-before-execute guidance for paid/broad operations.

### P0-E4 CSV privacy and intake preview

Purpose:

- Support accounting CSV use cases while respecting the boundary that CSV is private operational input, not a public source.
- Generate aggregate-only facts for packet composers.

Implementation file candidates:

- `src/jpintel_mcp/services/csv_intake.py`
- `src/jpintel_mcp/api/csv_intake.py`
- `src/jpintel_mcp/security/pii_redact.py`
- `src/jpintel_mcp/services/packets/client_monthly_review.py`
- `tests/fixtures/csv_intake/*.csv` with synthetic data only

Acceptance:

- CSV raw bytes, raw rows, row-level normalized records, free-text memo, counterparty names, personal identifiers, payroll detail, and bank account data are not persisted, logged, or echoed.
- Flow is split into analyze, preview, and paid packet execution.
- Preview returns row count, accepted/rejected/duplicate/unresolved counts, billable subject count, projected units, and cap requirement.
- Payroll/bank/personal-identifier files are rejected or reduced to aggregate-only review state.
- Formula-like cells are never emitted in Markdown, JSON examples, CSV exports, logs, prompts, or errors.
- Small aggregates are suppressed or coarsened where re-identification risk exists.

Tests:

- `tests/test_p0_csv_intake.py`
- `tests/test_dim_n_pii_redact_strict.py`
- Static leak scan for raw CSV fixture values in packets, docs, logs, and examples.

Docs/site updates:

- CSV intake page explains accepted aggregate outputs, rejected inputs, preview/cap requirement, and no raw-row persistence.
- Examples must use synthetic values and aggregate-only output.

### P0-E5 P0 packet composers

Purpose:

- Produce the first implementation slice of source-backed packet outputs.
- Keep composers thin: they assemble contract-compliant packets from source receipts, known gaps, pricing metadata, and existing domain services.

Implementation file candidates:

- `src/jpintel_mcp/services/packets/evidence_answer.py`
- `src/jpintel_mcp/services/packets/company_public_baseline.py`
- `src/jpintel_mcp/services/packets/application_strategy.py`
- `src/jpintel_mcp/services/packets/source_receipt_ledger.py`
- `src/jpintel_mcp/services/packets/client_monthly_review.py`
- `src/jpintel_mcp/services/packets/agent_routing_decision.py`
- Existing adapters: `src/jpintel_mcp/services/evidence_packet.py`, `cross_source.py`, `funding_stack_checker.py`, `citation_verifier.py`

Acceptance:

- Composers are directly unit-callable without HTTP or MCP transport.
- Every packet preserves receipts, known gaps, billing metadata, human review status, and professional fence.
- `company_public_baseline` requires stable identity in P0; ambiguous name-only input returns identity gap or validation error.
- `application_strategy` ranks candidates but never states final eligibility, approval, or legal/tax conclusion.
- `client_monthly_review` consumes normalized aggregate derived facts only.
- `agent_routing_decision` can be free preflight and must explain when to use jpcite, when not to, cost preview, API key, caps, and source preservation.

Tests:

- `tests/test_p0_evidence_answer_packet.py`
- `tests/test_p0_company_public_baseline_packet.py`
- `tests/test_p0_application_strategy_packet.py`
- `tests/test_p0_client_monthly_review_packet.py`
- `tests/test_p0_agent_routing_decision_packet.py`
- `tests/test_p0_packet_fence.py`

Docs/site updates:

- One public example page per P0 packet with sample input, sample output, source receipts, known gaps, legal/accounting fence, REST call, MCP tool, and pricing block.

### P0-E6 REST packet facade

Purpose:

- Expose the catalog and packet outputs through stable API routes while keeping guard order consistent.

Implementation file candidates:

- `src/jpintel_mcp/api/packets.py`
- `src/jpintel_mcp/api/main.py`
- `src/jpintel_mcp/api/cost.py`
- `scripts/export_openapi.py`
- `docs/openapi/v1.json`
- `docs/openapi/agent.json`

Acceptance:

- REST exposes catalog, cost preview, and P0 packet endpoints.
- Paid execution guard order is auth, validation, idempotency, cap, billable work, meter-on-success.
- Errors use the existing error envelope.
- REST has no local copy of packet pricing or discovery metadata outside catalog/policy.
- OpenAPI is generated from or drift-tested against actual route names and validated examples.

Tests:

- `tests/test_p0_packets_api.py`
- `tests/test_openapi_agent.py`
- `tests/test_openapi_response_models.py`
- `tests/test_p0_openapi_mcp_catalog_drift.py`

Docs/site updates:

- `docs/api-reference.md` and OpenAPI agent-safe subset describe only agent-safe P0 operations, with admin/internal routes excluded.

### P0-E7 MCP agent-first tools

Purpose:

- Let AI agents call the same P0 packet functionality without a divergent MCP product surface.

Implementation file candidates:

- `src/jpintel_mcp/mcp/jpcite_tools/packet_tools.py`
- `src/jpintel_mcp/mcp/server.py`
- `mcp-server.core.json`
- `mcp-server.full.json`
- `scripts/sync_mcp_public_manifests.py`
- `scripts/check_mcp_drift.py`

Acceptance:

- MCP tools match catalog names and call the same composers as REST.
- Tool schemas include sample arguments and preserve source receipts, known gaps, billing metadata, and professional fence.
- Existing aliases either remain compatible or are documented as deprecated with no silent behavior change.
- MCP outputs differ from REST only by transport envelope.

Tests:

- `tests/test_p0_packets_mcp.py`
- `tests/test_mcp_public_manifest_sync.py`
- `tests/test_mcp_drift_version.py`
- `tests/test_p0_openapi_mcp_catalog_drift.py`

Docs/site updates:

- `docs/mcp-tools.md`, install snippets, MCP manifests, and agent playbooks reference the same tool names and packet examples.

### P0-E8 Public proof and discovery surfaces

Purpose:

- Turn runtime packets into machine-readable public evidence that agents can find, quote, and route to.

Implementation file candidates:

- `docs/packets/*.md`
- `docs/proof/*.md`
- `docs/pricing.md`
- `docs/api-reference.md`
- `docs/mcp-tools.md`
- `docs/assets/*` only if existing docs generator needs assets
- `mkdocs.yml`
- `site/openapi.agent.json`
- `site/.well-known/openapi-discovery.json`
- `.well-known/agents.json`
- `.well-known/mcp.json`
- `llms.txt`
- Generator candidate: `scripts/generate_packet_pages.py`

Acceptance:

- Each public packet page includes sample input, output JSON, source receipts, known gaps, billing metadata, REST endpoint, MCP tool, cost preview behavior, and professional fence.
- Proof pages expose claim ledger and receipt ledger without overclaiming source completeness.
- `llms.txt` and `.well-known` point to current packet catalog, MCP, OpenAPI, pricing, and proof pages.
- Public copy avoids final eligibility, approved, no risk, complete coverage, real-time guarantee, and LLM cost guarantee claims.

Tests:

- `tests/test_p0_public_packet_pages.py`
- `tests/test_p0_geo_discovery_surfaces.py`
- `tests/test_p0_geo_forbidden_claim_scan.py`
- `tests/e2e/test_public_pages.py`

Docs/site updates:

- This epic is the docs/site update. Public pages should be generated from checked examples or verified against the catalog.

### P0-E9 Drift, privacy, billing, and release gates

Purpose:

- Prevent launch with inconsistent metadata, accidental billing, private-data leaks, or unsafe claims.

Implementation file candidates:

- `scripts/check_mcp_drift.py`
- `scripts/export_openapi.py`
- `scripts/check_packet_catalog_drift.py`
- `scripts/check_public_packet_pages.py`
- `docs/runbook/*`
- `docs/_internal/*release*` or a new internal operator checklist

Acceptance:

- One focused CI target covers packet contract, catalog, receipts, known gaps, cost preview, billing guard order, CSV privacy, API/MCP drift, public pages, and forbidden claims.
- Release blocks if packet catalog differs from OpenAPI, MCP, public pages, or discovery files.
- Release blocks if pricing constants diverge.
- Release blocks if raw/private CSV values appear in outputs, logs, docs, fixtures, or examples.
- Release blocks if `packet_id` lookup is documented without persistence/access control.

Tests:

- `pytest tests/test_p0_* tests/test_openapi_agent.py tests/test_mcp_public_manifest_sync.py tests/test_usage_billing_idempotency.py`
- Static scans for forbidden billing phrases, forbidden professional claims, API key leakage, and raw CSV fixture leakage.

Docs/site updates:

- Operator checklist for release, rollback, known limitations, non-billable rejection states, and support handling of CSV privacy reports.

## 3. P1 epic list

P1 expands value and durability after the P0 control plane is stable.

| Epic | Purpose | Implementation file candidates | Acceptance | Docs/site updates |
| --- | --- | --- | --- | --- |
| P1-E1 Persistence and replay | Add `packet_runs` only if replay, export, audit lookup, or paid support requires it. | `scripts/migrations/*packet_run*.sql`, `src/jpintel_mcp/services/packet_runs.py`, usage/idempotency linkage | Access-controlled packet lookup works; inline-only gap removed only after tests pass. | API reference documents lookup semantics and retention. |
| P1-E2 Public source expansion | Increase source coverage beyond P0 sources. | `data/source_profile_registry.jsonl`, ingest cron jobs, source adapters, `source_catalog` migration extensions | New sources have license boundary, freshness window, join keys, no-hit behavior, and receipt tests. | Source coverage/proof pages update from registry. |
| P1-E3 Algorithmic outputs | Add ranking, similarity, anomaly, period comparison, dedupe, confidence, and change detection as explainable algorithms. | `src/jpintel_mcp/analytics/*`, `services/packets/*`, evaluation fixtures | Algorithm outputs include version, inputs, weights, confidence, gaps, and no final judgment claims. | Methodology pages explain models without overclaiming. |
| P1-E4 CSV provider templates | Improve freee/Money Forward/Yayoi/kintone/accounting import mapping. | `src/jpintel_mcp/services/csv_provider_aliases.py`, `csv_intake.py`, synthetic fixtures | Provider-specific header aliases normalize to aggregate facts with privacy tests. | CSV intake guide adds supported templates and fallback behavior. |
| P1-E5 Full ICP packet catalog | Add practitioner-specific packets beyond six P0 packets. | `services/packets/*`, catalog entries, fixtures | Each new packet passes contract, receipt, pricing, fence, API/MCP/site drift tests. | Packet catalog pages by user type. |
| P1-E6 Proof page UX and audit ledger depth | Improve claim/receipt browsing, filters, hashes, freshness, and verification UX. | `docs/proof/*.md`, page generator, ledger schemas | Proof pages support packet, source, claim, and gap drill-down without private data. | Public proof pages and screenshots. |
| P1-E7 Billing risk controls depth | Add anomaly alerts, monthly caps, abuse detection, Stripe reconciliation, and chargeback evidence. | `billing/*`, `scripts/cron/predictive_billing_alert.py`, `stripe_reconcile.py` | Abuse scenarios have tests and operator alerts. | Billing runbooks and pricing FAQ. |
| P1-E8 Agent surface playbooks | Publish tested setup paths for ChatGPT, Claude, Cursor, Cline, Gemini, OpenAI Agents, LangChain/LlamaIndex. | `docs/integrations/*`, MCP/OpenAPI examples | Each playbook has current install snippet, auth warning, cost preview, and fallback. | Integration docs and `llms.txt` entries. |
| P1-E9 GEO evaluation harness | Measure whether agents discover, recommend, preserve, and cite jpcite correctly. | `scripts/eval/*`, `docs/geo_eval_query_set_100.md`, eval fixtures | Evaluation reports pass routing, recommendation, citation, and forbidden-claim criteria. | GEO methodology and benchmark pages. |

## 4. P2 epic list

P2 is scale, automation, and market expansion after P0/P1 contracts are proven.

| Epic | Purpose | Implementation file candidates | Acceptance | Docs/site updates |
| --- | --- | --- | --- | --- |
| P2-E1 Large-scale prebuilt packet generation | Generate broad public example packets and SEO/GEO pages from source foundation. | packet/page generators, scheduled jobs, static publishing | Generated pages pass receipt, gap, copy, and drift gates at scale. | Expanded packet and proof libraries. |
| P2-E2 Watchlists, webhooks, and recurring monitors | Turn one-shot packets into recurring customer workflows. | `src/jpintel_mcp/services/*watch*`, `webhooks`, cron jobs | Watchlist events are idempotent, capped, metered, and source-backed. | Webhook docs, alerts guide, operator guide. |
| P2-E3 Marketplace and directory distribution | Package MCP/OpenAPI listings for external directories. | `docs/marketplace/*`, `scripts/publish_to_mcp_registries.py` | Directory metadata matches catalog and current manifests. | Marketplace submission docs. |
| P2-E4 Enterprise controls | Add org keys, audit exports, retention policy, DSR support, security posture depth. | billing keys, tenant controls, compliance docs, audit trail | Org-level access and retention behavior are tested and documented. | Security/compliance pages. |
| P2-E5 Advanced source acquisition automation | Automate license checks, freshness recovery, parser drift, and acquisition backlog. | ingest cron jobs, source registry checks, freshness alerts | Source drift creates gaps and operator tasks before stale claims leak. | Source methodology and coverage dashboard. |
| P2-E6 Multilingual and international surfaces | Improve English and agent-facing language variants. | i18n docs, generated pages, OpenAPI descriptions | Language variants preserve legal fence and pricing/source semantics. | English docs and localized integration pages. |
| P2-E7 Partner integrations | Deepen freee, Money Forward, SmartHR, kintone, accounting/BPO workflows. | integration adapters, docs, OAuth/runbooks if approved | Partner flows keep CSV privacy, caps, and source receipts intact. | Partner pages and integration runbooks. |

## 5. Cross-epic dependency map

Hard dependencies:

- P0-E1 blocks every implementation epic.
- P0-E2 blocks any packet that exposes claims, proof pages, and public examples.
- P0-E3 blocks paid REST/MCP execution, CSV/batch/fanout, pricing pages, and agent routing claims.
- P0-E4 blocks `client_monthly_review` and any CSV-derived public or private output.
- P0-E5 blocks REST, MCP, OpenAPI examples, public packet pages, and proof pages.
- P0-E6 blocks generated OpenAPI and REST examples.
- P0-E7 blocks MCP manifests, MCP docs, and agent integration playbooks.
- P0-E8 blocks GEO launch readiness.
- P0-E9 blocks release.

Recommended PR order:

| PR | Scope | Merge gate |
| --- | --- | --- |
| PR1 | Packet contract, examples, catalog | `test_p0_packet_contract`, `test_p0_packet_catalog` |
| PR2 | Source receipts, claim refs, known gaps, no-hit | source receipt and known-gap tests |
| PR3 | Pricing policy, cost preview, billing guard order | cost preview and idempotency tests |
| PR4 | CSV analyze/preview and privacy controls | CSV privacy and leak scans |
| PR5 | P0 composers | packet composer unit tests |
| PR6 | REST facade | API contract and OpenAPI response tests |
| PR7 | MCP wrappers | MCP catalog and manifest tests |
| PR8 | OpenAPI, docs, site, discovery generation | public page, discovery, forbidden-claim, drift tests |
| PR9 | Release hardening | focused P0 CI target and operator checklist |

## 6. Shared acceptance checklist

P0 cannot ship until all items below are true:

- Packet catalog, REST, MCP, OpenAPI, public pages, pricing, and discovery files agree on packet names, routes, tool names, prices, and required fields.
- Every reusable claim has a source receipt or is moved to known gaps.
- `no_hit` is represented as `no_hit_not_absence`.
- Paid execution cannot meter before auth, validation, idempotency, cap, and successful output.
- Cost preview is free and does not consume anonymous execution quota.
- CSV raw rows/private values are not persisted, logged, echoed, or included in examples.
- Public pages and examples avoid final legal/tax/accounting/eligibility/credit claims.
- Existing Evidence Packet and ArtifactResponse clients are not broken by the P0 facade.
- If `packet_id` lookup is documented, persistence and access control are implemented; otherwise inline-only behavior is explicitly gapped.
- Migration inventory and existing drift checks pass if schema changes are introduced.

## 7. Non-goals

These are explicitly out of scope for the first implementation pass:

- Do not build a second packet metadata source in docs, OpenAPI, MCP manifest, or frontend copy.
- Do not claim final eligibility, approval, legal/tax/accounting/audit judgment, credit safety, no risk, complete source coverage, real-time freshness, or guaranteed LLM cost reduction.
- Do not treat `no_hit` as proof of absence.
- Do not persist raw CSV bytes, raw rows, row-level normalized records, free-text memo, counterparty values, personal identifiers, payroll detail, or bank account details.
- Do not make Evidence Packet composer responsible for source foundation writes.
- Do not expose internal/admin endpoints in the agent-safe OpenAPI subset.
- Do not implement partner OAuth, enterprise org controls, broad watchlists, or recurring monitors in P0.
- Do not document packet replay or lookup until persistence and access control exist.
- Do not hand-edit public packet pages in ways that can drift from runtime catalog.
- Do not expand to many new packet types before the six P0 packets pass the shared contract and drift gates.

## 8. Start blockers

Resolve or explicitly choose defaults before coding:

| Blocker | Decision needed | Recommended default |
| --- | --- | --- |
| Catalog source of truth | Python registry, JSON registry, or schema-generated constants. | Python registry with JSON export for docs/site/OpenAPI tests. |
| Persistence | Inline-only P0 or `packet_runs` in first release. | Inline-only P0 with `packet_persistence_unavailable` gap unless replay is mandatory. |
| CSV input mode | Upload/analyze in P0 or normalized `derived_business_facts` only. | Analyze/preview allowed; packet execution from normalized aggregate facts first. |
| Metering of `agent_routing_decision` | Free preflight or billable packet. | Free preflight with abuse throttle, no billable usage. |
| Docs generation | Generate checked-in Markdown or runtime JSON consumed by docs build. | Generate checked-in Markdown from catalog examples and drift-test. |
| Source license boundary | Which public sources are safe for agent-facing normalized facts. | Require source profile row before public exposure; unknown license becomes gap or metadata-only. |
| `company_public_baseline` identity | Whether name-only requests can run. | Require stable ID in P0; name-only returns ambiguity gap or validation error. |
| Cost display rounding | Decimal billing vs whole-yen display. | Store decimal precision, display rounded-up whole JPY with tax note. |
| Known-gap enum governance | Closed enum vs ad hoc strings. | Closed enum in contract, migration path for existing names. |

## 9. Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Metadata drift across REST/MCP/OpenAPI/docs/site | Agents call wrong routes or preserve wrong fields. | One catalog plus drift tests. |
| Billing before guard completion | Double billing, support burden, trust loss. | Guard-order tests and idempotency conflict tests. |
| Raw CSV/private value leakage | Privacy incident and product trust failure. | Aggregate-only allowlist, redaction, static leak scans, synthetic fixtures. |
| Source receipts incomplete but presented as audit-grade | GEO premise fails and users overtrust outputs. | Receipt completeness tests and `source_receipt_missing_fields` gaps. |
| No-hit phrased as absence | False negative legal/compliance risk. | Closed no-hit copy and forbidden-phrase scans. |
| Professional judgment overclaim | Legal/tax/accounting boundary breach. | Fence fields, human review flags, forbidden-claim scans. |
| Persistence overpromised | API docs lie or leak another customer's packets. | Inline-only default or access-controlled persistence tests. |
| Public page generator becomes a second SOT | Future drift after first release. | Generate from catalog or compare generated pages to catalog. |
| Source license ambiguity | Redistribution or excerpt risk. | Source profile license boundary, metadata-only fallback, short/no excerpts. |
| Existing clients break | Regression to current users. | Additive envelope, compatibility tests, legacy aliases. |

## 10. Source spec inputs consolidated

Primary 2026-05-15 planning inputs:

- `docs/_internal/p0_geo_first_packets_spec_2026-05-15.md`
- `docs/_internal/implementation_sequence_deepdive_2026-05-15.md`
- `docs/_internal/packet_taxonomy_common_schema_output_contract_pack_2026-05-15.md`
- `docs/_internal/geo_source_receipts_data_foundation_spec_2026-05-15.md`
- `docs/_internal/data_model_schema_deepdive_2026-05-15.md`
- `docs/_internal/source_receipt_claim_graph_deepdive_2026-05-15.md`
- `docs/_internal/cost_preview_ux_tests_deepdive_2026-05-15.md`
- `docs/_internal/billing_risk_controls_deepdive_2026-05-15.md`
- `docs/_internal/security_privacy_csv_deepdive_2026-05-15.md`
- `docs/_internal/csv_accounting_outputs_deepdive_2026-05-15.md`
- `docs/_internal/developer_mcp_api_deepdive_2026-05-15.md`
- `docs/_internal/mcp_agent_first_catalog_deepdive_2026-05-15.md`
- `docs/_internal/openapi_agent_safe_subset_deepdive_2026-05-15.md`
- `docs/_internal/public_packet_page_generator_deepdive_2026-05-15.md`
- `docs/_internal/proof_pages_audit_ledger_deepdive_2026-05-15.md`
- `docs/_internal/frontend_geo_first_ux_deepdive_2026-05-15.md`
- `docs/_internal/frontend_copy_audit_deepdive_2026-05-15.md`
- `docs/_internal/llms_well_known_contract_deepdive_2026-05-15.md`
- `docs/_internal/ai_surface_integration_playbooks_deepdive_2026-05-15.md`
- `docs/_internal/geo_eval_harness_deepdive_2026-05-15.md`
- `docs/_internal/market_icp_jtbd_deepdive_2026-05-15.md`
- `docs/_internal/competitive_positioning_deepdive_2026-05-15.md`
- `docs/_internal/algorithmic_outputs_deepdive_2026-05-15.md`
- `docs/_internal/official_source_acquisition_plan_deepdive_2026-05-15.md`
- `docs/_internal/public_source_join_expansion_deepdive_2026-05-15.md`
- `docs/_internal/ops_drift_prevention_deepdive_2026-05-15.md`

## 11. Final implementation slice recommendation

If implementation capacity is constrained, ship the narrow P0 slice:

1. Contract, catalog, source receipts, known gaps.
2. Pricing policy and cost preview.
3. Three packets first: `evidence_answer`, `source_receipt_ledger`, `agent_routing_decision`.
4. REST and MCP for those same three.
5. Public packet/proof/pricing pages for those same three.
6. Drift, billing, privacy, forbidden-claim, and discovery tests.

Defer `company_public_baseline`, `application_strategy`, and `client_monthly_review` only if identity resolution, source coverage, or CSV privacy is not ready. Do not defer source receipt validation, cost preview, cap/idempotency guard order, or cross-surface drift tests.
