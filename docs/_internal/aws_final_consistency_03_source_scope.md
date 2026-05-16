# AWS final consistency check 03: source scope

Date: 2026-05-15
Scope: information range / source family coverage / priority consistency
AWS execution: none
Write target: this file only

## 1. Verdict

The expanded source scope is now broad enough for the concept: "Japanese public primary information that AI agents can turn into cheap, source-backed end-user outputs."

However, the plan must not treat every public source as equally urgent. The correct rule is:

> P0 is not "important public information." P0 is "public information that directly powers launch packets and can pass source_profile, rights, receipt, and no-hit gates quickly."

With that correction, the source family plan is coherent.

## 2. Main consistency findings

### Finding 1: Coverage is sufficient, but launch priority needs stricter wording

The current documents cover the requested public information range:

- Laws / systems / industry regulation: `law_primary`, `policy_process`, `procedure_permit`, industry maps.
- Permits / licenses / registrations: `procedure_permit`, sector registries, local government registries.
- Gazette / notices / announcements: `gazette_notice`.
- Notifications / circulars / guidelines: `policy_process`.
- Local governments: `local_government`, with ordinance /制度 /入札 /処分 /許認可.
- Courts / decisions / administrative appeal-like materials: `court_decision`.
- Administrative disposition / enforcement: `enforcement_safety`.
- Statistics / geography / land / address: `statistics_cohort`, `geo_land_address`.
- Standards / certifications / product safety: `ip_standard_cert`.
- Procurement / bids / awards: `procurement_contract`.
- Tax / labor / social insurance: tax-labor source family in output plans and quality gates.

This is enough as a strategic source universe. The remaining issue is execution priority.

### Finding 2: Several families are written as P0/P1 in different files

This is not fatal, but it must be normalized:

| Source family | Current ambiguity | Final decision |
|---|---|---|
| `gazette_notice` | P0/P1 in corpus map, P0-B in synthesis | P0-B for metadata/deep link/hash tied to law-change/procurement/company-event packets. P1 for bulk/full historical expansion. |
| `policy_process` | P0/P1 in corpus map, P0-B in synthesis | P0-B for p-comment, guidelines, circulars that support `reg_change_impact` and `permit_precheck`. P1 for broad councils/whitepaper context. |
| `local_government` | P1 in corpus map, P0-B in synthesis | P0-B only for top allowlisted prefectures/designated cities and high-value pages: subsidies, permits, bids, dispositions. Broad all-municipality crawl is P1/P2. |
| `statistics_cohort` | P0-A backbone but also expansion-like | P0-A for e-Stat basics, municipality/industry codes, regional context. P1 for broad statistical tables and whitepaper-derived tables. |
| `geo_land_address` | P0-A in corpus map, P1 expansion in synthesis | P0-A for address/municipality normalization. P1 for hazard, land price, urban planning, PLATEAU, detailed real-estate DD. |
| `filing_disclosure` / EDINET | P0/P1 | P0-B only for listed-company public trail and vendor DD packets. P1 for XBRL-heavy financial extraction. |
| `court_decision` | P1, sometimes appears close to compliance P0 | Keep P1. Use only context / relevant precedent packet. Do not block RC1 on court data. |
| `ip_standard_cert` | P1 but high-value in standards plan | Keep P1 for broad standards/certification. Promote exact-ID checks, recall/product-safety checks, and public certification lookups to P0-B only when tied to a priced packet. |

Required improvement: the unified plan should explicitly use "P0-B subset" and "P1 broad expansion" language for these families.

## 3. Final priority model

### P0-A: Backbone that almost every packet needs

These must be first because they become identifiers, join keys, source boundaries, and receipt primitives.

| Family | Reason | Outputs enabled |
|---|---|---|
| `source_profile_terms` | Cannot scale collection without terms, robots, license boundary, screenshot/OCR policy. | all packets |
| `identity_tax` | Corporation number and invoice number are exact identifiers. | `company_public_baseline`, `invoice_vendor_public_check`, vendor DD |
| `law_primary` | Legal basis for systems, permits, obligations. | `reg_change_impact`, `permit_precheck`, legal basis packets |
| `statistics_cohort` basic | Public context by region/industry without private inference. | grant matching, market context, site DD |
| `geo_land_address` basic | Links company/site/user region to local governments and geography. | local subsidy, permit, site DD |

### P0-B: Revenue-direct sources

These should run immediately after P0-A gate passes because they make paid packets sellable.

