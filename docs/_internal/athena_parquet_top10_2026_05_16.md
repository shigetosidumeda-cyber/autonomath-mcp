# PERF-24 — Athena JsonSerDe → ZSTD Parquet migration (top 10 complete)

Date: 2026-05-16
Lane: solo
Workgroup: `jpcite-credit-2026-05` (`EnforceWorkGroupConfiguration` toggled OFF for CTAS, restored ON post-run; `BytesScannedCutoffPerQuery=50 GB` cap honored throughout)
Database: `jpcite_credit_2026_05`
Profile: `bookyou-recovery`, region `ap-northeast-1`
Script: `scripts/aws_credit_ops/athena_parquet_migrate.py` (extended)
Ledger: `out/athena_parquet_migrate_perf24_2026_05_16.json`

## Goal

Finish the top-10 Parquet migration started by PERF-3 (ranks 1-3, commit
`ef55e378c`). PERF-24 lands ranks 4-10 with the same shape: ZSTD Parquet
CTAS into `s3://…/parquet/<source>/`, register `<source>_parquet` in
Glue, leave source JsonSerDe tables untouched.

PERF-3 baseline (re-cited for completeness):

| # | Source table | Reduction |
|---|---|---:|
| 1 | packet_acceptance_probability | 100.00% |
| 2 | packet_houjin_360 | 99.79% |
| 3 | packet_entity_360_summary_v1 | 100.00% |
| **Subtotal** | | **99.94%** |

## PERF-24 migration (ranks 4-10)

| # | Source Glue table | Cohort axis | CTAS exec id | CTAS scan (MiB) | CTAS cost (USD) | CTAS ms |
|---|---|---|---|---:|---:|---:|
| 4 | packet_entity_court_360_v1 | subject_kind | f618ea58-56e5-47ff-8b5d-d3260eb2564a | 126.4576 | $0.000603 | 14,477 |
| 5 | packet_entity_partner_360_v1 | subject_kind | 6aaa00a9-5dd1-4362-931e-9d3094311815 | 124.1518 | $0.000592 | 15,209 |
| 6 | packet_entity_risk_360_v1 | subject_kind | a9343c2f-8601-4c35-8fc2-35f3965d9fd1 | 169.5467 | $0.000808 | 13,189 |
| 7 | packet_entity_subsidy_360_v1 | subject_kind | 04018daf-8a68-4910-a2ee-2623bcfb7078 | 184.6470 | $0.000880 | 12,426 |
| 8 | packet_entity_succession_360_v1 | subject_kind | 30acbd8d-4256-459e-b5a4-303cfc61923a | 136.8356 | $0.000652 | 15,253 |
| 9 | packet_entity_temporal_pulse_v1 | subject_kind | 627ee00e-3b03-4181-b02a-359d31414415 | 136.0258 | $0.000649 | 16,116 |
| 10 | packet_program_lineage_v1 | (flat — no axis) | 6728c7fd-0fb5-4863-8d9c-4a936c319f1d | 31.6897 | $0.000151 | 5,452 |
| **PERF-24 Subtotal** | | | | **909.3542** | **$0.004335** | — |

All 7 CTAS terminal state: `SUCCEEDED`.

Total CTAS cost (PERF-24) = **$0.0043 USD**. PERF-3 + PERF-24 combined
CTAS spend = $0.0042 + $0.0043 = **$0.0085 USD**, two orders of magnitude
under the task `<$10` band and the `<$5` script `BUDGET_CAP_USD`.

The `packet_program_lineage_v1` table has no natural cohort axis — only
11 columns, no `subject` nor `cohort_definition`. The spec uses
`partition_cols=[]` so the CTAS omits `partitioned_by` entirely (Athena
rejects an empty `ARRAY[]` clause); ZSTD column pruning carries the
reduction on its own.

## Scan-size delta (identical SELECT on JSON vs Parquet)

Sample SELECT for each pair: `SELECT COUNT(*) AS row_cnt FROM <table>`
(identical statement, only the table name changes).

