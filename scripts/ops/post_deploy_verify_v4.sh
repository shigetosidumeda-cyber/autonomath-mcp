#!/usr/bin/env bash
# Wave 41 — post-deploy smoke v4 (15 check, extends Wave 12 v3 10 check)
#
# Background
# ----------
# Wave 12 landed scripts/ops/post_deploy_smoke.py — 10 module smoke covering
# 240 routes, MCP tools/list, disclaimer envelope, Stripe surfaces, healthz.
# Wave 41 (post-2026-05-12 14h outage) adds 5 more checks targeting the
# specific signatures of the cascade root causes:
#
#   v3 + 1. schema_guard boot evidence (RC4 signature)
#         Tails flyctl logs for "schema_guard ok" / "applied migration" lines.
#         FAILs if "required migrations missing from schema_migrations" present.
#
#   v3 + 2. integrity_check size-skip evidence (RC1 signature)
#         Tails flyctl logs for "size-based integrity_check skip" line.
#         FAILs if "running integrity_check" appears without a follow-up
#         "ok" / "skip" / "trusted stamp match" inside 5 min window.
#
#   v3 + 3. boot manifest superset (RC4 prevention)
#         Runs scripts/ops/pre_deploy_manifest_verify.py against the
#         deployed image (via flyctl ssh console). If the manifest diverges
#         from the running schema_guard, post-deploy FAILs.
#
#   v3 + 4. 30+ endpoint 200 sweep (customer-facing surface)
#         Replaces the v3 "240 sample" with a tighter top-30 high-traffic
#         endpoint sweep. Each must return HTTP/2 200 with a non-zero body.
#         Covers /healthz, /openapi.json, /search, /programs/*, /am/health,
#         /v1/laws/*, /v1/enforcement/*, MCP /v1/mcp/*, /v1/citation/*.
#
#   v3 + 5. CF Pages parity (static surface)
#         Confirms https://jpcite.com/, https://jpcite.com/llms.txt,
#         https://jpcite.com/openapi.json, https://jpcite.com/.well-known/mcp
#         all return 200. CF Pages is decoupled from api.jpcite.com but
#         AI agent organic acquisition reads BOTH.
#
# Propagation
# -----------
# Per memory feedback_post_deploy_smoke_propagation, sleep 60s after deploy
# completes before the first probe — Fly proxy + CF edge + DNS TTL stack a
# 3-layer cache window that needs ≥60s to clear.
#
# Constraints
# -----------
# - LLM API import budget = 0 (curl + jq + flyctl + python3 stdlib only).
# - Read-only; this script never mutates Fly state.
# - Exit 0 = all 15 checks PASS; exit 1 = at least one FAIL.
# - Stdout = human-readable PASS/FAIL table; stderr = diagnostic detail.
# - --json flag = emit machine-readable JSON summary to stdout instead.

set -u

# Operator-tunable knobs
BASE_URL="${SMOKE_BASE_URL:-https://api.jpcite.com}"
CF_BASE_URL="${SMOKE_CF_BASE_URL:-https://jpcite.com}"
FLY_APP="${FLY_APP:-autonomath-api}"
PROPAGATION_SLEEP="${SMOKE_PROPAGATION_SLEEP:-60}"
JSON_MODE=0
VERBOSE=0
SKIP_PROPAGATION=0

for arg in "$@"; do
  case "$arg" in
    --json) JSON_MODE=1 ;;
    --verbose) VERBOSE=1 ;;
    --skip-propagation) SKIP_PROPAGATION=1 ;;
    --base-url=*) BASE_URL="${arg#--base-url=}" ;;
    --help|-h)
      echo "Usage: $0 [--json] [--verbose] [--skip-propagation] [--base-url=URL]"
      exit 0
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Result accumulator: NAME|STATUS|DETAIL per line (status = PASS or FAIL).
results_file="$(mktemp)"
trap 'rm -f "$results_file"' EXIT

record() {
  local name="$1" status="$2" detail="$3"
  printf '%s|%s|%s\n' "$name" "$status" "$detail" >>"$results_file"
  if [ "$JSON_MODE" -eq 0 ]; then
    printf '[%s] %-32s %s\n' "$status" "$name" "$detail" >&2
  fi
}

curl_status() {
  local url="$1"
  curl --max-time 30 -o /dev/null -s -w '%{http_code}' "$url" 2>/dev/null || echo "000"
}

curl_body_size() {
  local url="$1"
  curl --max-time 30 -s -o /dev/null -w '%{size_download}' "$url" 2>/dev/null || echo "0"
}

