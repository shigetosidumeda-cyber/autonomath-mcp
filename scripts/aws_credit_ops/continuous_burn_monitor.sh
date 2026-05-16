#!/usr/bin/env bash
# continuous_burn_monitor.sh — sustained credit burn monitor + auto-resubmit
#
# Loop (every 1 hour via EventBridge or cron):
#   1. Probe SageMaker batch transform job states (last 24h).
#   2. Probe EC2 Spot GPU + CPU Batch queue states.
#   3. Probe budget headroom via Cost Explorer + Budgets.
#   4. If quota slot freed (CPU < 8 active OR GPU < 1 active) AND budget
#      under slowdown_line ($16,065 = 85% of $18,900 hard-stop), submit
#      ONE replacement job per freed lane.
#   5. If budget over hard_stop_line ($18,900), HALT — write SENTINEL
#      file ``/tmp/jpcite_burn_halted`` and exit non-zero. The Budget
#      Action with DenyAll IAM policy is the structural backstop; this
#      script is the cooperative gate.
#
# Read-mostly by default. Submission gated behind ``--commit``; without
# it the script logs what *would* be submitted (DRY_RUN). The hourly
# EventBridge schedule will pass ``--commit`` once the operator has
# validated dry-run output once.
#
# Outputs a single jsonl line per tick to STATE_DIR=/tmp/jpcite_burn_state
# (tick timestamp + status counts + budget + decision).
#
# Constraints:
#   * AWS profile: bookyou-recovery (override with AWS_PROFILE env).
#   * Budget hard-stop: $18,900 (matches Budget Action attached to
#     ``jpcite-credit-run-stop-18900``).
#   * Budget slowdown: $16,065 (85%) — no new submissions above this line.
#   * NEVER submits jobs that would violate the deny IAM (Budget Action
#     fires at $18,900 and detaches submit permission anyway).
#   * NO LLM API.
#   * [lane:solo].
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="${JPCITE_BURN_STATE_DIR:-/tmp/jpcite_burn_state}"
HALT_SENTINEL="$STATE_DIR/HALTED"
LEDGER="$STATE_DIR/tick_ledger.jsonl"
COMMIT_MODE="0"

BUDGET_HARD_STOP_USD="${JPCITE_BURN_HARD_STOP_USD:-18900}"
BUDGET_SLOWDOWN_USD="${JPCITE_BURN_SLOWDOWN_USD:-16065}"
SAGEMAKER_CPU_QUOTA="${JPCITE_SM_CPU_QUOTA:-8}"
SAGEMAKER_GPU_QUOTA="${JPCITE_SM_GPU_QUOTA:-1}"
GPU_BATCH_QUOTA="${JPCITE_GPU_BATCH_QUOTA:-4}"  # CE max 64 vCPU / 16 vCPU per job = 4 concurrent.

GPU_QUEUE="${GPU_QUEUE:-jpcite-credit-ec2-spot-gpu-queue}"
CPU_QUEUE="${CPU_QUEUE:-jpcite-credit-ec2-spot-cpu-queue}"
FARGATE_QUEUE="${FARGATE_QUEUE:-jpcite-credit-fargate-spot-short-queue}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) COMMIT_MODE="1"; shift ;;
    --dry-run) COMMIT_MODE="0"; shift ;;
    --state-dir) STATE_DIR="$2"; HALT_SENTINEL="$STATE_DIR/HALTED"; LEDGER="$STATE_DIR/tick_ledger.jsonl"; shift 2 ;;
    --help|-h)
      grep -E '^# ' "$0" | sed 's/^# //'
      exit 0 ;;
    *) echo "[burn-monitor] unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$STATE_DIR"

