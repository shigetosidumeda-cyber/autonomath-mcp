#!/usr/bin/env bash
# Post-deploy smoke test for jpintel-mcp.
#
# Usage:
#   BASE_URL=https://jpintel-mcp.fly.dev ./scripts/smoke_test.sh
#   BASE_URL=https://api.jpcite.com API_KEY=am_... ./scripts/smoke_test.sh
#
# Exit code 0 = green, non-zero = at least one probe failed.
# Designed for `flyctl status && scripts/smoke_test.sh` post-deploy.

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
API_KEY="${API_KEY:-}"
TIMEOUT="${TIMEOUT:-10}"

pass=0
fail=0

check() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    printf '  \033[32mPASS\033[0m  %s (HTTP %s)\n' "$name" "$actual"
    pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  %s (expected HTTP %s, got %s)\n' "$name" "$expected" "$actual"
    fail=$((fail+1))
  fi
}

check_any() {
  local name="$1"
  local actual="$2"
  shift 2
  local expected
  for expected in "$@"; do
    if [[ "$expected" == "$actual" ]]; then
      printf '  \033[32mPASS\033[0m  %s (HTTP %s)\n' "$name" "$actual"
      pass=$((pass+1))
      return 0
    fi
  done
  printf '  \033[31mFAIL\033[0m  %s (expected one of: %s; got %s)\n' "$name" "$*" "$actual"
  fail=$((fail+1))
  return 1
}

hdr() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"
}

hdr "Health"
status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/healthz")
check "GET /healthz" 200 "$status"

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/v1/ping")
check_any "GET /v1/ping" "$status" 200 429

status=$(curl -sS -o /tmp/smoke_deep_health.json -w '%{http_code}' --max-time "$TIMEOUT" \
  "$BASE_URL/v1/am/health/deep?fail_on_unhealthy=true")
check_any "GET /v1/am/health/deep?fail_on_unhealthy=true" "$status" 200 429
if [[ "$status" == "200" ]]; then
  deep_status=$(python3 -c "import json; print(json.load(open('/tmp/smoke_deep_health.json')).get('status', ''))" 2>/dev/null || echo "")
  if [[ "$deep_status" != "ok" ]]; then
    printf '        \033[31mWARN\033[0m  deep health status=%s\n' "$deep_status"
  fi
fi

hdr "Unauthenticated (free tier)"
status=$(curl -sS -o /tmp/smoke_search.json -w '%{http_code}' --max-time "$TIMEOUT" \
  "$BASE_URL/v1/programs/search?q=%E8%A3%9C%E5%8A%A9%E9%87%91&limit=1")
check_any "GET /v1/programs/search?q=補助金 (anonymous)" "$status" 200 429
if [[ "$status" == "200" ]]; then
  total=$(python3 -c "import json; print(json.load(open('/tmp/smoke_search.json')).get('total', -1))" 2>/dev/null || echo -1)
  printf '        -> total=%s\n' "$total"
  if [[ "$total" -le 0 ]]; then
    printf '        \033[31mWARN\033[0m  no results for 補助金 — suspicious\n'
  fi
else
  printf '        -> anonymous quota already reached; 429 is expected without API_KEY\n'
fi

if [[ -n "$API_KEY" ]]; then
  status=$(curl -sS -o /tmp/smoke_enforcement_detail.json -w '%{http_code}' --max-time "$TIMEOUT" \
    -H "x-api-key: $API_KEY" "$BASE_URL/v1/enforcement-cases/details/search?limit=1")
else
  status=$(curl -sS -o /tmp/smoke_enforcement_detail.json -w '%{http_code}' --max-time "$TIMEOUT" \
    "$BASE_URL/v1/enforcement-cases/details/search?limit=1")
fi
check_any "GET /v1/enforcement-cases/details/search?limit=1" "$status" 200 429
if [[ "$status" == "200" ]]; then
  detail_summary=$(python3 -c "import json; d=json.load(open('/tmp/smoke_enforcement_detail.json')); print(f\"table={d.get('source_table')} total={d.get('total', -1)}\")" 2>/dev/null || echo "table= total=-1")
  printf '        -> %s\n' "$detail_summary"
fi

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/v1/exclusions/rules?limit=1")
check_any "GET /v1/exclusions/rules?limit=1" "$status" 200 429

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/v1/meta")
check_any "GET /v1/meta" "$status" 200 429

if [[ -n "$API_KEY" ]]; then
  hdr "Authenticated (paid tier, API_KEY set)"
  status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" \
    -H "x-api-key: $API_KEY" "$BASE_URL/v1/programs/search?q=補助金&limit=5")
  check "GET /v1/programs/search (x-api-key)" 200 "$status"

  status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" \
    -H "authorization: Bearer $API_KEY" "$BASE_URL/v1/programs/search?q=補助金&limit=5")
  check "GET /v1/programs/search (Bearer)" 200 "$status"
fi

hdr "Security headers"
headers=$(curl -sS -I --max-time "$TIMEOUT" "$BASE_URL/healthz" | tr -d '\r')
for h in "x-content-type-options: nosniff" "x-frame-options: DENY" "referrer-policy: strict-origin-when-cross-origin" "strict-transport-security: max-age="; do
  if grep -qi "^${h}" <<< "$headers"; then
    printf '  \033[32mPASS\033[0m  %s\n' "$h"
    pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  missing header: %s\n' "$h"
    fail=$((fail+1))
  fi
done

hdr "Rate limit header"
rl_hdr=$(curl -sS -I --max-time "$TIMEOUT" -o /dev/null \
  -w 'x-request-id: %header{x-request-id}\n' "$BASE_URL/healthz")
if [[ -n "$rl_hdr" && "$rl_hdr" != "x-request-id: " ]]; then
  printf '  \033[32mPASS\033[0m  %s' "$rl_hdr"
  pass=$((pass+1))
else
  printf '  \033[31mFAIL\033[0m  x-request-id missing\n'
  fail=$((fail+1))
fi

hdr "Invalid key rejection"
status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" \
  -H "x-api-key: am_live_nonexistent_000" "$BASE_URL/v1/programs/search?q=a")
check_any "invalid key -> 401 or anon quota 429" "$status" 401 429

hdr "Summary"
total=$((pass+fail))
printf 'passed=%d  failed=%d  total=%d\n' "$pass" "$fail" "$total"

exit $((fail > 0 ? 1 : 0))
