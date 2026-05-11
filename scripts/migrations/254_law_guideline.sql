-- target_db: autonomath
-- migration: 254_law_guideline
-- generated_at: 2026-05-12
-- author: Wave 43.1.7 — 業種ガイドライン (省庁 + 業界団体)
-- idempotent: every CREATE uses IF NOT EXISTS.
--
-- Guidelines (ガイドライン / 指針 / 手引) authored by 省庁 OR 業界団体
-- (商工会議所 / 中小企業庁 / 中小企業基盤整備機構 / 経団連 / 税理士連合会
-- / 公認会計士協会 等). Separates guideline rows from 通達 so cohort
-- queries can filter one without the other.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE IF NOT EXISTS am_law_guideline (
    guideline_id        TEXT PRIMARY KEY,
    issuer_type         TEXT NOT NULL,
    issuer_org          TEXT NOT NULL,
    issuer_agency_id    TEXT,
    title               TEXT NOT NULL,
    short_title         TEXT,
    body_text           TEXT,
    body_excerpt        TEXT,
    industry_jsic_major TEXT,
    industry_jsic_minor TEXT,
    industry_jsic_label TEXT,
    target_audience     TEXT,
    compliance_status   TEXT NOT NULL DEFAULT 'recommended',
    issued_date         TEXT,
    last_revised        TEXT,
    related_law_ids_json TEXT NOT NULL DEFAULT '[]',
    document_type       TEXT NOT NULL DEFAULT 'guideline',
    source_url          TEXT NOT NULL,
    full_text_url       TEXT,
    pdf_url             TEXT,
    license             TEXT NOT NULL DEFAULT 'gov_standard',
    content_hash        TEXT,
    ingested_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified       TEXT,
    CONSTRAINT ck_guideline_issuer_type CHECK (issuer_type IN (
        'ministry','industry_body','public_corp','other'
    )),
    CONSTRAINT ck_guideline_compliance CHECK (compliance_status IN (
        'mandatory','recommended','voluntary','unknown'
    )),
    CONSTRAINT ck_guideline_doc_type CHECK (document_type IN (
        'guideline','manual','tebiki','shishin','best_practice','model_rules','other'
    ))
);

CREATE INDEX IF NOT EXISTS idx_guideline_issuer
    ON am_law_guideline(issuer_type, issuer_org);
CREATE INDEX IF NOT EXISTS idx_guideline_agency
    ON am_law_guideline(issuer_agency_id, issued_date DESC);
CREATE INDEX IF NOT EXISTS idx_guideline_industry
    ON am_law_guideline(industry_jsic_major, industry_jsic_minor);
CREATE INDEX IF NOT EXISTS idx_guideline_issued
    ON am_law_guideline(issued_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_guideline_source_url
    ON am_law_guideline(source_url);
CREATE INDEX IF NOT EXISTS idx_guideline_hash
    ON am_law_guideline(content_hash);
CREATE INDEX IF NOT EXISTS idx_guideline_compliance
    ON am_law_guideline(compliance_status, industry_jsic_major);

CREATE VIRTUAL TABLE IF NOT EXISTS am_law_guideline_fts USING fts5(
    title, body_text, issuer_org,
    content='am_law_guideline', content_rowid='rowid',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_guideline_ai
AFTER INSERT ON am_law_guideline BEGIN
    INSERT INTO am_law_guideline_fts(rowid, title, body_text, issuer_org)
    VALUES (new.rowid, new.title, new.body_text, new.issuer_org);
END;

CREATE TRIGGER IF NOT EXISTS am_guideline_ad
AFTER DELETE ON am_law_guideline BEGIN
    INSERT INTO am_law_guideline_fts(am_law_guideline_fts, rowid, title, body_text, issuer_org)
    VALUES ('delete', old.rowid, old.title, old.body_text, old.issuer_org);
END;

CREATE TRIGGER IF NOT EXISTS am_guideline_au
AFTER UPDATE ON am_law_guideline BEGIN
    INSERT INTO am_law_guideline_fts(am_law_guideline_fts, rowid, title, body_text, issuer_org)
    VALUES ('delete', old.rowid, old.title, old.body_text, old.issuer_org);
    INSERT INTO am_law_guideline_fts(rowid, title, body_text, issuer_org)
    VALUES (new.rowid, new.title, new.body_text, new.issuer_org);
END;

DROP VIEW IF EXISTS v_guideline_industry_density;
CREATE VIEW v_guideline_industry_density AS
SELECT
    industry_jsic_major, industry_jsic_label,
    COUNT(*) AS guideline_count,
    SUM(CASE WHEN compliance_status='mandatory' THEN 1 ELSE 0 END) AS mandatory_count,
    SUM(CASE WHEN compliance_status='recommended' THEN 1 ELSE 0 END) AS recommended_count
FROM am_law_guideline
WHERE industry_jsic_major IS NOT NULL
GROUP BY industry_jsic_major, industry_jsic_label
ORDER BY guideline_count DESC;

CREATE TABLE IF NOT EXISTS am_law_guideline_run_log (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    issuers_run    TEXT,
    rows_inserted  INTEGER NOT NULL DEFAULT 0,
    rows_skipped   INTEGER NOT NULL DEFAULT 0,
    error_text     TEXT
);

CREATE INDEX IF NOT EXISTS idx_guideline_run_log_started
    ON am_law_guideline_run_log(started_at DESC);

COMMIT;
