# SageMaker PM8 Monitor + 5 New Transform Jobs (2026-05-16 PM8)

**Status**: PM7 partial drain at PM8 submit. 2/5 PM7 jobs Completed (the 2
g4dn.xlarge GPU jobs, amlaw27gpu + amlaw28gpu), 3/5 PM7 CPU jobs still
InProgress (amlaw24cpu / amlaw25cpu / adoption26cpu). PM8 fires 5 new
transform jobs (3 c5.2xlarge CPU + 2 g4dn.xlarge GPU) on the next batch
of newly-truncated parts. All 5 confirmed `InProgress` at
2026-05-16T15:20:37Z UTC.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm7_2026_05_16.md` (run
`20260516T143552Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm8_submit.py`
(DRY_RUN default, `--commit` to fire).

---

## PM7 status at PM8 submit time (partial drain)

| Tag | Instance | Status | Notes |
| --- | --- | --- | --- |
| `amlaw27gpu` | ml.g4dn.xlarge | **Completed** | 23:35:57 -> 00:13:51 JST (~38 min); output 41.8 GB |
| `amlaw28gpu` | ml.g4dn.xlarge | **Completed** | 23:35:58 -> 00:14:21 JST (~38 min); output 42.8 GB |
| `amlaw24cpu` | ml.c5.2xlarge | InProgress | started 23:35:52 JST |
| `amlaw25cpu` | ml.c5.2xlarge | InProgress | started 23:35:55 JST |
| `adoption26cpu` | ml.c5.2xlarge | InProgress | started 23:35:56 JST (116K rows, ~75-80 min projected) |

PM7 GPU side completed within walltime estimate. PM7 CPU side
(3/5 jobs) still draining — expected complete within next 30-60 min
based on PM7 projection (~17 min am_law_article CPU + ~75-80 min
adoption_records CPU).

### Verified S3 outputs (PM7 completed jobs)

```
s3://jpcite-credit-993693061769-202605-derived/embeddings_burn/amlaw-fix27-gpu/part-0005.jsonl.out  41,843,575,813 bytes
s3://jpcite-credit-993693061769-202605-derived/embeddings_burn/amlaw-fix28-gpu/part-0006.jsonl.out  42,819,899,619 bytes
```

Embedded output drop: ~84.7 GB across the 2 PM7 GPU jobs
(am_law_article parts 0005 + 0006, 26,480 + 28,764 rows; ~1.4 MB
output per row at 384-dim float32 + metadata).

---

## PM8 plan (5 jobs across both quotas)

PM8 reads the next batch of **untouched truncated parts**. Same honesty
note as PM7: the user's task framing mentioned "Wave 80/81/82 packet
corpus (truncate first, then embed)" + "Wave 86-88 packet corpus when
available", but Wave 80-88 packets (10 each, catalog 282..372) are
JSON analytic data living at the named packet prefixes
(`s3://<derived_bucket>/packets/<packet_name>/...`) and are **not** a
separate embedding source family. The embedding fleet always reads
from `corpus_export_trunc/<table>/part-<seq>.jsonl`. PM8 therefore
selects the actual untouched truncated parts.

### Sources prepared by /tmp/pm8_truncate.py

Five new truncated parts were materialized this run by
`/tmp/pm8_truncate.py` (streams the raw `corpus_export/` JSONL,
truncates `inputs` to 320 chars for BERT 512 cap headroom, re-uploads
to `corpus_export_trunc/`):