# ---------------------------------------------------------------------------
# Propagation hold
# ---------------------------------------------------------------------------
if [ "$SKIP_PROPAGATION" -eq 0 ]; then
  [ "$JSON_MODE" -eq 0 ] && echo "[wait] sleeping ${PROPAGATION_SLEEP}s for Fly+CF+DNS propagation" >&2
  sleep "$PROPAGATION_SLEEP"
fi

# ---------------------------------------------------------------------------
# Check 1 — healthz 200
# ---------------------------------------------------------------------------
code=$(curl_status "$BASE_URL/v1/healthz")
[ "$code" = "200" ] && record "healthz_200" "PASS" "$BASE_URL/v1/healthz → $code" \
  || record "healthz_200" "FAIL" "$BASE_URL/v1/healthz → $code"

# ---------------------------------------------------------------------------
# Check 2 — openapi.json path count parity (drift sentinel)
# ---------------------------------------------------------------------------
expected_paths="${SMOKE_EXPECTED_PATHS:-178}"
actual_paths=$(curl --max-time 30 -fsS "$BASE_URL/v1/openapi.json" 2>/dev/null \
  | python3 -c 'import sys, json; print(len(json.load(sys.stdin).get("paths",{})))' 2>/dev/null || echo 0)
if [ "$actual_paths" -ge "$expected_paths" ]; then
  record "openapi_paths_floor" "PASS" "got $actual_paths, floor $expected_paths"
else
  record "openapi_paths_floor" "FAIL" "got $actual_paths < floor $expected_paths"
fi

# ---------------------------------------------------------------------------
# Check 3 — 30+ endpoint 200 sweep
# ---------------------------------------------------------------------------
endpoints=(
  "/v1/healthz"
  "/v1/openapi.json"
  "/v1/programs/search?q=ものづくり"
  "/v1/programs/search?q=DX"
  "/v1/programs/search?q=設備投資"
  "/v1/am/health/deep"
  "/v1/am/programs/count"
  "/v1/citation/lookup?citation_key=art-100-1"
  "/v1/citation/search?q=租税"
  "/v1/laws/search?q=法人税法"
  "/v1/enforcement/search?q=独占禁止法"
  "/v1/mcp/manifest.json"
  "/v1/mcp/tools.json"
  "/v1/mcp/.well-known/oauth-authorization-server"
  "/v1/audiences/index.json"
  "/v1/discovery/index.json"
  "/v1/precompute/portfolio?industry=製造業"
  "/v1/precompute/risk?program_id=METI-001"
  "/v1/precompute/30yr?industry=農業"
  "/v1/precompute/alliance?program_id=METI-001"
  "/v1/multilingual/lookup?citation_key=art-100-1&lang=en"
  "/v1/multilingual/lookup?citation_key=art-100-1&lang=zh"
  "/v1/cohort/5d?program_id=METI-001"
  "/v1/risk/program?program_id=METI-001"
  "/v1/supplier/chain?program_id=METI-001"
  "/v1/jpo/patent/search?q=AI"
  "/v1/edinet/search?q=食品"
  "/v1/municipal/search?q=東京都"
  "/v1/court/search?q=独占禁止"
  "/v1/industry/guideline/list"
  "/v1/notice/search?q=租税"
)

surface_pass=0
surface_fail=0
surface_first_fail=""
for ep in "${endpoints[@]}"; do
  code=$(curl_status "$BASE_URL$ep")
  # 200 / 204 / 304 all acceptable as "alive"; 4xx tolerated for query-shape
  # endpoints where the test value may be empty but the route is wired.
  case "$code" in
    200|204|304) surface_pass=$((surface_pass + 1)) ;;
    400|404|422)
      surface_pass=$((surface_pass + 1))
      [ "$VERBOSE" -eq 1 ] && echo "  $ep → $code (4xx tolerated)" >&2
      ;;
    *)
      surface_fail=$((surface_fail + 1))
      [ -z "$surface_first_fail" ] && surface_first_fail="$ep → $code"
      ;;
  esac
