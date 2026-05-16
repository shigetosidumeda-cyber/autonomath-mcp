#!/usr/bin/env bash
# Manage the jpcite-credit-orchestrator EventBridge schedule.
#
# Architecture:
#   - EventBridge rule `jpcite-credit-orchestrator-schedule` fires every N minutes
#     and calls `states:StartExecution` on the orchestrator state machine.
#   - State machine fans out to 7 J0X Batch jobs (~$1-2 / execution at current size).
#   - Continuous burn target: rate(10 minutes) × 144/day × 14 days = 2016 iterations.
#   - Default DISABLED — operator must explicitly enable to start the burn window.
#
# Usage:
#   AWS_PROFILE=bookyou-recovery ./scripts/aws_credit_ops/enable_burn_schedule.sh \
#       [--rate N]   tune schedule to rate(N minutes)        (no implicit state flip)
#       [--enable]   flip rule state to ENABLED              (starts the cadence)
#       [--disable]  flip rule state to DISABLED             (stops the cadence)
#       [--describe] print current rule state + target wiring (no mutation)
#       [--commit]   apply changes (otherwise DRY_RUN, prints what would change)
#
# Idempotent:
#   - First run with --commit creates the IAM role + inline policy + rule + target.
#   - Subsequent runs update in place (put-rule / put-targets are idempotent).
#   - --rate and --enable / --disable can be combined in one invocation.
#
# Examples:
#   ./scripts/aws_credit_ops/enable_burn_schedule.sh --describe
#   ./scripts/aws_credit_ops/enable_burn_schedule.sh --rate 10 --commit            # set rate but keep DISABLED
#   ./scripts/aws_credit_ops/enable_burn_schedule.sh --enable --commit             # start burn at current rate
#   ./scripts/aws_credit_ops/enable_burn_schedule.sh --rate 5 --enable --commit    # compress burn to 5-min cadence
#   ./scripts/aws_credit_ops/enable_burn_schedule.sh --disable --commit            # stop burn immediately
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
REGION="${REGION:-ap-northeast-1}"
ACCOUNT_ID="${ACCOUNT_ID:-993693061769}"

RULE_NAME="${RULE_NAME:-jpcite-credit-orchestrator-schedule}"
ROLE_NAME="${ROLE_NAME:-jpcite-credit-orchestrator-schedule-role}"
POLICY_NAME="${POLICY_NAME:-jpcite-credit-orchestrator-schedule-policy}"
STATE_MACHINE_ARN="${STATE_MACHINE_ARN:-arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:jpcite-credit-orchestrator}"
TARGET_ID="${TARGET_ID:-jpcite-credit-orchestrator-target}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRUST_DOC="$ROOT/infra/aws/iam/jpcite_credit_orchestrator_schedule_trust.json"
POLICY_DOC="$ROOT/infra/aws/iam/jpcite_credit_orchestrator_schedule_policy.json"

RATE_MIN=""
ACTION_STATE=""
COMMIT="false"
DESCRIBE="false"

usage() {
  sed -n '2,30p' "$0"
  exit "${1:-1}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --rate)
      [ $# -ge 2 ] || { echo "[burn-schedule] --rate requires a value"; exit 2; }
      RATE_MIN="$2"
      shift 2
      ;;
    --enable)
      ACTION_STATE="ENABLED"
      shift
      ;;
    --disable)
      ACTION_STATE="DISABLED"
      shift
      ;;
    --describe)
      DESCRIBE="true"
      shift
      ;;
    --commit)
      COMMIT="true"
      shift
      ;;
    -h|--help)
      usage 0
      ;;
    *)
      echo "[burn-schedule] unknown arg: $1"
      usage 1
      ;;
  esac
done

if [ -n "$RATE_MIN" ]; then
  case "$RATE_MIN" in
    ''|*[!0-9]*)
      echo "[burn-schedule] --rate must be a positive integer (minutes); got '$RATE_MIN'"
      exit 2
      ;;
  esac
  if [ "$RATE_MIN" -lt 1 ]; then
    echo "[burn-schedule] --rate must be >= 1 minute (got $RATE_MIN)"
    exit 2
  fi
fi

MODE="$([ "$COMMIT" = "true" ] && echo COMMIT || echo DRY_RUN)"

echo "[burn-schedule] mode: $MODE"
echo "[burn-schedule] region: $REGION  account: $ACCOUNT_ID"
echo "[burn-schedule] rule:   $RULE_NAME"
echo "[burn-schedule] target: $STATE_MACHINE_ARN"
echo "[burn-schedule] role:   $ROLE_NAME"
[ -n "$RATE_MIN" ]      && echo "[burn-schedule] requested rate: rate($RATE_MIN minutes)"
[ -n "$ACTION_STATE" ]  && echo "[burn-schedule] requested state: $ACTION_STATE"

