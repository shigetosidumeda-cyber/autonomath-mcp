-- target_db: autonomath
-- migration: 253_law_tsutatsu_all
-- generated_at: 2026-05-12
-- author: Wave 43.1.6 — 各省庁 通達 (15 ministry) all-government cohort
-- idempotent: every CREATE uses IF NOT EXISTS; no destructive DML.
--
-- Existing 230 `am_nta_tsutatsu_extended` covers ONLY 国税庁 (NTA) 通達.
-- This table extends 通達 coverage across 15 ministries (NTA + METI + MHLW +
-- ENV + MAFF + MLIT + FSA + JFTC + NPA + SOUMU + MEXT + CAO + MOD + MOF +
-- MOJ) under a single namespace so cross-ministry search works.
--
-- Source discipline (一次資料 only): each ministry's primary domain. Aggregator
-- hosts (noukaweb / hojyokin-portal / biz.stayway / hojo-navi / mirai-joho)
-- are banned. ETL enforces this via BANNED_SOURCE_HOSTS.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE IF NOT EXISTS am_law_tsutatsu_all (
    tsutatsu_id        TEXT PRIMARY KEY,
    agency_id          TEXT NOT NULL,
    agency_name        TEXT NOT NULL,
    tsutatsu_number    TEXT,
    title              TEXT NOT NULL,
    body_text          TEXT,
    body_excerpt       TEXT,
    issued_date        TEXT,
    last_revised       TEXT,
    industry_jsic_major TEXT,
    applicable_law_id  TEXT,
    document_type      TEXT NOT NULL DEFAULT 'tsutatsu',
    source_url         TEXT NOT NULL,
    full_text_url      TEXT,
    pdf_url            TEXT,
    license            TEXT NOT NULL DEFAULT 'gov_standard',
    content_hash       TEXT,
    ingested_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified      TEXT,
    CONSTRAINT ck_tsutatsu_all_agency CHECK (agency_id IN (
        'nta','meti','mhlw','env','maff','mlit','fsa','jftc',
        'npa','soumu','mext','cao','mod','mof','moj'
    )),
    CONSTRAINT ck_tsutatsu_all_doctype CHECK (document_type IN (
        'tsutatsu','notice','kokuji','jirei','q_a','other'
    ))
);

CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_agency
    ON am_law_tsutatsu_all(agency_id, issued_date DESC);
CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_issued
    ON am_law_tsutatsu_all(issued_date DESC);
CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_industry
    ON am_law_tsutatsu_all(industry_jsic_major, issued_date DESC);
CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_applicable_law
    ON am_law_tsutatsu_all(applicable_law_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tsutatsu_all_source_url
    ON am_law_tsutatsu_all(source_url);
CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_hash
    ON am_law_tsutatsu_all(content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS am_law_tsutatsu_all_fts USING fts5(
    title, body_text, agency_name,
    content='am_law_tsutatsu_all', content_rowid='rowid',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_tsutatsu_all_ai
AFTER INSERT ON am_law_tsutatsu_all BEGIN
    INSERT INTO am_law_tsutatsu_all_fts(rowid, title, body_text, agency_name)
    VALUES (new.rowid, new.title, new.body_text, new.agency_name);
END;

CREATE TRIGGER IF NOT EXISTS am_tsutatsu_all_ad
AFTER DELETE ON am_law_tsutatsu_all BEGIN
    INSERT INTO am_law_tsutatsu_all_fts(am_law_tsutatsu_all_fts, rowid, title, body_text, agency_name)
    VALUES ('delete', old.rowid, old.title, old.body_text, old.agency_name);
END;

CREATE TRIGGER IF NOT EXISTS am_tsutatsu_all_au
AFTER UPDATE ON am_law_tsutatsu_all BEGIN
    INSERT INTO am_law_tsutatsu_all_fts(am_law_tsutatsu_all_fts, rowid, title, body_text, agency_name)
    VALUES ('delete', old.rowid, old.title, old.body_text, old.agency_name);
    INSERT INTO am_law_tsutatsu_all_fts(rowid, title, body_text, agency_name)
    VALUES (new.rowid, new.title, new.body_text, new.agency_name);
END;

DROP VIEW IF EXISTS v_tsutatsu_all_agency_density;
CREATE VIEW v_tsutatsu_all_agency_density AS
SELECT
    agency_id, agency_name,
    COUNT(*) AS tsutatsu_count,
    MAX(issued_date) AS latest_issued,
    MIN(issued_date) AS earliest_issued
FROM am_law_tsutatsu_all
GROUP BY agency_id, agency_name
ORDER BY tsutatsu_count DESC;

CREATE TABLE IF NOT EXISTS am_law_tsutatsu_all_run_log (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    agencies_run   TEXT,
    rows_inserted  INTEGER NOT NULL DEFAULT 0,
    rows_skipped   INTEGER NOT NULL DEFAULT 0,
    error_text     TEXT
);

CREATE INDEX IF NOT EXISTS idx_tsutatsu_all_run_log_started
    ON am_law_tsutatsu_all_run_log(started_at DESC);

COMMIT;
