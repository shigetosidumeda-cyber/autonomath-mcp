-- target_db: autonomath
-- migration 229_industry_guidelines
-- generated_at: 2026-05-12
-- author: Wave 32 Axis 1e (省庁業種ガイドライン corpus)
--
-- Purpose
-- -------
-- Captures sector-specific guideline documents published by each major
-- ministry. These are the prose / circular-letter substrate that bridges
-- statute (laws / enforcement) and program eligibility — e.g. MAFF's
-- 「農林水産業・食品産業の事業継続計画 (BCP) 策定ガイドライン」 or
-- METI's 「中小企業向け DX レポート 2.0」.
--
-- Coverage targets (primary sources only):
--   * env.go.jp   — 環境省
--   * maff.go.jp  — 農林水産省
--   * mhlw.go.jp  — 厚生労働省
--   * meti.go.jp  — 経済産業省
--   * mlit.go.jp  — 国土交通省
--   * mext.go.jp  — 文部科学省
--   * mof.go.jp   — 財務省 (税務系は nta_tsutatsu_extended に分離)
--   * mic.go.jp   — 総務省
--   * moj.go.jp   — 法務省
--   * mod.go.jp   — 防衛省
--
-- Each ministry's official guideline pages are scraped via its RSS feed
-- or sitemap (primary). NO aggregator URLs — same banned-host discipline
-- as scripts/ingest_external_data.BANNED_SOURCE_HOSTS.
--
-- Industry mapping = JSIC major (`am_industry_jsic.major_code`, 19 majors
-- A-T). Cross-corpus join enables agent queries like "what guidelines
-- apply to JSIC E (manufacturing) issued by METI?" and "show the 5 most
-- recent guidelines for JSIC F (construction)".
--
-- Idempotent / forward-only. Re-runs on each Fly boot are safe.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_industry_guidelines (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    guideline_id            TEXT NOT NULL UNIQUE,          -- 'GL-' + sha256(ministry|title)[:10]
    ministry                TEXT NOT NULL,                 -- 'env'|'maff'|'mhlw'|'meti'|'mlit'|'mext'|'mof'|'mic'|'moj'|'mod'
    industry_jsic_major     TEXT,                          -- 'A'..'T' or NULL = cross-industry
    industry_jsic_label     TEXT,                          -- '製造業' etc. (denormalized for surface display)
    title                   TEXT NOT NULL,
    body                    TEXT,                          -- abstract / first 2000 chars
    full_text_url           TEXT,                          -- official ministry HTML
    pdf_url                 TEXT,                          -- attached PDF if any
    issued_date             TEXT,                          -- ISO 8601 公表日
    last_revised            TEXT,                          -- ISO 8601 最終改訂日
    document_type           TEXT NOT NULL DEFAULT 'guideline', -- 'guideline'|'manual'|'circular'|'notice'
    source_url              TEXT NOT NULL,                 -- canonical (ministry domain only)
    license                 TEXT NOT NULL DEFAULT 'gov_standard',
    ingested_at             TEXT NOT NULL,
    last_verified           TEXT,
    CONSTRAINT ck_gl_ministry CHECK (ministry IN (
        'env','maff','mhlw','meti','mlit','mext','mof','mic','moj','mod','other'
    )),
    CONSTRAINT ck_gl_doc_type CHECK (document_type IN (
        'guideline','manual','circular','notice','q_and_a','other'
    ))
);

-- Spec'd index: (industry_jsic_major, last_revised DESC)
CREATE INDEX IF NOT EXISTS idx_am_industry_guidelines_jsic
    ON am_industry_guidelines(industry_jsic_major, last_revised DESC);

CREATE INDEX IF NOT EXISTS idx_am_industry_guidelines_ministry
    ON am_industry_guidelines(ministry, last_revised DESC);

CREATE INDEX IF NOT EXISTS idx_am_industry_guidelines_issued
    ON am_industry_guidelines(issued_date DESC);

-- FTS5 over title + body (trigram for partial kanji match).
CREATE VIRTUAL TABLE IF NOT EXISTS am_industry_guidelines_fts USING fts5(
    title, body,
    content='am_industry_guidelines', content_rowid='id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_ind_gl_ai
AFTER INSERT ON am_industry_guidelines BEGIN
    INSERT INTO am_industry_guidelines_fts(rowid, title, body)
    VALUES (new.id, new.title, new.body);
END;

CREATE TRIGGER IF NOT EXISTS am_ind_gl_ad
AFTER DELETE ON am_industry_guidelines BEGIN
    INSERT INTO am_industry_guidelines_fts(
        am_industry_guidelines_fts, rowid, title, body
    ) VALUES ('delete', old.id, old.title, old.body);
END;

CREATE TRIGGER IF NOT EXISTS am_ind_gl_au
AFTER UPDATE ON am_industry_guidelines BEGIN
    INSERT INTO am_industry_guidelines_fts(
        am_industry_guidelines_fts, rowid, title, body
    ) VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO am_industry_guidelines_fts(rowid, title, body)
    VALUES (new.id, new.title, new.body);
END;

-- Rollup by industry + ministry.
DROP VIEW IF EXISTS v_am_industry_guidelines_rollup;
CREATE VIEW v_am_industry_guidelines_rollup AS
SELECT
    industry_jsic_major,
    ministry,
    COUNT(*)                                      AS guideline_count,
    MAX(last_revised)                             AS latest_revision,
    MIN(issued_date)                              AS earliest_issued
FROM am_industry_guidelines
GROUP BY industry_jsic_major, ministry;
