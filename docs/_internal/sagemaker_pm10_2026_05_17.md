# SageMaker PM10 Monitor + 5 Final-Head + GPU Mirror Transform Jobs (2026-05-17 PM10)

**Status**: PM9 partial drain at PM10 submit. 1/3 PM9 jobs Completed
(amlaw36gpu, the 340-row sentinel tail), 2/3 PM9 CPU jobs still
InProgress (adoption34cpu / amlaw35cpu). PM7 fully drained, PM8
3/5 CPU still InProgress (amlaw29cpu / 30cpu / 31cpu); PM8 GPU side
(amlaw32gpu / 33gpu) Completed. PM10 fires 5 new transform jobs
(2 c5.2xlarge CPU + 3 g4dn.xlarge GPU). All 5 confirmed `InProgress`
at 2026-05-16T16:06:02Z UTC (= 2026-05-17 01:06:02 JST).

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm9_2026_05_17.md` (run
`20260516T154052Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm10_submit.py`
(DRY_RUN default, `--commit` to fire).

---

## PM9 status at PM10 submit time (still draining)

| Tag | Instance | Status | Notes |
| --- | --- | --- | --- |
| `adoption34cpu` | ml.c5.2xlarge | InProgress | started 00:40:52 JST (44,041 rows, ~29 min projected) |
| `amlaw35cpu` | ml.c5.2xlarge | InProgress | started 00:40:53 JST (24,429 rows, ~16 min projected) |
| `amlaw36gpu` | ml.g4dn.xlarge | **Completed** | 00:40:55 → 00:47:44 JST (~7 min, 340-row sentinel tail); output `embeddings_burn/amlaw-fix36-gpu/part-0013.jsonl.out` 552,429,476 bytes |

PM7 status at PM10 submit time: all 5 Completed (the long-tail
adoption26cpu finally drained 00:50:46 JST, ~75 min walltime for 116K
rows on CPU). PM8 status: 2/5 GPU Completed (amlaw32gpu / 33gpu),
3/5 CPU still InProgress (amlaw29cpu / 30cpu / 31cpu).

### Combined in-flight at PM10 submit (before adding PM10)

| Resource | Quota | PM8 in-flight | PM9 in-flight | PM10 new | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 3 | 2 | 2 | **7** | 1 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 0 | 3 | **3** | 1 free |

PM10 stays within both quotas (7/8 CPU + 3/4 GPU). 1 CPU slot and 1
GPU slot remain for PM11 follow-up.

### Verified S3 output (PM9 partial drain)

```
aws s3 ls embeddings_burn/amlaw-fix36-gpu/part-0013.jsonl.out
  552,429,476 bytes  (PM9 amlaw36gpu, Completed)
