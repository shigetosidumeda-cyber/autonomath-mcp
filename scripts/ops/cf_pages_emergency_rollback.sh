#!/usr/bin/env bash
# cf_pages_emergency_rollback.sh - 1-command Cloudflare Pages capsule rollback.
#
# ============================================================================
#  WARNING — PRODUCTION EDGE MUTATION
# ============================================================================
#  This script is the **emergency rollback** lever for the Cloudflare Pages
#  edge surface. Invoking it with the live token will:
#
#    * Rewrite ``site/releases/current/runtime_pointer.json`` to the
#      previous capsule (atomic, writes to ``.tmp.$$`` then mv-renames),
#    * Re-affirm the AWS-runtime safety flags
#      (``aws_runtime_dependency_allowed=false`` +
#      ``live_aws_commands_allowed=false``) so a rollback cannot silently
#      flip the live-AWS gate open,
#    * Purge the Cloudflare cache via API (if CF_API_TOKEN + CF_ZONE_ID
#      are present in env),
#    * Sleep 60s for edge cache + DNS TTL propagation,
#    * Probe ``healthz`` on the apex (https://jpcite.com/healthz) and
#      emit an attestation JSON.
#
#  The 60s sleep is non-negotiable — see memory
#  ``feedback_post_deploy_smoke_propagation``: Fly proxy + CF edge + DNS
#  TTL stack into a 3-layer cache window that needs ~60s to clear. A
#  shorter sleep yields false-negative healthz failures.
#
#  Live execution requires BOTH:
#
#    1. ``DRY_RUN=false`` explicit env var, AND
#    2. ``JPCITE_EMERGENCY_TOKEN`` non-empty (2-stage gate).
#
#  Missing either => exit 64 BEFORE any pointer rewrite / cache purge /
#  network call. DRY_RUN default is true, so an accidental invocation
#  prints the would-do plan and exits clean.
#
#  Usage:
#
#    DRY_RUN=true scripts/ops/cf_pages_emergency_rollback.sh
#    DRY_RUN=true scripts/ops/cf_pages_emergency_rollback.sh <prev_capsule_id>
#
#    JPCITE_EMERGENCY_TOKEN=... DRY_RUN=false \
#      scripts/ops/cf_pages_emergency_rollback.sh <prev_capsule_id>
#
#  If the previous capsule id is omitted, the script auto-derives it from
#  ``site/releases/current/runtime_pointer.json.bak`` (sibling backup
#  left by the previous rollback run).
# ============================================================================

set -euo pipefail

DRY_RUN="${DRY_RUN:-true}"
RUN_ID="${RUN_ID:-rc1-p0-bootstrap}"
HEALTHZ_URL="${HEALTHZ_URL:-https://jpcite.com/healthz}"
POST_ROLLBACK_SLEEP_SEC="${POST_ROLLBACK_SLEEP_SEC:-60}"
PROBE_TIMEOUT_SEC="${PROBE_TIMEOUT_SEC:-30}"
ATTESTATION_DIR="${ATTESTATION_DIR:-site/releases/${RUN_ID}/teardown_attestation}"
STEP="cf_pages_emergency_rollback"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POINTER_PATH="${REPO_ROOT}/site/releases/current/runtime_pointer.json"
BAK_PATH="${POINTER_PATH}.bak"

mkdir -p "${ATTESTATION_DIR}"
OUT="${ATTESTATION_DIR}/${STEP}.log"
JSON="${ATTESTATION_DIR}/${STEP}.json"

log() {
  printf '[%s] [%s] %s\n' "${TS}" "${STEP}" "$*" | tee -a "${OUT}"
}

# Two-stage gate. Mirrors 00_emergency_stop.sh exactly so an operator
# only has to remember ONE failure mode across the panic-button surface.
if [[ "${DRY_RUN}" != "true" ]]; then
  if [[ -z "${JPCITE_EMERGENCY_TOKEN:-}" ]]; then
    log "ABORT live emergency rollback requires JPCITE_EMERGENCY_TOKEN; refusing"
    exit 64
  fi
  log "ARMED live emergency rollback; token present"
else
  log "DRY_RUN emergency rollback preview; zero pointer mutation will occur"
fi

# Resolve previous capsule id.
PREV_CAPSULE_ID="${1:-}"
if [[ -z "${PREV_CAPSULE_ID}" ]]; then
  if [[ -f "${BAK_PATH}" ]]; then
    log "deriving previous capsule id from ${BAK_PATH}"
    PREV_CAPSULE_ID="$(POINTER_BAK="${BAK_PATH}" python3 -c '
import json, os, sys
with open(os.environ["POINTER_BAK"], encoding="utf-8") as fh:
    p = json.load(fh)
print(p.get("active_capsule_id", ""))
' 2>/dev/null || echo '')"
  fi
fi

if [[ -z "${PREV_CAPSULE_ID}" ]]; then
  log "ABORT no previous capsule id supplied and no .bak fallback at ${BAK_PATH}"
  exit 2
fi
log "target prev_capsule_id=${PREV_CAPSULE_ID}"

if [[ ! -f "${POINTER_PATH}" ]]; then
  log "ABORT runtime_pointer.json not found at ${POINTER_PATH}"
  exit 1
fi

# ---------------------------------------------------------------------------
# 1) Atomic pointer rewrite.
# ---------------------------------------------------------------------------
log "STEP 1/3 atomic runtime_pointer.json rewrite"
TMP_PATH="${POINTER_PATH}.tmp.$$"