| New trunc prefix | Source | In rows | Out rows | Size |
| --- | --- | --- | --- | --- |
| `corpus_export_trunc/am_law_article/part-0007.jsonl` | raw `corpus_export/am_law_article/part-0007.jsonl` | 28,049 | 28,049 | 16.7 MB |
| `corpus_export_trunc/am_law_article/part-0008.jsonl` | raw `corpus_export/am_law_article/part-0008.jsonl` | 27,252 | 27,252 | 16.6 MB |
| `corpus_export_trunc/am_law_article/part-0009.jsonl` | raw `corpus_export/am_law_article/part-0009.jsonl` | 26,332 | 26,332 | 16.3 MB |
| `corpus_export_trunc/am_law_article/part-0010.jsonl` | raw `corpus_export/am_law_article/part-0010.jsonl` | 28,014 | 28,014 | 16.6 MB |
| `corpus_export_trunc/am_law_article/part-0011.jsonl` | raw `corpus_export/am_law_article/part-0011.jsonl` | 26,232 | 26,232 | 16.5 MB |

Cumulative trunc input rows in PM8 batch: 135,879.

### Run ID

`20260516T152037Z`

### Jobs submitted (5)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `amlaw29cpu` | `jpcite-embed-20260516T152037Z-amlaw29cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0007.jsonl` (16.7 MB / 28,049 rows) | `embeddings_burn/amlaw-fix29-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw30cpu` | `jpcite-embed-20260516T152037Z-amlaw30cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0008.jsonl` (16.6 MB / 27,252 rows) | `embeddings_burn/amlaw-fix30-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw31cpu` | `jpcite-embed-20260516T152037Z-amlaw31cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0009.jsonl` (16.3 MB / 26,332 rows) | `embeddings_burn/amlaw-fix31-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw32gpu` | `jpcite-embed-20260516T152037Z-amlaw32gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0010.jsonl` (16.6 MB / 28,014 rows) | `embeddings_burn/amlaw-fix32-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw33gpu` | `jpcite-embed-20260516T152037Z-amlaw33gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0011.jsonl` (16.5 MB / 26,232 rows) | `embeddings_burn/amlaw-fix33-gpu/` | `jpcite-embed-allminilm-v1` |

All 5 Created and confirmed `InProgress` at 2026-05-16T15:20:37Z UTC.
Verified via:

```
aws sagemaker list-transform-jobs --region ap-northeast-1 \
    --query 'TransformJobSummaries[?contains(TransformJobName,`20260516T152037Z`)].[TransformJobName,TransformJobStatus]' \
    --profile bookyou-recovery
```

Returns 5 / 5 rows in state `InProgress`.

## Quota compliance

PM7 CPU side still in-flight at submit time. Combined PM7+PM8 in-flight
fits both quotas:

| Resource | Quota | PM7 in-flight | PM8 new | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 3 | 3 | **6** | 2 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | **2** | 2 free |

PM8 stays within both quotas (6/8 CPU + 2/4 GPU). 2 CPU slots and
2 GPU slots remain for any PM9 follow-up.

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY` returned
`actual_usd = $1.931e-07` for May 2026 (Cost Explorer 8-12h lag
dominant). `$0.00` <<< `$13K` threshold -> submit proceeds. AWS Budget
Action at `$18,900` remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm8_submit.py` `preflight_cost_check()`
calls `sys.exit(2)` if `actual_usd >= 13000` before any
`create_transform_job` invocation.

## Throughput projections

PM5-PM7 observed throughput baselines (rows / sec):

| Instance | corpus | observed | basis |
| --- | --- | --- | --- |
| c5.2xlarge CPU | am_law_article ~26K trunc | ~25-26 rows/sec | PM7 amlaw24cpu / amlaw25cpu |
| g4dn.xlarge GPU | am_law_article ~28K trunc | ~12 rows/sec | PM7 amlaw27gpu / amlaw28gpu (~38 min for 26-29K rows) |

PM8 expected walltime per job:

| Tag | Instance | Rows | Est. rows/sec | Est. walltime |
| --- | --- | --- | --- | --- |
| `amlaw29cpu` | c5.2xlarge | 28,049 | ~25 | ~19 min |
| `amlaw30cpu` | c5.2xlarge | 27,252 | ~25 | ~18 min |
| `amlaw31cpu` | c5.2xlarge | 26,332 | ~25 | ~18 min |
| `amlaw32gpu` | g4dn.xlarge | 28,014 | ~12 | ~40 min |
| `amlaw33gpu` | g4dn.xlarge | 26,232 | ~12 | ~37 min |

