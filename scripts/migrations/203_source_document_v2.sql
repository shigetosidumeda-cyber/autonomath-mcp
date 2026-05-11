-- target_db: autonomath
-- migration 203_source_document_v2
--
-- Additive extension of source_document (migration 174). Adds columns the
-- bridge / freshness / license-gate layers need on every source row:
-- bridge_id (when the source proves an entity_id_bridge tie), license_class
-- (redistribution_class enum for the license-gate), publisher_role, primary
-- vs aggregator flag, source_kind discriminator, and a freshness_window_days
-- hint so source_freshness_ledger can derive staleness without per-source
-- code paths.
--
-- Why this exists:
--   blueprint §4.2 + turn5 §4 want every source row to carry redistribution
--   posture + primary/aggregator discriminator + per-source freshness window
--   without forcing every caller to re-walk source_catalog. Materialising
--   them on source_document keeps the artifact `_evidence.sources[]` array
--   cheap.
--
-- Schema notes:
--   * SQLite no portable ADD COLUMN IF NOT EXISTS; runner duplicate-column
--     skip carries us through partial application.
--   * No CHECK constraints on the new enum columns (cannot add CHECK via
--     ALTER); enum validation is enforced at writer / validation_predicates.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN nullable / defaulted. No data writes.
--
-- DOWN:
--   See companion `203_source_document_v2_rollback.sql`.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS source_document (
    source_document_id       TEXT PRIMARY KEY,
    source_url               TEXT NOT NULL,
    canonical_url            TEXT,
    domain                   TEXT,
    title                    TEXT,
    publisher                TEXT,
    publisher_entity_id      TEXT,
    document_kind            TEXT NOT NULL DEFAULT 'unknown',
    license                  TEXT,
    content_hash             TEXT,
    bytes                    INTEGER,
    fetched_at               TEXT,
    last_verified_at         TEXT,
    http_status              INTEGER,
    artifact_id              TEXT,
    corpus_snapshot_id       TEXT,
    robots_status            TEXT NOT NULL DEFAULT 'unknown',
    tos_note                 TEXT,
    known_gaps_json          TEXT NOT NULL DEFAULT '[]',
    metadata_json            TEXT NOT NULL DEFAULT '{}',
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE source_document ADD COLUMN bridge_id TEXT;
ALTER TABLE source_document ADD COLUMN license_class TEXT;
ALTER TABLE source_document ADD COLUMN redistribution_class TEXT;
ALTER TABLE source_document ADD COLUMN publisher_role TEXT;
ALTER TABLE source_document ADD COLUMN is_primary_source INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN is_aggregator INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN source_kind TEXT;
ALTER TABLE source_document ADD COLUMN freshness_window_days INTEGER;
ALTER TABLE source_document ADD COLUMN attribution_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN attribution_text TEXT;

CREATE INDEX IF NOT EXISTS idx_source_document_bridge
    ON source_document(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_license_class
    ON source_document(license_class)
    WHERE license_class IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_redistribution
    ON source_document(redistribution_class)
    WHERE redistribution_class IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_primary
    ON source_document(is_primary_source, fetched_at DESC)
    WHERE is_primary_source = 1;

CREATE INDEX IF NOT EXISTS idx_source_document_aggregator
    ON source_document(is_aggregator)
    WHERE is_aggregator = 1;

CREATE INDEX IF NOT EXISTS idx_source_document_kind
    ON source_document(source_kind)
    WHERE source_kind IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
