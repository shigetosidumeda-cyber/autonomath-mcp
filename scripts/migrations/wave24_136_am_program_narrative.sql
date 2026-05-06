-- target_db: autonomath
-- migration wave24_136_am_program_narrative (MASTER_PLAN_v1 章 10.2.11
-- — 解説 narrative 4 section × 2 lang + FTS5 + 3 trigger)
--
-- Why this exists:
--   `get_program_narrative` (#107, sensitive=YES) and
--   `get_program_keyword_analysis` (#116) need a structured
--   narrative table where each (program × language × section) is
--   one row. Sections are the 4 standard panels of the §10.8 full
--   envelope: overview, eligibility, application_flow, pitfalls.
--
--   Generation is offline by Claude Code subagent batch (memory
--   `feedback_no_operator_llm_api`); jpcite service-side path is
--   SELECT only.
--
--   FTS5 trigram lets `get_program_keyword_analysis` and
--   freeform program search hit the narrative body without a
--   LIKE scan over 93,472 rows.
--
-- Schema:
--   am_program_narrative
--     * narrative_id INTEGER PRIMARY KEY AUTOINCREMENT
--     * program_id INTEGER NOT NULL  — joins to programs.id (jpintel-side)
--                                     / jpi_programs.id (autonomath-side mirror)
--     * lang TEXT NOT NULL CHECK (lang IN ('ja','en'))
--     * section TEXT NOT NULL CHECK (section IN
--          ('overview','eligibility','application_flow','pitfalls'))
--     * body_text TEXT NOT NULL
--     * source_url_json TEXT  — JSON list of citations from generation
--     * model_id TEXT
--     * generated_at TEXT NOT NULL DEFAULT (datetime('now'))
--     * literal_quote_check_passed INTEGER NOT NULL DEFAULT 0
--                                  -- 0 / 1, set by ingest_offline_inbox
--     * UNIQUE (program_id, lang, section)
--
--   The is_active / quarantine_id / content_hash columns mandated
--   by §10.10 are added by wave24_141 (intentionally split so this
--   migration is a clean CREATE).
--
--   am_program_narrative_fts (FTS5 trigram contentless wrapper):
--     * body_text — the column FTS5 indexes
--     * narrative_id UNINDEXED — join key back to base table
--
-- Triggers (3 — INSERT / UPDATE / DELETE keep FTS in sync):
--   am_program_narrative_ai (AFTER INSERT)
--   am_program_narrative_au (AFTER UPDATE)
--   am_program_narrative_ad (AFTER DELETE)
--
--   Pattern matches migration 057_case_studies_fts.sql for
--   consistency.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS for table / virtual table / index /
--   trigger. Re-apply on populated DB is a no-op.
--
-- DOWN:
--   See companion `wave24_136_am_program_narrative_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_narrative (
    narrative_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id                  INTEGER NOT NULL,
    lang                        TEXT NOT NULL CHECK (lang IN ('ja','en')),
    section                     TEXT NOT NULL CHECK (section IN (
                                    'overview','eligibility','application_flow','pitfalls'
                                )),
    body_text                   TEXT NOT NULL,
    source_url_json             TEXT,
    model_id                    TEXT,
    generated_at                TEXT NOT NULL DEFAULT (datetime('now')),
    literal_quote_check_passed  INTEGER NOT NULL DEFAULT 0
                                 CHECK (literal_quote_check_passed IN (0, 1)),
    UNIQUE (program_id, lang, section)
);

CREATE INDEX IF NOT EXISTS idx_apn_program_lang
    ON am_program_narrative(program_id, lang);

-- FTS5 trigram for substring / phrase search across narrative bodies.
CREATE VIRTUAL TABLE IF NOT EXISTS am_program_narrative_fts USING fts5(
    body_text,
    narrative_id UNINDEXED,
    tokenize = 'trigram'
);

-- Trigger 1/3 — keep FTS in sync on INSERT.
CREATE TRIGGER IF NOT EXISTS am_program_narrative_ai
AFTER INSERT ON am_program_narrative
BEGIN
    INSERT INTO am_program_narrative_fts(rowid, body_text, narrative_id)
    VALUES (NEW.narrative_id, COALESCE(NEW.body_text, ''), NEW.narrative_id);
END;

-- Trigger 2/3 — keep FTS in sync on UPDATE.
CREATE TRIGGER IF NOT EXISTS am_program_narrative_au
AFTER UPDATE ON am_program_narrative
BEGIN
    UPDATE am_program_narrative_fts
       SET body_text = COALESCE(NEW.body_text, '')
     WHERE rowid = NEW.narrative_id;
END;

-- Trigger 3/3 — keep FTS in sync on DELETE.
CREATE TRIGGER IF NOT EXISTS am_program_narrative_ad
AFTER DELETE ON am_program_narrative
BEGIN
    DELETE FROM am_program_narrative_fts WHERE rowid = OLD.narrative_id;
END;
