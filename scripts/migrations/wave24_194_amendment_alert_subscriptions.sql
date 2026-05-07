-- target_db: jpintel
-- migration: wave24_194_amendment_alert_subscriptions
-- generated_at: 2026-05-07
-- author: R8 amendment-alert subscription feed (jpcite v0.3.4)
-- spec: tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_AMENDMENT_ALERT_FEED_2026-05-07.md
--
-- Purpose
-- -------
-- New "法令改正 alert subscription feed" surface. Distinct from migration 038
-- (`alert_subscriptions`, the legacy filter_type/min_severity table) — this
-- table stores **multi-watch JSON** so a single subscription can target a
-- list of (program_id, law_id, industry_jsic) entries at once and the daily
-- fan-out cron joins it against `am_amendment_diff` (autonomath.db, 12,116
-- rows as of 2026-05-07).
--
-- Why a new table (not an ALTER on alert_subscriptions)
-- -----------------------------------------------------
--   1. Migration 038 schema commits to single (filter_type, filter_value)
--      pairs. Adding a watch_json column would break the CHECK constraint
--      semantics (filter_type='all' must keep filter_value NULL — adding
--      JSON would create two competing match shapes on the same row).
--   2. The new feed surface (POST /v1/me/amendment_alerts/subscribe) speaks
--      multi-watch from day one (the body is `watch: [{type, id}, ...]`).
--      A separate table keeps the legacy single-filter alerts.py router
--      and the new amendment_alerts.py router from contending for the
--      same row space.
--   3. Distinct fan-out cadence: legacy alerts cron runs daily at 05:30 JST
--      and reads `am_amendment_snapshot`. The new feed cron reads
--      `am_amendment_diff` (per-field deltas, append-only) and emits a
--      90-day rolling feed window per subscription. Decoupling the two
--      tables avoids cross-cron interference.
--
-- Schema
-- ------
-- * id              — autoincrement PRIMARY KEY (returned as subscription_id).
-- * api_key_id      — FK target column on api_keys.id (rowid alias).
--                     Stored as INTEGER. Migration 086 introduced the rowid
--                     alias; older keys may have NULL ids — the application
--                     layer rejects subscribe attempts from such keys with
--                     a clear 401, never silently nulls the FK.
-- * api_key_hash    — denormalized HMAC for fast lookup by key (the deps
--                     ApiContext carries `key_hash`; resolving id requires
--                     an extra round-trip we avoid on the GET feed path).
-- * watch_json      — TEXT JSON array of watch entries. Each entry is
--                     `{"type": "program_id"|"law_id"|"industry_jsic",
--                       "id": "<string>"}`. NULL not allowed — at least one
--                     watch is required (the application layer also enforces
--                     a max length of 50 entries to keep cron O(N×M) bounded).
-- * created_at      — ISO-8601 UTC, datetime('now') default.
-- * deactivated_at  — NULL while active. Soft-delete on DELETE; the row
--                     remains for audit-trail reasons. Cron filters
--                     `deactivated_at IS NULL`.
-- * last_fanout_at  — ISO-8601 UTC of the most recent successful fan-out
--                     run that scanned this subscription. NULL until the
--                     first run. Cron uses MIN(last_fanout_at) across
--                     subscriptions to compute its scan window per shard.
--
-- Indexes
-- -------
-- * idx_amendment_alert_sub_key  — (api_key_id, deactivated_at)
--   GET /v1/me/amendment_alerts/feed lists the calling key's active
--   subscriptions; the partial-active form on (api_key_id) WHERE
--   deactivated_at IS NULL keeps the hot read O(log n).
-- * idx_amendment_alert_sub_active — (deactivated_at, last_fanout_at)
--   Cron sweep filters `deactivated_at IS NULL ORDER BY last_fanout_at`
--   to drain oldest-first.
--
-- Idempotency
-- -----------
-- CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS — re-running on a
-- DB where the table already exists is a no-op. No ALTER TABLE clauses.
--
-- Cost posture
-- ------------
-- Subscription create / list / delete are FREE. Fan-out is FREE retention
-- (no usage_event / Stripe metering). project_autonomath_business_model
-- keeps ¥3/req immutable; this is a cohort-key feature for 税理士 / 補助金
-- consultant retention.
--
-- LLM call: 0. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS amendment_alert_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id      INTEGER,
    api_key_hash    TEXT NOT NULL,
    watch_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deactivated_at  TEXT,
    last_fanout_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_amendment_alert_sub_key
    ON amendment_alert_subscriptions(api_key_hash, deactivated_at);

CREATE INDEX IF NOT EXISTS idx_amendment_alert_sub_active
    ON amendment_alert_subscriptions(deactivated_at, last_fanout_at);

-- Bookkeeping recorded by scripts/migrate.py into schema_migrations
-- (id, checksum, applied_at). Do NOT INSERT here.
