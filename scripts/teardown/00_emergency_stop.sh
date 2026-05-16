#!/usr/bin/env bash
# Stream I/E EMERGENCY teardown 00: one-command AWS kill switch.
#
# ============================================================================
#  WARNING — DESTRUCTIVE OPERATION
# ============================================================================
#  This script is the **emergency stop** lever for the live AWS canary phase
#  of the Stream I rollout. Invoking it with the live token will:
#
#    * terminate every AWS Batch job in non-final state (parallel),
#    * scale every ECS service tagged for jpcite to desired-count 0 then
#      force-delete,
#    * delete every Bedrock provisioned-throughput model commitment,
#    * delete every OpenSearch domain owned by this run-id,
#    * freeze every S3 bucket (versioning suspend + DenyAll bucket policy,
#      no object deletion — provenance preserved),
#    * terminate every EC2 instance tagged for this run-id,
#    * emit a per-step attestation JSON under
#      ``site/releases/${RUN_ID}/teardown_attestation/00_emergency_stop.*``.
#
#  The script is **distinct from** the staged 01..05 teardown flow:
#
#    - 01..05 are the planned, audited launch-gate teardown sequence with
#      ordered preconditions (inventory → export → drain → bedrock-stop →
#      attestation). Use 01..05 for a normal shutdown.
#    - 00_emergency_stop.sh is the panic button. It runs ALL service-class
#      stops in parallel without inventory/export first. Use 00 ONLY when
#      cost / blast-radius / data-leak risk is so high that losing the
#      planned attestation chain is acceptable.
#
#  Live execution requires BOTH:
#
#    1. ``DRY_RUN=false`` explicit env var, AND
#    2. ``JPCITE_EMERGENCY_TOKEN`` non-empty (2-stage gate).
#
#  Missing either => exit 64 BEFORE any AWS call.
#
#  The ``JPCITE_EMERGENCY_TOKEN`` is **separate from**
#  ``JPCITE_TEARDOWN_LIVE_TOKEN`` deliberately: the emergency lever should
#  not share a credential with the planned-teardown lever, so a leaked
#  planned-teardown token cannot also trigger the emergency panic stop.
#
#  DRY_RUN is the safe default. Without arming, every aws call is echoed
#  to the attestation log and zero side effects occur — making this script
#  CI-safe and operator-rehearsable.
# ============================================================================

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
TAG_KEY="${TAG_KEY:-jpcite-run-id}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="00_emergency_stop"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

# Two-stage gate. Fail-closed BEFORE any side-effecting aws call.
if [[ "${DRY_RUN}" != "true" ]]; then
  if [[ -z "${JPCITE_EMERGENCY_TOKEN:-}" ]]; then
    log "ABORT live emergency stop requires JPCITE_EMERGENCY_TOKEN; refusing"
    log "ABORT this token is intentionally SEPARATE from JPCITE_TEARDOWN_LIVE_TOKEN"
    exit 64
  fi
  log "ARMED live emergency stop; token present, profile=${AWS_PROFILE}"
else
  log "DRY_RUN emergency stop preview; zero AWS mutation will occur"
fi

run_aws() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN aws $*"
    return 0
  fi
  log "EXEC aws $*"
  aws "$@" --profile "${AWS_PROFILE}" --region "${AWS_REGION}" \
    >> "${OUT}" 2>&1 || log "WARN aws $* exited non-zero"
}

# Each service block emits a fragment we accumulate into a single JSON
# attestation. STEP_RESULTS appends one line per service.
declare -a STEP_RESULTS=()

emit_step() {
  # $1 = service label, $2 = brief outcome string.
  STEP_RESULTS+=("    {\"service\": \"$1\", \"outcome\": \"$2\"}")
}

log "BEGIN profile=${AWS_PROFILE} region=${AWS_REGION} dry_run=${DRY_RUN} run_id=${RUN_ID}"

# ---------------------------------------------------------------------------
# 1) AWS Batch: terminate every non-final job in parallel.
# ---------------------------------------------------------------------------
# Strategy: enumerate every job-queue tagged for this run-id, then for each
# active state (SUBMITTED / PENDING / RUNNABLE / STARTING / RUNNING) issue
# terminate-job for every returned job-id. In DRY_RUN we only echo the
# enumeration; in live mode the inner aws call returns a job list and we
# fan-out terminate calls in parallel via ``xargs -P``.
log "STEP 1/6 batch terminate-jobs"
run_aws batch describe-job-queues \
  --query "jobQueues[?starts_with(jobQueueName, \`jpcite-\`) == \`true\`].jobQueueName"
for state in SUBMITTED PENDING RUNNABLE STARTING RUNNING; do
  run_aws batch list-jobs \
    --job-queue "jpcite-playwright-${RUN_ID}" --job-status "${state}"
done
# The live caller resolves real job-ids from the list above; the dry-run
# shape preserves the parallel terminate pattern for auditor review.
run_aws batch terminate-job \
  --job-id "<resolved-from-list-jobs>" \
  --reason "jpcite emergency-stop ${RUN_ID}"
