#!/usr/bin/env bash
set -euo pipefail
source "${HOME}/.jpcite_secrets.env"

: "${CLOUDFLARE_API_TOKEN:?missing}"
: "${CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI:?missing}"

ZONE_ID="${CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI}"
TOKEN="${CLOUDFLARE_API_TOKEN}"

# Page Rule: zeimu-kaikei.ai/* → 301 → https://jpcite.com/$1
curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/pagerules" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "targets": [{"target":"url","constraint":{"operator":"matches","value":"*zeimu-kaikei.ai/*"}}],
    "actions": [{"id":"forwarding_url","value":{"url":"https://jpcite.com/$2","status_code":301}}],
    "priority": 1,
    "status": "active"
  }' | jq .

# WWW variant
curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/pagerules" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "targets": [{"target":"url","constraint":{"operator":"matches","value":"*www.zeimu-kaikei.ai/*"}}],
    "actions": [{"id":"forwarding_url","value":{"url":"https://jpcite.com/$2","status_code":301}}],
    "priority": 2,
    "status": "active"
  }' | jq .

echo "[OK] 301 redirect rules created"
