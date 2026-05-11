-- target_db: autonomath
-- rollback: 235_am_portfolio_optimize

BEGIN;

DROP INDEX IF EXISTS idx_am_portfolio_optimize_refreshed;
DROP INDEX IF EXISTS idx_am_portfolio_optimize_program;
DROP INDEX IF EXISTS idx_am_portfolio_optimize_score;
DROP INDEX IF EXISTS idx_am_portfolio_optimize_refresh_log_started;
DROP TABLE IF EXISTS am_portfolio_optimize;
DROP TABLE IF EXISTS am_portfolio_optimize_refresh_log;

COMMIT;