| Family | P0-B subset | Direct paid outputs |
|---|---|---|
| `subsidy_program` | J-Grants, MHLW grants, SME/municipality program pages, official PDFs. | `grant_candidate_shortlist_packet`, `application_strategy_pack` |
| `procedure_permit` | Construction, real estate, transport, staffing, waste, finance registries first. | `permit_scope_checklist_packet`, `regulated_business_check` |
| `enforcement_safety` | FSA / MLIT / MHLW / JFTC / CAA / PPC / selected local dispositions. | `administrative_disposition_radar`, vendor DD |
| `procurement_contract` | p-portal, JETRO, central agencies, top local bids. | `procurement_opportunity_pack`, award ledger |
| `corporate_activity` | gBizINFO public activity signals. | company baseline, vendor DD |
| `gazette_notice` | Metadata/deep links/hashes for announcements, public notices, procurement/company events. | legal-change watch, gazette event ledger |
| `policy_process` | e-Gov public comments, ministry circulars, guidelines, Q&A that attach to P0 packets. | `reg_change_impact_brief`, permit checklist |
| `tax_labor_social` | NTA, eLTAX references, pension, MHLW, labor insurance, minimum wage, grant deadlines. | `tax_labor_event_radar`, CSV monthly review |

### P1: Broad but valuable expansion

These are worth using AWS credit on, but they should not block RC1 or early revenue.

- Broad local government crawl beyond top allowlist.
- Courts, tribunal-like decisions, JFTC decisions, tax appeal materials.
- Broad standards/certification/product safety datasets.
- Full geospatial/land/urban planning/hazard/PLATEAU datasets.
- Public finance, budget, administrative project review, funds, expenditure trail.
- Whitepapers, councils, study groups, annual reports.
- Trade/FDI/export-control source navigation, where outputs are "source candidates" only.

### P2/P3: Caution or only with strict review

These should not consume fast-lane budget unless a specific paid packet and review policy exists.

- Political funding / public integrity datasets.
- Personal-name-heavy gazette/court/enforcement materials.
- Full-text court/gazette redistribution.
- Professional association member lists unless link-only is sufficient.
- Any source where screenshot/OCR is the only support for a critical claim.
- Any source whose terms/robots cannot pass `source_profile`.

## 4. Product-backcast audit

Every collection family must justify itself by one or more paid packet families.

| Source family | Connected to sellable output? | Assessment |
|---|---:|---|
| `identity_tax` | Yes | Strong P0. Cheap, exact, high-volume. |
| `law_primary` | Yes | Strong P0. Needed for permit/reg-change packets. |
| `subsidy_program` | Yes | Strong P0-B. High user intent and clear willingness to pay. |
| `procedure_permit` | Yes | Strong P0-B. High professional workflow value. |
| `enforcement_safety` | Yes | Strong P0-B, but highest misinterpretation risk. Must use scoped no-hit and exact identifiers. |
| `procurement_contract` | Yes | Strong P0-B. Sales/procurement outputs can monetize quickly. |
| `tax_labor_social` | Yes | Strong P0-B for recurring CSV/monthly workflows. |
| `gazette_notice` | Yes, if metadata/event based | Keep focused. Do not sell raw gazette content. |
| `policy_process` | Yes, for change impact | Keep tied to laws, systems, permits, and deadlines. Broad policy background is P1. |
| `statistics_cohort` | Yes, as context and scoring input | P0 only for small core tables/codes. Broad statistical lake is P1. |
| `geo_land_address` | Yes, for local/site packets | P0 for address/municipality mapping. Detailed land/geospatial is P1. |
| `local_government` | Yes, but only selected pages first | Top allowlist is P0-B. Nationwide crawl is P1/P2. |
| `court_decision` | Partly | P1. Useful for context, not a launch dependency. |
| `ip_standard_cert` | Yes, for product/compliance packets | P1 unless exact-ID public lookup is directly packaged. |
| `public_finance` | Partly | P1. Useful for grant/procurement background, not P0. |
| `official_reports` | Weak as standalone | P1/P2. Use only as context attached to concrete outputs. |
| `international_trade_fdi` | Niche but high-value | P1. Must avoid classification/export-control legal judgment. |
| `political_public_integrity` | Weak / risky | P2/P3. Only strict review and clear packet demand. |

## 5. Collections that are over-broad unless narrowed

### 5.1 Broad local government crawl

Issue: "自治体" is commercially valuable, but a nationwide unfocused crawl can consume AWS credit and produce low accepted-artifact yield.

