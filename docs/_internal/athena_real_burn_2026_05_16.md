# Athena Real Burn — 8 Big Cross-Source Queries on Populated Packet Data (2026-05-16)

Run kind: 8 large cross-source / cross-join Athena queries against the
**populated** derived bucket `s3://jpcite-credit-993693061769-202605-derived/`
after Wave 53 full-scale packet generators landed real corpus data
(houjin_360 86,849 / acceptance_probability 225,600 / program_lineage
11,601 + 16 Wave 53 outcome tables totaling ~74k JSON docs).

Supersedes `docs/_internal/athena_big_query_run_2026-05-16.md` (legacy
5-query smoke run that pre-dated the packet ETL).

- Workgroup: `jpcite-credit-2026-05`
- Database:  `jpcite_credit_2026_05`
- Region:    `ap-northeast-1`
- Profile:   `bookyou-recovery`
- Result S3: `s3://jpcite-credit-993693061769-202605-derived/athena-results/`
- Athena rate: $5.00/TB scanned
- Budget cap per query: **$100** (operator can re-run)

## Glue catalog state at run time

Pre-existing tables: `claim_refs`, `known_gaps`, `object_manifest`,
`source_receipts` (all Parquet).

**Tables added this run (19 new):**

| Table | S3 prefix | File count |
| --- | --- | --: |
| `packet_houjin_360` | `houjin_360/` | 86,849 |
| `packet_acceptance_probability` | `acceptance_probability/` | 225,600 |
| `packet_program_lineage` | `program_lineage/` | 11,601 |
| `packet_application_strategy_v1` | `application_strategy_v1/` | 11,208 |
| `packet_bid_opportunity_matching_v1` | `bid_opportunity_matching_v1/` | 11 |
| `packet_cohort_program_recommendation_v1` | `cohort_program_recommendation_v1/` | 171 |
| `packet_company_public_baseline_v1` | `company_public_baseline_v1/` | 17,123 |
| `packet_enforcement_industry_heatmap_v1` | `enforcement_industry_heatmap_v1/` | 47 |
| `packet_invoice_houjin_cross_check_v1` | `invoice_houjin_cross_check_v1/` | 13,801 |
| `packet_invoice_registrant_public_check_v1` | `invoice_registrant_public_check_v1/` | 13,801 |
| `packet_kanpou_gazette_watch_v1` | `kanpou_gazette_watch_v1/` | 665 |
| `packet_local_government_subsidy_aggregator_v1` | `local_government_subsidy_aggregator_v1/` | 95 |
| `packet_permit_renewal_calendar_v1` | `permit_renewal_calendar_v1/` | 2 |
| `packet_program_law_amendment_impact_v1` | `program_law_amendment_impact_v1/` | 390 |
| `packet_regulatory_change_radar_v1` | `regulatory_change_radar_v1/` | 1 |
| `packet_subsidy_application_timeline_v1` | `subsidy_application_timeline_v1/` | 9 |
| `packet_succession_program_matching_v1` | `succession_program_matching_v1/` | 67 |
| `packet_tax_treaty_japan_inbound_v1` | `tax_treaty_japan_inbound_v1/` | 33 |
| `packet_vendor_due_diligence_v1` | `vendor_due_diligence_v1/` | 16,484 |

DDL serde: `org.openx.data.jsonserde.JsonSerDe` with
`ignore.malformed.json = true` and `case.insensitive = false`. Nested
struct columns kept as JSON STRING for schema-drift resistance; the 3
new packet-side queries below extract nested fields with
`json_extract_scalar(...)`. Registration script:
`scripts/aws_credit_ops/register_packet_glue_tables.py` (idempotent
`CREATE EXTERNAL TABLE IF NOT EXISTS`).

## Per-query results (all 8 SUCCEEDED)

| # | Query | Kind | ExecID | State | Bytes (MB) | Cost (USD) | Total ms |
| - | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | houjin_360_full_crossjoin | legacy | `c9f3...` | SUCCEEDED | 0.0015 | $0.000000 | 1,920 |
| 2 | program_lineage_full_trace | legacy | `c9f3...` | SUCCEEDED | 0.0039 | $0.000000 | 2,053 |
| 3 | acceptance_probability_cohort_groupby | legacy | `c9f3...` | SUCCEEDED | 0.0038 | $0.000000 | 1,681 |
| 4 | enforcement_industry_heatmap | legacy | `c9f3...` | SUCCEEDED | 0.0016 | $0.000000 | 2,119 |
| 5 | cross_source_identity_resolution | legacy | `c9f3...` | SUCCEEDED | 0.0000 | $0.000000 | 1,238 |
| 6 | **cross_packet_correlation** | **new** | `08c036c7-872f-4ffc-be5a-c95946e38667` | SUCCEEDED | **722.10** | **$0.003443** | 28,906 |
| 7 | **time_series_burn_pattern** | **new** | (run 6 in summary JSON) | SUCCEEDED | **861.21** | **$0.004107** | 24,312 |
| 8 | **entity_resolution_full** | **new** | `b8be6f04-947b-4038-b15a-ba858773ff82` | SUCCEEDED | **686.66** | **$0.003274** | 14,211 |

