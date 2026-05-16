#!/usr/bin/env bash
# Stream E teardown 01: STS identity + Budgets + read-only account inventory.
#
# Maps to noop_aws_command_plan.json command_id=aws_identity_budget_inventory.
# Pure read-only probes (STS / Budgets / CE / resourcegroupstaggingapi).
# DRY_RUN=true echoes the commands without invoking AWS.
# Switch to live execution ONLY after the explicit launch-gate review.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
TAG_KEY="${TAG_KEY:-jpcite-run-id}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="01_identity_budget_inventory"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

run_aws() {
  # $@ = aws ... arguments. DRY_RUN gate decides invoke vs echo.
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN aws $*"
    return 0
  fi
  log "EXEC aws $*"
  aws "$@" --profile "${AWS_PROFILE}" --region "${AWS_REGION}" \
    >> "${OUT}" 2>&1 || log "WARN aws $* exited non-zero"
}

log "BEGIN profile=${AWS_PROFILE} region=${AWS_REGION} dry_run=${DRY_RUN} run_id=${RUN_ID}"

# 1) Confirm caller identity (catches wrong profile / expired creds).
run_aws sts get-caller-identity

# 2) Budgets visibility for the cash-bill guard (no creation, list only).
run_aws budgets describe-budgets --account-id "${AWS_ACCOUNT_ID:-993693061769}"

# 3) Cost Explorer 30-day usage rollup (read-only).
run_aws ce get-cost-and-usage \
  --time-period Start="$(date -u -v -30d +%Y-%m-%d 2>/dev/null || date -u --date='-30 days' +%Y-%m-%d)",End="$(date -u +%Y-%m-%d)" \
  --granularity DAILY \
  --metrics UnblendedCost

# 4) Resource inventory by jpcite run-id tag (no mutation).
run_aws resourcegroupstaggingapi get-resources \
  --tag-filters "Key=${TAG_KEY},Values=${RUN_ID}"

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "region": "${AWS_REGION}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "next_step": "02_artifact_lake_export.sh"
}
EOF

log "END attestation=${JSON}"
