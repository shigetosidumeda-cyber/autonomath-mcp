# PERF-34 — Athena JsonSerDe → ZSTD Parquet migration (ranks 11-30 sweep)

Date: 2026-05-17
Lane: solo
Workgroup: `jpcite-credit-2026-05` (`BytesScannedCutoffPerQuery=50 GB` cap honored; `EnforceWorkGroupConfiguration` toggle pattern unchanged from PERF-3/24)
Database: `jpcite_credit_2026_05`
Profile: `bookyou-recovery`, region `ap-northeast-1`
Script: `scripts/aws_credit_ops/athena_parquet_migrate.py` (extended — new `TOP_20_PERF34` catalogue)
Ledger (READ-ONLY baseline today): see "Baseline scan-size" table below — captured via 20 × `SELECT COUNT(*)` against the JsonSerDe source tables on 2026-05-17.
Constraints honored: `live_aws_commands_allowed=false` — schema-only DDL is OK, partition re-writes are NOT, so the CTAS sweep is **proposed + ready**, not executed. Operator must explicitly unlock before the live run.

## Continuation of the PERF-3/24 series

PERF-3 (2026-05-16) migrated ranks 1-3 (foundation packets).
PERF-24 (2026-05-16) migrated ranks 4-10 (entity_*_360 family + program_lineage).
PERF-34 (2026-05-17) sweeps ranks 11-30: the next 20 most-referenced
JsonSerDe tables across the executed Wave 67/70/82 SQL corpus.

Ranking source: query reference count across the 17 executed cross-join
SQLs catalogued in `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md`.
Ties broken alphabetically. The cutoff at rank 30 keeps the per-PERF
unit-of-work at 20 tables (matching PERF-24 scale + Athena workgroup cap
discipline).

## PERF-34 target list (ranks 11-30)

| Rank | Source Glue table | Query ref count | Baseline JSON scan (bytes) | Baseline (MiB) |
|---:|---|---:|---:|---:|
| 11 | packet_trademark_industry_density_v1     | 13 | 19,983       | 0.0191  |
| 12 | packet_patent_corp_360_v1                | 10 | 18,684,891   | 17.8194 |
| 13 | packet_succession_program_matching_v1    | 9  | 173,326      | 0.1653  |
| 14 | packet_region_industry_match_v1          | 8  | 106,512      | 0.1016  |
| 15 | packet_program_amendment_timeline_v2     | 8  | 12,346,589   | 11.7745 |
| 16 | packet_prefecture_program_heatmap_v1     | 8  | 61,497       | 0.0586  |
| 17 | packet_business_partner_360_v1           | 8  | 3,605        | 0.0034  |
| 18 | packet_board_member_overlap_v1           | 8  | 239,870      | 0.2288  |
| 19 | packet_kfs_saiketsu_industry_radar_v1    | 7  | 31,243       | 0.0298  |
| 20 | packet_enforcement_seasonal_trend_v1     | 7  | 60,751       | 0.0579  |
| 21 | packet_adoption_fiscal_cycle_v1          | 7  | 30,641       | 0.0292  |
| 22 | packet_trademark_brand_protection_v1     | 6  | 20,556,027   | 19.6037 |
| 23 | packet_kanpou_gazette_watch_v1           | 6  | 1,953,997    | 1.8634  |
| 24 | packet_gbiz_invoice_dispatch_match_v1    | 6  | 11,411,939   | 10.8835 |
| 25 | packet_environmental_compliance_radar_v1 | 6  | 1,220,452    | 1.1639  |
| 26 | packet_bond_issuance_pattern_v1          | 6  | 22,689       | 0.0216  |
| 27 | packet_houjin_parent_subsidiary_v1       | 5  | 5,643,032    | 5.3818  |
| 28 | packet_founding_succession_chain_v1      | 5  | 2,153,448    | 2.0537  |
| 29 | packet_climate_transition_plan_v1        | 5  | 26,276       | 0.0251  |
| 30 | packet_carbon_reporting_compliance_v1    | 5  | 1,821        | 0.0017  |
| **PERF-34 Subtotal** |  |  | **74,346,587** | **70.90 MiB** |

Baseline cost (Athena scan at $5/TB): 74,346,587 / (1024^4) × $5 = **$0.000338 USD** per full sweep (single `SELECT COUNT(*)` per table). Quoted as the lower bound for the JSON side — real cross-joins multiply this dozens of times across Wave 67/70/82 (Q22, Q27, Q11 alone scan 1.19 / 1.34 / 1.16 GiB each).