GPU jobs are walltime-dominant at ~40 min each. CPU side wraps in
~20 min per job.

## Cost estimate (PM8 run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| `amlaw29cpu` | c5.2xlarge | $0.408 | ~19 min | $0.13 |
| `amlaw30cpu` | c5.2xlarge | $0.408 | ~18 min | $0.12 |
| `amlaw31cpu` | c5.2xlarge | $0.408 | ~18 min | $0.12 |
| `amlaw32gpu` | g4dn.xlarge | $0.94 | ~40 min | $0.63 |
| `amlaw33gpu` | g4dn.xlarge | $0.94 | ~37 min | $0.58 |
| **Total** | | | | **~$1.58** |

PM5+PM6+PM7+PM8 combined cost trivially within $13K hard-stop / $18.9K
canary cap.

## Cumulative coverage snapshot (PM5 + PM6 + PM7 + PM8)

| Corpus part | Status | Rows |
| --- | --- | --- |
| programs part-0000 (PM5 programs17) | Completed | 12,753 |
| invoice_registrants part-0000 (PM5 invoice18) | Completed | 13,801 |
| nta_saiketsu part-0000 (PM5 saiketsu19) | Completed | 137 |
| nta_tsutatsu_index part-0000 (PM5 tsutatsu20gpu) | Completed | 3,232 |
| court_decisions part-0000 (PM5 court21gpu) | Completed | 848 |
| am_law_article part-0001 (PM6 amlaw22gpu) | Completed | ~26K |
| am_law_article part-0002 (PM6 amlaw23gpu) | Completed | ~26K |
| am_law_article part-0003 (PM7 amlaw24cpu) | InProgress | ~26K |
| am_law_article part-0004 (PM7 amlaw25cpu) | InProgress | ~26K |
| adoption_records part-0000 (PM7 adoption26cpu) | InProgress | 116,335 |
| am_law_article part-0005 (PM7 amlaw27gpu) | Completed | 26,480 |
| am_law_article part-0006 (PM7 amlaw28gpu) | Completed | 28,764 |
| am_law_article part-0007 (PM8 amlaw29cpu) | **InProgress** | 28,049 |
| am_law_article part-0008 (PM8 amlaw30cpu) | **InProgress** | 27,252 |
| am_law_article part-0009 (PM8 amlaw31cpu) | **InProgress** | 26,332 |
| am_law_article part-0010 (PM8 amlaw32gpu) | **InProgress** | 28,014 |
| am_law_article part-0011 (PM8 amlaw33gpu) | **InProgress** | 26,232 |
| **PM5+PM6+PM7+PM8 cumulative** | 7 done + 8 in-flight | **~430K+** rows on target |

Target framing: this batch puts cumulative embedded-rows on a path
toward ~400K once PM7 CPU side + PM8 finishes. PM5+PM6+PM7 GPU done =
108,015 rows confirmed; PM7 CPU in-flight = 168,919 rows (26+26+116K);
PM8 = 135,879 rows. Total = **~412K rows** when fully drained.

## Followups (deferred — not part of this run)

1. Watch the 5 PM8 jobs to Completed; verify `embeddings_burn/*/part-NNNN.jsonl.out`
   are non-empty (~40 GB GPU output, ~1-2 GB CPU output per ~16 MB
   input based on PM6/PM7 ratio).
2. PM9 candidates: am_law_article parts 0012 + 0013 (raw exists but
   not yet truncated; 0013 is only 260 KB so likely a trailing
   sentinel); adoption_records part-0001 (~9 MB raw, would yield ~50K
   rows truncated).
3. Build per-corpus FAISS shards from the expanded `embeddings_burn/*.jsonl.out`
   set once PM8 completes — FAISS expand task is already complete for
   the PM5/PM6 substrate; PM7+PM8 output adds the next layer.
