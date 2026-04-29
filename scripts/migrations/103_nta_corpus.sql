-- target_db: autonomath
-- migration 103_nta_corpus
--
-- NTA / 国税不服審判所 primary-source corpus tables.
--
-- Surfaces 4 datasets the customer LLMs need for tax research:
--   * nta_saiketsu        — 国税不服審判所 公表裁決事例 (kfs.go.jp/service/JP/...)
--   * nta_tsutatsu_index  — 通達 article index (mirrors am_law_article tsutatsu rows
--                            with normalized search shape; the bulk text already lives
--                            in am_law_article via scripts/ingest/ingest_tsutatsu_nta.py)
--   * nta_shitsugi        — 国税庁 質疑応答事例 (nta.go.jp/law/shitsugi/...)
--   * nta_bunsho_kaitou   — 国税庁 文書回答事例 (nta.go.jp/law/bunshokaito/...)
--
-- All sourced from PUBLIC government sites under government-standard
-- terms (PDL v1.0 / ministry standard). Every row carries source_url so
-- the §52 envelope on the MCP tools can cite primary source verbatim.
--
-- Forward-only / idempotent. Re-running on each Fly boot is safe because
-- every CREATE uses IF NOT EXISTS. No ALTER COLUMN. License is fixed at
-- 'gov_standard' on every row (NTA pages carry the standard 利用規約 —
-- no aggregator content).
--
-- The 4 MCP tools that read these tables are gated behind
-- AUTONOMATH_NTA_CORPUS_ENABLED (default ON) and emit `_disclaimer`
-- declaring output is citation-only retrieval, not 税務助言 (税理士法 §52).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. nta_saiketsu — 国税不服審判所 公表裁決事例
-- ---------------------------------------------------------------------------
-- Volume index runs from 43 (S60) to current (R7+). One row per published
-- decision. case_no within volume identifies the section (01..NN).
-- decision_date is the actual ruling date (parsed from page <h1>).
-- tax_type is the major head (所得税 / 法人税 / 消費税 / 相続税 / 国税通則 / etc.).

CREATE TABLE IF NOT EXISTS nta_saiketsu (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_no           INTEGER NOT NULL,        -- 43 .. 140 (集 number)
    case_no             TEXT NOT NULL,           -- '01' .. 'NN' within volume
    decision_date       TEXT,                    -- ISO 'YYYY-MM-DD' parsed from page header
    fiscal_period       TEXT,                    -- '令和3年1月分から3月分' raw label
    tax_type            TEXT,                    -- '所得税' / '法人税' / '消費税' / '相続税' / '国税通則' / etc.
    title               TEXT,                    -- decision title / 争点
    decision_summary    TEXT,                    -- 要旨 (first paragraph)
    fulltext            TEXT,                    -- full body text (cleaned)
    source_url          TEXT NOT NULL UNIQUE,    -- canonical kfs.go.jp URL
    license             TEXT NOT NULL DEFAULT 'gov_standard',
    ingested_at         TEXT NOT NULL,           -- ISO-8601 UTC
    UNIQUE (volume_no, case_no)
);

CREATE INDEX IF NOT EXISTS idx_nta_saiketsu_volume
    ON nta_saiketsu(volume_no, case_no);

CREATE INDEX IF NOT EXISTS idx_nta_saiketsu_tax_type
    ON nta_saiketsu(tax_type, decision_date DESC);

CREATE INDEX IF NOT EXISTS idx_nta_saiketsu_decision_date
    ON nta_saiketsu(decision_date DESC);

