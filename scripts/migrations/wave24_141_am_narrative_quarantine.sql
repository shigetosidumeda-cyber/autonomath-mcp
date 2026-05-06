-- target_db: autonomath
-- migration wave24_141_am_narrative_quarantine (MASTER_PLAN_v1 章
-- 10.10.1 — quarantine table + 5 narrative tables に
-- is_active / quarantine_id / content_hash 列追加)
--
-- Why this exists:
--   The fact-check pipeline (§10.10) needs a way to soft-delete
--   ("quarantine") narrative rows that fail match-rate, customer
--   report, corpus-drift, or operator review without hard-deleting
--   them. The `is_active` column is the read-time gate (every
--   serve query MUST `WHERE is_active = 1`). `quarantine_id`
--   joins to `am_narrative_quarantine` for audit trail.
--   `content_hash` is recorded on insert so corpus-drift detection
--   can flag rows whose source body has changed since generation.
--
--   The 4 non-program narrative tables (am_houjin_360_narrative,
--   am_enforcement_summary, am_case_study_narrative,
--   am_law_article_summary) do NOT have their own dedicated
--   migration in Wave 24 — generation is offline, ingest is the
--   only schema-touching path. We CREATE IF NOT EXISTS minimal
--   stubs here so the ALTER ADD COLUMN statements have a target
--   even on a fresh DB. The cron's INSERT OR REPLACE owns the
--   actual column population. Once a future migration declares
--   any of the 4 with a richer shape, the IF NOT EXISTS here
--   silently steps aside.
--
-- Schema:
--   am_narrative_quarantine
--     * quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT
--     * narrative_id INTEGER NOT NULL
--     * narrative_table TEXT NOT NULL CHECK (narrative_table IN (
--          'am_program_narrative','am_houjin_360_narrative',
--          'am_enforcement_summary','am_case_study_narrative',
--          'am_law_article_summary'))
--     * reason TEXT NOT NULL CHECK (reason IN (
--          'low_match_rate','customer_report','corpus_drift','operator_reject'))
--     * match_rate REAL  — only when reason='low_match_rate'
--     * detected_at TEXT NOT NULL DEFAULT (datetime('now'))
--     * resolved_at TEXT
--     * resolution TEXT CHECK (resolution IS NULL OR resolution IN (
--          'regenerated','manual_fix','deleted','false_positive'))
--     * UNIQUE (narrative_id, narrative_table, detected_at)
--
--   ALTER on 5 narrative tables (each table gets is_active /
--   quarantine_id / content_hash):
--     am_program_narrative      — created in wave24_136
--     am_houjin_360_narrative   — stub created here
--     am_enforcement_summary    — stub created here
--     am_case_study_narrative   — stub created here
--     am_law_article_summary    — stub created here
--
-- Indexes:
--   * idx_anq_state — find unresolved quarantine entries.
--   * is_active partial indexes per narrative table (next ingest
--     queries serve only is_active=1 rows).
--
-- Idempotency:
--   ALTER ADD COLUMN raises "duplicate column name" on re-run;
--   entrypoint.sh §4 swallows that case (lines 420-428) when the
--   message is exclusively "duplicate column" — same pattern as
--   migrations 049/101/105/106. CREATE * IF NOT EXISTS for
--   tables / indexes.
--
-- DOWN:
--   See companion `wave24_141_am_narrative_quarantine_rollback.sql`.

PRAGMA foreign_keys = ON;

-- 1. quarantine table.
CREATE TABLE IF NOT EXISTS am_narrative_quarantine (
    quarantine_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id     INTEGER NOT NULL,
    narrative_table  TEXT NOT NULL CHECK (narrative_table IN (
                        'am_program_narrative','am_houjin_360_narrative',
                        'am_enforcement_summary','am_case_study_narrative',
                        'am_law_article_summary'
                     )),
    reason           TEXT NOT NULL CHECK (reason IN (
                        'low_match_rate','customer_report','corpus_drift','operator_reject'
                     )),
    match_rate       REAL,
    detected_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at      TEXT,
    resolution       TEXT CHECK (resolution IS NULL OR resolution IN (
                        'regenerated','manual_fix','deleted','false_positive'
                     )),
    UNIQUE (narrative_id, narrative_table, detected_at)
);