if [[ "${DRY_RUN}" == "true" ]]; then
  log "DRY_RUN would-write pointer.active_capsule_id=${PREV_CAPSULE_ID}"
  POINTER_REWRITE_OUTCOME="dry-run-noop"
else
  cp -p "${POINTER_PATH}" "${BAK_PATH}"
  PREV_CAPSULE_ID="${PREV_CAPSULE_ID}" POINTER_PATH="${POINTER_PATH}" TMP_PATH="${TMP_PATH}" python3 <<'PYEOF'
import json
import os
import sys

pointer_path = os.environ["POINTER_PATH"]
tmp_path = os.environ["TMP_PATH"]
prev = os.environ["PREV_CAPSULE_ID"]

with open(pointer_path, "r", encoding="utf-8") as fh:
    pointer = json.load(fh)

if not isinstance(pointer, dict):
    print("fatal: runtime_pointer.json root is not an object", file=sys.stderr)
    sys.exit(3)

# Convention: capsule_id = <slug>-YYYY-MM-DD
parts = prev.rsplit("-", 3)
if len(parts) >= 4 and all(p.isdigit() for p in parts[-3:]):
    slug = parts[0]
else:
    slug = prev

pointer["active_capsule_id"] = prev
pointer["active_capsule_manifest"] = f"/releases/{slug}/release_capsule_manifest.json"
# Re-affirm safety flags - emergency rollback must NEVER flip these open.
pointer["aws_runtime_dependency_allowed"] = False
pointer["live_aws_commands_allowed"] = False

with open(tmp_path, "w", encoding="utf-8") as fh:
    json.dump(pointer, fh, indent=2, ensure_ascii=False, sort_keys=True)
    fh.write("\n")
PYEOF
  mv -f "${TMP_PATH}" "${POINTER_PATH}"
  POINTER_REWRITE_OUTCOME="written"
  log "pointer rewritten; backup at ${BAK_PATH}"
fi

# ---------------------------------------------------------------------------
# 2) Cloudflare cache purge (only if API token present).
# ---------------------------------------------------------------------------
log "STEP 2/3 cloudflare cache purge"
if [[ -z "${CF_API_TOKEN:-}" || -z "${CF_ZONE_ID:-}" ]]; then
  log "skip cache purge — CF_API_TOKEN or CF_ZONE_ID missing (this is OK)"
  CACHE_PURGE_OUTCOME="skipped-missing-credentials"
elif [[ "${DRY_RUN}" == "true" ]]; then
  log "DRY_RUN would-purge zone=${CF_ZONE_ID}"
  CACHE_PURGE_OUTCOME="dry-run-noop"
else
  log "EXEC purge_everything zone=${CF_ZONE_ID}"
  if curl -fsS --max-time "${PROBE_TIMEOUT_SEC}" \
       -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
       -H "Authorization: Bearer ${CF_API_TOKEN}" \
       -H "Content-Type: application/json" \
       --data '{"purge_everything":true}' >> "${OUT}" 2>&1; then
    CACHE_PURGE_OUTCOME="purged"
  else
    log "WARN purge_everything call failed; rollback continues regardless"
    CACHE_PURGE_OUTCOME="purge-failed"
  fi
fi

# ---------------------------------------------------------------------------
# 3) Post-rollback smoke: 60s propagation sleep + healthz probe.
# ---------------------------------------------------------------------------
log "STEP 3/3 post-rollback smoke (sleep=${POST_ROLLBACK_SLEEP_SEC}s + ${HEALTHZ_URL})"
if [[ "${DRY_RUN}" == "true" ]]; then
  log "DRY_RUN skip sleep + healthz probe"
  HEALTHZ_STATUS="dry-run-skipped"
  HEALTHZ_OUTCOME="dry-run-skipped"
else
  log "sleeping ${POST_ROLLBACK_SLEEP_SEC}s for Fly+CF+DNS propagation window"
  sleep "${POST_ROLLBACK_SLEEP_SEC}"
  log "probing ${HEALTHZ_URL}"
  HEALTHZ_STATUS="$(curl -fsS -o /dev/null -w '%{http_code}' \
                     --max-time "${PROBE_TIMEOUT_SEC}" \
                     "${HEALTHZ_URL}" 2>>"${OUT}" || echo '000')"
  if [[ "${HEALTHZ_STATUS}" == "200" ]]; then
    HEALTHZ_OUTCOME="green"
  else
    HEALTHZ_OUTCOME="red"
    log "WARN healthz=${HEALTHZ_STATUS}; manual triage required"
  fi
fi

cat > "${JSON}" <<EOF
{
  "step": "${STEP}",
  "run_id": "${RUN_ID}",
  "dry_run": ${DRY_RUN},
  "completed_at": "${TS}",
  "token_gate": "JPCITE_EMERGENCY_TOKEN",
  "prev_capsule_id": "${PREV_CAPSULE_ID}",
  "pointer_path": "${POINTER_PATH}",
  "pointer_backup_path": "${BAK_PATH}",
  "pointer_rewrite_outcome": "${POINTER_REWRITE_OUTCOME}",
  "cache_purge_outcome": "${CACHE_PURGE_OUTCOME}",
  "post_rollback_sleep_sec": ${POST_ROLLBACK_SLEEP_SEC},
  "healthz_url": "${HEALTHZ_URL}",
  "healthz_status": "${HEALTHZ_STATUS}",
  "healthz_outcome": "${HEALTHZ_OUTCOME}"
}
EOF

log "END cf-pages-emergency-rollback attestation=${JSON}"

if [[ "${DRY_RUN}" == "false" && "${HEALTHZ_OUTCOME}" == "red" ]]; then
  exit 66
fi
exit 0
