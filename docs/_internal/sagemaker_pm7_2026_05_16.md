# SageMaker PM7 Monitor + 5 New Transform Jobs (2026-05-16 PM7)

**Status**: PM6 fully drained (2/2 g4dn.xlarge Completed at 19:51-19:59 JST).
PM7 fires 5 new transform jobs (3 c5.2xlarge CPU + 2 g4dn.xlarge GPU)
on the next batch of truncated parts. All 5 confirmed `InProgress` at
2026-05-16T14:35:52Z UTC (23:35:52 JST).

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_pm6_2026_05_16.md`
(commit successor of PM5 ledger, PM6 run `20260516T105156Z`).

**Driver**: `scripts/aws_credit_ops/sagemaker_pm7_submit.py`
(DRY_RUN default, `--commit` to fire).

---

## PM6 final status (2/2 Completed)

| Tag | Instance | Status | Start (JST) | End (JST) | Wall | Output bytes |
| --- | --- | --- | --- | --- | --- | --- |
| `amlaw22gpu` | ml.g4dn.xlarge | **Completed** | 19:51:57 | ~19:58:23 | ~6.5 min | 43,839,257,600 (43.8 GB) |
| `amlaw23gpu` | ml.g4dn.xlarge | **Completed** | 19:51:58 | ~19:59:00 | ~7 min | 42,746,536,826 (42.7 GB) |

Embedded output drop: ~86.6 GB across the 2 PM6 jobs (am_law_article
parts 0001 + 0002, 17.2 + 16.7 MB truncated input each, embedded as
allMiniLM 384-dim vectors per row).

---

## PM7 plan (5 jobs across both quotas)

PM7 reads the next batch of **untouched truncated parts**. Note: the
user's task framing mentioned "Wave 80-82 newly synced corpus", but
Wave 80-82 packets (10 each, catalog 282..312) are JSON analytic
data living at the named packet prefixes
(`s3://<derived_bucket>/packets/<packet_name>/...`) and are **not**
a separate embedding source family. The embedding fleet always reads
from `corpus_export_trunc/<table>/part-<seq>.jsonl`. PM7 therefore
selects the actual untouched truncated parts.

### Sources prepared by /tmp/pm7_truncate.py

Three new truncated parts were materialized this run by
`/tmp/pm7_truncate.py` (streams the raw `corpus_export/` JSONL,
truncates `inputs` to 320 chars for BERT 512 cap headroom, re-uploads
to `corpus_export_trunc/`):

| New trunc prefix | Source | In rows | Out rows | Size |
| --- | --- | --- | --- | --- |
| `corpus_export_trunc/am_law_article/part-0005.jsonl` | raw `corpus_export/am_law_article/part-0005.jsonl` | 26,480 | 26,480 | 16.3 MB |
| `corpus_export_trunc/am_law_article/part-0006.jsonl` | raw `corpus_export/am_law_article/part-0006.jsonl` | 28,764 | 28,764 | 16.7 MB |
| `corpus_export_trunc/adoption_records/part-0000.jsonl` | raw `corpus_export/adoption_records/part-0000.jsonl` | 116,335 | 116,335 | 21.0 MB |

The two existing truncated parts (`am_law_article/part-0003.jsonl`
+ `am_law_article/part-0004.jsonl`, 16.8 MB each) were already present
but never embedded; PM7 consumes them on the CPU side.

### Run ID

`20260516T143552Z`

### Jobs submitted (5)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `amlaw24cpu` | `jpcite-embed-20260516T143552Z-amlaw24cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0003.jsonl` (16.8 MB) | `embeddings_burn/amlaw-fix24-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw25cpu` | `jpcite-embed-20260516T143552Z-amlaw25cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-0004.jsonl` (16.8 MB) | `embeddings_burn/amlaw-fix25-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `adoption26cpu` | `jpcite-embed-20260516T143552Z-adoption26cpu` | ml.c5.2xlarge | `corpus_export_trunc/adoption_records/part-0000.jsonl` (21.0 MB / 116,335 rows) | `embeddings_burn/adoption-fix26-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw27gpu` | `jpcite-embed-20260516T143552Z-amlaw27gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0005.jsonl` (16.3 MB / 26,480 rows) | `embeddings_burn/amlaw-fix27-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw28gpu` | `jpcite-embed-20260516T143552Z-amlaw28gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_law_article/part-0006.jsonl` (16.7 MB / 28,764 rows) | `embeddings_burn/amlaw-fix28-gpu/` | `jpcite-embed-allminilm-v1` |

All 5 Created and confirmed `InProgress` at 2026-05-16T14:35:52Z UTC
(23:35:52 JST). Verified via:

```
aws sagemaker list-transform-jobs --region ap-northeast-1 \
    --query 'TransformJobSummaries[?contains(TransformJobName,`20260516T143552Z`)].[TransformJobName,TransformJobStatus]' \
    --profile bookyou-recovery
```

Returns 5 / 5 rows in state `InProgress`.

## Quota compliance

Both quotas were fully free at submit time (PM6 had fully drained):

