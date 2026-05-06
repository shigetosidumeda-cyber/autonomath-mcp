-- target_db: jpintel
-- migration 151_programs_cross_source_verified
--
-- Why this exists (Wave 24+ moat-signal hardening, 2026-05-05):
--   The phantom-moat audit (CLAUDE.md "Honest counts") concluded that
--   the only durable signal we own is *cross-source agreement*: two or
--   more independent first-party hosts pointing at the same `programs`
--   row is a verifiable, replayable claim. A single `source_url` is not.
--
--   Migration 118 introduced `source_url_status` (is the link live?).
--   Migration 124 added `src_attribution` (per-fact source rollup).
--   Migration 126 captured per-citation verification.
--   This migration adds the **program-level** cross-source rollup so
--   surface tools can filter / boost / disclose without re-deriving the
--   join on every request.
--
-- Schema additions:
--   programs.cross_source_verified TEXT DEFAULT '[]'
--     JSON array of confirming source-kind tokens. Tokens are stable
--     hostname-derived buckets (e.g. 'egov', 'pref_lg_jp', 'nta',
--     'maff', 'meti', 'mhlw', 'jfc', 'jgrants', 'moj') so downstream
--     code can `LIKE '%"nta"%'` without parsing host strings.
--   programs.verification_count INTEGER DEFAULT 0
--     Count of *distinct* source-kind tokens in `cross_source_verified`.
--     Hot-path filter / sort key for moat-signal surfaces.
--   ix_programs_verification_count
--     Index for ORDER BY verification_count DESC and threshold filters.
--
-- Populator:
--   `scripts/etl/populate_cross_source_verification.py` (NON-LLM) walks
--   programs.source_url + entity_id_map -> am_entity_source -> am_source
--   to collect every distinct host-derived token per program. Re-running
--   is idempotent (UPDATE overwrites both columns from a freshly-derived
--   set).
--
-- Idempotency:
--   `ALTER TABLE ADD COLUMN` is not natively IF NOT EXISTS in SQLite;
--   migrate.py's tolerant ADD COLUMN handler catches "duplicate column
--   name" errors. CREATE INDEX uses IF NOT EXISTS.
--
-- DOWN:
--   No down — the columns are additive and ignored by every existing
--   read path. To remove, drop the index then rebuild the table without
--   the columns (SQLite has no DROP COLUMN before 3.35; production
--   ships 3.46+, but no downgrade is planned).

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN cross_source_verified TEXT DEFAULT '[]';
ALTER TABLE programs ADD COLUMN verification_count INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_programs_verification_count
    ON programs(verification_count);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
