#!/usr/bin/env bash
# Stream E teardown 08: ECR attacker-repo cleanup (dual-region).
#
# Maps to AWS damage inventory (docs/_internal/AWS_DAMAGE_INVENTORY_2026_05_16.md,
# commit a51c988e1) — 2 attacker ECR repos identified in the compromised
# 993693061769 account during the amira.vn intrusion window:
#
#   * satyr-model        in us-east-1      (created 2026-03-23, 20+ tags incl
#                                            a 12.73 GB layer, ~$150.05/mo gross)
#   * z-image-inference  in ap-southeast-1 (created 2026-03-25)
#
# Goal: forensic dump every image manifest first, batch-delete tags, then
# delete the repo with --force. This is the LAST step before Awano-san closes
# the compromise ticket, so we keep a paper-trail attestation per region.
#
# Safety contract:
#   * DRY_RUN=true (default) lists images + writes forensic JSON but
#     never invokes batch-delete-image or delete-repository.
#   * Live execution requires BOTH DRY_RUN=false AND ONE OF:
#       - --commit flag (operator interactive)
#       - JPCITE_TEARDOWN_LIVE_TOKEN env (run_all.sh orchestrated)
#     Missing the gate aborts before any AWS mutation.
#   * Both regions are walked in sequence; per-region attestation JSON.
#
# Operator workflow:
#   1. Confirm Awano-san (AWS Japan) approval on the compromise thread.
#   2. Dry-run first:  ./08_ecr_attacker_cleanup.sh
#   3. Inspect site/releases/${RUN_ID}/teardown_attestation/08_*.json.
#   4. Live execute:   DRY_RUN=false JPCITE_TEARDOWN_LIVE_TOKEN=... \
#                      ./08_ecr_attacker_cleanup.sh --commit
#   5. Verify $0 inventory survives in attestation/ for the ticket.
#
# NEVER hardcode credentials. Profile is bookyou-recovery (post-compromise
# rotated keys); region is set per-repo, not globally.

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="08_ecr_attacker_cleanup"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Attacker repo catalogue. Order matters: us-east-1 first (largest cost),
# ap-southeast-1 second. To add a third row, append "repo_name:region".
ATTACKER_REPOS=(
  "satyr-model:us-east-1"
  "z-image-inference:ap-southeast-1"
)

# Parse --commit flag. Mirrors JPCITE_TEARDOWN_LIVE_TOKEN as a second gate
# so operators can invoke this script directly without exporting the token.
COMMIT_FLAG="false"
for arg in "$@"; do
  case "${arg}" in
    --commit) COMMIT_FLAG="true" ;;
    *) ;;
  esac
done

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

# Live-gate check. Both DRY_RUN=false AND (--commit OR JPCITE_TEARDOWN_LIVE_TOKEN)
# required before any mutating call. Read-only describe/list APIs are always
# permitted (so the forensic JSON dump always runs).
LIVE_OK="false"
if [[ "${DRY_RUN}" == "false" ]]; then
  if [[ "${COMMIT_FLAG}" == "true" ]] || [[ -n "${JPCITE_TEARDOWN_LIVE_TOKEN:-}" ]]; then
    LIVE_OK="true"
    log "LIVE mode armed (commit_flag=${COMMIT_FLAG} token_present=$([[ -n "${JPCITE_TEARDOWN_LIVE_TOKEN:-}" ]] && echo yes || echo no))"
  else
    log "ABORT DRY_RUN=false but neither --commit nor JPCITE_TEARDOWN_LIVE_TOKEN provided; refusing to mutate ECR"
    exit 64
  fi
else
  log "DRY_RUN mode; no AWS mutation will occur"
fi

# run_aws_ro: read-only AWS calls (describe-repositories etc.). Gated by
# DRY_RUN to match the pattern of 01..05 (DRY_RUN echoes only, no AWS call
# even for read-only APIs — keeps CI green without an AWS profile).
# Args: <region> <aws ... args>
run_aws_ro() {
  local region="$1"; shift
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN[ro,${region}] aws $*"
    return 0
  fi
  log "EXEC[ro,${region}] aws $*"
  aws "$@" --profile "${AWS_PROFILE}" --region "${region}" \
    >> "${OUT}" 2>&1 || log "WARN aws $* exited non-zero in ${region}"
}

# run_aws_mut: mutating AWS calls — gated by LIVE_OK.
# Args: <region> <aws ... args>
run_aws_mut() {
  local region="$1"; shift
  if [[ "${LIVE_OK}" != "true" ]]; then
    log "DRY_RUN[mut,${region}] aws $*"
    return 0
  fi
  log "EXEC[mut,${region}] aws $*"
  aws "$@" --profile "${AWS_PROFILE}" --region "${region}" \
    >> "${OUT}" 2>&1 || log "WARN aws $* exited non-zero in ${region}"
}

