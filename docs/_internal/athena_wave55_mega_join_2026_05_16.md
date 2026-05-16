# Athena Wave 55 — Mega Cross-Join 39 Packet Tables (2026-05-16)

Run kind: 1 "mother of all cross-joins" + 5 NEW big Athena queries over
the fully-populated derived bucket
`s3://jpcite-credit-993693061769-202605-derived/` after Wave 53.3 +
Wave 54 generators landed an additional ~107k JSON packets (cumulative
~315 MB) on top of the existing Wave 53 + foundation corpus.

Supersedes `docs/_internal/athena_real_burn_2026_05_16.md` (legacy 8-query
run with 19 tables registered). This run registers 20 additional tables
(Wave 53.3 = 10 + Wave 54 = 10) for a **total of 39 packet Glue tables**
and exercises the populated cross-Wave packet corpus end-to-end.

- Workgroup: `jpcite-credit-2026-05`
- Database:  `jpcite_credit_2026_05`
- Region:    `ap-northeast-1`
- Profile:   `bookyou-recovery`
- Result S3: `s3://jpcite-credit-993693061769-202605-reports/athena-results/`
- Athena rate: $5.00/TB scanned
- Budget cap per query: **$100** (advisory; workgroup also enforces a
  100 GB BytesScannedCutoffPerQuery)

## Glue catalog state at run time

**Pre-existing (19 tables, registered 2026-05-16 earlier)**: 3 foundation
(`packet_houjin_360`, `packet_acceptance_probability`,
`packet_program_lineage`) + 16 Wave 53 outcome tables.

**Tables added this run (20 new — Wave 53.3 + Wave 54)**:

| Wave | Table | S3 prefix | Approx file count |
| ---- | --- | --- | --: |
| 53.3 | `packet_patent_corp_360_v1`                  | `patent_corp_360_v1/`                  | 10,679 |
| 53.3 | `packet_environmental_compliance_radar_v1`   | `environmental_compliance_radar_v1/`   | 499 |
| 53.3 | `packet_statistical_cohort_proxy_v1`         | `statistical_cohort_proxy_v1/`         | 50 |
| 53.3 | `packet_diet_question_program_link_v1`       | `diet_question_program_link_v1/`       | 10,867 |
| 53.3 | `packet_edinet_finance_program_match_v1`     | `edinet_finance_program_match_v1/`     | 10,768 |
| 53.3 | `packet_trademark_brand_protection_v1`       | `trademark_brand_protection_v1/`       | 10,647 |
| 53.3 | `packet_statistics_market_size_v1`           | `statistics_market_size_v1/`           | 50 |
| 53.3 | `packet_cross_administrative_timeline_v1`    | `cross_administrative_timeline_v1/`    | 10,685 |
| 53.3 | `packet_public_procurement_trend_v1`         | `public_procurement_trend_v1/`         | 9 |
| 53.3 | `packet_regulation_impact_simulator_v1`      | `regulation_impact_simulator_v1/`      | 10,753 |
| 54   | `packet_patent_environmental_link_v1`        | `patent_environmental_link_v1/`        | 10,783 |
| 54   | `packet_diet_question_amendment_correlate_v1`| `diet_question_amendment_correlate_v1/`| 10,517 |
| 54   | `packet_edinet_program_subsidy_compounding_v1`| `edinet_program_subsidy_compounding_v1/`| 10,732 |
| 54   | `packet_kanpou_program_event_link_v1`        | `kanpou_program_event_link_v1/`        | 4,205 |
| 54   | `packet_kfs_saiketsu_industry_radar_v1`      | `kfs_saiketsu_industry_radar_v1/`      | 10 |
| 54   | `packet_municipal_budget_match_v1`           | `municipal_budget_match_v1/`           | 55 |
| 54   | `packet_trademark_industry_density_v1`       | `trademark_industry_density_v1/`       | 6 |
| 54   | `packet_environmental_disposal_radar_v1`     | `environmental_disposal_radar_v1/`     | 41 |
| 54   | `packet_regulatory_change_industry_impact_v1`| `regulatory_change_industry_impact_v1/`| 17 |
| 54   | `packet_gbiz_invoice_dispatch_match_v1`      | `gbiz_invoice_dispatch_match_v1/`      | 5,605 |

