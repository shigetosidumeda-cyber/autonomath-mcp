#!/usr/bin/env bash
# Deploy / update the jpcite credit real-time burn-metric emitter Lambda.
#
# Architecture:
#   - Lambda lives in ap-northeast-1 (co-located with the CloudWatch dashboard).
#   - Cost Explorer endpoint is us-east-1 (region-agnostic but single endpoint).
#   - EventBridge rule rate(5 minutes) fires the Lambda on a fixed schedule.
#   - Default JPCITE_BURN_METRIC_ENABLED=false (operator opts in explicitly).
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/deploy_burn_metric_lambda.sh
#
# Idempotent: first run creates the role + function + EventBridge rule;
# subsequent runs update the code + configuration in place.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
LAMBDA_REGION="${LAMBDA_REGION:-ap-northeast-1}"
CE_REGION="${CE_REGION:-us-east-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-burn-metric-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-credit-burn-metric-policy}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-credit-burn-metric-emitter}"
RULE_NAME="${RULE_NAME:-jpcite-credit-burn-metric-5min}"
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-arn:aws:sns:us-east-1:${ACCOUNT_ID}:jpcite-credit-cost-alerts}"
BURN_ENABLED="${JPCITE_BURN_METRIC_ENABLED:-false}"
CREDIT_TARGET="${JPCITE_CREDIT_TARGET_USD:-18300}"
HOURLY_STOP="${JPCITE_HOURLY_STOP_USD:-500}"
HOURLY_ALERT="${JPCITE_HOURLY_ALERT_USD:-500}"
METRIC_NAMESPACE="${JPCITE_BURN_METRIC_NAMESPACE:-jpcite/credit}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_credit_burn_metric.py"
SHARED_SRC="$ROOT/scripts/aws_credit_ops/emit_burn_metric.py"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_credit_burn_metric_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_credit_burn_metric_policy.json"

for f in "$LAMBDA_SRC" "$SHARED_SRC" "$TRUST_DOC" "$POLICY_DOC"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_credit_burn_metric.py"
cp "$SHARED_SRC" "$WORKDIR/emit_burn_metric.py"
( cd "$WORKDIR" && zip -q jpcite_credit_burn_metric.zip jpcite_credit_burn_metric.py emit_burn_metric.py )
ZIP_PATH="$WORKDIR/jpcite_credit_burn_metric.zip"

echo "[deploy] step 1/7  IAM role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite credit real-time burn-metric Lambda execution role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 >/dev/null
  echo "  created role $ROLE_NAME"
else
  echo "  reuse role $ROLE_NAME"
fi

echo "[deploy] step 2/7  inline policy"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_DOC" >/dev/null
echo "  policy attached ($POLICY_NAME)"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  role_arn=$ROLE_ARN"

echo "[deploy] step 3/7  wait for role propagation (10s)"
sleep 10

echo "[deploy] step 4/7  Lambda function"
ENV_VARS="Variables={JPCITE_BURN_METRIC_ENABLED=$BURN_ENABLED,JPCITE_CREDIT_TARGET_USD=$CREDIT_TARGET,JPCITE_HOURLY_STOP_USD=$HOURLY_STOP,JPCITE_HOURLY_ALERT_USD=$HOURLY_ALERT,JPCITE_BURN_METRIC_NAMESPACE=$METRIC_NAMESPACE,JPCITE_BURN_METRIC_REGION=$LAMBDA_REGION,JPCITE_CE_REGION=$CE_REGION,JPCITE_ATTESTATION_TOPIC_ARN=$SNS_TOPIC_ARN}"

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
    --timeout 60 \
    --memory-size 256 \
    --environment "$ENV_VARS" >/dev/null
  echo "  updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_credit_burn_metric.lambda_handler" \
    --timeout 60 \
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
echo "  lambda_arn=$LAMBDA_ARN"

echo "[deploy] step 5/7  EventBridge rule"
if ! aws events describe-rule --region "$LAMBDA_REGION" --name "$RULE_NAME" >/dev/null 2>&1; then
  aws events put-rule \
    --region "$LAMBDA_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "rate(5 minutes)" \
    --description "jpcite credit real-time burn-metric emitter (every 5 min)" \
    --state ENABLED \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 >/dev/null
  echo "  created rule $RULE_NAME"
else
  aws events put-rule \
    --region "$LAMBDA_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "rate(5 minutes)" \
    --state ENABLED >/dev/null
  echo "  updated rule $RULE_NAME"
fi

RULE_ARN=$(aws events describe-rule \
  --region "$LAMBDA_REGION" \
  --name "$RULE_NAME" \
  --query 'Arn' --output text)
echo "  rule_arn=$RULE_ARN"

echo "[deploy] step 6/7  EventBridge invoke permission + target"
EXISTING_PERM=$(aws lambda get-policy \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" 2>/dev/null || echo "")
if echo "$EXISTING_PERM" | grep -q 'jpcite-credit-burn-metric-events-invoke'; then
  echo "  EventBridge invoke permission already present"
else
  aws lambda add-permission \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "jpcite-credit-burn-metric-events-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" >/dev/null
  echo "  added EventBridge invoke permission"
fi

aws events put-targets \
  --region "$LAMBDA_REGION" \
  --rule "$RULE_NAME" \
  --targets "Id=jpcite-credit-burn-metric-target,Arn=$LAMBDA_ARN" >/dev/null
echo "  target wired ($FUNCTION_NAME)"

echo "[deploy] step 7/7  summary"
cat <<EOF

[deploy] done.
  lambda_arn   = $LAMBDA_ARN
  role_arn     = $ROLE_ARN
  rule_arn     = $RULE_ARN
  schedule     = rate(5 minutes)
  enabled      = $BURN_ENABLED  (set JPCITE_BURN_METRIC_ENABLED=true on the function to arm)
  namespace    = $METRIC_NAMESPACE
  metric_rgn   = $LAMBDA_REGION
  ce_rgn       = $CE_REGION
  target_usd   = $CREDIT_TARGET
  hourly_stop  = $HOURLY_STOP
  hourly_alert = $HOURLY_ALERT
  sns_topic    = $SNS_TOPIC_ARN
EOF
