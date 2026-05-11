-- target_db: autonomath
-- migration 228_court_decisions_extended
-- generated_at: 2026-05-12
-- author: Wave 32 Axis 1d (judicial corpus 20k+ extension)
--
-- Purpose
-- -------
-- Extends the jpintel-side `court_decisions` table (migration 016, 2,065
-- rows live as of 2026-05-07 snapshot) with an autonomath-side mirror +
-- enrichment layer for the 20,000+ scale ingest from:
--
--   1. 裁判所判例検索 (courts.go.jp /app/hanrei_jp/) — primary source.
--      Already whitelisted in `BANNED_SOURCE_HOSTS`-compatible discipline.
--   2. 国立国会図書館 (dl.ndl.go.jp OAI-PMH) — supplementary primary
--      source for older 明治-平成 期 rulings not on courts.go.jp.
--
-- 旧 016 court_decisions is the canonical store on jpintel.db (operator
-- API surface). This new table `am_court_decisions_extended` lives on
-- autonomath.db (record_kind='court_decision' under am_entities) and
-- carries the enrichment layer:
--
--   * court_level (最高裁/高裁/地裁/簡裁/家裁) — already on 016 but mirrored
--   * case_type (税務/行政/会社/知財/労働/民事一般/刑事/その他) — NEW
--   * decision_date_range (start/end ISO date pair) — NEW for range queries
--   * related_law_ids_json (FK → laws.law_id list) — mirrored from 016
--   * related_program_ids_json (FK → programs.pid list) — NEW cross-corpus
--
-- Cross-corpus join with autonomath programs (8,203 program entities) +
-- jpi_law (mirrored 9,484 laws stub) enables agent queries like
-- "this program X has been litigated in 47 rulings, here are the binding
-- ones with their statute chains".
--
-- License posture
-- ---------------
-- * courts.go.jp pages: gov_standard (PDL v1.0 ministry).
-- * NDL OAI-PMH: gov_standard with NDL attribution on derivative use.
-- Both legally allow API redistribution under primary-source citation.
--
-- D1 Law / Westlaw Japan / LEX/DB / 判例秘書 / TKC LEX/DB / 判例検索ロー
-- ライブラリ 等の commercial aggregators are **banned** (license + 再配布
-- blocks + no primary cite). Same `BANNED_SOURCE_HOSTS` discipline as
-- scripts/ingest_external_data.py applies on every INSERT path.
--
-- Idempotent / forward-only. Re-runs on each Fly boot are safe.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_court_decisions_extended (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    unified_id                  TEXT NOT NULL UNIQUE,           -- 'HAN-' + sha256(case_number|court)[:10]
    case_number                 TEXT,                            -- 平成29年(行ヒ)第123号
    court                       TEXT,                            -- 東京地方裁判所 etc.
    court_level                 TEXT NOT NULL,                   -- 'supreme'|'high'|'district'|'summary'|'family'
    case_type                   TEXT NOT NULL DEFAULT 'other',   -- 'tax'|'admin'|'corporate'|'ip'|'labor'|'civil'|'criminal'|'other'
    case_name                   TEXT,                            -- 事件名
    decision_date               TEXT,                            -- ISO 8601 言渡日
    decision_date_start         TEXT,                            -- range query start
    decision_date_end           TEXT,                            -- range query end
    decision_type               TEXT,                            -- '判決'|'決定'|'命令'
    subject_area                TEXT,                            -- '租税'|'行政'|'補助金適正化法' etc.
    related_law_ids_json        TEXT NOT NULL DEFAULT '[]',      -- JSON list[str]
    related_program_ids_json    TEXT NOT NULL DEFAULT '[]',      -- JSON list[str] (program.pid)
    key_ruling                  TEXT,                            -- 判示事項 要約
    full_text_url               TEXT,                            -- courts.go.jp hanrei_jp permalink
    pdf_url                     TEXT,                            -- PDF mirror
    source_url                  TEXT NOT NULL,                   -- primary (courts.go.jp or dl.ndl.go.jp)
    source                      TEXT NOT NULL DEFAULT 'courts_jp', -- 'courts_jp'|'ndl_oai'
    license                     TEXT NOT NULL DEFAULT 'gov_standard',
    ingested_at                 TEXT NOT NULL,                   -- ISO 8601 UTC
    last_verified               TEXT,
    CONSTRAINT ck_ext_court_level CHECK (court_level IN (
        'supreme','high','district','summary','family'
    )),
    CONSTRAINT ck_ext_case_type CHECK (case_type IN (
        'tax','admin','corporate','ip','labor','civil','criminal','other'
    )),
    CONSTRAINT ck_ext_source CHECK (source IN ('courts_jp','ndl_oai'))
);

