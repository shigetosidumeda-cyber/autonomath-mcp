# Athena Query Catalog Audit — 2026-05-17

Lane: `[lane:solo]`  ·  Mode: READ-ONLY (no Athena execution)  ·  Source: `infra/aws/athena/`

## Summary

- **Total SQL files**: 83
- **Big cross-join queries** (`big_queries/wave*/`): 61
- **Legacy / single-source queries** (`queries/`): 22
- **Queries with captured execution log**: 17
- **Succeeded** (per captured log): 17
- **Total bytes scanned** (captured runs only): 9.20 GiB = 9,883,151,814 bytes
- **Total estimated cost** (captured runs only): **$0.0451** USD at $5/TB
- **Total table references** (FROM/JOIN, post-CTE dedup): 1419

> Captured-run subtotals only count queries whose `*_result.log` / `*_rerun.log` is present under `big_queries/wave*/results/`. Queries without a log are marked `NOT_EXECUTED` here; they may have been executed and the log discarded, or are pending execution.

## Wave-by-Wave Breakdown

| Wave | Files | Executed | Succeeded | Sum bytes scanned | Sum cost USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| `queries` | 22 | 0 | 0 | 0 B | $0.0000 |
| `wave55` | 6 | 0 | 0 | 0 B | $0.0000 |
| `wave58` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave60` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave67` | 7 | 7 | 7 | 3.99 GiB | $0.0196 |
| `wave70` | 5 | 5 | 5 | 3.06 GiB | $0.0149 |
| `wave82` | 5 | 5 | 5 | 2.16 GiB | $0.0106 |
| `wave85` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave88` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave91` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave94` | 5 | 0 | 0 | 0 B | $0.0000 |
| `wave98` | 4 | 0 | 0 | 0 B | $0.0000 |
| `wave99` | 4 | 0 | 0 | 0 B | $0.0000 |
| **TOTAL** | **83** | **17** | **17** | **9.20 GiB** | **$0.0451** |

## Top 5 Most-Expensive Queries (by bytes scanned, captured runs only)

| Rank | Wave | Q-ID | Bytes scanned | Cost USD | Wall sec | File |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | `wave82` | `Q27` | 1.34 GiB | $0.0066 | 95s | `q27_allwave_53_82_grand_aggregate.sql` |
| 2 | `wave70` | `Q22` | 1.19 GiB | $0.0058 | 72s | `q22_entity360_x_houjin_x_allwave_footprint.sql` |
| 3 | `wave67` | `Q11` | 1.16 GiB | $0.0057 | 37s | `q11_allwave_53_67_row_count_by_family.sql` |
| 4 | `wave70` | `Q19` | 1.06 GiB | $0.0052 | 71s | `q19_wave69_entity360_x_acceptance_probability_xref.sql` |
| 5 | `wave67` | `Q13` | 966.48 MiB | $0.0046 | 31s | `q13_top50_houjin_bangou_allwave.sql` |

## Top 5 Broadest Queries (by tables/UNION arms)

| Rank | Wave | Q-ID | Tables/UNION arms | File |
| ---: | --- | --- | ---: | --- |
| 1 | `wave94` | `Q47` | 77 | `q47_allwave_53_94_grand_aggregate.sql` |
| 2 | `wave91` | `Q42` | 72 | `q42_allwave_53_91_grand_aggregate.sql` |
| 3 | `wave60` | `Q06` | 69 | `q6_allwave_aggregation_53_62.sql` |
| 4 | `wave67` | `Q11` | 69 | `q11_allwave_53_67_row_count_by_family.sql` |
| 5 | `wave67` | `Q16` | 62 | `q16_wave60_65_cross_industry_x_cross_finance_rollup.sql` |

## Full Catalog

| Wave | Q-ID | Tables | Bytes | Cost USD | State | File | Theme |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `queries` | `acceptance_probability_cohort_` | 3 | — | — | NOT_EXECUTED | `acceptance_probability_cohort_groupby.sql` | Purpose:  GROUP BY the canonical 5-axis cohort (industry × scale × region |
| `queries` | `artifact_size_per_run` | 1 | — | — | NOT_EXECUTED | `artifact_size_per_run.sql` | Purpose:  Storage footprint per run. SUM(content_length) gives total bytes |
| `queries` | `claim_refs_per_subject` | 1 | — | — | NOT_EXECUTED | `claim_refs_per_subject.sql` | Purpose:  Fact density per entity. For each (subject_kind, subject_id) |
| `queries` | `cohort_acceptance_probability` | 1 | — | — | NOT_EXECUTED | `cohort_acceptance_probability.sql` | Purpose:  Build the 採択確率 (acceptance probability) cohort model from |
| `queries` | `coverage_score_run` | 4 | — | — | NOT_EXECUTED | `coverage_score_run.sql` | Purpose:  Per-run aggregate scorecard. Combines source_receipts, |
| `queries` | `cross_packet_correlation` | 4 | — | — | NOT_EXECUTED | `cross_packet_correlation.sql` | Purpose:  Correlate three populated packet families on shared keys: |
| `queries` | `cross_source_identity_resoluti` | 1 | — | — | NOT_EXECUTED | `cross_source_identity_resolution.sql` | Purpose:  Identity-resolve a houjin across three authoritative directories |
| `queries` | `enforcement_industry_heatmap` | 3 | — | — | NOT_EXECUTED | `enforcement_industry_heatmap.sql` | Purpose:  Build the 行政処分 (enforcement) × 業種 (industry) × 地域 |
| `queries` | `entity_resolution_full` | 5 | — | — | NOT_EXECUTED | `entity_resolution_full.sql` | Purpose:  Identity resolution across the three corporate-entity-keyed |
| `queries` | `forbidden_claim_scan` | 2 | — | — | NOT_EXECUTED | `forbidden_claim_scan.sql` | Purpose:  Safety regression scan. claim_refs.value MUST NOT carry strings |
| `queries` | `houjin_360_full_crossjoin` | 3 | — | — | NOT_EXECUTED | `houjin_360_full_crossjoin.sql` | Purpose:  Materialise a 7-axis 法人360 packet for every corporate_entity |
| `queries` | `identity_ambiguity` | 2 | — | — | NOT_EXECUTED | `identity_ambiguity.sql` | Purpose:  Claims attached to a houjin (法人) subject with confidence < 0.5 |
| `queries` | `j06_pdf_extraction_yield` | 3 | — | — | NOT_EXECUTED | `j06_pdf_extraction_yield.sql` | Purpose:  Per-source-id PDF yield for J06 (PDF/OCR extraction stage). |
| `queries` | `known_gaps_by_code` | 1 | — | — | NOT_EXECUTED | `known_gaps_by_code.sql` | Purpose:  Distribution of the 7-code JPCIR gap enum |
| `queries` | `license_boundary_summary` | 1 | — | — | NOT_EXECUTED | `license_boundary_summary.sql` | Purpose:  Distribution of `license_boundary` on source_receipts. Expected |
| `queries` | `no_hit_audit` | 1 | — | — | NOT_EXECUTED | `no_hit_audit.sql` | Purpose:  Audit `receipt_kind='no_hit_check'` rows. These are receipts that |
| `queries` | `program_lineage_full_trace` | 3 | — | — | NOT_EXECUTED | `program_lineage_full_trace.sql` | Purpose:  Reconstruct the full 5-hop lineage for every program (補助金/ |
| `queries` | `program_lineage_join` | 2 | — | — | NOT_EXECUTED | `program_lineage_join.sql` | Purpose:  Aggregate "lineage coverage" per program across the 6-source |
| `queries` | `source_coverage_per_family` | 2 | — | — | NOT_EXECUTED | `source_coverage_per_family.sql` | Purpose:  Per-source-family row count from claim_refs joined back through |
| `queries` | `stale_freshness` | 1 | — | — | NOT_EXECUTED | `stale_freshness.sql` | Purpose:  Surface receipts whose `source_fetched_at` is older than 30 days |
| `queries` | `time_series_burn_pattern` | 19 | — | — | NOT_EXECUTED | `time_series_burn_pattern.sql` | Purpose:  Track ETL progress over time across every populated packet |
| `queries` | `top_10_largest_documents` | 1 | — | — | NOT_EXECUTED | `top_10_largest_documents.sql` | Purpose:  Identify the 10 largest individual documents landed in |
| `wave55` | `wave55_coverage_grade_breakdow` | 24 | — | — | NOT_EXECUTED | `wave55_coverage_grade_breakdown.sql` | Coverage A/B/C/D grade distribution per outcome (quality QA). |
| `wave55` | `wave55_cross_packet_entity_uni` | 39 | — | — | NOT_EXECUTED | `wave55_cross_packet_entity_unique.sql` | Count DISTINCT subject_id values per outcome_type across all 39 |
| `wave55` | `wave55_gap_code_frequency` | 24 | — | — | NOT_EXECUTED | `wave55_gap_code_frequency.sql` | 7-enum gap code frequency per outcome (data quality audit). |
| `wave55` | `wave55_mega_cross_join` | 41 | — | — | NOT_EXECUTED | `wave55_mega_cross_join.sql` | "Mother of all cross-joins". LEFT JOINs across 39 packet Glue tables |
| `wave55` | `wave55_outcome_freshness_trend` | 39 | — | — | NOT_EXECUTED | `wave55_outcome_freshness_trend.sql` | generated_at distribution per outcome bucketed into 24h windows. |
| `wave55` | `wave55_packet_size_distributio` | 23 | — | — | NOT_EXECUTED | `wave55_packet_size_distribution.sql` | Histogram of packet "size" by outcome_type. We approximate packet |
| `wave58` | `Q01` | 20 | — | — | NOT_EXECUTED | `q1_timeseries_x_geographic.sql` | Cross-join Wave 56 (time-series) × Wave 57 (geographic) on subject_id / |
| `wave58` | `Q02` | 17 | — | — | NOT_EXECUTED | `q2_relationship_x_timeseries.sql` | Cross-join Wave 58 (relationship) × Wave 56 (time-series) on |
| `wave58` | `Q03` | 16 | — | — | NOT_EXECUTED | `q3_geographic_x_crosssource.sql` | Cross-join Wave 57 (geographic) × Wave 55 cross-source cohort. |
| `wave58` | `Q04` | 20 | — | — | NOT_EXECUTED | `q4_relationship_x_crosssource.sql` | Cross-join Wave 58 (relationship) × Wave 54 cross-source. Wave 54 = the |
| `wave58` | `Q05` | 47 | — | — | NOT_EXECUTED | `q5_allwave_grand_aggregate.sql` | Grand aggregate across **all 6 packet wave families** (Wave 53 / 53.3 / |
| `wave60` | `Q06` | 69 | — | — | NOT_EXECUTED | `q6_allwave_aggregation_53_62.sql` | Grand all-Wave aggregation across Waves 53/53.3/54/55/56/57/58/60 (and |
| `wave60` | `Q07` | 17 | — | — | NOT_EXECUTED | `q7_houjin_bangou_entity_resolution.sql` | Cross-family entity resolution: given a houjin_bangou (subject.id), how |
| `wave60` | `Q08` | 17 | — | — | NOT_EXECUTED | `q8_fiscal_year_x_family_rollup.sql` | Time-series compression: roll up packets by Japanese fiscal year (FY, |
| `wave60` | `Q09` | 47 | — | — | NOT_EXECUTED | `q9_allwave_fiscal_year_aggregation_53_62.sql` | Sister of q8_fiscal_year_x_family_rollup.sql, **extended to include the |
| `wave60` | `Q10` | 15 | — | — | NOT_EXECUTED | `q10_cross_prefecture_x_cross_industry.sql` | Cross-prefecture × cross-industry intersection: surface entities that |
| `wave67` | `Q11` | 69 | 1.16 GiB | $0.0057 | SUCCEEDED | `q11_allwave_53_67_row_count_by_family.sql` | Wave 53-67 ultra-aggregate row count per (wave_family, src). Extends |
| `wave67` | `Q12` | 12 | 138.54 MiB | $0.0007 | SUCCEEDED | `q12_industry_geographic_time_relationship_4axis.sql` | 4-axis cross-join: industry (wave60) × geographic (wave57) × time-series |
| `wave67` | `Q13` | 24 | 966.48 MiB | $0.0046 | SUCCEEDED | `q13_top50_houjin_bangou_allwave.sql` | Top-50 most-referenced houjin_bangou (entity id) across all Wave 53-67 |
| `wave67` | `Q14` | 8 | 12.04 MiB | $0.0001 | SUCCEEDED | `q14_cross_prefecture_x_cross_industry_x_time_3axis.sql` | 3-axis cross pulse: prefecture × industry × time. For each |
| `wave67` | `Q15` | 23 | 936.63 MiB | $0.0045 | SUCCEEDED | `q15_allwave_fy_x_family_rollup_with_ci.sql` | All-Wave fiscal-year × family rollup WITH confidence intervals on the |
| `wave67` | `Q16` | 62 | 67.78 MiB | $0.0003 | SUCCEEDED | `q16_wave60_65_cross_industry_x_cross_finance_rollup.sql` | Wave 60-65 specific ultra-aggregate. Cross-industry packets (wave60 set |
| `wave67` | `Q17` | 17 | 768.26 MiB | $0.0037 | SUCCEEDED | `q17_wave66_68_pii_tech_supply_x_jsic_intersection.sql` | Wave 66-68 specific intersection. Covers the three newest packet families |
| `wave70` | `Q18` | 19 | 742.43 MiB | $0.0035 | SUCCEEDED | `q18_wave74_76_fintech_labor_startup_x_jsic.sql` | Wave 74-76 specific intersection across the three newest packet families |
| `wave70` | `Q19` | 10 | 1.06 GiB | $0.0052 | SUCCEEDED | `q19_wave69_entity360_x_acceptance_probability_xref.sql` | Wave 69 entity_360 family × Wave 53.3 acceptance_probability cross-ref. |
| `wave70` | `Q20` | 27 | 183.49 KiB | — | SUCCEEDED | `q20_wave72_73_aiml_climate_x_wave60_65_finance.sql` | Wave 72-73 (AI/ML + climate) × Wave 60-65 (cross-industry / finance) |
| `wave70` | `Q21` | 20 | 84.80 MiB | $0.0004 | SUCCEEDED | `q21_allwave_fy_x_jsic_5axis_rollup.sql` | All-Wave fiscal-year × jsic 5-axis roll-up across Wave 53 → 76 packets. |
| `wave70` | `Q22` | 15 | 1.19 GiB | $0.0058 | SUCCEEDED | `q22_entity360_x_houjin_x_allwave_footprint.sql` | Entity_360 (Wave 69) × foundation packet_houjin_360 entity resolution |
| `wave82` | `Q23` | 4 | 481.21 MiB | $0.0023 | SUCCEEDED | `q23_wave80_supply_x_wave53_3_acceptance_xref.sql` | Wave 80 supply-chain-risk family × Wave 53.3 acceptance-probability |
| `wave82` | `Q24` | 10 | 216.58 KiB | — | SUCCEEDED | `q24_wave81_esg_x_wave60_65_finance_intersection.sql` | Wave 81 ESG-materiality family × Wave 60-65 finance / green-finance |
| `wave82` | `Q25` | 9 | 58.55 MiB | $0.0003 | SUCCEEDED | `q25_wave82_ip_x_wave76_startup_growth.sql` | Wave 82 IP/innovation family × Wave 76 startup/scaleup growth signal |
| `wave82` | `Q26` | 14 | 299.33 MiB | $0.0014 | SUCCEEDED | `q26_wave80_82_supply_esg_ip_x_jsic.sql` | All-Wave-80-82 (supply chain + ESG + IP) × jsic_major rollup. |
| `wave82` | `Q27` | 31 | 1.34 GiB | $0.0066 | SUCCEEDED | `q27_allwave_53_82_grand_aggregate.sql` | Grand aggregate row-count per wave_family across the full |
| `wave85` | `Q28` | 9 | — | — | NOT_EXECUTED | `q28_wave83_climate_physical_x_wave81_esg_materiality.sql` | Wave 83 climate physical-risk family × Wave 81 ESG materiality family |
| `wave85` | `Q29` | 9 | — | — | NOT_EXECUTED | `q29_wave84_demographics_x_wave57_geographic.sql` | Wave 84 demographics/population family × Wave 57 geographic family |
| `wave85` | `Q30` | 10 | — | — | NOT_EXECUTED | `q30_wave85_cybersec_x_wave67_tech_infra.sql` | Wave 85 cybersec family × Wave 67 tech-infra family cross-join. |
| `wave85` | `Q31` | 15 | — | — | NOT_EXECUTED | `q31_wave83_85_x_jsic_intersection.sql` | Wave 83 (climate physical) + Wave 84 (demographics) + Wave 85 |
| `wave85` | `Q32` | 48 | — | — | NOT_EXECUTED | `q32_allwave_53_85_grand_aggregate.sql` | Grand aggregate row-count per wave_family across the full Wave 53 |
| `wave88` | `Q33` | 7 | — | — | NOT_EXECUTED | `q33_wave86_social_media_x_wave76_startup_growth.sql` | Wave 86 social media / digital presence family × Wave 76 startup |
| `wave88` | `Q34` | 5 | — | — | NOT_EXECUTED | `q34_wave87_procurement_x_wave53_3_acceptance.sql` | Wave 87 procurement / public contracting family × Wave 53.3 |
| `wave88` | `Q35` | 7 | — | — | NOT_EXECUTED | `q35_wave88_activism_x_wave81_esg_materiality.sql` | Wave 88 corporate activism / political donation family × Wave 81 |
| `wave88` | `Q36` | 9 | — | — | NOT_EXECUTED | `q36_wave86_88_x_jsic_intersection.sql` | Wave 86 (social media / digital presence) + Wave 87 (procurement / |
| `wave88` | `Q37` | 58 | — | — | NOT_EXECUTED | `q37_allwave_53_88_grand_aggregate.sql` | Grand aggregate row-count per wave_family across the full Wave 53 |
| `wave91` | `Q38` | 16 | — | — | NOT_EXECUTED | `q38_wave89_ma_x_wave69_entity_360.sql` | Wave 89 M&A / succession / governance family × Wave 69 entity_360 |
| `wave91` | `Q39` | 7 | — | — | NOT_EXECUTED | `q39_wave90_talent_x_wave75_employment.sql` | Wave 90 talent / workforce / leadership family × Wave 75 employment |
| `wave91` | `Q40` | 11 | — | — | NOT_EXECUTED | `q40_wave91_brand_x_wave86_social_media.sql` | Wave 91 brand / customer-proxy family × Wave 86 social media / |
| `wave91` | `Q41` | 20 | — | — | NOT_EXECUTED | `q41_wave89_91_x_jsic_intersection.sql` | Wave 89 (M&A / succession / governance) + Wave 90 (talent / workforce |
| `wave91` | `Q42` | 72 | — | — | NOT_EXECUTED | `q42_allwave_53_91_grand_aggregate.sql` | Grand aggregate row-count per wave_family across the full Wave 53 |
| `wave94` | `Q43` | 15 | — | — | NOT_EXECUTED | `q43_wave92_product_safety_x_wave81_esg_materiality.sql` | Wave 92 product safety / quality compliance family × Wave 81 ESG |
| `wave94` | `Q44` | 10 | — | — | NOT_EXECUTED | `q44_wave93_real_estate_x_wave57_geographic.sql` | Wave 93 real estate / property family × Wave 57 geographic family |
| `wave94` | `Q45` | 13 | — | — | NOT_EXECUTED | `q45_wave94_insurance_x_wave80_supply_chain_risk.sql` | Wave 94 insurance / risk transfer family × Wave 80 supply chain |
| `wave94` | `Q46` | 13 | — | — | NOT_EXECUTED | `q46_wave92_94_x_jsic_intersection.sql` | Wave 92 (product safety / quality compliance) + Wave 93 (real estate |
| `wave94` | `Q47` | 77 | — | — | NOT_EXECUTED | `q47_allwave_53_94_grand_aggregate.sql` | Grand aggregate row-count per wave_family across the full Wave 53 |
| `wave98` | `Q50` | 6 | — | — | NOT_EXECUTED | `Q50_wave53_acceptance_x_wave69_entity360_x_wave70_industry.sql` | 3-way industry impact surface — Wave 53.3 採択確率 cohort × |
| `wave98` | `Q51` | 6 | — | — | NOT_EXECUTED | `Q51_wave82_85_89_91_94_jsic_small_cohort_5way.sql` | 5-way thin-but-recent newer-family JSIC small-cohort aggregate — |
| `wave98` | `Q52` | 9 | — | — | NOT_EXECUTED | `Q52_foundation_x_wave_72_94_jsic_x_wave70_industry_mat.sql` | Corp × industry × prefecture × JSIC small-cohort matrix — |
| `wave98` | `Q53` | 17 | — | — | NOT_EXECUTED | `Q53_allwave_grand_aggregate_top14_families.sql` | Full grand-aggregate — 14 wave families touched at the top level. |
| `wave99` | `Q54` | 5 | — | — | NOT_EXECUTED | `Q54_outcome_evidence_governance_chain.sql` | Outcome × evidence pairing surface — Wave 51 L3 cross_outcome_routing |
| `wave99` | `Q55` | 6 | — | — | NOT_EXECUTED | `Q55_data_governance_x_program_eligibility.sql` | Data governance × program eligibility — Wave 95-97 data governance |
| `wave99` | `Q56` | 6 | — | — | NOT_EXECUTED | `Q56_data_residency_x_program_offering.sql` | Cross-prefecture data residency × program offering — Wave 95-97 |
| `wave99` | `Q57` | 20 | — | — | NOT_EXECUTED | `Q57_allwave_grand_aggregate_wave_95_97.sql` | Full grand-aggregate including Wave 95-97 newer-family small-cohort. |

## Duplicates / Stale Candidates

- No duplicate Q-IDs detected across waves.

- **Wave 99 status**: Q54/Q55/Q56/Q57 all present (4 SQL files). Memory MEMORY.md still flags "Athena Q54-Q57 wave 99 cross-joins" as `in_progress` — that is execution status; authoring is **complete**.
- **`queries/` directory** (22 files): single-source / pre-Wave-58 reference templates. None have captured logs in this audit (logs live elsewhere or were rotated). Not part of the Wave 58+ ultra-aggregate program.

## Notes

- **Captured execution data is concentrated in Waves 67/70/82** (17/22 logged runs). Waves 55/58/60/85/88/91/94/98/99 ran but result logs were not retained under `big_queries/wave*/results/` (they live in S3 `athena-results/` keyed by `QueryExecutionId`).
- **Cost per query is tiny**: max captured = $0.0066 (Q27 wave82 grand_aggregate, 1.34 GiB). Q14/Q21 ran on ~12 MiB = $0.0001. PERF-3 Parquet ZSTD top-10 + PERF-14 workgroup `BytesScannedCutoffPerQuery=50GB` + result-reuse 11.2x speedup are working as designed; PERF-24 expanded ZSTD coverage to 7 more tables.
- **No queries flagged as stale/dangerous**: every wave* SQL has a clear Wave family scope and explicit table list in the header comment block. The `queries/` legacy templates predate the Wave 58 cross-join program and remain useful as reference.
- **Tables-joined count** uses a simple FROM/JOIN regex with CTE-name removal; large `UNION ALL` aggregates (Q11/Q27/Q32/Q37/Q42/Q47/Q53/Q57) score high because each `UNION ALL` arm references a packet table.