Correction:

1. Start with prefectures, designated cities, core cities, and municipalities with high business density.
2. Restrict first pass to subsidies, permits, bids, dispositions, ordinances/reiki links, and department contact pages.
3. Everything else becomes `metadata_only` or P1 backlog.

### 5.2 Court and dispute corpus

Issue: Court data can improve quality, but it is not the product core for cheap AI-agent packets. Full-text or personal-name-heavy material increases risk.

Correction:

1. Keep P1.
2. Store metadata, official URL, hash, short claim_refs, and known coverage gaps.
3. Use it for `case_law_context_pack`, not for definitive legal conclusions.

### 5.3 Official reports / councils / whitepapers

Issue: Useful context, but easily becomes "interesting data" rather than paid output.

Correction:

1. Only collect when linked to `reg_change_impact`, `grant_origin_trace`, `industry_context`, or `policy_background_brief`.
2. Do not use broad OCR here until high-value P0-B sources have passed.

### 5.4 Political/public integrity

Issue: High reputation and privacy risk, weak initial revenue connection.

Correction:

1. P2/P3 only.
2. No RC1/RC2 dependency.
3. Require explicit strict-review packet before AWS budget allocation.

### 5.5 Standards and certifications

Issue: Valuable, but many sources are search UI / terms-sensitive / exact-ID dependent.

Correction:

1. Promote only exact-ID, public-status, product-safety, recall, and public certification checks.
2. Keep broad standards catalog extraction P1.
3. No safety/compliance guarantee wording.

## 6. Missing or under-emphasized source areas

These are not major gaps, but should be named explicitly so the AWS run can classify them correctly.

| Area | Why it matters | Priority |
|---|---|---|
| Local ordinance / reiki systems | Permits and local business rules often depend on local ordinances. | P1, P0-B only for top localities and permit packets |
| Designation / suspension / nomination-stop lists | Procurement and vendor DD often need 指名停止 and eligibility restrictions. | P0-B for procurement/vendor packets |
| Standard processing periods / application forms | Permit precheck is much more useful when it includes required docs and expected process. | P0-B for selected permits |
| Public warning / alert pages | CAA/FSA/PPC/MHLW warnings can be valuable in DD. | P0-B with strict no-hit language |
| Recall / product accident databases | Standards/certification packet needs safety-event context. | P1, P0-B for product-safety exact checks |
| Tax-labor annual calendars | CSV monthly review needs recurring public deadlines. | P0-B |

## 7. Playwright, screenshot, and OCR consistency

The user expectation that AWS can use Playwright and screenshots is valid. The plan is consistent if it stays within this boundary:

- Use Playwright for public official pages that require rendering, search forms, or JS tables.
- Use screenshots under 1600px as observation receipts, not as the primary source of claims.
- Store screenshot hash, visible text hash, final URL, timestamp, viewport, and blank/CAPTCHA/login detection.
- Do not bypass login, CAPTCHA, rate limits, paywalls, or explicit access controls.
- Do not publish screenshots by default. Public proof pages should use metadata, links, short permitted excerpts, and derived facts.
- OCR is allowed for public PDFs/images, but critical fields require confidence, span links, and preferably cross-check against text/HTML/API.

This resolves the apparent conflict between "fetch困難な部分でも突破" and terms/robots compliance: it is rendering/capturing public pages, not access-control circumvention.

## 8. Recommended merged execution order

This order should be adopted by the main plan and AWS plan.

1. Freeze packet contract, claim_refs, source_receipts, known_gaps, no-hit wording, pricing/cap metadata.
2. Build `source_profile` schema with family, authority rank, terms/robots, fetch class, screenshot policy, OCR policy, redistribution policy, TTL.
3. Run P0-A `source_profile` and small canary for identity, invoice, e-Gov law, e-Stat basic, address/municipality.
4. Start AWS self-running queues only for pass/limited-pass sources.
5. In parallel, freeze sellable P0 packet set: counterparty, grant, permit, disposition, reg-change, invoice, tax-labor, CSV monthly.
6. Run P0-B collection for subsidy, permit, enforcement, procurement, gBizINFO, EDINET subset, gazette metadata, policy process, tax-labor.
7. Run Playwright canaries only after `source_profile` allows it; scale only high-yield sources.
8. Generate packet fixtures, proof pages, agent recommendation examples, and GEO discovery files from accepted artifacts.
9. Deploy RC1 without waiting for broad P1 collection: 3 to 6 proof-backed packets are enough.
10. Use remaining AWS credit on P1 expansion in ROI order: local gov allowlist expansion, geospatial/site DD, standards/certification, courts/decisions, public finance, official reports.
11. Export/checksum/import all accepted artifacts.
12. Delete AWS run resources for zero ongoing bill.

