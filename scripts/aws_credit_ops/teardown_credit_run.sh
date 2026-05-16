#!/usr/bin/env bash
# Final teardown for jpcite-credit-* AWS Batch credit run.
#
# Each step previews under DRY_RUN (default), executes only when JPCITE_TEARDOWN_LIVE_TOKEN
# is set to the literal string "I-AM-TEARING-DOWN-jpcite-credit-2026-05".
#
# Steps (each independently dry-runnable via env):
#   1. STEP_DISABLE_QUEUES   disable jpcite-credit-* job queues
#   2. STEP_DRAIN_JOBS       cancel SUBMITTED/PENDING/RUNNABLE + terminate RUNNING
#   3. STEP_DELETE_QUEUES    delete the (disabled, drained) job queues
#   4. STEP_DELETE_JOBDEFS   deregister jpcite-crawl revisions
#   5. STEP_DELETE_CES       disable + delete jpcite-credit-* compute environments
#   6. STEP_DELETE_LOGS      delete CloudWatch log group /aws/batch/jpcite-credit-2026-05
#   7. STEP_DELETE_BUCKETS   delete jpcite-credit-*-202605-raw + -reports (only when JPCITE_TEARDOWN_DELETE_BUCKETS=1)
#
# Each STEP_* defaults to "1" (enabled). Set to "0" to skip individual steps.
#
# This script is read-only by default. Live mode requires the explicit token AND DRY_RUN=false.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

DRY_RUN="${DRY_RUN:-true}"
LIVE_TOKEN_EXPECTED="I-AM-TEARING-DOWN-jpcite-credit-2026-05"
LIVE_TOKEN="${JPCITE_TEARDOWN_LIVE_TOKEN:-}"

STEP_DISABLE_QUEUES="${STEP_DISABLE_QUEUES:-1}"
STEP_DRAIN_JOBS="${STEP_DRAIN_JOBS:-1}"
STEP_DELETE_QUEUES="${STEP_DELETE_QUEUES:-1}"
STEP_DELETE_JOBDEFS="${STEP_DELETE_JOBDEFS:-1}"
STEP_DELETE_CES="${STEP_DELETE_CES:-1}"
STEP_DELETE_LOGS="${STEP_DELETE_LOGS:-1}"
STEP_DELETE_BUCKETS="${STEP_DELETE_BUCKETS:-0}"  # off by default (data loss)

LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
JOB_DEF_NAME="${JOB_DEF_NAME:-jpcite-crawl}"
BUCKETS_TO_DELETE=(
  "jpcite-credit-993693061769-202605-raw"
  "jpcite-credit-993693061769-202605-reports"
)

# Mode gate
LIVE=false
if [ "$DRY_RUN" = "false" ]; then
  if [ "$LIVE_TOKEN" = "$LIVE_TOKEN_EXPECTED" ]; then
    LIVE=true
  else
    echo "[teardown] ERROR: DRY_RUN=false requires JPCITE_TEARDOWN_LIVE_TOKEN=$LIVE_TOKEN_EXPECTED" >&2
    echo "[teardown] aborting; forcing DRY_RUN preview only." >&2
    DRY_RUN=true
  fi
fi
echo "[teardown] mode: $([ "$LIVE" = "true" ] && echo LIVE || echo DRY_RUN)"
echo "[teardown] region: $REGION  profile: $AWS_PROFILE"

run() {
  # run "<label>" <aws cli args ...>
  local label="$1"; shift
  if [ "$LIVE" = "true" ]; then
    echo "  LIVE: $label"
    "$@" || echo "  warn: command failed for: $label"
  else
    echo "  DRY_RUN would: $label"
  fi
}

# ----- step 1: disable queues -----
if [ "$STEP_DISABLE_QUEUES" = "1" ]; then
  echo ""
  echo "[teardown] step 1/7: disable jpcite-credit-* queues"
  QUEUES=$(aws batch describe-job-queues --region "$REGION" \
    --query 'jobQueues[?starts_with(jobQueueName,`jpcite-credit-`)].jobQueueName' \
    --output text 2>/dev/null || true)
  for Q in $QUEUES; do
    run "update-job-queue --state DISABLED $Q" \
      aws batch update-job-queue --region "$REGION" --job-queue "$Q" --state DISABLED
  done
else
  echo "[teardown] step 1/7: SKIP (STEP_DISABLE_QUEUES=0)"
fi

# ----- step 2: drain jobs -----
if [ "$STEP_DRAIN_JOBS" = "1" ]; then
  echo ""
  echo "[teardown] step 2/7: drain SUBMITTED/PENDING/RUNNABLE/RUNNING jobs"
  QUEUES=$(aws batch describe-job-queues --region "$REGION" \
    --query 'jobQueues[?starts_with(jobQueueName,`jpcite-credit-`)].jobQueueName' \
    --output text 2>/dev/null || true)
  for Q in $QUEUES; do
    for STATUS in SUBMITTED PENDING RUNNABLE STARTING; do
      JOBS=$(aws batch list-jobs --region "$REGION" --job-queue "$Q" --job-status "$STATUS" \
        --query 'jobSummaryList[*].jobId' --output text 2>/dev/null || true)
      for JID in $JOBS; do
        run "cancel-job $JID ($STATUS in $Q)" \
          aws batch cancel-job --region "$REGION" --job-id "$JID" --reason "teardown cancel"
      done
    done
    RUNNING=$(aws batch list-jobs --region "$REGION" --job-queue "$Q" --job-status RUNNING \
      --query 'jobSummaryList[*].jobId' --output text 2>/dev/null || true)
    for JID in $RUNNING; do
      run "terminate-job $JID (RUNNING in $Q)" \
        aws batch terminate-job --region "$REGION" --job-id "$JID" --reason "teardown terminate"
    done
  done
