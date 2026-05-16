#!/usr/bin/env bash
# emergency_kill_switch.sh - Common emergency entry point (aws / cf / both).
#
# ============================================================================
#  WARNING — DESTRUCTIVE OPERATION
# ============================================================================
#  This is the single panic-button operators are trained to hit. It wraps
#  the two underlying scripts so a single command can:
#
#    * ``aws``  -> invoke scripts/teardown/00_emergency_stop.sh (terminate
#                  every AWS Batch / ECS / Bedrock / OpenSearch / EC2
#                  surface + lock every S3 bucket)
#    * ``cf``   -> invoke scripts/ops/cf_pages_emergency_rollback.sh
#                  (rewrite runtime_pointer.json + purge CF cache +
#                  60s propagation + healthz probe)
#    * ``both`` -> run AWS stop AND CF rollback **in parallel** so the
#                  operator does not have to choose which to fire first.
#
#  Live execution requires:
#
#    1. ``DRY_RUN=false`` explicit env var,
#    2. ``JPCITE_EMERGENCY_TOKEN`` non-empty (passed through to both
#       child scripts unchanged).
#
#  Missing either => the child scripts exit 64 BEFORE any side effect,
#  surfaced here as a non-zero composite exit.
#
#  Usage:
#
#    scripts/ops/emergency_kill_switch.sh aws         # dry-run preview
#    scripts/ops/emergency_kill_switch.sh cf [prev_capsule_id]
#    scripts/ops/emergency_kill_switch.sh both [prev_capsule_id]
#
#    JPCITE_EMERGENCY_TOKEN=... DRY_RUN=false \
#      scripts/ops/emergency_kill_switch.sh both <prev_capsule_id>
# ============================================================================

set -euo pipefail

DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="emergency_kill_switch"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_SCRIPT="${REPO_ROOT}/scripts/teardown/00_emergency_stop.sh"
CF_SCRIPT="${REPO_ROOT}/scripts/ops/cf_pages_emergency_rollback.sh"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

usage() {
  cat <<EOF
usage: $0 {aws|cf|both} [previous_capsule_id_for_cf]

  aws   - terminate AWS resources (calls 00_emergency_stop.sh)
  cf    - rollback Cloudflare Pages capsule pointer (calls cf_pages_emergency_rollback.sh)
  both  - run aws + cf in parallel

  env:
    DRY_RUN=true|false        (default: true)
    JPCITE_EMERGENCY_TOKEN    (required when DRY_RUN=false)
    RUN_ID                    (default: rc1-p0-bootstrap)

EOF
}

MODE="${1:-}"
if [[ -z "${MODE}" || ("${MODE}" != "aws" && "${MODE}" != "cf" && "${MODE}" != "both") ]]; then
  usage >&2
  exit 2
fi
CF_PREV_CAPSULE_ID="${2:-}"

# Up-front sanity check on the two child scripts. The teardown-scripts
# integrity test enforces the same, but doing it here gives the operator
# a friendlier failure mode than a 127 from the child.
for s in "${AWS_SCRIPT}" "${CF_SCRIPT}"; do
  if [[ ! -x "${s}" ]]; then
    log "ABORT missing-or-not-executable: ${s}"
    exit 65
  fi
done

# Two-stage gate up-front so the composite log captures the refusal even
# when the child scripts would also refuse. Belt-and-braces — child scripts
# enforce their own gate too.
if [[ "${DRY_RUN}" != "true" ]]; then
  if [[ -z "${JPCITE_EMERGENCY_TOKEN:-}" ]]; then
    log "ABORT live emergency_kill_switch requires JPCITE_EMERGENCY_TOKEN; refusing"
    exit 64
  fi
  log "ARMED live emergency_kill_switch mode=${MODE}"
else
  log "DRY_RUN emergency_kill_switch preview mode=${MODE}"
fi

invoke_aws() {
  log "BEGIN aws child=${AWS_SCRIPT}"
  if DRY_RUN="${DRY_RUN}" \
     RUN_ID="${RUN_ID}" \
     ATTESTATION_DIR="${ATTESTATION_DIR}" \
     JPCITE_EMERGENCY_TOKEN="${JPCITE_EMERGENCY_TOKEN:-}" \
     bash "${AWS_SCRIPT}" >> "${OUT}" 2>&1; then
    log "OK aws child exited 0"
    return 0
  else
    rc="$?"
    log "FAIL aws child exit=${rc}"
    return "${rc}"
  fi
}

invoke_cf() {
  log "BEGIN cf child=${CF_SCRIPT} prev=${CF_PREV_CAPSULE_ID:-<auto>}"
  if DRY_RUN="${DRY_RUN}" \
     RUN_ID="${RUN_ID}" \
     ATTESTATION_DIR="${ATTESTATION_DIR}" \
     JPCITE_EMERGENCY_TOKEN="${JPCITE_EMERGENCY_TOKEN:-}" \
     CF_API_TOKEN="${CF_API_TOKEN:-}" \
     CF_ZONE_ID="${CF_ZONE_ID:-}" \
     bash "${CF_SCRIPT}" "${CF_PREV_CAPSULE_ID:-}" >> "${OUT}" 2>&1; then
    log "OK cf child exited 0"
    return 0
  else
    rc="$?"
    log "FAIL cf child exit=${rc}"
    return "${rc}"
  fi
}

AWS_RC="skipped"
CF_RC="skipped"

case "${MODE}" in
  aws)
    if invoke_aws; then AWS_RC=0; else AWS_RC=$?; fi
    ;;
  cf)
    if invoke_cf; then CF_RC=0; else CF_RC=$?; fi
    ;;
  both)
    # Fire both in parallel; collect both exit codes.
    invoke_aws &
    AWS_PID=$!
    invoke_cf &
    CF_PID=$!
    # ``wait <pid>`` propagates child exit; capture without aborting.
    if wait "${AWS_PID}"; then AWS_RC=0; else AWS_RC=$?; fi
    if wait "${CF_PID}"; then CF_RC=0; else CF_RC=$?; fi
    ;;
esac

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "mode": "${MODE}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "token_gate": "JPCITE_EMERGENCY_TOKEN",
  "aws_exit_code": "${AWS_RC}",
  "cf_exit_code": "${CF_RC}",
  "aws_child": "${AWS_SCRIPT}",
  "cf_child": "${CF_SCRIPT}"
}
EOF

log "END emergency_kill_switch attestation=${JSON} aws_rc=${AWS_RC} cf_rc=${CF_RC}"

# Composite exit: any non-zero child surfaces non-zero composite.
COMPOSITE=0
[[ "${AWS_RC}" != "0" && "${AWS_RC}" != "skipped" ]] && COMPOSITE=1
[[ "${CF_RC}"  != "0" && "${CF_RC}"  != "skipped" ]] && COMPOSITE=1
exit "${COMPOSITE}"
