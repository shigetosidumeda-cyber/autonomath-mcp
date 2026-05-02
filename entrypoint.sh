#!/usr/bin/env bash
# ------------------------------------------------------------------
# AutonoMath container entrypoint.
# Order:
#   1. Ensure /data exists (Fly volume mounted at /data).
#   2. R2 bootstrap: download autonomath.db if missing/SHA mismatch.
#   3. Run migrate.py (idempotent migrations on jpintel.db).
#   4. Run schema_guard.py and autonomath self-heal migrations.
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

# 1.6. autonomath_static seed sync (Phase A static taxonomies + example profiles).
# /seed/autonomath_static/ is baked into image. Copy to /data/autonomath_static/
# if MANIFEST.md missing or DATA_SEED_VERSION drifts. Idempotent.
SEED_STATIC="/seed/autonomath_static"
TARGET_STATIC="/data/autonomath_static"
if [ -d "$SEED_STATIC" ] && [ -f "$SEED_STATIC/MANIFEST.md" ]; then
  if [ ! -f "$TARGET_STATIC/MANIFEST.md" ]; then
    log "autonomath_static missing on volume — copying from /seed"
    mkdir -p "$TARGET_STATIC"
    cp -rf "$SEED_STATIC/." "$TARGET_STATIC/"
    log "autonomath_static copied to $TARGET_STATIC"
  else
    log "autonomath_static already present on volume — skipping copy"
  fi
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

file_size() {
  local f="$1"
  stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo unknown
}

sha_stamp_path() {
  printf '%s.sha256.stamp' "$1"
}

trusted_stamp_path() {
  printf '%s.trusted.stamp' "$1"
}

sha_stamp_matches() {
  local f="$1"
  local want_sha="$2"
  local size
  local stamp
  local stamp_value
  size="$(file_size "$f")"
  [ "$size" != "unknown" ] || return 1
  stamp="$(sha_stamp_path "$f")"
  [ -f "$stamp" ] || return 1
  stamp_value="$(cat "$stamp" 2>/dev/null || true)"
  [ "$stamp_value" = "$want_sha $size" ]
}

trusted_stamp_matches() {
  local f="$1"
  local want_sha="$2"
  local size
  local stamp
  local stamp_value
  size="$(file_size "$f")"
  [ "$size" != "unknown" ] || return 1
  stamp="$(trusted_stamp_path "$f")"
  if [ -f "$stamp" ]; then
    stamp_value="$(cat "$stamp" 2>/dev/null || true)"
    [ "$stamp_value" = "trusted $want_sha $size" ] && return 0
  fi
  return 1
}

write_sha_stamp() {
  local f="$1"
  local sha="$2"
  local size
  local stamp
  size="$(file_size "$f")"
  [ "$size" != "unknown" ] || return 0
  stamp="$(sha_stamp_path "$f")"
  printf '%s %s\n' "$sha" "$size" > "${stamp}.new"
  mv -f "${stamp}.new" "$stamp"
}

write_trusted_stamp() {
  local f="$1"
  local sha="$2"
  local size
  local stamp
  size="$(file_size "$f")"
  [ "$size" != "unknown" ] || return 0
  stamp="$(trusted_stamp_path "$f")"
  printf 'trusted %s %s\n' "$sha" "$size" > "${stamp}.new"
  mv -f "${stamp}.new" "$stamp"
  rm -f "$(sha_stamp_path "$f")"
}

# 2. R2 bootstrap: download autonomath.db if missing or SHA mismatch.
needs_download=0
if [ ! -s "$DB_PATH" ]; then
  log "no existing DB at $DB_PATH"
  needs_download=1
elif [ -n "$DB_SHA256" ]; then
  if sha_stamp_matches "$DB_PATH" "$DB_SHA256"; then
    log "SHA256 stamp match for existing $DB_PATH — skipping full-file hash"
  elif trusted_stamp_matches "$DB_PATH" "$DB_SHA256"; then
    log "trusted DB stamp match for existing $DB_PATH — skipping full-file hash"
  else
    legacy_stamp="$(sha_stamp_path "$DB_PATH")"
    if [ -f "$legacy_stamp" ] && grep -q "^trusted " "$legacy_stamp" 2>/dev/null; then
      log "legacy trusted stamp found at $legacy_stamp — ignoring and forcing full-file hash"
      rm -f "$legacy_stamp"
    fi
    log "checking SHA256 of existing $DB_PATH against AUTONOMATH_DB_SHA256"
    existing_sha="$(compute_sha256 "$DB_PATH")"
    if [ "$existing_sha" = "$DB_SHA256" ]; then
      write_sha_stamp "$DB_PATH" "$DB_SHA256"
      log "SHA256 match — stamp written; skipping download"
    else
      rm -f "$(sha_stamp_path "$DB_PATH")"
      log "SHA256 mismatch (have=$existing_sha want=$DB_SHA256) — re-downloading"
      needs_download=1
    fi
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
  # Pre-clean: stale WAL/SHM from the previous DB attach to the new file
  # at sqlite open time and cause spurious integrity_check failures. Always
  # remove them when downloading a fresh DB. Idempotent.
  rm -f "${DB_PATH}-shm" "${DB_PATH}-wal" "${DB_PATH}.partial"
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
  if [ -n "$DB_SHA256" ]; then
    write_sha_stamp "$DB_PATH" "$DB_SHA256"
  fi
  log "DB snapshot landed at $DB_PATH"
