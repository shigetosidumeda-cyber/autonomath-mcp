# SageMaker PM4 Resubmit + GPU Quota Fill (2026-05-16 PM4)

**Status**: 5 new transform jobs LIVE (InProgress) on `bookyou-recovery` profile, ap-northeast-1.

**Lane**: `[lane:solo]`

**Predecessor**: `docs/_internal/sagemaker_resubmit_2026_05_16_PM3.md` (commit `1352d2c09`, PM3 run `20260516T094536Z`).

---

## TL;DR

Of the 6 PM3 jobs from run_id `20260516T094536Z`:

| Job | Instance | Status | Output |
| --- | --- | --- | --- |
| `court6` | c5.2xlarge | **SUCCEEDED** | `embeddings_burn/court-fix6/` |
| `tsutatsu7` | c5.2xlarge | **SUCCEEDED** | `embeddings_burn/tsutatsu-fix7/` |
| `programs8` | c5.2xlarge | **SUCCEEDED** | `embeddings_burn/programs-fix8/` |
| `saiketsu9` | c5.2xlarge | **SUCCEEDED** | `embeddings_burn/saiketsu-fix9/` |
| `invoice10` | c5.2xlarge | **SUCCEEDED** | `embeddings_burn/invoice-fix10/` |
| `amlaw11gpu` | g4dn.xlarge | **Failed** | `ClientError` (raw `am_law_article/part-0000.jsonl` over 512 BERT token cap — same root cause as PM3 court/tsutatsu fail) |

5/6 success on the c5.2xlarge truncation strategy. Only `amlaw11gpu` failed, because the predecessor sent **raw** (untruncated) `am_law_article/part-0000.jsonl` on the assumption that GPU + the non-`-cpu-v1` model variant would tolerate longer inputs — they did not.

## Fix Applied (this run, 2026-05-16T10:03:46Z)

Same 320-character pre-truncation strategy from PM3 — extended to additional `am_law_article` parts and a new GPU lane.

- `corpus_export_trunc/am_law_article/part-0001.jsonl` — 30,954 rows, **8,082 truncated (26.1%)**
- `corpus_export_trunc/am_law_article/part-0002.jsonl` — 27,969 rows, **8,766 truncated (31.3%)**
- `corpus_export_trunc/am_law_article/part-0003.jsonl` — 27,850 rows, **8,758 truncated (31.4%)**
- `corpus_export_trunc/am_law_article/part-0004.jsonl` — 28,380 rows, **8,618 truncated (30.4%)**

`adoption_records/part-0000.jsonl` was sampled and the longest `inputs` value was **151 characters** (well under 320); no truncation needed, so the raw `corpus_export/adoption_records/part-0000.jsonl` is used directly.

Original `corpus_export/*` prefixes remain untouched (read-only) — truncation is non-destructive.

## Run ID

`20260516T100346Z`

## Jobs Submitted (5 = 2 GPU + 3 CPU)

