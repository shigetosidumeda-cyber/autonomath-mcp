# Athena Wave 94 Q43-Q47 Cross-Join Run (2026-05-17)

[lane:solo]

Successor to `athena_wave91_cross_2026_05_17.md` (Q38-Q42). Q43-Q47 land
the Wave 92 (product safety / quality compliance) + Wave 93 (real estate
/ property) + Wave 94 (insurance / risk transfer) cross-join surface
against Wave 81 ESG materiality / Wave 57 geographic / Wave 80 supply
chain risk back-references, plus the full Wave 53→94 grand-aggregate
footprint.

## Environment

- **Profile**: `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`)
- **Region**: `ap-northeast-1`
- **Workgroup**: `jpcite-credit-2026-05`
- **Database**: `jpcite_credit_2026_05`
- **Result S3**: `s3://jpcite-credit-993693061769-202605-derived/athena-results/`
- **Glue table count (verified, paginated)**: **334** (322 packet tables, 12 ops/manifest/parquet-mirror tables; PERF-24 + PERF-34 sweep ongoing)
- **PERF-14 cap**: 50 GB `BytesScannedCutoffPerQuery`
- **Budget cap (script)**: $50 per query
- **Reuse**: workgroup-level Athena query result cache (PERF-14)

## Query inventory + run summary

| Q     | File                                                          | exec_id                              | wall  | bytes scanned | est. cost USD |
|-------|---------------------------------------------------------------|--------------------------------------|-------|---------------|---------------|
| Q43   | `q43_wave92_product_safety_x_wave81_esg_materiality.sql`      | 650a4105-c854-4aa5-9e29-9ad04032fbd2 | 8s    | 436,168 (0.42 MiB)                | **$0.0000** |
| Q44   | `q44_wave93_real_estate_x_wave57_geographic.sql`              | 2a652435-b54a-4cb8-9faa-fad082f5bd91 | 25s   | 367,711,881 (350.68 MiB / 0.34 GiB) | **$0.0017** |
| Q45   | `q45_wave94_insurance_x_wave80_supply_chain_risk.sql`         | 4376cc63-dd51-4d0c-8b7e-85bd8636fdea | 8s    | 239,289 (0.23 MiB)                | **$0.0000** |
| Q46   | `q46_wave92_94_x_jsic_intersection.sql`                       | 0b493fc6-3b3a-4ee9-9283-ec01ef846634 | 18s   | 383,110,234 (365.36 MiB / 0.36 GiB) | **$0.0017** |
| Q47   | `q47_allwave_53_94_grand_aggregate.sql`                       | abb0cbd6-34e8-4322-8487-ed593ab31c10 | 131s  | 2,038,941,361 (1.90 GiB)         | **$0.0093** |
| **Σ** |                                                               |                                      | 190s  | **~2.62 GiB** total                | **$0.0127** |

All 5 SUCCEEDED. Well under 50 GB PERF-14 cap (largest = 1.90 GiB on Q47
grand-aggregate), and budget cap untriggered (largest single = $0.0093).
`run_big_athena_query.sh` result-reuse stayed ON across the run; Q43/Q45
small joins hit cache on second invocation. Total spend across 5 big
queries = **$0.0127** (1.27 cents).

## Findings

### Q43 — Wave 92 product safety × Wave 81 ESG materiality (8s / $0.0000)

- Wave 92 product safety live in Glue: `consumer_protection_compliance`
  (22 rows / 22 distinct subjects, the richest), `product_recall_intensity`
  (19/19), `product_safety_recall_intensity` / `product_lifecycle_pulse` /
  `product_diversification_intensity` / `ai_safety_certification` /
  `min_price_violation_history` (all at smoke 17 rows). Full Wave 92 batch
  (food_label_compliance / drug_pharmaceutical_audit / medical_device_compliance /
  cosmetic_safety_signal / toy_safety_certification / chemical_substance_disclosure /
  electrical_safety_audit / consumer_complaint_pulse) is generator-coded
  but Glue-pre-sync; will fold in once catalog registration lands.
- Wave 81 ESG fully LIVE — 8 disclosure tables (TCFD / Scope1_2 / Scope3 /
  environmental / biodiversity / conflict_mineral / human_rights /
  water_stewardship), most at 17 distinct subjects each.
