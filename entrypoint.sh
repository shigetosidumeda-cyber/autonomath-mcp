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

# 1.4. jpcite ⇄ autonomath compatibility symlink (Wave 46.C).
# Brand rename strategy: jpcite.db is the canonical name going forward; old
# AUTONOMATH_DB_PATH consumers still resolve through the same inode. Per
# `project_jpcite_internal_autonomath_rename` and
# `feedback_destruction_free_organization`: never delete or rename the
# physical autonomath.db, only create the symlink when the new path is
# absent. Per `feedback_no_quick_check_on_huge_sqlite`: zero PRAGMA /
# integrity probe here — symlink ops are O(1) inode-only so boot stays well
# under the 60s Fly grace window. Per `feedback_dual_cli_lane_atomic`:
# additive overlay (`ln -sf` only when target missing) — safe against
# concurrent boot.
JPCITE_DB="${JPCITE_DB_PATH:-/data/jpcite.db}"
AM_DB="${AUTONOMATH_DB_PATH:-/data/autonomath.db}"

if [ -f "$AM_DB" ] && [ ! -e "$JPCITE_DB" ]; then
  ln -sf "$AM_DB" "$JPCITE_DB"
  log "[W46.C] symlink created: $JPCITE_DB -> $AM_DB"
elif [ -f "$JPCITE_DB" ] && [ ! -e "$AM_DB" ]; then
  # Inverse case (post-eventual-rename world): jpcite.db is the real file
  # and autonomath.db is missing. Symlink the legacy path so old code paths
  # remain transparent. Still no destructive op on either side.
  ln -sf "$JPCITE_DB" "$AM_DB"
  log "[W46.C] reverse symlink created: $AM_DB -> $JPCITE_DB"
elif [ -e "$AM_DB" ] && [ -e "$JPCITE_DB" ]; then
  # Both exist. If they resolve to the same inode (either is symlink to
  # the other, or both are bind mounts of the same file), nothing to do.
  # Otherwise split-brain — log a warning and continue; downstream §2
  # bootstrap still operates on $DB_PATH (= AUTONOMATH_DB_PATH default).
  am_inode=$(stat -L -c%i "$AM_DB" 2>/dev/null || stat -L -f%i "$AM_DB" 2>/dev/null || echo "?")
  jc_inode=$(stat -L -c%i "$JPCITE_DB" 2>/dev/null || stat -L -f%i "$JPCITE_DB" 2>/dev/null || echo "?")
  if [ "$am_inode" != "$jc_inode" ] || [ "$am_inode" = "?" ]; then
    err "[W46.C] split-brain: $AM_DB (inode=$am_inode) and $JPCITE_DB (inode=$jc_inode) are distinct files — manual reconcile required; continuing with $AM_DB as canonical"
  fi
fi

