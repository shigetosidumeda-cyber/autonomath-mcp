-- migration 219_jpi_user_search_history
-- target_db: jpintel  (default; consumed by scripts/migrate.py — NO `target_db: autonomath` header)
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #4 (検索履歴、retention 90 day)
--
-- Purpose
-- -------
-- Authenticated users want a "再検索" button on the dashboard that
-- replays the last N searches against the current corpus. Without
-- a history table, that requires browser localStorage (incompatible
-- across devices) or per-keystroke logging (massive privacy ask).
--
-- 90-day retention is the contract: rows older than that are deleted
-- nightly by `scripts/cron/expire_user_history.py` (NEW, not in this
-- migration). Retention period is documented in the privacy policy
-- and surfaced in the dashboard UI.
--
-- Privacy posture
-- ---------------
-- - Each row keys on `key_hash` (the SHA-256 of the API key), NOT the
--   raw key. We never persist plaintext keys.
-- - `query_text` is the raw query string the user typed. We will
--   re-show this to them on re-render; it is not third-party data.
-- - `result_count` is recorded but result IDs are NOT (those are
--   transient and would balloon the table).
-- - No IP, no User-Agent, no referer. The minimum surface needed for
--   re-replay.
-- - 90-day TTL is enforced by index + cron job, not a SQLite trigger
--   (triggers fire per-row and don't compose with the bulk DELETE).
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/me/history` (list, 50 most recent),
--   `DELETE /v1/me/history` (purge all), `DELETE /v1/me/history/{id}`.
-- - Anonymous (no API key) callers cannot use this surface — it's
--   keyed on hashed key.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jpi_user_search_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash        TEXT    NOT NULL,                    -- SHA-256 of API key
    query_text      TEXT    NOT NULL,                    -- user-typed query
    query_kind      TEXT    NOT NULL,                    -- 'programs' | 'cases' | 'laws' | 'tax_rules' | 'mixed'
    result_count    INTEGER,                             -- top-level rowcount (may be NULL on error)
    duration_ms     INTEGER,                             -- server-side end-to-end ms
    requested_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Soft-delete flag — DELETE /v1/me/history/{id} flips this rather
    -- than removing the row immediately, so the operator can audit
    -- a deletion claim before cron sweeps the row.
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    deleted_at      TEXT,
    CONSTRAINT ck_history_kind CHECK (query_kind IN (
        'programs', 'cases', 'laws', 'tax_rules', 'mixed', 'other'
    )),
    CONSTRAINT ck_history_deleted CHECK (is_deleted IN (0, 1))
);

-- Per-key chronological access (dashboard "history" tab).
CREATE INDEX IF NOT EXISTS idx_jpi_user_history_recent
    ON jpi_user_search_history(key_hash, requested_at DESC)
    WHERE is_deleted = 0;

-- Retention sweep index — cron job filters by requested_at < now-90d.
CREATE INDEX IF NOT EXISTS idx_jpi_user_history_retention
    ON jpi_user_search_history(requested_at);

-- Soft-delete clean-up index.
CREATE INDEX IF NOT EXISTS idx_jpi_user_history_deleted
    ON jpi_user_search_history(deleted_at)
    WHERE is_deleted = 1;

-- View: per-user 50 most recent (after soft-delete). The router
-- ORDERs by `id DESC` so this view is a convenience over the index.
DROP VIEW IF EXISTS v_jpi_user_history_recent;
CREATE VIEW v_jpi_user_history_recent AS
SELECT
    id,
    key_hash,
    query_text,
    query_kind,
    result_count,
    duration_ms,
    requested_at
FROM jpi_user_search_history
WHERE is_deleted = 0;
