#!/usr/bin/env bash
# ------------------------------------------------------------------
# AutonoMath container entrypoint.
# Order:
#   1. Ensure /data exists (Fly volume mounted at /data).
#   2. R2 bootstrap: download autonomath.db if missing/SHA mismatch.
#   3. Run schema_guard.py (asserts required tables + migration level).
#   4. Run migrate.py (idempotent migrations on jpintel.db).
#   5. exec CMD.
# ------------------------------------------------------------------
set -euo pipefail

DB_PATH="${AUTONOMATH_DB_PATH:-/data/autonomath.db}"
DB_URL="${AUTONOMATH_DB_URL:-}"
DB_SHA256="${AUTONOMATH_DB_SHA256:-}"
TMP_DB="${DB_PATH}.partial"

log() { printf '[entrypoint] %s %s\n' "$(date -u +%FT%TZ)" "$1"; }
err() { printf '[entrypoint] %s ERROR: %s\n' "$(date -u +%FT%TZ)" "$1" >&2; }

# 1. Data dir (Fly volume must be mounted at /data)
mkdir -p /data
if [ ! -d /data ]; then
  err "data directory missing: /data — Fly volume not mounted?"
  exit 1
fi

# 1.5. Seed data sync (jpintel.db + unified_registry.json baked into image at /seed/).
# DATA_SEED_VERSION env var (set in Dockerfile) controls re-sync — bumping it
# forces overwrite of the volume copy. Without bump, existing volume wins
# (preserves operator-managed runtime updates).
JPINTEL_DB="${JPINTEL_DB_PATH:-/data/jpintel.db}"
SEED_VERSION_FILE="/data/.seed_version"
SEED_DB="/seed/jpintel.db"
SEED_REGISTRY="/seed/unified_registry.json"
TARGET_REGISTRY="/opt/venv/lib/python3.12/site-packages/data/unified_registry.json"

if [ -n "${DATA_SEED_VERSION:-}" ] && [ -f "$SEED_DB" ]; then
  current_seed=""
  [ -f "$SEED_VERSION_FILE" ] && current_seed="$(cat "$SEED_VERSION_FILE" 2>/dev/null || echo '')"
  if [ "$current_seed" != "$DATA_SEED_VERSION" ]; then
    log "seed version drift (volume='$current_seed' image='$DATA_SEED_VERSION') — copying baked seed"
    # Stop any in-flight sqlite WAL/shm so the replacement is atomic from app POV.
    rm -f "${JPINTEL_DB}-wal" "${JPINTEL_DB}-shm"
    cp -f "$SEED_DB" "${JPINTEL_DB}.new"
    mv -f "${JPINTEL_DB}.new" "$JPINTEL_DB"
    if [ -f "$SEED_REGISTRY" ]; then
      mkdir -p "$(dirname "$TARGET_REGISTRY")"
      cp -f "$SEED_REGISTRY" "$TARGET_REGISTRY"
      log "unified_registry.json placed at $TARGET_REGISTRY"
    fi
    echo "$DATA_SEED_VERSION" > "$SEED_VERSION_FILE"
    log "seed sync complete (jpintel.db + unified_registry.json now at $DATA_SEED_VERSION)"
  else
    log "seed version current ($DATA_SEED_VERSION) — no copy needed"
    # Always ensure unified_registry.json exists at the target path (image rebuild may
    # have replaced site-packages but volume seed sentinel was already current).
    if [ -f "$SEED_REGISTRY" ] && [ ! -f "$TARGET_REGISTRY" ]; then
      mkdir -p "$(dirname "$TARGET_REGISTRY")"
      cp -f "$SEED_REGISTRY" "$TARGET_REGISTRY"
      log "unified_registry.json restored at $TARGET_REGISTRY (was missing)"
    fi
  fi
else
  log "DATA_SEED_VERSION unset or seed missing — using volume DB as-is"
fi

# Helper: compute SHA256 of a file (portable across Linux + macOS).
compute_sha256() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    shasum -a 256 "$f" | awk '{print $1}'
  fi
}

# 2. R2 bootstrap: download autonomath.db if missing or SHA mismatch.
needs_download=0
if [ ! -s "$DB_PATH" ]; then
  log "no existing DB at $DB_PATH"
  needs_download=1
elif [ -n "$DB_SHA256" ]; then
  log "checking SHA256 of existing $DB_PATH against AUTONOMATH_DB_SHA256"
  existing_sha="$(compute_sha256 "$DB_PATH")"
  if [ "$existing_sha" = "$DB_SHA256" ]; then
    log "SHA256 match — skipping download"
  else
    log "SHA256 mismatch (have=$existing_sha want=$DB_SHA256) — re-downloading"
    needs_download=1
  fi
