-- migration 074: programs.merged_from column for noise-duplicate consolidation
--
-- target_db: jpintel.db
--
-- Background:
--   Wave 17 data freshness audit detected 1,245 name-collision groups in
--   `programs` (excluded=0), of which 568 groups (575 extra rows) are
--   "noise" duplicates: same primary_name + same prefecture + same
--   source_url. The remaining ~542 groups are legitimate per-prefecture
--   variants (e.g. 47 県別 entries of 環境保全型農業直接支払交付金) and
--   ~193 are ambiguous (same name+pref, different URL — manual review
--   queue lives at data/duplicate_review_queue.jsonl).
--
--   Noise duplicates are merged via the dedup script (scripts/dedup_programs_wave17.py):
--     * Keep 1 row per (primary_name, prefecture, source_url) cluster — pick
--       highest tier (S>A>B>C>X), tie-break by latest source_fetched_at,
--       then lexicographically smallest unified_id.
--     * Drop the rest by setting excluded=1 + exclusion_reason='duplicate_merged'.
--     * Record provenance on the kept row's `merged_from` column as a JSON
--       array of the absorbed unified_ids.
--
-- Coordination:
--   The exclusion_reason value 'duplicate_merged' is shared with Wave 18
--   (tier_x quarantine agent) — keep the literal string consistent.
--
-- Idempotency:
--   ALTER TABLE … ADD COLUMN is wrapped in a defensive check at the
--   dedup-script layer (the migration runner itself does not support
--   conditional column-add, so re-running this raw SQL on a DB that
--   already has the column will fail; the dedup script handles that
--   by inspecting PRAGMA table_info first).
--
-- DOWN (commented — keep merge history; SQLite ALTER TABLE … DROP COLUMN
-- exists but loses the JSON provenance forever):
--   -- ALTER TABLE programs DROP COLUMN merged_from;

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN merged_from TEXT;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
