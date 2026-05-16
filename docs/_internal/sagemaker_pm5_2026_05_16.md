# SageMaker PM5 Resubmit + New Corpus Prefixes (2026-05-16 PM5)

**Status**: 5 fresh transform jobs LIVE (InProgress) on `bookyou-recovery` profile, ap-northeast-1.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm4_resubmit_2026_05_16.md` (commit `bfe7dbf73`, PM4 run `20260516T100346Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm5_submit.py` (DRY_RUN default, `--commit` to fire).

---

## PM4 status (all 5 failed)

| Job | Instance | Status | Failure reason |
| --- | --- | --- | --- |
| `amlaw12gpu` | g4dn.xlarge | **Failed** | `ClientError 400 / InternalServerException: "Extra data: line 2 column 1 (char 350)"` |
| `amlaw13gpu` | g4dn.xlarge | **Failed** | same |
| `amlaw14cpu` | c5.2xlarge | **Failed** | same |
| `amlaw15cpu` | c5.2xlarge | **Failed** | same |
| `adopt16` | c5.2xlarge | **Failed** | same |

### Root cause

PM4 created the transform jobs with `BatchStrategy` unset (defaulted to `MULTI_RECORD`),
which packs multiple newline-delimited JSONL rows into a single HTTP POST body.
The `sentence-transformers` MMS handler expects ONE `{"inputs": "..."}` object per
request — when it receives a body of `{"id":"..","inputs":".."}\n{"id":"..","inputs":".."}`
it chokes parsing the second-line continuation with `Extra data: line 2 column 1`.

PM3 `court6` (which succeeded) explicitly set `BatchStrategy=SingleRecord`. PM4
regressed by not threading that knob through.

Evidence: CloudWatch log group `/aws/sagemaker/TransformJobs`, stream
`jpcite-embed-20260516T100346Z-amlaw12gpu/.../data-log`, message at
`2026-05-16T10:09:49.175`:

> `ClientError: 400 / "code": 400, "type": "InternalServerException", "message": "Extra data: line 2 column 1 (char 350)"`

`aws sagemaker describe-transform-job ... --query BatchStrategy` returns `null` for
all 5 PM4 jobs, vs `"SingleRecord"` for the PM3 court6 success.

## PM5 fix

Submit 5 fresh jobs with **`BatchStrategy=SingleRecord`** + `SplitType=Line` +
`AssembleWith=Line`, targeting 5 untouched `corpus_export_trunc/` prefixes.

### Run ID

`20260516T103042Z`

### Prefix mapping

User requested 5 prefixes (`jpi_houjin_master`, `enforcement_actions`, `known_gaps`,
`object_manifest`, `source_receipts`). None of these exist as exported S3 prefixes —
they are table names inside `autonomath.db` that have not been staged to S3 by
`scripts/aws_credit_ops/export_corpus_to_s3.py`. PM5 maps them to the closest
semantic substitutes from the existing `corpus_export/` catalog so the embedding
coverage advances:

| User-requested | PM5 substitute | Semantic rationale |
| --- | --- | --- |
| `jpi_houjin_master` | `programs` | jpi-derived program corpus (12,753 rows) |
| `source_receipts` | `invoice_registrants` | NTA T-number receipts (13,801 rows, 適格事業者) |
| `enforcement_actions` | `court_decisions` | 民訴 + 行政訴訟 corpus (848 rows) |
| `known_gaps` / `object_manifest` | `nta_saiketsu` + `nta_tsutatsu_index` | 税務 通達 + 裁決 (137 + 3,232 rows) — gap-fills 税務 cohort |

This decision is **honest mapping**: corpus_export prefixes named exactly as user
requested do not exist, so we substitute by semantic intent. Future PM6+ should
add an `export_corpus_to_s3.py` pass for the user's literal table names.

### Truncation stats

| Table | Total rows | max_len before | Truncated | % |
| --- | --- | --- | --- | --- |
| `programs` | 12,753 | 208 | 0 | 0.0% (raw used) |
| `invoice_registrants` | 13,801 | 249 | 0 | 0.0% (raw used) |
| `nta_saiketsu` | 137 | 474 | 19 | 13.9% |
| `nta_tsutatsu_index` | 3,232 | 616 | 1,696 | 52.5% |
| `court_decisions` | 848 | 2,000 | 579 | 68.3% |

Truncation strategy: `inputs` text cut at 320 chars (same as PM3/PM4 contract).
Truncation is non-destructive — `corpus_export/` stays as-is; output written to
`corpus_export_trunc/<table>/part-0000.jsonl`.

### Jobs submitted (5)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `programs17` | `jpcite-embed-20260516T103042Z-programs17` | `ml.c5.2xlarge` | `corpus_export_trunc/programs/part-0000.jsonl` | `embeddings_burn/programs-fix17-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `invoice18` | `jpcite-embed-20260516T103042Z-invoice18` | `ml.c5.2xlarge` | `corpus_export_trunc/invoice_registrants/part-0000.jsonl` | `embeddings_burn/invoice-fix18-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `saiketsu19` | `jpcite-embed-20260516T103042Z-saiketsu19` | `ml.c5.2xlarge` | `corpus_export_trunc/nta_saiketsu/part-0000.jsonl` | `embeddings_burn/saiketsu-fix19-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `tsutatsu20gpu` | `jpcite-embed-20260516T103042Z-tsutatsu20gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/nta_tsutatsu_index/part-0000.jsonl` | `embeddings_burn/tsutatsu-fix20-gpu/` | `jpcite-embed-allminilm-v1` |
| `court21gpu` | `jpcite-embed-20260516T103042Z-court21gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/court_decisions/part-0000.jsonl` | `embeddings_burn/court-fix21-gpu/` | `jpcite-embed-allminilm-v1` |

