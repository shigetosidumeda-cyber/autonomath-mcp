-- target_db: autonomath
-- migration 230_nta_tsutatsu_extended
-- generated_at: 2026-05-12
-- author: Wave 32 Axis 1f (国税庁 通達 full-body + section breakdown)
--
-- Purpose
-- -------
-- Extends the existing `nta_tsutatsu_index` (migration 103, 3,232 rows
-- live as of 2026-05-12) with section-level breakdown + full body text +
-- tax-law article join.
--
-- Existing 103 index stores only `body_excerpt` (first 500 chars). For
-- agent queries that need "show me the full text of 法基通-9-2-3 and the
-- specific section addressing 損金不算入" we need:
--
--   * section_id        — 9-2-3-1, 9-2-3-2, ... within a tsutatsu
--   * parent_tsutatsu_id — backlink to nta_tsutatsu_index.id
--   * body_text         — full section body (uncapped)
--   * applicable_tax_law_id — FK → am_law_article (税理士法/法人税法/...)
--
-- Source: NTA 通達 web (https://www.nta.go.jp/law/tsutatsu/) — primary
-- only. Each tsutatsu page is parsed for its section anchors (<a name="...">)
-- and split row-per-section. 3,232 → 10,000+ rows after section expansion
-- (avg 3 sections per tsutatsu).
--
-- Idempotent / forward-only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_nta_tsutatsu_extended (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id                  TEXT NOT NULL UNIQUE,          -- '法基通-9-2-3-1' / '所基通-36-1-2' etc.
    parent_tsutatsu_id          INTEGER,                       -- FK nta_tsutatsu_index.id (NULL = top-level)
    parent_code                 TEXT,                          -- '法基通-9-2-3' etc.
    law_canonical_id            TEXT,                          -- 'law:hojin-zei-tsutatsu' / 'law:shotoku-zei-tsutatsu' / ...
    applicable_tax_law_id       TEXT,                          -- FK am_law_article.law_canonical_id (法人税法 article level)
    article_number              TEXT,                          -- '9-2-3-1'
    section_number              TEXT,                          -- '1' (just the leaf section)
    title                       TEXT,
    body_text                   TEXT,                          -- full section body (NOT excerpt)
    cross_references_json       TEXT NOT NULL DEFAULT '[]',    -- JSON list[str] of section_ids referenced
    source_url                  TEXT NOT NULL,
    last_amended                TEXT,
    ingested_at                 TEXT NOT NULL,
    last_verified               TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_nta_tsutatsu_ext_parent
    ON am_nta_tsutatsu_extended(parent_tsutatsu_id);

CREATE INDEX IF NOT EXISTS idx_am_nta_tsutatsu_ext_parent_code
    ON am_nta_tsutatsu_extended(parent_code, article_number);

CREATE INDEX IF NOT EXISTS idx_am_nta_tsutatsu_ext_law_join
    ON am_nta_tsutatsu_extended(applicable_tax_law_id);

CREATE INDEX IF NOT EXISTS idx_am_nta_tsutatsu_ext_canonical
    ON am_nta_tsutatsu_extended(law_canonical_id, article_number);

-- FTS5 over title + body_text (trigram for partial kanji match).
CREATE VIRTUAL TABLE IF NOT EXISTS am_nta_tsutatsu_extended_fts USING fts5(
    title, body_text,
    content='am_nta_tsutatsu_extended', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_nta_ts_ext_ai
AFTER INSERT ON am_nta_tsutatsu_extended BEGIN
    INSERT INTO am_nta_tsutatsu_extended_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS am_nta_ts_ext_ad
AFTER DELETE ON am_nta_tsutatsu_extended BEGIN
    INSERT INTO am_nta_tsutatsu_extended_fts(
        am_nta_tsutatsu_extended_fts, rowid, title, body_text
    ) VALUES ('delete', old.id, old.title, old.body_text);
END;

CREATE TRIGGER IF NOT EXISTS am_nta_ts_ext_au
AFTER UPDATE ON am_nta_tsutatsu_extended BEGIN
    INSERT INTO am_nta_tsutatsu_extended_fts(
        am_nta_tsutatsu_extended_fts, rowid, title, body_text
    ) VALUES ('delete', old.id, old.title, old.body_text);
    INSERT INTO am_nta_tsutatsu_extended_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;

-- View: section list for a given parent tsutatsu code (used by REST
-- /v1/nta/tsutatsu/{tsutatsu_id}/sections).
DROP VIEW IF EXISTS v_am_nta_tsutatsu_sections;
CREATE VIEW v_am_nta_tsutatsu_sections AS
SELECT
    parent_code,
    section_id,
    article_number,
    section_number,
    title,
    body_text,
    applicable_tax_law_id,
    source_url
FROM am_nta_tsutatsu_extended
ORDER BY parent_code, article_number;
