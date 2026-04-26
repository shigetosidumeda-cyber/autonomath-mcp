-- migration 073: api_keys.key_hash_bcrypt — bcrypt dual-path storage
--
-- Background (Wave 16 abuse-defense audit, P1):
--   The legacy API-key hash is HMAC-SHA256(api_key_salt, raw_key) — stored
--   in `api_keys.key_hash` (PRIMARY KEY). Single-round HMAC-SHA256 is
--   deterministic and fast; an offline brute-force attack against an
--   exfiltrated DB only needs to compute the same HMAC over a candidate
--   key space. With `am_` prefix + 32 bytes of secrets.token_urlsafe (≈190
--   bits), brute force is currently infeasible — but the salt is a single
--   per-deployment value, so a salt leak collapses the work factor.
--
--   bcrypt with cost factor 12 raises the per-attempt cost from microseconds
--   to ~100ms. Dual-path lets us migrate without breaking existing keys:
--
--     * NEW keys (issued after this migration): both `key_hash` (HMAC,
--       used as PRIMARY KEY for fast lookup) AND `key_hash_bcrypt`
--       (bcrypt over raw key) are written.
--     * LEGACY keys (issued before this migration): only `key_hash` is
--       populated; `key_hash_bcrypt` stays NULL until the customer next
--       signs in via /v1/session at which point we cannot recompute
--       (we only have the hash). Customer rotation -> new bcrypt entry.
--     * VERIFY at auth time: lookup row by HMAC PRIMARY KEY (O(log n)),
--       then if bcrypt column is non-NULL run bcrypt.checkpw on the
--       raw key. If NULL fall through to legacy HMAC verify (already
--       successful by virtue of the row lookup).
--
-- Schema:
--   key_hash_bcrypt TEXT
--     bcrypt hash of the raw API key, cost factor 12 (~100ms/attempt on
--     modern hardware). NULL on legacy rows. Format is the standard
--     `$2b$12$<22-char-salt><31-char-hash>` (60 chars total).
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is no-op-on-duplicate per the migrate runner.
--
-- DOWN (commented; SQLite < 3.35 cannot drop columns; nullable column is
-- safe to leave on rollback):
--   -- (no-op)

PRAGMA foreign_keys = ON;

ALTER TABLE api_keys ADD COLUMN key_hash_bcrypt TEXT;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