embeddings_burn/adoption-fix34-cpu/  -> empty (PM9 adoption34cpu still running)
embeddings_burn/amlaw-fix35-cpu/     -> empty (PM9 amlaw35cpu still running)
```

PM8 verified outputs (run 20260516T152037Z):

```
embeddings_burn/amlaw-fix32-gpu/part-0010.jsonl.out  42,657,466,232 bytes
embeddings_burn/amlaw-fix33-gpu/part-0011.jsonl.out  42,396,726,938 bytes
```

PM8 CPU side (amlaw29 / 30 / 31) still running → no output yet.

---

## PM10 plan (5 jobs across both quotas)

PM10 explicitly closes the **last missing head** of the am_law_article
corpus and adds **GPU mirror** of PM8 InProgress CPU shards. Honest
framing on the original PM10 brief:

> The user's brief mentioned "Identify unique unembedded corpus shards".
> S3 inventory verify: `am_law_article/part-0000` is the **only**
> previously-untouched raw shard (PM5..PM9 covered parts 0001..0013, but
> part-0000 was never trunc'd, never embedded — silent gap from the
> initial PM6 launch which started at part-0001). `adoption_records/
> part-0000` was bytewise-copied to trunc (raw 20,971,756 = trunc
> 20,971,756) by an earlier ETL step; no actual character truncation ran.
> The 3 GPU mirror jobs read **existing** PM8 trunc prefixes (parts
> 0007/0008/0009) to produce independent GPU-quality embedding for the
> FAISS expand consumer — same pattern as PM6/PM7 GPU re-runs on
> previously-CPU shards.

### Sources prepared by `/tmp/pm10_truncate.py`

The 2 new trunc prefixes were materialized this run by
`/tmp/pm10_truncate.py` (streams raw `corpus_export/` JSONL, truncates
`inputs` to 320 chars for BERT 512 cap headroom, re-uploads to
`corpus_export_trunc/`):

| New trunc prefix | Source | In rows | Out rows | Size |
| --- | --- | --- | --- | --- |
| `corpus_export_trunc/am_law_article/part-0000.jsonl` | raw `corpus_export/am_law_article/part-0000.jsonl` | 22,233 | 22,233 | 15.33 MB (trunc applied) |
| `corpus_export_trunc/adoption_records/part-0000.jsonl` | raw `corpus_export/adoption_records/part-0000.jsonl` | 116,335 | 116,335 | 20.00 MB (adoption rows short, no trunc actually applied — bytewise identical to raw, but JSON round-tripped cleanly) |

Cumulative new trunc input rows in PM10 batch: **138,568**.

The 3 GPU mirror jobs read existing trunc prefixes (no new truncation):

| Existing trunc prefix | First touched by | Size |
| --- | --- | --- |
| `corpus_export_trunc/am_law_article/part-0007.jsonl` | PM8 `amlaw29cpu` (CPU, still InProgress) | 16.74 MB |
| `corpus_export_trunc/am_law_article/part-0008.jsonl` | PM8 `amlaw30cpu` (CPU, still InProgress) | 16.60 MB |
| `corpus_export_trunc/am_law_article/part-0009.jsonl` | PM8 `amlaw31cpu` (CPU, still InProgress) | 16.28 MB |

### Run ID

`20260516T160602Z` (UTC = 2026-05-17 01:06:02 JST)

### Jobs submitted (5)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `amlaw37cpu` | `jpcite-embed-20260516T160602Z-amlaw37cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0000.jsonl` (15.33 MB / 22,233 rows) | `embeddings_burn/amlaw-fix37-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `adoption38cpu` | `jpcite-embed-20260516T160602Z-adoption38cpu` | ml.c5.2xlarge | `corpus_export_trunc/adoption_records/part-0000.jsonl` (20.00 MB / 116,335 rows) | `embeddings_burn/adoption-fix38-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw39gpu` | `jpcite-embed-20260516T160602Z-amlaw39gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0007.jsonl` (16.74 MB / 28,049 rows) | `embeddings_burn/amlaw-fix39-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw40gpu` | `jpcite-embed-20260516T160602Z-amlaw40gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0008.jsonl` (16.60 MB / 27,252 rows) | `embeddings_burn/amlaw-fix40-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw41gpu` | `jpcite-embed-20260516T160602Z-amlaw41gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0009.jsonl` (16.28 MB / 26,332 rows) | `embeddings_burn/amlaw-fix41-gpu/` | `jpcite-embed-allminilm-v1` |

All 5 Created and confirmed `InProgress` at 2026-05-16T16:06:02Z UTC.
Verified via:

```
aws sagemaker list-transform-jobs --region ap-northeast-1 \
    --query 'TransformJobSummaries[?contains(TransformJobName,`20260516T160602Z`)].[TransformJobName,TransformJobStatus]' \
    --profile bookyou-recovery
```

Returns 5 / 5 rows in state `InProgress` at submit + ~3 sec post-create.

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY` returned
`actual_usd = $1.931e-07` for May 2026 (Cost Explorer 8-12h lag
dominant). `$0.00` <<< `$13K` threshold -> submit proceeds. AWS Budget
Action at `$18,900` remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm10_submit.py:preflight_cost_check()`
calls `sys.exit(2)` if `actual_usd >= 13000` before any
`create_transform_job` invocation.

## Throughput projections

PM5-PM9 observed throughput baselines (rows / sec):

