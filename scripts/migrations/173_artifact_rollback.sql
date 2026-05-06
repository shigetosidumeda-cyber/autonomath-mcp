-- target_db: autonomath
-- migration 173_artifact (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_artifact_retention_expires;
DROP INDEX IF EXISTS idx_artifact_uri;
DROP INDEX IF EXISTS idx_artifact_sha256;
DROP INDEX IF EXISTS idx_artifact_snapshot;
DROP INDEX IF EXISTS idx_artifact_kind_created;
DROP TABLE IF EXISTS artifact;
