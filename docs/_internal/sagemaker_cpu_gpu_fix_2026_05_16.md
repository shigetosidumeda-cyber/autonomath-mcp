# SageMaker CPU/GPU Image Mismatch — Root Cause + Fix (2026-05-16)

**Status**: 5 resubmit jobs LIVE (InProgress) on `bookyou-recovery` profile, ap-northeast-1.

**Lane**: `[lane:solo]`

---

## TL;DR

21 transform jobs on 2026-05-16 went `Failed` with `ClientError: See job logs for more information`. Root cause turned out **not** to be a CPU/GPU image mismatch — the existing CPU model (`jpcite-embed-allminilm-cpu-v1`) is correctly wired to the `huggingface-pytorch-inference:2.1.0-transformers4.37.0-cpu-py310-ubuntu22.04-v1.1` ECR image, and the GPU model (`jpcite-embed-allminilm-v1`) correctly points at the `cu118-ubuntu20.04` image. The container actually loaded the model, answered most rows with HTTP 200, and the resubmitted jobs use the same CPU model unchanged.

The **actual** root cause was a corpus-export footgun: the input S3 prefix `corpus_export/<table>/` contained both `.jsonl` data files *and* a pretty-printed `_manifest.json`. SageMaker batch transform with `SplitType=Line` reads every file under the prefix and splits each by line. The pretty-printed manifest opens with `{\n  "table": ...`, so the worker received line 1 = `{`, then line 2 = `  "table": ...` which then triggered:

```
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 2 column 1 (char 2)
mms.service.PredictionException: ... : 400
```

Enough `_manifest.json`-induced 400s tripped the job-level failure threshold and SageMaker flipped the whole TransformJob to `Failed`. This explains why most `data-log` lines were perfectly healthy HTTP 200 / ~30 ms latencies, with a handful of 400s mixed in.

## Diagnostic Steps

1. `aws sagemaker list-transform-jobs ... | grep Failed` — confirmed 21 jobs Failed.
2. `aws sagemaker describe-transform-job ... --query FailureReason` — generic `ClientError: See job logs`. ModelName + TransformResources confirmed the CPU job used CPU model + `ml.c5.2xlarge` (no actual mismatch); GPU job used GPU model + `ml.g4dn.xlarge`.
3. `aws sagemaker describe-model jpcite-embed-allminilm-cpu-v1` confirmed image = `763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/huggingface-pytorch-inference:2.1.0-transformers4.37.0-cpu-py310-ubuntu22.04-v1.1` → CPU image, correct.
4. `aws sagemaker describe-model jpcite-embed-allminilm-v1` confirmed image = `huggingface-pytorch-inference:2.1.0-transformers4.37.0-gpu-py310-cu118-ubuntu20.04` → GPU image, correct.
5. `aws logs filter-log-events ... --filter-pattern '?ERROR ?error ?failed ?Exception'` exposed the real signal: `json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 2 column 1 (char 2)`.
6. `aws s3 ls s3://jpcite-credit-993693061769-202605-derived/corpus_export/<table>/` revealed `_manifest.json` (pretty-printed, multi-line) sitting next to `part-0000.jsonl` (compact, one record per line).
7. `aws s3 cp ... part-0000.jsonl - | head -3` validated the `.jsonl` records were structurally clean (`{"id": "...", "inputs": "..."}` per line).

## Fix Applied (resubmit, 2026-05-16T09:07:39Z)

For each of 5 tables, point `S3Uri` at the **specific `.jsonl` file** rather than the directory prefix. SageMaker still treats this as `S3Prefix` semantics (it will pick up just that single object) and the manifest is excluded.

