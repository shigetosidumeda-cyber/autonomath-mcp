-- target_db: autonomath
-- migration 174_source_document
--
-- Schema-only receiver for fetched public source documents. A source document
-- is the observed HTML/PDF/API/CSV/XLSX/etc. unit behind citations and
-- extracted facts, not merely a URL string.
--
-- Why this exists:
--   Evidence packets need source_url, fetched time, verification time,
--   content hash, license, robots/TOS posture, and known gaps to travel
--   together. This ledger also lets URL liveness drift without losing the
--   retrieval-time proof linked through artifact_id.
--
--   No customer-private material is stored here.
--
-- Schema notes:
--   * JSON arrays/objects are stored as TEXT.
--   * artifact_id and corpus_snapshot_id are soft references to keep this
--     foundation layer independently idempotent.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `174_source_document_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_document (
    source_document_id       TEXT PRIMARY KEY,
    source_url               TEXT NOT NULL,
    canonical_url            TEXT,
    domain                   TEXT,
    title                    TEXT,
    publisher                TEXT,
    publisher_entity_id      TEXT,
    document_kind            TEXT NOT NULL DEFAULT 'unknown' CHECK (document_kind IN (
                                 'html','pdf','text','csv','tsv','json','jsonl',
                                 'xlsx','docx','api','rss','unknown','other'
                             )),
    license                  TEXT,
    content_hash             TEXT,
    bytes                    INTEGER CHECK (bytes IS NULL OR bytes >= 0),
    fetched_at               TEXT,
    last_verified_at         TEXT,
    http_status              INTEGER CHECK (
                                 http_status IS NULL OR
                                 (http_status >= 100 AND http_status <= 599)
                             ),
    artifact_id              TEXT,
    corpus_snapshot_id       TEXT,
    robots_status            TEXT NOT NULL DEFAULT 'unknown' CHECK (robots_status IN (
                                 'unknown','not_checked','allowed','disallowed',
                                 'conditional','error'
                             )),
    tos_note                 TEXT,
    known_gaps_json          TEXT NOT NULL DEFAULT '[]',
    metadata_json            TEXT NOT NULL DEFAULT '{}',
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_source_document_url
    ON source_document(source_url);

CREATE INDEX IF NOT EXISTS idx_source_document_canonical
    ON source_document(canonical_url)
    WHERE canonical_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_domain_kind
    ON source_document(domain, document_kind);

CREATE INDEX IF NOT EXISTS idx_source_document_publisher
    ON source_document(publisher)
    WHERE publisher IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_hash
    ON source_document(content_hash)
    WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_artifact
    ON source_document(artifact_id)
    WHERE artifact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_snapshot
    ON source_document(corpus_snapshot_id)
    WHERE corpus_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_document_freshness
    ON source_document(last_verified_at DESC, fetched_at DESC);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
