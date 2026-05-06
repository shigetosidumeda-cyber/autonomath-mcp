-- target_db: autonomath
-- migration wave24_140_am_narrative_extracted_entities (MASTER_PLAN_v1
-- 章 10.10.1 — fact-check pipeline entity extraction store)
--
-- Why this exists:
--   `tools/offline/extract_narrative_entities.py` (operator-side
--   weekly cron, Sun 02:00 JST) parses every active narrative row,
--   extracts entities (money / year / percent / count / url / law /
--   program / houjin / jsic) via regex + spaCy GiNZA, and records
--   each (narrative × entity × span) here. The match-rate scorer
--   then joins this table to `am_entities` / `am_source` / `laws`
--   etc. to flag corpus-not-found entities for quarantine.
--
--   jpcite service-side path is SELECT only (this entire pipeline
--   is operator-side; no LLM imports under src/).
--
-- Schema:
--   * extract_id INTEGER PRIMARY KEY AUTOINCREMENT
--   * narrative_id INTEGER NOT NULL
--   * narrative_table TEXT NOT NULL  — 'am_program_narrative' /
--                                       'am_houjin_360_narrative' /
--                                       'am_enforcement_summary' /
--                                       'am_case_study_narrative' /
--                                       'am_law_article_summary'
--   * entity_kind TEXT NOT NULL  — 'money'|'year'|'percent'|'count'|'url'|
--                                  'law'|'program'|'houjin'|'jsic'
--   * entity_text TEXT NOT NULL  — raw substring extracted
--   * entity_norm TEXT NOT NULL  — normalized form (e.g. yen-converted,
--                                  ISO date, lowercased URL)
--   * span_start INTEGER NOT NULL  — char offset in body_text
--   * span_end INTEGER NOT NULL
--   * corpus_match INTEGER NOT NULL DEFAULT 0  — 0/1, did we find this in corpus
--   * corpus_table TEXT  — table the match landed in (NULL if no match)
--   * corpus_pk TEXT     — PK of the matching row (NULL if no match)
--   * extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE (narrative_id, narrative_table, span_start, span_end)
--
--   The composite UNIQUE makes the extractor's `INSERT OR REPLACE`
--   safe to re-run on the same narrative (offsets are stable until
--   the body text changes, which then triggers regeneration anyway).
--
-- Indexes:
--   * (narrative_table, narrative_id) — per-narrative scan.
--   * (entity_kind, corpus_match) — KPI roll-up "money entities
--     not found in corpus".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR REPLACE under UNIQUE.
--
-- DOWN:
--   See companion `wave24_140_am_narrative_extracted_entities_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_narrative_extracted_entities (
    extract_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id     INTEGER NOT NULL,
    narrative_table  TEXT NOT NULL CHECK (narrative_table IN (
                        'am_program_narrative','am_houjin_360_narrative',
                        'am_enforcement_summary','am_case_study_narrative',
                        'am_law_article_summary'
                     )),
    entity_kind      TEXT NOT NULL CHECK (entity_kind IN (
                        'money','year','percent','count','url',
                        'law','program','houjin','jsic'
                     )),
    entity_text      TEXT NOT NULL,
    entity_norm      TEXT NOT NULL,
    span_start       INTEGER NOT NULL,
    span_end         INTEGER NOT NULL CHECK (span_end > span_start),
    corpus_match     INTEGER NOT NULL DEFAULT 0 CHECK (corpus_match IN (0, 1)),
    corpus_table     TEXT,
    corpus_pk        TEXT,
    extracted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (narrative_id, narrative_table, span_start, span_end)
);

CREATE INDEX IF NOT EXISTS idx_nee_narrative
    ON am_narrative_extracted_entities(narrative_table, narrative_id);

CREATE INDEX IF NOT EXISTS idx_nee_kind_match
    ON am_narrative_extracted_entities(entity_kind, corpus_match);
