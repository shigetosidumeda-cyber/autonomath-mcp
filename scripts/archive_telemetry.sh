#!/usr/bin/env bash
# scripts/archive_telemetry.sh
#
# Nightly log archiver: pulls the last 24 h of Fly.io logs for autonomath-api,
# filters to autonomath.query logger lines, gzip-compresses them, and uploads
# the result to Cloudflare R2.
#
# OPERATOR SETUP REQUIRED (one-time, before first run):
#   1. Create an R2 bucket named "autonomath-telemetry" in the Cloudflare dashboard.
#   2. Create an R2 API token (Dashboard → R2 → Manage API Tokens → Create API Token).
#      Scope: Object Read & Write on the "autonomath-telemetry" bucket.
#   3. Authenticate wrangler: `wrangler login` on the ops machine, OR set:
#        CLOUDFLARE_API_TOKEN   — R2 API token from step 2
#        CLOUDFLARE_ACCOUNT_ID  — found in Cloudflare Dashboard → right sidebar
#   4. Ensure FLY_API_TOKEN is set (flyctl tokens create).
#   5. For failure emails set POSTMARK_API_TOKEN (same token used by the main app).
#
# GitHub Actions cron (add to .github/workflows/archive-telemetry.yml):
#   on:
#     schedule:
#       - cron: '30 15 * * *'   # 00:30 JST daily
#
# Usage:
#   ./scripts/archive_telemetry.sh           # normal run
#   ./scripts/archive_telemetry.sh --dry-run # print what would happen, skip upload
#
# wrangler r2 object put exact invocation:
#   wrangler r2 object put autonomath-telemetry/<key> --file <local-file>
#
# Exit codes: 0 = success, 1 = any failure (cron-detectable).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_NAME="${FLY_APP_NAME:-autonomath-api}"
R2_BUCKET="${R2_BUCKET:-autonomath-telemetry}"
OPERATOR_EMAIL="${OPERATOR_EMAIL:-info@bookyou.net}"
POSTMARK_API_TOKEN="${POSTMARK_API_TOKEN:-}"
POSTMARK_FROM="${POSTMARK_FROM:-info@bookyou.net}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

DATESTAMP="$(date -u +%Y-%m-%d)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
RAW_FILE="${TMPDIR_BASE}/autonomath-telemetry-raw-${DATESTAMP}.json"
GZ_FILE="${RAW_FILE}.gz"
R2_KEY="${DATESTAMP}.json.gz"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() {
    log "ERROR: $*"
    _send_failure_email "$*"
    exit 1
}

_send_failure_email() {
    local reason="$1"
    if [[ -z "${POSTMARK_API_TOKEN}" ]]; then
        log "POSTMARK_API_TOKEN not set — cannot send failure email"
        return 0
    fi
    local body
    body="$(cat <<JSON
{
  "From": "${POSTMARK_FROM}",
  "To": "${OPERATOR_EMAIL}",
  "Subject": "[AutonoMath] archive_telemetry.sh FAILED ${DATESTAMP}",
  "TextBody": "archive_telemetry.sh failed on ${DATESTAMP}.\n\nError: ${reason}\n\nPlease investigate. R2 bucket: ${R2_BUCKET}.",
  "MessageStream": "outbound"
}
JSON
)"
    curl -s -o /dev/null --max-time 10 \
        -X POST "https://api.postmarkapp.com/email" \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "X-Postmark-Server-Token: ${POSTMARK_API_TOKEN}" \
        -d "${body}" || log "Warning: failure email itself failed (curl exit $?)"
}

_cleanup() {
    rm -f "${RAW_FILE}" "${GZ_FILE}" || true
}
trap _cleanup EXIT

# ---------------------------------------------------------------------------
# Step 1: Fetch logs from Fly.io
# ---------------------------------------------------------------------------
log "Fetching fly logs --app ${APP_NAME} --json --since 24h"
if [[ ${DRY_RUN} -eq 1 ]]; then
    log "[DRY RUN] would run: fly logs --app ${APP_NAME} --json --since 24h > ${RAW_FILE}"
    log "[DRY RUN] would filter for autonomath.query logger lines"
    log "[DRY RUN] would compress to ${GZ_FILE}"
    log "[DRY RUN] would upload: wrangler r2 object put ${R2_BUCKET}/${R2_KEY} --file ${GZ_FILE}"
    log "[DRY RUN] would delete local file ${GZ_FILE}"
    exit 0
fi

if ! command -v fly &>/dev/null; then
    fail "fly CLI not found in PATH — install flyctl and set FLY_API_TOKEN"
fi

# Fetch and filter in one pipeline: keep only autonomath.query logger lines.
# Fly's --json output is JSON-lines; each record has a "log" field with the
# nested structlog JSON. We extract lines where the inner JSON has
# logger == "autonomath.query".
fly logs --app "${APP_NAME}" --json --since 24h 2>/dev/null \
    | python3 -c "
import sys, json
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        continue
    # Fly log records have a 'message' or 'log' field containing the app output
    inner_text = outer.get('message') or outer.get('log') or ''
    if not inner_text:
        continue
    try:
        inner = json.loads(inner_text)
    except (json.JSONDecodeError, TypeError):
        continue
    if inner.get('logger') == 'autonomath.query':
        print(json.dumps(inner))
" > "${RAW_FILE}" || fail "fly logs fetch or filter failed"

LINE_COUNT="$(wc -l < "${RAW_FILE}" | tr -d ' ')"
log "Filtered ${LINE_COUNT} autonomath.query log lines to ${RAW_FILE}"

if [[ "${LINE_COUNT}" -eq 0 ]]; then
    log "Warning: zero query log lines for ${DATESTAMP} — uploading empty archive anyway"
fi

# ---------------------------------------------------------------------------
# Step 2: Compress
# ---------------------------------------------------------------------------
log "Compressing to ${GZ_FILE}"
gzip -9 -c "${RAW_FILE}" > "${GZ_FILE}" || fail "gzip compression failed"
GZ_SIZE="$(wc -c < "${GZ_FILE}" | tr -d ' ')"
log "Compressed size: ${GZ_SIZE} bytes"

# ---------------------------------------------------------------------------
# Step 3: Checksum
# ---------------------------------------------------------------------------
if command -v sha256sum &>/dev/null; then
    CHECKSUM="$(sha256sum "${GZ_FILE}" | awk '{print $1}')"
else
    CHECKSUM="$(shasum -a 256 "${GZ_FILE}" | awk '{print $1}')"
fi
log "sha256: ${CHECKSUM}"

# ---------------------------------------------------------------------------
# Step 4: Upload to R2 via wrangler
# ---------------------------------------------------------------------------
if ! command -v wrangler &>/dev/null; then
    fail "wrangler CLI not found in PATH — run 'npm install -g wrangler' or use npx"
fi

log "Uploading to R2: ${R2_BUCKET}/${R2_KEY}"
wrangler r2 object put "${R2_BUCKET}/${R2_KEY}" \
    --file "${GZ_FILE}" \
    --content-type "application/gzip" \
    || fail "wrangler r2 object put failed for ${R2_KEY}"

log "Upload successful: r2://${R2_BUCKET}/${R2_KEY} (sha256=${CHECKSUM})"

# ---------------------------------------------------------------------------
# Step 5: Delete local file (trap handles it on exit; explicit for clarity)
# ---------------------------------------------------------------------------
rm -f "${RAW_FILE}" "${GZ_FILE}"
log "Local temp files removed"

log "Done: archived ${LINE_COUNT} query events to r2://${R2_BUCKET}/${R2_KEY}"
exit 0
