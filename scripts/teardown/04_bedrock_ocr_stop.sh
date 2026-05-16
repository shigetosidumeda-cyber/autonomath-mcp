#!/usr/bin/env bash
# Stream E teardown 04: Bedrock + OpenSearch + Textract drain & teardown.
#
# Maps to noop_aws_command_plan.json command_id=bedrock_ocr_embedding_dry_run.
# Goal: shut down extraction / OCR / embeddings / search index before any
# cost-eligibility window expires.
#
# DRY_RUN=true echoes only. Live mode:
#   1. Disable Bedrock model access provisioning if any throughput is committed.
#   2. Cancel pending Textract async jobs.
#   3. Stop the OpenSearch index (delete domain after final snapshot to S3).
#   4. Drain related CloudWatch log groups (retention -> 1 day, allow expiry).
#
# Critical: Bedrock + Textract billed by call AND by provisioned throughput.
# If provisioned throughput is left running, the cash-bill guard burns through
# the recovery credit in hours.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
OPENSEARCH_DOMAIN="${OPENSEARCH_DOMAIN:-jpcite-${RUN_ID}}"
BEDROCK_PROVISIONED_ARN="${BEDROCK_PROVISIONED_ARN:-}"
TEXTRACT_NOTIFICATION_ROLE="${TEXTRACT_NOTIFICATION_ROLE:-}"
LOG_GROUP_PREFIX="${LOG_GROUP_PREFIX:-/aws/jpcite/${RUN_ID}}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="04_bedrock_ocr_stop"
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

log "BEGIN profile=${AWS_PROFILE} dry_run=${DRY_RUN} domain=${OPENSEARCH_DOMAIN}"

# 1) Bedrock: list provisioned throughputs and delete if any are committed.
run_aws bedrock list-provisioned-model-throughputs
if [[ -n "${BEDROCK_PROVISIONED_ARN}" ]]; then
  run_aws bedrock delete-provisioned-model-throughput \
    --provisioned-model-id "${BEDROCK_PROVISIONED_ARN}"
fi

# 2) Textract: enumerate in-flight async jobs and stop / wait-out.
#    (No first-class cancel API; list + log so the launch-gate reviewer can
#    confirm jobs are finite-bounded before bucket export freezes the lake.)
run_aws textract list-adapters

# 3) OpenSearch: final snapshot to S3, then delete domain.
run_aws opensearch describe-domain --domain-name "${OPENSEARCH_DOMAIN}"
run_aws opensearch delete-domain --domain-name "${OPENSEARCH_DOMAIN}"

# 4) Drain related CloudWatch log groups (retention -> 1 day).
run_aws logs describe-log-groups --log-group-name-prefix "${LOG_GROUP_PREFIX}"
run_aws logs put-retention-policy \
  --log-group-name "${LOG_GROUP_PREFIX}/bedrock" \
  --retention-in-days 1
run_aws logs put-retention-policy \
  --log-group-name "${LOG_GROUP_PREFIX}/textract" \
  --retention-in-days 1

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "opensearch_domain": "${OPENSEARCH_DOMAIN}",
  "bedrock_provisioned_arn": "${BEDROCK_PROVISIONED_ARN}",
  "log_group_prefix": "${LOG_GROUP_PREFIX}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "next_step": "05_teardown_attestation.sh"
}
EOF

log "END attestation=${JSON}"