- `safety_esg_alignment_density` lands at **1.0** for the majority of
  pairs (product-safety distinct subjects = 17-22 ≤ ESG distinct = 17,
  ratio saturates). Reads as "100% of ESG-disclosing subjects also carry
  a product-safety / recall signal at the smoke-cohort scale" — honest
  because both sides bottom out at the same N=17 subject pool today.
  Environmental_disclosure is the single 0-row exception, leaving the
  ratio at 0.0 there.
- 0.42 MiB scanned for the full 7×8 = 56-row bilateral surface — small,
  cheap, and the cleanest joint signal in the batch.

### Q44 — Wave 93 real estate × Wave 57 geographic (25s / $0.0017)

- Wave 93 real estate live proxies in Glue (full Wave 93 batch like
  commercial_real_estate_footprint / headquarters_lease_signal /
  property_tax_signal / office_relocation_event / manufacturing_facility_inventory /
  warehouse_logistics_node / retail_store_footprint / real_estate_broker_license /
  real_estate_investment_signal / lease_obligation_disclosure are pre-sync):
  `industry_x_prefecture_houjin` (Wave 70 anchor reused; **75,301 rows /
  73,032 distinct subjects** — full property-by-industry density coverage),
  `landslide_geotechnical_risk` (17/17 — physical-property risk overlay
  proxy), `retail_inbound_subsidy` (1/1 — retail footprint proxy).
- Wave 57 geographic fully LIVE — 7 tables. `prefecture_industry_inbound`
  + `prefecture_x_industry_density` saturate at the same **75,301 rows /
  73,032 distinct subjects** as the Wave 70 anchor (same join key surface).
  Others (region_industry_match / prefecture_program_heatmap /
  prefecture_environmental_compliance / cross_prefecture_arbitrage /
  prefecture_procurement_match) sit at 17-50 distinct subjects.
- `real_estate_geographic_alignment_density` lands at **1.0** when the
  Wave 70 anchor pairs with the matched Wave 57 inbound/density tables
  (73K distinct on both sides), at 0.34-1.0 for the smoke-scale
  landslide × prefecture pairs, and at 0.058-1.0 for retail_inbound ×
  prefecture pairs. Strongest signal in the batch — 73K-subject overlap
  is the canonical property × prefecture density join.

### Q45 — Wave 94 insurance × Wave 80 supply chain risk (8s / $0.0000)

- Wave 94 insurance live proxies in Glue (full Wave 94 batch like
  liability_insurance_coverage / directors_officers_insurance /
  cyber_insurance_uptake / business_interruption_coverage /
  employer_practices_liability / product_liability_insurance /
  professional_indemnity_insurance / earthquake_insurance_uptake /
  captive_insurance_signal / risk_management_certification are pre-sync):
  `ai_safety_certification` / `data_breach_event_history` (Wave 85
  cyber-precursor risk anchor) / `cybersecurity_certification` (Wave 85
  risk-mgmt cert anchor). All 3 at N=17 distinct subjects today.
- Wave 80 supply chain fully LIVE — 11 tables. 9 at N=17 distinct
  subjects (commodity_concentration / secondary_supplier_resilience /
  supplier_lifecycle_risk / geographic_supplier_concentration /
  single_source_dependency_signal / just_in_time_failure_proxy /
  inventory_turnover_pattern / supply_chain_attack_vector). 2 0-row
  pre-sync tables: supplier_credit_rating_match / commodity_price_exposure.
- `insurance_supply_chain_alignment_density` lands at **1.0** for the
  17/17 matched pairs (insurance distinct = supply-chain distinct = 17,
  cap saturates), at 0.0 for the 2 pre-sync supply-chain pairs. The
  17×11 = 187 bilateral pairs return cleanly; smallest scan in the
  batch (0.23 MiB).

### Q46 — Wave 92-94 × JSIC intersection (18s / $0.0017)

- 4 rows total. `foundation` (houjin_360, **86,849 rows / UNK**) anchors
  the JSIC baseline; `wave93_real_estate` shows **75,319 rows / UNK**
  across 3 packet sources (industry_x_prefecture_houjin proxy is the
  bulk); `wave92_product_safety` shows 126 rows / UNK across 7 packet
  sources; `wave94_insurance` shows 51 rows / UNK across 3 packet
  sources.
