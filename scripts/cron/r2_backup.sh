#!/usr/bin/env bash
# ------------------------------------------------------------------
# AutonoMath nightly DR backup → Cloudflare R2 (K8 / launch wave 18).
#
# Runs on the Fly machine (or any host with the live SQLite DB +
# rclone configured). Writes a consistent .backup snapshot,
# computes SHA256, uploads to R2, and prunes >90d backups.
#
# Why .backup, not cp:
#   `sqlite3 ... .backup` is the only safe online snapshot for a
#   live WAL DB. cp races against checkpoint and produces corrupt
#   files; the entrypoint restore path will reject them via SHA
#   mismatch (see entrypoint.sh:75-100), so we'd page the operator
#   on every restart.
#
# Required env (set via `flyctl secrets set ...` — values NEVER in
# this file or in docs):
#   R2_ENDPOINT           e.g. https://<acct>.r2.cloudflarestorage.com
#   R2_ACCESS_KEY_ID      Cloudflare R2 API token access key.
#   R2_SECRET_KEY         Cloudflare R2 API token secret.
#   R2_BUCKET             Bucket name (default: autonomath-backup).
#   R2_BACKUP_PREFIX      Object prefix (default: nightly/).
#
# Optional env:
#   AUTONOMATH_DB_PATH    Path to the live DB (default /data/autonomath.db).
#   BACKUP_TMP_DIR        Where to stage the snapshot (default /tmp).
#   BACKUP_RETENTION_DAYS How many days of nightly backups to keep
#                          on R2 (default 90).
#   DRY_RUN=1             Stage + checksum locally; skip upload + prune.
#
# Exit codes:
#   0  success
#   1  config error (missing env / sqlite3 / rclone)
#   2  snapshot failed
#   3  upload failed
#   4  retention prune failed (warning — backup itself succeeded)
#
# Usage on Fly:
#   /app/scripts/cron/r2_backup.sh                  # real run
#   DRY_RUN=1 /app/scripts/cron/r2_backup.sh        # local stage only
# ------------------------------------------------------------------
set -euo pipefail

DB_PATH="${AUTONOMATH_DB_PATH:-/data/autonomath.db}"
TMP_DIR="${BACKUP_TMP_DIR:-/tmp}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-90}"
BUCKET="${R2_BUCKET:-autonomath-backup}"
PREFIX="${R2_BACKUP_PREFIX:-nightly/}"
DRY_RUN="${DRY_RUN:-0}"

DATESTAMP="$(date -u +%Y%m%d)"
SNAP_NAME="autonomath-${DATESTAMP}.db"
SNAP_PATH="${TMP_DIR}/${SNAP_NAME}"
SHA_PATH="${SNAP_PATH}.sha256"

log() { printf '[r2-backup] %s %s\n' "$(date -u +%FT%TZ)" "$1"; }
err() { printf '[r2-backup] %s ERROR: %s\n' "$(date -u +%FT%TZ)" "$1" >&2; }

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
  if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_ACCESS_KEY_ID:-}" ] || [ -z "${R2_SECRET_KEY:-}" ]; then
    err "R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_KEY must be set (use flyctl secrets)"
    exit 1
  fi
  if ! command -v rclone >/dev/null 2>&1; then
    err "rclone not installed (apt-get install rclone OR add to image)"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 1. Snapshot via sqlite3 .backup
# ---------------------------------------------------------------------------
log "snapshot start  src=${DB_PATH}  dest=${SNAP_PATH}"
rm -f "$SNAP_PATH" "${SNAP_PATH}-wal" "${SNAP_PATH}-shm"
if ! sqlite3 "$DB_PATH" ".backup '${SNAP_PATH}'"; then
  err "sqlite3 .backup failed"
  exit 2
fi
SNAP_BYTES="$(stat -c '%s' "$SNAP_PATH" 2>/dev/null || stat -f '%z' "$SNAP_PATH")"
log "snapshot done   bytes=${SNAP_BYTES}"

# Quick integrity check — sqlite3 will exit non-zero on corruption.
if ! sqlite3 "$SNAP_PATH" "PRAGMA integrity_check;" | head -1 | grep -q "^ok$"; then
  err "PRAGMA integrity_check failed on snapshot"
  exit 2
fi
log "integrity_check ok"

# ---------------------------------------------------------------------------
# 2. SHA256 sidecar
# ---------------------------------------------------------------------------
if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$SNAP_PATH" | awk '{print $1}')"
else
  SHA="$(shasum -a 256 "$SNAP_PATH" | awk '{print $1}')"
fi
printf '%s  %s\n' "$SHA" "$SNAP_NAME" > "$SHA_PATH"
log "sha256 ${SHA}"

if [ "$DRY_RUN" = "1" ]; then
  log "DRY_RUN=1 — stage complete, skipping upload + prune"
  log "staged at ${SNAP_PATH} (+ .sha256)"
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Upload to R2 via rclone (S3-compatible)
# ---------------------------------------------------------------------------
# Inline rclone config — avoids a global ~/.config/rclone/rclone.conf
# file on the Fly machine and keeps secrets only in env vars.
RCLONE_BASE=(
  rclone
  --config /dev/null
  --s3-endpoint "${R2_ENDPOINT}"
  --s3-access-key-id "${R2_ACCESS_KEY_ID}"
  --s3-secret-access-key "${R2_SECRET_KEY}"
  --s3-region auto
  --s3-provider Cloudflare
)

REMOTE=":s3:${BUCKET}/${PREFIX}"

log "upload start   remote=${REMOTE}${SNAP_NAME}"
if ! "${RCLONE_BASE[@]}" copyto "$SNAP_PATH" "${REMOTE}${SNAP_NAME}"; then
  err "rclone copyto (db) failed"
  exit 3
fi
if ! "${RCLONE_BASE[@]}" copyto "$SHA_PATH" "${REMOTE}${SNAP_NAME}.sha256"; then
  err "rclone copyto (sha) failed"
  exit 3
fi
log "upload done"

# ---------------------------------------------------------------------------
# 4. Retention: delete objects older than RETENTION_DAYS
# ---------------------------------------------------------------------------
log "prune start    retention=${RETENTION_DAYS}d"
if ! "${RCLONE_BASE[@]}" delete "${REMOTE}" --min-age "${RETENTION_DAYS}d" --include "autonomath-*.db" --include "autonomath-*.db.sha256" 2>&1; then
  err "rclone delete (prune) failed — backup uploaded but old files remain"
  exit 4
fi
log "prune done"

# ---------------------------------------------------------------------------
# 5. Local cleanup (don't keep snapshots on the Fly machine)
# ---------------------------------------------------------------------------
rm -f "$SNAP_PATH" "$SHA_PATH"
log "local cleanup ok"

log "ALL DONE       snapshot=${SNAP_NAME}  sha=${SHA}"
exit 0
