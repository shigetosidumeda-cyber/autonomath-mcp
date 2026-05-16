#!/usr/bin/env bash
# create_sns_topic_apne1.sh
# Create the ap-northeast-1 parallel SNS topic that Step Functions
# orchestrator (jpcite-credit-orchestrator) publishes failure
# notifications to, and update the state machine definition.
#
# Root cause (2026-05-16):
#   Step Functions tasks at arn:aws:states:::sns:publish cannot
#   publish cross-region. The orchestrator state machine lives in
#   ap-northeast-1 but the existing SNS topic
#   arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts
#   is in us-east-1. Every Catch handler that fired the SNS Publish
#   task therefore failed with SNS.InvalidParameterException, which
#   then bubbled out of the Catch chain and aborted the execution.
#
# Fix: parallel topic in ap-northeast-1 (jpcite-credit-cost-alerts-apne1)
#   for orchestrator alerts. The us-east-1 topic is preserved for
#   the billing-alarms surface so we keep both notification paths.
#
# Usage:
#   DRY_RUN=1 ./create_sns_topic_apne1.sh   # default (preview only)
#   ./create_sns_topic_apne1.sh --commit    # actually run side-effects
#
# Tags: Project=jpcite, CreditRun=2026-05, AutoStop=2026-05-29
# [lane:solo]
set -euo pipefail

REGION="ap-northeast-1"
ACCOUNT="993693061769"
TOPIC_NAME="jpcite-credit-cost-alerts-apne1"
TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:${TOPIC_NAME}"
SF_ARN="arn:aws:states:${REGION}:${ACCOUNT}:stateMachine:jpcite-credit-orchestrator"
ASL_PATH="$(cd "$(dirname "$0")/../.." && pwd)/infra/aws/step_functions/jpcite_credit_orchestrator.json"
SUBSCRIBE_EMAIL="${SUBSCRIBE_EMAIL:-sss@bookyou.net}"

DRY_RUN="${DRY_RUN:-1}"
if [[ "${1:-}" == "--commit" ]]; then
  DRY_RUN=0
fi

run() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY_RUN] $*"
  else
    echo "[COMMIT] $*"
    eval "$@"
  fi
}

echo "Region:     ${REGION}"
echo "Topic ARN:  ${TOPIC_ARN}"
echo "SF ARN:     ${SF_ARN}"
echo "ASL path:   ${ASL_PATH}"
echo "DRY_RUN:    ${DRY_RUN}"
echo

# 1) Create the parallel SNS topic in ap-northeast-1
run "aws sns create-topic \
  --region ${REGION} \
  --name ${TOPIC_NAME} \
  --tags Key=Project,Value=jpcite Key=CreditRun,Value=2026-05 Key=AutoStop,Value=2026-05-29 \
  --output text"

# 2) Subscribe operator email (will require manual confirmation
#    via inbox — subscription stays PendingConfirmation until then)
run "aws sns subscribe \
  --region ${REGION} \
  --topic-arn ${TOPIC_ARN} \
  --protocol email \
  --notification-endpoint ${SUBSCRIBE_EMAIL} \
  --output text"

# 3) Update the Step Functions state machine to use the new ASL
#    (the file is already pointed at the apne1 topic ARN; commit
#    fix(stepfn): create ap-northeast-1 SNS topic + update orchestrator ASL [lane:solo])
run "aws stepfunctions update-state-machine \
  --region ${REGION} \
  --state-machine-arn ${SF_ARN} \
  --definition file://${ASL_PATH} \
  --output text"

# 4) Smoke retry: start an execution and tail its status
RUN_NAME="smoke-$(date -u +%Y%m%dT%H%M%SZ)"
run "aws stepfunctions start-execution \
  --region ${REGION} \
  --state-machine-arn ${SF_ARN} \
  --name ${RUN_NAME} \
  --input '{\"trigger\": \"sns-apne1-fix-smoke\"}' \
  --output text"

echo
echo "After confirmation in inbox, verify with:"
echo "  aws sns list-subscriptions-by-topic --region ${REGION} --topic-arn ${TOPIC_ARN}"
echo "  aws stepfunctions describe-execution --region ${REGION} \\"
echo "    --execution-arn arn:aws:states:${REGION}:${ACCOUNT}:execution:jpcite-credit-orchestrator:${RUN_NAME}"