**Total tables in catalog**: **39** (3 foundation + 16 Wave 53 + 10
Wave 53.3 + 10 Wave 54). Registration ledger: `out/glue_packet_table_register.json`
(`total=39 ok=39`).

DDL serde: `org.openx.data.jsonserde.JsonSerDe` with
`ignore.malformed.json = true` and `case.insensitive = false`. Nested
struct columns are kept as JSON STRING for schema-drift resistance; all
mega-cross-join SQL projects use `json_extract_scalar(...)` /
`json_parse(...)` to traverse them.

## Per-query results (all 6 SUCCEEDED)

| # | Query | Kind | Bytes (MiB) | Cost (USD) | Total ms | ExecID |
| - | --- | --- | ---: | ---: | ---: | --- |
| 1 | wave55_mega_cross_join              | mega | 1,162.10 | $0.005541 | 36,526 | `ae495c9a-...` |
| 2 | wave55_cross_packet_entity_unique   | new  | 1,162.10 | $0.005541 | 30,900 | `69ed6d1e-...` |
| 3 | wave55_packet_size_distribution     | new  | 1,033.27 | $0.004927 | 29,744 | `22043cd7-...` |
| 4 | wave55_coverage_grade_breakdown     | new  | 1,033.27 | $0.004927 | 31,633 | `24132818-...` |
| 5 | wave55_outcome_freshness_trend      | new  | 1,162.10 | $0.005541 | 32,272 | `c13b85f8-...` |
| 6 | wave55_gap_code_frequency           | new  | 1,022.86 | $0.004877 | 29,711 | `4808016b-...` |

**Aggregate burn**: **6,895,125,076 bytes scanned (6.42 GiB)**, total
**$0.031354 USD** across 6 queries. Wall-clock total ~190 seconds.
**Zero queries exceeded the $100/query budget cap.**

Compared to the prior 8-query 2.22 GiB run (`athena_real_burn_2026_05_16.md`),
scan volume is **~3× higher** and total cost is **~2.9× higher**, despite
6 queries vs 8 — confirms the Wave 53.3 + Wave 54 corpus pushed the
per-query scan from ~700-860 MB into the **1 GiB band**.

### Query 1 — `wave55_mega_cross_join` (mother of all)

LEFT JOINs across all 39 packet tables on a normalized common dimension:
`subject_id` resolves to `subject.id` (when present) or
`cohort_definition.cohort_id` (fallback), with `subject_kind` carried
through for grouping. Aggregates per (subject_id, subject_kind):

- `source_table_presence`: count of distinct packet tables a subject appears in
- `total_packet_count`: total document hits across all 39 tables
- `avg_metric_value` / `max_metric_value`: representative metric per packet kind
- 5 individual presence counters (`n_houjin_360`, `n_acceptance`, `n_lineage`,
  `n_patent_360`, `n_gbiz_invoice`)
- `earliest_generated_at` / `latest_generated_at`

**Output**: LIMIT 5000 hit (the result row count cap; the underlying
mega-view aggregates over a **distinct houjin/cohort universe of 134,405
ids** — verified by a separate COUNT(DISTINCT) probe `65501f16-d66e-...`).
Top of the LIMIT 5000 sample distribution by `source_table_presence`:

| `source_table_presence` | rows in top 5000 |
| ---: | ---: |
| 8 | 22 |
| 7 | 121 |
| 6 | 367 |
| 5 | 1,165 |
| 4 | 3,325 |

