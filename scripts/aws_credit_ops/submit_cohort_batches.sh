#!/usr/bin/env bash
# Render the 47×20×4×12×5 = 225,600 acceptance-probability cohort grid in
# parallel shards. PUTs JSON packets to S3 under acceptance_probability/.
#
# Shard contract:
#   batch 0..223  -> width 1000 each (224 batches × 1000 = 224000 cells)
#   batch 224     -> width 1600 (indices [224000, 225600))
#   total batches = 225, total cells = 225,600
#
# Two execution backends are wired:
#
#   1. Local parallel (default; --backend=local)
#      Spawns N python workers locally; each worker takes one batch from
#      the queue and runs generate_acceptance_probability_packets.py with
#      the deterministic --batch-start/--batch-end slice. Each worker
#      uploads directly to S3 with the bookyou-recovery profile. Concurrency
#      is bounded by --concurrency (default 8). This is the production
#      path while the jpcite-crawler image lacks the cohort renderer in
#      /opt/jpcite/scripts (the Batch job def in
#      infra/aws/batch/jpcite_cohort_render_job_definition.json is the
#      authoritative spec for the future image-baked path; revision 2 is
#      already registered with the correct IAM roles).
#
#   2. AWS Batch (--backend=batch)
#      Calls aws batch submit-job once per shard against
#      jpcite-cohort-render:2 (Fargate, 4 vCPU / 8 GB). Requires the image
#      to ship the cohort renderer + the 9.7 GB autonomath.db on the
#      container filesystem (or a separate fetch step). Use this only
#      after a Batch-image rebuild that bakes
#      scripts/aws_credit_ops/generate_acceptance_probability_packets.py
#      under /opt/jpcite/scripts/aws_credit_ops/.
#
# Usage:
#   scripts/aws_credit_ops/submit_cohort_batches.sh [--backend local|batch]
#                                                   [--smoke]
#                                                   [--start N] [--end N]
#                                                   [--concurrency N]
#                                                   [--dry-run]
#
#   --smoke            run only batch 0 (indices [0, 1000)).
#   --start N          first batch index to submit (default 0).
#   --end N            one past the last batch index (default 225).
#   --concurrency N    parallel workers for local backend (default 8).
#   --backend B        local | batch (default: local).
#   --dry-run          preview without spawning workers / submitting jobs.
#
# Environment overrides:
#   AWS_PROFILE   (default: bookyou-recovery)
#   REGION        (default: ap-northeast-1)
#   QUEUE         (default: jpcite-credit-fargate-spot-short-queue)
#   JOB_DEF       (default: jpcite-cohort-render)
#   S3_PREFIX     (default: s3://jpcite-credit-993693061769-202605-derived/acceptance_probability/)
#   RUN_PREFIX    (default: full_$(date -u +%Y%m%d))
#   DB_PATH       (default: $REPO/autonomath.db)
#   JPINTEL_DB    (default: $REPO/data/jpintel.db)
#   AUTO_STOP     (default: 2026-05-29)
#
# Cost:
#   * local backend  : $0 (compute on operator workstation, S3 PUT only).
#   * batch backend  : 225 Fargate shards × ~$0.05 = ~$11.25 + Athena.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

QUEUE="${QUEUE:-jpcite-credit-fargate-spot-short-queue}"
JOB_DEF="${JOB_DEF:-jpcite-cohort-render}"
S3_PREFIX="${S3_PREFIX:-s3://jpcite-credit-993693061769-202605-derived/acceptance_probability/}"
RUN_PREFIX="${RUN_PREFIX:-full_$(date -u +%Y%m%d)}"
DB_PATH="${DB_PATH:-$REPO/autonomath.db}"
JPINTEL_DB="${JPINTEL_DB:-$REPO/data/jpintel.db}"
AUTO_STOP="${AUTO_STOP:-2026-05-29}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"

GRID_TOTAL=225600
SHARD_WIDTH=1000
TOTAL_BATCHES=225
TAIL_END=$GRID_TOTAL

DRY_RUN=false
START=0
END=$TOTAL_BATCHES
CONCURRENCY=8
BACKEND="local"

usage() {
  sed -n '2,55p' "$0"
  exit 64
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --smoke) START=0; END=1 ;;
    --start) shift; START="$1" ;;
    --end) shift; END="$1" ;;
    --concurrency) shift; CONCURRENCY="$1" ;;
    --backend) shift; BACKEND="$1" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage ;;
    *) echo "[submit_cohort_batches] unknown arg: $1" >&2; usage ;;
  esac
  shift
done

if ! [[ "$START" =~ ^[0-9]+$ ]] || ! [[ "$END" =~ ^[0-9]+$ ]] || ! [[ "$CONCURRENCY" =~ ^[0-9]+$ ]]; then
  echo "[submit_cohort_batches] --start, --end, --concurrency must be integers" >&2
  exit 64
fi
if [ "$START" -lt 0 ] || [ "$END" -gt "$TOTAL_BATCHES" ] || [ "$START" -ge "$END" ]; then
  echo "[submit_cohort_batches] invalid range [$START, $END) — must satisfy 0 <= start < end <= $TOTAL_BATCHES" >&2
  exit 64
fi
case "$BACKEND" in
  local|batch) ;;
  *) echo "[submit_cohort_batches] --backend must be local or batch" >&2; exit 64 ;;
esac

