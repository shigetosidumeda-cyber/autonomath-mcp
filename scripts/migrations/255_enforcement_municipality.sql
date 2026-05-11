-- target_db: autonomath
-- migration: 255_enforcement_municipality (Wave 43.1.9 — 1,815+ rows target)
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS am_enforcement_municipality (
    enforcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    unified_id TEXT NOT NULL UNIQUE,
    municipality_code TEXT,
    prefecture_code TEXT NOT NULL,
    prefecture_name TEXT NOT NULL,
    municipality_name TEXT,
    agency_type TEXT NOT NULL DEFAULT 'pref',
    agency_name TEXT,
    action_type TEXT NOT NULL DEFAULT 'other',
    action_date TEXT NOT NULL,
    action_period_start TEXT,
    action_period_end TEXT,
    respondent_name_anonymized TEXT NOT NULL DEFAULT '匿名化',
    respondent_houjin_bangou TEXT,
    industry_jsic TEXT,
    body_text_excerpt TEXT,
    action_summary TEXT,
    source_url TEXT NOT NULL,
    source_host TEXT NOT NULL,
    content_hash TEXT,
    license TEXT NOT NULL DEFAULT 'gov_standard',
    redistribute_ok INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_ok IN (0, 1)),
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified TEXT,
    notes TEXT,
    CONSTRAINT ck_enmuni_pref CHECK (length(prefecture_code) = 2),
    CONSTRAINT ck_enmuni_agency CHECK (agency_type IN ('pref','city','ward','town','village','kouikirengou','other')),
    CONSTRAINT ck_enmuni_action CHECK (action_type IN ('license_revoke','business_suspend','business_improvement','subsidy_refund','subsidy_exclude','fine','kankoku','caution','recommendation','public_announcement','other'))
);
CREATE INDEX IF NOT EXISTS idx_enmuni_unified ON am_enforcement_municipality(unified_id);
CREATE INDEX IF NOT EXISTS idx_enmuni_pref_date ON am_enforcement_municipality(prefecture_code, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_muni_date ON am_enforcement_municipality(municipality_code, action_date DESC) WHERE municipality_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_enmuni_action_type ON am_enforcement_municipality(action_type, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_agency_type ON am_enforcement_municipality(agency_type, prefecture_code, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_houjin ON am_enforcement_municipality(respondent_houjin_bangou, action_date DESC) WHERE respondent_houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_enmuni_source_host ON am_enforcement_municipality(source_host, ingested_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS am_enforcement_municipality_fts USING fts5(
    agency_name, action_summary, body_text_excerpt, respondent_name_anonymized,
    content='am_enforcement_municipality', content_rowid='enforcement_id', tokenize="trigram");
CREATE TRIGGER IF NOT EXISTS am_enmuni_ai AFTER INSERT ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES (new.enforcement_id, new.agency_name, new.action_summary, new.body_text_excerpt, new.respondent_name_anonymized);
END;
CREATE TRIGGER IF NOT EXISTS am_enmuni_ad AFTER DELETE ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(am_enforcement_municipality_fts, rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES ('delete', old.enforcement_id, old.agency_name, old.action_summary, old.body_text_excerpt, old.respondent_name_anonymized);
END;
CREATE TRIGGER IF NOT EXISTS am_enmuni_au AFTER UPDATE ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(am_enforcement_municipality_fts, rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES ('delete', old.enforcement_id, old.agency_name, old.action_summary, old.body_text_excerpt, old.respondent_name_anonymized);
    INSERT INTO am_enforcement_municipality_fts(rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES (new.enforcement_id, new.agency_name, new.action_summary, new.body_text_excerpt, new.respondent_name_anonymized);
END;
DROP VIEW IF EXISTS v_enforcement_municipality_public;
CREATE VIEW v_enforcement_municipality_public AS
SELECT enforcement_id, unified_id, municipality_code, prefecture_code,
    prefecture_name, municipality_name, agency_type, agency_name,
    action_type, action_date, action_period_start, action_period_end,
    respondent_name_anonymized, respondent_houjin_bangou,
    industry_jsic, body_text_excerpt, action_summary,
    source_url, source_host, license, ingested_at
FROM am_enforcement_municipality WHERE redistribute_ok = 1;
CREATE TABLE IF NOT EXISTS am_enforcement_municipality_run_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT, source_kind TEXT,
    pref_count INTEGER NOT NULL DEFAULT 0, muni_count INTEGER NOT NULL DEFAULT 0,
    rows_added INTEGER NOT NULL DEFAULT 0, rows_updated INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0, error_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_enmuni_run_log_started ON am_enforcement_municipality_run_log(started_at DESC);
COMMIT;
