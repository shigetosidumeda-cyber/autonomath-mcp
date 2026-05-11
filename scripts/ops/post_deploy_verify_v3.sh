#!/bin/bash
# post_deploy_verify_v3.sh — 10-check production verify for deploy.yml run
#                            25646632328 (commit 6bf378ab33998fb8c0cbff56323d38c3333a12fc).
#
# All checks are curl + jq + flyctl. Per repo CLAUDE.md "Non-negotiable constraints"
# and memory feedback_no_operator_llm_api, this script imports NO LLM API SDKs.
#
# Run:   bash scripts/ops/post_deploy_verify_v3.sh
# Make executable (one-time): chmod +x scripts/ops/post_deploy_verify_v3.sh
#
# Exit 0 = all 10 checks PASS.  Exit 1 = at least one FAIL.

set -euo pipefail

API_HOST="${JPCITE_API_HOST:-https://api.jpcite.com}"
SITE_HOST="${JPCITE_SITE_HOST:-https://jpcite.com}"
FLY_APP="${JPCITE_FLY_APP:-autonomath-api}"  # canonical Fly app name; "jpcite-api" was a never-realized rename target — actual deployed app stayed "autonomath-api". See scripts/ops/production_deploy_go_gate.py CANONICAL_FLY_APP / LEGACY_FLY_APP_ALIASES.
EXPECTED_SHA8="${JPCITE_EXPECTED_SHA8:-6bf378ab}"

FAIL=0
PASS=0
RESULTS=()

record_pass() {
  local n="$1" msg="$2"
  PASS=$((PASS+1))
  RESULTS+=("[PASS] check ${n}: ${msg}")
}

record_fail() {
  local n="$1" msg="$2"
  FAIL=$((FAIL+1))
  RESULTS+=("[FAIL] check ${n}: ${msg}")
  echo "[FAIL] check ${n}: ${msg}" 1>&2
}

# ---- check 1: flyctl image show contains expected commit SHA8 -----------------
check_1_flyctl_image() {
  local out
  if ! command -v flyctl >/dev/null 2>&1; then
    record_fail 1 "flyctl not on PATH (cannot verify image SHA)"
    return
  fi
  if ! out="$(flyctl image show -a "$FLY_APP" 2>&1)"; then
    record_fail 1 "flyctl image show -a ${FLY_APP} failed: $(echo "$out" | head -1)"
    return
  fi
  if echo "$out" | grep -qi "$EXPECTED_SHA8"; then
    record_pass 1 "flyctl image show contains ${EXPECTED_SHA8}"
  else
    record_fail 1 "flyctl image show missing ${EXPECTED_SHA8}; head=$(echo "$out" | head -1)"
  fi
}

# ---- check 2: /healthz returns 200 --------------------------------------------
check_2_healthz() {
  local code
  code="$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 30 "${API_HOST}/healthz" 2>/dev/null || echo "000")"
  if [ "$code" = "200" ]; then
    record_pass 2 "${API_HOST}/healthz -> 200"
  else
    record_fail 2 "${API_HOST}/healthz -> ${code} (expected 200)"
  fi
}

# ---- check 3: /v1/am/health/deep returns 200 + parsable JSON ------------------
check_3_deep_health() {
  local body code
  body="$(curl -fsS --max-time 30 "${API_HOST}/v1/am/health/deep" 2>/dev/null || true)"
  code="$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 30 "${API_HOST}/v1/am/health/deep" 2>/dev/null || echo "000")"
  if [ "$code" != "200" ]; then
    record_fail 3 "/v1/am/health/deep -> ${code} (expected 200)"
    return
  fi
  if echo "$body" | jq -e . >/dev/null 2>&1; then
    record_pass 3 "/v1/am/health/deep -> 200 + valid JSON"
  else
    record_fail 3 "/v1/am/health/deep -> 200 but JSON parse failed"
  fi
}

# ---- check 4: openapi.json .paths length >= 182 -------------------------------
check_4_openapi_paths() {
  local n
  n="$(curl -fsS --max-time 30 "${API_HOST}/v1/openapi.json" 2>/dev/null | jq -r '.paths | length' 2>/dev/null || echo "")"
  if [ -z "$n" ] || ! [[ "$n" =~ ^[0-9]+$ ]]; then
    record_fail 4 "openapi.json paths length unreadable (got '${n}')"
    return
  fi
  if [ "$n" -ge 182 ]; then
    record_pass 4 "openapi.json paths=${n} (>=182)"
  else
    record_fail 4 "openapi.json paths=${n} (<182)"
  fi
}

