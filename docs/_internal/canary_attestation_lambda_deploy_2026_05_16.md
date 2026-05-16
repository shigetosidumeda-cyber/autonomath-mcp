# Canary Attestation Lambda — Deploy Procedure (2026-05-16)

Phase 9 dry-run of the credit-run drain procedure surfaced a missing
`jpcite-credit-canary-attestation` Lambda (`ResourceNotFoundException`).
This doc captures the build + deploy + smoke-test procedure used to
land the Lambda on 2026-05-16. **NO LLM** anywhere in the runtime path —
the function only polls Batch / Cost Explorer / S3 (read-only) and
writes a JSON attestation to the reports bucket.

## Live deploy state

| field | value |
| --- | --- |
| function name | `jpcite-credit-canary-attestation-emitter` |
| function ARN | `arn:aws:lambda:ap-northeast-1:993693061769:function:jpcite-credit-canary-attestation-emitter` |
| region | `ap-northeast-1` (co-located with Batch + reports bucket) |
| runtime | `python3.12` |
| handler | `jpcite_credit_canary_attestation.lambda_handler` |
| memory | 256 MB |
| timeout | 120s |
| code size | ~10.5 KB (well under the 100 KB constraint) |
| role ARN | `arn:aws:iam::993693061769:role/jpcite-credit-canary-attestation-role` |
| profile | `bookyou-recovery` |
| AWS account | `993693061769` |

Cost Explorer (`ce:GetCostAndUsage`) only resolves in `us-east-1`, so
the handler uses `JPCITE_CE_REGION=us-east-1` while the function and
all other AWS endpoints remain in `ap-northeast-1`.

## Safety env vars (default OFF)

The Lambda mirrors the Stream W (Wave 50 tick 8) concern-separation
pattern. **Both** flags must flip `true` for any side effect to fire:

| env var | default | controls |
| --- | --- | --- |
| `JPCITE_CANARY_ATTESTATION_ENABLED` | `false` | enables the attestation envelope (still local-only) |
| `JPCITE_CANARY_LIVE_UPLOAD` | `false` | gates the actual S3 `PutObject` upload |

Default deploy ships both as `"false"`, so the first invocation is
inherently a dry-run that returns the attestation JSON without writing
anything to S3. Live mode is a deliberate two-step opt-in by the
operator (mirrors the `--unlock-live-aws-commands` flag on the CLI
counterpart).

## Files involved

- `scripts/aws_credit_ops/emit_canary_attestation.py` — shared CLI +
  Lambda library, pure Python with lazy boto3 import.
- `infra/aws/lambda/jpcite_credit_canary_attestation.py` — thin Lambda
  handler that wires `lambda_handler` to the shared library.
- `infra/aws/iam/jpcite_credit_canary_attestation_trust.json` — IAM
  trust policy (Lambda service principal).
- `infra/aws/iam/jpcite_credit_canary_attestation_policy.json` — IAM
  inline policy (Batch ListJobs + CE GetCostAndUsage + S3 ListBucket
  on raw/derived/reports + S3 PutObject only under
  `reports/attestations/*` + CloudWatch Logs).
- `scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh` —
  idempotent deploy script (creates IAM role on first run, updates
  function code + configuration on subsequent runs).
- `tests/test_emit_canary_attestation.py` — 17 unit tests covering AST
  guards, pagination, malformed CE responses, write/upload dry-run
  paths, and Lambda handler envelope shape.

## Build + deploy

```bash
# Verify profile + identity (must show bookyou-recovery-admin)
AWS_PROFILE=bookyou-recovery aws sts get-caller-identity

# Idempotent deploy — creates role + function on first run,
# updates code + config on subsequent runs. No EventBridge rule.
AWS_PROFILE=bookyou-recovery \
  bash scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh
```

The deploy script:

1. Creates or reuses `jpcite-credit-canary-attestation-role`.
2. Attaches the inline policy from `infra/aws/iam/*_policy.json`.
3. Sleeps 10s to wait for IAM propagation.
4. Builds a 2-file zip (`emit_canary_attestation.py` +
   `jpcite_credit_canary_attestation.py`) and creates or updates the
   Lambda function.
5. Prints a summary block with the live ARNs.

## Smoke test

