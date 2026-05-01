#!/usr/bin/env bash
# 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。
#
# jpcite — curl / bash quickstart
# ----------------------------------------------------------
# Run: `bash quickstart.sh`  (curl + jq recommended; jq optional)
# Set JPCITE_API_KEY=am_xxx for paid (¥3/req).
# Without a key, anonymous tier: 3 req/日 per IP, JST 翌日 00:00 リセット.
#
# Errors handled by inspecting HTTP status line:
#   401 = auth fail (check key)
#   429 = rate limited (anon quota burned)
#   5xx = server side, try again later

set -euo pipefail

BASE="https://api.jpcite.com/v1"
# Use a single string so bash 3.2 (macOS default) doesn't choke on empty arrays under set -u.
JPCITE_KEY="${JPCITE_API_KEY:-${AUTONOMATH_API_KEY:-}}"
if [ -n "${JPCITE_KEY}" ]; then
  AUTH_OPT=(-H "X-API-Key: ${JPCITE_KEY}")
  MODE="authenticated (¥3/req)"
else
  AUTH_OPT=()
  MODE="anonymous (3/日 free)"
fi
# safe expansion: yields nothing when AUTH_OPT is empty
AUTH=("${AUTH_OPT[@]+${AUTH_OPT[@]}}")

# tiny helper: pretty-print JSON when jq available, otherwise raw
pp() { if command -v jq >/dev/null 2>&1; then jq "$@"; else cat; fi; }

echo "==> Mode: ${MODE}"
echo

# ----- 1. Health check (always free, no auth, no quota) -----
echo "[1] GET /healthz  (free, no auth)"
curl -fsS "${BASE%/v1}/healthz" "${AUTH[@]+${AUTH[@]}}" | pp .
echo

# ----- 2. Catalog metadata (counts of programs by tier/prefecture) -----
echo "[2] GET /v1/meta  (catalog totals)"
curl -fsS "${BASE}/meta" "${AUTH[@]+${AUTH[@]}}" | pp '{total_programs, tier_counts, last_ingested_at}'
echo

# ----- 3. Search programs: 省エネ keyword, tier S+A, top 3 -----
# Note: tier appears twice (S, A) — repeat the param to send multiple values.
echo "[3] GET /v1/programs/search?q=省エネ&tier=S&tier=A&limit=3"
curl -fsS -G "${BASE}/programs/search" "${AUTH[@]+${AUTH[@]}}" \
  --data-urlencode "q=省エネ" \
  --data-urlencode "tier=S" \
  --data-urlencode "tier=A" \
  --data-urlencode "limit=3" \
  | pp '{total, results: [.results[] | {unified_id, tier, primary_name}]}'
echo

# ----- 4. List tax incentives (税制) — central use case -----
echo "[4] GET /v1/tax_rulesets/search?q=中小企業&limit=3"
curl -fsS -G "${BASE}/tax_rulesets/search" "${AUTH[@]+${AUTH[@]}}" \
  --data-urlencode "q=中小企業" \
  --data-urlencode "limit=3" \
  | pp '{total, results: [.results[] | {unified_id, ruleset_kind, ruleset_name}]}'
echo

# ----- 5. Filter chain: keyword + tier + pagination -----
# Replace `prefecture=東京都`, `funding_purpose=equipment_investment`, etc.
# to narrow further. Repeat tier= for multiple values.
echo "[5] GET /v1/programs/search  q=省エネ, tier=S/A, limit=5"
curl -fsS -G "${BASE}/programs/search" "${AUTH[@]+${AUTH[@]}}" \
  --data-urlencode "q=省エネ" \
  --data-urlencode "tier=S" \
  --data-urlencode "tier=A" \
  --data-urlencode "limit=5" \
  --data-urlencode "offset=0" \
  | pp '{total, returned: (.results | length), first: .results[0]?.primary_name}'
echo

echo "Done. Reference: https://api.jpcite.com/v1/openapi.json"