-- FTS5 over title + summary + fulltext (trigram for partial kanji matches)
CREATE VIRTUAL TABLE IF NOT EXISTS nta_saiketsu_fts USING fts5(
    title, decision_summary, fulltext,
    content='nta_saiketsu', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS nta_saiketsu_ai AFTER INSERT ON nta_saiketsu BEGIN
    INSERT INTO nta_saiketsu_fts(rowid, title, decision_summary, fulltext)
    VALUES (new.id, new.title, new.decision_summary, new.fulltext);
END;

CREATE TRIGGER IF NOT EXISTS nta_saiketsu_ad AFTER DELETE ON nta_saiketsu BEGIN
    INSERT INTO nta_saiketsu_fts(nta_saiketsu_fts, rowid, title, decision_summary, fulltext)
    VALUES ('delete', old.id, old.title, old.decision_summary, old.fulltext);
END;

CREATE TRIGGER IF NOT EXISTS nta_saiketsu_au AFTER UPDATE ON nta_saiketsu BEGIN
    INSERT INTO nta_saiketsu_fts(nta_saiketsu_fts, rowid, title, decision_summary, fulltext)
    VALUES ('delete', old.id, old.title, old.decision_summary, old.fulltext);
    INSERT INTO nta_saiketsu_fts(rowid, title, decision_summary, fulltext)
    VALUES (new.id, new.title, new.decision_summary, new.fulltext);
END;

-- ---------------------------------------------------------------------------
-- 2. nta_shitsugi — 国税庁 質疑応答事例
-- ---------------------------------------------------------------------------
-- Categorized by tax law (shotoku / hojin / shohi / sozoku / hyoka / etc.).
-- One row per Q/A pair. slug = stable identifier (URL filename minus .htm).

CREATE TABLE IF NOT EXISTS nta_shitsugi (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL,           -- e.g. 'shotoku-12-3'
    category        TEXT NOT NULL,           -- 'shotoku' / 'hojin' / 'shohi' / 'sozoku' / 'hyoka' / 'inshi' / 'hotei' / 'gensen' / 'joto'
    question        TEXT NOT NULL,           -- 【照会要旨】
    answer          TEXT NOT NULL,           -- 【回答要旨】
    related_law     TEXT,                    -- 【関係法令通達】 (free text — multiple law refs)
    source_url      TEXT NOT NULL UNIQUE,
    license         TEXT NOT NULL DEFAULT 'gov_standard',
    ingested_at     TEXT NOT NULL,
    UNIQUE (category, slug)
);

CREATE INDEX IF NOT EXISTS idx_nta_shitsugi_category
    ON nta_shitsugi(category, slug);

CREATE VIRTUAL TABLE IF NOT EXISTS nta_shitsugi_fts USING fts5(
    question, answer, related_law,
    content='nta_shitsugi', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS nta_shitsugi_ai AFTER INSERT ON nta_shitsugi BEGIN
    INSERT INTO nta_shitsugi_fts(rowid, question, answer, related_law)
    VALUES (new.id, new.question, new.answer, new.related_law);
END;

CREATE TRIGGER IF NOT EXISTS nta_shitsugi_ad AFTER DELETE ON nta_shitsugi BEGIN
    INSERT INTO nta_shitsugi_fts(nta_shitsugi_fts, rowid, question, answer, related_law)
    VALUES ('delete', old.id, old.question, old.answer, old.related_law);
END;

CREATE TRIGGER IF NOT EXISTS nta_shitsugi_au AFTER UPDATE ON nta_shitsugi BEGIN
    INSERT INTO nta_shitsugi_fts(nta_shitsugi_fts, rowid, question, answer, related_law)
    VALUES ('delete', old.id, old.question, old.answer, old.related_law);
    INSERT INTO nta_shitsugi_fts(rowid, question, answer, related_law)
    VALUES (new.id, new.question, new.answer, new.related_law);
END;

-- ---------------------------------------------------------------------------
-- 3. nta_bunsho_kaitou — 国税庁 文書回答事例
-- ---------------------------------------------------------------------------
-- 1,200ish published 文書回答. Each is a formal pre-ruling letter response.
-- date = response date (when NTA replied). request_summary = inquiry topic.

CREATE TABLE IF NOT EXISTS nta_bunsho_kaitou (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                TEXT NOT NULL,           -- URL-derived stable id
    category            TEXT NOT NULL,           -- 'shotoku' / 'hojin' / 'shohi' / 'sozoku' / etc.
    response_date       TEXT,                    -- ISO 'YYYY-MM-DD' if parsable
    request_summary     TEXT,                    -- 【照会の趣旨】
    answer              TEXT,                    -- 【回答の内容】
    source_url          TEXT NOT NULL UNIQUE,
    license             TEXT NOT NULL DEFAULT 'gov_standard',
    ingested_at         TEXT NOT NULL,
    UNIQUE (category, slug)
);

CREATE INDEX IF NOT EXISTS idx_nta_bunsho_category
    ON nta_bunsho_kaitou(category, response_date DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS nta_bunsho_kaitou_fts USING fts5(
    request_summary, answer,
    content='nta_bunsho_kaitou', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS nta_bunsho_kaitou_ai AFTER INSERT ON nta_bunsho_kaitou BEGIN
    INSERT INTO nta_bunsho_kaitou_fts(rowid, request_summary, answer)
    VALUES (new.id, new.request_summary, new.answer);
END;

CREATE TRIGGER IF NOT EXISTS nta_bunsho_kaitou_ad AFTER DELETE ON nta_bunsho_kaitou BEGIN
    INSERT INTO nta_bunsho_kaitou_fts(nta_bunsho_kaitou_fts, rowid, request_summary, answer)
    VALUES ('delete', old.id, old.request_summary, old.answer);
END;

CREATE TRIGGER IF NOT EXISTS nta_bunsho_kaitou_au AFTER UPDATE ON nta_bunsho_kaitou BEGIN
    INSERT INTO nta_bunsho_kaitou_fts(nta_bunsho_kaitou_fts, rowid, request_summary, answer)
    VALUES ('delete', old.id, old.request_summary, old.answer);
    INSERT INTO nta_bunsho_kaitou_fts(rowid, request_summary, answer)
    VALUES (new.id, new.request_summary, new.answer);
END;

-- ---------------------------------------------------------------------------
-- 4. nta_tsutatsu_index — projection over am_law_article tsutatsu rows
-- ---------------------------------------------------------------------------
-- Lookup table for cite_tsutatsu(code). The bulk article body lives in
-- am_law_article via scripts/ingest/ingest_tsutatsu_nta.py. This index
-- gives the MCP tool a fast key→{law_id, article_number, source_url}
-- map keyed by user-friendly code (e.g. '法基通-9-2-3', '所基通-36-1').
--
-- Populated by scripts/cron/index_nta_tsutatsu.py from existing
-- am_law_article rows where article_kind='tsutatsu'. Operator-managed
-- aliases (parent_code) trace 旧通達 → 新通達 numbering changes.

CREATE TABLE IF NOT EXISTS nta_tsutatsu_index (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    code                    TEXT NOT NULL UNIQUE,    -- '法基通-9-2-3' / '所基通-36-1' / '消基通-5-1-1' / '相基通-13-2'
    law_canonical_id        TEXT NOT NULL,           -- 'law:hojin-zei-tsutatsu' etc.
    article_number          TEXT NOT NULL,           -- '9-2-3'
    title                   TEXT,
    body_excerpt            TEXT,                    -- first 500 chars of am_law_article.text_full
    parent_code             TEXT,                    -- predecessor code if renumbered
    source_url              TEXT NOT NULL,
    last_amended            TEXT,                    -- if known
    refreshed_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nta_tsutatsu_index_law
    ON nta_tsutatsu_index(law_canonical_id, article_number);

CREATE INDEX IF NOT EXISTS idx_nta_tsutatsu_index_parent
    ON nta_tsutatsu_index(parent_code);

-- ---------------------------------------------------------------------------
-- Migration bookkeeping
-- ---------------------------------------------------------------------------
-- Operator (Bookyou株式会社, T8010001213708) acknowledges:
--   * All 4 datasets are PUBLIC government documents under PDL v1.0 / 国税庁
--     利用規約. source_url + license columns are mandatory on every row.
--   * MCP tools surface citations only — output declares `_disclaimer`
--     citing 税理士法 §52 and refusing 税務助言.
--   * No aggregator content (zeiken.jp / 税大論叢 mirrors / etc.) lands
--     in these tables. NTA / 国税不服審判所 primary URLs only.