The 22 subjects with `source_table_presence = 8` are 法人 (houjin_bangou)
that show up across at least 8 distinct Wave-53.3/54 packet axes —
material 法人 360 entities for downstream cohort delivery.

### Query 2 — `wave55_cross_packet_entity_unique`

`COUNT(DISTINCT subject_id)` per packet table. **uniqueness_ratio = 1.0
in every table** — confirms that the generators emit exactly one packet
per subject_id (the cohort_id key is fully bijective). Top by distinct
subject count: `packet_houjin_360` 86,849, `packet_company_public_baseline_v1`
17,123, `packet_vendor_due_diligence_v1` 16,484, `packet_invoice_*` 13,801,
`packet_application_strategy_v1` 11,208, Wave 53.3+54 outcome tables
each ~10,500-10,900.

### Query 3 — `wave55_packet_size_distribution`

Histogram of approximate per-packet bytes (sum of representative
struct-column lengths) per outcome. Notable findings:

- `packet_houjin_360`: total 99.1 MB, avg 1,140 B, p50=1,063 B, p95=1,455 B.
- `packet_edinet_finance_program_match_v1`: 8.1 MB total, p95=1,131 B.
- `packet_environmental_disposal_radar_v1`: only 41 docs but
  **avg 2,848 B** (heavy disposal_enforcements + municipality_actions
  payloads, p95=5,564 B).
- `packet_acceptance_probability`: total 0 bytes — the size proxy reads
  `cohort_definition + confidence_interval`, which the generator stores
  as compact JSON nullable strings that often serialize to length 0 in
  Athena STRING. **Honest gap**: size proxy under-counts this packet's
  real S3 footprint (225,600 rows × ~1 KB ≈ 220 MB on S3).

### Query 4 — `wave55_coverage_grade_breakdown`

A/B/C/D grade rubric over a normalized score (probability_estimate /
metric-saturating ratio for the 20 Wave 53.3+54 tables). Notable:

- `packet_municipal_budget_match_v1`: avg 0.846, 46 of 55 docs grade A.
- `packet_statistics_market_size_v1` / `packet_statistical_cohort_proxy_v1`:
  avg 0.966, 48 of 50 grade A — these are statistical packets with
  strong houjin_count signal.
- `packet_edinet_program_subsidy_compounding_v1`: avg 0.520, grade A=1,005
  / B=4,226 / C=5,501 — broad mid-band; subsidy_adoption_count is a
  meaningful signal across the corpus.
- `packet_houjin_360`: avg 0.471, almost entirely grade C (85,619 of
  86,849) — the coverage_score struct is uniform across the bulk run.
- `packet_acceptance_probability`: **11,505,600 rows projected** (the
  union pull touches all 225k acceptance JSON cohorts × ~50 query
  fan-out from the row builder), all grade D because `probability_estimate`
  is consistently below 0.25 by definition (the cohorts target rare
  hits). Honest interpretation: this is the only packet where the
  grade-D mass is **expected** rather than a quality gap.

### Query 5 — `wave55_outcome_freshness_trend`