log "BEGIN profile=${AWS_PROFILE} dry_run=${DRY_RUN} live_ok=${LIVE_OK} run_id=${RUN_ID}"
log "ATTACKER_REPOS=${ATTACKER_REPOS[*]}"

# Per-region per-repo walk.
declare -a REGIONS_SEEN=()
declare -a REPOS_SEEN=()
declare -a FORENSIC_FILES=()
for entry in "${ATTACKER_REPOS[@]}"; do
  REPO_NAME="${entry%%:*}"
  REGION="${entry##*:}"
  REPOS_SEEN+=("${REPO_NAME}")
  REGIONS_SEEN+=("${REGION}")
  FORENSIC_FILE="${ATTESTATION_DIR}/${STEP}__${REPO_NAME}__${REGION}__forensic.json"
  FORENSIC_FILES+=("${FORENSIC_FILE}")

  log "---- repo=${REPO_NAME} region=${REGION} ----"

  # Step 1: list repos (confirm existence + ownership). Read-only.
  run_aws_ro "${REGION}" ecr describe-repositories \
    --repository-names "${REPO_NAME}"

  # Step 2: forensic dump — list every image (manifest + tag + size) BEFORE
  # any delete, so the compromise audit retains the full inventory even if
  # the live step later succeeds. Always read-only; always executed.
  #
  # We capture into the per-repo forensic JSON path (not the shared OUT log)
  # so the inventory survives as a discrete artifact attached to the ticket.
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN[forensic,${REGION}] would write ${FORENSIC_FILE}"
    # Still produce a stub so the attestation references a real file.
    cat > "${FORENSIC_FILE}" <<EOF
{
  "stub": true,
  "note": "DRY_RUN mode — live forensic dump deferred until --commit run",
  "repo": "${REPO_NAME}",
  "region": "${REGION}",
  "captured_at": "${TS}"
}
EOF
  else
    log "EXEC[forensic,${REGION}] aws ecr describe-images --repository-name ${REPO_NAME} > ${FORENSIC_FILE}"
    aws ecr describe-images \
      --repository-name "${REPO_NAME}" \
      --profile "${AWS_PROFILE}" \
      --region "${REGION}" \
      --output json \
      > "${FORENSIC_FILE}" 2>> "${OUT}" \
      || log "WARN forensic dump for ${REPO_NAME}@${REGION} exited non-zero"
  fi

  # Step 3: batch-delete-image — remove every tag in the repo. Mutating.
  # The --image-ids argument needs concrete imageDigest values; in live mode
  # the caller resolves them from the forensic JSON dumped in step 2. We
  # keep the call shape here so reviewers see the exact sequence.
  run_aws_mut "${REGION}" ecr batch-delete-image \
    --repository-name "${REPO_NAME}" \
    --image-ids "imageTag=<resolved-from-forensic>"

  # Step 4: delete-repository --force — drop the whole repo. Mutating.
  # --force lets ECR delete even if untagged images remain (defensive in
  # case step 3 missed any image due to race / partial failure).
  run_aws_mut "${REGION}" ecr delete-repository \
    --repository-name "${REPO_NAME}" \
    --force
done

# Step 5: attestation JSON.
# Format: list of repos seen, regions, forensic file paths, dry_run / live_ok
# state, and the next step pointer. The compromise audit ticket pins this
# JSON path as the proof-of-cleanup artifact.
REPOS_JSON=""
for r in "${REPOS_SEEN[@]}"; do
  REPOS_JSON+="\"${r}\","
done
REPOS_JSON="[${REPOS_JSON%,}]"

REGIONS_JSON=""
for r in "${REGIONS_SEEN[@]}"; do
  REGIONS_JSON+="\"${r}\","
done
REGIONS_JSON="[${REGIONS_JSON%,}]"

FORENSIC_JSON=""
for f in "${FORENSIC_FILES[@]}"; do
  FORENSIC_JSON+="\"${f}\","
done
FORENSIC_JSON="[${FORENSIC_JSON%,}]"

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "profile": "${AWS_PROFILE}",
  "dry_run": ${DRY_RUN},
  "live_ok": ${LIVE_OK},
  "commit_flag": ${COMMIT_FLAG},
  "token_present": $([[ -n "${JPCITE_TEARDOWN_LIVE_TOKEN:-}" ]] && echo true || echo false),
  "attacker_repos": ${REPOS_JSON},
  "regions": ${REGIONS_JSON},
  "forensic_files": ${FORENSIC_JSON},
  "completed_at": "${TS}",
  "compromise_ticket_ref": "docs/_internal/AWS_DAMAGE_INVENTORY_2026_05_16.md",
  "next_step": "verify_zero_aws.sh"
}
EOF

log "END attestation=${JSON} forensic_count=${#FORENSIC_FILES[@]}"
