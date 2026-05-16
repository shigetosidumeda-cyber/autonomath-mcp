#!/usr/bin/env bash
# post_deploy_smoke.sh - Post-deploy smoke against jpcite production after a
# Cloudflare Pages rollback (or routine deploy). Verifies healthz + a small
# set of sample routes survive the Fly proxy + Cloudflare edge + DNS TTL
# propagation window.
#
# Usage:
#   scripts/ops/post_deploy_smoke.sh [base_url]
#
# Defaults base_url to https://jpcite.com.
#
# Hardening rationale (memory feedback_post_deploy_smoke_propagation):
#   - 60s sleep BEFORE first curl so Fly machine swap + CF edge purge settle.
#   - curl --max-time 30 (Fly p99 swap window exceeds 25s).
#   - Each URL is probed twice with a short backoff to smooth over isolated
#     edge-cache misses without false-negative gating.

set -euo pipefail

BASE_URL="${1:-https://jpcite.com}"
SLEEP_SECONDS="${POST_DEPLOY_SMOKE_SLEEP:-60}"
MAX_TIME="${POST_DEPLOY_SMOKE_MAX_TIME:-30}"
ATTEMPTS_PER_URL="${POST_DEPLOY_SMOKE_ATTEMPTS:-2}"

SAMPLE_ROUTES=(
  "/healthz"
  "/release/current/capsule_manifest.json"
  "/release/current/capability_matrix.json"
  "/release/current/agent_surface/p0_facade.json"
  "/release/current/preflight_scorecard.json"
)

echo "post_deploy_smoke: base_url=${BASE_URL}"
echo "post_deploy_smoke: sleeping ${SLEEP_SECONDS}s for edge propagation"
sleep "${SLEEP_SECONDS}"

FAILED=0
PROBED=0

for route in "${SAMPLE_ROUTES[@]}"; do
  url="${BASE_URL}${route}"
  ok=0
  for attempt in $(seq 1 "${ATTEMPTS_PER_URL}"); do
    PROBED=$((PROBED + 1))
    status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${MAX_TIME}" "${url}" || echo '000')"
    if [[ "${status}" == "200" ]]; then
      echo "post_deploy_smoke: OK    ${url} attempt=${attempt} status=${status}"
      ok=1
      break
    fi
    echo "post_deploy_smoke: RETRY ${url} attempt=${attempt} status=${status}"
    sleep 5
  done
  if [[ "${ok}" -ne 1 ]]; then
    echo "post_deploy_smoke: FAIL  ${url} (all ${ATTEMPTS_PER_URL} attempts)"
    FAILED=$((FAILED + 1))
  fi
done

echo "post_deploy_smoke: summary probed=${PROBED} failed=${FAILED}"

if [[ "${FAILED}" -gt 0 ]]; then
  echo "post_deploy_smoke: exiting non-zero — CI gate must fail this deploy" >&2
  exit 1
fi

echo "post_deploy_smoke: all green"