```bash
cat > /tmp/canary_payload.json <<'EOF'
{
  "run_id": "canary-smoke-20260516T1830Z",
  "current_status": "IN_PROGRESS",
  "started_at": "2026-05-16T18:00:00+00:00"
}
EOF

AWS_PROFILE=bookyou-recovery aws lambda invoke \
  --region ap-northeast-1 \
  --function-name jpcite-credit-canary-attestation-emitter \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/canary_payload.json \
  /tmp/canary_response.json
```

Expected output:

```
{
  "StatusCode": 200,
  "ExecutedVersion": "$LATEST"
}
```

Observed in the 2026-05-16 18:30 JST smoke:

- `StatusCode = 200`, `mode = "dry_run"`, `duration_s ~ 57.8`.
- `succeeded = 0 / failed = 0 / running = 0` (no Batch jobs in flight at
  the smoke moment).
- `raw_objects = 6346`, `derived_objects = 50000` (`sampled = true`
  because derived hit the 50-page LIST cap).
- `cost_consumed_usd = 0.0` (Cost Explorer reports MTD = 0 for the
  bookyou-recovery profile in this smoke window).
- `upload_action.live = false` (default-OFF env keeps S3 untouched).
- `safety_env.JPCITE_CANARY_ATTESTATION_ENABLED = "false"`,
  `safety_env.JPCITE_CANARY_LIVE_UPLOAD = "false"`.

## Wiring to Step Functions (deferred)

`infra/aws/step_functions/jpcite_credit_orchestrator.json` does **not**
yet reference the Lambda — wiring is a separate landing once the
operator chooses where in the orchestrator (after each parallel batch,
or only on the final aggregate step) the per-tick attestation should
fire. Until then, the Lambda is invokable manually via `aws lambda
invoke` and remains safe (no side effects with default env).

## Promotion to live mode (operator-only, intentional)

```bash
AWS_PROFILE=bookyou-recovery aws lambda update-function-configuration \
  --region ap-northeast-1 \
  --function-name jpcite-credit-canary-attestation-emitter \
  --environment 'Variables={
    JPCITE_CANARY_ATTESTATION_ENABLED=true,
    JPCITE_CANARY_LIVE_UPLOAD=true,
    JPCITE_BATCH_REGION=ap-northeast-1,
    JPCITE_S3_REGION=ap-northeast-1,
    JPCITE_CE_REGION=us-east-1,
    JPCITE_CANARY_RAW_BUCKET=jpcite-credit-993693061769-202605-raw,
    JPCITE_CANARY_DERIVED_BUCKET=jpcite-credit-993693061769-202605-derived,
    JPCITE_CANARY_ATTESTATION_BUCKET=jpcite-credit-993693061769-202605-reports,
    JPCITE_CANARY_BATCH_QUEUE_ARN=arn:aws:batch:ap-northeast-1:993693061769:job-queue/jpcite-credit-fargate-spot-short-queue
  }'
```

After flipping, attestations land under
`s3://jpcite-credit-993693061769-202605-reports/attestations/aws_canary_attestation_<run_id>.json`
with tagging `Project=jpcite&CreditRun=2026-05&AutoStop=2026-05-29`.

## Teardown

```bash
AWS_PROFILE=bookyou-recovery aws lambda delete-function \
  --region ap-northeast-1 \
  --function-name jpcite-credit-canary-attestation-emitter

AWS_PROFILE=bookyou-recovery aws iam delete-role-policy \
  --role-name jpcite-credit-canary-attestation-role \
  --policy-name jpcite-credit-canary-attestation-policy

AWS_PROFILE=bookyou-recovery aws iam delete-role \
  --role-name jpcite-credit-canary-attestation-role
```

Tagged `Project=jpcite,CreditRun=2026-05` so the
`scripts/teardown/run_all.sh` sweep can find and remove it on the
2026-05-29 AutoStop date.

## Quality gates verified before deploy

- `pytest tests/test_emit_canary_attestation.py` — 17/17 PASS.
- `pytest tests/test_emit_canary_attestation.py tests/test_emit_burn_metric.py`
  — 35/35 PASS (no regression on the sibling burn-metric emitter).
- `ruff check` on Lambda + shared library + tests — clean.
- `mypy --strict` on `emit_canary_attestation.py` and
  `jpcite_credit_canary_attestation.py` — clean.
- Code zip size 10,557 bytes (constraint was < 100 KB).
- `aws sts get-caller-identity` confirmed `bookyou-recovery-admin`.
- Live smoke `aws lambda invoke` returned `StatusCode 200`.

last_updated: 2026-05-16