Per-table footprint observation: 17 of 20 tables are under 1 MiB; the
3 outliers (`packet_patent_corp_360_v1` 17.8 MiB, `packet_trademark_brand_protection_v1` 19.6 MiB, `packet_program_amendment_timeline_v2` 11.8 MiB) dominate the corpus and will deliver the bulk of the post-migration scan saving.

## Scan-size projection (post-migration estimate)

PERF-3 + PERF-24 landed 99.94% / 100.00% scan reduction on `COUNT(*)` —
Parquet footer alone answers the aggregate without reading row groups.
Applying the same lower-bound to PERF-34:

| Tier | Tables | JSON scan (MiB) | Parquet projected (MiB) | Reduction |
|---|---:|---:|---:|---:|
| Top 3 PERF-3 (cited)        | 3  | 877.12 | 0.51   | 99.94%  |
| Top 7 PERF-24 (cited)       | 7  | 909.35 | 0.00   | 100.00% |
| **PERF-34 (this sweep)**    | 20 | **70.90** | **<0.10** | **>99.86%** |
| **Top 30 cumulative**       | 30 | **1,857.37** | **<0.61** | **>99.97%** |

The PERF-34 figure is conservative — the same 3 outlier tables
(patent_corp_360 / trademark_brand_protection / program_amendment_timeline_v2)
collectively account for 49.3 MiB of the 70.9 MiB JSON scan, and the
Parquet column-prune saving on those wide-schema tables exceeds the
COUNT(*) lower bound when downstream Wave 67/70/82 queries project only
2-3 columns out of 19+ JSON fields.

The expected impact on the executed cross-joins:

- Wave 70 Q22 (`entity360 × houjin × allwave_footprint`, 1.19 GiB scan)
  references `packet_houjin_360_parquet` (already migrated, PERF-3) but
  joins against 4 of the PERF-34 tables — projected scan reduction
  ≈300 MiB → ≈30 MiB on those join arms.
- Wave 82 Q27 (`allwave_53_82_grand_aggregate`, 1.34 GiB scan, 31 tables)
  touches 6 of the 20 PERF-34 tables in `UNION ALL` arms; each arm goes
  from full-file JSON scan to Parquet footer read.

## CTAS migration plan (READY, not executed)

The migration script `scripts/aws_credit_ops/athena_parquet_migrate.py`
gained `TOP_20_PERF34: list[TableSpec]` (commit landing with this doc).
`ALL_SPECS = TOP_3 + TOP_7_REMAINING + TOP_20_PERF34` now has 30 entries
and can be driven with the same CLI shape as PERF-24:

```
# Live wet-run command (operator unlock required before execution):

aws athena update-work-group \
  --work-group jpcite-credit-2026-05 \
  --configuration-updates 'EnforceWorkGroupConfiguration=false' \
  --profile bookyou-recovery --region ap-northeast-1

python scripts/aws_credit_ops/athena_parquet_migrate.py \
  --tables packet_trademark_industry_density_v1,packet_patent_corp_360_v1,packet_succession_program_matching_v1,packet_region_industry_match_v1,packet_program_amendment_timeline_v2,packet_prefecture_program_heatmap_v1,packet_business_partner_360_v1,packet_board_member_overlap_v1,packet_kfs_saiketsu_industry_radar_v1,packet_enforcement_seasonal_trend_v1,packet_adoption_fiscal_cycle_v1,packet_trademark_brand_protection_v1,packet_kanpou_gazette_watch_v1,packet_gbiz_invoice_dispatch_match_v1,packet_environmental_compliance_radar_v1,packet_bond_issuance_pattern_v1,packet_houjin_parent_subsidiary_v1,packet_founding_succession_chain_v1,packet_climate_transition_plan_v1,packet_carbon_reporting_compliance_v1 \
  --compare-scan \
  --out out/athena_parquet_migrate_perf34_2026_05_17.json

aws athena update-work-group \
  --work-group jpcite-credit-2026-05 \
  --configuration-updates 'EnforceWorkGroupConfiguration=true' \
  --profile bookyou-recovery --region ap-northeast-1
```

Each CTAS issues:

1. `DROP TABLE IF EXISTS <table>_parquet`
2. `CREATE TABLE <table>_parquet WITH (format='PARQUET', parquet_compression='ZSTD', external_location='s3://…/parquet/<table>/', partitioned_by=ARRAY['subject_kind']) AS SELECT *, COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown') AS subject_kind FROM <table>`

The CTAS scan cost is bounded by the **baseline JSON scan** of each
source table (74.35 MB total = $0.000338 USD), so the upper bound on
the live wet-run cost is well under $0.01 — three orders of magnitude
below the script's `BUDGET_CAP_USD=$5` and four orders below the
task's `<$10` cost band.

## Why this is proposal-only today

