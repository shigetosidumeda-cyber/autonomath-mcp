#!/usr/bin/env bash
# Submit all 167 jpcite-houjin360-render shards (1,000 corporates each) to AWS Batch.
#
# Cohort #1 of the prebuilt deliverable packet catalog: pre-generates
# `company_public_baseline` JPCIR packets for every corporate_entity in
# autonomath.db (166,969 rows). Each shard claims rows [batch_start, batch_end)
# via the `--batch-start` / `--batch-end` parameters wired through the job def.
#
# Usage:
#   scripts/aws_credit_ops/submit_houjin360_batches.sh           # DRY_RUN (default)
#   scripts/aws_credit_ops/submit_houjin360_batches.sh --commit  # actually submit
#   scripts/aws_credit_ops/submit_houjin360_batches.sh --commit --smoke  # only 1 shard (0-1000)
#   scripts/aws_credit_ops/submit_houjin360_batches.sh --commit --from N --to M  # custom range
#
# Job name pattern: `jpcite-houjin360-render-<batch-start>-<batch-end>`
# Tags: Project=jpcite, CreditRun=2026-05, Workload=houjin360, AutoStop=2026-05-29
#
# 167 batches = ceil(166969 / 1000). Last shard covers [166000, 166969).
#
# DRY_RUN default. --commit is the dual of DRY_RUN=1 — without it, the script
# previews every shard it would submit and exits cleanly.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

JOB_DEF="${JOB_DEF:-jpcite-houjin360-render}"
QUEUE="${QUEUE:-jpcite-credit-fargate-spot-short-queue}"
LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
AUTO_STOP="${AUTO_STOP:-2026-05-29}"
TOTAL_CORPORATES="${TOTAL_CORPORATES:-166969}"
BATCH_SIZE="${BATCH_SIZE:-1000}"
SUBMISSION_DELAY_SEC="${SUBMISSION_DELAY_SEC:-0.05}"

COMMIT=false
SMOKE=false
FROM_OVERRIDE=""
TO_OVERRIDE=""

usage() {
  cat <<USAGE
usage: $0 [--commit] [--smoke] [--from N] [--to M]
  --commit:     lift DRY_RUN, actually submit jobs to Batch
  --smoke:      submit only shard [0, 1000) (1 job, ~5 min runtime, ~\$0.05)
  --from N:     start shard index N (0-indexed, default 0)
  --to M:       stop at shard index M (exclusive, default 167)
env:
  AWS_PROFILE          default: bookyou-recovery
  REGION               default: ap-northeast-1
  TOTAL_CORPORATES     default: 166969
  BATCH_SIZE           default: 1000
  SUBMISSION_DELAY_SEC default: 0.05 (sleep between submits, throttle)
USAGE
  exit 64
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --commit) COMMIT=true ;;
    --smoke) SMOKE=true ;;
    --from) shift; FROM_OVERRIDE="$1" ;;
    --to) shift; TO_OVERRIDE="$1" ;;
    -h|--help) usage ;;
    *) echo "[submit_houjin360] unknown arg: $1" >&2; usage ;;
  esac
  shift
done

NUM_SHARDS=$(( (TOTAL_CORPORATES + BATCH_SIZE - 1) / BATCH_SIZE ))
SHARD_FROM=${FROM_OVERRIDE:-0}
SHARD_TO=${TO_OVERRIDE:-$NUM_SHARDS}

if [ "$SMOKE" = "true" ]; then
  SHARD_FROM=0
  SHARD_TO=1
fi

if [ "$SHARD_FROM" -lt 0 ] || [ "$SHARD_TO" -gt "$NUM_SHARDS" ] || [ "$SHARD_FROM" -ge "$SHARD_TO" ]; then
  echo "[submit_houjin360] ERROR: invalid range from=$SHARD_FROM to=$SHARD_TO (num_shards=$NUM_SHARDS)" >&2
  exit 64
fi

