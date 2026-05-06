-- target_db: autonomath
-- migration 171_corporate_risk_layer
--
-- Initial SQLite receiver for docs/integrations/derived-data-layer-spec.md
-- §5 `corporate_risk_layer`.
--
-- Why this exists:
--   Corporate DD currently spans invoice, enforcement, adoption,
--   procurement, EDINET, kanpou, houjin master, and entity-bridge sources.
--   Answer surfaces need one derived row per houjin subject that separates
--   public signals, DD questions, risk timeline events, source facts, and
--   known gaps.
--
--   This table deliberately excludes price, unit, conversion, and billing
--   fields. It stores only material that deepens public DD summaries,
--   evidence packets, monitoring deltas, and program-decision suppression.
--
-- Schema notes:
--   * Signal and list fields are serialized JSON TEXT. Offline builders
--     own object shapes such as {status, severity, evidence, inferred}.
--   * source_fact_ids_json / source_document_ids_json / known_gaps_json
--     implement the common derived-layer contract.
--   * subject_id normally equals houjin_no, but watch/query/private overlay
--     subjects can also materialize houjin risk rows.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `171_corporate_risk_layer_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_corporate_risk_layer (
    risk_layer_id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_name                            TEXT NOT NULL DEFAULT 'corporate_risk_layer'
                                          CHECK (layer_name = 'corporate_risk_layer'),
    subject_kind                          TEXT NOT NULL DEFAULT 'houjin' CHECK (subject_kind IN (
                                              'houjin','private_overlay','watch','query'
                                          )),
    subject_id                            TEXT NOT NULL,
    houjin_no                             TEXT NOT NULL CHECK (length(houjin_no) = 13),
    resolved_entity_id                    TEXT,
    invoice_status_signal_json            TEXT,
    enforcement_signal_json               TEXT,
    public_funding_dependency_signal_json TEXT,
    procurement_signal_json               TEXT,
    edinet_signal_json                    TEXT,
    kanpou_signal_json                    TEXT,
    name_change_signal_json               TEXT,
    related_entity_signal_json            TEXT,
    risk_timeline_json                    TEXT NOT NULL DEFAULT '[]',
    dd_questions_json                     TEXT NOT NULL DEFAULT '[]',
    risk_reason_codes_json                TEXT NOT NULL DEFAULT '[]',
    source_fact_ids_json                  TEXT NOT NULL DEFAULT '[]',
    source_document_ids_json              TEXT NOT NULL DEFAULT '[]',
    quality_tier                          TEXT NOT NULL DEFAULT 'X' CHECK (quality_tier IN
                                          ('S','A','B','C','X')),
    known_gaps_json                       TEXT NOT NULL DEFAULT '[]',
    corpus_snapshot_id                    TEXT,
    computed_at                           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_acrl_subject_houjin_snapshot
    ON am_corporate_risk_layer(
        subject_kind,
        subject_id,
        houjin_no,
        COALESCE(corpus_snapshot_id, '')
    );

CREATE INDEX IF NOT EXISTS idx_acrl_houjin_computed
    ON am_corporate_risk_layer(houjin_no, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_acrl_entity
    ON am_corporate_risk_layer(resolved_entity_id)
    WHERE resolved_entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_acrl_quality_time
    ON am_corporate_risk_layer(quality_tier, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_acrl_subject_time
    ON am_corporate_risk_layer(subject_kind, subject_id, computed_at DESC);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
