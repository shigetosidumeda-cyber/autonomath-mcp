#!/usr/bin/env bash
# Stream E teardown verifier: assert zero residual jpcite resources across AWS.
#
# Runs AFTER 05_teardown_attestation.sh as a separate, fail-closed check.
# Each service probe must return an empty result set; any non-empty observation
# is flagged in the attestation and the script exits non-zero.
#
# DRY_RUN=true echoes the probes without invoking AWS (useful for CI lint).

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
TAG_KEY="${TAG_KEY:-jpcite-run-id}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="verify_zero_aws"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

# Each probe records "ZERO" or "NONZERO". Aggregated at the end.
declare -a SERVICES=(
  "s3"
  "batch"
  "ecs"
  "bedrock"
  "opensearch"
  "ec2"
  "rds"
  "lambda"
  "events"
)

probe() {
  local service="$1"
  shift
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN ${service}: aws $*"
    echo "ZERO"
    return 0
  fi
  log "EXEC ${service}: aws $*"
  local raw
  if ! raw="$(aws "$@" --profile "${AWS_PROFILE}" --region "${AWS_REGION}" \
               --output text 2>>"${OUT}")"; then
    log "WARN ${service} probe errored"
    echo "ERROR"
    return 0
  fi
  if [[ -z "${raw// /}" ]]; then
    echo "ZERO"
  else
    log "NONZERO ${service}: ${raw}"
    echo "NONZERO"
  fi
}

S3_STATE="$(probe s3 s3api list-buckets \
  --query "Buckets[?starts_with(Name, \`jpcite-\`) == \`true\`].Name")"
BATCH_STATE="$(probe batch batch describe-job-queues \
  --query 'jobQueues[?starts_with(jobQueueName, `jpcite-`) == `true`].jobQueueName')"
ECS_STATE="$(probe ecs ecs list-clusters \
  --query 'clusterArns[?contains(@, `jpcite`)]')"
BEDROCK_STATE="$(probe bedrock bedrock list-provisioned-model-throughputs \
  --query 'provisionedModelSummaries[?starts_with(provisionedModelName, `jpcite-`) == `true`].provisionedModelArn')"
OPENSEARCH_STATE="$(probe opensearch opensearch list-domain-names \
  --query 'DomainNames[?starts_with(DomainName, `jpcite-`) == `true`].DomainName')"
EC2_STATE="$(probe ec2 ec2 describe-instances \
  --filters "Name=tag:${TAG_KEY},Values=${RUN_ID}" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId')"
RDS_STATE="$(probe rds rds describe-db-instances \
  --query 'DBInstances[?starts_with(DBInstanceIdentifier, `jpcite-`) == `true`].DBInstanceIdentifier')"
LAMBDA_STATE="$(probe lambda lambda list-functions \
  --query 'Functions[?starts_with(FunctionName, `jpcite-`) == `true`].FunctionName')"
EVENTS_STATE="$(probe events events list-rules \
  --name-prefix "jpcite-${RUN_ID}" \
  --query 'Rules[].Name')"

declare -a STATES=(
  "${S3_STATE}" "${BATCH_STATE}" "${ECS_STATE}" "${BEDROCK_STATE}"
  "${OPENSEARCH_STATE}" "${EC2_STATE}" "${RDS_STATE}" "${LAMBDA_STATE}"
  "${EVENTS_STATE}"
)

VERDICT="zero"
for s in "${STATES[@]}"; do
  if [[ "${s}" == "NONZERO" || "${s}" == "ERROR" ]]; then
    VERDICT="nonzero"
  fi
done

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "region": "${AWS_REGION}",
  "dry_run": ${DRY_RUN},
  "verdict": "${VERDICT}",
  "services": {
    "s3": "${S3_STATE}",
    "batch": "${BATCH_STATE}",
    "ecs": "${ECS_STATE}",
    "bedrock": "${BEDROCK_STATE}",
    "opensearch": "${OPENSEARCH_STATE}",
    "ec2": "${EC2_STATE}",
    "rds": "${RDS_STATE}",
    "lambda": "${LAMBDA_STATE}",
    "events": "${EVENTS_STATE}"
  },
  "completed_at": "${TS}"
}
EOF

log "END verdict=${VERDICT} attestation=${JSON}"

if [[ "${VERDICT}" != "zero" ]]; then
  log "FAIL residual resources detected; review ${OUT}"
  exit 65
fi
exit 0