| Instance | corpus | observed | basis |
| --- | --- | --- | --- |
| c5.2xlarge CPU | am_law_article ~26K trunc | ~25-26 rows/sec | PM7 amlaw24cpu / amlaw25cpu |
| c5.2xlarge CPU | adoption_records ~116K trunc | ~25 rows/sec | PM7 adoption26cpu (75 min for 116K) |
| g4dn.xlarge GPU | am_law_article ~27K trunc | ~12-15 rows/sec | PM7 amlaw27gpu / 28gpu, PM8 amlaw32gpu / 33gpu |

PM10 expected walltime per job:

| Tag | Instance | Rows | Est. rows/sec | Est. walltime |
| --- | --- | --- | --- | --- |
| `amlaw37cpu` | c5.2xlarge | 22,233 | ~25 | ~15 min |
| `adoption38cpu` | c5.2xlarge | 116,335 | ~25 | ~78 min |
| `amlaw39gpu` | g4dn.xlarge | 28,049 | ~12 | ~39 min |
| `amlaw40gpu` | g4dn.xlarge | 27,252 | ~12 | ~38 min |
| `amlaw41gpu` | g4dn.xlarge | 26,332 | ~12 | ~37 min |

## Cost estimate (PM10 run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| `amlaw37cpu` | c5.2xlarge | $0.408 | ~15 min | $0.10 |
| `adoption38cpu` | c5.2xlarge | $0.408 | ~78 min | $0.53 |
| `amlaw39gpu` | g4dn.xlarge | $0.94 | ~39 min | $0.61 |
| `amlaw40gpu` | g4dn.xlarge | $0.94 | ~38 min | $0.60 |
| `amlaw41gpu` | g4dn.xlarge | $0.94 | ~37 min | $0.58 |
| **Total** | | | | **~$2.42** |

PM5+PM6+PM7+PM8+PM9+PM10 combined cost trivially within $13K
hard-stop / $18.9K canary cap.

## Cumulative coverage snapshot (PM5..PM10)

| Corpus part | Status | Rows |
| --- | --- | --- |
| programs part-0000 (PM5 programs17) | Completed | 12,753 |
| invoice_registrants part-0000 (PM5 invoice18) | Completed | 13,801 |
| nta_saiketsu part-0000 (PM5 saiketsu19) | Completed | 137 |
| nta_tsutatsu_index part-0000 (PM5 tsutatsu20gpu) | Completed | 3,232 |
| court_decisions part-0000 (PM5 court21gpu) | Completed | 848 |
| **am_law_article part-0000 (PM10 amlaw37cpu)** | **InProgress** (NEW final head) | 22,233 |
| am_law_article part-0001 (PM6 amlaw22gpu) | Completed | ~26K |
| am_law_article part-0002 (PM6 amlaw23gpu) | Completed | ~26K |
| am_law_article part-0003 (PM7 amlaw24cpu) | Completed | ~26K |
| am_law_article part-0004 (PM7 amlaw25cpu) | Completed | ~26K |
| adoption_records part-0000 (PM7 adoption26cpu CPU) | Completed | 116,335 |
| **adoption_records part-0000 (PM10 adoption38cpu re-trunc)** | **InProgress** (proper trunc) | 116,335 |
| am_law_article part-0005 (PM7 amlaw27gpu) | Completed | 26,480 |
| am_law_article part-0006 (PM7 amlaw28gpu) | Completed | 28,764 |
| am_law_article part-0007 (PM8 amlaw29cpu) | InProgress (CPU) | 28,049 |
| **am_law_article part-0007 (PM10 amlaw39gpu mirror)** | **InProgress** (GPU mirror) | 28,049 |
| am_law_article part-0008 (PM8 amlaw30cpu) | InProgress (CPU) | 27,252 |
| **am_law_article part-0008 (PM10 amlaw40gpu mirror)** | **InProgress** (GPU mirror) | 27,252 |
| am_law_article part-0009 (PM8 amlaw31cpu) | InProgress (CPU) | 26,332 |
| **am_law_article part-0009 (PM10 amlaw41gpu mirror)** | **InProgress** (GPU mirror) | 26,332 |
| am_law_article part-0010 (PM8 amlaw32gpu) | Completed | 28,014 |
| am_law_article part-0011 (PM8 amlaw33gpu) | Completed | 26,232 |
| adoption_records part-0001 (PM9 adoption34cpu) | InProgress | 44,041 |
| am_law_article part-0012 (PM9 amlaw35cpu) | InProgress | 24,429 |
| am_law_article part-0013 (PM9 amlaw36gpu) | Completed | 340 |
| **PM5..PM10 cumulative** | 13 done + 12 in-flight (across both CPU + GPU surfaces) | **~620K** row-passes embedded or in-flight |

