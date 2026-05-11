-- target_db: autonomath
-- rollback: 236_am_houjin_risk_score

BEGIN;

DROP INDEX IF EXISTS idx_am_houjin_risk_score_refreshed;
DROP INDEX IF EXISTS idx_am_houjin_risk_score_bucket;
DROP INDEX IF EXISTS idx_am_houjin_risk_score_desc;
DROP INDEX IF EXISTS idx_am_houjin_risk_score_refresh_log_started;
DROP TABLE IF EXISTS am_houjin_risk_score;
DROP TABLE IF EXISTS am_houjin_risk_score_refresh_log;

COMMIT;
