#!/usr/bin/env bash
# Stream E teardown orchestrator: run 01..05 in order with attestation rollup.
#
# DRY_RUN=true (default) executes every step in dry-run mode (echo only).
# Live execution requires both DRY_RUN=false AND the explicit launch-gate token
# JPCITE_TEARDOWN_LIVE_TOKEN; missing the token aborts before any AWS call.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "${ATTESTATION_DIR}"
ROLLUP="${ATTESTATION_DIR}/run_all.log"
ROLLUP_JSON="${ATTESTATION_DIR}/run_all.json"

log() {
  printf '[%s] [run_all] %s\n' "${TS}" "$*" | tee -a "${ROLLUP}"
}

if [[ "${DRY_RUN}" == "false" ]]; then
  if [[ -z "${JPCITE_TEARDOWN_LIVE_TOKEN:-}" ]]; then
    log "ABORT live execution requires JPCITE_TEARDOWN_LIVE_TOKEN; refusing to proceed"
    exit 64
  fi
  log "LIVE mode armed; token present"
else
  log "DRY_RUN mode; no AWS mutation will occur"
fi

STEPS=(
  "01_identity_budget_inventory.sh"
  "02_artifact_lake_export.sh"
  "03_batch_playwright_drain.sh"
  "04_bedrock_ocr_stop.sh"
  "05_teardown_attestation.sh"
)

declare -a EXIT_CODES=()
for s in "${STEPS[@]}"; do
  log "BEGIN ${s}"
  if AWS_PROFILE="${AWS_PROFILE}" AWS_REGION="${AWS_REGION}" \
     DRY_RUN="${DRY_RUN}" RUN_ID="${RUN_ID}" \
     ATTESTATION_DIR="${ATTESTATION_DIR}" \
     bash "${SCRIPT_DIR}/${s}"; then
    log "OK ${s}"
    EXIT_CODES+=("0")
  else
    rc="$?"
    log "FAIL ${s} exit=${rc}"
    EXIT_CODES+=("${rc}")
    # Continue running residual steps so the final attestation captures
    # everything we observed even if an upstream step failed; surface the
    # composite exit at the end.
  fi
done

cat > "${ROLLUP_JSON}" <<EOF
{
  "orchestrator": "run_all",
  "run_id": "${RUN_ID}",
  "dry_run": ${DRY_RUN},
  "steps": ["${STEPS[0]}", "${STEPS[1]}", "${STEPS[2]}", "${STEPS[3]}", "${STEPS[4]}"],
  "exit_codes": [${EXIT_CODES[0]}, ${EXIT_CODES[1]}, ${EXIT_CODES[2]}, ${EXIT_CODES[3]}, ${EXIT_CODES[4]}],
  "completed_at": "${TS}",
  "attestation_dir": "${ATTESTATION_DIR}"
}
EOF

log "END rollup=${ROLLUP_JSON}"

COMPOSITE=0
for rc in "${EXIT_CODES[@]}"; do
  if [[ "${rc}" != "0" ]]; then
    COMPOSITE=1
  fi
done
exit "${COMPOSITE}"
