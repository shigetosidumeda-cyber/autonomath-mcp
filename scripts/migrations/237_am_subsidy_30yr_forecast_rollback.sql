-- target_db: autonomath
-- rollback: 237_am_subsidy_30yr_forecast

BEGIN;

DROP INDEX IF EXISTS idx_am_subsidy_30yr_forecast_refreshed;
DROP INDEX IF EXISTS idx_am_subsidy_30yr_forecast_year;
DROP INDEX IF EXISTS idx_am_subsidy_30yr_forecast_program;
DROP INDEX IF EXISTS idx_am_subsidy_30yr_forecast_refresh_log_started;
DROP TABLE IF EXISTS am_subsidy_30yr_forecast;
DROP TABLE IF EXISTS am_subsidy_30yr_forecast_refresh_log;

COMMIT;
