-- target_db: autonomath
-- migration 197_public_funding_ledger (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_public_funding_ledger_source;
DROP INDEX IF EXISTS idx_public_funding_ledger_bridge;
DROP INDEX IF EXISTS idx_public_funding_ledger_authority;
DROP INDEX IF EXISTS idx_public_funding_ledger_kind_year;
DROP INDEX IF EXISTS idx_public_funding_ledger_procurement;
DROP INDEX IF EXISTS idx_public_funding_ledger_program;
DROP INDEX IF EXISTS idx_public_funding_ledger_houjin;
DROP TABLE IF EXISTS public_funding_ledger;