## 9. Final normalized source family table

| Final rank | Source family | Included examples | Excluded or delayed examples |
|---|---|---|---|
| P0-A | `source_profile_terms` | terms, robots, license boundary, screenshot/OCR/TTL policy | none |
| P0-A | `identity_tax` | corporation number, invoice registry | private accounting CSV raw data |
| P0-A | `law_primary` | e-Gov law XML/API | unofficial legal commentary |
| P0-A | `statistics_cohort_basic` | e-Stat core, municipality/industry codes | broad statistical lake |
| P0-A | `geo_address_basic` | address base, municipality mapping | full PLATEAU/land/hazard expansion |
| P0-B | `subsidy_program` | J-Grants, MHLW grants, SME/local programs | unverified blog/listing sites |
| P0-B | `procedure_permit_selected` | construction, real estate, transport, staffing, waste, finance | every niche permit nationwide |
| P0-B | `enforcement_safety_selected` | FSA/MLIT/MHLW/JFTC/CAA/PPC/local selected | personal-name-heavy or ambiguous records without review |
| P0-B | `procurement_contract_selected` | p-portal, JETRO, central/top local bids | all local procurement pages before allowlist |
| P0-B | `corporate_activity` | gBizINFO | unverifiable corporate data aggregators |
| P0-B | `filing_disclosure_subset` | EDINET metadata/key facts for DD | full XBRL extraction as launch blocker |
| P0-B | `gazette_notice_metadata` | issue/page/title/deep link/hash/event metadata | raw full-text redistribution |
| P0-B | `policy_process_practical` | p-comment, guidelines, circulars, Q&A tied to packets | broad meeting archive OCR |
| P0-B | `tax_labor_social` | NTA/eLTAX/pension/MHLW/minimum wage/deadlines | final tax/labor judgment |
| P1 | `local_government_expansion` | ordinances, local systems, permits, bids, dispositions | unbounded all-page crawl |
| P1 | `court_decision` | courts, JFTC decisions, tax appeals, administrative appeal metadata | legal conclusion service |
| P1 | `ip_standard_cert` | JISC, JPO, Giteki, PSE, NITE, PMDA, PPC, public certifications | safety/compliance guarantee |
| P1 | `geo_land_real_estate` | GSI, NLNI, land price, hazard, urban planning, PLATEAU | site suitability guarantee |
| P1 | `public_finance` | budget, admin project review, funds, expenditure trail | political inference |
| P1/P2 | `official_reports` | whitepapers, councils, study groups, annual reports | standalone data lake |
| P1/P2 | `international_trade_fdi` | JETRO, customs, export-control source navigation | HS/export-control final judgment |
| P2/P3 | `political_public_integrity` | only strict review, link/metadata first | RC1/RC2 launch dependency |

## 10. Action items for the main plan

1. Update the unified plan to say: "P0-B subset, P1 broad expansion" for gazette, policy process, local government, statistics, geography, standards, and EDINET.
2. Add `tax_labor_social` as an explicit source family, not only as an output theme.
3. Add `local_reiki_ordinance` as a subfamily of `local_government`.
4. Add `suspension_nomination_stop` as a subfamily under `procurement_contract` / `enforcement_safety`.
5. Add `application_forms_processing_periods` under `procedure_permit`.
6. For every source family, require `primary_paid_output_ids[]`. If empty, default to P2.
7. For every AWS job, require an `accepted_artifact_target`. If it cannot produce one, it should not run in the fast lane.
8. For screenshot/OCR sources, require `public_publish_allowed=false` by default.
9. Keep RC1 focused on P0-A plus P0-B selected sources; do not wait for courts, all local gov, broad standards, official reports, or broad geospatial data.
10. Use P1 expansion only after P0-B packet fixtures and proof pages are already being generated.

## 11. Final answer for check 03

The information scope is not too narrow anymore. It is broad enough to make jpcite valuable later, provided the AWS run does not become a generic public-data crawl.

The corrected principle is:

> Collect broadly as an asset factory, but only after each source family has a paid-output reason, a source_profile boundary, and a concrete accepted-artifact target.

Under that principle, the current plan is consistent and should proceed with the priority normalization above.
