-- target_db: autonomath
-- migration 199_permit_event (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_permit_event_source;
DROP INDEX IF EXISTS idx_permit_event_bridge;
DROP INDEX IF EXISTS idx_permit_event_holder;
DROP INDEX IF EXISTS idx_permit_event_authority_kind;
DROP INDEX IF EXISTS idx_permit_event_permit_no;
DROP INDEX IF EXISTS idx_permit_event_registry;
DROP TABLE IF EXISTS permit_event;
