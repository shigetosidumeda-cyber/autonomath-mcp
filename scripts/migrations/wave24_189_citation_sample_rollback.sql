-- target_db: autonomath
-- rollback: wave24_189_citation_sample
-- WARNING: drops citation_sample manual sample history (DEEP-43).
-- Only run after exporting CSV snapshots — tipping panel feed will lose
-- 12-month trend baseline if dropped without backup.

DROP VIEW IF EXISTS v_citation_q_monthly;
DROP VIEW IF EXISTS v_citation_rate_monthly;

DROP INDEX IF EXISTS idx_citation_sample_month_provider;
DROP INDEX IF EXISTS idx_citation_sample_provider;
DROP INDEX IF EXISTS idx_citation_sample_month;

DROP TABLE IF EXISTS citation_sample;
