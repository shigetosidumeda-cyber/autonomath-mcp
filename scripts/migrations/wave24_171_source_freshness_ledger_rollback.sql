-- target_db: autonomath
-- rollback for wave24_171_source_freshness_ledger
--
-- DROP VIEWS first, then the table. Indexes are dropped automatically with
-- the table.
--
-- WARNING: dropping this table erases the per-source health history. There is
-- no upstream reconstruction — last_failure_at / consecutive_failures only
-- exist here. After rollback + re-create, the next cron run rebuilds the
-- ledger from scratch (every source starts as health_status='unknown' until
-- the next refresh_source_freshness.py pass touches it).

DROP VIEW IF EXISTS v_source_freshness_public;
DROP VIEW IF EXISTS v_source_freshness_alerts;
DROP TABLE IF EXISTS source_freshness_ledger;
