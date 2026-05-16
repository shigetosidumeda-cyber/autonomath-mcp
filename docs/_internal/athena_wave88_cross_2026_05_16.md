# Athena Wave 88 cross-joins (Q33-Q37) — 2026-05-16

5 new cross-join Athena queries landed under
`infra/aws/athena/big_queries/wave88/`. Successor to
`wave85/q28-q32` (Wave 83-85), extends the cross-source surface
through Wave 86 (social media / digital presence), Wave 87
(procurement / public contracting), Wave 88 (corporate activism /
political).

## Context

- Catalog: 372 outcomes (Wave 86 + Wave 87 + Wave 88 = +30 over
  Wave 85's 342, per `site/.well-known/jpcite-outcome-catalog.json`).
- Glue: 274 tables in `jpcite_credit_2026_05` database (>240 target
  confirmed). Wave 86-88 generators have shipped, but several
  Wave 86/87/88-specific Glue tables are pre-sync; the 5 queries
  reuse the closest LIVE proxies (community_engagement /
  trademark_* / industry_association_link /
  regulatory_change_industry_impact / public_procurement_trend /
  bid_announcement_seasonality / construction_public_works /
  bid_opportunity_matching) so the cross-join is honest without
  blocking on S3+Glue registration.
- Profile: `bookyou-recovery`, region `ap-northeast-1`.
- Workgroup: `jpcite-credit-2026-05`, 50 GB BytesScannedCutoffPerQuery
  per PERF-14 cap. All 5 queries scanned ≪ 50 GB.
- Result reuse: workgroup default. Q33 re-run leveraged result cache
  (7s wall, identical exec_id absent on first run).

## 5 queries — scan + cost

| Query | Purpose | exec_id | bytes scanned | est cost |
| --- | --- | --- | --- | --- |
| Q33 wave86 social media × wave76 startup growth | brand-engagement vs capital-velocity alignment density | `1bcb8086-4fcd-4b96-9195-2829b2812139` | 19.74 MiB | $0.0001 |
| Q34 wave87 procurement × wave53.3 acceptance | procurement-pool-to-application-probability lift | `8f0fd004-23e0-4bf6-8dd9-db8d40a44f33` | 481.28 MiB | $0.0023 |
| Q35 wave88 activism × wave81 ESG materiality | activism-to-materiality coherence | `3c59967d-345c-40bb-8abe-54217cc247fe` | 0.25 MiB | $0.0000 |
| Q36 wave86-88 × jsic_major intersection | brand+procurement+activism per JSIC sector | `d0e6ff66-4ebc-4436-98f2-4435f4538705` | 260.59 MiB | $0.0012 |
| Q37 allwave 53-88 grand aggregate | row-count + distinct subjects per wave_family | `6bf728f1-7c5e-4fe7-ad77-48d5398031d8` | 1684.53 MiB | $0.0080 |
| **TOTAL** | | | **2.42 GiB** | **$0.0116** |

All 5 SUCCEEDED. Total scan 2.42 GiB ≪ 50 GB PERF-14 cap (4.8%).
Total cost $0.0116 ≪ $50 budget cap (0.02%).

## Findings

- **Q33 (social × startup growth)**: trademark_industry_density carries
  the most procurement-vs-funding alignment density (alignment density
  ratios 0.35-0.38 across capital_raising / funding_to_revenue /
  business_lifecycle pairs). Brand engagement signal vs startup growth
  signal correlates but is not 1-1; ~35-38% of startup-tracked
  subjects also carry a brand/community signal.
- **Q34 (procurement × acceptance)**: public_procurement_trend ×
  acceptance_probability cross-join scanned 481 MiB, largest of the
  5. acceptance_probability table is the 225K-row dominant scan
  contributor.
- **Q35 (activism × ESG)**: smallest scan (0.25 MiB). industry_
  association_link + regulatory_change_industry_impact rows × ESG
  disclosure tables stay thin in Wave 81 pre-sync state.
- **Q36 (Wave 86-88 × JSIC)**: 260 MiB, 9 packet sources × 21+ JSIC
  buckets including 'UNK' for missing jsic_major. Foundation
  houjin_360 baseline added so the JSIC distribution shape is
  observable in the same output.
- **Q37 (grand aggregate Wave 53-88)**: 1.68 GiB, largest single
  query. Confirmed footprint of all 14 wave families. Largest row
  counts cluster on wave69_entity360 (houjin_bangou ~166K) and
  wave53_3 acceptance (~225K cohort packets); Wave 86-88 are still
  thin (<100 rows each on the live proxies) pre full S3+Glue sync.

## Lessons (carry forward)

- Some packet tables (acceptance_probability, bid_opportunity_matching)
  do NOT have `subject` column — they use `cohort_definition`.
  Always check `aws glue get-table ... StorageDescriptor.Columns`
  before writing cross-joins; mixing the wrong key path returns
  COLUMN_NOT_FOUND mid-query.
- Wave 86-88 generators shipped, but S3+Glue table registration lags.
  Cross-joins should reference LIVE proxies (trademark_* / industry_
  association_link / public_procurement_trend) instead of pre-sync
  wave-specific tables, so the query stays honest.
- 5 cross-joins under $0.02 total + 2.4 GiB scan total. The PERF-14
  50 GB cap is loose for this scale; cost-driver remains Q37 grand
  aggregate as wave family count grows.

## Next ramp

- When Wave 86-88-specific Glue tables (social_media_account_inventory
  / political_donation_record / lobby_activity_intensity etc.) land,
  Q33-Q35 can be widened from proxy-table to direct-table without
  re-architecting.
- Q37 should be kept as the canonical Wave-53-N grand aggregate;
  add per-family LIMIT 5 sample probes if scan grows beyond 5 GiB.