echo "[submit_houjin360] mode: $([ "$COMMIT" = "true" ] && echo LIVE || echo DRY_RUN)"
echo "[submit_houjin360] total_corporates : $TOTAL_CORPORATES"
echo "[submit_houjin360] batch_size       : $BATCH_SIZE"
echo "[submit_houjin360] num_shards       : $NUM_SHARDS"
echo "[submit_houjin360] shard range      : [$SHARD_FROM, $SHARD_TO)"
echo "[submit_houjin360] job_definition   : $JOB_DEF"
echo "[submit_houjin360] queue            : $QUEUE"
echo "[submit_houjin360] tags             : Project=jpcite,CreditRun=2026-05,Workload=houjin360,AutoStop=$AUTO_STOP"
echo "[submit_houjin360] log_group        : $LOG_GROUP"
echo ""

TAGS_JSON=$(python3 -c "import json; print(json.dumps({'Project':'jpcite','CreditRun':'2026-05','Workload':'houjin360','AutoStop':'$AUTO_STOP'}))")

SUBMITTED=0
JOB_IDS_SAMPLE=()
FAILED=0
LEDGER_DIR="${LEDGER_DIR:-out/houjin_360_submissions}"
mkdir -p "$LEDGER_DIR"
LEDGER_FILE="$LEDGER_DIR/submissions_$(date -u +%Y%m%dT%H%M%SZ).jsonl"

for ((idx=SHARD_FROM; idx<SHARD_TO; idx++)); do
  BATCH_START=$((idx * BATCH_SIZE))
  BATCH_END=$(((idx + 1) * BATCH_SIZE))
  if [ "$BATCH_END" -gt "$TOTAL_CORPORATES" ]; then
    BATCH_END="$TOTAL_CORPORATES"
  fi
  JOB_NAME="jpcite-houjin360-render-${BATCH_START}-${BATCH_END}"
  PARAMS="batch_start=${BATCH_START},batch_end=${BATCH_END}"

  if [ "$COMMIT" != "true" ]; then
    echo "[submit_houjin360][DRY] would submit $JOB_NAME (params: $PARAMS)"
    SUBMITTED=$((SUBMITTED + 1))
    continue
  fi

  JOB_OUT=$(aws batch submit-job \
    --region "$REGION" \
    --job-name "$JOB_NAME" \
    --job-queue "$QUEUE" \
    --job-definition "$JOB_DEF" \
    --parameters "$PARAMS" \
    --tags "$TAGS_JSON" \
    --output json 2>&1) || {
    echo "[submit_houjin360] FAIL submit $JOB_NAME: $JOB_OUT" >&2
    FAILED=$((FAILED + 1))
    echo "{\"job_name\":\"$JOB_NAME\",\"status\":\"submit_failed\",\"error\":\"$(echo "$JOB_OUT" | head -c 200 | tr '"' '\\\"')\"}" >> "$LEDGER_FILE"
    continue
  }
  JOB_BATCH_ID=$(echo "$JOB_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('jobId',''))")
  echo "[submit_houjin360] SUBMITTED $JOB_NAME -> jobId=$JOB_BATCH_ID"
  echo "{\"job_name\":\"$JOB_NAME\",\"job_id\":\"$JOB_BATCH_ID\",\"batch_start\":$BATCH_START,\"batch_end\":$BATCH_END,\"submitted_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" >> "$LEDGER_FILE"
  SUBMITTED=$((SUBMITTED + 1))
  if [ "${#JOB_IDS_SAMPLE[@]}" -lt 5 ]; then
    JOB_IDS_SAMPLE+=("$JOB_BATCH_ID")
  fi
  sleep "$SUBMISSION_DELAY_SEC"
done

echo ""
echo "[submit_houjin360] summary:"
echo "[submit_houjin360]   submitted = $SUBMITTED"
echo "[submit_houjin360]   failed    = $FAILED"
echo "[submit_houjin360]   ledger    = $LEDGER_FILE"
if [ "${#JOB_IDS_SAMPLE[@]}" -gt 0 ]; then
  echo "[submit_houjin360]   job_id sample (first ${#JOB_IDS_SAMPLE[@]}):"
  for jid in "${JOB_IDS_SAMPLE[@]}"; do
    echo "[submit_houjin360]     - $jid"
  done
fi
echo ""
echo "[submit_houjin360] verify with: scripts/aws_credit_ops/monitor_jobs.sh"
echo "[submit_houjin360] aggregate run ledger: scripts/aws_credit_ops/aggregate_run_ledger.py"
