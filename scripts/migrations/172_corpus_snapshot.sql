-- target_db: autonomath
-- migration 172_corpus_snapshot
--
-- Schema-only receiver for public-corpus snapshot manifests produced by
-- offline collection and precompute jobs.
--
-- Why this exists:
--   Evidence packets and deep artifacts need a durable "data as of" ledger
--   so an answer can be regenerated or audited against the same corpus
--   boundary. This table records snapshot identity, table-level counts,
--   corpus checksums, source freshness, license posture, and known gaps.
--
--   No customer-specific paid output is stored here. This is public corpus
--   foundation metadata for autonomath.db.
--
-- Schema notes:
--   * JSON arrays/objects are stored as TEXT so the migration remains a
--     pure SQLite schema layer. Offline builders own JSON serialization.
--   * corpus_snapshot_id is an opaque stable id. Existing response code may
--     still derive transient ids until a writer starts populating this table.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `172_corpus_snapshot_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS corpus_snapshot (
    corpus_snapshot_id        TEXT PRIMARY KEY,
    db_name                   TEXT NOT NULL DEFAULT 'autonomath'
                              CHECK (db_name IN ('autonomath')),
    snapshot_kind             TEXT NOT NULL CHECK (snapshot_kind IN (
                                  'daily','manual','source_ingest',
                                  'precompute','backfill','test','other'
                              )),
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

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_db_kind_created
    ON corpus_snapshot(db_name, snapshot_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_content_hash
    ON corpus_snapshot(content_hash)
    WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_corpus_snapshot_corpus_checksum
    ON corpus_snapshot(corpus_checksum)
    WHERE corpus_checksum IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
