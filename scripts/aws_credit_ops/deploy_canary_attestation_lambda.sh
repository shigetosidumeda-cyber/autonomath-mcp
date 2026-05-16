#!/usr/bin/env bash
# Deploy / update the jpcite credit live canary-attestation Lambda.
#
# Architecture:
#   - Lambda lives in ap-northeast-1 (co-located with Batch + reports bucket).
#   - Cost Explorer endpoint is us-east-1 (region-agnostic).
#   - The Step Functions orchestrator invokes this Lambda after each
#     execution batch (see infra/aws/step_functions/jpcite_credit_orchestrator.json).
#   - Default JPCITE_CANARY_ATTESTATION_ENABLED=false +
#     JPCITE_CANARY_LIVE_UPLOAD=false (operator opts in explicitly).
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh
#
# Idempotent: first run creates the role + function; subsequent runs update
# code + configuration in place. No EventBridge rule is created — invocation
# is driven by Step Functions per-batch.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
LAMBDA_REGION="${LAMBDA_REGION:-ap-northeast-1}"
CE_REGION="${CE_REGION:-us-east-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-canary-attestation-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-credit-canary-attestation-policy}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-credit-canary-attestation-emitter}"
ATTESTATION_ENABLED="${JPCITE_CANARY_ATTESTATION_ENABLED:-false}"
ATTESTATION_LIVE_UPLOAD="${JPCITE_CANARY_LIVE_UPLOAD:-false}"
RAW_BUCKET="${JPCITE_CANARY_RAW_BUCKET:-jpcite-credit-${ACCOUNT_ID}-202605-raw}"
DERIVED_BUCKET="${JPCITE_CANARY_DERIVED_BUCKET:-jpcite-credit-${ACCOUNT_ID}-202605-derived}"
ATTESTATION_BUCKET="${JPCITE_CANARY_ATTESTATION_BUCKET:-jpcite-credit-${ACCOUNT_ID}-202605-reports}"
JOB_QUEUE="${JPCITE_CANARY_BATCH_QUEUE_ARN:-arn:aws:batch:${LAMBDA_REGION}:${ACCOUNT_ID}:job-queue/jpcite-credit-fargate-spot-short-queue}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_credit_canary_attestation.py"
SHARED_SRC="$ROOT/scripts/aws_credit_ops/emit_canary_attestation.py"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_credit_canary_attestation_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_credit_canary_attestation_policy.json"

for f in "$LAMBDA_SRC" "$SHARED_SRC" "$TRUST_DOC" "$POLICY_DOC"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_credit_canary_attestation.py"
cp "$SHARED_SRC" "$WORKDIR/emit_canary_attestation.py"
( cd "$WORKDIR" && zip -q jpcite_credit_canary_attestation.zip \
    jpcite_credit_canary_attestation.py emit_canary_attestation.py )
ZIP_PATH="$WORKDIR/jpcite_credit_canary_attestation.zip"

echo "[deploy] step 1/5  IAM role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite credit live canary-attestation Lambda execution role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 >/dev/null
  echo "  created role $ROLE_NAME"
else
  echo "  reuse role $ROLE_NAME"
fi

echo "[deploy] step 2/5  inline policy"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_DOC" >/dev/null
echo "  policy attached ($POLICY_NAME)"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  role_arn=$ROLE_ARN"

echo "[deploy] step 3/5  wait for role propagation (10s)"
sleep 10

echo "[deploy] step 4/5  Lambda function"
ENV_VARS="Variables={JPCITE_CANARY_ATTESTATION_ENABLED=$ATTESTATION_ENABLED,JPCITE_CANARY_LIVE_UPLOAD=$ATTESTATION_LIVE_UPLOAD,JPCITE_BATCH_REGION=$LAMBDA_REGION,JPCITE_S3_REGION=$LAMBDA_REGION,JPCITE_CE_REGION=$CE_REGION,JPCITE_CANARY_RAW_BUCKET=$RAW_BUCKET,JPCITE_CANARY_DERIVED_BUCKET=$DERIVED_BUCKET,JPCITE_CANARY_ATTESTATION_BUCKET=$ATTESTATION_BUCKET,JPCITE_CANARY_BATCH_QUEUE_ARN=$JOB_QUEUE}"

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
    --timeout 120 \
    --memory-size 256 \
    --environment "$ENV_VARS" >/dev/null
  echo "  updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_credit_canary_attestation.lambda_handler" \
    --timeout 120 \
    --memory-size 256 \
    --zip-file "fileb://$ZIP_PATH" \
    --environment "$ENV_VARS" \
    --tags Project=jpcite,CreditRun=2026-05 >/dev/null
  aws lambda wait function-active \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME"
  echo "  created function $FUNCTION_NAME"
fi

LAMBDA_ARN=$(aws lambda get-function \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' --output text)

echo "[deploy] step 5/5  summary"
cat <<EOF

[deploy] done.
  lambda_arn          = $LAMBDA_ARN
  role_arn            = $ROLE_ARN
  invocation          = Step Functions per-batch (no EventBridge schedule)
  enabled             = $ATTESTATION_ENABLED  (JPCITE_CANARY_ATTESTATION_ENABLED)
  live_upload         = $ATTESTATION_LIVE_UPLOAD  (JPCITE_CANARY_LIVE_UPLOAD)
  raw_bucket          = $RAW_BUCKET
  derived_bucket      = $DERIVED_BUCKET
  attestation_bucket  = $ATTESTATION_BUCKET
  batch_queue         = $JOB_QUEUE
EOF