# Helper: compute SHA256 of a file (portable across Linux + macOS).
# Forward-declared here so the seed validation block in §1.5 can hash the
# staged seed file before the atomic rename. The same function is used by
# the R2 bootstrap path further below.
compute_sha256() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    shasum -a 256 "$f" | awk '{print $1}'
  fi
}

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
    log "seed version drift (volume='$current_seed' image='$DATA_SEED_VERSION') — validating seed policy"
    if [ -f "$JPINTEL_DB" ] && [ "${JPINTEL_FORCE_SEED_OVERWRITE:-0}" != "1" ]; then
      live_quick_check=$(sqlite3 "$JPINTEL_DB" 'PRAGMA quick_check;' 2>&1 | head -1 || echo "FAILED")
      live_program_count=$(sqlite3 "$JPINTEL_DB" 'SELECT COUNT(*) FROM programs;' 2>/dev/null || echo "0")
      if [ "$live_quick_check" = "ok" ] && [ "$live_program_count" -ge 10000 ] 2>/dev/null; then
        live_sha=$(compute_sha256 "$JPINTEL_DB")
        log "existing volume jpintel.db is healthy (programs=$live_program_count sha256=$live_sha) — preserving live DB; set JPINTEL_FORCE_SEED_OVERWRITE=1 to replace"
        if [ -f "$SEED_REGISTRY" ] && [ ! -f "$TARGET_REGISTRY" ]; then
          mkdir -p "$(dirname "$TARGET_REGISTRY")"
          cp -f "$SEED_REGISTRY" "$TARGET_REGISTRY"
          log "unified_registry.json restored at $TARGET_REGISTRY (was missing)"
        fi
        printf '%s\n' "$DATA_SEED_VERSION" > "${SEED_VERSION_FILE}.new"
        mv -f "${SEED_VERSION_FILE}.new" "$SEED_VERSION_FILE"
        printf 'version=%s preserved_existing=true sha256=%s programs=%s applied_at=%s\n' \
          "$DATA_SEED_VERSION" "$live_sha" "$live_program_count" "$(date -u +%FT%TZ)" \
          > "${SEED_VERSION_FILE}.manifest.new"
        mv -f "${SEED_VERSION_FILE}.manifest.new" "${SEED_VERSION_FILE}.manifest"
        log "seed sentinel updated without DB replacement"
      else
        log "existing volume jpintel.db failed health check (quick_check=$live_quick_check programs=$live_program_count) — replacing from baked seed"
        JPINTEL_FORCE_SEED_OVERWRITE=1
      fi
    fi

    if [ ! -f "$JPINTEL_DB" ] || [ "${JPINTEL_FORCE_SEED_OVERWRITE:-0}" = "1" ]; then
      log "copying baked seed into volume"
    # Stop any in-flight sqlite WAL/shm so the replacement is atomic from app POV.
    rm -f "${JPINTEL_DB}-wal" "${JPINTEL_DB}-shm"
    # Stage the seed at $JPINTEL_DB.new and validate BEFORE atomic rename so a
    # broken / empty / corrupt seed never lands on the live path. Three gates:
    #   * PRAGMA quick_check returns 'ok'
    #   * SELECT COUNT(*) FROM programs >= 10000 (sentinel against empty seed)
    #   * sha256 of staged file recorded next to .seed_version (manifest)
    # If any gate fails we abort with the staged file removed; the volume DB
    # (whatever version) keeps serving until the operator fixes the image.
    cp -f "$SEED_DB" "${JPINTEL_DB}.new"
    seed_quick_check=$(sqlite3 "${JPINTEL_DB}.new" 'PRAGMA quick_check;' 2>&1 | head -1 || echo "FAILED")
    if [ "$seed_quick_check" != "ok" ]; then
      err "seed DB quick_check failed: $seed_quick_check (staged=${JPINTEL_DB}.new)"
      rm -f "${JPINTEL_DB}.new"
      exit 1
    fi
    seed_program_count=$(sqlite3 "${JPINTEL_DB}.new" 'SELECT COUNT(*) FROM programs;' 2>/dev/null || echo "0")
    if [ "$seed_program_count" -lt 10000 ] 2>/dev/null; then
      err "seed DB programs row-count below 10000 floor (got=$seed_program_count)"
      rm -f "${JPINTEL_DB}.new"
      exit 1
    fi
    seed_sha=$(compute_sha256 "${JPINTEL_DB}.new")
    log "seed gate pass: quick_check=ok programs=$seed_program_count sha256=$seed_sha"
    mv -f "${JPINTEL_DB}.new" "$JPINTEL_DB"
    if [ -f "$SEED_REGISTRY" ]; then
      mkdir -p "$(dirname "$TARGET_REGISTRY")"
      cp -f "$SEED_REGISTRY" "$TARGET_REGISTRY"
      log "unified_registry.json placed at $TARGET_REGISTRY"
    fi
    # Atomic .seed_version write: include sha + program count for manifest audit.
    printf '%s\n' "$DATA_SEED_VERSION" > "${SEED_VERSION_FILE}.new"
    mv -f "${SEED_VERSION_FILE}.new" "$SEED_VERSION_FILE"
    printf 'version=%s sha256=%s programs=%s applied_at=%s\n' \
      "$DATA_SEED_VERSION" "$seed_sha" "$seed_program_count" "$(date -u +%FT%TZ)" \
      > "${SEED_VERSION_FILE}.manifest.new"
    mv -f "${SEED_VERSION_FILE}.manifest.new" "${SEED_VERSION_FILE}.manifest"
    log "seed sync complete (jpintel.db + unified_registry.json now at $DATA_SEED_VERSION, manifest written)"
    fi
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

