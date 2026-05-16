# jpcite-crawler

Generic Python crawler container image for the AWS Batch credit run
(`docs/_internal/aws_credit_data_acquisition_jobs_agent.md`,
`docs/_internal/aws_credit_batch_compute_agent.md`,
`docs/_internal/aws_credit_review_08_artifact_manifest_schema.md`).

* Image: `jpcite-crawler:0.1.0`
* ECR: `993693061769.dkr.ecr.ap-northeast-1.amazonaws.com/jpcite-crawler:0.1.0`
* Operator: Bookyou株式会社 (T8010001213708)
* Project / CreditRun tags: `Project=jpcite`, `CreditRun=2026-05`

## What it does

AWS Batch jobs J01-J07 (and follow-on jobs in the same plan) launch
this container with a single env var:

    JOB_MANIFEST_S3_URI=s3://<bucket>/<key>.json

The container:

1. Downloads the manifest JSON via boto3.
2. Loops `target_urls[]` from the manifest, fetching each with
   `httpx` (HTTP/2 + gzip), respecting `robots.txt` and the per-source
   `license_boundary` policy (`no_collect` skips, `link_only` records
   URL+hash only, `derived_fact` / `full_fact` persists raw body).
3. Applies per-host rate limiting (default 1 req/sec) + retry with
   exponential backoff on 5xx and 429.
4. Honors caller-supplied `ETag` / `Last-Modified` (conditional GET
   short-circuits to a `not_modified` known-gap row).
5. Emits the canonical jpcite contract artifacts under `/work/out/`:

   ```
   run_manifest.json
   object_manifest.jsonl   (and .parquet when pyarrow is available)
   source_receipts.jsonl
   source_profile_delta.jsonl
   known_gaps.jsonl
   quarantine.jsonl
   raw/<sha256>.bin        (only when license_boundary allows)
   ```

6. Uploads the entire `/work/out/` tree to
   `s3://<output_bucket>/<output_prefix>/` from the manifest.

## Manifest schema (input)

```json
{
  "run_id": "credit-20260515-001",
  "job_id": "J04",
  "source_id": "egov_law",
  "publisher": "デジタル庁",
  "license_boundary": "derived_fact",
  "respect_robots": true,
  "user_agent": "jpcite-crawler/0.1.0 (+ops@bookyou.net)",
  "request_delay_seconds": 1.0,
  "max_retries": 3,
  "timeout_seconds": 30.0,
  "output_bucket": "jpcite-credit-993693061769-202605-raw",
  "output_prefix": "runs/credit-20260515-001/J04",
  "target_urls": [
    "https://elaws.e-gov.go.jp/api/1/articles?id=...",
    {
      "url": "https://example.go.jp/foo.pdf",
      "target_id": "t000123",
      "parser": "pdf",
      "license_boundary": "derived_fact",
      "etag": "\"abc123\""
    }
  ]
}
```

## Constraints

* NO LLM API calls anywhere in the image.
* NO outbound traffic beyond manifest `target_urls[]` and AWS regional
  endpoints used by boto3 (S3, STS).
* `robots.txt` is fetched + cached per host per run; unreachable
  robots = `manual_review` (the source profile in the manifest is the
  authority for fallback decisions).
* `no_hit` is always emitted as a known_gap row with
  `gap_id=no_hit_not_absence`; never converted to absence/safety.
* All artifacts use canonical JSON (sorted keys, no whitespace) so
  `sha256(file_bytes)` is stable across reruns.

## Build / push (operator runs these)

When Docker Desktop is running:

```bash
cd /Users/shigetoumeda/jpcite

# 1. Build
docker build --platform linux/amd64 \
  -t jpcite-crawler:0.1.0 \
  docker/jpcite-crawler/

# 2. Tag for ECR
docker tag jpcite-crawler:0.1.0 \
  993693061769.dkr.ecr.ap-northeast-1.amazonaws.com/jpcite-crawler:0.1.0

# 3. Login to ECR
AWS_PROFILE=bookyou-recovery aws ecr get-login-password \
  --region ap-northeast-1 \
  | docker login \
      --username AWS \
      --password-stdin \
      993693061769.dkr.ecr.ap-northeast-1.amazonaws.com

# 4. Push
docker push \
  993693061769.dkr.ecr.ap-northeast-1.amazonaws.com/jpcite-crawler:0.1.0

# 5. Verify
AWS_PROFILE=bookyou-recovery aws ecr describe-images \
  --region ap-northeast-1 \
  --repository-name jpcite-crawler
```

The image is `linux/amd64` only — AWS Batch Fargate Spot and EC2
Spot run x86_64 by default in `ap-northeast-1`, so passing
`--platform linux/amd64` from an Apple Silicon dev box prevents an
arm64 wheel mismatch.

## Local smoke test

```bash
# build
docker build --platform linux/amd64 -t jpcite-crawler:0.1.0 docker/jpcite-crawler/

# write a tiny manifest somewhere
cat > /tmp/sample-manifest.json <<'JSON'
{
  "run_id": "smoke-001",
  "job_id": "J01",
  "source_id": "example",
  "license_boundary": "derived_fact",
  "output_bucket": "jpcite-credit-993693061769-202605-raw",
  "output_prefix": "smoke/runs/smoke-001/J01",
  "target_urls": ["https://example.com/"]
}
JSON

# upload manifest
AWS_PROFILE=bookyou-recovery aws s3 cp /tmp/sample-manifest.json \
  s3://jpcite-credit-993693061769-202605-raw/smoke/manifest.json

# run container locally with AWS creds passed through
docker run --rm \
  -e JOB_MANIFEST_S3_URI=s3://jpcite-credit-993693061769-202605-raw/smoke/manifest.json \
  -e AWS_REGION=ap-northeast-1 \
  -v ~/.aws:/root/.aws:ro \
  -e AWS_PROFILE=bookyou-recovery \
  jpcite-crawler:0.1.0
```

## Job manifest examples for J01-J07

Use this image for every job that fetches public URLs and writes
JPCIR-shaped artifacts. Per-job differences live entirely in the
manifest JSON (no per-job container variants):

| Job | source_id | license_boundary | Notes |
|---|---|---|---|
| J01 | `<source_under_review>` | `metadata_only` | One manifest per candidate source; emit `source_profile_delta` |
| J02 | `nta_houjin` | `derived_fact` | Bulk 法人番号 mirror; respect公共データ利用規約 |
| J03 | `nta_invoice` | `derived_fact` | T-number lookup + no-hit rows go to `known_gaps` |
| J04 | `egov_law` | `derived_fact` | e-Gov API + 条文 snapshot |
| J05 | `jgrants_programs` | `derived_fact` | J-Grants + 自治体制度 |
| J06 | `<ministry_pdf_source>` | `derived_fact` | PDFはbinary persistedで `raw/<sha>.bin` |
| J07 | `gbizinfo` | `derived_fact` | 法人番号 join axis |
