-- target_db: jpintel
-- migration 108_api_keys_id_unique_nonpartial
--
-- BUG FIX (caught 2026-04-29 in migration audit):
--
-- The `uniq_api_keys_id` UNIQUE INDEX on `api_keys(id)` was originally
-- created with a `WHERE id IS NOT NULL` partial filter. Migration 086
-- explicitly notes this was a bug: SQLite refuses to use a *partial*
-- UNIQUE INDEX as the referent of a FOREIGN KEY.
--
-- Migration 086 was rewritten to drop the partial filter, but the
-- production jpintel.db still carries the legacy partial index because
-- `CREATE UNIQUE INDEX IF NOT EXISTS` is a no-op when an index of the
-- same name already exists, regardless of definition. Result: every
-- `INSERT INTO api_keys(... parent_key_id ...)` fails with
-- "foreign key mismatch — api_keys referencing api_keys".
--
-- Reproduce:
--   sqlite3 data/jpintel.db "PRAGMA foreign_keys=ON;
--     INSERT INTO api_keys(key_hash,customer_id,tier,created_at,id) VALUES('p','c','paid','2026',1);
--     INSERT INTO api_keys(key_hash,customer_id,tier,created_at,id,parent_key_id) VALUES('c','c','paid','2026',2,1);"
--   → Error: foreign key mismatch
--
-- Fix: DROP the partial index and recreate non-partial. The `id` column
-- has zero NULL values in production (`UPDATE ... SET id = rowid WHERE
-- id IS NULL` from migration 086 + the issue_child_key code path keep
-- it backfilled), so a non-partial UNIQUE INDEX is safe — even if NULL
-- legacy rows existed, SQLite treats every NULL as distinct under
-- UNIQUE.
--
-- Idempotency: DROP INDEX IF EXISTS is safe on re-run; the recreated
-- index uses CREATE UNIQUE INDEX IF NOT EXISTS so the second pass is a
-- no-op.

DROP INDEX IF EXISTS uniq_api_keys_id;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_api_keys_id
    ON api_keys(id);

-- Bookkeeping recorded by scripts/migrate.py.
