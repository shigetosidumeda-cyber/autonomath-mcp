# Athena 5 Big Cross-Join Query Run — 2026-05-16

Run kind: 5 big cross-source / cross-join Athena queries against the populated
derived bucket (`s3://jpcite-credit-993693061769-202605-derived/`).

Status: **all 5 queries FAILED** with identical TABLE_NOT_FOUND on `claim_refs`.
Root cause: the 5 query templates pre-date the receipt-assembly downstream — they
join `claim_refs` against `source_receipts` / `object_manifest`, but `claim_refs`
is an *optional* artifact per `scripts/aws_credit_ops/etl_raw_to_derived.py` (see
`REQUIRED_ARTIFACTS = frozenset({"object_manifest"})`). No crawl run has emitted
`claim_refs.jsonl` yet, so no Parquet partition exists and no Glue table was
registered. This is "schema-mismatch with current data" — pre-built queries
waiting for the next ETL phase, **not** a defect in the query SQL.

- Workgroup: `jpcite-credit-2026-05`
- Database:  `jpcite_credit_2026_05`
- Region:    `ap-northeast-1`
- Profile:   `bookyou-recovery`
- Result S3: `s3://jpcite-credit-993693061769-202605-derived/athena-results/`
- Report S3: `s3://jpcite-credit-993693061769-202605-derived/reports/athena_big_query_results/`
- Athena rate: $5.00/TB
- Budget cap per query: $50 (uniform)

## Glue catalog state at run time

Tables present: `known_gaps`, `object_manifest`, `source_receipts` (47 partitions
across the three, ~1,029 source_receipts rows).

Tables missing (referenced by 5 big queries): `claim_refs`.

Derived bucket prefixes present:
`J04_embeddings/`, `acceptance_probability/`, `corpus_export/`, `embeddings/`,
`embeddings_db/`, `known_gaps/`, `object_manifest/`, `source_receipts/` —
notably **no** `claim_refs/` prefix.

## Per-query results

| # | Query | ExecID | State | Bytes (MB / GB) | Cost (USD) | Rows | Total ms | Failure |
| - | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | houjin_360_full_crossjoin | `7a72f404-1d0b-457d-9c40-75f33807758b` | FAILED | 0 / 0.00 | $0.0000 | 0 | 532 | TABLE_NOT_FOUND: jpcite_credit_2026_05.claim_refs |
| 2 | program_lineage_full_trace | `de730494-490e-4385-bedd-776cb4658cb5` | FAILED | 0 / 0.00 | $0.0000 | 0 | 533 | TABLE_NOT_FOUND: jpcite_credit_2026_05.claim_refs |
| 3 | acceptance_probability_cohort_groupby | `6398a436-4254-4701-9ecc-7338c8bb7760` | FAILED | 0 / 0.00 | $0.0000 | 0 | 446 | TABLE_NOT_FOUND: jpcite_credit_2026_05.claim_refs |
| 4 | enforcement_industry_heatmap | `10a1a9b5-cfd7-483e-bcea-61bca4cf4596` | FAILED | 0 / 0.00 | $0.0000 | 0 | 597 | TABLE_NOT_FOUND: jpcite_credit_2026_05.claim_refs |
| 5 | cross_source_identity_resolution | `813614cc-818a-414e-b3b0-f4e5df516011` | FAILED | 0 / 0.00 | $0.0000 | 0 | 558 | TABLE_NOT_FOUND: jpcite_credit_2026_05.claim_refs |

Aggregate: 0 bytes scanned, **$0.0000 total cost**, 0 rows returned, 2,666 ms
total wall clock. All 5 failed at planning stage — no executor pages were
allocated. Budget cap $50/query never reached (0% utilisation across the run).

## Top 10 sample rows

None — all queries failed before row materialisation. No CSV result files were
written to `athena-results/` (Athena does emit a `.metadata` for the failure but
no payload).

## S3 artefacts uploaded

- `s3://jpcite-credit-993693061769-202605-derived/reports/athena_big_query_results/summary_2026-05-16.json`
- `s3://.../reports/athena_big_query_results/houjin_360_full_crossjoin.log`
- `s3://.../reports/athena_big_query_results/program_lineage_full_trace.log`
- `s3://.../reports/athena_big_query_results/acceptance_probability_cohort_groupby.log`
- `s3://.../reports/athena_big_query_results/enforcement_industry_heatmap.log`
- `s3://.../reports/athena_big_query_results/cross_source_identity_resolution.log`

Local: `out/athena_big_query_summary.json` (gitignored, S3 is the SOT).

## Remediation — to unblock the 5 big queries

1. Wire the crawler to emit `claim_refs.jsonl` per run
   (`docker/jpcite-crawler/entrypoint.py` + `manifest.py`). Schema already
   declared in `etl_raw_to_derived.py: ARTIFACT_SCHEMAS["claim_refs"]`
   (`claim_id, subject_kind, subject_id, claim_kind, value, source_receipt_ids,
   confidence`).
2. Re-run `scripts/aws_credit_ops/etl_raw_to_derived.py` to land Parquet
   under `s3://jpcite-credit-993693061769-202605-derived/claim_refs/run_id=.../`.
3. Run the Glue crawler against the derived bucket to register the new
   `claim_refs` table + partitions in `jpcite_credit_2026_05`.
4. Re-execute the 5 big queries; the queries themselves require no change.

Expected post-unblock scan: 40-80 GB at full corpus (~$0.20-0.40 per
houjin_360 execution) per the comment header in
`houjin_360_full_crossjoin.sql`. Current smoke corpus (~1,029
source_receipts rows + receipts-from-deep-runs) will scan well under 1 GB.