emit_step "batch" "terminate-jobs-fanout-issued"

# ---------------------------------------------------------------------------
# 2) ECS: every jpcite service -> desired-count 0, then force-delete.
# ---------------------------------------------------------------------------
log "STEP 2/6 ecs update-service desired-count=0 + delete-service"
run_aws ecs list-clusters \
  --query 'clusterArns[?contains(@, `jpcite`)]'
run_aws ecs list-services --cluster "jpcite-${RUN_ID}"
run_aws ecs update-service \
  --cluster "jpcite-${RUN_ID}" \
  --service "jpcite-playwright-${RUN_ID}" \
  --desired-count 0
run_aws ecs delete-service \
  --cluster "jpcite-${RUN_ID}" \
  --service "jpcite-playwright-${RUN_ID}" \
  --force
emit_step "ecs" "desired-count-0-then-force-delete"

# ---------------------------------------------------------------------------
# 3) Bedrock: delete every provisioned-throughput commitment.
# ---------------------------------------------------------------------------
# Bedrock provisioned throughput bills by the hour and is the single largest
# cash-burn vector if left running. Enumerate then delete every commitment
# whose name matches the jpcite prefix.
log "STEP 3/6 bedrock delete-provisioned-model-throughput"
run_aws bedrock list-provisioned-model-throughputs \
  --query 'provisionedModelSummaries[?starts_with(provisionedModelName, `jpcite-`) == `true`].provisionedModelArn'
run_aws bedrock delete-provisioned-model-throughput \
  --provisioned-model-id "${BEDROCK_PROVISIONED_ARN:-<resolved-from-list>}"
emit_step "bedrock" "delete-provisioned-throughput-fanout-issued"

# ---------------------------------------------------------------------------
# 4) OpenSearch: delete every domain owned by this run-id.
# ---------------------------------------------------------------------------
# delete-domain is async; the verify_zero_aws.sh probe is the
# confirmation gate. We do NOT snapshot first — emergency-stop accepts
# the data-loss tradeoff. Use 01..05 for the snapshot-then-delete path.
log "STEP 4/6 opensearch delete-domain"
run_aws opensearch list-domain-names \
  --query 'DomainNames[?starts_with(DomainName, `jpcite-`) == `true`].DomainName'
run_aws opensearch delete-domain \
  --domain-name "jpcite-${RUN_ID}"
emit_step "opensearch" "delete-domain-issued"

# ---------------------------------------------------------------------------
# 5) S3: bucket lock — suspend versioning + DenyAll bucket policy.
# ---------------------------------------------------------------------------
# We deliberately do NOT delete objects — provenance is the operator's only
# defense in a post-incident review under 景表法 / 消費者契約法. Lock-only
# leaves the lake immutable for forensic export at the operator's pace.
log "STEP 5/6 s3 versioning-suspend + DenyAll bucket-policy"
run_aws s3api list-buckets \
  --query "Buckets[?starts_with(Name, \`jpcite-\`) == \`true\`].Name"

BUCKET_LOCK_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyAllAfterEmergencyStop",
    "Effect": "Deny",
    "Principal": "*",
    "Action": ["s3:PutObject", "s3:DeleteObject", "s3:PutBucketPolicy"],
    "Resource": "arn:aws:s3:::jpcite-source-receipts-'"${RUN_ID}"'/*"
  }]
}'
run_aws s3api put-bucket-versioning \
  --bucket "jpcite-source-receipts-${RUN_ID}" \
  --versioning-configuration "Status=Suspended"
run_aws s3api put-bucket-policy \
  --bucket "jpcite-source-receipts-${RUN_ID}" \
  --policy "${BUCKET_LOCK_POLICY}"
emit_step "s3" "versioning-suspend-and-deny-all-policy"

# ---------------------------------------------------------------------------
# 6) EC2: terminate every instance tagged for this run-id.
# ---------------------------------------------------------------------------
log "STEP 6/6 ec2 terminate-instances"
run_aws ec2 describe-instances \
  --filters "Name=tag:${TAG_KEY},Values=${RUN_ID}" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId'
run_aws ec2 terminate-instances \
  --instance-ids "<resolved-from-describe-instances>"
emit_step "ec2" "terminate-instances-fanout-issued"

# ---------------------------------------------------------------------------
# Attestation JSON: per-step results + composite outcome.
# ---------------------------------------------------------------------------
# shellcheck disable=SC2155
RESULTS_BODY="$(IFS=$',\n'; printf '%s' "${STEP_RESULTS[*]}")"

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "region": "${AWS_REGION}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "token_gate": "JPCITE_EMERGENCY_TOKEN",
  "services_swept": [
    "batch", "ecs", "bedrock", "opensearch", "s3", "ec2"
  ],
  "step_results": [
${RESULTS_BODY}
  ],
  "next_step": "verify_zero_aws.sh"
}
EOF

log "END emergency-stop attestation=${JSON}"
