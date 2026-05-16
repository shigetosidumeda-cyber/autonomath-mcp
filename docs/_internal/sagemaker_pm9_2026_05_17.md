# SageMaker PM9 Monitor + 3 Cross-Corpus Transform Jobs (2026-05-17 PM9)

**Status**: PM8 partial drain at PM9 submit. 0/5 PM8 jobs Completed at submit
moment (all still InProgress per `aws sagemaker list-transform-jobs`
sampled 2026-05-17 00:39 JST), PM7 adoption26cpu also still InProgress.
PM9 fires 3 new transform jobs (2 c5.2xlarge CPU + 1 g4dn.xlarge GPU) on
3 untouched cross-corpus truncated parts. All 3 confirmed `InProgress` at
2026-05-16T15:40:52Z UTC.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm8_2026_05_16.md` (run
`20260516T152037Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm9_submit.py`
(DRY_RUN default, `--commit` to fire).

---

## PM8 status at PM9 submit time (still draining)

| Tag | Instance | Status | Notes |
| --- | --- | --- | --- |
| `amlaw29cpu` | ml.c5.2xlarge | InProgress | started 00:23:27 JST |
| `amlaw30cpu` | ml.c5.2xlarge | InProgress | started 00:23:50 JST |
| `amlaw31cpu` | ml.c5.2xlarge | InProgress | started 00:24:10 JST |
| `amlaw32gpu` | ml.g4dn.xlarge | InProgress | started 00:23:12 JST |
| `amlaw33gpu` | ml.g4dn.xlarge | InProgress | started 00:23:59 JST |

PM7 status at PM9 submit time: 4 jobs Completed (amlaw24cpu / amlaw25cpu /
amlaw27gpu / amlaw28gpu), adoption26cpu **still InProgress** (started
2026-05-16T23:39:37 JST, ~80 min projected for 116K rows on CPU). No PM7
S3 output anomalies — PM7 GPU outputs ~42 GB each (verified PM8 doc),
PM7 CPU side will land standard ~1-2 GB each.

### Combined in-flight at PM9 submit (before adding PM9)

| Resource | Quota | PM7 in-flight | PM8 in-flight | PM9 new | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 1 (adoption26) | 3 | 2 | **6** | 2 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | 1 | **3** | 1 free |

PM9 stays within both quotas (6/8 CPU + 3/4 GPU). 2 CPU slots and 1 GPU
slot remain for PM10 follow-up.

### Verified S3 output (PM8 still draining)

`aws s3 ls embeddings_burn/amlaw-fix29-cpu/` ... `amlaw-fix33-gpu/`
all return empty at PM9 submit time (jobs still running). No
intermediate `.out` files surface for SageMaker batch transform until
the job reaches `Completed`. This is normal SageMaker behavior, not a
failure signal.

---

## PM9 plan (3 cross-corpus jobs)

PM9 explicitly leaves pure am_law saturation and grows on a **3-corpus
cross surface**. Honest framing on the original PM9 brief:

> The user's brief mentioned "Truncated court_decisions/ remaining parts"
> + "Other corpus tables not yet embedded". S3 inventory verify:
> `court_decisions` raw is single-part (part-0000 only, 1.4 MB),
> already truncated to 682.7 KB by PM5 (during the 20260516T19:29 trunc
> session) and embedded by `court21gpu` (PM5). There is **no** court
> part-0001 to embed.

Single-part corpora already fully drained at PM9 entry:
`programs/part-0000`, `invoice_registrants/part-0000`,
`nta_saiketsu/part-0000`, `nta_tsutatsu_index/part-0000`,
`court_decisions/part-0000` (all 1 part each, all done in PM5/PM6).

The genuinely **cross-corpus** untouched content remaining is:

| Source | Status before PM9 | Size raw | After trunc |
| --- | --- | --- | --- |
| `adoption_records/part-0001` | Untouched (PM7 handled part-0000 only) | 8.7 MB raw | 44,041 rows, 9.07 MB trunc |
| `am_law_article/part-0012` | Untouched (PM5/6/7/8 covered 0001..0011) | 20 MB raw | 24,429 rows, 16.08 MB trunc |
| `am_law_article/part-0013` | Untouched sentinel tail | 260 KB raw | 340 rows, 215.6 KB trunc |

The two am_law parts complete the `am_law_article` corpus (0001..0013
all embedded once PM9 + PM8 drain). adoption_records part-0001 is the
second adoption batch beyond PM7 `adoption26cpu` (which handled
part-0000, 116,335 rows).

### Sources prepared by /tmp/pm9_truncate.py

The 3 new trunc prefixes were materialized this run by
`/tmp/pm9_truncate.py` (streams raw `corpus_export/` JSONL, truncates
`inputs` to 320 chars for BERT 512 cap headroom, re-uploads to
`corpus_export_trunc/`):

| New trunc prefix | Source | In rows | Out rows | Size |
| --- | --- | --- | --- | --- |
| `corpus_export_trunc/adoption_records/part-0001.jsonl` | raw `corpus_export/adoption_records/part-0001.jsonl` | 44,041 | 44,041 | 9.07 MB |
| `corpus_export_trunc/am_law_article/part-0012.jsonl` | raw `corpus_export/am_law_article/part-0012.jsonl` | 24,429 | 24,429 | 16.08 MB |
| `corpus_export_trunc/am_law_article/part-0013.jsonl` | raw `corpus_export/am_law_article/part-0013.jsonl` | 340 | 340 | 215.6 KB |

Cumulative trunc input rows in PM9 batch: **68,810**.

### Run ID

`20260516T154052Z` (UTC = 2026-05-17 00:40:52 JST)

### Jobs submitted (3)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `adoption34cpu` | `jpcite-embed-20260516T154052Z-adoption34cpu` | ml.c5.2xlarge | `corpus_export_trunc/adoption_records/part-0001.jsonl` (9.07 MB / 44,041 rows) | `embeddings_burn/adoption-fix34-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw35cpu` | `jpcite-embed-20260516T154052Z-amlaw35cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0012.jsonl` (16.08 MB / 24,429 rows) | `embeddings_burn/amlaw-fix35-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw36gpu` | `jpcite-embed-20260516T154052Z-amlaw36gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0013.jsonl` (215.6 KB / 340 rows) | `embeddings_burn/amlaw-fix36-gpu/` | `jpcite-embed-allminilm-v1` |

All 3 Created and confirmed `InProgress` at 2026-05-16T15:40:52Z UTC.
Verified via:

```
aws sagemaker list-transform-jobs --region ap-northeast-1 \
    --query 'TransformJobSummaries[?contains(TransformJobName,`20260516T154052Z`)].[TransformJobName,TransformJobStatus]' \
    --profile bookyou-recovery