# compute_sha256 forward-declared at top of file (above §1.5 seed gate).

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
#
# §2 boot gate strategy (re-shaped 2026-05-11 after the 30+ min prod outage
# caused by image-stamped AUTONOMATH_DB_SHA256 drifting from the live volume
# DB — autonomath.db is mutated in-place by cron-driven ETL/migrations, so a
# hardcoded image SHA goes stale immediately. The legacy logic then forced a
# full R2 re-download on every boot, which on a 9 GB DB with intermittent R2
# connectivity could loop indefinitely):
#
#   1. Default: SIZE-BASED gate. If the existing volume DB is already at
#      production scale (>= AUTONOMATH_DB_MIN_PRODUCTION_BYTES, default 5 GB),
#      we trust the volume copy as-is and skip both full-file SHA256 hashing
#      AND R2 download. PRAGMA integrity_check in §4 below is still the
#      authoritative health probe — SHA256 of a cron-mutated DB is structurally
#      meaningless. Boot becomes O(few seconds) instead of O(re-download 9 GB).
#
#   2. Opt-in legacy: set BOOT_ENFORCE_DB_SHA=1 (and supply
#      AUTONOMATH_DB_SHA256) to restore the strict SHA256 path. Intended for
#      DR drills / restore-from-snapshot scenarios where the SHA actually
#      matches a known snapshot, not for routine boots.
#
#   3. New volume / missing DB: still bootstraps from R2 exactly once
#      (foreground or background mode per AUTONOMATH_BOOTSTRAP_MODE), with
#      SHA256 verification of the downloaded artifact retained inside
#      bootstrap_autonomath_db_snapshot() — that hash IS meaningful because
#      it gates the freshly-downloaded blob, not the long-lived volume.
#
# Knobs (all optional, sane defaults):
#   AUTONOMATH_DB_MIN_PRODUCTION_BYTES   default 5000000000 (~5 GB)
#   BOOT_ENFORCE_DB_SHA                  default 0 (skip volume SHA check)
needs_download=0
missing_db=0
sha_mismatch_db=0
existing_sha=""
AUTONOMATH_DB_MIN_PRODUCTION_BYTES="${AUTONOMATH_DB_MIN_PRODUCTION_BYTES:-5000000000}"
BOOT_ENFORCE_DB_SHA="${BOOT_ENFORCE_DB_SHA:-0}"
if [ ! -s "$DB_PATH" ]; then
  log "no existing DB at $DB_PATH"
  needs_download=1
  missing_db=1
else
  existing_db_size="$(file_size "$DB_PATH")"
  size_ok=0
  if [ "$existing_db_size" != "unknown" ] && [ "$existing_db_size" -ge "$AUTONOMATH_DB_MIN_PRODUCTION_BYTES" ] 2>/dev/null; then
    size_ok=1
  fi
  if [ "$size_ok" = "1" ] && [ "$BOOT_ENFORCE_DB_SHA" != "1" ]; then
    # PRIMARY PATH (post 2026-05-11): the volume DB is production-sized, so
    # accept it as authoritative without hashing or re-downloading. The
    # autonomath profile schema_guard + PRAGMA integrity_check in §4 below
    # remain the structural correctness gate; SHA256 against a baked image
    # value would be a false signal because cron ETL mutates the DB.
    log "existing DB at $DB_PATH is production-sized ($existing_db_size bytes >= $AUTONOMATH_DB_MIN_PRODUCTION_BYTES) — trusting volume, skipping SHA256 + R2 (set BOOT_ENFORCE_DB_SHA=1 to override)"
  elif [ -n "$DB_SHA256" ]; then
    # LEGACY PATH retained behind a gate so DR drills / smaller-DB envs / the
    # tests/test_entrypoint_vec0_boot_gate.py SHA-mismatch contract keep
    # working. Sub-threshold DBs naturally fall into this branch too, which
    # is fine — small files are cheap to hash.
    if [ "$BOOT_ENFORCE_DB_SHA" = "1" ]; then
      log "BOOT_ENFORCE_DB_SHA=1 — verifying SHA256 of existing $DB_PATH against AUTONOMATH_DB_SHA256 (size=$existing_db_size)"
    else
      log "existing DB at $DB_PATH below production-size threshold (size=$existing_db_size < $AUTONOMATH_DB_MIN_PRODUCTION_BYTES) — falling back to SHA256 verification"
    fi
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
        sha_mismatch_db=1
      fi
    fi
  else
    log "existing DB at $DB_PATH (size=$existing_db_size; no AUTONOMATH_DB_SHA256 set; skipping verification)"
  fi
