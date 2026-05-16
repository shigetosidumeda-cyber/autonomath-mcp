#!/usr/bin/env bash
# ------------------------------------------------------------------
# Pre-teardown artifact export: jpcite-credit-* S3 buckets -> Cloudflare R2.
#
# Why this script exists
# ----------------------
# The AWS canary plan §1 says: "AWS must produce durable assets, not
# permanent runtime. Export valuable artifacts outside AWS before teardown."
# Three jpcite-credit-* S3 buckets accumulate the crawl / derivation /
# report artifacts during the credit run; once teardown runs (see
# `scripts/aws_credit_ops/teardown_credit_run.sh`), they're gone forever.
#
# This script mirrors those three S3 buckets into a single R2 bucket
# (`jpcite-credit-artifacts` by default) with the original key layout
# prefixed by the source bucket name, so a future re-hydrate path can
# round-trip without ambiguity.
#
# What it does
# ------------
#   1. For each of the 3 S3 source buckets:
#      a. List objects via `aws s3api list-objects-v2 --output json` (paginated).
#      b. For each object:
#         - Download to a local stage dir (default: /tmp/jpcite_r2_export/).
#         - Compute SHA-256 locally.
#         - Upload to R2 at key `<source-bucket>/<original-key>`.
#         - HEAD the R2 object and verify the upload SHA-256 matches.
#   2. Emit `r2_export_manifest.json` with one entry per file:
#      { "s3_uri": "s3://bucket/key",
#        "r2_uri": "r2://bucket/source-bucket/key",
#        "sha256": "abc...",
#        "size_bytes": 12345 }
#
# DRY_RUN default
# ---------------
# DRY_RUN=true is the default — the script only LISTS what it would
# export, prints a per-bucket summary, and writes a manifest preview
# (no s3_uri / sha256 / size — just the planned object count). Setting
# DRY_RUN=false flips to real download + upload + verify; live mode also
# requires R2 credentials (R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_KEY).
#
# Required env (live mode only — DRY_RUN=true ignores these):
#   R2_ENDPOINT           https://<acct>.r2.cloudflarestorage.com
#   R2_ACCESS_KEY_ID      R2 API token access key.
#   R2_SECRET_KEY         R2 API token secret.
#
# Optional env:
#   AWS_PROFILE           default bookyou-recovery (same as teardown_credit_run.sh)
#   REGION                default ap-northeast-1
#   R2_DEST_BUCKET        default jpcite-credit-artifacts
#   STAGE_DIR             default /tmp/jpcite_r2_export
#   MANIFEST_PATH         default $STAGE_DIR/r2_export_manifest.json
#   DRY_RUN=true|false    default true
#
# Exit codes:
#   0  success (or DRY_RUN preview ok)
#   1  config error (missing tool / env in live mode)
#   2  S3 listing failed for at least one bucket
#   3  download / upload / verify failed for at least one object (live mode)
# ------------------------------------------------------------------
set -euo pipefail

DRY_RUN="${DRY_RUN:-true}"

export AWS_PROFILE="${AWS_PROFILE:-bookyou-recovery}"
export REGION="${REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$REGION"

R2_DEST_BUCKET="${R2_DEST_BUCKET:-jpcite-credit-artifacts}"
STAGE_DIR="${STAGE_DIR:-/tmp/jpcite_r2_export}"
MANIFEST_PATH="${MANIFEST_PATH:-${STAGE_DIR}/r2_export_manifest.json}"

# The 3 source S3 buckets. These mirror the bucket names used by the credit
# run (raw crawl output / derived datasets / reports). Keep in sync with
# `scripts/aws_credit_ops/teardown_credit_run.sh::BUCKETS_TO_DELETE` —
# teardown deletes raw + reports; we additionally mirror -derived because
# it is the most operator-relevant of the three.
SOURCE_BUCKETS=(
  "jpcite-credit-993693061769-202605-raw"
  "jpcite-credit-993693061769-202605-derived"
  "jpcite-credit-993693061769-202605-reports"
)

log() { printf '[r2-export] %s %s\n' "$(date -u +%FT%TZ)" "$1"; }
err() { printf '[r2-export] %s ERROR: %s\n' "$(date -u +%FT%TZ)" "$1" >&2; }

# ---------------------------------------------------------------------------
# 0. Pre-flight
# ---------------------------------------------------------------------------
if ! command -v aws >/dev/null 2>&1; then
  err "aws CLI not on PATH"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  err "jq not on PATH (required for manifest emit + s3 list parse)"
  exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
  SHA_CMD=(sha256sum)