# ---- check 5: openapi.agent.json .paths length == 34 --------------------------
check_5_openapi_agent_paths() {
  local n
  n="$(curl -fsS --max-time 30 "${API_HOST}/v1/openapi.agent.json" 2>/dev/null | jq -r '.paths | length' 2>/dev/null || echo "")"
  if [ -z "$n" ] || ! [[ "$n" =~ ^[0-9]+$ ]]; then
    record_fail 5 "openapi.agent.json paths length unreadable (got '${n}')"
    return
  fi
  if [ "$n" -eq 34 ]; then
    record_pass 5 "openapi.agent.json paths=${n} (==34)"
  else
    record_fail 5 "openapi.agent.json paths=${n} (expected 34)"
  fi
}

# ---- check 6: openapi.agent.gpt30.json .paths length == 30 --------------------
check_6_openapi_gpt30_paths() {
  local n
  n="$(curl -fsS --max-time 30 "${API_HOST}/v1/openapi.agent.gpt30.json" 2>/dev/null | jq -r '.paths | length' 2>/dev/null || echo "")"
  if [ -z "$n" ] || ! [[ "$n" =~ ^[0-9]+$ ]]; then
    record_fail 6 "openapi.agent.gpt30.json paths length unreadable (got '${n}')"
    return
  fi
  if [ "$n" -eq 30 ]; then
    record_pass 6 "openapi.agent.gpt30.json paths=${n} (==30)"
  else
    record_fail 6 "openapi.agent.gpt30.json paths=${n} (expected 30)"
  fi
}

# ---- check 7: mcp.json contact.email -----------------------------------------
check_7_mcp_contact() {
  local email
  email="$(curl -fsS --max-time 30 "${SITE_HOST}/.well-known/mcp.json" 2>/dev/null | jq -r '.contact.email' 2>/dev/null || echo "")"
  if [ "$email" = "info@bookyou.net" ]; then
    record_pass 7 "mcp.json contact.email=info@bookyou.net"
  else
    record_fail 7 "mcp.json contact.email='${email}' (expected info@bookyou.net)"
  fi
}

# ---- check 8: llms.txt mentions 'Brand: jpcite' -------------------------------
check_8_llms_brand() {
  local n
  n="$(curl -fsS --max-time 30 "${SITE_HOST}/llms.txt" 2>/dev/null | grep -c "Brand: jpcite" || true)"
  if [ -z "$n" ]; then
    n=0
  fi
  if [ "$n" -ge 1 ]; then
    record_pass 8 "llms.txt 'Brand: jpcite' occurrences=${n}"
  else
    record_fail 8 "llms.txt 'Brand: jpcite' occurrences=0"
  fi
}

# ---- check 9: /sources returns 200 --------------------------------------------
check_9_sources_page() {
  local code
  code="$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 30 "${SITE_HOST}/sources" 2>/dev/null || echo "000")"
  if [ "$code" = "200" ]; then
    record_pass 9 "${SITE_HOST}/sources -> 200"
  else
    record_fail 9 "${SITE_HOST}/sources -> ${code} (expected 200)"
  fi
}

# ---- check 10: /.well-known/security.txt returns 200 --------------------------
check_10_security_txt() {
  local code
  code="$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 30 "${SITE_HOST}/.well-known/security.txt" 2>/dev/null || echo "000")"
  if [ "$code" = "200" ]; then
    record_pass 10 "${SITE_HOST}/.well-known/security.txt -> 200"
  else
    record_fail 10 "${SITE_HOST}/.well-known/security.txt -> ${code} (expected 200)"
  fi
}

main() {
  echo "post_deploy_verify_v3 — target run=25646632328 sha=${EXPECTED_SHA8} fly_app=${FLY_APP}"
  echo "api_host=${API_HOST}  site_host=${SITE_HOST}"
  echo

  check_1_flyctl_image
  check_2_healthz
  check_3_deep_health
  check_4_openapi_paths
  check_5_openapi_agent_paths
  check_6_openapi_gpt30_paths
  check_7_mcp_contact
  check_8_llms_brand
  check_9_sources_page
  check_10_security_txt

  echo
  echo "----- detail -----"
  for line in "${RESULTS[@]}"; do
    echo "$line"
  done
  echo

  local total=$((PASS+FAIL))
  echo "summary: ${PASS}/${total} pass, ${FAIL} fail"
  if [ "$FAIL" -eq 0 ]; then
    echo "RESULT: ALL_GREEN"
    exit 0
  fi
  echo "RESULT: AT_LEAST_ONE_FAIL"
  exit 1
}

main "$@"
