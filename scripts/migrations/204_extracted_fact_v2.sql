-- target_db: autonomath
-- migration 204_extracted_fact_v2
--
-- Additive extension of extracted_fact (migration 175). Adds the columns
-- artifact + validation + bridge layers need at the fact level: bridge_id
-- (so identity-linked facts can be replayed through entity_id_bridge),
-- confirming_source_ids_json (multi-source corroboration trail), stale_at
-- (per-fact staleness deadline), human_review_required flag, fact_status
-- discriminator, and known-gap-code list.
--
-- Why this exists:
--   blueprint §4.3 known_gaps + §3 sensitive surface gating + turn5 §3
--   `evidence_event_logs` all read per-fact metadata that today is buried
--   in selector_json / metadata_json. Lifting them to first-class columns
--   lets risk_gate_findings + sensitive_surface_detected emit accurate
--   properties without re-parsing JSON.
--
-- Schema notes:
--   * SQLite no portable ADD COLUMN IF NOT EXISTS; runner duplicate-column
--     skip carries us through partial application.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN nullable / defaulted. No data writes.
--
-- DOWN:
--   See companion `204_extracted_fact_v2_rollback.sql`.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS extracted_fact (
    fact_id                  TEXT PRIMARY KEY,
    subject_kind             TEXT NOT NULL,
    subject_id               TEXT NOT NULL,
    entity_id                TEXT,
    source_document_id       TEXT,
    field_name               TEXT NOT NULL,
    field_kind               TEXT NOT NULL DEFAULT 'text',
    value_text               TEXT,
    value_number             REAL,
    value_date               TEXT,
    value_json               TEXT,
    unit                     TEXT,
    quote                    TEXT,
    page_number              INTEGER,
    span_start               INTEGER,
    span_end                 INTEGER,
    selector_json            TEXT NOT NULL DEFAULT '{}',
    extraction_method        TEXT NOT NULL DEFAULT 'unknown',
    extractor_version        TEXT,
    confidence_score         REAL,
    confirming_source_count  INTEGER NOT NULL DEFAULT 0,
    valid_from               TEXT,
    valid_until              TEXT,
    observed_at              TEXT,
    corpus_snapshot_id       TEXT,
    known_gaps_json          TEXT NOT NULL DEFAULT '[]',
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE extracted_fact ADD COLUMN bridge_id TEXT;
ALTER TABLE extracted_fact ADD COLUMN confirming_source_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE extracted_fact ADD COLUMN stale_at TEXT;
ALTER TABLE extracted_fact ADD COLUMN human_review_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE extracted_fact ADD COLUMN fact_status TEXT NOT NULL DEFAULT 'observed';
ALTER TABLE extracted_fact ADD COLUMN known_gap_codes_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE extracted_fact ADD COLUMN superseded_by TEXT;
ALTER TABLE extracted_fact ADD COLUMN review_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_bridge
    ON extracted_fact(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_stale_at
    ON extracted_fact(stale_at)
    WHERE stale_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_human_review
    ON extracted_fact(human_review_required, observed_at DESC)
    WHERE human_review_required = 1;

CREATE INDEX IF NOT EXISTS idx_extracted_fact_status
    ON extracted_fact(fact_status);

CREATE INDEX IF NOT EXISTS idx_extracted_fact_superseded
    ON extracted_fact(superseded_by)
    WHERE superseded_by IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