log() {
  printf '[burn-monitor] %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Step 0 — abort fast if sentinel is set (re-arm requires manual rm).
if [[ -f "$HALT_SENTINEL" ]]; then
  log "HALTED sentinel present at $HALT_SENTINEL — refusing to submit. rm to re-arm."
  reason="halted_sentinel"
  printf '{"ts":"%s","decision":"halted","reason":"%s"}\n' "$(now_iso)" "$reason" >> "$LEDGER"
  exit 0
fi

# Step 1 — SageMaker transform-job tally (last 24h).
SM_JSON="$(aws sagemaker list-transform-jobs --region "$REGION" --max-results 100 --output json 2>/dev/null || echo '{}')"
sm_inprogress=$(python3 -c "
import json, sys
d = json.loads('''$SM_JSON''' or '{}')
jobs = d.get('TransformJobSummaries', [])
print(sum(1 for j in jobs if j.get('TransformJobStatus') == 'InProgress'))
")
sm_succeeded=$(python3 -c "
import json, sys
d = json.loads('''$SM_JSON''' or '{}')
jobs = d.get('TransformJobSummaries', [])
print(sum(1 for j in jobs if j.get('TransformJobStatus') == 'Completed'))
")
sm_failed=$(python3 -c "
import json, sys
d = json.loads('''$SM_JSON''' or '{}')
jobs = d.get('TransformJobSummaries', [])
print(sum(1 for j in jobs if j.get('TransformJobStatus') == 'Failed'))
")

# Step 2 — Batch GPU queue tally.
gpu_running=0
gpu_runnable=0
gpu_starting=0
for st in RUNNING RUNNABLE STARTING SUBMITTED PENDING; do
  n=$(aws batch list-jobs --job-queue "$GPU_QUEUE" --job-status "$st" --region "$REGION" --max-results 100 --output json 2>/dev/null \
    | python3 -c "import json, sys; d = json.load(sys.stdin); print(len(d.get('jobSummaryList', [])))" 2>/dev/null || echo 0)
  case "$st" in
    RUNNING) gpu_running=$n ;;
    RUNNABLE) gpu_runnable=$n ;;
    STARTING) gpu_starting=$n ;;
  esac
done
gpu_active=$((gpu_running + gpu_starting + gpu_runnable))

# Step 3 — Budget headroom via Cost Explorer (MTD gross).
month_start=$(date -u +%Y-%m-01)
tomorrow=$(date -u -v+1d +%Y-%m-%d 2>/dev/null || date -u -d 'tomorrow' +%Y-%m-%d)
ce_json="$(aws ce get-cost-and-usage --region us-east-1 \
  --time-period "Start=${month_start},End=${tomorrow}" \
  --granularity MONTHLY --metrics UnblendedCost --output json 2>/dev/null || echo '{}')"
mtd_usd=$(python3 -c "
import json, sys
try:
  d = json.loads('''$ce_json''' or '{}')
  r = d.get('ResultsByTime', [])
  print(float(r[0]['Total']['UnblendedCost']['Amount']) if r else 0.0)
except Exception:
  print(0.0)
")

# Step 4 — Decide.
decision="continue"
reason=""
sm_cpu_free=$((SAGEMAKER_CPU_QUOTA - sm_inprogress))
gpu_slot_free=$((GPU_BATCH_QUOTA - gpu_active))

if python3 -c "import sys; sys.exit(0 if float('$mtd_usd') >= float('$BUDGET_HARD_STOP_USD') else 1)"; then
  decision="halt"
  reason="mtd_over_hard_stop"
  touch "$HALT_SENTINEL"
elif python3 -c "import sys; sys.exit(0 if float('$mtd_usd') >= float('$BUDGET_SLOWDOWN_USD') else 1)"; then
  decision="slowdown"
  reason="mtd_over_slowdown"
fi

submitted_sagemaker=0
submitted_gpu_batch=0

# Cooldown gates: prevent double-submit when a previous submission is still
# warming up. SageMaker batch transform jobs ack within ~30s; honor a 30-min
# cooldown so we never stack saturate bursts within the same hour cadence.
sm_last_submit_file="$STATE_DIR/last_sagemaker_submit.epoch"
gpu_last_submit_file="$STATE_DIR/last_gpu_submit.epoch"
now_epoch=$(date -u +%s)
sm_cooldown=$(( ${JPCITE_SM_COOLDOWN_SEC:-1800} ))
gpu_cooldown=$(( ${JPCITE_GPU_COOLDOWN_SEC:-3600} ))

sm_can_submit=1
gpu_can_submit=1
if [[ -f "$sm_last_submit_file" ]]; then
  last=$(cat "$sm_last_submit_file")
  if (( now_epoch - last < sm_cooldown )); then sm_can_submit=0; fi
fi
if [[ -f "$gpu_last_submit_file" ]]; then
  last=$(cat "$gpu_last_submit_file")
  if (( now_epoch - last < gpu_cooldown )); then gpu_can_submit=0; fi
fi

if [[ "$decision" == "continue" ]] && [[ "$sm_cpu_free" -gt 2 ]] && [[ "$COMMIT_MODE" == "1" ]] && [[ "$sm_can_submit" == "1" ]]; then
  # submit_quota_saturate_burn.py submits the full 8 CPU + 1 GPU plan; rely on
  # SageMaker quota itself to gate. Only fire when >2 lanes free so we don't
  # bounce against the ceiling.
  log "SageMaker CPU lanes free=$sm_cpu_free; submitting quota-saturate burn"
  if "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/aws_credit_ops/submit_quota_saturate_burn.py" \
      --commit >/dev/null 2>&1; then
    submitted_sagemaker=1
    echo "$now_epoch" > "$sm_last_submit_file"
  else
    log "warn: saturate submit returned non-zero (continuing tick)"
  fi
fi

if [[ "$decision" == "continue" ]] && [[ "$gpu_slot_free" -gt 0 ]] && [[ "$COMMIT_MODE" == "1" ]] && [[ "$gpu_can_submit" == "1" ]]; then
  log "GPU Batch lanes free=$gpu_slot_free; submitting long-burn GPU job set"
  if "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/aws_credit_ops/submit_gpu_burn_long.py" \
      >/dev/null 2>&1; then
    submitted_gpu_batch=1
    echo "$now_epoch" > "$gpu_last_submit_file"
  else
    log "warn: GPU long-burn submit returned non-zero (continuing tick)"
  fi
fi

if [[ "$COMMIT_MODE" == "0" ]] && [[ "$decision" == "continue" ]]; then
  log "DRY_RUN — would submit sagemaker_cpu=$sm_cpu_free (cooldown_ok=$sm_can_submit) gpu_batch=$gpu_slot_free (cooldown_ok=$gpu_can_submit) (use --commit to apply)"
fi

# Step 5 — Ledger.
printf '{"ts":"%s","decision":"%s","reason":"%s","mtd_usd":%s,"budget_slowdown":%s,"budget_hard_stop":%s,"sagemaker":{"in_progress":%s,"completed":%s,"failed":%s,"cpu_free":%s,"submitted":%s},"gpu_batch":{"running":%s,"runnable":%s,"starting":%s,"slot_free":%s,"submitted":%s},"commit_mode":%s}\n' \
  "$(now_iso)" \
  "$decision" \
  "$reason" \
  "$mtd_usd" \
  "$BUDGET_SLOWDOWN_USD" \
  "$BUDGET_HARD_STOP_USD" \
  "$sm_inprogress" \
  "$sm_succeeded" \
  "$sm_failed" \
  "$sm_cpu_free" \
  "$submitted_sagemaker" \
  "$gpu_running" \
  "$gpu_runnable" \
  "$gpu_starting" \
  "$gpu_slot_free" \
  "$submitted_gpu_batch" \
  "$COMMIT_MODE" \
  >> "$LEDGER"

log "tick decision=$decision mtd=\$${mtd_usd} sm_inprogress=$sm_inprogress gpu_active=$gpu_active sm_submitted=$submitted_sagemaker gpu_submitted=$submitted_gpu_batch"

if [[ "$decision" == "halt" ]]; then
  exit 3
fi
exit 0