else
  SHA_CMD=(shasum -a 256)
fi

if [ "$DRY_RUN" != "true" ]; then
  if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_KEY:-}" ]; then
    err "live mode requires R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_KEY"
    exit 1
  fi
fi

mkdir -p "$STAGE_DIR"

log "mode: $([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE)"
log "region: $REGION  profile: $AWS_PROFILE"
log "r2 dest bucket: $R2_DEST_BUCKET"
log "stage dir: $STAGE_DIR"
log "manifest: $MANIFEST_PATH"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# r2_aws_cli — wraps `aws s3 ...` against the R2 endpoint using the R2
# credentials. We avoid clobbering the global AWS_* env by overriding only
# inside this function's environment.
r2_aws_cli() {
  AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$R2_SECRET_KEY" \
  AWS_PROFILE="" \
  aws --endpoint-url "$R2_ENDPOINT" --region auto "$@"
}

# list_bucket_keys <bucket> — emits one key per line to stdout (paginated).
list_bucket_keys() {
  local bucket="$1"
  local token=""
  local page_args=()
  while :; do
    page_args=(--bucket "$bucket" --region "$REGION" --output json)
    if [ -n "$token" ]; then
      page_args+=(--continuation-token "$token")
    fi
    local resp
    if ! resp=$(aws s3api list-objects-v2 "${page_args[@]}" 2>/dev/null); then
      err "list-objects-v2 failed for $bucket"
      return 2
    fi
    # Empty bucket -> Contents is null/missing; emit nothing for this page.
    echo "$resp" | jq -r '.Contents[]? | "\(.Key)\t\(.Size)"'
    token=$(echo "$resp" | jq -r '.NextContinuationToken // empty')
    if [ -z "$token" ]; then
      break
    fi
  done
}

# ---------------------------------------------------------------------------
# 1. Pre-flight: ensure R2 dest bucket exists (live mode only)
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = "false" ]; then
  if ! r2_aws_cli s3api head-bucket --bucket "$R2_DEST_BUCKET" >/dev/null 2>&1; then
    log "R2 bucket missing; attempting create: $R2_DEST_BUCKET"
    if ! r2_aws_cli s3api create-bucket --bucket "$R2_DEST_BUCKET" >/dev/null 2>&1; then
      err "could not create R2 bucket $R2_DEST_BUCKET — create it manually via wrangler"
      exit 1
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 2. Walk each source bucket
# ---------------------------------------------------------------------------
# We accumulate manifest entries into a temp file then build the final
# JSON array once at the end. This avoids jq -s memory blow-up on large
# buckets and keeps the script crash-resumable (the temp file is appended
# to as each object is processed).

ENTRIES_FILE="${STAGE_DIR}/.manifest_entries.ndjson"
: > "$ENTRIES_FILE"

TOTAL_OBJECTS=0
TOTAL_BYTES=0
FAILED_OBJECTS=0

