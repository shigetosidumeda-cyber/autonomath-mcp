# AWS Burn Lane G — Lambda Mass Invocation (2026-05-17)

> Internal runbook for the Lane G burn lane: drive Lambda spend toward
> the ~$300-400/day band by invoking the lightweight canary-attestation
> Lambda at sustained ~11K req/sec, producing a CloudWatch Logs +
> sampled-S3 audit trail as the moat artifact (not throwaway).
>
> live_aws_commands_allowed: TRUE (user explicit unlock 2026-05-17)
> never-reach hard cap: $19,490 cumulative spend

## TL;DR

| field | value |
| --- | --- |
| Function | `jpcite-credit-canary-attestation-lite` (128 MB, 10s timeout) |
| Region | ap-northeast-1 |
| Reserved concurrency | 800 (account limit 1000, leaves 100 unreserved) |
| Driver | `scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py` |
| Target rate | 11,500 req/sec |
| Target/day | 1,000,000,000 invocations (1B) |
| Projected $/day | ~$408 (1B × $0.0000004083 per invoke) |
| Moat artifact | CloudWatch Logs `/aws/lambda/jpcite-credit-canary-attestation-lite` + ~0.1% S3 sample in `s3://jpcite-credit-993693061769-202605-reports/canary-attestation-lite/...` |

## Cost model

```
unit:               128 MB × 100 ms = 0.0125 GB-sec
request cost:       $0.20 / 1M
compute cost/inv:   0.0125 × $0.0000166667 = $2.083e-7
total cost/inv:     $2.00e-7 + $2.083e-7 = $4.083e-7
1M invocations:     $0.41
1B invocations/day: ~$408
```

This sits in the $300-$500/day band the lane targets, comfortably under
the $19,490 cumulative hard cap.

## Components

### 1. Lambda function (lite)

`infra/aws/lambda/jpcite_credit_canary_attestation_lite.py` — purpose-
built lightweight handler:

- Memory 128 MB, timeout 10s (no Batch/CE/S3 polls in the hot path).
- Emits one structured JSON log line per invocation (CloudWatch Logs
  is the canonical audit trail).
- ~0.1% sample rate writes a compact JSON to the attestation S3 bucket
  (rolling moat artifact, queryable via Athena / S3 Select).
- Deploy: `scripts/aws_credit_ops/deploy_canary_attestation_lite_lambda.sh`

### 2. Reserved concurrency

`aws lambda put-function-concurrency
--function-name jpcite-credit-canary-attestation-lite
--reserved-concurrent-executions 800`

Reserved 800 (account default cap is 1000, must leave 100 unreserved).
This ceiling combined with the leaky-bucket RPS limit gives a stable
~11K-12K req/sec sustained without throttling.

### 3. Driver

`scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py` — async
``InvocationType=Event`` boto3 multi-threaded pump.

- DRY_RUN by default; ``--commit --unlock-live-aws-commands`` required.
- ``--budget-usd`` (default 500) caps projected spend.
- ``--rps-cap`` leaky-bucket limiter keeps the actual TPS predictable.
- ``--profile`` arg / `$AWS_PROFILE` env for credential selection
  (default boto3 chain often resolves to a different account).

## How to run

```bash
# Dry-run projection only (no side effects):
AWS_PROFILE=bookyou-recovery .venv/bin/python \
  scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \
  --requests 1000000 --concurrency 256

# Live 1M smoke:
AWS_PROFILE=bookyou-recovery .venv/bin/python \
  scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \
  --requests 1000000 --concurrency 256 --rps-cap 11500 \
  --commit --unlock-live-aws-commands

# Live 1B/day sustained (long-running):
AWS_PROFILE=bookyou-recovery .venv/bin/python \
  scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \
  --requests 1000000000 --concurrency 512 --rps-cap 11500 \
  --commit --unlock-live-aws-commands \
  --envelope-out reports/lane_g_1B_2026_05_17.json
```

## Verification

```bash
# Per-hour invocation count:
aws cloudwatch get-metric-statistics --namespace AWS/Lambda \
  --metric-name Invocations --statistics Sum \
  --start-time 2026-05-17T00:00:00Z --end-time 2026-05-18T00:00:00Z \
  --period 3600 \
  --dimensions Name=FunctionName,Value=jpcite-credit-canary-attestation-lite \
  --profile bookyou-recovery --region ap-northeast-1

# Daily spend via Cost Explorer:
aws ce get-cost-and-usage --time-period Start=2026-05-17,End=2026-05-18 \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AWS Lambda"]}}' \
  --profile bookyou-recovery --region us-east-1
```