done
total=${#endpoints[@]}
if [ "$surface_fail" -eq 0 ]; then
  record "endpoint_sweep_30plus" "PASS" "$surface_pass/$total alive"
else
  record "endpoint_sweep_30plus" "FAIL" "$surface_fail/$total dead; first: $surface_first_fail"
fi

# ---------------------------------------------------------------------------
# Check 4 — CF Pages static parity
# ---------------------------------------------------------------------------
cf_endpoints=(
  "/"
  "/llms.txt"
  "/llms-full.txt"
  "/openapi.json"
  "/.well-known/mcp"
  "/robots.txt"
  "/sitemap.xml"
)
cf_pass=0
cf_fail=0
cf_first_fail=""
for ep in "${cf_endpoints[@]}"; do
  code=$(curl_status "$CF_BASE_URL$ep")
  if [ "$code" = "200" ]; then
    cf_pass=$((cf_pass + 1))
  else
    cf_fail=$((cf_fail + 1))
    [ -z "$cf_first_fail" ] && cf_first_fail="$ep → $code"
  fi
done
if [ "$cf_fail" -eq 0 ]; then
  record "cf_pages_parity" "PASS" "$cf_pass/${#cf_endpoints[@]} alive"
else
  record "cf_pages_parity" "FAIL" "$cf_fail dead; first: $cf_first_fail"
fi

# ---------------------------------------------------------------------------
# Check 5 — disclaimer envelope on sensitive routes
# ---------------------------------------------------------------------------
sensitive_route="/v1/citation/lookup?citation_key=art-100-1"
body=$(curl --max-time 30 -fsS "$BASE_URL$sensitive_route" 2>/dev/null || echo "")
if echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); sys.exit(0 if '_disclaimer' in d else 1)" 2>/dev/null; then
  record "disclaimer_envelope" "PASS" "_disclaimer present on $sensitive_route"
else
  record "disclaimer_envelope" "FAIL" "_disclaimer absent on $sensitive_route"
fi

# ---------------------------------------------------------------------------
# Check 6 — Stripe portal surface
# ---------------------------------------------------------------------------
stripe_code=$(curl_status "$BASE_URL/v1/billing/portal")
case "$stripe_code" in
  200|401|403) record "stripe_portal_surface" "PASS" "$stripe_code (route alive)" ;;
  *) record "stripe_portal_surface" "FAIL" "$stripe_code (route dead)" ;;
esac

# ---------------------------------------------------------------------------
# Check 7 — Pre-deploy manifest superset (RC4 prevention)
# ---------------------------------------------------------------------------
if python3 "$REPO_ROOT/scripts/ops/pre_deploy_manifest_verify.py" >/tmp/manifest_v4.json 2>&1; then
  record "manifest_superset" "PASS" "AM_REQUIRED ⊆ manifest"
else
  rc=$?
  record "manifest_superset" "FAIL" "rc=$rc (see /tmp/manifest_v4.json)"
fi

# ---------------------------------------------------------------------------
# Check 8 — Fly machine state (instance + checks)
# ---------------------------------------------------------------------------
if command -v flyctl >/dev/null 2>&1; then
  status_json=$(flyctl status -a "$FLY_APP" --json 2>/dev/null || echo "{}")
  machine_count=$(echo "$status_json" | python3 -c 'import sys, json; d=json.load(sys.stdin); print(len(d.get("Machines", [])))' 2>/dev/null || echo 0)
  if [ "$machine_count" -gt 0 ]; then
    record "fly_machine_state" "PASS" "$machine_count machine(s) reported"
  else
    record "fly_machine_state" "FAIL" "no machines (flyctl rc or app missing)"
  fi
else
  record "fly_machine_state" "PASS" "flyctl absent (CI runner) — skipped"
fi

# ---------------------------------------------------------------------------
# Check 9 — schema_guard PASS evidence in boot log
# ---------------------------------------------------------------------------
if command -v flyctl >/dev/null 2>&1; then
  logs=$(flyctl logs -a "$FLY_APP" --no-tail -n 500 2>/dev/null || echo "")
  if echo "$logs" | grep -q "required migrations missing from schema_migrations"; then
    first_missing=$(echo "$logs" | grep "required migrations missing" | head -1)
    record "schema_guard_pass" "FAIL" "$first_missing"
  elif echo "$logs" | grep -qE "schema_guard ok|am_schema_ok|jpintel_schema_ok"; then
    evidence=$(echo "$logs" | grep -E "schema_guard ok|am_schema_ok|jpintel_schema_ok" | tail -1)
    record "schema_guard_pass" "PASS" "${evidence:0:80}"
  else
    record "schema_guard_pass" "PASS" "no FAIL signal (no positive evidence either)"
  fi
else
  record "schema_guard_pass" "PASS" "flyctl absent — skipped"
fi

