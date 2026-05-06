-- target_db: jpintel
-- migration wave24_108_programs_source_verified_at
--   (MASTER_PLAN_v1 章 3 §D3 — source_fetched_at sentinel 排除 / 真の median freshness)
--
-- Why this exists:
--   `source_fetched_at` is currently a uniform sentinel across rows that
--   were bulk-rewritten at ingest time (see CLAUDE.md "Common gotchas":
--   render it as "出典取得", never as "最終更新"). The Evidence Layer
--   pitch + median-freshness KPI both demand a column whose semantics are
--   "we re-checked the live URL at this timestamp", distinct from the
--   ingest-side `source_fetched_at`.
--
--   This migration adds three columns + two indexes that let
--   `scripts/refresh_sources.py` (D3 改修) record the verify event without
--   ever overwriting the canonical `source_fetched_at`:
--
--     source_verified_at TEXT
--       ISO-8601 UTC timestamp of the most recent successful HEAD/GET +
--       SHA256 hash compare. NULL until a verify pass touches the row.
--       Distinct from `source_fetched_at` (ingest-side). Distinct from
--       `source_url_last_checked` (mig 118, semantic status only).
--
--     source_content_hash_at_verify TEXT
--       SHA256 of the response body at last verify. Used by the next
--       verify pass to short-circuit "content unchanged → skip enrichment
--       cron" and by `/v1/programs/*` callers to detect content drift
--       between two reads of the same `source_url`.
--
--     source_verify_method TEXT
--       'HEAD'  → status code probe only (4xx/5xx skip)
--       'GET'   → full body fetch + SHA256 compare (default for diff path)
--       'cached'→ HEAD said 304 / If-None-Match short-circuit
--       'skip'  → robots disallow / quarantine / ratelimit budget exhausted
--
--   Two indexes:
--
--     idx_programs_source_verified_at — partial index on the timestamp
--       column ordered DESC. Powers the median-freshness KPI query
--       (SELECT julianday('now')-julianday(source_verified_at) ...).
--       Partial WHERE source_verified_at IS NOT NULL keeps the index
--       small while the back-fill is still in progress.
--
--     idx_programs_verify_freshness — composite (tier, source_verified_at)
--       with WHERE tier IN ('S','A'). Hot-path index for the public
--       freshness endpoint that filters S/A only and orders by oldest
--       verify timestamp first (most-stale first).
--
-- Idempotency:
--   `ALTER TABLE ADD COLUMN` is not natively IF NOT EXISTS in SQLite;
--   `scripts/migrate.py` swallows OperationalError "duplicate column
--   name" the same way migrations 049 / 101 / 118 / 119 / wave24_105
--   do. CREATE INDEX IF NOT EXISTS is already idempotent. Safe to apply
--   on every Fly boot.
--
-- DOWN:
--   See companion `wave24_108_programs_source_verified_at_rollback.sql`.
--   Columns are additive; default behaviour is "verify column missing →
--   refresh_sources.py degrades to legacy fetched_at-only path".

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN source_verified_at TEXT;
ALTER TABLE programs ADD COLUMN source_content_hash_at_verify TEXT;
ALTER TABLE programs ADD COLUMN source_verify_method TEXT;

CREATE INDEX IF NOT EXISTS idx_programs_source_verified_at
    ON programs(source_verified_at DESC)
    WHERE source_verified_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_programs_verify_freshness
    ON programs(tier, source_verified_at)
    WHERE tier IN ('S', 'A');

-- Bookkeeping recorded by scripts/migrate.py via schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
