# Athena Wave 60 post-sync 5 re-run + 3 new grand-aggregate — 2026-05-16

Wave 60 post-sync Athena run: re-execute the 5 Wave 58 mega cross-joins
and add 3 grand-aggregate queries under
`infra/aws/athena/big_queries/wave60/`. All 8 queries SUCCEEDED on the
`jpcite-credit-2026-05` workgroup; Athena rate = $5.00/TB; Profile =
`bookyou-recovery`; Region = `ap-northeast-1`; budget cap = $100.

## HONEST STATE: Wave 56-58 packets STILL NOT synced

`aws s3 ls s3://jpcite-credit-993693061769-202605-derived/packets_wave56_58/`
returned `Total Objects: 0 / Total Size: 0` at 2026-05-16 18:29 JST when
this run started. The 30 Wave 56-58 Glue tables are registered but the
underlying S3 prefixes remain empty — the parallel sync agent had not
landed yet at re-run time. Local Wave 56 smoke output exists in
`out/wave56_smoke/` (10 packet kinds × per-prefecture subdirs) but is not
uploaded.

Consequence:

- **Q1 (wave56 × wave57) re-scans 0 bytes** — unchanged from Wave 58
  baseline.
- **Q2 (wave58 × wave56) re-scans 0 bytes** — unchanged.
- **Q3 / Q4 / Q5 hit the populated Wave 53 / 53.3 / 54 / 55 packet
  surface** and reproduce the same byte counts as the Wave 58 baseline.

Once Wave 56-58 packets land in S3 (separate agent / cron), re-running
without SQL changes will surface real cross-join scans.

## Re-run + new query results table

| # | File | Joined families | exec_id | Wall | Engine ms | Bytes scanned | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q1 | wave58/q1_timeseries_x_geographic.sql | Wave 56 × Wave 57 | a1d8af90-5ff2-4d4f-a825-634f975f52b5 | 8s | 1,778 | 0 (0.00 MiB) | $0.0000 |
| Q2 | wave58/q2_relationship_x_timeseries.sql | Wave 58 × Wave 56 | d1809887-05a5-4559-a8d1-0aa30baa8572 | 7s | 2,370 | 0 (0.00 MiB) | $0.0000 |
| Q3 | wave58/q3_geographic_x_crosssource.sql | Wave 57 × Wave 55 | 4f461077-b744-4829-a261-177e87e845e1 | 7s | 6,266 | 75,481,580 (71.98 MiB) | $0.0003 |
| Q4 | wave58/q4_relationship_x_crosssource.sql | Wave 58 × Wave 54 | c59ea5da-895c-421a-8afe-5c5dc3214ad6 | 7s | 5,961 | 189,701,314 (180.91 MiB) | $0.0009 |
| Q5 | wave58/q5_allwave_grand_aggregate.sql | All 7 families | 77facdf6-eb40-40bc-829e-64c9a384473b | 36s | 31,145 | 926,782,784 (883.85 MiB / 0.86 GiB) | $0.0042 |
| Q6 | **wave60/q6_allwave_aggregation_53_62.sql** | All 8 families (53→60 catalog) | 09bcecbd-b5d3-4dcc-990e-96f62dd5de65 | 42s | 36,646 | 1,238,175,064 (1180.82 MiB / 1.15 GiB) | $0.0056 |
| Q7 | **wave60/q7_houjin_bangou_entity_resolution.sql** | Cross-family entity-ID footprint | 25b82ce0-d8f1-4dc9-ae89-9f226df71458 | 38s | 28,402 | 994,964,029 (948.87 MiB / 0.93 GiB) | $0.0045 |
| Q8 | **wave60/q8_fiscal_year_x_family_rollup.sql** | FY (4/1 anchor) × family | 3a525c0c-8747-4919-a5db-e0a83ab8f21d | 31s | 27,809 | 994,964,029 (948.87 MiB / 0.93 GiB) | $0.0045 |

**Totals**: **4,420,068,800 bytes ≈ 4.12 GiB scanned across 8 queries**,
estimated cost ≈ **$0.0200 USD** (well under the $100 budget cap and the
100 GB `BytesScannedCutoffPerQuery` workgroup cap).

## What the 3 new queries do

- **Q6 — All-Wave aggregation 53→62 (`q6_allwave_aggregation_53_62.sql`)**.
  Counts packets per `(wave_family, src)` across foundation + Wave 53 / 53.3 /
  54 / 55 / 56 / 57 / 58 / 60. Sister to Wave 58 Q5 but extends to Wave 55
  (cross-3-source analytics) and Wave 60 (cross-industry macro). 1.15 GiB
  scan because UNION ALL touches every populated table at least for row
  counting.

- **Q7 — Cross-family entity resolution (`q7_houjin_bangou_entity_resolution.sql`)**.
  For each `houjin_bangou`-or-cohort join key, count distinct wave_family +
  packet_source coverage. Sorted by footprint DESC so the top of the result
  is the deepest-moat entity. Per-table column projection handles light Wave
  53 packets (subject only) vs heavy Wave 53.3/54/55 packets (subject +
  cohort_definition fallback). 0.93 GiB scan.

- **Q8 — Fiscal-year × family roll-up (`q8_fiscal_year_x_family_rollup.sql`)**.
  Time-series compression: every packet is binned by Japanese fiscal year
  (FY = year if month ≥ 4 else year − 1, JP 会計年度 4/1-3/31 anchor) × wave
  family, with row count + distinct join keys + min/max generated_at per
  bin. Per-table timestamp resolution: wave53 uses `created_at`, wave53_3/
  54/55/60 heavy tables use `generated_at`, light tables fall back to
  `created_at`. 0.93 GiB scan.

## Schema gap fixes applied during run

Initial Q7 + Q8 drafts assumed `cohort_definition` and `generated_at` on
every packet table. Athena returned `COLUMN_NOT_FOUND` for the light Wave
53 tables (`packet_invoice_houjin_cross_check_v1`, `packet_kanpou_gazette_watch_v1`,
`packet_company_public_baseline_v1`, `packet_vendor_due_diligence_v1`,
`packet_succession_program_matching_v1`, `packet_invoice_registrant_public_check_v1`).
Both queries were rewritten to use per-table column projection (subject-only
where cohort_definition absent, `created_at` fallback where `generated_at`
absent). Re-run succeeded on the second pass.

## Result S3 locations

All result CSVs land under
`s3://jpcite-credit-993693061769-202605-derived/athena-results/{exec_id}.csv`.

## Re-run instructions

```bash
bash scripts/aws_credit_ops/run_big_athena_query.sh \
  infra/aws/athena/big_queries/wave60/q6_allwave_aggregation_53_62.sql \
  --budget-cap-usd 100

bash scripts/aws_credit_ops/run_big_athena_query.sh \
  infra/aws/athena/big_queries/wave60/q7_houjin_bangou_entity_resolution.sql \
  --budget-cap-usd 100

bash scripts/aws_credit_ops/run_big_athena_query.sh \
  infra/aws/athena/big_queries/wave60/q8_fiscal_year_x_family_rollup.sql \
  --budget-cap-usd 100
```

(Wave 58 Q1-Q5 re-run identically via the wave58/ path; bytes scanned
remains 0 for Q1/Q2 until Wave 56-58 packets sync to S3.)
