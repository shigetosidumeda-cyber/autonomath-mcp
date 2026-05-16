#!/usr/bin/env bash
# Emergency stop drill for jpcite credit run
# Disables all jpcite-credit-* queues, cancels all RUNNABLE/SUBMITTED jobs, terminates all RUNNING jobs.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
LIVE="${JPCITE_STOP_DRILL_LIVE:-false}"

echo "[stop-drill] mode: $([ "$LIVE" = "true" ] && echo LIVE || echo DRY_RUN)"

# List queues
QUEUES=$(aws batch describe-job-queues --region "$REGION" --query 'jobQueues[?starts_with(jobQueueName,`jpcite-credit-`)].jobQueueName' --output text)
echo "[stop-drill] queues found: $QUEUES"

for Q in $QUEUES; do
  echo "[stop-drill] queue: $Q"
  if [ "$LIVE" = "true" ]; then
    aws batch update-job-queue --region "$REGION" --job-queue "$Q" --state DISABLED >/dev/null
  fi
  for STATUS in SUBMITTED PENDING RUNNABLE; do
    JOBS=$(aws batch list-jobs --region "$REGION" --job-queue "$Q" --job-status "$STATUS" --query 'jobSummaryList[*].jobId' --output text 2>/dev/null || true)
    for JID in $JOBS; do
      if [ "$LIVE" = "true" ]; then
        aws batch cancel-job --region "$REGION" --job-id "$JID" --reason "stop-drill cancel" >/dev/null && echo "  cancelled $JID ($STATUS)"
      else
        echo "  DRY_RUN would cancel $JID ($STATUS)"
      fi
    done
  done
  RUNNING=$(aws batch list-jobs --region "$REGION" --job-queue "$Q" --job-status RUNNING --query 'jobSummaryList[*].jobId' --output text 2>/dev/null || true)
  for JID in $RUNNING; do
    if [ "$LIVE" = "true" ]; then
      aws batch terminate-job --region "$REGION" --job-id "$JID" --reason "stop-drill terminate" >/dev/null && echo "  terminated $JID (RUNNING)"
    else
      echo "  DRY_RUN would terminate $JID (RUNNING)"
    fi
  done
done

# Update CE to disabled too
CES=$(aws batch describe-compute-environments --region "$REGION" --query 'computeEnvironments[?starts_with(computeEnvironmentName,`jpcite-credit-`)].computeEnvironmentName' --output text)
for CE in $CES; do
  echo "[stop-drill] CE: $CE"
  if [ "$LIVE" = "true" ]; then
    aws batch update-compute-environment --region "$REGION" --compute-environment "$CE" --state DISABLED >/dev/null
  fi
done

echo "[stop-drill] done."
