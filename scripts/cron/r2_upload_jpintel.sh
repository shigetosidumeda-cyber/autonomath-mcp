#!/usr/bin/env bash
# ------------------------------------------------------------------
# Daily 04:00 JST upload of jpintel.db -> Cloudflare R2 (Wave 20).
#
# Purpose
# -------
# This is a deploy-hydrate safety net, NOT a DR backup. The DR backup is
# scripts/cron/backup_jpintel.py (called by nightly-backup.yml at 03:17 JST)
# which writes gzipped + sha256-sidecar snapshots to
# s3://$R2_BUCKET/autonomath-api/jpintel-YYYYMMDD-HHMMSS.db.gz.
#
# The deploy.yml hydrate step Wave 20 fallback pulls the latest of those keys
# when `flyctl ssh sftp get` fails (Fly SSH tunnel collapses on 200+ MB
# transfers — see run 25669988722). This script is the dedicated "every-day,
# always-fresh" upload pinned at 04:00 JST so the fallback never has to reach
# back >24h.
#
# Why a separate script (not just rely on backup_jpintel.py)?
#   1. nightly-backup.yml writes to /data/backups on the Fly machine first,
#      then sftp-pulls + R2-uploads from the GHA runner. If sftp dies (the
#      very failure mode this Wave 20 patch addresses), the R2 mirror also
#      never updates. A side-channel direct upload from the Fly machine
#      sidesteps that single-point-of-failure path entirely.
#   2. backup_jpintel.py gzips + tiered-retention prunes. We want a plain
#      single canonical key the deploy hydrate fallback can find without
#      having to enumerate the tiered space.
#   3. Decoupling lets us tune cadence independently — nightly DR backup
#      runs once a day; this safety mirror could go hourly later if needed.
#
# Output key
# ----------
# s3://$R2_BUCKET/$R2_HYDRATE_PREFIX/jpintel.db.gz (+ .sha256 sidecar)
# Default prefix: autonomath-api/ (same prefix the deploy hydrate fallback
# scans). The fixed `jpintel.db.gz` filename means a deploy can `aws s3 cp`
# without listing first — useful when the hydrate fallback wants a fast path.
#
# Required env (Fly secrets):
#   R2_ENDPOINT           https://<acct>.r2.cloudflarestorage.com
#   R2_ACCESS_KEY_ID      Cloudflare R2 access key.
#   R2_SECRET_ACCESS_KEY  Cloudflare R2 secret.
#   R2_BUCKET             Bucket name.
#
# Optional env:
#   JPINTEL_DB_PATH         default /data/jpintel.db
#   R2_HYDRATE_PREFIX       default autonomath-api/ (matches deploy.yml)
#   R2_HYDRATE_KEY          default jpintel.db.gz
#   BACKUP_TMP_DIR          default /tmp
#   DRY_RUN=1               stage + checksum locally; skip upload
#
# Exit codes:
#   0 success / 1 config / 2 snapshot / 3 upload
# ------------------------------------------------------------------
set -euo pipefail

DB_PATH="${JPINTEL_DB_PATH:-/data/jpintel.db}"
TMP_DIR="${BACKUP_TMP_DIR:-/tmp}"
PREFIX="${R2_HYDRATE_PREFIX:-autonomath-api/}"
KEY="${R2_HYDRATE_KEY:-jpintel.db.gz}"
DRY_RUN="${DRY_RUN:-0}"

SNAP_PATH="${TMP_DIR}/jpintel-hydrate.db"
GZ_PATH="${SNAP_PATH}.gz"
SHA_PATH="${GZ_PATH}.sha256"

log() { printf '[r2-upload-jpintel] %s %s\n' "$(date -u +%FT%TZ)" "$1"; }
err() { printf '[r2-upload-jpintel] %s ERROR: %s\n' "$(date -u +%FT%TZ)" "$1" >&2; }

# ---------------------------------------------------------------------------
# 0. Pre-flight
# ---------------------------------------------------------------------------
if ! command -v sqlite3 >/dev/null 2>&1; then
  err "sqlite3 not on PATH"
  exit 1
fi
if [ ! -s "$DB_PATH" ]; then
  err "live DB missing or empty: $DB_PATH"
  exit 1