| Job name | Instance | Source S3 URI | Output prefix |
| --- | --- | --- | --- |
| `jpcite-embed-20260516T090739Z-adoption-fix1` | `ml.c5.2xlarge` | `s3://jpcite-credit-993693061769-202605-derived/corpus_export/adoption_records/part-0000.jsonl` | `s3://.../embeddings_burn/adoption-fix1/` |
| `jpcite-embed-20260516T090739Z-court-fix2` | `ml.c5.2xlarge` | `s3://.../corpus_export/court_decisions/part-0000.jsonl` | `s3://.../embeddings_burn/court-fix2/` |
| `jpcite-embed-20260516T090739Z-invoice-fix3` | `ml.c5.2xlarge` | `s3://.../corpus_export/invoice_registrants/part-0000.jsonl` | `s3://.../embeddings_burn/invoice-fix3/` |
| `jpcite-embed-20260516T090739Z-saiketsu-fix4` | `ml.c5.2xlarge` | `s3://.../corpus_export/nta_saiketsu/part-0000.jsonl` | `s3://.../embeddings_burn/saiketsu-fix4/` |
| `jpcite-embed-20260516T090739Z-tsutatsu-fix5` | `ml.c5.2xlarge` | `s3://.../corpus_export/nta_tsutatsu_index/part-0000.jsonl` | `s3://.../embeddings_burn/tsutatsu-fix5/` |

Shared params for all 5 jobs:

- Model: `jpcite-embed-allminilm-cpu-v1` (CPU image, unchanged).
- `InstanceType` = `ml.c5.2xlarge`, `InstanceCount` = 1 → 5 / 8 quota slots used; 3 free.
- `ContentType` = `application/json`, `SplitType` = `Line`, `BatchStrategy` = `SingleRecord`, `MaxPayloadInMB` = 6, `MaxConcurrentTransforms` = 1.
- `Accept` = `application/json`, `AssembleWith` = `Line`.
- Tags: `Project=jpcite`, `Lane=solo`, `Wave=sagemaker-cpu-gpu-fix`.

All 5 returned a valid `TransformJobArn` and entered `InProgress` (confirmed via `list-transform-jobs --status-equals InProgress`).

## Quota Check

- `ml.c5.2xlarge for transform job usage` quota = **8.0** (ap-northeast-1).
- `ml.g4dn.xlarge for transform job usage` quota = **4.0** (per `aws service-quotas`).
- After resubmit: 5 of 8 c5.2xlarge slots in use, 0 of 4 g4dn.xlarge slots in use. We stay safely below the global 20-instance cap as well.

## 5-Line Hard-Stop Honored

This work touched only SageMaker batch transform with the existing CPU model. The 5-line hard-stop bundle (Budget Action $18.9K deny IAM + Lambda `JPCITE_AUTO_STOP_ENABLED=true` + SNS subscription + CW alarm + EventBridge auto-resubmit cron) was **not modified**. Embeddings burn continues under the existing budget envelope.

## Forward Mitigation

Future submissions should either:
- (Preferred) generate `_manifest.json` in a sibling prefix such as `corpus_export_manifest/<table>/_manifest.json`, so the `corpus_export/<table>/` data prefix only contains `.jsonl` files; or
- Submit using `S3DataType=ManifestFile` with an explicit manifest of just the `.jsonl` URIs, never the directory prefix.

Both eliminate the chance of pulling a structured manifest file into a Line-split feature-extraction pipeline.

## Live Submission Confirmation

All 5 jobs verified InProgress at `2026-05-16T09:08Z`:

```
jpcite-embed-20260516T090739Z-adoption-fix1     InProgress
jpcite-embed-20260516T090739Z-court-fix2        InProgress
jpcite-embed-20260516T090739Z-invoice-fix3      InProgress
jpcite-embed-20260516T090739Z-saiketsu-fix4     InProgress
jpcite-embed-20260516T090739Z-tsutatsu-fix5     InProgress
```

## References

- Failed jobs: `jpcite-embed-20260516T060901Z-applicationroundcpu` (representative), plus 20 others on the same submission burst.
- Successful CPU model: `jpcite-embed-allminilm-cpu-v1` (image `cpu-py310-ubuntu22.04-v1.1`).
- Profile: `bookyou-recovery` (UserId `AIDA6OXFY2KEYSUNJDC63`, Admin).
- Region: `ap-northeast-1`.
- Submitter script reference: `scripts/aws_credit_ops/submit_quota_saturate_burn.py` (the resubmit was a one-shot `aws sagemaker create-transform-job` per job because we wanted explicit `.jsonl`-URI control; the canonical script's `submit_one` builds its input URI from `corpus_export/<table>/` which is exactly the foot-gun — fix that script in a follow-up).
