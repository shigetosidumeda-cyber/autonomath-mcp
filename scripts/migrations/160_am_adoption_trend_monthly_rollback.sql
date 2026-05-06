-- target_db: autonomath
-- ROLLBACK companion for 160_am_adoption_trend_monthly.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS ix_adoption_trend_flag;
DROP INDEX IF EXISTS ix_adoption_trend_ym;
DROP INDEX IF EXISTS ix_adoption_trend_jsic;
DROP TABLE IF EXISTS am_adoption_trend_monthly;
PRAGMA foreign_keys = ON;
