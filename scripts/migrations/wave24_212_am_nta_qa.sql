-- target_db: autonomath
-- migration: wave24_212_am_nta_qa
-- generated_at: 2026-05-17
-- author: AA1-G1 NTA tax-advisor cohort ETL — 質疑応答 7 category expansion
-- idempotent: every CREATE uses IF NOT EXISTS; no DML in this DDL
--
-- Purpose
-- -------
-- The base 質疑応答 / 文書回答 tables `nta_shitsugi` + `nta_bunsho_kaitou`
-- (migration 103) cover the existing 286 + 278 rows. The G1 task expands
-- coverage to ~2,150 質疑応答 across 7 canonical categories (法人 / 消費 /
-- 相続 / 評価 / 印紙 / 法定 / 譲渡 / 所得 / 源泉) — but does so via an
-- additive helper table `am_nta_qa` that:
--
-- 1. carries the canonical 7-category enum (vs. the legacy slug-based
--    category column in `nta_shitsugi`)
-- 2. dual-keys both 質疑応答 (shitsugi) and 文書回答 (bunsho) under a
--    common `qa_kind` so the MCP cohort tool can fan-out one walk per
--    cohort.
-- 3. carries a `crawl_run_id` for provenance back to the G1 manifest
--    `etl_g1_nta_manifest_2026_05_17.json` + s3 staging prefix.
--
-- Field semantics
-- ---------------
-- am_qa_id           PK
-- qa_kind            'shitsugi' (質疑応答) | 'bunsho' (文書回答事例)
-- tax_category       canonical 7-cat enum (hojin / shohi / sozoku / hyoka /
--                                          inshi / hotei / joto / shotoku / gensen)
-- slug               URL-derived stable id
-- question           【照会要旨】 / 【照会の趣旨】
-- answer             【回答要旨】 / 【回答の内容】
-- related_law        【関係法令通達】 (free text)
-- decision_date      ISO date if parseable (bunsho only — shitsugi rarely dated)
-- source_url         canonical NTA URL (UNIQUE — prevents dup)
-- license            'pdl_v1.0' (NTA bulk PDL-licensed)
-- crawl_run_id       G1 manifest run id (etl_g1_nta_manifest_2026_05_17)
-- ingested_at        ISO 8601 UTC
--
-- License posture
-- ---------------
-- All rows are PDL v1.0 (国税庁公開資料). source_url verified primary
-- (nta.go.jp host only). Aggregator hosts (zeiken / tabisland / freee
-- articles) rejected at crawl time by allowlist.
--
-- NO LLM. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_nta_qa (
    am_qa_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    qa_kind           TEXT NOT NULL
                          CHECK (qa_kind IN ('shitsugi', 'bunsho')),
    tax_category      TEXT NOT NULL
                          CHECK (tax_category IN (
                            'hojin',
                            'shohi',
                            'sozoku',
                            'hyoka',
                            'inshi',
                            'hotei',
                            'joto',
                            'shotoku',
                            'gensen'
                          )),
    slug              TEXT NOT NULL,
    question          TEXT NOT NULL,
    answer            TEXT NOT NULL,
    related_law       TEXT,
    decision_date     TEXT,
    source_url        TEXT NOT NULL UNIQUE,
    license           TEXT NOT NULL DEFAULT 'pdl_v1.0'
                          CHECK (license IN ('pdl_v1.0', 'gov_standard', 'public_domain_jp_gov')),
    crawl_run_id      TEXT NOT NULL DEFAULT 'etl_g1_nta_manifest_2026_05_17',
    ingested_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (qa_kind, tax_category, slug)
);

CREATE INDEX IF NOT EXISTS ix_am_nta_qa_kind_category
    ON am_nta_qa(qa_kind, tax_category);

CREATE INDEX IF NOT EXISTS ix_am_nta_qa_category_date
    ON am_nta_qa(tax_category, decision_date DESC);

CREATE INDEX IF NOT EXISTS ix_am_nta_qa_crawl_run
    ON am_nta_qa(crawl_run_id, ingested_at DESC);

-- FTS5 over question + answer + related_law
CREATE VIRTUAL TABLE IF NOT EXISTS am_nta_qa_fts USING fts5(
    question, answer, related_law,
    content='am_nta_qa', content_rowid='am_qa_id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_nta_qa_ai AFTER INSERT ON am_nta_qa BEGIN
    INSERT INTO am_nta_qa_fts(rowid, question, answer, related_law)
    VALUES (new.am_qa_id, new.question, new.answer, new.related_law);
END;

CREATE TRIGGER IF NOT EXISTS am_nta_qa_ad AFTER DELETE ON am_nta_qa BEGIN
    INSERT INTO am_nta_qa_fts(am_nta_qa_fts, rowid, question, answer, related_law)
    VALUES ('delete', old.am_qa_id, old.question, old.answer, old.related_law);
END;

CREATE TRIGGER IF NOT EXISTS am_nta_qa_au AFTER UPDATE ON am_nta_qa BEGIN
    INSERT INTO am_nta_qa_fts(am_nta_qa_fts, rowid, question, answer, related_law)
    VALUES ('delete', old.am_qa_id, old.question, old.answer, old.related_law);
    INSERT INTO am_nta_qa_fts(rowid, question, answer, related_law)
    VALUES (new.am_qa_id, new.question, new.answer, new.related_law);
END;

-- Convenience view: per-category aggregate (MCP cohort tool / coverage probe).
CREATE VIEW IF NOT EXISTS v_am_nta_qa_coverage AS
    SELECT
        qa_kind,
        tax_category,
        COUNT(*) AS qa_count,
        MIN(ingested_at) AS earliest_ingested,
        MAX(ingested_at) AS latest_ingested
      FROM am_nta_qa
     GROUP BY qa_kind, tax_category;
