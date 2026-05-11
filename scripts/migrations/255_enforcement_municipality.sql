-- target_db: autonomath
-- migration: 255_enforcement_municipality
-- generated_at: 2026-05-12
-- author: Wave 43.1.9 — 行政処分 市町村+地方 extended layer (1,815+ rows target)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Extend the enforcement / 行政処分 corpus with a municipality + 地方 layer
-- so that local-government press releases (1,700 市町村 + 47 都道府県)
-- aggregate into one indexed surface alongside the existing
-- `am_enforcement_detail` (22,258 national-level rows) and
-- `enforcement_permit_event_layer` (mig 174) cross-source projection.
--
-- Why a NEW table (not a column on am_enforcement_detail)
-- -------------------------------------------------------
-- am_enforcement_detail (mig wave24_129) is the canonical national-level
-- single-source mirror with 22,258 rows and a strict houjin_bangou
-- resolution discipline. Local 市町村 press releases rarely carry a
-- houjin_bangou (often anonymized "市内事業者" / "A社" style), so they
-- fail the bridge-confidence gate (DEEP-08 0.95 floor) and don't fit
-- the mirror schema. We keep them in a separate, side-by-side table
-- whose row-level discipline matches local-government press-release
-- reality: anonymized respondent default, prefecture+municipality
-- denormalized, source_url == primary press release URL (NEVER an
-- aggregator).
--
-- Source discipline
-- -----------------
-- ONLY first-party government domains. Examples (non-exhaustive):
--   * pref.<code>.lg.jp  — 47 都道府県 公式
--   * city.<name>.lg.jp  — 1,700 市町村 公式
--   * town.<name>.lg.jp / village.<name>.lg.jp
-- Aggregators (noukaweb, hojyokin-portal, biz.stayway, news consolidators)
-- are BANNED on source_url. Discipline is enforced inside the fill ETL
-- (scripts/etl/fill_enforcement_municipality_2x.py) via the same
-- BANNED_SOURCE_HOSTS allowlist used elsewhere in the codebase.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_enforcement_municipality (
    enforcement_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    unified_id                  TEXT NOT NULL UNIQUE,
    municipality_code           TEXT,
    prefecture_code             TEXT NOT NULL,
    prefecture_name             TEXT NOT NULL,
    municipality_name           TEXT,
    agency_type                 TEXT NOT NULL DEFAULT 'pref',
    agency_name                 TEXT,
    action_type                 TEXT NOT NULL DEFAULT 'other',
    action_date                 TEXT NOT NULL,
    action_period_start         TEXT,
    action_period_end           TEXT,
    respondent_name_anonymized  TEXT NOT NULL DEFAULT '匿名化',
    respondent_houjin_bangou    TEXT,
    industry_jsic               TEXT,
    body_text_excerpt           TEXT,
    action_summary              TEXT,
    source_url                  TEXT NOT NULL,
    source_host                 TEXT NOT NULL,
    content_hash                TEXT,
    license                     TEXT NOT NULL DEFAULT 'gov_standard',
    redistribute_ok             INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_ok IN (0, 1)),
    ingested_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified               TEXT,
    notes                       TEXT,
    CONSTRAINT ck_enmuni_pref CHECK (length(prefecture_code) = 2
        AND prefecture_code GLOB '[0-9]*'
        AND prefecture_code NOT GLOB '*[^0-9]*'),
    CONSTRAINT ck_enmuni_muni CHECK (municipality_code IS NULL
        OR (length(municipality_code) = 5
            AND municipality_code GLOB '[0-9]*'
            AND municipality_code NOT GLOB '*[^0-9]*')),
    CONSTRAINT ck_enmuni_agency CHECK (agency_type IN (
        'pref','city','ward','town','village','kouikirengou','other'
    )),
    CONSTRAINT ck_enmuni_action CHECK (action_type IN (
        'license_revoke','business_suspend','business_improvement',
        'subsidy_refund','subsidy_exclude','fine','kankoku','caution',
        'recommendation','public_announcement','other'
    )),
    CONSTRAINT ck_enmuni_houjin CHECK (
        respondent_houjin_bangou IS NULL
        OR (length(respondent_houjin_bangou) = 13
            AND respondent_houjin_bangou GLOB '[0-9]*'
            AND respondent_houjin_bangou NOT GLOB '*[^0-9]*')
    ),
    CONSTRAINT ck_enmuni_jsic CHECK (
        industry_jsic IS NULL OR industry_jsic GLOB '[A-T]'
    )
);

CREATE INDEX IF NOT EXISTS idx_enmuni_unified
    ON am_enforcement_municipality(unified_id);
CREATE INDEX IF NOT EXISTS idx_enmuni_pref_date
    ON am_enforcement_municipality(prefecture_code, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_muni_date
    ON am_enforcement_municipality(municipality_code, action_date DESC)
    WHERE municipality_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_enmuni_action_type
    ON am_enforcement_municipality(action_type, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_agency_type
    ON am_enforcement_municipality(agency_type, prefecture_code, action_date DESC);
CREATE INDEX IF NOT EXISTS idx_enmuni_houjin
    ON am_enforcement_municipality(respondent_houjin_bangou, action_date DESC)
    WHERE respondent_houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_enmuni_source_host
    ON am_enforcement_municipality(source_host, ingested_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS am_enforcement_municipality_fts USING fts5(
    agency_name, action_summary, body_text_excerpt, respondent_name_anonymized,
    content='am_enforcement_municipality', content_rowid='enforcement_id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_enmuni_ai
AFTER INSERT ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES (new.enforcement_id, new.agency_name, new.action_summary, new.body_text_excerpt, new.respondent_name_anonymized);
END;

CREATE TRIGGER IF NOT EXISTS am_enmuni_ad
AFTER DELETE ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(am_enforcement_municipality_fts, rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES ('delete', old.enforcement_id, old.agency_name, old.action_summary, old.body_text_excerpt, old.respondent_name_anonymized);
END;

CREATE TRIGGER IF NOT EXISTS am_enmuni_au
AFTER UPDATE ON am_enforcement_municipality BEGIN
    INSERT INTO am_enforcement_municipality_fts(am_enforcement_municipality_fts, rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES ('delete', old.enforcement_id, old.agency_name, old.action_summary, old.body_text_excerpt, old.respondent_name_anonymized);
    INSERT INTO am_enforcement_municipality_fts(rowid, agency_name, action_summary, body_text_excerpt, respondent_name_anonymized)
    VALUES (new.enforcement_id, new.agency_name, new.action_summary, new.body_text_excerpt, new.respondent_name_anonymized);
END;

DROP VIEW IF EXISTS v_enforcement_municipality_public;
CREATE VIEW v_enforcement_municipality_public AS
SELECT
    enforcement_id, unified_id, municipality_code, prefecture_code,
    prefecture_name, municipality_name, agency_type, agency_name,
    action_type, action_date, action_period_start, action_period_end,
    respondent_name_anonymized, respondent_houjin_bangou,
    industry_jsic, body_text_excerpt, action_summary,
    source_url, source_host, license, ingested_at
FROM am_enforcement_municipality
WHERE redistribute_ok = 1;

CREATE TABLE IF NOT EXISTS am_enforcement_municipality_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source_kind     TEXT,
    pref_count      INTEGER NOT NULL DEFAULT 0,
    muni_count      INTEGER NOT NULL DEFAULT 0,
    rows_added      INTEGER NOT NULL DEFAULT 0,
    rows_updated    INTEGER NOT NULL DEFAULT 0,
    errors_count    INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_enmuni_run_log_started
    ON am_enforcement_municipality_run_log(started_at DESC);

COMMIT;
