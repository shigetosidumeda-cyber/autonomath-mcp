-- target_db: autonomath
-- migration 154_am_temporal_correlation_rollback (DOWN)
--
-- Drops the indexes then the mat view table. Safe — table is precomputed
-- and re-derivable from build_temporal_correlation.py at any time.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_atc_law_effective;
DROP INDEX IF EXISTS idx_atc_ratio;
DROP INDEX IF EXISTS idx_atc_effective;
DROP TABLE IF EXISTS am_temporal_correlation;
