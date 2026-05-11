-- target_db: autonomath
-- migration: 240_law_en_full
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 5a — 法令 6,493 EN 全部 (現 body_en は article 単位 53,278 / 353,278)
-- idempotent: every CREATE uses IF NOT EXISTS; ADD COLUMN swallowed by entrypoint.sh
--
-- Axis 5a expands the Foreign FDI cohort English-translation surface from
-- 53,278 / 353,278 articles (15.1%) toward full coverage at:
--   - am_law (6,493 rows) body_en + summary_en (NEW columns)
--   - am_law_article (353,278 rows) body_en already present (migration 090) —
--     this migration only adds the *progress + provenance* substrate
--     (am_law_translation_progress / am_law_translation_review_queue).
--
-- Memory constraints honored:
--   - No LLM API call substrate. All translation candidates land in
--     am_law_translation_review_queue and require human promote before
--     they are visible on body_en (一次資料 only 原則).
--   - source_url_en stays NOT NULL on promoted rows; sentence-transformer
--     transfer candidates are stored separately and disclaimed.
--
-- Forward-only / idempotent: re-running on each Fly boot is safe.

PRAGMA foreign_keys = OFF;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. am_law (catalog stub) language columns
-- ---------------------------------------------------------------------------
ALTER TABLE am_law ADD COLUMN summary_en TEXT;
ALTER TABLE am_law ADD COLUMN title_en TEXT;
ALTER TABLE am_law ADD COLUMN body_en TEXT;
ALTER TABLE am_law ADD COLUMN body_en_source_url TEXT;
ALTER TABLE am_law ADD COLUMN body_en_fetched_at TEXT;
ALTER TABLE am_law ADD COLUMN body_en_license TEXT DEFAULT 'cc_by_4.0';

CREATE INDEX IF NOT EXISTS ix_am_law_body_en_present
    ON am_law(canonical_id)
    WHERE body_en IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_am_law_title_en_present
    ON am_law(canonical_id)
    WHERE title_en IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. am_law_translation_progress — per-law coverage tracker
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_law_translation_progress (
    canonical_id           TEXT NOT NULL,
    target_lang            TEXT NOT NULL CHECK (target_lang IN ('en','zh','ko')),
    total_articles         INTEGER NOT NULL DEFAULT 0 CHECK (total_articles >= 0),
    translated_articles    INTEGER NOT NULL DEFAULT 0 CHECK (translated_articles >= 0),
    title_translated       INTEGER NOT NULL DEFAULT 0 CHECK (title_translated IN (0,1)),
    summary_translated     INTEGER NOT NULL DEFAULT 0 CHECK (summary_translated IN (0,1)),
    coverage_pct           REAL NOT NULL DEFAULT 0 CHECK (coverage_pct BETWEEN 0 AND 100),
    last_refreshed_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (canonical_id, target_lang)
);

CREATE INDEX IF NOT EXISTS ix_am_law_translation_progress_lang
    ON am_law_translation_progress(target_lang, coverage_pct DESC);

CREATE INDEX IF NOT EXISTS ix_am_law_translation_progress_gap
    ON am_law_translation_progress(target_lang, coverage_pct ASC)
    WHERE coverage_pct < 100;

-- ---------------------------------------------------------------------------
-- 3. am_law_translation_review_queue — sentence-transformer candidates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_law_translation_review_queue (
    queue_id              TEXT PRIMARY KEY,
    target_kind           TEXT NOT NULL CHECK (target_kind IN ('law','article')),
    canonical_id          TEXT NOT NULL,
    article_id            INTEGER,
    target_lang           TEXT NOT NULL CHECK (target_lang IN ('en','zh','ko')),
    field_name            TEXT NOT NULL CHECK (field_name IN ('title','summary','body')),
    source_lang           TEXT NOT NULL DEFAULT 'ja',
    candidate_text        TEXT NOT NULL,
    candidate_source_url  TEXT NOT NULL,
    candidate_license     TEXT NOT NULL DEFAULT 'cc_by_4.0',
    similarity_score      REAL,
    model_name            TEXT,
    model_version         TEXT,
    operator_decision     TEXT CHECK (operator_decision IN ('pending','promote','reject')),
    operator_decision_at  TEXT,
    operator_notes        TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_am_law_translation_review_queue_pending
    ON am_law_translation_review_queue(target_lang, created_at DESC)
    WHERE operator_decision IS NULL OR operator_decision = 'pending';

CREATE INDEX IF NOT EXISTS ix_am_law_translation_review_queue_canonical
    ON am_law_translation_review_queue(canonical_id, target_lang);

-- ---------------------------------------------------------------------------
-- 4. fill refresh log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_law_translation_refresh_log (
    refresh_id            TEXT PRIMARY KEY,
    target_lang           TEXT NOT NULL CHECK (target_lang IN ('en','zh','ko')),
    started_at            TEXT NOT NULL,
    finished_at           TEXT,
    laws_processed        INTEGER NOT NULL DEFAULT 0,
    articles_filled       INTEGER NOT NULL DEFAULT 0,
    review_queue_added    INTEGER NOT NULL DEFAULT 0,
    skipped_no_source     INTEGER NOT NULL DEFAULT 0,
    error_text            TEXT,
    mode                  TEXT NOT NULL DEFAULT 'incremental' CHECK (mode IN ('incremental','full','dry-run'))
);

CREATE INDEX IF NOT EXISTS ix_am_law_translation_refresh_log_started
    ON am_law_translation_refresh_log(started_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_law_translation_refresh_log_lang
    ON am_law_translation_refresh_log(target_lang, started_at DESC);

COMMIT;
