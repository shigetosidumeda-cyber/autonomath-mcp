-- target_db: autonomath
-- migration 150_am_amount_condition_quality_tier
--
-- Why this exists (Wave 20 amount_condition re-validation, 2026-05-05):
--   `am_amount_condition` holds 250,946 rows. Pre-flight measurement (2026-05-05):
--     SELECT fixed_yen, COUNT(*) FROM am_amount_condition
--      WHERE fixed_yen IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
--       3500000 -> 72,918    500000 -> 61,363
--      12500000 -> 49,210   4500000 -> 32,392
--      70000000 -> 16,379  15000000 ->  5,077
--       2000000 ->  2,606  90000000 ->  1,887   ← 8 ceiling buckets = 241,832 rows (96.4%)
--   Of 250,269 rows with fixed_yen, only 515 carry a non-empty
--   `extracted_text` (a verbatim string from the source PDF/HTML).
--   The remaining ~99.8% are template-defaults injected by an old ETL
--   pass that copied the program ceiling into every per-record row.
--
--   Migration 078 already added a binary `template_default` flag and
--   migration 109 added `is_authoritative` (3-condition AND). This
--   migration introduces a **3-tier explicit `quality_tier`** so the
--   surface side can filter `quality_tier='verified'` without having to
--   replicate the rule logic in every tool. The tier is computed from
--   existing columns — NO new ingest, NO LLM call.
--
--     'verified'         — extracted_text is non-empty (the value can
--                          be re-checked against the source PDF/HTML
--                          literal at audit time).
--     'template_default' — fixed_yen sits in one of the 8 ceiling
--                          buckets above AND extracted_text is empty.
--     'unknown'          — everything else (fixed_yen NULL, or a value
--                          we cannot prove is template-default OR
--                          verified given current evidence). Conservative
--                          default; downstream filter must NOT surface
--                          'unknown' to customers without a manual
--                          review pass.
--
--   The bucket list is held inline in this migration (NOT a CONFIG
--   table) so the audit trail is grep-able from one file. If a new
--   ceiling bucket emerges, add it both here AND in
--   `scripts/etl/revalidate_amount_conditions.py`.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN raises duplicate-column on second apply;
--   `entrypoint.sh` §4 swallows that and continues the file. The
--   UPDATE statements are guarded so re-runs are O(rows-changed).
--   CREATE INDEX uses IF NOT EXISTS.
--
-- DOWN:
--   companion `150_am_amount_condition_quality_tier_rollback.sql`
--   drops the column + index. Note SQLite < 3.35 cannot DROP COLUMN;
--   prod runtime is 3.43+ (verified in Dockerfile base image).

PRAGMA foreign_keys = ON;

-- 1. Add the explicit 3-tier column. Default 'unknown' so existing rows
--    are conservative until the validation script reclassifies them.
ALTER TABLE am_amount_condition ADD COLUMN quality_tier TEXT NOT NULL DEFAULT 'unknown';

-- 2. Hot-path index. Surface filters use `quality_tier='verified'`
--    overwhelmingly, so a partial index keeps the index tiny while
--    still covering full-bucket scans for audit/admin paths.
CREATE INDEX IF NOT EXISTS ix_amount_condition_tier
    ON am_amount_condition(quality_tier);

CREATE INDEX IF NOT EXISTS ix_amount_condition_tier_verified
    ON am_amount_condition(quality_tier, condition_label)
 WHERE quality_tier = 'verified';

-- 3. Initial bulk classification (idempotent — guarded on tier='unknown'
--    so re-runs after the validation script bumps a tier do NOT revert).
--
--    Rule order matters: 'verified' wins over 'template_default' even
--    if the value happens to land in a ceiling bucket, because an
--    extracted_text presence means we have literal source evidence.
UPDATE am_amount_condition
   SET quality_tier = 'verified'
 WHERE quality_tier = 'unknown'
   AND extracted_text IS NOT NULL
   AND TRIM(extracted_text) != '';

UPDATE am_amount_condition
   SET quality_tier = 'template_default'
 WHERE quality_tier = 'unknown'
   AND fixed_yen IN (
        500000, 2000000, 3500000, 4500000,
       12500000, 15000000, 70000000, 90000000
   );

-- Rows left at 'unknown' = fixed_yen NULL OR a non-bucket value with
-- no extracted_text. The Python validation script
-- `scripts/etl/revalidate_amount_conditions.py` may reclassify some
-- of these later (e.g. round-number outliers detected dynamically).

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