echo "[submit_cohort_batches] mode:       $([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE)"
echo "[submit_cohort_batches] backend:    $BACKEND"
echo "[submit_cohort_batches] s3_prefix:  $S3_PREFIX"
echo "[submit_cohort_batches] run_prefix: $RUN_PREFIX"
echo "[submit_cohort_batches] range:      batches [$START, $END) (total $((END - START)) shards)"
if [ "$BACKEND" = "local" ]; then
  echo "[submit_cohort_batches] python:     $PYTHON"
  echo "[submit_cohort_batches] db:         $DB_PATH"
  echo "[submit_cohort_batches] jpintel_db: $JPINTEL_DB"
  echo "[submit_cohort_batches] concurrency: $CONCURRENCY"
else
  echo "[submit_cohort_batches] queue:      $QUEUE"
  echo "[submit_cohort_batches] job_def:    $JOB_DEF"
fi
echo ""

LOG_DIR="$REPO/out/logs/cohort_render_${RUN_PREFIX}"
mkdir -p "$LOG_DIR"

# ---- helper: compute (start, end) for a batch index --------------------
batch_range() {
  local i="$1"
  local bs=$((i * SHARD_WIDTH))
  local be
  if [ "$i" -eq $((TOTAL_BATCHES - 1)) ]; then
    be=$TAIL_END
  else
    be=$((bs + SHARD_WIDTH))
  fi
  echo "$bs $be"
}

# ---- backend: batch ----------------------------------------------------
submit_batch_shard() {
  local i="$1"
  read -r bs be < <(batch_range "$i")
  local bid; bid=$(printf "%03d" "$i")
  local job_name; job_name="jpcite-cohort-render-${bid}-$(date -u +%Y%m%dT%H%M%SZ)"
  local run_id="${RUN_PREFIX}_batch_${bid}"
  local tags_json; tags_json=$(python3 -c "
import json
print(json.dumps({
  'Project': 'jpcite',
  'CreditRun': '2026-05',
  'Workload': 'cohort_render',
  'BatchId': '$bid',
  'AutoStop': '$AUTO_STOP',
}))
")
  local param_json; param_json=$(python3 -c "
import json
print(json.dumps({
  'batch_start': '$bs',
  'batch_end': '$be',
  's3_prefix': '$S3_PREFIX',
  'run_id': '$run_id',
}))
")
  echo "[submit] batch=$bid range=[$bs, $be) name=$job_name"
  if [ "$DRY_RUN" = "true" ]; then return 0; fi
  local out; out=$(aws batch submit-job \
    --region "$REGION" \
    --job-name "$job_name" \
    --job-queue "$QUEUE" \
    --job-definition "$JOB_DEF" \
    --tags "$tags_json" \
    --parameters "$param_json" \
    --output json)
  local jid; jid=$(echo "$out" | python3 -c "import json,sys; print(json.load(sys.stdin).get('jobId',''))")
  echo "[submit]   -> jobId=$jid"
}

# ---- backend: local ----------------------------------------------------
render_local_shard() {
  local i="$1"
  read -r bs be < <(batch_range "$i")
  local bid; bid=$(printf "%03d" "$i")
  local run_id="${RUN_PREFIX}_batch_${bid}"
  local log_file="$LOG_DIR/batch_${bid}.log"
  echo "[local] batch=$bid range=[$bs, $be) run_id=$run_id log=$log_file"
  if [ "$DRY_RUN" = "true" ]; then return 0; fi
  AWS_PROFILE="$AWS_PROFILE" "$PYTHON" \
    "$REPO/scripts/aws_credit_ops/generate_acceptance_probability_packets.py" \
    --db "$DB_PATH" \
    --jpintel-db "$JPINTEL_DB" \
    --batch-start "$bs" --batch-end "$be" \
    --s3-prefix "$S3_PREFIX" --commit \
    --run-id "$run_id" >"$log_file" 2>&1
  echo "[local]   -> done batch=$bid"
}

run_local_pool() {
  # bash 3.2 (macOS default) lacks `wait -n`, so we poll an associative
  # list of live pids and wait for any one to drop before launching the
  # next worker. The poll interval is 1s which is well below shard
  # duration (~30-60s) so concurrency stays close to the target.
  local pids=()
  for ((i = START; i < END; i++)); do
    # Reap any finished pids first.
    local live=()
    for p in "${pids[@]:-}"; do
      if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        live+=("$p")
      fi
    done
    pids=("${live[@]:-}")
    # If the pool is full, sleep until at least one worker exits.
    while [ "${#pids[@]}" -ge "$CONCURRENCY" ]; do
      sleep 1
      local still=()
      for p in "${pids[@]:-}"; do
        if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
          still+=("$p")
        fi
      done
      pids=("${still[@]:-}")
    done
    render_local_shard "$i" &
    pids+=("$!")
  done
  # Drain.
  for p in "${pids[@]:-}"; do
    [ -z "$p" ] && continue
    wait "$p" || echo "[local] worker pid=$p exited non-zero" >&2
  done
}

# ---- dispatch ----------------------------------------------------------
if [ "$BACKEND" = "batch" ]; then
  for ((i = START; i < END; i++)); do
    submit_batch_shard "$i"
  done
else
  run_local_pool
fi

echo ""
echo "[submit_cohort_batches] done — range [$START, $END) processed via $BACKEND backend."
echo "[submit_cohort_batches] verify: aws s3 ls $S3_PREFIX --recursive --profile $AWS_PROFILE --region $REGION | wc -l"