(legacy 5 exec IDs are recorded in
`out/athena_real_burn_2026_05_16.json` and the per-execution row in
the workgroup history — abbreviated above for table width.)

Aggregate: **2,380,255,182 bytes scanned (2.22 GiB)**, total burn
**$0.010824 USD** across 8 queries. Wall-clock total ~76 seconds.
**Zero queries exceeded the $100/query budget cap.**

### Why the legacy 5 scan ~0 MB

The legacy 5 join on `claim_refs` × `source_receipts` × `object_manifest`.
The crawler smoke run landed only 7 Parquet partitions of 1,392 bytes each
in `claim_refs/` (zero data rows). The Wave 53 packet generators write
directly to the per-outcome JSON prefixes and do not (yet) emit
`claim_refs.jsonl` rows — so the legacy 5 effectively read 7 tiny Parquet
footers and a trivial Hive split per partition, returning 0 rows. They
SUCCEEDED but did not exercise the populated data. To make them
meaningful, the next ETL pass must emit `claim_refs.jsonl` per packet
(plumbing already declared in
`scripts/aws_credit_ops/etl_raw_to_derived.py:
ARTIFACT_SCHEMAS["claim_refs"]`).

### Why the 3 new queries each scan ~700-860 MB

They read the populated JSON packet tables end-to-end (no partition
filter — `:run_id_filter` resolves to `'%'`). Each one fires a full
table scan over either 19 outcome tables (time_series_burn_pattern), 3
high-cardinality packets (cross_packet_correlation), or 5 corp-entity
packets (entity_resolution_full).

## SQL files added

- `infra/aws/athena/big_queries/cross_packet_correlation.sql` — joins
  houjin_360 ↔ acceptance_probability ↔ enforcement_heatmap on
  prefecture × jsic_major; emits `cohort_density_score`.
- `infra/aws/athena/big_queries/time_series_burn_pattern.sql` —
  19-table `UNION ALL` row-count-per-day-per-package_kind. Honest
  proof of how the credit run's outcomes accreted over time.
- `infra/aws/athena/big_queries/entity_resolution_full.sql` — 5-axis
  identity resolution (h360 ∪ invoice_cross ∪ invoice_registrant ∪
  company_baseline ∪ vendor_dd) by trimmed houjin_bangou. Emits
  `axis_presence_bitmap` (0..31) and `resolution_confidence`.

## Python scripts added

- `scripts/aws_credit_ops/register_packet_glue_tables.py` — registers
  19 Glue tables idempotently. `mypy --strict` + `ruff` clean.
- `scripts/aws_credit_ops/run_8_athena_big_queries.py` — runs all 8
  big queries, computes USD cost at $5/TB, emits per-query +
  aggregate JSON summary. `mypy --strict` + `ruff` clean.

## Artefacts

- Local SOT: `out/athena_real_burn_2026_05_16.json`
- Glue registration ledger: `out/glue_packet_table_register.json`
- Athena result CSVs: `s3://jpcite-credit-993693061769-202605-derived/athena-results/{exec_id}.csv`

## Re-run

```bash
AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/register_packet_glue_tables.py   # idempotent

AWS_PROFILE=bookyou-recovery AWS_REGION=ap-northeast-1 \
  .venv/bin/python scripts/aws_credit_ops/run_8_athena_big_queries.py
```

Each subsequent run is also charged at $5/TB; 8 queries ≈ $0.011 per
full re-run.

## Headroom for higher burn

The 100 GB BytesScannedCutoffPerQuery workgroup cap remains in force.
To burn $50/query, a single query needs to scan ≈ 10 GB; to burn
$500/query, ≈ 100 GB (i.e., the cap). Today's 2.22 GiB aggregate is
0.0218% of the per-query cap and 0.000018% of the conceptual $1M
ceiling at the per-query budget. To raise the burn meaningfully:

1. Land `claim_refs.jsonl` per packet so the legacy 5 join axes light up.
2. Add `embeddings/` and `corpus_export/` JSONL prefixes as Glue tables
   (~310 MB + several GB respectively).
3. Replace `LIMIT 1000` / `LIMIT 50000` / `LIMIT 200000` clauses with
   full-corpus aggregations and join on the populated facts.

Budget cap can be raised per query via `--budget-cap-usd` on
`scripts/aws_credit_ops/run_big_athena_query.sh`; the new runner
treats $100/query as informational (no kill switch).

last_updated: 2026-05-16
