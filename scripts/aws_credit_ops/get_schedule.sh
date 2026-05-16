#!/usr/bin/env bash
#
# get_schedule.sh — probe EventBridge for a schedule across both namespaces
#
# AWS exposes two completely separate schedule namespaces:
#   1. EventBridge Rules (legacy `events` API)        — `aws events list-rules`
#   2. EventBridge Scheduler (new `scheduler` API)    — `aws scheduler list-schedules`
#
# `aws scheduler get-schedule --name X` returns ResourceNotFoundException if X
# is registered in Rules instead, even though the schedule exists and fires.
# Always probe BOTH namespaces before concluding a schedule is missing.
#
# See memory: feedback_aws_eventbridge_dual_namespace.md
#
# Usage:
#   scripts/aws_credit_ops/get_schedule.sh <schedule-name> [--region REGION] [--profile PROFILE]
#
# Defaults:
#   region  = ap-northeast-1
#   profile = bookyou-recovery
#
# Exit codes:
#   0 — found in at least one namespace
#   1 — usage error
#   2 — not found in either namespace

set -euo pipefail

SCHEDULE_NAME="${1:-}"
REGION="ap-northeast-1"
PROFILE="bookyou-recovery"

shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) REGION="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,30p' "$0"
      exit 0
      ;;
    *)
      echo "[get_schedule] unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${SCHEDULE_NAME}" ]]; then
  echo "[get_schedule] usage: $0 <schedule-name> [--region REGION] [--profile PROFILE]" >&2
  exit 1
fi

echo "[get_schedule] probing namespace=Rules (events API) for name=${SCHEDULE_NAME} region=${REGION} profile=${PROFILE}"
RULES_OUT=$(aws events list-rules \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --name-prefix "${SCHEDULE_NAME}" \
  --output json 2>&1 || true)

RULES_HIT=$(echo "${RULES_OUT}" | python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read())
    rules = data.get('Rules', [])
    match = [r for r in rules if r.get('Name') == '${SCHEDULE_NAME}']
    if match:
        r = match[0]
        print(f\"FOUND state={r.get('State')} expr={r.get('ScheduleExpression')} arn={r.get('Arn')}\")
    else:
        print('NOT_FOUND')
except Exception as e:
    print(f'PARSE_ERROR: {e}')
" 2>&1)

echo "[get_schedule]   Rules result: ${RULES_HIT}"

echo "[get_schedule] probing namespace=Scheduler (scheduler API) for name=${SCHEDULE_NAME} region=${REGION} profile=${PROFILE}"
SCHED_OUT=$(aws scheduler get-schedule \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --name "${SCHEDULE_NAME}" \
  --output json 2>&1 || true)

if echo "${SCHED_OUT}" | grep -q "ResourceNotFoundException"; then
  SCHED_HIT="NOT_FOUND"
elif echo "${SCHED_OUT}" | grep -q "\"Arn\""; then
  SCHED_HIT=$(echo "${SCHED_OUT}" | python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read())
    print(f\"FOUND state={data.get('State')} expr={data.get('ScheduleExpression')} arn={data.get('Arn')}\")
except Exception as e:
    print(f'PARSE_ERROR: {e}')
")
else
  SCHED_HIT="ERROR: ${SCHED_OUT}"
fi

echo "[get_schedule]   Scheduler result: ${SCHED_HIT}"

# Determine overall outcome
if [[ "${RULES_HIT}" == FOUND* ]] || [[ "${SCHED_HIT}" == FOUND* ]]; then
  echo "[get_schedule] OK — schedule '${SCHEDULE_NAME}' exists in at least one namespace"
  exit 0
fi

echo "[get_schedule] FAIL — schedule '${SCHEDULE_NAME}' not found in either namespace" >&2
exit 2
