#!/usr/bin/env bash
# Deploy / update the jpcite credit Lane J — burn-rate monitor Lambda.
#
# Architecture:
#   - Lambda lives in ap-northeast-1 (co-located with the CloudWatch dashboard).
#   - Cost Explorer endpoint is us-east-1 (region-agnostic, single endpoint).
#   - EventBridge rule rate(1 hour) fires the Lambda on a fixed schedule.
#   - Default JPCITE_BURN_RATE_MONITOR_ENABLED=false (operator opts in explicitly).
#
# Difference from deploy_burn_metric_lambda.sh (5-minute classifier):
#   - 1-hour cadence (operator wants daily-rolling pace verification, not 5-min ramp gate)
#   - Computes 24h burn rate + projects credit-exhaust day (linear)
#   - Alerts on OVER_BUDGET (>$3500/day) or UNDER_PACE (<$1500/day)
#   - Target band: $2000-$3000/day × 7 days = $19,490 credit exhaust
#
# Usage:
#   AWS_PROFILE=bookyou-recovery JPCITE_BURN_RATE_MONITOR_ENABLED=true \
#     ./scripts/aws_credit_ops/deploy_burn_rate_monitor_lambda.sh
#
# Idempotent: first run creates the role + function + EventBridge rule;
# subsequent runs update the code + configuration in place.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
LAMBDA_REGION="${LAMBDA_REGION:-ap-northeast-1}"
CE_REGION="${CE_REGION:-us-east-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-burn-metric-role}"  # reuse existing role
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-credit-burn-rate-monitor}"
RULE_NAME="${RULE_NAME:-jpcite-credit-burn-monitor-hourly}"
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-arn:aws:sns:us-east-1:${ACCOUNT_ID}:jpcite-credit-cost-alerts}"
MONITOR_ENABLED="${JPCITE_BURN_RATE_MONITOR_ENABLED:-false}"
BURN_TARGET_LO="${JPCITE_BURN_TARGET_LO_USD_PER_DAY:-2000}"
BURN_TARGET_HI="${JPCITE_BURN_TARGET_HI_USD_PER_DAY:-3000}"
BURN_ALERT_LO="${JPCITE_BURN_ALERT_LO_USD_PER_DAY:-1500}"
BURN_ALERT_HI="${JPCITE_BURN_ALERT_HI_USD_PER_DAY:-3500}"
CREDIT_NEVER_REACH="${JPCITE_CREDIT_NEVER_REACH_USD:-19490}"
CREDIT_HARD_STOP="${JPCITE_CREDIT_HARD_STOP_USD:-18900}"
METRIC_NAMESPACE="${JPCITE_BURN_METRIC_NAMESPACE:-jpcite/credit}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_credit_burn_rate_monitor.py"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_credit_burn_metric_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_credit_burn_metric_policy.json"

for f in "$LAMBDA_SRC" "$TRUST_DOC" "$POLICY_DOC"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_credit_burn_rate_monitor.py"
( cd "$WORKDIR" && zip -q jpcite_credit_burn_rate_monitor.zip jpcite_credit_burn_rate_monitor.py )
ZIP_PATH="$WORKDIR/jpcite_credit_burn_rate_monitor.zip"

echo "[deploy] step 1/7  IAM role (reuse existing $ROLE_NAME)"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite credit burn-metric / rate-monitor Lambda execution role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 >/dev/null
  echo "  created role $ROLE_NAME"
  echo "[deploy] step 1b   attach inline policy"
  aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "jpcite-credit-burn-metric-policy" \
    --policy-document "file://$POLICY_DOC" >/dev/null
else
  echo "  reuse role $ROLE_NAME (policy already attached by deploy_burn_metric_lambda.sh)"
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  role_arn=$ROLE_ARN"

echo "[deploy] step 2/7  wait for role propagation (5s)"
sleep 5