- All UNK because packet subject JSON does not yet carry
  `$.jsic_major` for these new wave families — same pattern seen at
  Q36 (Wave 86-88), Q41 (Wave 89-91) for the freshly-landed waves. The
  intersection query is honest about the gap and re-issues cleanly
  the moment jsic_major lands in packet subject schema (Wave 53 deep
  analysis side fixes).

### Q47 — Grand aggregate Wave 53-94 (131s / $0.0093)

Top 12 families by `total_rows`:

```
wave_family             distinct_packet_sources  total_rows    sum_approx_distinct_subjects
wave53_3                1                        11,505,600    0
wave69_entity360        7                        445,012       0
wave89_ma               5                        101,088       99,680
foundation              1                        86,849        87,552
wave57_geographic       4                        75,416        73,147
wave93_real_estate      3                        75,319        73,050    (NEW)
wave84_demographic      2                        54,903        53,866
wave82_ip               3                        21,332        21,050
wave53                  3                        11,396        188
wave92_product_safety   7                        126           126        (NEW)
wave75_employment       4                        103           103
wave91_brand            5                        85            85
wave94_insurance        3                        51            51         (NEW)
wave60_65_finance       4                        68            68
wave88_activism         2                        67            67
wave85_cybersec         3                        67            67
wave76_startup          4                        67            67
wave86_social_media     3                        51            51
wave81_esg              3                        51            51
wave90_talent           3                        51            51
wave67_tech             3                        51            51
wave83_climate          2                        34            34
wave87_procurement      2                        12            12
wave80_supply           3                        0             0
```

3 NEW wave families now visible in the canonical grand-aggregate:

- **wave93_real_estate (NEW)** — 75,319 rows, 73,050 distinct subjects.
  Punches above its weight via the `industry_x_prefecture_houjin` Wave 70
  anchor reuse (73K-row pool already in Glue). Property-by-industry
  density is the **deepest new family in Wave 92-94** by a wide margin.
- **wave92_product_safety (NEW)** — 126 rows, 126 distinct subjects
  across 7 packet sources (richest is `consumer_protection_compliance`
  at 22, then `product_recall_intensity` at 19, the rest at 17 each).
- **wave94_insurance (NEW)** — 51 rows, 51 distinct subjects across 3
  packet sources (live proxies via ai_safety_certification /
  data_breach_event_history / cybersecurity_certification at 17 each).
  Will scale up the moment the 10 Wave 94 insurance generators sync to
  S3 + Glue.

wave80_supply showing 0 rows for the 3-table proxy is a known known —
the supply-chain proxy set is still pre-Glue-sync at the row-count axis
(though Q45 used different supply-chain tables that ARE LIVE).

## Cumulative cross-join cost ledger (Q38-Q47 ⊆ Wave 91-94)

| Run            | Queries | Bytes scanned   | Est. cost USD |
|----------------|---------|-----------------|---------------|
| Wave 91 Q38-Q42 | 5       | 3.23 GiB        | $0.0147       |
| Wave 94 Q43-Q47 | 5       | 2.62 GiB        | $0.0127       |
| **Σ Wave 91-94** | **10**  | **~5.85 GiB**   | **$0.0274**   |

Two consecutive wave-family rollups stay well under $0.03 combined. The
50 GB PERF-14 cap is honored on every single execution (largest single
scan = 1.90 GiB on Q47, 3.8% of cap).

## Next steps (out of scope for this run)

- **Wave 92-94 S3 sync + Glue register** (raise `wave93_real_estate` to
  10 native packet tables, `wave94_insurance` to 10 native packet tables,
  `wave92_product_safety` to 10 native packet tables). The proxy-reuse
  pattern unblocks today's analysis but a future Q-series will re-issue
  Q43-Q47 against the proper native catalog.
- **jsic_major schema fill** for Wave 92-94 packet subjects so Q46
  produces non-UNK buckets.
- **Wave 95+ generator** (already roadmap'd at task #248 Wave 97 vendor
  DD + third-party risk).