else
  echo "[teardown] step 2/7: SKIP (STEP_DRAIN_JOBS=0)"
fi

# ----- step 3: delete queues -----
if [ "$STEP_DELETE_QUEUES" = "1" ]; then
  echo ""
  echo "[teardown] step 3/7: delete jpcite-credit-* queues"
  QUEUES=$(aws batch describe-job-queues --region "$REGION" \
    --query 'jobQueues[?starts_with(jobQueueName,`jpcite-credit-`)].jobQueueName' \
    --output text 2>/dev/null || true)
  for Q in $QUEUES; do
    run "delete-job-queue $Q" \
      aws batch delete-job-queue --region "$REGION" --job-queue "$Q"
  done
else
  echo "[teardown] step 3/7: SKIP (STEP_DELETE_QUEUES=0)"
fi

# ----- step 4: deregister job defs -----
if [ "$STEP_DELETE_JOBDEFS" = "1" ]; then
  echo ""
  echo "[teardown] step 4/7: deregister $JOB_DEF_NAME revisions"
  REVS=$(aws batch describe-job-definitions --region "$REGION" \
    --job-definition-name "$JOB_DEF_NAME" \
    --query 'jobDefinitions[?status==`ACTIVE`].[jobDefinitionName,revision]' \
    --output text 2>/dev/null || true)
  while read -r NAME REV; do
    [ -z "${NAME:-}" ] && continue
    run "deregister-job-definition $NAME:$REV" \
      aws batch deregister-job-definition --region "$REGION" --job-definition "$NAME:$REV"
  done <<<"$REVS"
else
  echo "[teardown] step 4/7: SKIP (STEP_DELETE_JOBDEFS=0)"
fi

# ----- step 5: delete CEs -----
if [ "$STEP_DELETE_CES" = "1" ]; then
  echo ""
  echo "[teardown] step 5/7: disable + delete jpcite-credit-* compute environments"
  CES=$(aws batch describe-compute-environments --region "$REGION" \
    --query 'computeEnvironments[?starts_with(computeEnvironmentName,`jpcite-credit-`)].computeEnvironmentName' \
    --output text 2>/dev/null || true)
  for CE in $CES; do
    run "update-compute-environment --state DISABLED $CE" \
      aws batch update-compute-environment --region "$REGION" --compute-environment "$CE" --state DISABLED
    run "delete-compute-environment $CE" \
      aws batch delete-compute-environment --region "$REGION" --compute-environment "$CE"
  done
else
  echo "[teardown] step 5/7: SKIP (STEP_DELETE_CES=0)"
fi

# ----- step 6: delete log group -----
if [ "$STEP_DELETE_LOGS" = "1" ]; then
  echo ""
  echo "[teardown] step 6/7: delete log group $LOG_GROUP"
  if aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "$LOG_GROUP" \
       --query "logGroups[?logGroupName==\`$LOG_GROUP\`].logGroupName" --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
    run "delete-log-group $LOG_GROUP" \
      aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP"
  else
    echo "  (log group not found: $LOG_GROUP)"
  fi
else
  echo "[teardown] step 6/7: SKIP (STEP_DELETE_LOGS=0)"
fi

# ----- step 7: delete buckets -----
if [ "$STEP_DELETE_BUCKETS" = "1" ]; then
  echo ""
  echo "[teardown] step 7/7: delete S3 buckets"
  echo "  WARNING: data loss — only proceeds when JPCITE_TEARDOWN_DELETE_BUCKETS=1 AND DRY_RUN=false."
  if [ "${JPCITE_TEARDOWN_DELETE_BUCKETS:-0}" != "1" ]; then
    echo "  JPCITE_TEARDOWN_DELETE_BUCKETS != 1; previewing only."
  fi
  for B in "${BUCKETS_TO_DELETE[@]}"; do
    if aws s3api head-bucket --bucket "$B" --region "$REGION" >/dev/null 2>&1; then
      if [ "$LIVE" = "true" ] && [ "${JPCITE_TEARDOWN_DELETE_BUCKETS:-0}" = "1" ]; then
        echo "  LIVE: rm s3://$B (recursive) then rb"
        aws s3 rm "s3://$B" --recursive --region "$REGION" || echo "  warn: rm failed for $B"
        aws s3api delete-bucket --bucket "$B" --region "$REGION" || echo "  warn: delete-bucket failed for $B"
      else
        echo "  DRY_RUN would: rm s3://$B (recursive) then delete-bucket"
      fi
    else
      echo "  (bucket not found: $B)"
    fi
  done
else
  echo "[teardown] step 7/7: SKIP (STEP_DELETE_BUCKETS=0)"
fi

echo ""
echo "[teardown] done. mode: $([ "$LIVE" = "true" ] && echo LIVE || echo DRY_RUN)"