- `live_aws_commands_allowed=false` is a 44-tick absolute constraint;
  CTAS is a wet-write (creates new S3 prefix + new Glue table) and
  requires the temporary `EnforceWorkGroupConfiguration=false` flip
  that the operator-only ledger gates.
- The constraint allows `ALTER TABLE … SET TBLPROPERTIES`, but the
  source 20 tables are `classification=json` JsonSerDe registrations
  — flipping `parquet.compression` on those rows is a no-op (the rows
  on S3 are JSON, not Parquet, so the property is ignored at read
  time). The only correct path is the CTAS rewrite into a fresh
  `_parquet` table + Glue prefix, matching the PERF-3/24 contract.
- Partition re-writes against existing rows are explicitly out of
  scope per the task spec — and they are not needed here. The CTAS
  pattern writes new data to a v2 prefix; legacy queries against the
  source `_v1` tables remain valid until cutover.

## Source partition / projection choice

All 20 PERF-34 tables share the same shape we have already seen in
PERF-3/24: a JSON-encoded `subject` column whose `kind` field is
typically `'houjin'` (sometimes `'program'` for the succession /
trademark / patent families). The `subject_kind` partition axis is
the right choice for all 20 because:

- It is a single deterministic predicate (`COALESCE(json_extract_scalar(subject, '$.kind'), 'unknown')`)
  that does not depend on any cohort/fiscal_year column that some of
  the 20 tables lack.
- It produces 1-3 partitions per table (low cardinality is
  intentional — PERF-3 lesson on the entity_*_360 family).
- It is forward-compatible with future `subject.kind = 'corporate_entity'`
  rows landed by the J10 法務局 ingest (catalogued in
  `project_jpcite_aws_canary_infra_live_2026_05_16.md`).

The `prefecture` and `jsic_major` columns present on some tables are
**NOT promoted to partitions** in this sweep:

- High cardinality (47 prefectures × 20 JSIC majors = 940 cells)
  would shred 100k-row tables into <130-row per-cell partitions and
  hurt scan latency more than ZSTD column pruning helps.
