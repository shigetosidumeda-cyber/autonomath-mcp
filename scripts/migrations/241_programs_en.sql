-- target_db: jpintel
-- migration: 241_programs_en
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 5b — 制度 11,601 EN (Foreign FDI cohort enabler)
-- idempotent: ADD COLUMN failure swallowed; CREATE * IF NOT EXISTS

BEGIN;

ALTER TABLE programs ADD COLUMN title_en TEXT;
ALTER TABLE programs ADD COLUMN summary_en TEXT;
ALTER TABLE programs ADD COLUMN eligibility_en TEXT;
ALTER TABLE programs ADD COLUMN source_url_en TEXT;
ALTER TABLE programs ADD COLUMN translation_fetched_at TEXT;
ALTER TABLE programs ADD COLUMN translation_status TEXT
    DEFAULT 'unavailable'
    CHECK (translation_status IN ('unavailable','partial','full','review_pending'));

CREATE INDEX IF NOT EXISTS idx_programs_translation_status
    ON programs(translation_status, tier);

CREATE INDEX IF NOT EXISTS idx_programs_title_en_present
    ON programs(tier)
    WHERE title_en IS NOT NULL;

CREATE TABLE IF NOT EXISTS programs_translation_review_queue (
    queue_id              TEXT PRIMARY KEY,
    unified_id            TEXT NOT NULL,
    target_lang           TEXT NOT NULL CHECK (target_lang IN ('en','zh','ko')),
    field_name            TEXT NOT NULL CHECK (field_name IN ('title','summary','eligibility')),
    candidate_text        TEXT NOT NULL,
    candidate_source_url  TEXT NOT NULL,
    candidate_license     TEXT,
    similarity_score      REAL,
    model_name            TEXT,
    model_version         TEXT,
    operator_decision     TEXT CHECK (operator_decision IN ('pending','promote','reject')),
    operator_decision_at  TEXT,
    operator_notes        TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_programs_translation_review_pending
    ON programs_translation_review_queue(target_lang, created_at DESC)
    WHERE operator_decision IS NULL OR operator_decision = 'pending';

CREATE INDEX IF NOT EXISTS idx_programs_translation_review_program
    ON programs_translation_review_queue(unified_id, target_lang);

CREATE TABLE IF NOT EXISTS programs_translation_refresh_log (
    refresh_id            TEXT PRIMARY KEY,
    target_lang           TEXT NOT NULL CHECK (target_lang IN ('en','zh','ko')),
    started_at            TEXT NOT NULL,
    finished_at           TEXT,
    programs_processed    INTEGER NOT NULL DEFAULT 0,
    programs_filled       INTEGER NOT NULL DEFAULT 0,
    review_queue_added    INTEGER NOT NULL DEFAULT 0,
    skipped_no_english_page INTEGER NOT NULL DEFAULT 0,
    refused_aggregator    INTEGER NOT NULL DEFAULT 0,
    error_text            TEXT,
    mode                  TEXT NOT NULL DEFAULT 'incremental' CHECK (mode IN ('incremental','full','dry-run'))
);

CREATE INDEX IF NOT EXISTS idx_programs_translation_refresh_started
    ON programs_translation_refresh_log(started_at DESC);

COMMIT;