else
  log "existing DB at $DB_PATH (no AUTONOMATH_DB_SHA256 set; skipping verification)"
fi

if [ "$needs_download" -eq 1 ]; then
  if [ -z "$DB_URL" ]; then
    # autonomath.db is optional at boot. /v1/am/* and 16 MCP autonomath tools
    # will return 503 until the DB is uploaded (R2 bootstrap pending), but the
    # core API/jpintel.db endpoints stay live. Do NOT hard-fail here.
    log "AUTONOMATH_DB_URL unset and DB missing — skipping bootstrap (autonomath features will be 503 until DB is restored)"
    needs_download=0
  fi
fi

if [ "$needs_download" -eq 1 ]; then
  log "downloading DB snapshot from R2"
  # Resume-friendly (-C -), follow redirects (-L), hard-fail on HTTP >=400 (-f),
  # retry transient errors. --retry-all-errors is curl >=7.71; harmless if absent.
  curl -fL --retry 5 --retry-delay 10 --retry-all-errors \
       -C - -o "$TMP_DB" "$DB_URL"

  if [ -n "$DB_SHA256" ]; then
    log "verifying SHA256 of downloaded snapshot"
    got_sha="$(compute_sha256 "$TMP_DB")"
    if [ "$got_sha" != "$DB_SHA256" ]; then
      err "SHA256 mismatch on download (got=$got_sha want=$DB_SHA256)"
      rm -f "$TMP_DB"
      exit 1
    fi
    log "SHA256 verified"
  else
    log "AUTONOMATH_DB_SHA256 unset — skipping integrity check (NOT recommended for prod)"
  fi

  # Atomic rename so a crash mid-download never leaves a half-baked DB at $DB_PATH.
  mv "$TMP_DB" "$DB_PATH"
  log "DB snapshot landed at $DB_PATH"
elif [ -s "$DB_PATH" ]; then
  size_bytes="$(stat -c%s "$DB_PATH" 2>/dev/null || stat -f%z "$DB_PATH" 2>/dev/null || echo unknown)"
  log "using existing DB at $DB_PATH ($size_bytes bytes)"
else
  log "no autonomath DB present — proceeding without it (am features will return 503)"
fi

# 3. Migrations on jpintel.db (idempotent, safe on cold starts).
# Must run BEFORE schema_guard so guard validates the post-migration schema.
if [ -f /app/scripts/migrate.py ]; then
  log "running migrate.py"
  python /app/scripts/migrate.py
else
  log "migrate.py absent — skipping"
fi

# 4. Schema guard — idempotent, must pass before traffic.
# Note: schema_guard.py expects (db_path, profile) args. We run it once per DB
# that actually exists. jpintel.db is mandatory; autonomath.db is optional.
if [ -f /app/scripts/schema_guard.py ]; then
  JPINTEL_DB="${JPINTEL_DB_PATH:-/data/jpintel.db}"
  if [ -s "$JPINTEL_DB" ]; then
    log "running schema_guard.py on $JPINTEL_DB (jpintel profile)"
    python /app/scripts/schema_guard.py "$JPINTEL_DB" jpintel
  else
    log "jpintel DB missing at $JPINTEL_DB — schema guard for jpintel skipped (migrate.py will create it)"
  fi
  if [ -s "$DB_PATH" ]; then
    log "running integrity_check on $DB_PATH before schema_guard (autonomath)"
    integrity=$(sqlite3 "$DB_PATH" 'PRAGMA integrity_check;' 2>&1 | head -1 || echo "FAILED")
    if [ "$integrity" != "ok" ]; then
      log "autonomath DB malformed (integrity=$integrity) — removing partial/corrupt file to unblock boot"
      rm -f "$DB_PATH" "${DB_PATH}-shm" "${DB_PATH}-wal" "${DB_PATH}.partial"
      log "autonomath DB removed; /v1/am/* will return 503 until re-uploaded"
    else
      log "running schema_guard.py on $DB_PATH (autonomath profile)"
      python /app/scripts/schema_guard.py "$DB_PATH" autonomath || {
        log "schema_guard failed for autonomath — moving aside to /data/autonomath.db.failed and continuing"
        mv "$DB_PATH" "${DB_PATH}.failed.$(date +%s)"
      }
    fi
  else
    log "autonomath DB absent — schema guard for autonomath skipped"
  fi
else
  log "schema_guard.py absent — skipping (dev build?)"
fi

# 5. Hand off to CMD.
log "starting server: $*"
exec "$@"