echo "[deploy] step 3/7  Lambda function"
ENV_VARS="Variables={JPCITE_BURN_RATE_MONITOR_ENABLED=$MONITOR_ENABLED,JPCITE_BURN_TARGET_LO_USD_PER_DAY=$BURN_TARGET_LO,JPCITE_BURN_TARGET_HI_USD_PER_DAY=$BURN_TARGET_HI,JPCITE_BURN_ALERT_LO_USD_PER_DAY=$BURN_ALERT_LO,JPCITE_BURN_ALERT_HI_USD_PER_DAY=$BURN_ALERT_HI,JPCITE_CREDIT_NEVER_REACH_USD=$CREDIT_NEVER_REACH,JPCITE_CREDIT_HARD_STOP_USD=$CREDIT_HARD_STOP,JPCITE_BURN_METRIC_NAMESPACE=$METRIC_NAMESPACE,JPCITE_BURN_METRIC_REGION=$LAMBDA_REGION,JPCITE_CE_REGION=$CE_REGION,JPCITE_ATTESTATION_TOPIC_ARN=$SNS_TOPIC_ARN}"

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
    --handler "jpcite_credit_burn_rate_monitor.lambda_handler" \
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

echo "[deploy] step 4/7  EventBridge rule (rate(1 hour))"
if ! aws events describe-rule --region "$LAMBDA_REGION" --name "$RULE_NAME" >/dev/null 2>&1; then
  aws events put-rule \
    --region "$LAMBDA_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "rate(1 hour)" \
    --description "jpcite credit Lane J burn rate monitor (every 1 hour)" \
    --state ENABLED \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=Lane,Value=J >/dev/null
  echo "  created rule $RULE_NAME"
else
  aws events put-rule \
    --region "$LAMBDA_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "rate(1 hour)" \
    --state ENABLED >/dev/null
  echo "  updated rule $RULE_NAME"
fi

RULE_ARN=$(aws events describe-rule \
  --region "$LAMBDA_REGION" \
  --name "$RULE_NAME" \
  --query 'Arn' --output text)
echo "  rule_arn=$RULE_ARN"

echo "[deploy] step 5/7  EventBridge invoke permission"
EXISTING_PERM=$(aws lambda get-policy \
  --region "$LAMBDA_REGION" \
  --function-name "$FUNCTION_NAME" 2>/dev/null || echo "")
if echo "$EXISTING_PERM" | grep -q 'jpcite-credit-burn-rate-monitor-events-invoke'; then
  echo "  EventBridge invoke permission already present"
else
  aws lambda add-permission \
    --region "$LAMBDA_REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "jpcite-credit-burn-rate-monitor-events-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" >/dev/null
  echo "  added EventBridge invoke permission"
fi

echo "[deploy] step 6/7  wire EventBridge target"
aws events put-targets \
  --region "$LAMBDA_REGION" \
  --rule "$RULE_NAME" \
  --targets "Id=jpcite-credit-burn-rate-monitor-target,Arn=$LAMBDA_ARN" >/dev/null
echo "  target wired ($FUNCTION_NAME)"

echo "[deploy] step 7/7  summary"
cat <<EOF

[deploy] done.
  lambda_arn        = $LAMBDA_ARN
  role_arn          = $ROLE_ARN
  rule_arn          = $RULE_ARN
  schedule          = rate(1 hour)
  enabled           = $MONITOR_ENABLED  (set JPCITE_BURN_RATE_MONITOR_ENABLED=true on the function to arm)
  namespace         = $METRIC_NAMESPACE
  metric_rgn        = $LAMBDA_REGION
  ce_rgn            = $CE_REGION
  target_band       = \$${BURN_TARGET_LO}-\$${BURN_TARGET_HI}/day
  alert_band        = \$${BURN_ALERT_LO}-\$${BURN_ALERT_HI}/day
  credit_never_reach= \$$CREDIT_NEVER_REACH
  credit_hard_stop  = \$$CREDIT_HARD_STOP
  sns_topic         = $SNS_TOPIC_ARN
EOF