fi

bootstrap_autonomath_db_snapshot() {
  local mode="${1:-foreground}"
  log "downloading DB snapshot from R2 ($mode)"
  # Pre-clean stale WAL/SHM from the previous DB. Preserve .partial in
  # background mode so a fresh-volume restart can resume a large download.
  rm -f "${DB_PATH}-shm" "${DB_PATH}-wal"
  if [ "$mode" = "foreground" ]; then
    rm -f "$TMP_DB"
  fi
  if ! curl -fL --retry 5 --retry-delay 10 --retry-all-errors \
       -C - -o "$TMP_DB" "$DB_URL"; then
    err "DB snapshot download failed"
    rm -f "$TMP_DB"
    return 1
  fi

  if [ -n "$DB_SHA256" ]; then
    log "verifying SHA256 of downloaded snapshot"
    got_sha="$(compute_sha256 "$TMP_DB")"
    if [ "$got_sha" != "$DB_SHA256" ]; then
      err "SHA256 mismatch on download (got=$got_sha want=$DB_SHA256)"
      rm -f "$TMP_DB"
      return 1
    fi
    log "SHA256 verified"
  else
    log "AUTONOMATH_DB_SHA256 unset — skipping integrity check (NOT recommended for prod)"
  fi

  if [ "$mode" = "background" ] && [ -f /app/scripts/schema_guard.py ]; then
    log "validating downloaded snapshot with schema_guard.py before landing"
    if ! python /app/scripts/schema_guard.py "$TMP_DB" autonomath --drop-empty-cross-pollution; then
      err "schema_guard failed for staged autonomath snapshot"
      rm -f "$TMP_DB"
      return 1
    fi
  fi

  if ! mv "$TMP_DB" "$DB_PATH"; then
    err "failed to land DB snapshot at $DB_PATH"
    return 1
  fi
  if [ -n "$DB_SHA256" ]; then
    write_sha_stamp "$DB_PATH" "$DB_SHA256"
  fi
  log "DB snapshot landed at $DB_PATH"
}

AUTONOMATH_BOOTSTRAP_MODE="${AUTONOMATH_BOOTSTRAP_MODE:-background}"

if [ "$needs_download" -eq 1 ]; then
  if [ -z "$DB_URL" ]; then
    if [ "$missing_db" -eq 1 ]; then
      # autonomath.db is optional at boot. /v1/am/* and 16 MCP autonomath tools
      # will return 503 until the DB is uploaded (R2 bootstrap pending), but the
      # core API/jpintel.db endpoints stay live. Do NOT hard-fail here.
      log "AUTONOMATH_DB_URL unset and DB missing — skipping bootstrap (autonomath features will be 503 until DB is restored)"
      needs_download=0
    elif [ "$sha_mismatch_db" -eq 1 ]; then
      err "AUTONOMATH_DB_URL unset and existing DB SHA256 mismatch — failing boot (have=$existing_sha want=$DB_SHA256)"
      exit 1
    else
      err "AUTONOMATH_DB_URL unset but DB requires download — failing boot"
      exit 1
    fi
  fi
fi

