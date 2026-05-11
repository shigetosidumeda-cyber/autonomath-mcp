-- target_db: autonomath
-- migration 203_source_document_v2 (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.
--
-- SQLite < 3.35 cannot DROP COLUMN; the rollback drops the new indexes
-- only. The v2 columns remain in place; they are nullable and default-zero
-- so they do not block any pre-v2 reader.

DROP INDEX IF EXISTS idx_source_document_kind;
DROP INDEX IF EXISTS idx_source_document_aggregator;
DROP INDEX IF EXISTS idx_source_document_primary;
DROP INDEX IF EXISTS idx_source_document_redistribution;
DROP INDEX IF EXISTS idx_source_document_license_class;
DROP INDEX IF EXISTS idx_source_document_bridge;
