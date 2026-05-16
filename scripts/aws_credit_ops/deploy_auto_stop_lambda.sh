#!/usr/bin/env bash
# Deploy / update the jpcite credit auto-stop Lambda.
#
# Architecture:
#   - Lambda lives in us-east-1 (co-located with the SNS topic).
#   - Target Batch resources live in ap-northeast-1 (passed via env var).
#   - Default JPCITE_AUTO_STOP_ENABLED=false (operator must opt in).
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_auto_stop_lambda.sh
#
# Idempotent: first run creates the role + function + subscription;
# subsequent runs update the code + configuration in place.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
LAMBDA_REGION="${LAMBDA_REGION:-us-east-1}"
BATCH_REGION="${BATCH_REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-auto-stop-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-credit-auto-stop-policy}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-credit-auto-stop}"
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-arn:aws:sns:us-east-1:${ACCOUNT_ID}:jpcite-credit-cost-alerts}"
AUTO_STOP_ENABLED="${JPCITE_AUTO_STOP_ENABLED:-false}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_credit_auto_stop.py"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_credit_auto_stop_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_credit_auto_stop_policy.json"

[ -f "$LAMBDA_SRC" ] || { echo "missing $LAMBDA_SRC"; exit 1; }
[ -f "$TRUST_DOC" ] || { echo "missing $TRUST_DOC"; exit 1; }
[ -f "$POLICY_DOC" ] || { echo "missing $POLICY_DOC"; exit 1; }

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_credit_auto_stop.py"
( cd "$WORKDIR" && zip -q jpcite_credit_auto_stop.zip jpcite_credit_auto_stop.py )
ZIP_PATH="$WORKDIR/jpcite_credit_auto_stop.zip"

echo "[deploy] step 1/6  IAM role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite credit auto-stop Lambda execution role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=AutoStop,Value=2026-05-29 >/dev/null
  echo "  created role $ROLE_NAME"
else
  echo "  reuse role $ROLE_NAME"
fi

echo "[deploy] step 2/6  inline policy"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_DOC" >/dev/null
echo "  policy attached ($POLICY_NAME)"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  role_arn=$ROLE_ARN"

echo "[deploy] step 3/6  wait for role propagation (10s)"
sleep 10

echo "[deploy] step 4/6  Lambda function"
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
    --environment "Variables={JPCITE_AUTO_STOP_ENABLED=$AUTO_STOP_ENABLED,JPCITE_BATCH_REGION=$BATCH_REGION,JPCITE_ATTESTATION_TOPIC_ARN=$SNS_TOPIC_ARN}" >/dev/null
  echo "  updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_credit_auto_stop.lambda_handler" \
    --timeout 120 \
    --memory-size 256 \
    --zip-file "fileb://$ZIP_PATH" \
    --environment "Variables={JPCITE_AUTO_STOP_ENABLED=$AUTO_STOP_ENABLED,JPCITE_BATCH_REGION=$BATCH_REGION,JPCITE_ATTESTATION_TOPIC_ARN=$SNS_TOPIC_ARN}" \
    --tags Project=jpcite,CreditRun=2026-05,AutoStop=2026-05-29 >/dev/null
  aws lambda wait function-active \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME"
  echo "  created function $FUNCTION_NAME"
fi

LAMBDA_ARN=$(aws lambda get-function \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' --output text)
echo "  lambda_arn=$LAMBDA_ARN"

echo "[deploy] step 5/6  SNS invoke permission"
EXISTING_POLICY=$(aws lambda get-policy \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" 2>/dev/null || echo "")
if echo "$EXISTING_POLICY" | grep -q 'jpcite-credit-sns-invoke'; then
  echo "  SNS invoke permission already present"
else
  aws lambda add-permission \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "jpcite-credit-sns-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "sns.amazonaws.com" \
    --source-arn "$SNS_TOPIC_ARN" >/dev/null
  echo "  added SNS invoke permission"
fi

echo "[deploy] step 6/6  SNS subscription"
EXISTING_SUB=$(aws sns list-subscriptions-by-topic \
  --region "$LAMBDA_REGION" \
  --topic-arn "$SNS_TOPIC_ARN" \
  --query "Subscriptions[?Endpoint=='$LAMBDA_ARN'].SubscriptionArn | [0]" \
  --output text 2>/dev/null || echo "None")
if [ "$EXISTING_SUB" != "None" ] && [ -n "$EXISTING_SUB" ] && [ "$EXISTING_SUB" != "PendingConfirmation" ]; then
  SUB_ARN="$EXISTING_SUB"
  echo "  reuse subscription $SUB_ARN"
else
  SUB_ARN=$(aws sns subscribe \
    --region "$LAMBDA_REGION" \
    --topic-arn "$SNS_TOPIC_ARN" \
    --protocol lambda \
    --notification-endpoint "$LAMBDA_ARN" \
    --query 'SubscriptionArn' --output text)
  echo "  created subscription $SUB_ARN"
fi

cat <<EOF

[deploy] done.
  lambda_arn   = $LAMBDA_ARN
  role_arn     = $ROLE_ARN
  sub_arn      = $SUB_ARN
  enabled      = $AUTO_STOP_ENABLED  (set JPCITE_AUTO_STOP_ENABLED=true on the function to arm)
  topic        = $SNS_TOPIC_ARN
  lambda_rgn   = $LAMBDA_REGION
  batch_rgn    = $BATCH_REGION
EOF