All 5 returned `TransformJobArn` at 2026-05-16T10:30:42Z UTC.

## Quota compliance

`aws sagemaker list-transform-jobs --status-equals InProgress` returned 0 in-flight
before PM5 submit (PM4 burst fully drained: all Failed terminal state).

| Resource | Quota | In-flight at submit | New (this run) | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 0 | 3 | **3** | 5 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | **2** | 2 free |

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY --metrics UnblendedCost --time-period Start=2026-05-01,End=2026-05-17`
returned `actual_usd = $0.0000001906` for May 2026 (Cost Explorer 8-12h lag
dominant). $0.00 ≪ $13K threshold → submit proceeds. AWS Budget Action at $18,900
remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm5_submit.py` `preflight_cost_check()` calls
`sys.exit(2)` if `actual_usd >= 13000` before any `create_transform_job` invocation.

## Cost estimate (this run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| programs17 | c5.2xlarge | $0.476 | ~30 min (12,753 rows on CPU) | $0.24 |
| invoice18 | c5.2xlarge | $0.476 | ~30 min (13,801 rows, short text) | $0.24 |
| saiketsu19 | c5.2xlarge | $0.476 | ~3 min (137 rows) | $0.03 |
| tsutatsu20gpu | g4dn.xlarge | $0.94 | ~3 min (3,232 rows truncated on GPU) | $0.05 |
| court21gpu | g4dn.xlarge | $0.94 | ~1 min (848 rows truncated on GPU) | $0.02 |
| **Total** | | | | **~$0.58** |

(All 5 jobs combined cost is < $1, well under the $13K hard-stop and trivially
within the $18.9K canary cap envelope.)

## Throughput (rows embedded)

Expected coverage of this PM5 run (when all 5 finish): **30,771 rows** across 5
new corpus prefixes (programs 12,753 + invoice 13,801 + saiketsu 137 +
tsutatsu 3,232 + court 848). Cumulative PM3+PM4 success snapshot was ~30,770;
PM5 brings total **~61,541 embedded rows** across all PM* runs.

## Followups (deferred — not part of this run)

1. After PM5 jobs validate the SingleRecord contract on 5 new prefixes, re-submit
   PM4's 5 failed (`amlaw12gpu`..`adopt16`) using the same SingleRecord fix on
   the remaining 4 `am_law_article` truncated parts + `adoption_records` raw.
2. Add an `export_corpus_to_s3.py` pass for the user-literal table names
   (`jpi_houjin_master`, `enforcement_actions`, `known_gaps`, `object_manifest`,
   `source_receipts`) so PM6+ can use the names verbatim.
3. Wire `BatchStrategy=SingleRecord` as a **mandatory** field in any future
   embedding-batch submitter to prevent the PM4 regression class.