fi
if [ "$DRY_RUN" != "1" ]; then
  if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_ACCESS_KEY:-}" ] || [ -z "${R2_BUCKET:-}" ]; then
    err "R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET must be set"
    exit 1
  fi
  if ! command -v rclone >/dev/null 2>&1; then
    err "rclone not installed"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 1. Atomic online .backup snapshot (never use cp on a WAL DB)
# ---------------------------------------------------------------------------
log "snapshot start  src=${DB_PATH}  dest=${SNAP_PATH}"
rm -f "$SNAP_PATH" "${SNAP_PATH}-wal" "${SNAP_PATH}-shm" "$GZ_PATH" "$SHA_PATH"
if ! sqlite3 "$DB_PATH" ".backup '${SNAP_PATH}'"; then
  err "sqlite3 .backup failed"
  exit 2
fi
SNAP_BYTES="$(stat -c '%s' "$SNAP_PATH" 2>/dev/null || stat -f '%z' "$SNAP_PATH")"
log "snapshot done   bytes=${SNAP_BYTES}"

# Sanity floor — match the hydrate step + schema_guard prod gate.
if [ "$SNAP_BYTES" -lt 100000000 ]; then
  err "snapshot is implausibly small (${SNAP_BYTES} bytes < 100 MB) — aborting"
  exit 2
fi

# quick_check is fast on jpintel.db (~352 MB); cheap to keep.
if ! sqlite3 "$SNAP_PATH" "PRAGMA quick_check;" | head -1 | grep -q "^ok$"; then
  err "PRAGMA quick_check failed on snapshot"
  exit 2
fi
log "quick_check ok"

# ---------------------------------------------------------------------------
# 2. gzip + SHA256 sidecar (gzip cuts upload size ~40%)
# ---------------------------------------------------------------------------
gzip -9 -c "$SNAP_PATH" > "$GZ_PATH"
GZ_BYTES="$(stat -c '%s' "$GZ_PATH" 2>/dev/null || stat -f '%z' "$GZ_PATH")"
log "gzipped         bytes=${GZ_BYTES}"

if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$GZ_PATH" | awk '{print $1}')"
else
  SHA="$(shasum -a 256 "$GZ_PATH" | awk '{print $1}')"
fi
printf '%s  %s\n' "$SHA" "${KEY}" > "$SHA_PATH"
log "sha256 ${SHA}"

if [ "$DRY_RUN" = "1" ]; then
  log "DRY_RUN=1 — stage complete; skipping upload"
  log "staged at ${GZ_PATH} (+ .sha256)"
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Upload to R2 via rclone (S3-compatible). copyto = single canonical key.
# ---------------------------------------------------------------------------
RCLONE_BASE=(
  rclone
  --config /dev/null
  --s3-endpoint "${R2_ENDPOINT}"
  --s3-access-key-id "${R2_ACCESS_KEY_ID}"
  --s3-secret-access-key "${R2_SECRET_ACCESS_KEY}"
  --s3-region auto
  --s3-provider Cloudflare
)
REMOTE_KEY=":s3:${R2_BUCKET}/${PREFIX%/}/${KEY}"
REMOTE_SHA=":s3:${R2_BUCKET}/${PREFIX%/}/${KEY}.sha256"

log "upload start    remote=${REMOTE_KEY}"
if ! "${RCLONE_BASE[@]}" copyto "$GZ_PATH" "${REMOTE_KEY}"; then
  err "rclone copyto (db) failed"
  exit 3
fi
if ! "${RCLONE_BASE[@]}" copyto "$SHA_PATH" "${REMOTE_SHA}"; then
  err "rclone copyto (sha) failed"
  exit 3
fi
log "upload done"

# ---------------------------------------------------------------------------
# 4. Local cleanup
# ---------------------------------------------------------------------------
rm -f "$SNAP_PATH" "$GZ_PATH" "$SHA_PATH"
log "local cleanup ok"

log "ALL DONE        remote=${PREFIX%/}/${KEY}  uncompressed_bytes=${SNAP_BYTES}  gz_bytes=${GZ_BYTES}  sha=${SHA}"
exit 0
