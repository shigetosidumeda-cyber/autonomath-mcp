-- target_db: jpintel
-- ROLLBACK companion for wave24_143_customer_webhooks_test_hits.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.
--
-- Manual review required. With the SQLite-persisted hits table
-- removed, the read path in `customer_webhooks.py` falls back to
-- the legacy in-process dict — under N>1 worker deployments this
-- bypasses the 5/min/webhook test-delivery cap, so confirm with
-- the operator that worker count is 1 before rolling back.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_customer_webhooks_test_hits_lookup;
DROP TABLE IF EXISTS customer_webhooks_test_hits;

PRAGMA foreign_keys = ON;