if [ "$DESCRIBE" = "true" ]; then
  echo "[burn-schedule] describe-only — no mutation"
  if aws events describe-rule --region "$REGION" --name "$RULE_NAME" >/dev/null 2>&1; then
    aws events describe-rule --region "$REGION" --name "$RULE_NAME" \
      --query '{Name:Name,Arn:Arn,Schedule:ScheduleExpression,State:State,RoleArn:RoleArn}' \
      --output table
    echo
    echo "[burn-schedule] targets:"
    aws events list-targets-by-rule --region "$REGION" --rule "$RULE_NAME" \
      --query 'Targets[*].{Id:Id,Arn:Arn,RoleArn:RoleArn}' --output table
  else
    echo "[burn-schedule] rule does not exist (run with --commit to create)"
  fi
  exit 0
fi

# Resolve IAM role (create if needed when --commit).
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
  echo "[burn-schedule] role exists: $ROLE_ARN"
else
  echo "[burn-schedule] role missing: $ROLE_NAME"
  if [ "$COMMIT" = "true" ]; then
    [ -f "$TRUST_DOC" ]  || { echo "missing $TRUST_DOC"; exit 1; }
    [ -f "$POLICY_DOC" ] || { echo "missing $POLICY_DOC"; exit 1; }
    aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "file://$TRUST_DOC" \
      --description "jpcite credit orchestrator EventBridge → Step Functions invoke role" \
      --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=AutoStop,Value=2026-05-29 >/dev/null
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "$POLICY_NAME" \
      --policy-document "file://$POLICY_DOC" >/dev/null
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    echo "[burn-schedule] created role $ROLE_NAME ($ROLE_ARN)"
    echo "[burn-schedule] waiting 10s for role propagation"
    sleep 10
  else
    echo "[burn-schedule] DRY_RUN would create role $ROLE_NAME with trust=$TRUST_DOC policy=$POLICY_DOC"
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
  fi
fi

# Resolve current schedule + state (if rule exists).
CURRENT_SCHEDULE=""
CURRENT_STATE=""
if aws events describe-rule --region "$REGION" --name "$RULE_NAME" >/dev/null 2>&1; then
  CURRENT_SCHEDULE=$(aws events describe-rule --region "$REGION" --name "$RULE_NAME" --query 'ScheduleExpression' --output text)
  CURRENT_STATE=$(aws events describe-rule    --region "$REGION" --name "$RULE_NAME" --query 'State'              --output text)
  echo "[burn-schedule] current schedule: $CURRENT_SCHEDULE"
  echo "[burn-schedule] current state:    $CURRENT_STATE"
fi

# Decide final schedule + state.
if [ -n "$RATE_MIN" ]; then
  NEW_SCHEDULE="rate($RATE_MIN minutes)"
elif [ -n "$CURRENT_SCHEDULE" ]; then
  NEW_SCHEDULE="$CURRENT_SCHEDULE"
else
  NEW_SCHEDULE="rate(10 minutes)"
fi

if [ -n "$ACTION_STATE" ]; then
  NEW_STATE="$ACTION_STATE"
elif [ -n "$CURRENT_STATE" ]; then
  NEW_STATE="$CURRENT_STATE"
else
  NEW_STATE="DISABLED"
fi

echo "[burn-schedule] target schedule: $NEW_SCHEDULE"
echo "[burn-schedule] target state:    $NEW_STATE"

if [ "$COMMIT" = "true" ]; then
  echo "[burn-schedule] put-rule"
  aws events put-rule \
    --region "$REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "$NEW_SCHEDULE" \
    --description "jpcite credit orchestrator scheduled trigger ($NEW_SCHEDULE) — DISABLED by default, operator-controlled" \
    --state "$NEW_STATE" \
    --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=AutoStop,Value=2026-05-29 >/dev/null

  RULE_ARN=$(aws events describe-rule --region "$REGION" --name "$RULE_NAME" --query 'Arn' --output text)
  echo "[burn-schedule] rule_arn: $RULE_ARN"

  TARGET_INPUT='{"trigger":"eventbridge-schedule","source":"jpcite-credit-orchestrator-schedule"}'
  echo "[burn-schedule] put-targets"
  aws events put-targets \
    --region "$REGION" \
    --rule "$RULE_NAME" \
    --targets "Id=$TARGET_ID,Arn=$STATE_MACHINE_ARN,RoleArn=$ROLE_ARN,Input=$TARGET_INPUT" >/dev/null
  echo "[burn-schedule] target wired ($STATE_MACHINE_ARN)"

  echo
  echo "[burn-schedule] done."
  echo "  rule_arn        = $RULE_ARN"
  echo "  schedule        = $NEW_SCHEDULE"
  echo "  state           = $NEW_STATE"
  echo "  target          = $STATE_MACHINE_ARN"
  echo "  invoke_role_arn = $ROLE_ARN"
else
  echo "[burn-schedule] DRY_RUN — no changes applied. Re-run with --commit to apply."
  echo "  would-put-rule    name=$RULE_NAME schedule=$NEW_SCHEDULE state=$NEW_STATE"
  echo "  would-put-targets id=$TARGET_ID arn=$STATE_MACHINE_ARN role=$ROLE_ARN"
fi