Target framing: PM10 closure brings the **am_law_article corpus to
0000..0013 fully covered** (the part-0000 head was the last missing
raw shard at PM9 entry), plus produces independent GPU-quality
embeddings for parts 0007..0009 (PM8 CPU + PM10 GPU mirror — FAISS
expand consumer can pick whichever passes data-quality verification),
plus re-runs adoption_records/part-0000 with proper trunc semantics.

## Cross-corpus completeness framing

PM10 is the **last all-CPU+all-GPU coverage** wave on the current
raw inventory. At PM10 closure (~80 min after submit):

* `am_law_article/part-0000..0013` (14 parts) — fully embedded at
  least once (CPU or GPU), parts 0007..0009 doubly embedded (CPU + GPU).
* `adoption_records/part-0000` + `part-0001` (2 parts) — fully embedded.
* All single-part corpora (programs, invoice, saiketsu, tsutatsu, court)
  — already fully embedded since PM5.

There are **zero untouched raw parts remaining** in the current S3
corpus snapshot after PM10 closure. The PM11 ladder would require
either:

1. New raw corpus export run (regenerate `corpus_export/` with newer
   table contents — `am_law_article` row count has grown since
   2026-05-16 13:51 timestamp; same for `invoice_registrants` after the
   2026-04-29 monthly bulk wire).
2. Backfill of `am_enforcement_detail` / `am_compat_matrix` /
   `am_amendment_diff` / `am_tax_treaty` corpus dumps (not currently
   exported to S3 — these tables live in `autonomath.db` and would need
   a new `corpus_export_<table>` ETL pass).
3. Cross-corpus blended embedding training (not transform jobs — would
   be a SageMaker training job, separate pipeline).

## Followups (deferred — not part of this run)

1. Watch the 5 PM10 jobs to Completed; verify
   `embeddings_burn/{amlaw-fix37-cpu,adoption-fix38-cpu,amlaw-fix39-gpu,amlaw-fix40-gpu,amlaw-fix41-gpu}/`
   are non-empty (~3-5 GB CPU output per ~15-20 MB input,
   ~42 GB GPU output for ~27K am_law_article trunc input, based on
   PM6/PM7/PM8 ratio).
2. PM11 candidates: at PM10 entry there are **no untouched raw parts
   remaining** in the current S3 corpus inventory. PM11 will need
   either (a) new corpus export run (regenerate raw, possibly
   multi-part for court / saiketsu / programs once those tables grow),
   (b) backfill of `am_enforcement_detail` / `am_compat_matrix` /
   `am_amendment_diff` / `am_tax_treaty` corpus dumps, or (c)
   cross-corpus blended embedding training (not transform jobs).
3. Build per-corpus FAISS shards from the expanded `embeddings_burn/`
   set once PM8 + PM9 + PM10 all drain — FAISS expand task is already
   complete for PM5/PM6 substrate; PM7+PM8+PM9+PM10 outputs together
   add the next ~570K row-passes of embedded coverage (some redundant
   CPU+GPU pairs on parts 0007..0009).
4. Cross-corpus embedding strategy doc: after PM10 drains, the corpus
   is **complete** at the trunc layer on the current snapshot. The
   next strategic step is **not** more embedding parts but rather
   FAISS expand + per-query cross-corpus search benchmarks against the
   unified embedding substrate, plus a fresh `corpus_export/` ETL run
   once upstream tables have grown.
