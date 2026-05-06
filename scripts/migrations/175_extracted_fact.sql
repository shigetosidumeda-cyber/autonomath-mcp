-- target_db: autonomath
-- migration 175_extracted_fact
--
-- Schema-only receiver for citation-positioned extracted facts. This is the
-- v2 fact ledger that keeps a claim's subject, source document, field,
-- value, quote, page/span/selector, extractor provenance, confidence, and
-- known gaps in one row.
--
-- Why this exists:
--   Existing am_entity_facts is useful for EAV facts, but deep artifacts need
--   quote/page/span and extraction metadata so citations can be verified,
--   repaired, and reviewed by a human without re-reading the entire source.
--
--   Customer-specific private facts are out of scope for this public-corpus
--   foundation migration.
--
-- Schema notes:
--   * value_json / selector_json / known_gaps_json are serialized JSON TEXT.
--   * source_document_id and corpus_snapshot_id are soft references.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `175_extracted_fact_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS extracted_fact (
    fact_id                  TEXT PRIMARY KEY,
    subject_kind             TEXT NOT NULL CHECK (subject_kind IN (
                                 'program','houjin','law','tax_measure',
                                 'loan','source_document','procurement',
                                 'enforcement_event','court_case',
                                 'stat_series','entity','query','other'
                             )),
    subject_id               TEXT NOT NULL,
    entity_id                TEXT,
    source_document_id       TEXT,
    field_name               TEXT NOT NULL,
    field_kind               TEXT NOT NULL DEFAULT 'text' CHECK (field_kind IN (
                                 'text','number','date','datetime','amount',
                                 'boolean','url','json','other'
                             )),
    value_text               TEXT,
    value_number             REAL,
    value_date               TEXT,
    value_json               TEXT,
    unit                     TEXT,
    quote                    TEXT,
    page_number              INTEGER CHECK (page_number IS NULL OR page_number > 0),
    span_start               INTEGER CHECK (span_start IS NULL OR span_start >= 0),
    span_end                 INTEGER CHECK (
                                 span_end IS NULL OR
                                 (span_end >= 0 AND
                                  (span_start IS NULL OR span_end >= span_start))
                             ),
    selector_json            TEXT NOT NULL DEFAULT '{}',
    extraction_method        TEXT NOT NULL DEFAULT 'unknown' CHECK (extraction_method IN (
                                 'manual','parser','rule','llm','ocr',
                                 'backfill','unknown','other'
                             )),
    extractor_version        TEXT,
    confidence_score         REAL CHECK (
                                 confidence_score IS NULL OR
                                 (confidence_score >= 0.0 AND confidence_score <= 1.0)
                             ),
    confirming_source_count  INTEGER NOT NULL DEFAULT 0
                             CHECK (confirming_source_count >= 0),
    valid_from               TEXT,
    valid_until              TEXT,
    observed_at              TEXT,
    corpus_snapshot_id       TEXT,
    known_gaps_json          TEXT NOT NULL DEFAULT '[]',
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        value_text IS NOT NULL OR
        value_number IS NOT NULL OR
        value_date IS NOT NULL OR
        value_json IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_extracted_fact_subject_field
    ON extracted_fact(subject_kind, subject_id, field_name);

CREATE INDEX IF NOT EXISTS idx_extracted_fact_entity
    ON extracted_fact(entity_id)
    WHERE entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_source_document
    ON extracted_fact(source_document_id)
    WHERE source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_snapshot
    ON extracted_fact(corpus_snapshot_id)
    WHERE corpus_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_field_kind
    ON extracted_fact(field_name, field_kind);

CREATE INDEX IF NOT EXISTS idx_extracted_fact_observed
    ON extracted_fact(observed_at DESC)
    WHERE observed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_confidence
    ON extracted_fact(confidence_score DESC)
    WHERE confidence_score IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