CREATE INDEX IF NOT EXISTS idx_anq_state
    ON am_narrative_quarantine(narrative_table, narrative_id, resolved_at);

CREATE INDEX IF NOT EXISTS idx_anq_unresolved
    ON am_narrative_quarantine(detected_at) WHERE resolved_at IS NULL;

-- 2. Stub the 4 non-program narrative tables IF NOT EXISTS, so the
--    ALTER below can run on a fresh DB. Each carries a minimal
--    narrative_id / body_text / generated_at shell; the offline
--    ETL owns the richer column set later via INSERT OR REPLACE
--    (or a future migration enlarging the shape under IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS am_houjin_360_narrative (
    narrative_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou   TEXT NOT NULL,
    lang            TEXT NOT NULL DEFAULT 'ja' CHECK (lang IN ('ja','en')),
    body_text       TEXT NOT NULL,
    source_url_json TEXT,
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (houjin_bangou, lang)
);

CREATE TABLE IF NOT EXISTS am_enforcement_summary (
    narrative_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    enforcement_id  INTEGER NOT NULL,
    lang            TEXT NOT NULL DEFAULT 'ja' CHECK (lang IN ('ja','en')),
    body_text       TEXT NOT NULL,
    source_url_json TEXT,
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (enforcement_id, lang)
);

CREATE TABLE IF NOT EXISTS am_case_study_narrative (
    narrative_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL,
    lang            TEXT NOT NULL DEFAULT 'ja' CHECK (lang IN ('ja','en')),
    body_text       TEXT NOT NULL,
    source_url_json TEXT,
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (case_id, lang)
);

CREATE TABLE IF NOT EXISTS am_law_article_summary (
    narrative_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    law_canonical_id TEXT NOT NULL,
    article_no       TEXT,
    lang             TEXT NOT NULL DEFAULT 'ja' CHECK (lang IN ('ja','en')),
    body_text        TEXT NOT NULL,
    source_url_json  TEXT,
    generated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- UNIQUE 句は CREATE UNIQUE INDEX で後付け (SQLite 3.31+ の expression UNIQUE INDEX)
-- inline UNIQUE (..., COALESCE(...)) は SQLite が
-- "expressions prohibited in PRIMARY KEY and UNIQUE constraints" で abort するため不可。
CREATE UNIQUE INDEX IF NOT EXISTS uq_alas_article_lang
    ON am_law_article_summary(law_canonical_id, COALESCE(article_no, ''), lang);

-- 3. ALTER each narrative table to add (is_active, quarantine_id,
--    content_hash). is_active default 1 means existing rows
--    materialize as active by default. SQLite's ALTER ADD COLUMN
--    with DEFAULT applies lazily to existing rows; explicit values
--    on subsequent UPDATE / INSERT are honored.

-- am_program_narrative (declared in wave24_136).
ALTER TABLE am_program_narrative ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE am_program_narrative ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_program_narrative ADD COLUMN content_hash TEXT;

ALTER TABLE am_houjin_360_narrative ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE am_houjin_360_narrative ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_houjin_360_narrative ADD COLUMN content_hash TEXT;

ALTER TABLE am_enforcement_summary ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE am_enforcement_summary ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_enforcement_summary ADD COLUMN content_hash TEXT;

ALTER TABLE am_case_study_narrative ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE am_case_study_narrative ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_case_study_narrative ADD COLUMN content_hash TEXT;

ALTER TABLE am_law_article_summary ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE am_law_article_summary ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_law_article_summary ADD COLUMN content_hash TEXT;

-- 4. Partial indexes on is_active for the serve-time `WHERE is_active = 1`
--    hot path. Partial keeps the index size proportional to active rows,
--    not the full quarantined population.
CREATE INDEX IF NOT EXISTS idx_apn_active
    ON am_program_narrative(program_id, lang, section)
    WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_ah360n_active
    ON am_houjin_360_narrative(houjin_bangou, lang)
    WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_aes_active
    ON am_enforcement_summary(enforcement_id, lang)
    WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_acsn_active
    ON am_case_study_narrative(case_id, lang)
    WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_alas_active
    ON am_law_article_summary(law_canonical_id, lang)
    WHERE is_active = 1;
