-- target_db: jpintel
-- migration 118_programs_source_url_status (S/A tier broken-URL accountability)
--
-- Why this exists:
--   The LLM-resilient business plan (docs/_internal/llm_resilient_business_plan_2026-04-30.md
--   §17 step 3 + §18 row "citation") demands two invariants for the
--   Evidence Layer pitch:
--     1. Zero high-stakes responses without a `source_url`.
--     2. No broken links inside S/A tier programs.
--
--   `scripts/refresh_sources.py` already populates two columns:
--     - source_last_check_status (HTTP status of last HEAD/GET probe)
--     - source_fail_count        (streak counter, quarantine at 3)
--   That is enough for the script's own quarantine logic, but it is too
--   low-level for the public freshness surface to consume directly:
--   `200 / 301 / 404` integers cannot be filtered by a meta endpoint
--   without baking the HTTP semantic into every caller.
--
--   This migration adds a coarser, semantic status column that mirrors
--   `am_source.canonical_status` (live / stale / broken / promoted) so
--   the public `/v1/meta/freshness` endpoint can surface a single
--   `source_url_broken_count` number without reverse-engineering HTTP
--   codes.
--
-- Schema additions:
--   programs.source_url_status TEXT DEFAULT 'unknown'
--     One of {'unknown', 'live', 'stale', 'broken', 'redirect'}.
--     Set by refresh_sources.py on each run; set manually by the broken-
--     URL audit script seeded alongside this migration.
--
--   programs.source_url_last_checked TEXT
--     ISO-8601 UTC timestamp of the last status set. Distinct from
--     `source_fetched_at` (which is the canonical ingest timestamp,
--     "出典取得" — see CLAUDE.md "Common gotchas") and from
--     `source_last_check_status` (which is the HTTP integer code).
--
--   idx_programs_source_status ON (source_url_status, tier)
--     Hot-path index for the freshness aggregate query that filters by
--     status='broken' AND tier IN ('S','A').
--
-- Idempotency:
--   `ALTER TABLE ADD COLUMN` is not natively IF NOT EXISTS in SQLite;
--   migrate.py's tolerant ADD COLUMN handler catches "duplicate column
--   name" errors. CREATE INDEX IF NOT EXISTS is already idempotent.
--
-- DOWN:
--   No down — the columns are additive and ignored by every existing
--   read path. To remove, drop the index then rebuild the table without
--   the columns (SQLite has no DROP COLUMN before 3.35; production
--   ships 3.46+, but no downgrade is planned).

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN source_url_status TEXT DEFAULT 'unknown';
ALTER TABLE programs ADD COLUMN source_url_last_checked TEXT;

CREATE INDEX IF NOT EXISTS idx_programs_source_status
    ON programs(source_url_status, tier);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
