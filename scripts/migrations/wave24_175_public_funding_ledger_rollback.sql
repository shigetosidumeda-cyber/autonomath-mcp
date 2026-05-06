-- target_db: autonomath
-- rollback for wave24_175_public_funding_ledger
--
-- Drops the public view, all 6 indexes, and the table in dependency
-- order. Re-running is safe (DROP IF EXISTS).
--
-- WARNING: destructive. Take a backup of $AUTONOMATH_DB_PATH first:
--   sqlite3 autonomath.db ".backup autonomath.db.bak-pre-rollback-175"
-- Backfill ETL (scripts/etl/backfill_public_funding_ledger.py) can
-- re-derive rows from gbizinfo_subsidy_v2 + jgrants + jpi_adoption_records
-- + jfc_* mirror tables, but candidate_program rows (eligibility hits)
-- are recomputed and may differ from the prior population.

DROP VIEW IF EXISTS v_public_funding_ledger_public;
DROP INDEX IF EXISTS idx_public_funding_program;
DROP INDEX IF EXISTS idx_public_funding_receipt;
DROP INDEX IF EXISTS idx_public_funding_pref_industry;
DROP INDEX IF EXISTS idx_public_funding_agency;
DROP INDEX IF EXISTS idx_public_funding_kind_year;
DROP INDEX IF EXISTS idx_public_funding_recipient_year;
DROP TABLE IF EXISTS public_funding_ledger;
