#!/usr/bin/env bash
# Deploy / update the jpcite CloudFront bandwidth load-tester Lambda.
#
# Idempotent: first run creates role + function; subsequent runs update
# the code + configuration in place.
#
# Usage:
#   AWS_PROFILE=bookyou-recovery JPCITE_CF_DISTRIBUTION_DOMAIN=d1234.cloudfront.net \
#     ./scripts/aws_credit_ops/deploy_cf_loadtest_lambda.sh
#
# Default JPCITE_CF_LOADTEST_ENABLED=false — operator opts in explicitly.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
REGION="${REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"
ROLE_NAME="${ROLE_NAME:-jpcite-cf-loadtest-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-cf-loadtest-policy}"
FUNCTION_NAME="${FUNCTION_NAME:-jpcite-cf-loadtest}"
DIST_DOMAIN="${JPCITE_CF_DISTRIBUTION_DOMAIN:-}"
ENABLED="${JPCITE_CF_LOADTEST_ENABLED:-false}"
REQUESTS="${JPCITE_CF_REQUESTS:-10000}"
CONCURRENCY="${JPCITE_CF_CONCURRENCY:-64}"
AVG_BYTES="${JPCITE_CF_AVG_BYTES:-2000}"
BUDGET_USD="${JPCITE_CF_BUDGET_USD:-100}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAMBDA_SRC="$ROOT/infra/aws/lambda/jpcite_cf_loadtest.py"
SHARED_SRC="$ROOT/scripts/aws_credit_ops/cf_loadtest_runner.py"
MANIFEST_SRC="$ROOT/infra/aws/cloudfront/jpcite_packet_keys.txt"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_cf_loadtest_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_cf_loadtest_policy.json"

for f in "$LAMBDA_SRC" "$SHARED_SRC" "$TRUST_DOC" "$POLICY_DOC"; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done

if [ -z "$DIST_DOMAIN" ]; then
  echo "[deploy] WARN: JPCITE_CF_DISTRIBUTION_DOMAIN unset — Lambda will require event-level override" >&2
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cp "$LAMBDA_SRC" "$WORKDIR/jpcite_cf_loadtest.py"
cp "$SHARED_SRC" "$WORKDIR/cf_loadtest_runner.py"
if [ -f "$MANIFEST_SRC" ]; then
  cp "$MANIFEST_SRC" "$WORKDIR/jpcite_packet_keys.txt"
else
  echo "[deploy] WARN: manifest $MANIFEST_SRC missing — Lambda will run with empty key list (dry-run only)" >&2
  : > "$WORKDIR/jpcite_packet_keys.txt"
fi
( cd "$WORKDIR" && zip -q jpcite_cf_loadtest.zip jpcite_cf_loadtest.py cf_loadtest_runner.py jpcite_packet_keys.txt )
ZIP_PATH="$WORKDIR/jpcite_cf_loadtest.zip"

echo "[deploy] step 1/4  IAM role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC" \
    --description "jpcite CloudFront load-tester Lambda execution role" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=AutoStop,Value=2026-05-29 >/dev/null
  echo "  created role $ROLE_NAME"
else
  echo "  reuse role $ROLE_NAME"
fi

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_DOC" >/dev/null
echo "  policy attached ($POLICY_NAME)"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "[deploy] step 2/4  wait for role propagation (10s)"
sleep 10

echo "[deploy] step 3/4  Lambda function"
ENV_VARS="Variables={JPCITE_CF_LOADTEST_ENABLED=$ENABLED,JPCITE_CF_DISTRIBUTION_DOMAIN=$DIST_DOMAIN,JPCITE_CF_REQUESTS=$REQUESTS,JPCITE_CF_CONCURRENCY=$CONCURRENCY,JPCITE_CF_AVG_BYTES=$AVG_BYTES,JPCITE_CF_BUDGET_USD=$BUDGET_USD,JPCITE_CF_LOADTEST_NAMESPACE=jpcite/credit}"

if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" >/dev/null
  aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION_NAME"
  aws lambda update-function-configuration \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --timeout 300 \
    --memory-size 1024 \
    --environment "$ENV_VARS" >/dev/null
  echo "  updated function $FUNCTION_NAME"
else
  aws lambda create-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "jpcite_cf_loadtest.lambda_handler" \
    --timeout 300 \
    --memory-size 1024 \
    --zip-file "fileb://$ZIP_PATH" \
    --environment "$ENV_VARS" \
    --tags Project=jpcite,CreditRun=2026-05,AutoStop=2026-05-29 >/dev/null
  aws lambda wait function-active --region "$REGION" --function-name "$FUNCTION_NAME"
  echo "  created function $FUNCTION_NAME"
fi

LAMBDA_ARN=$(aws lambda get-function \
  --region "$REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' --output text)

echo "[deploy] step 4/4  summary"
cat <<EOF

[deploy] done.
  lambda_arn        = $LAMBDA_ARN
  role_arn          = $ROLE_ARN
  enabled           = $ENABLED  (set JPCITE_CF_LOADTEST_ENABLED=true on the function to arm)
  distribution      = $DIST_DOMAIN
  requests/inv      = $REQUESTS
  concurrency/inv   = $CONCURRENCY
  avg_obj_bytes     = $AVG_BYTES
  budget_usd        = $BUDGET_USD

invoke (one shot):
  aws lambda invoke --region $REGION --function-name $FUNCTION_NAME \\
    --invocation-type Event /dev/null

parallel (5 invocations):
  AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/cf_loadtest_invoke.sh 5
EOF
