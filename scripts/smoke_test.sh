#!/usr/bin/env bash
# Post-deploy smoke test for jpintel-mcp.
#
# Usage:
#   BASE_URL=https://jpintel-mcp.fly.dev ./scripts/smoke_test.sh
#   BASE_URL=https://jpintel-mcp.fly.dev API_KEY=sk_live_... ./scripts/smoke_test.sh
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

hdr() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"
}

hdr "Health"
status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/healthz")
check "GET /healthz" 200 "$status"

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/")
check "GET /" 200 "$status"

hdr "Unauthenticated (free tier)"
status=$(curl -sS -o /tmp/smoke_search.json -w '%{http_code}' --max-time "$TIMEOUT" \
  "$BASE_URL/v1/programs/search?q=%E8%BE%B2%E6%A5%AD&limit=1")
check "GET /v1/programs/search?q=農業 (anonymous)" 200 "$status"
total=$(python3 -c "import json; print(json.load(open('/tmp/smoke_search.json')).get('total', -1))" 2>/dev/null || echo -1)
printf '        -> total=%s\n' "$total"
if [[ "$total" -le 0 ]]; then
  printf '        \033[31mWARN\033[0m  no results for 農業 — suspicious\n'
fi

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/v1/exclusions?limit=1")
check "GET /v1/exclusions?limit=1" 200 "$status"

status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$BASE_URL/meta")
check "GET /meta" 200 "$status"

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
  -H "x-api-key: sk_live_nonexistent_000" "$BASE_URL/v1/programs/search?q=a")
check "invalid key -> 401" 401 "$status"

hdr "Summary"
total=$((pass+fail))
printf 'passed=%d  failed=%d  total=%d\n' "$pass" "$fail" "$total"

exit $((fail > 0 ? 1 : 0))