elif [ -s "$DB_PATH" ]; then
  size_bytes="$(file_size "$DB_PATH")"
  log "using existing DB at $DB_PATH ($size_bytes bytes)"
else
  log "no autonomath DB present — proceeding without it (am features will return 503)"
fi

# 3. Migrations on jpintel.db (idempotent, safe on cold starts).
# Must run BEFORE schema_guard so guard validates the post-migration schema.
if [ -f /app/scripts/migrate.py ]; then
  log "running migrate.py on jpintel.db"
  python /app/scripts/migrate.py
  # NOTE: Naive `JPINTEL_DB_PATH=$DB_PATH python migrate.py` to also apply
  # autonomath-targeted migrations CORRUPTS autonomath.db because migrate.py
  # also runs jpintel-default migrations (creating `programs` / `api_keys`
  # tables that schema_guard then rejects as FORBIDDEN). For now, rely on
  # autonomath.db being shipped from R2 with the latest schema baked in
  # (recreate the snapshot when adding new autonomath-target migrations).
  # TODO: split migrate.py to filter strictly by target_db marker, or run
  # specific autonomath migrations explicitly here.
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
    if [ -n "$DB_SHA256" ] && { sha_stamp_matches "$DB_PATH" "$DB_SHA256" || trusted_stamp_matches "$DB_PATH" "$DB_SHA256"; }; then
      log "trusted stamp match for $DB_PATH — skipping full integrity_check"
      integrity="ok"
    else
      log "running integrity_check on $DB_PATH before schema_guard (autonomath)"
      integrity=$(sqlite3 "$DB_PATH" 'PRAGMA integrity_check;' 2>&1 | head -1 || echo "FAILED")
    fi
    if [ "$integrity" != "ok" ]; then
      err "autonomath DB malformed (integrity=$integrity)"
      if [ "${AUTONOMATH_ENABLED:-true}" = "true" ] || [ "${AUTONOMATH_ENABLED:-1}" = "1" ]; then
        err "AUTONOMATH_ENABLED=true — failing boot instead of serving a silently degraded API"
        exit 1
      fi
      log "AUTONOMATH_ENABLED=false — removing partial/corrupt file to unblock boot"
      rm -f "$DB_PATH" "${DB_PATH}-shm" "${DB_PATH}-wal" "${DB_PATH}.partial"
      log "autonomath DB removed; /v1/am/* will return 503 until re-uploaded"
    else
      # Apply autonomath-only views/migrations that the R2 snapshot may
      # predate. schema_migrations skips already-recorded files; failures are
      # counted and handled below instead of being marked applied.
      # This is the minimum self-healing step that keeps /v1/am/* alive
      # after an R2 redownload (which restores schema-as-of-snapshot).
      #
      # Discovery rule (replaces the old hard-coded `070` single-file loop
      # 2026-04-29 to pick up 075 and any future autonomath-target file):
      #   1. Iterate scripts/migrations/*.sql in numeric (lexical) order.
      #   2. Include only files whose first line declares
      #        `-- target_db: autonomath`
      #      (see migrate.py target_db marker convention). This guards
      #      against accidentally applying jpintel-default DDL — those
      #      files would create `programs` / `api_keys` tables that
      #      schema_guard then rejects as FORBIDDEN on autonomath.db.
      #   3. Exclude any filename containing `_rollback` — rollback
      #      companions (e.g. 065_*_rollback.sql) carry the same
      #      target_db marker but are draft scripts gated on manual
      #      review, not boot-time idempotent migrations.
      #   4. Exclude files declaring `-- boot_time: manual`; those can
      #      hold maintenance SQL that is safe offline but too expensive
      #      or disruptive for every production boot.
      #   5. Record hard errors without marking the migration applied.
      #      AUTONOMATH_ENABLED=true fails boot after the loop; otherwise
      #      schema_guard below still catches structural drift.
      # Ensure bookkeeping table exists so we can skip already-applied
      # migrations on the second-and-subsequent boot. Without this, the
      # 8 known non-idempotent ALTER TABLE migrations (049/067_autonomath/
      # 077/078/082/090/092/101) would flood boot logs with "duplicate column"
      # parse errors on every boot and now fail boot when AUTONOMATH_ENABLED=true.
      sqlite3 "$DB_PATH" "CREATE TABLE IF NOT EXISTS schema_migrations(
          id TEXT PRIMARY KEY,
          checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL
      );" 2>/dev/null || true

      am_mig_applied=0
      am_mig_skipped=0
      am_mig_already=0
      am_mig_failed=0
      for am_mig in $(ls /app/scripts/migrations/*.sql 2>/dev/null | sort); do
        case "$am_mig" in
          *_rollback.sql)
            log "skipping $am_mig (rollback companion, manual-review only)"
            am_mig_skipped=$((am_mig_skipped + 1))
            continue
            ;;
        esac
        if ! head -1 "$am_mig" | grep -q "target_db: autonomath"; then
          # Not an autonomath-target migration — silently skip
          # (jpintel.db migrations are handled by migrate.py above).
          am_mig_skipped=$((am_mig_skipped + 1))
          continue
        fi
        if head -20 "$am_mig" | grep -qi "^-- *boot_time: *manual"; then
          log "skipping $am_mig (boot_time: manual)"
          am_mig_skipped=$((am_mig_skipped + 1))
          continue
        fi
        am_mig_id="$(basename "$am_mig")"
        # Skip if already recorded in schema_migrations bookkeeping.
        already=$(sqlite3 "$DB_PATH" "SELECT 1 FROM schema_migrations WHERE id='$am_mig_id' LIMIT 1;" 2>/dev/null || echo "")
        if [ "$already" = "1" ]; then
          am_mig_already=$((am_mig_already + 1))
          continue
        fi
        log "applying $am_mig to $DB_PATH"
        am_mig_output="$(mktemp)"
        if sqlite3 "$DB_PATH" < "$am_mig" >"$am_mig_output" 2>&1; then
          # Record successful apply. Use INSERT OR IGNORE so concurrent
          # boots on the same volume don't crash on the bookkeeping write.
          now=$(date -u +%FT%TZ)
          sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO schema_migrations(id,checksum,applied_at) VALUES('$am_mig_id','self_heal','$now');" 2>/dev/null || true
          am_mig_applied=$((am_mig_applied + 1))
        else
          if grep -qi "duplicate column" "$am_mig_output" \
             && ! grep -vi "duplicate column" "$am_mig_output" | grep -q '[^[:space:]]'; then
            # SQLite has no ALTER TABLE ADD COLUMN IF NOT EXISTS. Treat a
            # duplicate column as "schema already has this additive change",
            # then record the migration id so future boots skip it. Mixed
            # output with any other hard error still fails below.
            now=$(date -u +%FT%TZ)
            sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO schema_migrations(id,checksum,applied_at) VALUES('$am_mig_id','self_heal_duplicate_column','$now');" 2>/dev/null || true
            log "autonomath migration duplicate-column treated as applied: $am_mig"
            am_mig_applied=$((am_mig_applied + 1))
          else
            # Do not mark hard-failed migrations as applied. Schema guard below
            # catches structural drift, and leaving the row unrecorded means a
            # future boot can retry after the operator fixes the migration.
            log "autonomath migration failed: $am_mig"
            grep -v "^$" "$am_mig_output" | head -5 || true
            am_mig_failed=$((am_mig_failed + 1))
          fi
        fi
        rm -f "$am_mig_output"
      done
      log "autonomath self-heal migrations: applied=$am_mig_applied already=$am_mig_already skipped=$am_mig_skipped failed=$am_mig_failed"
      if [ "$am_mig_failed" -gt 0 ]; then
        if [ "${AUTONOMATH_ENABLED:-true}" = "true" ] || [ "${AUTONOMATH_ENABLED:-1}" = "1" ]; then
          err "AUTONOMATH_ENABLED=true and autonomath migrations failed — failing boot"
          exit 1
        fi
        log "AUTONOMATH_ENABLED=false — continuing despite autonomath migration failures"
      fi
      log "running schema_guard.py on $DB_PATH (autonomath profile)"
      python /app/scripts/schema_guard.py "$DB_PATH" autonomath || {
        err "schema_guard failed for autonomath"
        if [ "${AUTONOMATH_ENABLED:-true}" = "true" ] || [ "${AUTONOMATH_ENABLED:-1}" = "1" ]; then
          err "AUTONOMATH_ENABLED=true — failing boot instead of serving a silently degraded API"
          exit 1
        fi
        log "AUTONOMATH_ENABLED=false — moving aside to /data/autonomath.db.failed and continuing"
        mv "$DB_PATH" "${DB_PATH}.failed.$(date +%s)"
      }
      if [ -n "$DB_SHA256" ] && [ -s "$DB_PATH" ]; then
        write_trusted_stamp "$DB_PATH" "$DB_SHA256"
      fi
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
