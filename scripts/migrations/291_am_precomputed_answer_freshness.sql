-- target_db: autonomath
-- migration 291_am_precomputed_answer_freshness (P4 — freshness tracking + auto-invalidate)
--
-- Background
-- ----------
-- P3 landed 500 precomputed answer rows in `am_precomputed_answer` (composed
-- envelopes that resolve to a single ¥3 SELECT instead of a 5-7 join hot
-- path). When law amendment lands in `am_amendment_diff` (cron-live since
-- 2026-05-02), the upstream law_article / tax_rule / program a precomputed
-- answer was composed from may have changed — yet the answer row continues
-- to serve from cache verbatim with a now-stale eligibility / amount /
-- effective-date payload. P4 closes that hole.
--
-- What this migration does
-- ------------------------
--   1. Idempotent CREATE of `am_precomputed_answer` so the freshness columns
--      add safely whether or not P3's seed migration has landed on this DB.
--      The shape matches P2 composer output (one composed_answer_json blob
--      per question_id + version_seq column for INSERT OR REPLACE).
--   2. Adds 4 freshness columns (ALTER TABLE … ADD COLUMN — entrypoint.sh §4
--      treats duplicate-column failures as already-applied, so re-runs on
--      booted DBs are safe):
--        * freshness_state TEXT — 'fresh' / 'stale' / 'expired' (default 'fresh')
--        * last_validated_at TIMESTAMP — wall-clock of the last freshness sweep
--        * invalidation_reason TEXT — human-readable cause string (the
--          法人税法34条改正 2026-04-01 case is the canonical example)
--        * amendment_diff_ids TEXT — JSON array of `am_amendment_diff.diff_id`
--          rows that flipped this answer to stale (SQLite stores JSON as TEXT;
--          callers parse with json.loads)
--   3. Two supporting indexes for the hourly cron sweep:
--        * state-partial index on freshness_state for `WHERE freshness_state =
--          'stale'` lookups in the re-compose loop
--        * detected_at index for the join against `am_amendment_diff`
--
-- Why ALTER instead of a redefined table
-- --------------------------------------
-- The 500 P3 rows are immutable cache content — recomposing them from the
-- entity_id walk on every boot would re-run the P2 composer (which P3 ran
-- offline to populate). ADD COLUMN preserves the cache content and only adds
-- the bookkeeping axis. The legacy boot path keeps working with NULL/default
-- values until the P4 cron sweep stamps them.
--
-- Append-only contract on amendment_diff_ids
-- ------------------------------------------
-- The cron writes ONE JSON array per affected answer per sweep. The Python
-- caller READs the existing value, merges new diff_ids into the set, and
-- writes back the union — so the column accumulates lineage across multiple
-- amendment events instead of overwriting the first one. The cron never
-- DELETEs rows from this table; expired answers stay queryable for audit
-- with `freshness_state='expired'` until P5 (cohort retire) lands.
--
-- Idempotency
-- -----------
-- * CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
-- * ALTER TABLE ADD COLUMN relies on entrypoint.sh §4's duplicate-column
--   shim (lines 666-668) to treat re-runs as already-applied.
-- * No DELETE / UPDATE in this file — those happen at cron time.

PRAGMA foreign_keys = ON;

-- Safety: if the table is somehow absent (dev DB / pre-P3), create it with
-- the minimum question_id PK so the ALTER below can run. Live prod DB
-- already carries the wider P3 schema (answer_id / cohort / faq_slug /
-- composed_from / version_seq / etc.); CREATE IF NOT EXISTS is a no-op there.
CREATE TABLE IF NOT EXISTS am_precomputed_answer (
    question_id   TEXT PRIMARY KEY,
    composed_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- P4 additive columns. ADD COLUMN raises 'duplicate column' on re-run;
-- entrypoint.sh §4 (lines 666-668) treats that as already-applied and stamps
-- schema_migrations with the 'self_heal_duplicate_column' sentinel.
ALTER TABLE am_precomputed_answer ADD COLUMN freshness_state TEXT DEFAULT 'fresh';
ALTER TABLE am_precomputed_answer ADD COLUMN last_validated_at TIMESTAMP;
ALTER TABLE am_precomputed_answer ADD COLUMN invalidation_reason TEXT;
ALTER TABLE am_precomputed_answer ADD COLUMN amendment_diff_ids TEXT;

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_freshness
    ON am_precomputed_answer(freshness_state, last_validated_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_precomputed_answer_validated
    ON am_precomputed_answer(last_validated_at DESC);

-- schema_migrations bookkeeping is stamped by entrypoint.sh §4 self-heal.