## Safety / kill switch

- The driver requires both ``--commit`` AND ``--unlock-live-aws-commands``
  to issue any AWS-side call. Either flag missing → dry-run, no
  side effects.
- Reserved concurrency 800 caps the maximum parallel executions even
  if the driver mis-specifies rps_cap.
- To **stop** the lane immediately: `aws lambda
  put-function-concurrency --function-name
  jpcite-credit-canary-attestation-lite
  --reserved-concurrent-executions 0` → all future invocations
  throttle to 429.

## Audit moat

- **Primary**: CloudWatch Logs at
  `/aws/lambda/jpcite-credit-canary-attestation-lite`. Each invoke emits
  one ``CANARY_ATTESTATION_LITE {"schema":...}`` JSON line. Default
  retention is unlimited; configure 30-day retention if log volume
  becomes a cost concern (`aws logs put-retention-policy
  --log-group-name /aws/lambda/jpcite-credit-canary-attestation-lite
  --retention-in-days 30`).
- **Sampled**: ~0.1% of invocations write to
  `s3://jpcite-credit-993693061769-202605-reports/canary-attestation-lite/YYYY/MM/DD/HH/lane=G/<uuid>.json`.
  Partitioned for Athena scan efficiency.

## Lane G ledger

| date | run_id | requests sent | driver ok | driver fail | elapsed_s | driver rps | actual Lambda invocations | spend |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-17 | smoke-test-1 | 1 | 1 | 0 | 0.27ms | n/a | 1 | $0.00 |
| 2026-05-17 | lane-g-100k (pre-profile-fix) | 100,000 | 0 | 100,000 | 65.1 | 1,535 | 0 | $0.00 (auth fail) |
| 2026-05-17 | lane-g-100 | 100 | 100 | 0 | 1.07 | 93 | ~100 | $0.00 |
| 2026-05-17 | lane-g-1M | 1,000,000 | 1,000,000 (driver-side 202s) | 0 | 87.7 | 11,403 | ~5,540 over 30+ min | $0.0023 actual |

## Honest findings — async-event queue throttle

**Driver-side numbers (11.4K rps, 1M ok) are HTTP 202 acceptance counts, not
actual Lambda executions.** AWS Lambda's async invoke (`InvocationType=Event`)
returns 202 as soon as the event lands in the internal async queue, then
dispatches at a much slower rate gated by:

1. Per-function async-event-source dispatch rate (observed ~50-100
   concurrent executions even with reserved concurrency 800).
2. Per-account concurrent-execution headroom.

Of 1,000,000 events accepted by the driver in 87.7 s, only ~5,540 actually
executed within the next 30 minutes — a 0.55% effective execution rate.
AsyncEventsDropped metric stayed at 0 (no silent drops), so the remainder
are either still queued or quietly aged-out beyond the metric window.

### Implication for the 1B/day target

The current design pattern (single-host async-invoke pump) does NOT
sustain 11.5K Lambda executions/sec. To meaningfully drive Lambda
spend toward $300/day, switch to one of:

- **Synchronous invocation (`InvocationType=RequestResponse`)** with
  ~1000 concurrent threads on the driver host. Each thread waits ~50-150ms
  per round-trip; 1000 threads × ~7 rps = ~7K rps execution. Two driver
  processes on c5.large get to ~14K rps.
- **Multiple Lambda functions in parallel.** Split target across N
  Lambda function copies, each with its own async queue dispatch budget.
- **SQS + Lambda event source mapping.** Push messages to an SQS queue;
  Lambda's SQS event source consumer is engineered for high throughput
  with batch size controls.

### Updated daily spend estimate (revised down)

With single-host async-invoke pump at observed ~5,540 invocations over 30 min:

```
~185 inv/sec sustained × 86,400 sec/day = ~16M invocations/day
16M × $4.083e-7 = ~$6.50/day  (far below $300 target)
```

To hit $300/day, escalate to synchronous-invoke or SQS pattern (next iteration).

last_updated: 2026-05-17
