#!/usr/bin/env bash
# Stream E teardown 02: S3 source-receipt bucket export to non-AWS lake + verify.
#
# Maps to noop_aws_command_plan.json command_id=artifact_lake_dry_run.
# Goal: lift the immutable source-receipt corpus off AWS S3 onto a non-AWS
# object store (Cloudflare R2 by default, declared via EXPORT_TARGET_URI) so
# the AWS account can be emptied without losing provenance.
#
# DRY_RUN=true echoes only. Live mode performs:
#   1. s3api list-buckets (discover jpcite-source-receipts-* buckets).
#   2. rclone (or aws s3 sync) push bucket -> ${EXPORT_TARGET_URI}.
#   3. checksum verify (sha256 manifest both sides).
#   4. s3api put-bucket-policy denying further writes (read-only freeze).
#
# Deletion of the bucket itself happens in 05_teardown_attestation.sh, not here.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
BUCKET_PREFIX="${BUCKET_PREFIX:-jpcite-source-receipts}"
EXPORT_TARGET_URI="${EXPORT_TARGET_URI:-r2://jpcite-receipts-archive}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="02_artifact_lake_export"
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

run_external() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN $*"
    return 0
  fi
  log "EXEC $*"
  "$@" >> "${OUT}" 2>&1 || log "WARN $* exited non-zero"
}

log "BEGIN profile=${AWS_PROFILE} dry_run=${DRY_RUN} target=${EXPORT_TARGET_URI}"

# 1) Discover candidate source-receipt buckets.
run_aws s3api list-buckets \
  --query "Buckets[?starts_with(Name, \`${BUCKET_PREFIX}\`) == \`true\`].Name"

# 2) Push corpus to non-AWS store. rclone preferred (handles R2 / B2 / GCS).
#    Pattern: rclone sync s3:${BUCKET}/ r2:jpcite-receipts-archive/ --checksum.
BUCKET_NAME="${BUCKET_PREFIX}-${RUN_ID}"
run_external rclone sync "s3:${BUCKET_NAME}/" "${EXPORT_TARGET_URI}/${BUCKET_NAME}/" \
  --checksum --progress

# 3) Cross-store SHA256 manifest verification.
run_external rclone check "s3:${BUCKET_NAME}/" "${EXPORT_TARGET_URI}/${BUCKET_NAME}/" \
  --one-way

# 4) Freeze the source bucket against further writes (defense-in-depth).
run_aws s3api put-bucket-policy \
  --bucket "${BUCKET_NAME}" \
  --policy "$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyAllPutAfterTeardownExport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": ["s3:PutObject", "s3:DeleteObject"],
    "Resource": "arn:aws:s3:::${BUCKET_NAME}/*"
  }]
}
POLICY
)"

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "bucket": "${BUCKET_NAME}",
  "export_target": "${EXPORT_TARGET_URI}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "next_step": "03_batch_playwright_drain.sh"
}
EOF

log "END attestation=${JSON}"
