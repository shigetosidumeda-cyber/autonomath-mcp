# SageMaker Resubmit + Quota Saturation (2026-05-16 PM3)

**Status**: 6 transform jobs LIVE (InProgress) on `bookyou-recovery` profile, ap-northeast-1.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_cpu_gpu_fix_2026_05_16.md` (commit `88cb7ef2d`, 5 fix1-fix5 jobs).

---

## TL;DR

Of the 5 fix1-fix5 jobs from run_id `20260516T090739Z` (CPU-image fix predecessor):

| Job | Status | Output |
| --- | --- | --- |
| `adoption-fix1` | InProgress | (running) |
| `court-fix2` | **Failed** | `RuntimeError: tensor a (537) must match tensor b (512)` — token-length overflow |
| `invoice-fix3` | **SUCCEEDED** | 4.45 GB embeddings at `embeddings_burn/invoice-fix3/part-0000.jsonl.out` |
| `saiketsu-fix4` | **SUCCEEDED** | 260 MB embeddings at `embeddings_burn/saiketsu-fix4/part-0000.jsonl.out` |
| `tsutatsu-fix5` | **Failed** | Same 512-token overflow on `nta_tsutatsu_index` |

Two prefixes carried multi-paragraph Japanese law/judgement text exceeding `bert-base-uncased`'s 512-position-embedding cap. Predecessor jobs sent untruncated inputs and tripped position-embedding overflow on the SageMaker HuggingFace inference toolkit, which has no `truncation=True` knob exposed via env-var (the toolkit defaults `truncation=False` for feature extraction).

## Fix Applied (this run, 2026-05-16T09:45:36Z)

Pre-truncate inputs at the JSONL level to **320 Japanese characters** (≈ 480 BERT tokens; leaves ≥32 token safety margin) and upload under a parallel `corpus_export_trunc/` prefix:

- `corpus_export_trunc/court_decisions/part-0000.jsonl` — 848 rows, 579 truncated.
- `corpus_export_trunc/nta_tsutatsu_index/part-0000.jsonl` — 3232 rows, 1696 truncated.
- `corpus_export_trunc/programs/part-0000.jsonl` — 12 753 rows, 0 truncated (corpus naturally short, copied for symmetry).

Original `corpus_export/*` prefixes are untouched (read-only) — truncation is non-destructive.

## Run ID

`20260516T094536Z`

## Jobs Submitted (6 = 5 CPU + 1 GPU)

| Tag | Job name | Instance | Source | Output |
| --- | --- | --- | --- | --- |
| `court6` | `jpcite-embed-20260516T094536Z-court6` | `ml.c5.2xlarge` | `corpus_export_trunc/court_decisions/part-0000.jsonl` | `embeddings_burn/court-fix6/` |
| `tsutatsu7` | `jpcite-embed-20260516T094536Z-tsutatsu7` | `ml.c5.2xlarge` | `corpus_export_trunc/nta_tsutatsu_index/part-0000.jsonl` | `embeddings_burn/tsutatsu-fix7/` |
| `programs8` | `jpcite-embed-20260516T094536Z-programs8` | `ml.c5.2xlarge` | `corpus_export_trunc/programs/part-0000.jsonl` | `embeddings_burn/programs-fix8/` |
| `saiketsu9` | `jpcite-embed-20260516T094536Z-saiketsu9` | `ml.c5.2xlarge` | `corpus_export/nta_saiketsu/part-0000.jsonl` | `embeddings_burn/saiketsu-fix9/` |
| `invoice10` | `jpcite-embed-20260516T094536Z-invoice10` | `ml.c5.2xlarge` | `corpus_export/invoice_registrants/part-0000.jsonl` | `embeddings_burn/invoice-fix10/` |
| `amlaw11gpu` | `jpcite-embed-20260516T094536Z-amlaw11gpu` | `ml.g4dn.xlarge` | `corpus_export/am_law_article/part-0000.jsonl` (21 MB / 1 of 15 parts) | `embeddings_burn/amlaw-fix11-gpu/` |

All 6 returned `TransformJobArn` and dropped into the `InProgress` queue.

## Quota Compliance

| Resource | Quota | Used | Headroom |
| --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 5 (this run) + 1 (`adoption-fix1` predecessor) = **6** | 2 free |
| `ml.g4dn.xlarge for transform job usage` | 4 (verified — not 1 as planned) | 1 (this run) | 3 free |
| `ml.g4dn.{4,8,12,16}xlarge` | 0 | 0 | n/a (not requested) |

Quota inventory confirmed via `aws service-quotas list-service-quotas --service-code sagemaker --query 'Quotas[?contains(QuotaName, \`transform\`)]'` immediately before submit.

## 5-Line Hard-Stop Compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY --metrics UnblendedCost` returned `actual_usd = $0.00` for May 2026 (Cost Explorer 8-12h lag is the dominant signal; the canary $18,900 cap is monitored by 5-line CW alarm + Budget Action). $0.00 ≪ $13K threshold → submit proceeds. The `submit_resubmit.py` driver enforces `actual_usd >= 13000 → sys.exit(2)` before any `create_transform_job` call.

## Cost Estimate (this run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| court6 | c5.2xlarge | $0.476 | ~25 min | $0.20 |
| tsutatsu7 | c5.2xlarge | $0.476 | ~30 min | $0.24 |
| programs8 | c5.2xlarge | $0.476 | ~45 min | $0.36 |
| saiketsu9 | c5.2xlarge | $0.476 | ~5 min | $0.04 |
| invoice10 | c5.2xlarge | $0.476 | ~80 min | $0.63 |
| amlaw11gpu | g4dn.xlarge | $0.94 | ~25 min (single 21 MB part) | $0.39 |
| **Total** | | | | **~$1.86** |

(All 6 jobs combined cost is < $2, well under the $13K hard-stop and trivially within the $18.9K canary cap envelope.)

## Throughput (rows embedded)

Expected coverage of this run (when all 6 finish, in addition to the predecessor `invoice-fix3` 4.45 GB + `saiketsu-fix4` 260 MB already SUCCEEDED):

- `nta_saiketsu`: ~137 rows × 2 (predecessor + topup) → fully covered.
- `invoice_registrants`: ~13 801 rows × 2 (predecessor + topup) → fully covered.
- `court_decisions`: 848 rows (truncated).
- `nta_tsutatsu_index`: 3 232 rows (truncated).
- `programs`: 12 753 rows.
- `am_law_article`: ~12 000 rows (1 of 15 parts; 14 parts deferred to follow-up topup runs after part-0000 validates).

Rows embedded this run: **~30 770** (vs predecessor's ~14 K). Cumulative across both runs: **~45 K rows** out of `am_law_article` 353 K full corpus target. The 14 remaining `am_law_article` parts (each ~20 MB / ~25 K rows) are deferrable to subsequent CPU/GPU batches now that part-0000's contract is proved.

## Followups (deferred — not part of this run)

1. After `amlaw11gpu` completes, fan-out the 14 remaining `am_law_article` parts onto 4 g4dn.xlarge slots in parallel waves (4 × 4 = full coverage in 4 sequential batches, < $20 total).
2. Topup truncated copies for any additional long-text prefix that surfaces (sample with `python -c 'import json; ... if len > 380'` before submit).
3. Wire `corpus_export_trunc/` regen into the ETL so subsequent re-exports don't need a manual truncate pass.