Doc count per (source_table, day_bucket) where `day_bucket` = first 10
chars of `generated_at` (or `created_at` for the 16 slim Wave 53 tables).
All packets generated on **2026-05-16** (today's run). Top:
`packet_houjin_360` 86,849 / `packet_company_public_baseline_v1` 17,123
/ `packet_vendor_due_diligence_v1` 16,484 / Wave 53.3+54 outcome tables
each ~10,500-10,900 same-day.

This is expected — the Wave 53.3 + 54 generators landed inside today's
window. Once we run the Wave 55 (and beyond) generators on subsequent
days, this view becomes a real freshness gauge.

### Query 6 — `wave55_gap_code_frequency`

`UNNEST(json_parse(known_gaps))` across 23 packet tables (the 3
foundation + 20 Wave 53.3+54 — Wave 53 slim 16 do not carry
`known_gaps`). Top gap codes observed:

- `professional_review_required` — present in ~99% of Wave 53.3+54
  packets (1 row each). Confirms the descriptive-proxy disclaimer
  contract is fully wired (every packet flags the need for licensed
  professional review).
- `no_hit_not_absence` — paired with `professional_review_required` in
  4 packet families (`diet_question_amendment`, `environmental_disposal`,
  `patent_environmental_link`, `regulation_impact_simulator`).
- `identity_ambiguity_unresolved` — in `edinet_program_subsidy_compounding`
  (10,732 rows), `environmental_compliance_radar` (499 rows),
  `kfs_saiketsu_industry_radar` (10 rows).
- `freshness_stale_or_unknown` — 678 rows in `gbiz_invoice_dispatch_match_v1`
  (NTA invoice rows where `source_fetched_at = null` or stale).

The 7-enum gap code surface is **healthy and self-describing**. No
unexpected gap codes outside the canonical set.

### Initial failure + fix

`wave55_gap_code_frequency` first run FAILED with
`INVALID_CAST_ARGUMENT: Cannot cast to array(json). Expected a json
array, but got [...]` — `known_gaps` is stored as STRING (JSON text),
not JSON type. Fix landed in `wave55_gap_code_frequency.sql`: wrap each
column with `json_parse(known_gaps)` before `CAST(... AS array(json))`
on the UNNEST. Re-run succeeded (1,022.86 MiB / $0.004877 / 29,711 ms).

## SQL files added

- `infra/aws/athena/big_queries/wave55_mega_cross_join.sql` — the
  39-table mother-of-all cross-join.
- `infra/aws/athena/big_queries/wave55_cross_packet_entity_unique.sql`
- `infra/aws/athena/big_queries/wave55_packet_size_distribution.sql`
- `infra/aws/athena/big_queries/wave55_coverage_grade_breakdown.sql`
- `infra/aws/athena/big_queries/wave55_outcome_freshness_trend.sql`
- `infra/aws/athena/big_queries/wave55_gap_code_frequency.sql`

## Python scripts touched

- `scripts/aws_credit_ops/register_packet_glue_tables.py` — extended
  `PACKET_TABLES` from 19 → **39** entries (added 10 Wave 53.3 + 10
  Wave 54). `mypy --strict` + `ruff` clean.
- `scripts/aws_credit_ops/run_wave55_mega_athena_queries.py` — runs the
  6 queries, computes USD cost at $5/TB, emits per-query + aggregate
  JSON summary, also paginates result rows for the mega-join row count.
  `mypy --strict` + `ruff` clean.

## Artefacts

- Local SOT: `out/athena_wave55_mega_join_2026_05_16.json`
- Glue registration ledger: `out/glue_packet_table_register.json`
- Athena result CSVs: `s3://jpcite-credit-993693061769-202605-reports/athena-results/{exec_id}.csv`

## Re-run

```bash
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/register_packet_glue_tables.py   # idempotent (39 tables)

AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/run_wave55_mega_athena_queries.py
```

Each subsequent run is ~$0.031 at $5/TB.

## Headroom for higher burn

The 100 GB BytesScannedCutoffPerQuery workgroup cap remains in force.
Today's 6.42 GiB aggregate is 0.063% of the conceptual per-query cap.
To raise the burn meaningfully:

1. Land the remaining J16 OCR-extracted text corpus into Glue (the
   `J16_textract/` prefix already exists in S3 — currently 0 tables).
2. Add embeddings (`embeddings/`, `embeddings_burn/`) + `corpus_export/`
   JSONL prefixes as Glue tables (~310 MB + several GB respectively).
3. Materialize the mega-cross-join as a CTAS Parquet table, then run
   higher-dimensional joins against it (cuts per-query scan by 10x on
   re-use; first CTAS still touches the full corpus).

[lane:solo]

last_updated: 2026-05-16