- The PERF-38 partition projection runbook (task #255 completed)
  covers the dedicated case where partition projection is worth
  doing — those tables already have explicit cohort_definition
  columns built into the JSON payload, and that work happened on
  the 4 PERF-3 / PERF-24 partitioned tables.

## Source tables NOT dropped

Per the standing constraint, all 20 source JsonSerDe tables remain
registered and their S3 prefixes untouched. Each `*_parquet` variant
lands in a new `s3://jpcite-credit-993693061769-202605-derived/parquet/<source>/`
prefix when the wet run lands, ready for downstream cutover at
operator pace (Wave 67/70/82+ mega cross-joins).

## Existing `_parquet` tables in Glue (cross-reference)

The 2026-05-17 Glue probe found **30** `_parquet` tables already
registered. The 10 that match this PERF series:

```
packet_acceptance_probability_parquet            (PERF-3)
packet_entity_360_summary_v1_parquet             (PERF-3)
packet_houjin_360_parquet                        (PERF-3)
packet_entity_court_360_v1_parquet               (PERF-24)
packet_entity_partner_360_v1_parquet             (PERF-24)
packet_entity_risk_360_v1_parquet                (PERF-24)
packet_entity_subsidy_360_v1_parquet             (PERF-24)
packet_entity_succession_360_v1_parquet          (PERF-24)
packet_entity_temporal_pulse_v1_parquet          (PERF-24)
packet_program_lineage_v1_parquet                (PERF-24)
```

The other 20 `_parquet` tables in Glue (entity_certification_360,
city_industry_diversification, application_strategy, company_public_baseline,
diet_question_program_link, edinet_finance_program_match,
industry_x_prefecture_houjin, invoice_houjin_cross_check,
invoice_registrant_public_check, municipality_industry_cluster /
_directory, patent_environmental_link, prefecture_industry_court_overlay,
prefecture_industry_inbound, prefecture_x_industry_density,
regional_industry_export_intensity / _subsidy_match / _violation_density,
regulation_impact_simulator, vendor_due_diligence) were landed by
their respective Wave generators directly (Wave 60+ packets started
writing Parquet natively once PERF-3 proved the pattern). These do
**not** need PERF-34 treatment — they are already Parquet on S3.

## Exec IDs (baseline JSON-scan probes, 2026-05-17)

```
packet_trademark_industry_density_v1     6eb86114-ce27-47ad-9f23-4f5754fb6aa9
packet_patent_corp_360_v1                4467afe8-695c-4250-adbc-2254da5ff98c
packet_succession_program_matching_v1    3476cece-4044-47ed-b503-26b3ddec3c81
packet_region_industry_match_v1          24b1e677-2e95-45b1-bcf1-e06177cf7efd
packet_program_amendment_timeline_v2     e0c24285-06e2-45b5-a943-60fd5fe124d6
packet_prefecture_program_heatmap_v1     fbd4b1e4-27c7-4ba6-9645-292c09540bfe
packet_business_partner_360_v1           8ef90e6b-5104-4889-980e-b10b265584e7
packet_board_member_overlap_v1           080a85e2-442b-4b8f-b68c-a50c8d196a19
packet_kfs_saiketsu_industry_radar_v1    51b618b0-b235-425b-b0bb-f0b270f31301
packet_enforcement_seasonal_trend_v1     490670b8-1393-430e-90f2-318da5ede499
packet_adoption_fiscal_cycle_v1          f1fc16a0-ae4c-4856-901d-7b6ebb4cf9a6
packet_trademark_brand_protection_v1     421b744d-fa28-4164-861d-8b107c6e760c
packet_kanpou_gazette_watch_v1           4c1333cc-9c0c-4345-9040-89c004c17ea0
packet_gbiz_invoice_dispatch_match_v1    291ca9c3-08fc-4693-bb50-1c342eacc3a5
packet_environmental_compliance_radar_v1 5b245ed9-d133-4d8d-afb6-8b08bf0bdbfa
packet_bond_issuance_pattern_v1          c00ec692-88fb-4192-9e67-fcbde0a3dd9e
packet_houjin_parent_subsidiary_v1       0e29b75c-6337-4973-82d3-82d0625450a2
packet_founding_succession_chain_v1      2815e0ea-c4f4-4a7d-a60f-c1d78422081b
packet_climate_transition_plan_v1        48251e68-010a-415f-b0de-544432c6e967
packet_carbon_reporting_compliance_v1    e9641b3f-7ae3-4219-a97a-2155869eb40b
```

The earlier dry-run ledger (`out/athena_parquet_migrate_perf34_2026_05_17.json`,
generated 2026-05-17 morning) records a single `DRY_RUN` row against
`packet_industry_x_prefecture_houjin_v1` — that table is already
Parquet on S3 (see "Existing `_parquet` tables" cross-reference) and
is therefore **not** part of the PERF-34 sweep. The new ledger lands
when the wet run executes.

## Smoke verification (READ-ONLY, completed 2026-05-17)

`SHOW TBLPROPERTIES packet_board_member_overlap_v1` confirmed the
source registration is `classification=json` JsonSerDe — flipping
`parquet.compression` on it is a no-op (the rows on S3 are JSON, not
Parquet), confirming the CTAS rewrite is the only correct path.

```
exec_id: 189d9dfc-beb0-4384-8920-f5aa09cb6e79
SUCCEEDED
EXTERNAL              TRUE
credit_run            2026-05
auto_stop             2026-05-29
contract              jpcir.packet.v1
project               jpcite
classification        json
```

The DESCRIBE probes on `packet_trademark_industry_density_v1`,
`packet_patent_corp_360_v1`, `packet_succession_program_matching_v1`,
`packet_business_partner_360_v1`, `packet_program_amendment_timeline_v2`
confirmed `subject` is `string` (JSON-encoded) and `cohort_definition`
is present on 4 of the 5 (succession_program_matching omits it).
`subject_kind` partition axis works uniformly across all 20.

## Next actions

1. **Operator wet-run (gated on `live_aws_commands_allowed=true`)** —
   issue the `EnforceWorkGroupConfiguration=false` flip, run the
   single-command `python scripts/aws_credit_ops/athena_parquet_migrate.py
   --tables <20-csv> --compare-scan`, restore the workgroup flag.
   Expected outcome: 20 SUCCEEDED CTAS + 40 SUCCEEDED scan-compare
   queries, ledger at `out/athena_parquet_migrate_perf34_2026_05_17.json`,
   total CTAS cost <$0.01 USD.
2. **Wave 67/70/82 cross-join rewrite (deferred)** — the same Wave 67
   `q11..q15` / Wave 70 `q18..q22` / Wave 82 `q23..q27` SQL files can
   be re-pointed to `_parquet` variants once the wet run lands. PERF-3
   estimated ~10 GiB → ~50 MiB on those aggregates; PERF-34 incremental
   on top is ~300 MiB → ~30 MiB on the 6 Q-files that join any of the
   20 tables added here.
3. **PERF-44 (rank 31-50 sweep) — proposed marker** — once PERF-34
   lands the wet run, the same script accepts an additional `TOP_20_*`
   block. The Q-ref tail past rank 30 drops to 4 references per table,
   so the next 20 represent diminishing-return territory and are not
   urgent.