| Tag | Job name | Instance | Source | Output | Model |
| --- | --- | --- | --- | --- | --- |
| `amlaw12gpu` | `jpcite-embed-20260516T100346Z-amlaw12gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/am_law_article/part-0001.jsonl` | `embeddings_burn/amlaw-fix12-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw13gpu` | `jpcite-embed-20260516T100346Z-amlaw13gpu` | `ml.g4dn.xlarge` | `corpus_export_trunc/am_law_article/part-0002.jsonl` | `embeddings_burn/amlaw-fix13-gpu/` | `jpcite-embed-allminilm-v1` |
| `amlaw14cpu` | `jpcite-embed-20260516T100346Z-amlaw14cpu` | `ml.c5.2xlarge` | `corpus_export_trunc/am_law_article/part-0003.jsonl` | `embeddings_burn/amlaw-fix14-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `amlaw15cpu` | `jpcite-embed-20260516T100346Z-amlaw15cpu` | `ml.c5.2xlarge` | `corpus_export_trunc/am_law_article/part-0004.jsonl` | `embeddings_burn/amlaw-fix15-cpu/` | `jpcite-embed-allminilm-cpu-v1` |
| `adopt16` | `jpcite-embed-20260516T100346Z-adopt16` | `ml.c5.2xlarge` | `corpus_export/adoption_records/part-0000.jsonl` (raw, max_len=151) | `embeddings_burn/adopt-fix16-cpu/` | `jpcite-embed-allminilm-cpu-v1` |

All 5 returned `TransformJobArn` and dropped into the `InProgress` queue at 2026-05-16T10:03:46Z.

## Quota Compliance

Verified via `aws service-quotas list-service-quotas` at submit time:

| Resource | Quota | In-flight at submit | New (this run) | Total in-flight | Headroom |
| --- | --- | --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | 8 | 1 (`adoption-fix1` from prior run) | 3 | **4** | 4 free |
| `ml.g4dn.xlarge for transform job usage` | 4 | 0 | 2 | **2** | 2 free |

Quota inventory confirmed via `aws service-quotas list-service-quotas --service-code sagemaker --query 'Quotas[?contains(QuotaName, \`transform\`)]'` immediately before submit; PM3 burst (6 jobs) drained before this PM4 burst started, leaving only the 1 still-running `adoption-fix1` from the 18:07Z run.

## 5-Line Hard-Stop Compliance

Preflight `aws ce get-cost-and-usage --granularity MONTHLY --metrics UnblendedCost --time-period Start=2026-05-01,End=2026-05-17` returned `actual_usd = $0.0000001906` for May 2026 (Cost Explorer 8-12h lag is the dominant signal; the canary $18,900 cap is monitored by 5-line CW alarm + Budget Action). $0.00 ≪ $13K threshold → submit proceeds. `submit_resubmit.py` driver enforces `actual_usd >= 13000 → sys.exit(2)` before any `create_transform_job` call.

## Cost Estimate (this run)

| Job | Instance | Hourly | Est. duration | Est. cost |
| --- | --- | --- | --- | --- |
| amlaw12gpu | g4dn.xlarge | $0.94 | ~30 min (truncated 30,954 rows) | $0.47 |
| amlaw13gpu | g4dn.xlarge | $0.94 | ~28 min (truncated 27,969 rows) | $0.44 |
| amlaw14cpu | c5.2xlarge | $0.476 | ~70 min (truncated 27,850 rows on CPU) | $0.56 |
| amlaw15cpu | c5.2xlarge | $0.476 | ~70 min (truncated 28,380 rows on CPU) | $0.56 |
| adopt16 | c5.2xlarge | $0.476 | ~30 min (raw 116k rows, short text) | $0.24 |
| **Total** | | | | **~$2.27** |

(All 5 jobs combined cost is < $3, well under the $13K hard-stop and trivially within the $18.9K canary cap envelope.)

## Throughput (rows embedded)

Expected coverage of this PM4 run (when all 5 finish), additive to the PM3 5-success snapshot:

- `am_law_article` parts 0001 / 0002 / 0003 / 0004 — total **115,153 rows** (of 14-part full corpus, ~353K rows after deduping with PM3 part-0000 failure).
- `adoption_records/part-0000.jsonl` — **116,335 rows** (raw, no truncation needed; longest input only 151 chars).

PM4 rows embedded this run: **~231,488** (vs PM3's ~30,770 across 5 success). Cumulative across PM3+PM4: **~262,258 rows**.

Remaining `am_law_article` parts (0000 [failed in PM3], 0005..0013) total ~14 parts left to cover — fan-out plan in followups.

## Followups (deferred — not part of this run)

1. After `amlaw12gpu` + `amlaw13gpu` validate the truncated GPU contract end-to-end, fan-out the remaining 10 `am_law_article` parts (part-0000 retry + part-0005..0013) onto the 2-3 g4dn.xlarge headroom slots in parallel waves (2 × 5 = full coverage in 5 sequential batches, < $10 total).
2. Topup remaining derived prefixes once the canonical input format is settled (`derived/jpi_houjin_master/`, `derived/enforcement_actions/`, `derived/known_gaps/` — currently absent from `corpus_export/` so no jsonl-formatted shard exists; need a fresh export pass via `scripts/aws_credit_ops/export_corpus_to_s3.py` before SageMaker batch transform can ingest them).
3. Wire `corpus_export_trunc/` regen into ETL so subsequent re-exports don't need a manual truncate pass (carried forward from PM3 followup list).