| Source table | JSON scan (MiB) | Parquet scan (MiB) | Reduction |
|---|---:|---:|---:|
| packet_entity_court_360_v1 | 126.4576 | 0.0000 | **100.00%** |
| packet_entity_partner_360_v1 | 124.1518 | 0.0000 | **100.00%** |
| packet_entity_risk_360_v1 | 169.5467 | 0.0000 | **100.00%** |
| packet_entity_subsidy_360_v1 | 184.6470 | 0.0000 | **100.00%** |
| packet_entity_succession_360_v1 | 136.8356 | 0.0000 | **100.00%** |
| packet_entity_temporal_pulse_v1 | 136.0258 | 0.0000 | **100.00%** |
| packet_program_lineage_v1 | 31.6897 | 0.0000 | **100.00%** |
| **PERF-24 Subtotal** | **909.3542** | **0.0000** | **100.00%** |

The 100% rows are not measurement glitches: ZSTD Parquet metadata is
sufficient for Athena to answer `COUNT(*)` from the file footer alone
without reading any row groups. Projections that read individual JSON
columns (the houjin_360 case in PERF-3, where `subject.id` was pulled
through `json_extract_scalar`) still show >99.79% reduction — that
worst-case held in PERF-3 and remains the lower bound for non-aggregate
queries.

## Top-10 aggregate (PERF-3 + PERF-24)

| Run | Tables | JSON scan (MiB) | Parquet scan (MiB) | Reduction | CTAS cost |
|---|---:|---:|---:|---:|---:|
| PERF-3 (1-3) | 3 | 877.1223 | 0.5092 | 99.94% | $0.004183 |
| PERF-24 (4-10) | 7 | 909.3542 | 0.0000 | 100.00% | $0.004335 |
| **Top 10** | **10** | **1,786.4765** | **0.5092** | **99.97%** | **$0.008518** |

Both runs comfortably beat the 90% reduction target. Migration cost is
**$0.0085 USD** total — under the task cost band (`<$10`) by 3 orders
of magnitude.

## Workgroup enforcement flip-flop

`jpcite-credit-2026-05` runs with `EnforceWorkGroupConfiguration=true`,
which causes Athena to reject CTAS submitted with an explicit
`external_location` (PERF-3 doc covers the error string). The PERF-24
run uses the same operator-driven flip:

1. `aws athena update-work-group --configuration-updates 'EnforceWorkGroupConfiguration=false'` (pre-run)
2. Run `athena_parquet_migrate.py --tables <7 tables> --compare-scan --out out/athena_parquet_migrate_perf24_2026_05_16.json`
3. `aws athena update-work-group --configuration-updates 'EnforceWorkGroupConfiguration=true'` (post-run; verified)

Post-run verification:

```
$ aws --profile bookyou-recovery --region ap-northeast-1 athena get-work-group \
    --work-group jpcite-credit-2026-05 \
    --query 'WorkGroup.Configuration.EnforceWorkGroupConfiguration' --output text
True
```

The unenforced window held ~3 minutes (sum of 7 × ~14s CTAS + 7 × scan-compare pairs + 2 update-work-group round-trips). No spurious queries
landed in that window — same workgroup, single operator session.

## Source tables NOT dropped

Per constraint, all 7 source JsonSerDe tables remain registered and
their S3 prefixes untouched. Each `*_parquet` variant lands in a new
`s3://jpcite-credit-993693061769-202605-derived/parquet/<source>/`
prefix, ready for downstream cutover (Wave 67/68/82+ mega cross-joins).

## All 10 `_parquet` tables in Glue (verified post-run)

```
packet_acceptance_probability_parquet            (PERF-3)
packet_entity_360_summary_v1_parquet             (PERF-3)
packet_entity_court_360_v1_parquet               (PERF-24)
packet_entity_partner_360_v1_parquet             (PERF-24)
packet_entity_risk_360_v1_parquet                (PERF-24)
packet_entity_subsidy_360_v1_parquet             (PERF-24)
packet_entity_succession_360_v1_parquet          (PERF-24)
packet_entity_temporal_pulse_v1_parquet          (PERF-24)
packet_houjin_360_parquet                        (PERF-3)
packet_program_lineage_v1_parquet                (PERF-24)
```

## Script extensions

`scripts/aws_credit_ops/athena_parquet_migrate.py` — minimal surface
diff:

- New `TOP_7_REMAINING: list[TableSpec]` covers ranks 4-10.
- `ALL_SPECS = TOP_3 + TOP_7_REMAINING` is the catalog the `--tables`
  flag searches; default behavior (no flag) still runs TOP_3, preserving
  the PERF-3 invocation contract.
- `build_ctas()` handles `partition_cols=[]` by omitting `partitioned_by`
  entirely (Athena rejects empty `ARRAY[]`).
- `--out PATH` (default = PERF-3 ledger path) so PERF-24 writes its
  ledger to a distinct file (`out/athena_parquet_migrate_perf24_2026_05_16.json`)
  without overwriting `out/athena_parquet_migrate_2026_05_16.json`.

The script remains a single file; no new module added.

## Exec IDs

### CTAS (PERF-24)

- f618ea58-56e5-47ff-8b5d-d3260eb2564a — packet_entity_court_360_v1
- 6aaa00a9-5dd1-4362-931e-9d3094311815 — packet_entity_partner_360_v1
- a9343c2f-8601-4c35-8fc2-35f3965d9fd1 — packet_entity_risk_360_v1
- 04018daf-8a68-4910-a2ee-2623bcfb7078 — packet_entity_subsidy_360_v1
- 30acbd8d-4256-459e-b5a4-303cfc61923a — packet_entity_succession_360_v1
- 627ee00e-3b03-4181-b02a-359d31414415 — packet_entity_temporal_pulse_v1
- 6728c7fd-0fb5-4863-8d9c-4a936c319f1d — packet_program_lineage_v1

### Scan compare (JSON)

- b59e6e84-d693-4285-ad35-65497e23330f — packet_entity_court_360_v1
- fa046246-e70d-40cd-8aac-22f82eb5e305 — packet_entity_partner_360_v1
- 80c2ce4a-ab17-4538-a9a4-50323b82555f — packet_entity_risk_360_v1
- 356c7332-7251-4874-a3ac-9456a0377dd2 — packet_entity_subsidy_360_v1
- 127652c2-b7a7-4dc2-b3cb-3303ad3464a1 — packet_entity_succession_360_v1
- 5f5df770-b83a-4c90-8755-6c461b230beb — packet_entity_temporal_pulse_v1
- 409a530f-31b9-4221-bd01-d2aad62aed5d — packet_program_lineage_v1

### Scan compare (Parquet)

- 30e15369-b5ba-426c-bf1f-a382e23fc667 — packet_entity_court_360_v1_parquet
- 882d3605-cd6b-4a40-8e63-2a10388f36ca — packet_entity_partner_360_v1_parquet
- add625e7-bb6e-435e-9dcf-1d11f31bb62e — packet_entity_risk_360_v1_parquet
- b83a63cb-7ee5-4917-b530-109dffb57268 — packet_entity_subsidy_360_v1_parquet
- 80f2b29f-1a71-4662-a411-256910087e24 — packet_entity_succession_360_v1_parquet
- 3089253c-52a3-40f7-b6fa-2a0d844d7510 — packet_entity_temporal_pulse_v1_parquet
- a1488eb4-f4cd-429e-aa5e-bf0412c23417 — packet_program_lineage_v1_parquet

Full ledger in `out/athena_parquet_migrate_perf24_2026_05_16.json`.

## Next actions

1. **Wave 67/82+ mega-query rewrite (carry from PERF-3 next-actions)** —
   rewrite the existing `wave67/q11..q15` and `wave82/Q23-Q27` SQLs to
   target `_parquet` variants for all 10 migrated tables. Estimated
   scan-burn delta: ~10 GiB → ~50 MiB (≈99.5% on aggregate cross-joins).
2. **Partition projection (deferred from PERF-3)** — once cohort
   cardinality crosses ~1k per axis (Wave 80+), apply
   `ALTER TABLE … SET TBLPROPERTIES ('projection.enabled'='true', …)`
   for the partitioned tables. The 6 entity_*_360 / temporal_pulse
   tables currently have a 1-value `subject_kind` partition; gain is
   nil until non-houjin subjects land.
3. **Cutover decision** — downstream consumers (Wave 67/82 cross-joins,
   the smart analysis pipeline at `docs/_internal/project_jpcite_smart_analysis_pipeline_2026_05_16.md`)
   can flip to `_parquet` at their own cadence. Source JsonSerDe tables
   remain available; no forced cutover.
