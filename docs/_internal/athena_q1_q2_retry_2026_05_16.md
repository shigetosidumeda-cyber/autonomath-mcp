# Athena Q1/Q2 retry post Wave 56-58 sync + Q9/Q10 new mega — 2026-05-16

`[lane:solo]`

## Context

`docs/_internal/athena_wave60_run_2026_05_16.md` (commit `3c90476ee`)
recorded that Wave 58 Q1 and Q2 still scanned 0 bytes during the
Wave 60 batch — the sync agent (`f2ce90755`, "Wave 56-58 packets s3
sync") landed at 18:35 JST, AFTER the Wave 60 batch had already started
at 18:29 JST. With the Wave 56-58 prefixes now populated in S3, this
re-run finally surfaces real cross-join scans for Q1 and Q2 and adds two
new mega queries (Q9 + Q10) under `infra/aws/athena/big_queries/wave60/`.

Profile = `bookyou-recovery`, Region = `ap-northeast-1`, Workgroup =
`jpcite-credit-2026-05` (100 GB BytesScannedCutoffPerQuery), database =
`jpcite_credit_2026_05`, Athena rate = $5.00/TB.

## S3 verification (Wave 56-58 packets)

The sync from commit `f2ce90755` landed each Wave 56-58 packet kind
under its own table prefix (NOT `packets_wave56_58/`), e.g.:

| sample prefix | objects | bytes |
| --- | --- | --- |
| `s3://jpcite-credit-993693061769-202605-derived/board_member_overlap_v1/` | 49 | 239,870 |
| `s3://jpcite-credit-993693061769-202605-derived/adoption_fiscal_cycle_v1/` | 17 | 30,641 |
| `s3://jpcite-credit-993693061769-202605-derived/city_jct_density_v1/` | 47 | 62,974 |

(`s3://jpcite-credit-993693061769-202605-derived/packets_wave56_58/`
itself is still 0 objects / 0 bytes — that is not the canonical prefix
the sync used; do not gate on its existence.)

## 4 query result table

| # | File | Joined families | exec_id | Wall-ish (engine ms) | Bytes scanned | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | wave58/q1_timeseries_x_geographic.sql | Wave 56 × Wave 57 | `b3a9dbad-ceb8-484e-a9f7-65aa63a76d47` | 3,985 | **15,086,948** (14.39 MiB / 0.0140 GiB) | $0.0001 |
| Q2 | wave58/q2_relationship_x_timeseries.sql | Wave 58 × Wave 56 | `092037af-dcab-4c2c-9954-2d93698f238e` | 3,274 | **21,396,718** (20.41 MiB / 0.0199 GiB) | $0.0001 |
| Q9 | **wave60/q9_allwave_fiscal_year_aggregation_53_62.sql** | Full 53/53.3/54/55/56/57/58/60 + foundation by FY | `e9ff6a25-a375-4128-a0c0-eb46dce38f29` | 30,600 | **1,018,841,012** (971.65 MiB / 0.9491 GiB) | $0.0046 |
| Q10 | **wave60/q10_cross_prefecture_x_cross_industry.sql** | Wave 57 (geographic) × Wave 60 industry + Wave 53 enforcement_industry_heatmap | `8eab5093-5cab-4c5d-81d9-325b778f188c` | 4,146 | **30,717,387** (29.29 MiB / 0.0286 GiB) | $0.0002 |

**Totals**: **1,086,042,065 bytes ≈ 1.012 GiB scanned across 4 queries**,
estimated cost **≈ $0.0051 USD** (negligible relative to the $100 budget
cap and the 100 GB per-query cutoff).

## What the 2 new queries add

- **Q9 — All-Wave FY aggregation 53→62 (`q9_allwave_fiscal_year_aggregation_53_62.sql`)**.
  Sister of `wave60/q8_fiscal_year_x_family_rollup.sql`, **extended to
  include the Wave 56-58 time-series + geographic + relationship
  families** which were empty when Q8 was authored. Per-table timestamp
  resolution (created_at vs generated_at vs freshest_announced_at)
  matches Q8's pattern. Result is one row per (fiscal_year_jp,
  wave_family) bucket with row count + distinct join keys + earliest /
  latest gen timestamp. 971.65 MiB scan reflects every table being read
  for its timestamp + join key column (per-row projection only — no body
  decompression).

- **Q10 — Cross-prefecture × cross-industry intersection (`q10_cross_prefecture_x_cross_industry.sql`)**.
  `INNER JOIN` between Wave 57 (10 geographic / prefecture-anchored
  packet kinds) and an industry-anchored set (Wave 60 trademark /
  vendor_due_diligence / succession_program_matching + Wave 53
  enforcement_industry_heatmap). Surfaces the deep-moat cohort — entities
  whose prefecture footprint AND industry footprint are both indexed.
  Schema gotcha caught + fixed during this run:
  `packet_enforcement_industry_heatmap_v1` has NO `subject` column (verified
  via `aws athena get-table-metadata`); its columns are `object_id /
  object_type / package_kind / created_at / cohort_definition / metrics /
  top_houjin / sources`. First Q10 attempt (`df65bd41-...`) FAILED with
  `COLUMN_NOT_FOUND: line 153:34: Column 'subject' cannot be resolved`.
  Fix: use `cohort_definition.cohort_id` (with `cohort_definition.industry_jsic_major`
  fallback) as the join key for that table. Re-run (`8eab5093-...`)
  SUCCEEDED. 29.29 MiB scan; INNER JOIN keeps row count small.

## Honest cross-check vs Wave 58 baseline + Wave 60 batch

- Q1 / Q2 byte counts match the values recorded in commit `f2ce90755`'s
  doc (`docs/_internal/wave56_58_s3_sync_2026_05_16.md`):
  - Q1: 15,086,948 B (this run) vs 15,086,948 B (sync doc) — identical.
  - Q2: 21,396,718 B (this run) vs 21,396,718 B (sync doc) — identical.
  Same packet corpus, same SQL, same scan footprint. The earlier 0-byte
  result during the Wave 60 batch was a race against the sync — fully
  closed.
- Q9 = 0.95 GiB, smaller than Q8's 0.93 GiB-scoped run only because Q8
  did not enumerate the Wave 56-58 prefixes (now populated). Combined
  with Q6 / Q7 already in the doc, the FY × family roll-up surface is
  now end-to-end on the 53-62 catalog.

## Files added in this commit

- `infra/aws/athena/big_queries/wave60/q9_allwave_fiscal_year_aggregation_53_62.sql`
- `infra/aws/athena/big_queries/wave60/q10_cross_prefecture_x_cross_industry.sql`
- `docs/_internal/athena_q1_q2_retry_2026_05_16.md` (this doc)

## Operational guardrails preserved

- 100 GB BytesScannedCutoffPerQuery workgroup cap honored (largest scan
  was 0.95 GiB, well under).
- `bookyou-recovery` profile used end-to-end (no other AWS profile
  touched).
- All scan numbers above pulled from
  `aws athena get-query-execution --query-execution-id <exec_id>` —
  no estimate / rounding / wishful aggregation. Q10's failure +
  re-run is recorded honestly above; the 4 reported queries are the
  4 SUCCEEDED final runs.
