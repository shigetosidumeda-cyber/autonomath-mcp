#!/usr/bin/env bash
# Lane E — Deploy / update the jpcite athena sustained burn Lambda + EventBridge schedule.
#
# Architecture:
#   - Lambda: ap-northeast-1, runs ONE Athena query per invocation.
#   - EventBridge rule rate(5 minutes) → 288 fires/day → ~$50/day burn target.
#   - Workgroup jpcite-credit-2026-05 already enforces 50 GB byte cap.
#   - Idempotent: re-runs update code + config + schedule in place.
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_athena_sustained_lambda_2026_05_17.sh
#
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
REGION="${REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"

ROLE_NAME="${ROLE_NAME:-jpcite-athena-sustained-2026-05-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-athena-sustained-2026-05-policy}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-athena-sustained-2026-05}"
RULE_NAME="${RULE_NAME:-jpcite-athena-sustained-2026-05}"
EB_ROLE_NAME="${EB_ROLE_NAME:-jpcite-athena-sustained-2026-05-eventbridge-role}"
EB_POLICY_NAME="${EB_POLICY_NAME:-jpcite-athena-sustained-2026-05-eventbridge-policy}"
TARGET_ID="${TARGET_ID:-jpcite-athena-sustained-target}"
SCHEDULE_RATE="${SCHEDULE_RATE:-rate(5 minutes)}"
SCHEDULE_STATE="${SCHEDULE_STATE:-ENABLED}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_athena_sustained_lambda.py"
SHARED_SRC="$ROOT/scripts/aws_credit_ops/athena_sustained_query_2026_05_17.py"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_athena_sustained_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_athena_sustained_policy.json"
EB_TRUST_DOC="$ROOT/infra/aws/iam/jpcite_athena_sustained_eventbridge_trust.json"
BIG_QUERIES_DIR="$ROOT/infra/aws/athena/big_queries"

for f in "$LAMBDA_SRC" "$SHARED_SRC" "$TRUST_DOC" "$POLICY_DOC" "$EB_TRUST_DOC"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done
[ -d "$BIG_QUERIES_DIR" ] || { echo "missing $BIG_QUERIES_DIR"; exit 1; }

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# Pack: Lambda entry + runner + ENTIRE big_queries tree (queries are read at runtime)
mkdir -p "$WORKDIR/pkg/infra/aws/athena/big_queries"
cp "$LAMBDA_SRC" "$WORKDIR/pkg/jpcite_athena_sustained_lambda.py"
cp "$SHARED_SRC" "$WORKDIR/pkg/athena_sustained_query_2026_05_17.py"
# Patch runner: in Lambda env, REPO_ROOT must resolve to /var/task
# (the Lambda working dir). We adjust by sym-mirroring the dir tree.
cp -R "$BIG_QUERIES_DIR/." "$WORKDIR/pkg/infra/aws/athena/big_queries/"
# also create __init__ shim so module resolution stays clean
touch "$WORKDIR/pkg/infra/__init__.py"
( cd "$WORKDIR/pkg" && zip -qr "$WORKDIR/jpcite_athena_sustained.zip" . )
ZIP_PATH="$WORKDIR/jpcite_athena_sustained.zip"
echo "[deploy] zip built: $(du -k "$ZIP_PATH" | awk '{print $1" KB"}')"

echo "[deploy] step 1/8  Lambda IAM role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite Lane E athena sustained burn Lambda role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=Lane,Value=E >/dev/null
  echo "  created role $ROLE_NAME"
else
  echo "  reuse role $ROLE_NAME"
fi

echo "[deploy] step 2/8  Lambda inline policy"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_DOC" >/dev/null
echo "  policy attached ($POLICY_NAME)"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  role_arn=$ROLE_ARN"

echo "[deploy] step 3/8  wait for role propagation (10s)"
sleep 10

echo "[deploy] step 4/8  Lambda function"
ENV_VARS="Variables={WORKGROUP=jpcite-credit-2026-05,DATABASE=jpcite_credit_2026_05,OUTPUT_S3=s3://jpcite-credit-993693061769-202605-derived/athena-results/}"

if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" >/dev/null
  aws lambda wait function-updated \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME"
  aws lambda update-function-configuration \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --timeout 180 \
    --memory-size 512 \
    --environment "$ENV_VARS" >/dev/null
  echo "  updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_athena_sustained_lambda.lambda_handler" \
    --timeout 180 \
    --memory-size 512 \
    --zip-file "fileb://$ZIP_PATH" \
    --environment "$ENV_VARS" \
    --tags Project=jpcite,CreditRun=2026-05,Lane=E >/dev/null
  echo "  created function $FUNCTION_NAME"
fi

FN_ARN=$(aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)
echo "  fn_arn=$FN_ARN"

echo "[deploy] step 5/8  EventBridge IAM role"
if ! aws iam get-role --role-name "$EB_ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$EB_ROLE_NAME" \
    --assume-role-policy-document "file://$EB_TRUST_DOC" \
    --description "jpcite Lane E EventBridge invoke Lambda role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=Lane,Value=E >/dev/null
  echo "  created EB role $EB_ROLE_NAME"
else
  echo "  reuse EB role $EB_ROLE_NAME"
fi

aws iam put-role-policy \
  --role-name "$EB_ROLE_NAME" \
  --policy-name "$EB_POLICY_NAME" \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"lambda:InvokeFunction\",\"Resource\":\"$FN_ARN\"}]}" >/dev/null
EB_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${EB_ROLE_NAME}"
echo "  eb_role_arn=$EB_ROLE_ARN"

echo "[deploy] step 6/8  wait for EB role propagation (5s)"
sleep 5

echo "[deploy] step 7/8  EventBridge rule"
aws events put-rule \
  --name "$RULE_NAME" \
  --schedule-expression "$SCHEDULE_RATE" \
  --state "$SCHEDULE_STATE" \
  --description "Lane E - jpcite Athena sustained burn (rate 5 min, ~288 fires/day, ~\$50/day)" \
  --region "$REGION" >/dev/null
RULE_ARN=$(aws events describe-rule --name "$RULE_NAME" --region "$REGION" --query 'Arn' --output text)
echo "  rule_arn=$RULE_ARN"

# Lambda permission so EB can invoke
STMT_ID="${RULE_NAME}-invoke"
aws lambda add-permission \
  --region "$REGION" \
  --function-name "$FUNCTION_NAME" \
  --statement-id "$STMT_ID" \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "$RULE_ARN" 2>/dev/null || echo "  (lambda permission already exists)"

echo "[deploy] step 8/8  EventBridge target"
aws events put-targets \
  --rule "$RULE_NAME" \
  --targets "Id=$TARGET_ID,Arn=$FN_ARN" \
  --region "$REGION" >/dev/null
echo "  target attached"

echo
echo "[deploy] DONE"
echo "  function:  $FUNCTION_NAME"
echo "  rule:      $RULE_NAME ($SCHEDULE_RATE, $SCHEDULE_STATE)"
echo "  rule_arn:  $RULE_ARN"
echo "  fn_arn:    $FN_ARN"
