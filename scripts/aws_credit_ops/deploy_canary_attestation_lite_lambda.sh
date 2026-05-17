#!/usr/bin/env bash
# Deploy the lightweight high-TPS jpcite credit canary-attestation Lambda.
#
# Companion to deploy_canary_attestation_lambda.sh — the LITE variant is
# purpose-built for the 2026-05-17 Lane G mass-invocation burn lane.
# Reuses the same IAM role + policy as the heavy emitter (S3 PutObject +
# CloudWatch Logs).
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_canary_attestation_lite_lambda.sh
#
# Idempotent: first run creates; subsequent runs update code + config.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
LAMBDA_REGION="${LAMBDA_REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-canary-attestation-role}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-credit-canary-attestation-lite}"
LITE_S3_ENABLED="${JPCITE_CANARY_LITE_S3_ENABLED:-false}"
LITE_S3_SAMPLE_RATE="${JPCITE_CANARY_LITE_S3_SAMPLE_RATE:-0.001}"
ATTESTATION_BUCKET="${JPCITE_CANARY_ATTESTATION_BUCKET:-jpcite-credit-${ACCOUNT_ID}-202605-reports}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_credit_canary_attestation_lite.py"

[ -f "$LAMBDA_SRC" ] || { echo "missing $LAMBDA_SRC"; exit 1; }

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_credit_canary_attestation_lite.py"
( cd "$WORKDIR" && zip -q jpcite_credit_canary_attestation_lite.zip \
    jpcite_credit_canary_attestation_lite.py )
ZIP_PATH="$WORKDIR/jpcite_credit_canary_attestation_lite.zip"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

ENV_VARS="Variables={JPCITE_CANARY_LITE_S3_ENABLED=$LITE_S3_ENABLED,JPCITE_CANARY_LITE_S3_SAMPLE_RATE=$LITE_S3_SAMPLE_RATE,JPCITE_CANARY_ATTESTATION_BUCKET=$ATTESTATION_BUCKET}"

if aws lambda get-function --region "$LAMBDA_REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" >/dev/null
  aws lambda wait function-updated \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME"
  aws lambda update-function-configuration \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --timeout 10 \
    --memory-size 128 \
    --environment "$ENV_VARS" >/dev/null
  echo "updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_credit_canary_attestation_lite.lambda_handler" \
    --timeout 10 \
    --memory-size 128 \
    --zip-file "fileb://$ZIP_PATH" \
    --environment "$ENV_VARS" \
    --tags Project=jpcite,CreditRun=2026-05,Lane=G >/dev/null
  aws lambda wait function-active \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME"
  echo "created function $FUNCTION_NAME"
fi

LAMBDA_ARN=$(aws lambda get-function \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' --output text)

cat <<EOF
[deploy-lite] done.
  lambda_arn         = $LAMBDA_ARN
  role_arn           = $ROLE_ARN
  memory_size        = 128 MB
  timeout            = 10 s
  s3_enabled         = $LITE_S3_ENABLED
  s3_sample_rate     = $LITE_S3_SAMPLE_RATE
  attestation_bucket = $ATTESTATION_BUCKET
EOF
