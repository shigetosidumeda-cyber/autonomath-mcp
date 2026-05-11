-- target_db: autonomath
-- rollback: 238_am_alliance_opportunity

BEGIN;

DROP INDEX IF EXISTS idx_am_alliance_opportunity_refreshed;
DROP INDEX IF EXISTS idx_am_alliance_opportunity_partner;
DROP INDEX IF EXISTS idx_am_alliance_opportunity_score;
DROP INDEX IF EXISTS idx_am_alliance_opportunity_refresh_log_started;
DROP TABLE IF EXISTS am_alliance_opportunity;
DROP TABLE IF EXISTS am_alliance_opportunity_refresh_log;

COMMIT;
