-- target_db: autonomath
-- rollback: wave24_186_industry_journal_mention
-- WARNING: drops industry_journal_mention rows (DEEP-40 organic 自走 KPI history).
-- Only run after exporting to R2 backup (operator-only path).

DROP INDEX IF EXISTS ix_ijm_journal;
DROP INDEX IF EXISTS ix_ijm_keyword;
DROP INDEX IF EXISTS ix_ijm_self_authored;
DROP INDEX IF EXISTS ix_ijm_issue_cohort;
DROP TABLE IF EXISTS industry_journal_mention;
