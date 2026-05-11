-- target_db: autonomath
-- migration: 259_court_decisions_extended (Wave 43.1.10 — 17,935+ rows target)
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS am_court_decisions_v2 (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    unified_id TEXT NOT NULL UNIQUE,
    case_number TEXT, court TEXT,
    court_level TEXT NOT NULL,
    court_level_canonical TEXT NOT NULL,
    case_type TEXT NOT NULL DEFAULT 'other',
    case_name TEXT,
    decision_date TEXT,
    decision_date_start TEXT,
    decision_date_end TEXT,
    fiscal_year INTEGER,
    decision_type TEXT,
    subject_area TEXT,
    precedent_weight TEXT NOT NULL DEFAULT 'informational',
    related_law_ids_json TEXT NOT NULL DEFAULT '[]',
    related_program_ids_json TEXT NOT NULL DEFAULT '[]',
    key_ruling_excerpt TEXT,
    key_ruling_full TEXT,
    parties_involved TEXT,
    impact_on_business TEXT,
    full_text_url TEXT,
    pdf_url TEXT,
    source_url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'courts_jp',
    source_excerpt TEXT,
    source_checksum TEXT,
    license TEXT NOT NULL DEFAULT 'gov_standard',
    redistribute_ok INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_ok IN (0, 1)),
    confidence REAL NOT NULL DEFAULT 0.85,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified TEXT,
    notes TEXT,
    CONSTRAINT ck_v2_court_level CHECK (court_level_canonical IN ('supreme','high','district','summary','family')),
    CONSTRAINT ck_v2_case_type CHECK (case_type IN ('tax','admin','corporate','ip','labor','civil','criminal','other')),
    CONSTRAINT ck_v2_source CHECK (source IN ('courts_jp','ndl_oai')),
    CONSTRAINT ck_v2_decision_type CHECK (decision_type IS NULL OR decision_type IN ('判決','決定','命令')),
    CONSTRAINT ck_v2_precedent_weight CHECK (precedent_weight IN ('binding','persuasive','informational')),
    CONSTRAINT ck_v2_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);
CREATE INDEX IF NOT EXISTS idx_court_v2_unified ON am_court_decisions_v2(unified_id);
CREATE INDEX IF NOT EXISTS idx_court_v2_level_type ON am_court_decisions_v2(court_level_canonical, case_type, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_court_v2_case_type ON am_court_decisions_v2(case_type, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_court_v2_date_range ON am_court_decisions_v2(decision_date_start, decision_date_end);
CREATE INDEX IF NOT EXISTS idx_court_v2_fiscal_year ON am_court_decisions_v2(fiscal_year DESC, court_level_canonical);
CREATE INDEX IF NOT EXISTS idx_court_v2_source ON am_court_decisions_v2(source, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_court_v2_precedent ON am_court_decisions_v2(precedent_weight, court_level_canonical, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_court_v2_decision_date_only ON am_court_decisions_v2(decision_date DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS am_court_decisions_v2_fts USING fts5(
    case_name, key_ruling_excerpt, key_ruling_full, impact_on_business, subject_area,
    content='am_court_decisions_v2', content_rowid='case_id', tokenize="trigram");
CREATE TRIGGER IF NOT EXISTS am_court_v2_ai AFTER INSERT ON am_court_decisions_v2 BEGIN
    INSERT INTO am_court_decisions_v2_fts(rowid, case_name, key_ruling_excerpt, key_ruling_full, impact_on_business, subject_area)
    VALUES (new.case_id, new.case_name, new.key_ruling_excerpt, new.key_ruling_full, new.impact_on_business, new.subject_area);
END;
CREATE TRIGGER IF NOT EXISTS am_court_v2_ad AFTER DELETE ON am_court_decisions_v2 BEGIN
    INSERT INTO am_court_decisions_v2_fts(am_court_decisions_v2_fts, rowid, case_name, key_ruling_excerpt, key_ruling_full, impact_on_business, subject_area)
    VALUES ('delete', old.case_id, old.case_name, old.key_ruling_excerpt, old.key_ruling_full, old.impact_on_business, old.subject_area);
END;
CREATE TRIGGER IF NOT EXISTS am_court_v2_au AFTER UPDATE ON am_court_decisions_v2 BEGIN
    INSERT INTO am_court_decisions_v2_fts(am_court_decisions_v2_fts, rowid, case_name, key_ruling_excerpt, key_ruling_full, impact_on_business, subject_area)
    VALUES ('delete', old.case_id, old.case_name, old.key_ruling_excerpt, old.key_ruling_full, old.impact_on_business, old.subject_area);
    INSERT INTO am_court_decisions_v2_fts(rowid, case_name, key_ruling_excerpt, key_ruling_full, impact_on_business, subject_area)
    VALUES (new.case_id, new.case_name, new.key_ruling_excerpt, new.key_ruling_full, new.impact_on_business, new.subject_area);
END;
DROP VIEW IF EXISTS v_am_court_decisions_v2_public;
CREATE VIEW v_am_court_decisions_v2_public AS
SELECT case_id, unified_id, case_number, court,
    court_level, court_level_canonical, case_type, case_name,
    decision_date, decision_date_start, decision_date_end, fiscal_year,
    decision_type, subject_area, precedent_weight,
    related_law_ids_json, related_program_ids_json,
    key_ruling_excerpt, key_ruling_full, parties_involved, impact_on_business,
    full_text_url, pdf_url, source_url, source, source_excerpt, license,
    confidence, fetched_at, last_verified
FROM am_court_decisions_v2 WHERE redistribute_ok = 1;
CREATE TABLE IF NOT EXISTS am_court_decisions_v2_run_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT, source_kind TEXT,
    rows_added INTEGER NOT NULL DEFAULT 0, rows_updated INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0, errors_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_court_v2_run_log_started ON am_court_decisions_v2_run_log(started_at DESC);
COMMIT;