| Resource | Quota | In-flight at submit | New (this run) | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 0 | 3 | **3** | 5 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | **2** | 2 free |

PM7 stays within both quotas (3/8 CPU + 2/4 GPU). 5 CPU slots and
2 GPU slots remain for any PM8 follow-up.

## 5-line hard-stop compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY` returned
`actual_usd = $1.931e-07` for May 2026 (Cost Explorer 8-12h lag
dominant). `$0.00` ≪ `$13K` threshold → submit proceeds. AWS Budget
Action at `$18,900` remains the ultimate hard-stop.

`scripts/aws_credit_ops/sagemaker_pm7_submit.py` `preflight_cost_check()`
calls `sys.exit(2)` if `actual_usd >= 13000` before any
`create_transform_job` invocation.

## Throughput projections

PM5 + PM6 observed throughput baselines (rows / sec):

| Instance | corpus | observed | basis |
| --- | --- | --- | --- |
| c5.2xlarge CPU | programs / invoice | ~25-26 rows/sec | PM5 programs17 / invoice18 |
| c5.2xlarge CPU | nta_saiketsu | ~1.2 rows/sec | PM5 saiketsu19 (tiny, IO-bound) |
| g4dn.xlarge GPU | tsutatsu / court | ~2.8-6.5 rows/sec | PM5 court21gpu / tsutatsu20gpu |

PM7 expected walltime per job:

| Tag | Instance | Rows | Est. rows/sec | Est. walltime |
| --- | --- | --- | --- | --- |
| `amlaw24cpu` | c5.2xlarge | ~26K | ~25 | ~17 min |
| `amlaw25cpu` | c5.2xlarge | ~26K | ~25 | ~17 min |
| `adoption26cpu` | c5.2xlarge | 116,335 | ~25 | **~75-80 min** (largest job) |
| `amlaw27gpu` | g4dn.xlarge | 26,480 | ~5 | ~85-90 min |
| `amlaw28gpu` | g4dn.xlarge | 28,764 | ~5 | ~90-100 min |

The 2 GPU jobs (amlaw27gpu / amlaw28gpu) are expected to be the
walltime-dominant runs. CPU side wraps in ~17 min for the 2 amlaw parts
and ~80 min for the adoption_records walk.

## Cost estimate (PM7 run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| `amlaw24cpu` | c5.2xlarge | $0.408 | ~17 min | $0.12 |
| `amlaw25cpu` | c5.2xlarge | $0.408 | ~17 min | $0.12 |
| `adoption26cpu` | c5.2xlarge | $0.408 | ~80 min | $0.54 |
| `amlaw27gpu` | g4dn.xlarge | $0.94 | ~90 min | $1.41 |
| `amlaw28gpu` | g4dn.xlarge | $0.94 | ~100 min | $1.57 |
| **Total** | | | | **~$3.76** |

PM5+PM6+PM7 combined cost trivially within $13K hard-stop / $18.9K
canary cap.

## Cumulative coverage snapshot (PM5 + PM6 + PM7)

| Corpus part | Status | Rows |
| --- | --- | --- |
| programs part-0000 (PM5 programs17) | Completed | 12,753 |
| invoice_registrants part-0000 (PM5 invoice18) | Completed | 13,801 |
| nta_saiketsu part-0000 (PM5 saiketsu19) | Completed | 137 |
| nta_tsutatsu_index part-0000 (PM5 tsutatsu20gpu) | Completed | 3,232 |
| court_decisions part-0000 (PM5 court21gpu) | Completed | 848 |
| am_law_article part-0001 (PM6 amlaw22gpu) | Completed | ~26K |
| am_law_article part-0002 (PM6 amlaw23gpu) | Completed | ~26K |
| am_law_article part-0003 (PM7 amlaw24cpu) | **InProgress** | ~26K |
| am_law_article part-0004 (PM7 amlaw25cpu) | **InProgress** | ~26K |
| adoption_records part-0000 (PM7 adoption26cpu) | **InProgress** | 116,335 |
| am_law_article part-0005 (PM7 amlaw27gpu) | **InProgress** | 26,480 |
| am_law_article part-0006 (PM7 amlaw28gpu) | **InProgress** | 28,764 |
| **PM5+PM6+PM7 cumulative** | 7 done + 5 in-flight | **~330K+** |

## Followups (deferred — not part of this run)

1. Watch the 5 PM7 jobs to Completed; verify `embeddings_burn/*/part-NNNN.jsonl.out`
   are non-empty (≥1.5 GB output per ~16 MB input based on PM6 ratio).
2. PM8 candidates: am_law_article parts 0007..0013 (raw exists but not
   yet truncated; would require another `/tmp/pm7_truncate.py`-style
   run); adoption_records part-0001 (~9 MB raw, would yield ~50K rows
   truncated).
3. Build per-corpus FAISS shards from the expanded `embeddings_burn/*.jsonl.out`
   set once PM7 completes — FAISS expand task #189 is already complete
   for the PM5/PM6 substrate; PM7 output adds the next layer.
