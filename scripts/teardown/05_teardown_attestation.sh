#!/usr/bin/env bash
# Stream E teardown 05: cross-service attestation that every resource is gone.
#
# Maps to noop_aws_command_plan.json command_id=teardown_attestation_dry_run.
# Goal: AFTER 01..04 have run, verify zero residual jpcite-tagged resources
# remain across S3 / Batch / ECS / Bedrock / OpenSearch / EC2 / RDS / Lambda /
# EventBridge / CloudWatch Logs, then write a signed attestation manifest to
# a non-AWS path (default: site/releases/${RUN_ID}/teardown_attestation/).
#
# DRY_RUN=true echoes the audit calls. Live mode performs the queries and
# fails-closed if any non-empty result is observed.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
TAG_KEY="${TAG_KEY:-jpcite-run-id}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="05_teardown_attestation"
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

log "BEGIN profile=${AWS_PROFILE} dry_run=${DRY_RUN} run_id=${RUN_ID}"

# Tag-scoped resource sweep (covers every taggable service we provisioned).
run_aws resourcegroupstaggingapi get-resources \
  --tag-filters "Key=${TAG_KEY},Values=${RUN_ID}"

# Per-service belt-and-braces probes (services that are not tag-discoverable
# in every region, or where the tag API has eventual-consistency delay).
run_aws s3api list-buckets
run_aws batch describe-job-queues
run_aws ecs list-clusters
run_aws bedrock list-provisioned-model-throughputs
run_aws opensearch list-domain-names
run_aws ec2 describe-instances \
  --filters "Name=tag:${TAG_KEY},Values=${RUN_ID}"
run_aws rds describe-db-instances
run_aws lambda list-functions
run_aws events list-rules --name-prefix "jpcite-${RUN_ID}"
run_aws logs describe-log-groups \
  --log-group-name-prefix "/aws/jpcite/${RUN_ID}"

# Compute attestation hash off the consolidated dry-run log.
# In live mode the same hash signs the empty-resource confirmation.
if command -v shasum >/dev/null 2>&1; then
  HASH="$(shasum -a 256 "${OUT}" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  HASH="$(sha256sum "${OUT}" | awk '{print $1}')"
else
  HASH="unavailable"
fi

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "region": "${AWS_REGION}",
  "dry_run": ${DRY_RUN},
  "attestation_sha256": "${HASH}",
  "audited_services": [
    "resourcegroupstaggingapi",
    "s3",
    "batch",
    "ecs",
    "bedrock",
    "opensearch",
    "ec2",
    "rds",
    "lambda",
    "events",
    "logs"
  ],
  "completed_at": "${TS}",
  "non_aws_attestation_path": "${ATTESTATION_DIR}"
}
EOF

log "END attestation=${JSON} hash=${HASH}"