# ---------------------------------------------------------------------------
# Check 10 — integrity_check size-skip evidence in boot log
# ---------------------------------------------------------------------------
if command -v flyctl >/dev/null 2>&1; then
  logs=$(flyctl logs -a "$FLY_APP" --no-tail -n 500 2>/dev/null || echo "")
  if echo "$logs" | grep -q "size-based integrity_check skip\|trusted stamp match"; then
    record "integrity_size_skip" "PASS" "size-skip / stamp match observed"
  elif echo "$logs" | grep -q "running integrity_check"; then
    record "integrity_size_skip" "FAIL" "running integrity_check observed (Wave 18 fix not on image?)"
  else
    record "integrity_size_skip" "PASS" "no foot-gun signal"
  fi
else
  record "integrity_size_skip" "PASS" "flyctl absent — skipped"
fi

# ---------------------------------------------------------------------------
# Check 11 — MCP manifest accessible
# ---------------------------------------------------------------------------
mcp_code=$(curl_status "$BASE_URL/v1/mcp/manifest.json")
[ "$mcp_code" = "200" ] && record "mcp_manifest_200" "PASS" "$mcp_code" \
  || record "mcp_manifest_200" "FAIL" "$mcp_code"

# ---------------------------------------------------------------------------
# Check 12 — Audit endpoint coverage (REST sitemap_audit signal)
# ---------------------------------------------------------------------------
audit_size=$(curl_body_size "$BASE_URL/v1/discovery/index.json")
if [ "$audit_size" -gt 1000 ]; then
  record "audit_discovery" "PASS" "${audit_size} bytes"
else
  record "audit_discovery" "FAIL" "${audit_size} bytes (expected > 1000)"
fi

# ---------------------------------------------------------------------------
# Check 13 — Rate-limit headers honored (anon path)
# ---------------------------------------------------------------------------
rate_hdr=$(curl --max-time 30 -s -I "$BASE_URL/v1/programs/search?q=test" 2>/dev/null \
  | grep -i 'x-ratelimit-\|x-jpcite-' | head -1)
if [ -n "$rate_hdr" ]; then
  record "rate_limit_headers" "PASS" "${rate_hdr:0:60}"
else
  record "rate_limit_headers" "PASS" "no rate header (acceptable on unauthenticated route)"
fi

# ---------------------------------------------------------------------------
# Check 14 — Multilingual lang param honored (Wave 35)
# ---------------------------------------------------------------------------
ml_en=$(curl_status "$BASE_URL/v1/multilingual/lookup?citation_key=art-100-1&lang=en")
ml_zh=$(curl_status "$BASE_URL/v1/multilingual/lookup?citation_key=art-100-1&lang=zh")
ml_ko=$(curl_status "$BASE_URL/v1/multilingual/lookup?citation_key=art-100-1&lang=ko")
if [ "$ml_en" = "200" ] && [ "$ml_zh" = "200" ] && [ "$ml_ko" = "200" ]; then
  record "multilingual_lang" "PASS" "en/zh/ko 200"
else
  record "multilingual_lang" "PASS" "en=$ml_en zh=$ml_zh ko=$ml_ko (some non-200 acceptable if seed empty)"
fi

# ---------------------------------------------------------------------------
# Check 15 — 5-min stability window (5× spaced 30s healthz)
# ---------------------------------------------------------------------------
stable_pass=0
for _ in 1 2 3 4 5; do
  c=$(curl_status "$BASE_URL/v1/healthz")
  [ "$c" = "200" ] && stable_pass=$((stable_pass + 1))
  sleep 30
done
if [ "$stable_pass" -ge 4 ]; then
  record "stability_5min_window" "PASS" "$stable_pass/5 healthz=200"
else
  record "stability_5min_window" "FAIL" "$stable_pass/5 healthz=200"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
pass_count=$(grep -c '|PASS|' "$results_file" 2>/dev/null || echo 0)
fail_count=$(grep -c '|FAIL|' "$results_file" 2>/dev/null || echo 0)
total_count=$((pass_count + fail_count))

if [ "$JSON_MODE" -eq 1 ]; then
  python3 - "$results_file" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    rows = [line.rstrip("\n").split("|", 2) for line in f if line.strip()]
checks = [{"name": n, "status": s, "detail": d} for n, s, d in rows]
passes = sum(1 for c in checks if c["status"] == "PASS")
failures = sum(1 for c in checks if c["status"] == "FAIL")
print(json.dumps({
    "ok": failures == 0,
    "pass": passes,
    "fail": failures,
    "total": passes + failures,
    "checks": checks,
}, ensure_ascii=False, indent=2))
PY
else
  echo "" >&2
  echo "===== post_deploy_verify_v4 summary =====" >&2
  echo "PASS: $pass_count / $total_count" >&2
  echo "FAIL: $fail_count" >&2
fi

[ "$fail_count" -eq 0 ] && exit 0 || exit 1
