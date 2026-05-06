-- target_db: autonomath
-- DOWN for migration 156_am_funding_stack_empirical.
--
-- entrypoint.sh §4 EXCLUDES *_rollback.sql by name match,
-- so this file is only invoked manually by the operator.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_funding_stack_conflict;
DROP INDEX IF EXISTS ix_funding_stack_count;
DROP TABLE IF EXISTS am_funding_stack_empirical;
