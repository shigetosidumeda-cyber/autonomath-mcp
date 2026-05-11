-- target_db: autonomath
-- migration 198_permit_registry (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS ux_permit_registry_natural_key;
DROP INDEX IF EXISTS idx_permit_registry_bridge;
DROP INDEX IF EXISTS idx_permit_registry_status_expires;
DROP INDEX IF EXISTS idx_permit_registry_prefecture;
DROP INDEX IF EXISTS idx_permit_registry_holder_houjin;
DROP INDEX IF EXISTS idx_permit_registry_authority_type;
DROP INDEX IF EXISTS idx_permit_registry_no;
DROP TABLE IF EXISTS permit_registry;