```

Returns 3 / 3 rows in state `InProgress` at submit + ~3 sec post-create.

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY` returned
`actual_usd = $1.931e-07` for May 2026 (Cost Explorer 8-12h lag
dominant). `$0.00` <<< `$13K` threshold -> submit proceeds. AWS Budget
Action at `$18,900` remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm9_submit.py:preflight_cost_check()`
calls `sys.exit(2)` if `actual_usd >= 13000` before any
`create_transform_job` invocation.

## Throughput projections

PM5-PM8 observed throughput baselines (rows / sec):

| Instance | corpus | observed | basis |
| --- | --- | --- | --- |
| c5.2xlarge CPU | am_law_article ~26K trunc | ~25-26 rows/sec | PM7 amlaw24cpu / amlaw25cpu |
| c5.2xlarge CPU | adoption_records ~116K trunc | ~25 rows/sec | PM7 adoption26cpu (projected) |
| g4dn.xlarge GPU | am_law_article ~28K trunc | ~12 rows/sec | PM7 amlaw27gpu / amlaw28gpu |

PM9 expected walltime per job:

| Tag | Instance | Rows | Est. rows/sec | Est. walltime |
| --- | --- | --- | --- | --- |
| `adoption34cpu` | c5.2xlarge | 44,041 | ~25 | ~29 min |
| `amlaw35cpu` | c5.2xlarge | 24,429 | ~25 | ~16 min |
| `amlaw36gpu` | g4dn.xlarge | 340 | ~12 | ~5-8 min (transform overhead dominates) |

## Cost estimate (PM9 run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| `adoption34cpu` | c5.2xlarge | $0.408 | ~29 min | $0.20 |
| `amlaw35cpu` | c5.2xlarge | $0.408 | ~16 min | $0.11 |
| `amlaw36gpu` | g4dn.xlarge | $0.94 | ~8 min | $0.13 |
| **Total** | | | | **~$0.44** |

PM5+PM6+PM7+PM8+PM9 combined cost trivially within $13K hard-stop /
$18.9K canary cap.

## Cumulative coverage snapshot (PM5 + PM6 + PM7 + PM8 + PM9)

| Corpus part | Status | Rows |
| --- | --- | --- |
| programs part-0000 (PM5 programs17) | Completed | 12,753 |
| invoice_registrants part-0000 (PM5 invoice18) | Completed | 13,801 |
| nta_saiketsu part-0000 (PM5 saiketsu19) | Completed | 137 |
| nta_tsutatsu_index part-0000 (PM5 tsutatsu20gpu) | Completed | 3,232 |
| court_decisions part-0000 (PM5 court21gpu) | Completed | 848 |
| am_law_article part-0001 (PM6 amlaw22gpu) | Completed | ~26K |
| am_law_article part-0002 (PM6 amlaw23gpu) | Completed | ~26K |
| am_law_article part-0003 (PM7 amlaw24cpu) | Completed | ~26K |
| am_law_article part-0004 (PM7 amlaw25cpu) | Completed | ~26K |
| adoption_records part-0000 (PM7 adoption26cpu) | InProgress | 116,335 |
| am_law_article part-0005 (PM7 amlaw27gpu) | Completed | 26,480 |
| am_law_article part-0006 (PM7 amlaw28gpu) | Completed | 28,764 |
| am_law_article part-0007 (PM8 amlaw29cpu) | InProgress | 28,049 |
| am_law_article part-0008 (PM8 amlaw30cpu) | InProgress | 27,252 |
| am_law_article part-0009 (PM8 amlaw31cpu) | InProgress | 26,332 |
| am_law_article part-0010 (PM8 amlaw32gpu) | InProgress | 28,014 |
| am_law_article part-0011 (PM8 amlaw33gpu) | InProgress | 26,232 |
| adoption_records part-0001 (PM9 adoption34cpu) | **InProgress** | 44,041 |
| am_law_article part-0012 (PM9 amlaw35cpu) | **InProgress** | 24,429 |
| am_law_article part-0013 (PM9 amlaw36gpu) | **InProgress** | 340 |
| **PM5+PM6+PM7+PM8+PM9 cumulative** | 9 done + 11 in-flight | **~480K** rows on target |

Target framing: PM9 closure puts cumulative embedded-rows on a path
toward ~480K (PM8 was ~412K; PM9 adds 68,810 rows = 14% over PM8).
Once both PM8 and PM9 drain, the entire `am_law_article` corpus
(part-0001..0013) plus `adoption_records` (part-0000..0001) plus
all single-part smaller corpora (programs, invoice, saiketsu, tsutatsu,
court) are fully embedded — this is the **complete jpcite cross-corpus
substrate**.

## Cross-corpus strategy framing

PM9 explicitly closes the **am_law tail** + opens the **adoption batch 2**
surface, not a pure am_law saturation. This matches the user's task
framing of "cross-corpus strategy scaffolding": instead of consuming
am_law parts indefinitely (the source is finite — 0001..0013 = 14
parts max, of which 1 is sentinel tail), PM9 also adds the second
adoption_records part as a cross-table surface and intentionally
exhausts the am_law tail so PM10+ can pivot to genuinely new corpora
ingested upstream (no more parts left in the current S3 inventory).

If/when new corpora become available (e.g., a regenerated
court_decisions with multi-part, or new am_enforcement_detail /
am_compat_matrix / am_amendment_diff exports), they enter the
PM10+ ladder. PM9 is the **last pure-tail** wave on the current
inventory snapshot.

## Followups (deferred — not part of this run)

1. Watch the 3 PM9 jobs to Completed; verify
   `embeddings_burn/{adoption-fix34-cpu,amlaw-fix35-cpu,amlaw-fix36-gpu}/`
   are non-empty (~1-2 GB CPU output per ~10-16 MB input,
   ~500 KB GPU output for the 340-row sentinel tail, based on
   PM6/PM7/PM8 ratio).
2. PM10 candidates: at PM9 entry there are **no untouched parts
   remaining** in the current S3 corpus inventory. PM10 will need
   either: (a) new corpus export run (regenerate raw, possibly
   multi-part for court / saiketsu / programs once those tables grow),
   (b) backfill of `am_enforcement_detail` / `am_compat_matrix` /
   `am_amendment_diff` corpus dumps, or (c) cross-corpus blended
   embedding training (not transform jobs).
3. Build per-corpus FAISS shards from the expanded `embeddings_burn/`
   set once PM7 + PM8 + PM9 all drain — FAISS expand task is already
   complete for PM5/PM6 substrate; PM7+PM8+PM9 outputs together add
   the next ~370K rows of embedded coverage.
4. Cross-corpus embedding strategy doc: after PM9 drains, the corpus
   is **complete** at the trunc layer. The next strategic step is
   **not** more embedding parts but rather FAISS expand + per-query
   cross-corpus search benchmarks against the unified embedding
   substrate.
