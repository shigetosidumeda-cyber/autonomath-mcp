# SageMaker batch transform — open-weight embedding burn ramp

> Status: 2026-05-16 — first smoke landed on J04 e-Gov law cohort.
> Scope: AWS credit burn ramp (§3.4 of Wave 50 credit plan, USD 1,500-3,000 envelope for "search / retrieval index").
> NO LLM, NO API call to any model provider. Pure open-weight encoder (sentence-transformers/all-MiniLM-L6-v2, Apache-2.0).

## What this runbook covers

The driver script `scripts/aws_credit_ops/sagemaker_embed_batch.py` renders a
`CreateTransformJob` spec but does not provision the IAM role or the SageMaker
Model resource — both are operator-managed. This runbook captures the live
resources created on 2026-05-16 so subsequent ramp-up jobs (J02 / J06 / J07
cohorts; multi-instance fan-out) can be submitted without re-deriving them.

## Resources (live, account 993693061769, region ap-northeast-1)

| Resource | ARN / identifier |
| --- | --- |
| Execution role | `arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role` |
| Managed policy | `arn:aws:iam::aws:policy/AmazonSageMakerFullAccess` (attached) |
| Inline S3 policy | `jpcite-credit-s3-rw` (R/W to `*-credit-*-raw` + `*-credit-*-derived`) |
| SageMaker Model | `arn:aws:sagemaker:ap-northeast-1:993693061769:model/jpcite-embed-allminilm-v1` |
| Container image | `763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/huggingface-pytorch-inference:2.1.0-transformers4.37.0-gpu-py310-cu118-ubuntu20.04` |
| HF model | `sentence-transformers/all-MiniLM-L6-v2` (env `HF_MODEL_ID`, task `feature-extraction`) |

Trust + inline policy definitions are versioned under
`infra/aws/iam/jpcite_sagemaker_execution_*.json`.

## Quota reality (ap-northeast-1, account 993693061769)

`ml.g5.4xlarge` transform quota is **0 instances** out of the box. The first
smoke landed on **`ml.g4dn.xlarge`** (T4 GPU, quota 1) instead. Other usable
GPU/CPU transform quotas in this account at 2026-05-16:

- `ml.g4dn.xlarge` × 1 (T4 GPU) — ~$0.736/hr
- `ml.p3.2xlarge` × 1 (V100 GPU) — ~$4.194/hr
- `ml.c5.{x,2,4,9,18}xlarge`, `ml.c4.*`, `ml.m4.*`, `ml.m5.*` — CPU, 1-16 instances each
- `ml.g5.*` — **0 across the board** (raise via Service Quotas if needed)

To scale beyond 1 GPU instance, submit a Service Quotas raise for the relevant
`mlp.g4dn.*` or `mlp.g5.*` "for transform job usage" quotas; G4dn raises
typically grant within 1 business day.

## First smoke (2026-05-16)

- Input: `s3://jpcite-credit-993693061769-202605-derived/J04_embeddings/input/input.jsonl` (5 rows, derived from J04 `object_manifest.jsonl`; one row per source artifact, content = artifact_id + source_id + kind + class + content_type + s3_uri).
- Output: `s3://jpcite-credit-993693061769-202605-derived/J04_embeddings/output/`
- Job ARN: `arn:aws:sagemaker:ap-northeast-1:993693061769:transform-job/jpcite-embed-j04-20260516T043756Z`
- Instance: `ml.g4dn.xlarge` × 1
- Strategy: `MultiRecord`, `SplitType=Line`, `MaxPayloadInMB=6`, `AssembleWith=Line`
- Estimated cost: 5-15 USD (job duration is dominated by ~5 min instance + image pull on GPU; actual embedding work is sub-second on 5 small rows). Re-derive once first job lands.

## Submit a new batch transform

```bash
JOB_NAME="jpcite-embed-<cohort>-$(date -u +%Y%m%dT%H%M%SZ)"
AWS_PROFILE=bookyou-recovery aws sagemaker create-transform-job \
  --transform-job-name "$JOB_NAME" \
  --model-name jpcite-embed-allminilm-v1 \
  --max-concurrent-transforms 1 \
  --max-payload-in-mb 6 \
  --batch-strategy MultiRecord \
  --transform-input '{
    "DataSource": {"S3DataSource": {"S3DataType": "S3Prefix",
      "S3Uri": "s3://jpcite-credit-993693061769-202605-derived/<cohort>/input/"}},
    "ContentType": "application/json", "SplitType": "Line", "CompressionType": "None"
  }' \
  --transform-output '{
    "S3OutputPath": "s3://jpcite-credit-993693061769-202605-derived/<cohort>/output/",
    "Accept": "application/json", "AssembleWith": "Line"
  }' \
  --transform-resources '{"InstanceType": "ml.g4dn.xlarge", "InstanceCount": 1}' \
  --tags Key=project,Value=jpcite Key=purpose,Value=aws-credit-burn Key=lane,Value=solo Key=cohort,Value=<cohort> \
  --region ap-northeast-1
```

Or render the spec via the driver and pipe to `--commit` once the input prefix
+ row estimate are known:

```bash
.venv/bin/python scripts/aws_credit_ops/sagemaker_embed_batch.py \
  --input-prefix s3://jpcite-credit-993693061769-202605-derived/<cohort>/input/ \
  --output-prefix s3://jpcite-credit-993693061769-202605-derived/<cohort>/output/ \
  --sagemaker-model-name jpcite-embed-allminilm-v1 \
  --execution-role-arn arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role \
  --instance-type ml.g4dn.xlarge \
  --estimated-rows 50000 \
  --commit
```

## Monitor

```bash
AWS_PROFILE=bookyou-recovery aws sagemaker describe-transform-job \
  --transform-job-name "$JOB_NAME" --region ap-northeast-1 \
  --query '[TransformJobStatus, TransformStartTime, TransformEndTime, FailureReason]'
```

`TransformJobStatus` transitions: `InProgress` → `Completed` (or `Failed` /
`Stopped`). On completion, output S3 prefix carries one `.out` per input shard
with the embedding vector inline.

## Cost ramp plan

- Smoke (this run): 1 × ml.g4dn.xlarge × ~5 min ≈ $0.07-0.15 cost,
  but billed in 60s minimum + provisioning overhead ⇒ budget ~$5-20.
- J02/J06/J07 ramp (after quota raise): scale to 5-10 ml.g4dn.xlarge or
  ml.g5.4xlarge instances; expected $30-100/hr aggregate, designed to land
  inside the $1,500-3,000 credit envelope across 2-5 days of compute.

## Anti-pattern guards

- **NO LLM API**: the only inference path is the HuggingFace inference DLC
  running the sentence-transformers encoder. Container has no outbound model
  provider keys; the only side-effect is S3 read/write.
- **Open-weight only**: `ALLOWED_MODELS` in the driver pins the three vetted
  sentence-transformer encoders. Unknown HF model IDs are rejected.
- **Budget gate**: driver computes `projected_spend = rows × per_row_usd` and
  refuses to submit when the projection meets `--budget-usd` (default
  `USD 3,000`, the Wave 50 credit-plan §3.4 ceiling).
- **¥0 customer cost**: this pipeline is operator-side ETL; embeddings feed
  internal retrieval indexes and are never re-exposed as a paid endpoint.