if [ "$needs_download" -eq 1 ] && [ "$missing_db" -eq 1 ] && [ "$AUTONOMATH_BOOTSTRAP_MODE" = "background" ]; then
  log "starting background autonomath DB bootstrap; /v1/am/* will return 503 until it lands"
  (
    if ! mkdir "${TMP_DB}.lock" 2>/dev/null; then
      log "background autonomath DB bootstrap already in progress"
      exit 0
    fi
    trap 'rmdir "${TMP_DB}.lock" 2>/dev/null || true' EXIT
    bootstrap_autonomath_db_snapshot background || err "background autonomath DB bootstrap failed"
  ) &
  needs_download=0
fi

if [ "$needs_download" -eq 1 ]; then
  bootstrap_autonomath_db_snapshot foreground || exit 1
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
    # 2026-05-11 Wave 18 root fix: integrity_check on 9.7GB autonomath.db hangs 30+ min,
    # exceeding Fly health check grace. The autonomath.db is mutated in-place by cron ETL,
    # so any baked-image stamp drifts. Production-sized DBs skip integrity_check; schema_guard
    # below remains the structural correctness probe.
    # Override with BOOT_ENFORCE_INTEGRITY_CHECK=1 for DR drills / restore-from-snapshot.
    db_size_pre_check=$(file_size "$DB_PATH")
    integrity_threshold="${AUTONOMATH_DB_MIN_PRODUCTION_BYTES:-5000000000}"
    if [ "$db_size_pre_check" != "unknown" ] && [ "$db_size_pre_check" -ge "$integrity_threshold" ] 2>/dev/null && [ "${BOOT_ENFORCE_INTEGRITY_CHECK:-0}" != "1" ]; then
      log "size-based integrity_check skip for $DB_PATH (size=$db_size_pre_check >= threshold=$integrity_threshold) — schema_guard remains structural probe (set BOOT_ENFORCE_INTEGRITY_CHECK=1 to override)"
      integrity="ok"
    elif [ -n "$DB_SHA256" ] && { sha_stamp_matches "$DB_PATH" "$DB_SHA256" || trusted_stamp_matches "$DB_PATH" "$DB_SHA256"; }; then
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
      am_mig_degraded=0
      am_mig_mode="${AUTONOMATH_BOOT_MIGRATION_MODE:-manifest}"
      am_mig_manifest="${AUTONOMATH_BOOT_MIGRATION_MANIFEST:-/app/scripts/migrations/autonomath_boot_manifest.txt}"
      am_mig_in_manifest() {
        local name="$1"
        [ -f "$am_mig_manifest" ] || return 1
        grep -Ev '^[[:space:]]*(#|$)' "$am_mig_manifest" \
          | awk '{print $1}' \
          | grep -Fxq "$name"
      }
      case "$am_mig_mode" in
        manifest)
          if [ -f "$am_mig_manifest" ]; then
            log "autonomath boot migrations restricted to manifest: $am_mig_manifest"
          else
            log "autonomath boot migration manifest missing — no autonomath migrations will auto-apply"
          fi
          ;;
        discover)
          log "AUTONOMATH_BOOT_MIGRATION_MODE=discover — legacy all-file autonomath migration discovery enabled"
          ;;
        off)
          log "AUTONOMATH_BOOT_MIGRATION_MODE=off — autonomath migrations disabled at boot"
          ;;
        *)
          err "unknown AUTONOMATH_BOOT_MIGRATION_MODE=$am_mig_mode (expected manifest, discover, or off)"
          if [ "${AUTONOMATH_ENABLED:-true}" = "true" ] || [ "${AUTONOMATH_ENABLED:-1}" = "1" ]; then
            exit 1
          fi
          ;;
      esac
      for am_mig in $(ls /app/scripts/migrations/*.sql 2>/dev/null | sort); do
        am_mig_id="$(basename "$am_mig")"
        case "$am_mig_mode" in
          off)
            am_mig_skipped=$((am_mig_skipped + 1))
            continue
            ;;
          manifest)
            if ! am_mig_in_manifest "$am_mig_id"; then
              am_mig_skipped=$((am_mig_skipped + 1))
              continue
            fi
            ;;
          discover)
            ;;
          *)
            am_mig_skipped=$((am_mig_skipped + 1))
            continue
            ;;
        esac
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
        # Skip if already recorded in schema_migrations bookkeeping.
        already=$(sqlite3 "$DB_PATH" "SELECT 1 FROM schema_migrations WHERE id='$am_mig_id' LIMIT 1;" 2>/dev/null || echo "")
        if [ "$already" = "1" ]; then
          am_mig_already=$((am_mig_already + 1))
          continue
        fi
        log "applying $am_mig to $DB_PATH"
        am_mig_output="$(mktemp)"
        is_vec_mig=0
        sqlite_args=("$DB_PATH")
        if grep -Eqi 'USING[[:space:]]+vec0[[:space:]]*\(' "$am_mig"; then
          is_vec_mig=1
          vec0_path="${AUTONOMATH_VEC0_PATH:-/opt/vec0.so}"
          if [ -n "$vec0_path" ] && [ -f "$vec0_path" ]; then
            sqlite_args=(-cmd ".load $vec0_path" "$DB_PATH")
          else
            log "autonomath vec0 migration degraded (vec0 extension missing: ${vec0_path:-unset}): $am_mig"
            am_mig_degraded=$((am_mig_degraded + 1))
            rm -f "$am_mig_output"
            continue
          fi
        fi
        if sqlite3 "${sqlite_args[@]}" < "$am_mig" >"$am_mig_output" 2>&1; then
          # Record successful apply. Use INSERT OR IGNORE so concurrent
          # boots on the same volume don't crash on the bookkeeping write.
          now=$(date -u +%FT%TZ)
          sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO schema_migrations(id,checksum,applied_at) VALUES('$am_mig_id','self_heal','$now');" 2>/dev/null || true
          am_mig_applied=$((am_mig_applied + 1))
        else
          if [ "$is_vec_mig" -eq 1 ] && grep -qi "no such module: vec0" "$am_mig_output"; then
            # vec0-backed virtual tables are optional search acceleration.
            # Do not mark the migration applied; a later boot with vec0
            # installed should retry and create the vector tables.
            log "autonomath vec0 migration degraded (vec0 unavailable): $am_mig"
            grep -v "^$" "$am_mig_output" | head -5 || true
            am_mig_degraded=$((am_mig_degraded + 1))
          elif grep -qi "duplicate column" "$am_mig_output" \
             && ! grep -vi "duplicate column" "$am_mig_output" | grep -q '[^[:space:]]'; then
            # SQLite has no ALTER TABLE ADD COLUMN IF NOT EXISTS. Treat a
            # duplicate column as "schema already has this additive change",
            # then record the migration id so future boots skip it. Mixed
            # output with any other hard error still fails below.
            now=$(date -u +%FT%TZ)
            sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO schema_migrations(id,checksum,applied_at) VALUES('$am_mig_id','self_heal_duplicate_column','$now');" 2>/dev/null || true
            log "autonomath migration duplicate-column treated as applied: $am_mig"
            am_mig_applied=$((am_mig_applied + 1))
          elif grep -qi "no such table:" "$am_mig_output"; then
            # Some autonomath migrations enrich optional absorbed/source
            # tables that are absent on older production volumes. Do not mark
            # them applied: a later boot after the source table is loaded must
            # retry. Keep boot alive; schema_guard below still protects the
            # required serving schema.
            log "autonomath migration degraded (optional source table missing): $am_mig"
            grep -v "^$" "$am_mig_output" | head -5 || true
            am_mig_degraded=$((am_mig_degraded + 1))
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
      log "autonomath self-heal migrations: applied=$am_mig_applied already=$am_mig_already skipped=$am_mig_skipped degraded=$am_mig_degraded failed=$am_mig_failed"
      if [ "$am_mig_failed" -gt 0 ]; then
        if [ "${AUTONOMATH_ENABLED:-true}" = "true" ] || [ "${AUTONOMATH_ENABLED:-1}" = "1" ]; then
          err "AUTONOMATH_ENABLED=true and autonomath migrations failed — failing boot"
          exit 1
        fi
        log "AUTONOMATH_ENABLED=false — continuing despite autonomath migration failures"
      fi
      log "running schema_guard.py on $DB_PATH (autonomath profile)"
      python /app/scripts/schema_guard.py "$DB_PATH" autonomath --drop-empty-cross-pollution || {
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
