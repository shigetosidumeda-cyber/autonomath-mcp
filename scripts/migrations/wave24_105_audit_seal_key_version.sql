-- target_db: jpintel
-- migration wave24_105_audit_seal_key_version (S1 ship-stop, MASTER_PLAN_v1 章 2 §S1)
--
-- Why this exists:
--   `_audit_seal.py` historically signed every seal with a single
--   `settings.audit_seal_secret`. Rotating that secret at any point
--   would flip every previously issued seal to verified=false, breaking
--   the long-tail integrity-check guarantee for receipts already in
--   customer hands.
--
--   This migration introduces a key-version column on `audit_seals` plus
--   an `audit_seal_keys` registry so the verifier can hold N keys
--   simultaneously: new signs use the active key, but verifies walk all
--   non-retired keys (and retired ones too, in case a customer presents
--   an older seal). Operators rotate via tools/offline/rotate_audit_seal.py
--   then publish the new JPINTEL_AUDIT_SEAL_KEYS Fly secret.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN raises "duplicate column name" on re-run; the
--   entrypoint loop swallows that OperationalError (same pattern used by
--   migrations 049 / 101 / 119). The CREATE TABLE / CREATE INDEX use
--   IF NOT EXISTS.
--
-- DOWN:
--   See companion `wave24_105_audit_seal_key_version_rollback.sql`. We
--   never auto-drop key registry rows in production — see rollback notes.

PRAGMA foreign_keys = ON;

-- 1. Add key_version column to audit_seals.
--    DEFAULT 1 so legacy rows (pre-migration) are tagged as key_version=1
--    consistent with the legacy single-secret path. NOT NULL on new
--    inserts; existing rows get the default at ALTER time.
ALTER TABLE audit_seals ADD COLUMN key_version INTEGER NOT NULL DEFAULT 1;

-- 2. Key registry table.
--    secret_argon2 stores the argon2id hash of the secret (NOT the
--    secret itself) so a DB compromise alone does not let an attacker
--    forge seals. The actual secret material lives ONLY in the Fly
--    secret JPINTEL_AUDIT_SEAL_KEYS (JSON array) plus the operator's
--    local backup. last_seen_at is updated fire-and-forget when verify
--    succeeds against a given key version (lets ops know which keys are
--    still in active rotation by retired customers).
CREATE TABLE IF NOT EXISTS audit_seal_keys (
    key_version    INTEGER PRIMARY KEY,
    secret_argon2  TEXT,
    activated_at   TEXT NOT NULL,
    retired_at     TEXT,
    last_seen_at   TEXT,
    notes          TEXT
);

-- 3. Lookup index — verify path filters by key_version when the seal
--    carries one. Most seals will share the active key_version so this
--    is also useful for "which keys produced N seals" rollups.
CREATE INDEX IF NOT EXISTS idx_audit_seal_key_version
    ON audit_seals(key_version);

-- Bookkeeping recorded by scripts/migrate.py via schema_migrations.
-- Do NOT INSERT here.
