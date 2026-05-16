#!/usr/bin/env bash
# Submit the 24-shard full-scale 制度 lineage packet render to AWS Batch.
#
# 11,601 searchable programs (tier S/A/B/C, excluded=0) sliced into 24
# shards of 500 each (last shard 601). Each shard runs as one AWS Batch
# Fargate Spot job (4 vCPU / 8 GB) and uploads <program_unified_id>.json
# packets to s3://jpcite-credit-993693061769-202605-derived/program_lineage/.
#
# Usage:
#   scripts/aws_credit_ops/submit_program_lineage_batches.sh [--commit] [--only-shard N] [--spacing SECONDS]
#
# Modes:
#   DRY_RUN=true (DEFAULT)   preview every shard submit-job invocation
#   DRY_RUN=false + --commit actually submits 24 Batch jobs
#
# Per the dual-CLI lane convention this script writes [lane:solo] and
# defaults to DRY_RUN. live_aws_commands_allowed must be true on the
# preflight scorecard before --commit is honoured; the script does NOT
# enforce that (the scorecard runner does), but the operator MUST
# verify the gate before flipping --commit.
#
# Output:
#   stdout: one [submit] line per shard (job_name, job_id when LIVE).
#   stderr: warnings + AWS CLI errors.
#
# Shards:
#   batch 0  : [0, 500)        500 programs
#   batch 1  : [500, 1000)     500 programs
#   ...
#   batch 22 : [11000, 11500)  500 programs
#   batch 23 : [11500, 11601)  101 programs (final remainder)
#
# Cost: 24 × $0.05 ≈ $1.20 Fargate Spot + Athena bytes-scan estimate (no
# Athena query is issued from the render — pure SQLite + S3 PUT).
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"
DRY_RUN="${DRY_RUN:-true}"

JOB_DEF="${JOB_DEF:-jpcite-program-lineage-render}"
QUEUE="${QUEUE:-jpcite-credit-fargate-spot-short-queue}"
LOG_GROUP="${LOG_GROUP:-/aws/batch/jpcite-credit-2026-05}"
AUTO_STOP="${AUTO_STOP:-2026-05-29}"
SPACING="${SPACING:-5}"

# 24-shard plan: 23 full shards of 500 + 1 remainder of 101 (= 11,601).
TOTAL_PROGRAMS=11601
SHARD_SIZE=500
ONLY_SHARD=""
COMMIT_REQUESTED=false

usage() {
  cat <<'USAGE'
usage: submit_program_lineage_batches.sh [--commit] [--only-shard N] [--spacing N]

Submit the 24-shard 制度 lineage packet render to AWS Batch Fargate Spot.

Flags:
  --commit         actually call aws batch submit-job (default: dry-run)
  --only-shard N   submit only shard N (0..23); useful for the smoke pass
  --spacing N      sleep N seconds between submits (default 5)

env:
  DRY_RUN=true     preview without submitting (default true)
  AWS_PROFILE      default: bookyou-recovery
  REGION           default: ap-northeast-1
  QUEUE            default: jpcite-credit-fargate-spot-short-queue
  JOB_DEF          default: jpcite-program-lineage-render
USAGE
  exit 64
}

for arg in "$@"; do
  case "$arg" in
    --commit) COMMIT_REQUESTED=true ;;
    --only-shard) shift; ONLY_SHARD="${1:-}" ;;
    --only-shard=*) ONLY_SHARD="${arg#--only-shard=}" ;;
    --spacing) shift; SPACING="${1:-5}" ;;
    --spacing=*) SPACING="${arg#--spacing=}" ;;
    -h|--help) usage ;;
  esac
done

if [ "$COMMIT_REQUESTED" = "true" ]; then
  DRY_RUN="false"
fi

# ---- shard table ----
declare -a SHARDS_START
declare -a SHARDS_END
for ((i=0; i<23; i++)); do
  SHARDS_START[$i]=$((i * SHARD_SIZE))
  SHARDS_END[$i]=$(((i + 1) * SHARD_SIZE))
done
SHARDS_START[23]=11500
SHARDS_END[23]=$TOTAL_PROGRAMS

NUM_SHARDS=${#SHARDS_START[@]}

echo "[submit_program_lineage] mode: $([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE)"
echo "[submit_program_lineage] job_def: $JOB_DEF  queue: $QUEUE"
echo "[submit_program_lineage] shards: $NUM_SHARDS  total_programs: $TOTAL_PROGRAMS  spacing: ${SPACING}s"
if [ -n "$ONLY_SHARD" ]; then
  echo "[submit_program_lineage] only_shard: $ONLY_SHARD"
fi
echo ""

submit_shard() {
  local IDX="$1"
  local START="${SHARDS_START[$IDX]}"
  local END="${SHARDS_END[$IDX]}"
  local ROWS=$((END - START))
  local TS
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  local SHARD_ID
  SHARD_ID="$(printf 'shard%02d' "$IDX")"
  local JOB_NAME="jpcite-program-lineage-${SHARD_ID}-${TS}"
  local PARAMS="batch_start=${START},batch_end=${END}"
  local TAGS_JSON
  TAGS_JSON="{\"Project\":\"jpcite\",\"CreditRun\":\"2026-05\",\"Workload\":\"program-lineage\",\"Shard\":\"${SHARD_ID}\",\"AutoStop\":\"${AUTO_STOP}\"}"

  printf '[shard %02d] %s rows=%d job_name=%s\n' "$IDX" "$PARAMS" "$ROWS" "$JOB_NAME"

  if [ "$DRY_RUN" = "true" ]; then
    return 0
  fi

  aws batch submit-job \
    --region "$REGION" \
    --job-name "$JOB_NAME" \
    --job-queue "$QUEUE" \
    --job-definition "$JOB_DEF" \
    --parameters "$PARAMS" \
    --tags "$TAGS_JSON" \
    --output text \
    --query 'jobId' || {
      echo "[submit_program_lineage] WARN: shard $IDX submit failed" >&2
      return 1
    }
}

if [ -n "$ONLY_SHARD" ]; then
  if ! [[ "$ONLY_SHARD" =~ ^[0-9]+$ ]] || [ "$ONLY_SHARD" -ge "$NUM_SHARDS" ]; then
    echo "[submit_program_lineage] ERROR: --only-shard must be 0..$((NUM_SHARDS-1))" >&2
    exit 64
  fi
  submit_shard "$ONLY_SHARD"
  echo ""
  echo "[submit_program_lineage] done (only_shard=$ONLY_SHARD)."
  exit 0
fi

for ((idx=0; idx<NUM_SHARDS; idx++)); do
  submit_shard "$idx"
  if [ "$idx" -lt "$((NUM_SHARDS - 1))" ]; then
    sleep "$SPACING"
  fi
done

echo ""
echo "[submit_program_lineage] done — $NUM_SHARDS shards submitted (mode: $([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE))."
echo "[submit_program_lineage] hint: scripts/aws_credit_ops/monitor_jobs.sh"
echo "[submit_program_lineage] s3 verify: aws s3 ls s3://jpcite-credit-993693061769-202605-derived/program_lineage/ --recursive | wc -l   # expect 11601"
