-- target_db: autonomath
-- ROLLBACK companion for wave24_131_am_houjin_360_snapshot.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_ah360s_month_risk;
DROP INDEX IF EXISTS idx_ah360s_houjin_month;
DROP TABLE IF EXISTS am_houjin_360_snapshot;
PRAGMA foreign_keys = ON;
