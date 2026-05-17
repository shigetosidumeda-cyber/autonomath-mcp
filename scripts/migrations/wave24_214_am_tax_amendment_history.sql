-- target_db: autonomath
-- migration: wave24_214_am_tax_amendment_history
-- generated_at: 2026-05-17
-- author: AA1-G1 — 税制改正履歴 720 row backfill
-- idempotent: every CREATE uses IF NOT EXISTS; no DML in this DDL
--
-- Purpose
-- -------
-- Existing `am_amendment_snapshot` (14,596 rows) captures program-level
-- eligibility hashes but does NOT carry the canonical 税制改正 history
-- (i.e. annual 税制改正大綱 → 法律 → 政令 → 通達 chain). G1 cohort needs
-- year-by-year 税制改正 history for FY-window comparisons:
--   * 法人税 — 税率, 損金算入, 繰越欠損金 etc.
--   * 所得税 — 配偶者控除, 給与所得控除 etc.
--   * 消費税 — 税率, 軽減税率, インボイス制度
--   * 相続税 — 基礎控除, 税率, 小規模宅地等の特例
--   * 各税目 — 重要 (年度) 改正 marker
--
-- ~720 改正 rows expected (10 税目 × 30 年 × 平均 2.4 改正 / 年 = 720).
-- Sourced from 国税庁 "税制改正の概要" + 財務省 公表 一次資料.
--
-- Field semantics
-- ---------------
-- amendment_id          PK
-- fiscal_year           FY of 改正大綱 (e.g. 2024 = 令和6年度)
-- tax_kind              same enum family as am_nta_qa.tax_category
-- amendment_title       改正 title
-- amendment_summary     content (1-3 sentence)
-- effective_from        ISO date (施行日)
-- effective_to          ISO date (廃止 / 失効 if present)
-- statute_kind          'tax_law' | 'enforcement_order' | 'enforcement_regulation'
--                       | 'tsutatsu' | 'gaiyou'
-- statute_ref           '法人税法 §57-2' / '措置法 §42の4' / etc. (free text)
-- gazette_ref           官報 reference if known
-- source_url            primary nta.go.jp / mof.go.jp URL (UNIQUE)
-- license               'pdl_v1.0' (NTA) | 'gov_standard' (MOF 公表)
-- crawl_run_id          G1 manifest run id
-- ingested_at           ISO 8601 UTC
--
-- License posture
-- ---------------
-- 国税庁 + 財務省 公表 = pdl_v1.0 / gov_standard. No aggregator host
-- allowed. source_url verified primary.
--
-- NO LLM. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_tax_amendment_history (
    amendment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_year       INTEGER NOT NULL
                          CHECK (fiscal_year BETWEEN 1989 AND 2100),
    tax_kind          TEXT NOT NULL
                          CHECK (tax_kind IN (
                            'hojin',
                            'shotoku',
                            'shohi',
                            'sozoku',
                            'gensen',
                            'hyoka',
                            'inshi',
                            'hotei',
                            'joto',
                            'sonota'
                          )),
    amendment_title   TEXT NOT NULL,
    amendment_summary TEXT NOT NULL,
    effective_from    TEXT,
    effective_to      TEXT,
    statute_kind      TEXT NOT NULL
                          CHECK (statute_kind IN (
                            'tax_law',
                            'enforcement_order',
                            'enforcement_regulation',
                            'tsutatsu',
                            'gaiyou'
                          )),
    statute_ref       TEXT,
    gazette_ref       TEXT,
    source_url        TEXT NOT NULL UNIQUE,
    license           TEXT NOT NULL DEFAULT 'pdl_v1.0'
                          CHECK (license IN ('pdl_v1.0', 'gov_standard', 'public_domain_jp_gov')),
    crawl_run_id      TEXT NOT NULL DEFAULT 'etl_g1_nta_manifest_2026_05_17',
    ingested_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_am_tax_amendment_fy_tax
    ON am_tax_amendment_history(fiscal_year DESC, tax_kind);

CREATE INDEX IF NOT EXISTS ix_am_tax_amendment_effective
    ON am_tax_amendment_history(effective_from DESC, effective_to);

CREATE INDEX IF NOT EXISTS ix_am_tax_amendment_crawl_run
    ON am_tax_amendment_history(crawl_run_id, ingested_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_tax_amendment_statute
    ON am_tax_amendment_history(statute_kind, fiscal_year DESC);

-- FTS5 over amendment_title + amendment_summary + statute_ref
CREATE VIRTUAL TABLE IF NOT EXISTS am_tax_amendment_history_fts USING fts5(
    amendment_title, amendment_summary, statute_ref,
    content='am_tax_amendment_history', content_rowid='amendment_id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_tax_amendment_history_ai AFTER INSERT ON am_tax_amendment_history BEGIN
    INSERT INTO am_tax_amendment_history_fts(rowid, amendment_title, amendment_summary, statute_ref)
    VALUES (new.amendment_id, new.amendment_title, new.amendment_summary, new.statute_ref);
END;

CREATE TRIGGER IF NOT EXISTS am_tax_amendment_history_ad AFTER DELETE ON am_tax_amendment_history BEGIN
    INSERT INTO am_tax_amendment_history_fts(am_tax_amendment_history_fts, rowid, amendment_title, amendment_summary, statute_ref)
    VALUES ('delete', old.amendment_id, old.amendment_title, old.amendment_summary, old.statute_ref);
END;

CREATE TRIGGER IF NOT EXISTS am_tax_amendment_history_au AFTER UPDATE ON am_tax_amendment_history BEGIN
    INSERT INTO am_tax_amendment_history_fts(am_tax_amendment_history_fts, rowid, amendment_title, amendment_summary, statute_ref)
    VALUES ('delete', old.amendment_id, old.amendment_title, old.amendment_summary, old.statute_ref);
    INSERT INTO am_tax_amendment_history_fts(rowid, amendment_title, amendment_summary, statute_ref)
    VALUES (new.amendment_id, new.amendment_title, new.amendment_summary, new.statute_ref);
END;

CREATE VIEW IF NOT EXISTS v_am_tax_amendment_coverage AS
    SELECT
        fiscal_year,
        tax_kind,
        statute_kind,
        COUNT(*) AS amendment_count,
        MIN(effective_from) AS earliest_effective,
        MAX(effective_from) AS latest_effective
      FROM am_tax_amendment_history
     GROUP BY fiscal_year, tax_kind, statute_kind;
