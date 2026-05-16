# Athena Wave 58 mega cross-join run — 2026-05-16

5 new mega cross-join queries landed under `infra/aws/athena/big_queries/wave58/`
plus 30 Wave 56-58 packet Glue tables registered in
`jpcite_credit_2026_05`. The Glue registration is **structural-only** —
the underlying S3 prefixes for Wave 56-58 (`program_amendment_timeline_v2/`
… `vendor_payment_history_match_v1/`) are still empty at run time because
the local packet generators have not yet been uploaded. Q1 and Q2 scan 0
bytes against the empty prefixes; Q3, Q4, and Q5 scan the already-populated
Wave 53/53.3/54/55 packet families and surface real data.

All runs honor the `jpcite-credit-2026-05` workgroup's 100 GB
`BytesScannedCutoffPerQuery` cap. Profile = `bookyou-recovery`,
Region = `ap-northeast-1`. Athena rate = $5.00/TB.

## Glue Catalog registration

```
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/register_packet_glue_tables.py
```

Output: `out/glue_packet_table_register.json` → `total=69 ok=69`. The 30
Wave 56-58 entries are appended to the existing 39 Wave 53/53.3/54
foundation + cross-source set via the shared `_WAVE_56_58_COLUMNS`
super-set schema (kitchen-sink Pydantic envelope + per-wave body fields,
JsonSerDe + `ignore.malformed.json = true`).

30 newly registered tables (1 per Wave 56-58 packet kind):

| Wave | Tables |
| --- | --- |
| 56 (time-series) | program_amendment_timeline_v2, enforcement_seasonal_trend_v1, adoption_fiscal_cycle_v1, tax_ruleset_phase_change_v1, invoice_registration_velocity_v1, regulatory_q_over_q_diff_v1, subsidy_application_window_predict_v1, bid_announcement_seasonality_v1, succession_event_pulse_v1, kanpou_event_burst_v1 |
| 57 (geographic) | city_jct_density_v1, city_size_subsidy_propensity_v1, cross_prefecture_arbitrage_v1, municipality_subsidy_inventory_v1, prefecture_court_decision_focus_v1, prefecture_environmental_compliance_v1, prefecture_program_heatmap_v1, region_industry_match_v1, regional_enforcement_density_v1, rural_subsidy_coverage_v1 |
| 58 (relationship) | board_member_overlap_v1, business_partner_360_v1, certification_houjin_link_v1, employment_program_eligibility_v1, founding_succession_chain_v1, houjin_parent_subsidiary_v1, industry_association_link_v1, license_houjin_jurisdiction_v1, public_listed_program_link_v1, vendor_payment_history_match_v1 |

## 5 mega cross-join queries

SQL files: `infra/aws/athena/big_queries/wave58/q{1..5}_*.sql`. Each
query LEFT JOINs across packet families on a normalized
COALESCE(`subject.id`, `cohort_definition.cohort_id`,
`cohort_definition.prefecture`) join key with JSON-extract metric
projection.

| # | File | Joined Wave families | exec_id | Wall | Engine ms | Bytes scanned | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q1 | q1_timeseries_x_geographic.sql | Wave 56 × Wave 57 | 803dec81-e506-466e-a3a9-82c961dd5317 | 7s | 2,091 | 0 (0.00 MiB) | $0.0000 |
| Q2 | q2_relationship_x_timeseries.sql | Wave 58 × Wave 56 | 299aeefe-0038-4529-8450-19093574b51b | 7s | 1,667 | 0 (0.00 MiB) | $0.0000 |
| Q3 | q3_geographic_x_crosssource.sql | Wave 57 × Wave 55 (53.3) | b91f5b29-a33b-40f5-bdaa-1c3cbac8e7c9 | 8s | 5,852 | 75,481,580 (71.98 MiB) | $0.0003 |
| Q4 | q4_relationship_x_crosssource.sql | Wave 58 × Wave 54 | ac1edd46-a390-4c9d-890f-72021739e534 | 13s | 6,933 | 189,701,314 (180.91 MiB) | $0.0009 |
| Q5 | q5_allwave_grand_aggregate.sql | All 7 families | ffce5810-d3ef-47ff-bc9b-7ec40f3f56d2 | 54s | 48,874 | 926,782,784 (883.85 MiB / 0.86 GiB) | $0.0042 |

**Totals**: 1,191,965,678 bytes (≈ 1.11 GiB) scanned across 5 queries,
estimated cost ≈ **$0.0054 USD** (well under the $100 budget cap and the
100 GB workgroup cutoff).

## Observations

- Q1 and Q2 returning 0 bytes confirms that the Wave 56-58 S3 prefixes
  are not yet populated. The Glue table registration is still correct;
  once the local packet generator outputs are `aws s3 sync`'d to the
  derived bucket, these queries will scan ~ MB-GB range without SQL
  changes.
- Q3 scans 72 MiB across the populated Wave 53.3 cross-source packets
  (patent_corp_360 / environmental_compliance_radar /
  statistical_cohort_proxy / edinet_finance_program_match /
  cross_administrative_timeline / gbiz_invoice_dispatch_match).
- Q4 scans 181 MiB across all 10 Wave 54 cross-source packets — densest
  cross-join surface in this run.
- Q5 is the largest scan at 884 MiB and ran for 54 s wall clock; it
  enumerates row count + distinct join-key count + earliest/latest
  generated_at per (wave_family, source). Schema variance across
  Wave 53 tables (some lack `cohort_definition`, some use `created_at`
  instead of `generated_at`) was handled by per-table projection.

## Result S3 locations

All result CSVs land under
`s3://jpcite-credit-993693061769-202605-derived/athena-results/{exec_id}.csv`.

## Re-run instructions

```
bash scripts/aws_credit_ops/run_big_athena_query.sh \
  infra/aws/athena/big_queries/wave58/q1_timeseries_x_geographic.sql \
  --budget-cap-usd 100
```

(Repeat for q2..q5; the helper script auto-substitutes `:run_id_filter`,
polls every 5 s up to 30 min, prints bytes scanned + estimated cost +
first 20 rows.)
