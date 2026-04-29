-- target_db: autonomath
-- migration 110_autonomath_drop_cross_pollution
--
-- BUG FIX (caught 2026-04-29 in migration audit):
--
-- autonomath.db carries an empty `programs` table that schema_guard.py
-- (AM_FORBIDDEN = {"programs"}) flags as a Wave-8-class FORBIDDEN
-- table. The table is empty (0 rows in production at audit time)
-- because the legitimate program corpus on autonomath.db lives in
-- `jpi_programs` (13,578 rows, mirrored via migration 032).
--
-- Most likely root cause: an earlier migrate.py invocation against
-- autonomath.db (before the entrypoint.sh self-heal loop existed) ran
-- _ensure_base_schema(), which executes src/jpintel_mcp/db/schema.sql
-- and creates `programs` + `api_keys` unconditionally with
-- CREATE TABLE IF NOT EXISTS. The CLAUDE.md gotcha section explicitly
-- warns against this pattern. The empty `programs` lingered for
-- months until schema_guard caught it.
--
-- Fix: drop the empty programs + programs_fts tables on autonomath.db.
-- We DO NOT touch jpi_programs (the correct mirror), and we DO NOT
-- touch api_keys on autonomath.db (which is pre-existing cross-pollution
-- but actively used by legacy code paths reading auth from a single
-- connection — see schema_guard.py AM_FORBIDDEN comment).
--
-- Idempotency: DROP TABLE IF EXISTS is a no-op on second pass.
--
-- Operator note: if a future regression repopulates `programs` on
-- autonomath.db, this migration's IF EXISTS guard would silently drop
-- the data on the next boot. Defense:
--   * schema_guard.py blocks startup if `programs` is present, so the
--     regression would be caught before any traffic hits the rebuilt
--     table.
--   * The `jpi_programs` mirror (target on autonomath.db) is the only
--     legitimate source of program data; any write to autonomath.db's
--     `programs` is a definitional bug.

DROP TABLE IF EXISTS programs;
DROP TABLE IF EXISTS programs_fts;
DROP TABLE IF EXISTS programs_fts_data;
DROP TABLE IF EXISTS programs_fts_idx;
DROP TABLE IF EXISTS programs_fts_content;
DROP TABLE IF EXISTS programs_fts_docsize;
DROP TABLE IF EXISTS programs_fts_config;

-- Bookkeeping recorded by entrypoint.sh §4 / scripts/migrate.py.
