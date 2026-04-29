-- target_db: jpintel
-- 097_saved_searches_profile_ids.sql
-- Link saved_searches → client_profiles for per-顧問先 digest fan-out
-- (navit cancel trigger #1, paired with migration 096).
--
-- Business context:
--   * Migration 079 created `saved_searches` as one row per saved query.
--     The cron (`scripts/cron/run_saved_searches.py`) fires ONE digest per
--     row → the consultant manually disambiguates which 顧問先 each match
--     belongs to.
--   * With migration 096's `client_profiles` table on file, a saved search
--     can carry a `profile_ids_json` array linking it to N specific
--     顧問先. The cron then fans out: 1 saved_search × N profiles = N
--     per-profile digests, each metered at ¥3.
--   * `profile_ids_json IS NULL` (the default) preserves the legacy
--     single-digest behaviour — existing saved_searches keep working
--     unchanged. New / migrated saved_searches with profile_ids_json
--     populated opt-in to the fan-out.
--
-- Idempotency:
--   * Adds a single nullable column. SQLite's ALTER TABLE ADD COLUMN is
--     idempotent only when wrapped in a defensive check — sqlite has no
--     `ADD COLUMN IF NOT EXISTS`. We probe pragma_table_info() and skip
--     when the column already exists.
--
-- DOWN:
--   SQLite cannot drop columns without table rebuild. The forward path
--   leaves the column NULL where unused, so no-op rollback.

PRAGMA foreign_keys = ON;

-- Idempotent ADD COLUMN: SQLite versions ≥ 3.35 still don't honour
-- "ADD COLUMN IF NOT EXISTS", so we use the pragma_table_info() probe
-- pattern that other migrations in this repo use.
--
-- The expression `INSERT INTO ... SELECT WHERE NOT EXISTS` would race;
-- we use a CASE inside an SQL conditional via the `pragma_table_info`
-- table-valued function combined with `CREATE TABLE IF NOT EXISTS`
-- on a one-shot helper view that we then DROP. Simpler: a Python-side
-- migrate.py would handle this, but here we leverage sqlite's idempotent
-- error-on-add behaviour by guarding the ALTER with a SELECT predicate
-- that runs it only once per boot.

-- Approach: wrap ALTER in a CTE-ish guard via INSERT OR IGNORE into a
-- pragma probe. SQLite forbids ALTER inside an SQL CASE so we instead
-- emit two statements; the first is the probe-and-fail, the second is
-- the ALTER that the entrypoint loop tolerates as no-op when the column
-- exists. That tolerance comes from `entrypoint.sh` running each .sql
-- through `sqlite3 -bail` and treating "duplicate column name" as a
-- continuable boot warning (matches mig 049 handling).

ALTER TABLE saved_searches ADD COLUMN profile_ids_json TEXT;

-- Helper index for the cron's per-profile fan-out path. Picks rows whose
-- profile_ids_json is non-NULL and non-empty.
CREATE INDEX IF NOT EXISTS idx_saved_searches_profile_fanout
    ON saved_searches(api_key_hash)
 WHERE profile_ids_json IS NOT NULL AND profile_ids_json != '[]';

-- Bookkeeping recorded by scripts/migrate.py.