CREATE INDEX IF NOT EXISTS idx_am_court_ext_unified
    ON am_court_decisions_extended(unified_id);

CREATE INDEX IF NOT EXISTS idx_am_court_ext_level_type
    ON am_court_decisions_extended(court_level, case_type, decision_date DESC);

CREATE INDEX IF NOT EXISTS idx_am_court_ext_case_type
    ON am_court_decisions_extended(case_type, decision_date DESC);

CREATE INDEX IF NOT EXISTS idx_am_court_ext_date_range
    ON am_court_decisions_extended(decision_date_start, decision_date_end);

CREATE INDEX IF NOT EXISTS idx_am_court_ext_source
    ON am_court_decisions_extended(source, ingested_at DESC);

-- FTS5 over case_name + key_ruling (trigram for partial kanji match).
CREATE VIRTUAL TABLE IF NOT EXISTS am_court_decisions_extended_fts USING fts5(
    case_name, key_ruling, subject_area,
    content='am_court_decisions_extended', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_court_ext_ai
AFTER INSERT ON am_court_decisions_extended BEGIN
    INSERT INTO am_court_decisions_extended_fts(rowid, case_name, key_ruling, subject_area)
    VALUES (new.id, new.case_name, new.key_ruling, new.subject_area);
END;

CREATE TRIGGER IF NOT EXISTS am_court_ext_ad
AFTER DELETE ON am_court_decisions_extended BEGIN
    INSERT INTO am_court_decisions_extended_fts(
        am_court_decisions_extended_fts, rowid, case_name, key_ruling, subject_area
    ) VALUES ('delete', old.id, old.case_name, old.key_ruling, old.subject_area);
END;

CREATE TRIGGER IF NOT EXISTS am_court_ext_au
AFTER UPDATE ON am_court_decisions_extended BEGIN
    INSERT INTO am_court_decisions_extended_fts(
        am_court_decisions_extended_fts, rowid, case_name, key_ruling, subject_area
    ) VALUES ('delete', old.id, old.case_name, old.key_ruling, old.subject_area);
    INSERT INTO am_court_decisions_extended_fts(rowid, case_name, key_ruling, subject_area)
    VALUES (new.id, new.case_name, new.key_ruling, new.subject_area);
END;

-- View: cross-source rollup (joins with mirrored jpi_court_decisions on
-- unified_id so callers can prefer 016 row when present, fall back to
-- extended row when the 016 catalog has not seen this case_number yet).
DROP VIEW IF EXISTS v_am_court_decisions_unified;
CREATE VIEW v_am_court_decisions_unified AS
SELECT
    ext.unified_id              AS unified_id,
    ext.case_number             AS case_number,
    ext.court                   AS court,
    ext.court_level             AS court_level,
    ext.case_type               AS case_type,
    ext.case_name               AS case_name,
    ext.decision_date           AS decision_date,
    ext.decision_type           AS decision_type,
    ext.subject_area            AS subject_area,
    ext.related_law_ids_json    AS related_law_ids_json,
    ext.related_program_ids_json AS related_program_ids_json,
    ext.key_ruling              AS key_ruling,
    ext.full_text_url           AS full_text_url,
    ext.source_url              AS source_url,
    ext.source                  AS source,
    ext.license                 AS license,
    ext.ingested_at             AS ingested_at
FROM am_court_decisions_extended AS ext;
