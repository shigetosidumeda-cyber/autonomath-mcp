-- target_db: autonomath
-- migration 174_source_document (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_source_document_freshness;
DROP INDEX IF EXISTS idx_source_document_snapshot;
DROP INDEX IF EXISTS idx_source_document_artifact;
DROP INDEX IF EXISTS idx_source_document_hash;
DROP INDEX IF EXISTS idx_source_document_publisher;
DROP INDEX IF EXISTS idx_source_document_domain_kind;
DROP INDEX IF EXISTS idx_source_document_canonical;
DROP INDEX IF EXISTS idx_source_document_url;
DROP TABLE IF EXISTS source_document;
