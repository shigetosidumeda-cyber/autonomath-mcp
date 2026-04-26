-- 001_lineage.sql
-- Adds per-record data lineage columns to programs so we can answer
-- "which URL, fetched when, and has it changed?" per program.
-- Idempotent when applied via scripts/migrate.py (tracked in schema_migrations).

ALTER TABLE programs ADD COLUMN source_url TEXT;
ALTER TABLE programs ADD COLUMN source_fetched_at TEXT;
ALTER TABLE programs ADD COLUMN source_checksum TEXT;

CREATE INDEX IF NOT EXISTS idx_programs_source_fetched ON programs(source_fetched_at);