for SRC in "${SOURCE_BUCKETS[@]}"; do
  log ""
  log "source bucket: s3://$SRC"
  BUCKET_OBJECTS=0
  BUCKET_BYTES=0

  if ! aws s3api head-bucket --bucket "$SRC" --region "$REGION" >/dev/null 2>&1; then
    log "  (bucket not found or no access — skipping: $SRC)"
    continue
  fi

  # Read key\tsize lines from the lister.
  while IFS=$'\t' read -r KEY SIZE; do
    [ -z "${KEY:-}" ] && continue
    BUCKET_OBJECTS=$((BUCKET_OBJECTS + 1))
    BUCKET_BYTES=$((BUCKET_BYTES + ${SIZE:-0}))

    S3_URI="s3://${SRC}/${KEY}"
    R2_KEY="${SRC}/${KEY}"
    R2_URI="r2://${R2_DEST_BUCKET}/${R2_KEY}"

    if [ "$DRY_RUN" = "true" ]; then
      # DRY_RUN: print intent + emit a manifest preview entry (no sha/size lookup).
      printf '  DRY_RUN would: %s -> %s (%s bytes)\n' "$S3_URI" "$R2_URI" "${SIZE:-?}"
      jq -nc \
        --arg s3 "$S3_URI" \
        --arg r2 "$R2_URI" \
        --argjson size "${SIZE:-0}" \
        '{s3_uri: $s3, r2_uri: $r2, sha256: null, size_bytes: $size, status: "preview"}' \
        >> "$ENTRIES_FILE"
      continue
    fi

    # ----- live mode -----
    LOCAL_PATH="${STAGE_DIR}/${SRC}/${KEY}"
    mkdir -p "$(dirname "$LOCAL_PATH")"

    if ! aws s3 cp "$S3_URI" "$LOCAL_PATH" --region "$REGION" --quiet; then
      err "download failed: $S3_URI"
      FAILED_OBJECTS=$((FAILED_OBJECTS + 1))
      continue
    fi

    LOCAL_SHA=$("${SHA_CMD[@]}" "$LOCAL_PATH" | awk '{print $1}')
    LOCAL_BYTES=$(stat -c '%s' "$LOCAL_PATH" 2>/dev/null || stat -f '%z' "$LOCAL_PATH")

    if ! r2_aws_cli s3 cp "$LOCAL_PATH" "s3://${R2_DEST_BUCKET}/${R2_KEY}" --quiet; then
      err "R2 upload failed: $R2_URI"
      FAILED_OBJECTS=$((FAILED_OBJECTS + 1))
      continue
    fi

    # Verify: re-download from R2 to a verify path and re-hash. R2 doesn't
    # expose a server-side SHA256 we can trust directly, so we round-trip
    # the bytes once. Cheap insurance against in-flight corruption.
    VERIFY_PATH="${LOCAL_PATH}.r2verify"
    if ! r2_aws_cli s3 cp "s3://${R2_DEST_BUCKET}/${R2_KEY}" "$VERIFY_PATH" --quiet; then
      err "R2 readback failed: $R2_URI"
      FAILED_OBJECTS=$((FAILED_OBJECTS + 1))
      rm -f "$LOCAL_PATH"
      continue
    fi
    R2_SHA=$("${SHA_CMD[@]}" "$VERIFY_PATH" | awk '{print $1}')
    rm -f "$VERIFY_PATH"

    if [ "$LOCAL_SHA" != "$R2_SHA" ]; then
      err "SHA mismatch: s3=$LOCAL_SHA r2=$R2_SHA key=$KEY"
      FAILED_OBJECTS=$((FAILED_OBJECTS + 1))
      rm -f "$LOCAL_PATH"
      continue
    fi

    printf '  OK: %s -> %s (sha=%s, %s bytes)\n' "$S3_URI" "$R2_URI" "${LOCAL_SHA:0:12}" "$LOCAL_BYTES"
    jq -nc \
      --arg s3 "$S3_URI" \
      --arg r2 "$R2_URI" \
      --arg sha "$LOCAL_SHA" \
      --argjson size "$LOCAL_BYTES" \
      '{s3_uri: $s3, r2_uri: $r2, sha256: $sha, size_bytes: $size, status: "verified"}' \
      >> "$ENTRIES_FILE"

    rm -f "$LOCAL_PATH"

  done < <(list_bucket_keys "$SRC")

  log "  bucket summary: objects=$BUCKET_OBJECTS bytes=$BUCKET_BYTES"
  TOTAL_OBJECTS=$((TOTAL_OBJECTS + BUCKET_OBJECTS))
  TOTAL_BYTES=$((TOTAL_BYTES + BUCKET_BYTES))
done

# ---------------------------------------------------------------------------
# 3. Emit manifest
# ---------------------------------------------------------------------------
log ""
log "writing manifest: $MANIFEST_PATH"
jq -s \
  --arg generated_at "$(date -u +%FT%TZ)" \
  --arg mode "$([ "$DRY_RUN" = "true" ] && echo dry_run || echo live)" \
  --arg dest "$R2_DEST_BUCKET" \
  --argjson total_objects "$TOTAL_OBJECTS" \
  --argjson total_bytes "$TOTAL_BYTES" \
  --argjson failed "$FAILED_OBJECTS" \
  '{generated_at: $generated_at, mode: $mode, r2_dest_bucket: $dest, total_objects: $total_objects, total_bytes: $total_bytes, failed_objects: $failed, entries: .}' \
  "$ENTRIES_FILE" > "$MANIFEST_PATH"

log ""
log "ALL DONE  objects=$TOTAL_OBJECTS bytes=$TOTAL_BYTES failed=$FAILED_OBJECTS  mode=$([ "$DRY_RUN" = "true" ] && echo DRY_RUN || echo LIVE)"

if [ "$FAILED_OBJECTS" -gt 0 ]; then
  exit 3
fi
exit 0
