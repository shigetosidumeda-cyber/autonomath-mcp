-- target_db: autonomath
-- migration 078_amount_condition_quarantine
--
-- Why this exists:
--   Phantom-moat audit (2026-04-29) confirmed that 76% of am_amount_condition
--   rows (27,233 / 35,713) were promoted from a single broken ETL pass that
--   filled `fixed_yen` with the program-ceiling template default
--   (¥500,000 for jizokuka_ippan; ¥2,000,000 for jizokuka_souzou) instead
--   of the per-record granted amount. The source records do not actually
--   carry per-grantee amounts; the original PDF tables only listed the
--   program ceiling. The promoter incorrectly treated the ceiling as
--   "amount granted".
--
--   Pre-flight measurement on autonomath.db (2026-04-29):
--     SELECT condition_label='granted' AND fixed_yen IN (500000, 2000000) :
--       27,233 rows / 35,713 total = 76.3%
--     fixed_yen=500000  -> 26,008 rows
--     fixed_yen=2000000 ->  1,225 rows
--     ALL granted rows fall in those two buckets (0 NULL, 0 other values).
--
--   This migration introduces a `template_default` flag on am_amount_condition
--   so the affected rows are quarantined (preserved for audit trail)
--   instead of deleted. Downstream tools must filter
--   `template_default = 0` to surface only honest values. The companion
--   re-promotion script (`scripts/etl/repromote_amount_conditions.py`)
--   reads from am_entity_facts and inserts genuine rows with
--   template_default = 0.
--
-- Quarantine, don't delete:
--   The bad rows stay on disk so an auditor can still see the bookkeeping
--   trail (`evidence_fact_id`, `promoted_at`). New / corrected rows live
--   alongside, distinguishable by the flag.
--
-- Idempotency:
--   * `ALTER TABLE ... ADD COLUMN` is not natively idempotent in SQLite.
--     The entrypoint.sh §4 boot loop runs each migration via
--     `sqlite3 "$DB_PATH" < "$am_mig" 2>&1 | grep -v "^$" | head -3 || true`,
--     which continues past the per-statement "duplicate column name"
--     error and still executes the subsequent UPDATE / CREATE INDEX
--     statements. Verified pattern matches migrations 049, 061.
--   * The UPDATE is guarded by `template_default = 0` to keep re-runs O(0)
--     after the first apply.
--   * `CREATE INDEX IF NOT EXISTS` is natively idempotent.
--
-- DOWN:
--   No DOWN migration provided. The flag is purely additive metadata; the
--   only revert path that makes data sense is to re-run the broken
--   promoter, which would re-create the same pollution. Use the
--   re-promotion script's idempotent INSERT to add corrected rows
--   instead.

PRAGMA foreign_keys = ON;

-- Add the quarantine flag. On re-runs the duplicate-column error is
-- non-fatal (entrypoint.sh logs and continues; subsequent statements
-- still run). NOT NULL DEFAULT 0 lets existing rows back-fill cleanly
-- because SQLite supports DEFAULT-backed NOT NULL on ADD COLUMN.
ALTER TABLE am_amount_condition ADD COLUMN template_default INTEGER NOT NULL DEFAULT 0;

-- Flag the polluted rows. Guard on `template_default = 0` so re-runs
-- skip already-flagged rows (keeps the migration idempotent + cheap).
UPDATE am_amount_condition
   SET template_default = 1
 WHERE condition_label = 'granted'
   AND fixed_yen IN (500000, 2000000)
   AND template_default = 0;

-- Make the `WHERE template_default = 0` filter cheap.
-- Combined with condition_label so downstream filters
-- `template_default = 0 AND condition_label = 'granted'` are covered.
CREATE INDEX IF NOT EXISTS ix_am_amount_condition_template_default
    ON am_amount_condition(template_default, condition_label);

-- Bookkeeping recorded by entrypoint.sh §4 / scripts/migrate.py.
