-- 023_device_codes.sql
-- OAuth 2.0 Device Authorization Grant (RFC 8628) state table.
--
-- Purpose: eliminate the "hit 429 → sign up → copy API key → edit
-- claude_desktop_config.json → restart Claude" friction for MCP users.
-- Instead the MCP server opens a short-lived `device_code`, shows the
-- user a verification URL + short `user_code`, polls until activated,
-- then stores the resulting api_key in the OS keychain automatically.
--
-- ============================================================================
-- PROTOCOL SURFACE (RFC 8628)
-- ============================================================================
-- * POST /v1/device/authorize   -> mint (device_code, user_code) pair
-- * POST /v1/device/token       -> client poll; returns authorization_pending,
--                                   slow_down, access_denied, expired_token, or
--                                   the issued access_token on activation
-- * POST /v1/device/complete    -> called by /go activation page after Stripe
--                                   Checkout succeeds (NOT an RFC 8628 endpoint,
--                                   but our "user finished payment" hook)
--
-- ============================================================================
-- KEY SCHEMA DECISIONS
-- ============================================================================
-- * device_code is opaque, 64 hex chars (32 random bytes). Never human-typed.
-- * user_code is the short human-enterable code shown in the URL:
--   8 chars from ABCDEFGHJKLMNPQRSTUVWXYZ23456789 (no ambiguous 0/O/1/I/L)
--   with a dash inserted at offset 4 → "ABCD-1234" style. Declared UNIQUE so
--   two live codes never collide.
-- * status CHECK ('pending','activated','expired','denied'): narrow on
--   purpose; a typo in Python code fails loudly at INSERT time instead of
--   silently creating a fifth state.
-- * expires_at = created_at + 15 min. Both stored as ISO 8601 UTC strings
--   (TEXT) to match the project convention (see api_keys, anon_rate_limit).
-- * client_fingerprint is hashed client metadata (OS, hostname hash, MCP
--   version) — privacy-preserving, used only for dashboards. Never a raw
--   hostname or IP.
-- * linked_api_key_id references api_keys(key_hash). `key_hash` is the PK
--   of api_keys in this schema; the spec's "linked_api_key_id REFERENCES
--   api_keys(key_id)" wording is aspirational — we reference the actual
--   PK column so the FK is valid today.
-- * verification_uri / verification_uri_complete stored denormalized so a
--   future domain change doesn't orphan in-flight codes.
-- * Stripe session/customer linked after /complete so we can reconcile a
--   device_code → paid subscription → api_key chain for support triage.
--
-- ============================================================================
-- EXPIRY / SWEEP
-- ============================================================================
-- Either the /token endpoint marks status='expired' inline when it sees
-- expires_at < now (cheap, zero new infra) OR scripts/expire_device_codes.py
-- sweeps the table for ops cleanup. A trailing index on expires_at makes
-- the sweep O(log n) even on a million-row table.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- migration runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS device_codes (
    device_code TEXT PRIMARY KEY,                       -- 64 hex chars, opaque
    user_code TEXT NOT NULL UNIQUE,                     -- 'ABCD-1234' (9 chars)
    status TEXT NOT NULL DEFAULT 'pending',
    client_fingerprint TEXT,                            -- SHA256 hex of (OS|hostname|version)
    scope TEXT DEFAULT 'api:read api:metered',
    created_at TEXT NOT NULL,                           -- ISO 8601 UTC
    expires_at TEXT NOT NULL,                           -- created_at + 15 min
    poll_interval_sec INTEGER NOT NULL DEFAULT 5,
    last_polled_at TEXT,                                -- ISO 8601 UTC; NULL until first poll
    activated_at TEXT,                                  -- ISO 8601 UTC; NULL until activated
    linked_api_key_id TEXT,                             -- FK to api_keys(key_hash)
    verification_uri TEXT NOT NULL,                     -- e.g. https://autonomath.ai/go
    verification_uri_complete TEXT NOT NULL,            -- e.g. https://autonomath.ai/go/ABCD-1234
    stripe_checkout_session_id TEXT,                    -- cs_... set on /complete
    stripe_customer_id TEXT,                            -- cus_... set on /complete
    raw_pickup TEXT,                                    -- one-time raw api_key handoff
    raw_pickup_consumed_at TEXT,                        -- cleared on first successful /token poll
    CHECK(status IN ('pending','activated','expired','denied')),
    FOREIGN KEY(linked_api_key_id) REFERENCES api_keys(key_hash)
);

-- raw_pickup note:
-- The device flow needs to hand the RAW api_key to the client exactly once
-- (via /token) after /complete activates the code. api_keys only stores
-- the HASH (by design — we never retain raw keys). So we stash the raw
-- key transiently in raw_pickup, and /token reads-and-clears it on the
-- first successful poll. A DB column (vs in-memory dict) survives API
-- process restarts during the 15-min device flow window. After the first
-- poll we NULL raw_pickup and set raw_pickup_consumed_at — the raw key
-- lives in the DB for at most one poll interval (~5 sec) in normal flow.

-- Pending-code lookups dominate during the 15-minute poll window.
CREATE INDEX IF NOT EXISTS idx_device_codes_status ON device_codes(status);

-- user_code is already UNIQUE (the UNIQUE constraint implicitly creates an
-- index), but an explicit index keeps EXPLAIN QUERY PLAN readable for ops.
CREATE INDEX IF NOT EXISTS idx_device_codes_user_code ON device_codes(user_code);

-- Expiry sweep: find all rows where status='pending' AND expires_at < now.
CREATE INDEX IF NOT EXISTS idx_device_codes_expires ON device_codes(expires_at);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
