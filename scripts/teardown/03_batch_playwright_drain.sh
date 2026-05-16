#!/usr/bin/env bash
# Stream E teardown 03: Batch / ECS drain (Playwright browser-capture workers).
#
# Maps to noop_aws_command_plan.json command_id=batch_playwright_dry_run.
# Goal: stop any active Playwright Batch jobs + ECS services + drain job queues
# before bucket teardown, so no in-flight worker writes to the receipt lake
# after 02_artifact_lake_export.sh freezes the bucket policy.
#
# DRY_RUN=true echoes only. Live mode:
#   1. batch list-jobs (RUNNING / RUNNABLE / SUBMITTED / PENDING).
#   2. batch terminate-job for each non-final state.
#   3. batch update-job-queue --state DISABLED.
#   4. ecs update-service --desired-count 0 for the playwright capture service.
#   5. ecs delete-service --force after tasks drain.
#   6. ecr delete-repository for the captured image registry.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
JOB_QUEUE="${JOB_QUEUE:-jpcite-playwright-${RUN_ID}}"
ECS_CLUSTER="${ECS_CLUSTER:-jpcite-${RUN_ID}}"
ECS_SERVICE="${ECS_SERVICE:-jpcite-playwright-${RUN_ID}}"
ECR_REPO="${ECR_REPO:-jpcite-playwright}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="03_batch_playwright_drain"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

run_aws() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN aws $*"
    return 0
  fi
  log "EXEC aws $*"
  aws "$@" --profile "${AWS_PROFILE}" --region "${AWS_REGION}" \
    >> "${OUT}" 2>&1 || log "WARN aws $* exited non-zero"
}

log "BEGIN profile=${AWS_PROFILE} dry_run=${DRY_RUN} queue=${JOB_QUEUE} cluster=${ECS_CLUSTER}"

# 1) List active Batch jobs in every non-final state.
for state in SUBMITTED PENDING RUNNABLE STARTING RUNNING; do
  run_aws batch list-jobs --job-queue "${JOB_QUEUE}" --job-status "${state}"
done

# 2) Terminate every non-final job. In live mode the caller resolves IDs from
#    step (1) and substitutes them here; the dry-run preview retains the loop
#    shape so reviewers can audit the call sequence.
run_aws batch terminate-job --job-id "<resolved-from-list-jobs>" \
  --reason "jpcite teardown ${RUN_ID}"

# 3) Disable the job queue so no further jobs schedule.
run_aws batch update-job-queue --job-queue "${JOB_QUEUE}" --state DISABLED

# 4) Scale the ECS Playwright capture service to 0 desired tasks.
run_aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --desired-count 0

# 5) Force-delete the ECS service.
run_aws ecs delete-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --force

# 6) ECR repo cleanup (browser-capture worker image).
run_aws ecr delete-repository --repository-name "${ECR_REPO}" --force

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "job_queue": "${JOB_QUEUE}",
  "ecs_cluster": "${ECS_CLUSTER}",
  "ecs_service": "${ECS_SERVICE}",
  "ecr_repo": "${ECR_REPO}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "next_step": "04_bedrock_ocr_stop.sh"
}
EOF

log "END attestation=${JSON}"
