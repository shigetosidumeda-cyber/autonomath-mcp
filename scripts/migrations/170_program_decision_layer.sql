-- target_db: autonomath
-- migration 170_program_decision_layer
--
-- Initial SQLite receiver for docs/integrations/derived-data-layer-spec.md
-- §4 `program_decision_layer`.
--
-- Why this exists:
--   Program search is already materialized in several am_* tables, but
--   downstream artifacts need a decision-ready row per
--   (subject × candidate program): proposal rank, reason codes, missing
--   eligibility inputs, next questions, source facts, and known gaps.
--
--   This table deliberately excludes price, unit, conversion, and billing
--   fields. It stores only material that deepens the answer body and
--   evidence packet.
--
-- Schema notes:
--   * JSON arrays/objects are stored as TEXT so the migration remains a
--     pure SQLite schema layer. Offline builders own JSON serialization.
--   * source_fact_ids_json / source_document_ids_json / known_gaps_json
--     implement the common derived-layer contract.
--   * candidate_rank is nullable because a row can be computed before the
--     final ranking pass; readers should ORDER BY candidate_rank only when
--     it is present, otherwise fall back to scores.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `170_program_decision_layer_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_decision_layer (
    decision_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_name                        TEXT NOT NULL DEFAULT 'program_decision_layer'
                                      CHECK (layer_name = 'program_decision_layer'),
    subject_kind                      TEXT NOT NULL CHECK (subject_kind IN (
                                          'program','houjin','private_overlay',
                                          'watch','query','region','industry','case'
                                      )),
    subject_id                        TEXT NOT NULL,
    program_id                        TEXT NOT NULL,
    subject_entity_id                 TEXT,
    private_overlay_id                TEXT,
    candidate_rank                    INTEGER CHECK (candidate_rank IS NULL OR candidate_rank > 0),
    fit_score                         REAL CHECK (fit_score IS NULL OR
                                                 (fit_score >= 0.0 AND fit_score <= 1.0)),
    win_signal_score                  REAL CHECK (win_signal_score IS NULL OR
                                                 (win_signal_score >= 0.0 AND win_signal_score <= 1.0)),
    urgency_score                     REAL CHECK (urgency_score IS NULL OR
                                                 (urgency_score >= 0.0 AND urgency_score <= 1.0)),
    documentation_risk_score          REAL CHECK (documentation_risk_score IS NULL OR
                                                 (documentation_risk_score >= 0.0 AND
                                                  documentation_risk_score <= 1.0)),
    eligibility_gap_count             INTEGER NOT NULL DEFAULT 0 CHECK (eligibility_gap_count >= 0),
    blocking_rule_count               INTEGER NOT NULL DEFAULT 0 CHECK (blocking_rule_count >= 0),
    unknown_rule_count                INTEGER NOT NULL DEFAULT 0 CHECK (unknown_rule_count >= 0),
    deadline_days_remaining           INTEGER,
    changed_since_last_packet         INTEGER CHECK (changed_since_last_packet IS NULL OR
                                                     changed_since_last_packet IN (0, 1)),
    rank_reason_codes_json            TEXT NOT NULL DEFAULT '[]',
    next_questions_json               TEXT NOT NULL DEFAULT '[]',
    recommended_action                TEXT NOT NULL CHECK (recommended_action IN (
                                          'propose_now','collect_docs','watch',
                                          'defer','exclude','broaden_search'
                                      )),
    source_fact_ids_json              TEXT NOT NULL DEFAULT '[]',
    source_document_ids_json          TEXT NOT NULL DEFAULT '[]',
    quality_tier                      TEXT NOT NULL DEFAULT 'X' CHECK (quality_tier IN
                                      ('S','A','B','C','X')),
    known_gaps_json                   TEXT NOT NULL DEFAULT '[]',
    corpus_snapshot_id                TEXT,
    computed_at                       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_apdl_subject_program_snapshot
    ON am_program_decision_layer(
        subject_kind,
        subject_id,
        program_id,
        COALESCE(private_overlay_id, ''),
        COALESCE(corpus_snapshot_id, '')
    );

CREATE INDEX IF NOT EXISTS idx_apdl_subject_rank
    ON am_program_decision_layer(subject_kind, subject_id, candidate_rank)
    WHERE candidate_rank IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_apdl_subject_scores
    ON am_program_decision_layer(
        subject_kind,
        subject_id,
        fit_score DESC,
        win_signal_score DESC,
        urgency_score DESC
    );

CREATE INDEX IF NOT EXISTS idx_apdl_program
    ON am_program_decision_layer(program_id);

CREATE INDEX IF NOT EXISTS idx_apdl_overlay
    ON am_program_decision_layer(private_overlay_id)
    WHERE private_overlay_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_apdl_action_quality
    ON am_program_decision_layer(recommended_action, quality_tier, computed_at DESC);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
