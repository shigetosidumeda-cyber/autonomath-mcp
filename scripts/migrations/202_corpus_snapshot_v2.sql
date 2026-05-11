-- target_db: autonomath
-- migration 202_corpus_snapshot_v2
--
-- Additive extension of corpus_snapshot (migration 172). Adds the columns
-- artifact / benchmark / freshness layers need to call out a snapshot's
-- artifact-section coverage, total source count, total fact count, freshness
-- floor, blocking known-gaps, and a "publishable" gate flag. Existing rows
-- are unaffected (every column is nullable or has a default).
--
-- Why this exists:
--   blueprint §3 Production gate + §6 benchmark runbook need to ask
--   "for this snapshot, how many artifact sections are populated end-to-end
--   and what is the latest stale source?" without re-scanning the corpus.
--   Materialising the summary onto corpus_snapshot keeps a one-row probe.
--
-- Schema notes:
--   * SQLite has no portable ADD COLUMN IF NOT EXISTS. The migration runner
--     (`scripts/migrate.py`) skips duplicate-column errors per statement, so
--     a partially-applied DB resumes through the rest of the ALTERs.
--   * Same per-statement skip lets entrypoint.sh §4 self-heal idempotently.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN with nullable / defaulted columns + duplicate-
--   column-skip behaviour at the runner layer. No data writes.
--
-- DOWN:
--   See companion `202_corpus_snapshot_v2_rollback.sql`.
--   (SQLite cannot DROP COLUMN < 3.35; rollback rebuilds the original.)

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS corpus_snapshot (
    corpus_snapshot_id        TEXT PRIMARY KEY,
    db_name                   TEXT NOT NULL DEFAULT 'autonomath',
    snapshot_kind             TEXT NOT NULL DEFAULT 'manual',
    created_at                TEXT NOT NULL DEFAULT (datetime('now')),
    table_counts_json         TEXT NOT NULL DEFAULT '{}',
    table_checksums_json      TEXT NOT NULL DEFAULT '{}',
    content_hash              TEXT,
    corpus_checksum           TEXT,
    source_freshness_json     TEXT NOT NULL DEFAULT '{}',
    license_breakdown_json    TEXT NOT NULL DEFAULT '{}',
    known_gaps_json           TEXT NOT NULL DEFAULT '[]',
    build_tool                TEXT,
    build_version             TEXT,
    metadata_json             TEXT NOT NULL DEFAULT '{}'
);

ALTER TABLE corpus_snapshot ADD COLUMN artifact_coverage_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE corpus_snapshot ADD COLUMN source_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE corpus_snapshot ADD COLUMN fact_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE corpus_snapshot ADD COLUMN freshness_floor TEXT;
ALTER TABLE corpus_snapshot ADD COLUMN blocking_known_gaps_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE corpus_snapshot ADD COLUMN publishable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE corpus_snapshot ADD COLUMN release_channel TEXT;
ALTER TABLE corpus_snapshot ADD COLUMN previous_snapshot_id TEXT;
ALTER TABLE corpus_snapshot ADD COLUMN diff_summary_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_publishable
    ON corpus_snapshot(publishable, created_at DESC)
    WHERE publishable = 1;

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_release_channel
    ON corpus_snapshot(release_channel, created_at DESC)
    WHERE release_channel IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_freshness_floor
    ON corpus_snapshot(freshness_floor)
    WHERE freshness_floor IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_previous
    ON corpus_snapshot(previous_snapshot_id)
    WHERE previous_snapshot_id IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
