-- target_db: autonomath
-- migration: wave24_217_am_municipality_subsidy
-- generated_at: 2026-05-17
-- author: DD2 Geo-expansion lane (municipality 1,718 補助金 PDF + Textract OCR)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML
--
-- Purpose
-- -------
-- DD2 unblocks the G3 / G4 / G5 audit fan-out gap (18 / 30 自治体 differential
-- fan-out required) by landing the structured 1,718 市町村 補助金 corpus.
-- This is the OCR-derived **structured extraction** layer that sits on top of:
--
--   * ``municipality_subsidy`` (wave24_191, target_db=jpintel) — 1st-pass 67
--     自治体 page diff cron. Stores raw HTML + sha256 only (no structured
--     amount / deadline extraction).
--   * ``am_window_directory`` (wave24_203, target_db=autonomath, lane N4) —
--     1,885 市町村 + 837 商工会議所 + 901 商工会 + 47 都道府県 windows.
--
-- DD2 adds a sibling table ``am_municipality_subsidy`` on autonomath (target
-- DB for am_* family) that stores **post-OCR structured fields**: amount_yen,
-- deadline, target_jsic_majors, target_corporate_forms, target_region_codes,
-- requirement_text, source_pdf_s3_uri, ocr_job_id.
--
-- 1st-pass scope
-- --------------
--   * 1,718 市町村 covered by DD2 crawl manifest
--     (data/etl_dd2_municipality_manifest_2026_05_17.json).
--   * ~3-5 補助金 PDF per municipality (avg 3.5 = ~6,000 PDF target).
--   * Each PDF → Textract AnalyzeDocument (TABLES + FORMS) → structured row.
--   * Cost ceiling: $4,500 worst case (6,000 PDF × 15 page × $0.05).
--
-- target_db = autonomath
-- ----------------------
-- This table is co-located with the am_* program / placeholder / window
-- family so that downstream JOIN queries (am_municipality_subsidy
-- ⋈ am_window_directory ⋈ am_region ⋈ am_program) stay in one DB —
-- the cross-DB ATTACH is explicitly forbidden by CLAUDE.md.
--
-- Idempotency contract
-- --------------------
--   * ``CREATE TABLE IF NOT EXISTS`` — existing rows preserved on re-apply.
--   * All indexes are ``CREATE INDEX IF NOT EXISTS``.
--   * Convenience views are ``CREATE VIEW IF NOT EXISTS``.
--   * No DML — bulk load is handled by
--     ``scripts/etl/crawl_municipality_subsidy_2026_05_17.py`` +
--     ``scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py``.
--
-- LLM call: 0. Pure SQLite DDL. Downstream loaders are regex + 国税庁用語辞典.
--
-- License posture
-- ---------------
-- 自治体公式サイトは §13 著作権法 上 政府著作物 — 編集 / 翻案 / 再配信 原則自由。
-- 個別 row の license カラムは upstream PDF host から推論
-- (city.*.lg.jp / pref.*.lg.jp / metro.tokyo.lg.jp → public_domain_jp_gov;
-- 商工会議所 jcci → cc_by_4.0; その他 fallback → gov_standard).
--
-- aggregator host (noukaweb / hojyokin-portal / biz.stayway / stayway.jp /
-- subsidies-japan / jgrant-aggregator) は ingest 段階で弾かれる
-- (DD2 crawler PRIMARY_HOST_REGEX + AGGREGATOR_HOST_BLACKLIST).
--
-- Field semantics
-- ---------------
-- subsidy_id              INTEGER PK AUTOINCREMENT
-- municipality_code       TEXT NOT NULL — J-LIS 全国地方公共団体コード 5-digit
--                                         (e.g. '01202' 函館市, '13104' 新宿区).
-- prefecture              TEXT NOT NULL — 都道府県名 (e.g. '北海道', '東京都')
-- municipality_name       TEXT NOT NULL — 自治体名 (e.g. '函館市', '新宿区')
-- municipality_type       TEXT NOT NULL CHECK enum
--                                         (prefecture/seirei/chukaku/special/regular)
-- program_name            TEXT NOT NULL — 補助金名 (Textract heading 抽出)
-- amount_yen_max          INTEGER — 補助金額上限 (円 単位 integer)
-- amount_yen_min          INTEGER — 補助金額下限 (円 単位 integer)
-- subsidy_rate            REAL — 補助率 (0.0..1.0, fallback NULL)
-- deadline                TEXT — 締切 ISO 8601 date (YYYY-MM-DD), NULL if rolling
-- target_jsic_majors      TEXT — JSON array of JSIC major-code strings (e.g.
--                                ["F","G"]). NULL if 全業種 / 不明.
-- target_corporate_forms  TEXT — JSON array of corporate form codes (e.g.
--                                ["kabushiki","godo","yugen","ippan_shadan",
--                                 "ippan_zaidan","kojin_jigyou"]). NULL if 全形態.
-- target_region_codes     TEXT — JSON array of region_code (e.g. ['13104'])
-- requirement_text        TEXT — 申請要件 free-text (full OCR paragraph fallback)
-- contact_window_id       TEXT — am_window_directory.window_id (申請窓口)
-- source_url              TEXT NOT NULL — 募集要項 PDF / page URL (1次資料)
-- source_pdf_s3_uri       TEXT — s3://...derived/municipality_pdf_raw/<key>
-- ocr_s3_uri              TEXT — s3://...derived/municipality_ocr/<key>.json
-- ocr_job_id              TEXT — Textract JobId for traceability
-- ocr_confidence          REAL — Textract block-level mean confidence (0..1)
-- ocr_page_count          INTEGER — pages OCR'd (cost-tracking)
-- sha256                  TEXT NOT NULL — PDF body hash for re-fetch dedup
-- fetched_at              TEXT NOT NULL — ISO 8601 UTC
-- ingested_at             TEXT NOT NULL — Textract result ingestion timestamp
-- license                 TEXT NOT NULL DEFAULT 'public_domain_jp_gov'
-- license_source          TEXT — heuristic source for license value
-- created_at              TEXT NOT NULL
-- updated_at              TEXT NOT NULL

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_municipality_subsidy — DD2 1,718 市町村 補助金 post-OCR structured corpus
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_municipality_subsidy (
    subsidy_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_code       TEXT NOT NULL,
    prefecture              TEXT NOT NULL,
    municipality_name       TEXT NOT NULL,
    municipality_type       TEXT NOT NULL CHECK (municipality_type IN
                              ('prefecture','seirei','chukaku','special','regular')),
    program_name            TEXT NOT NULL,
    amount_yen_max          INTEGER,
    amount_yen_min          INTEGER,
    subsidy_rate            REAL,
    deadline                TEXT,
    target_jsic_majors      TEXT,
    target_corporate_forms  TEXT,
    target_region_codes     TEXT,
    requirement_text        TEXT,
    contact_window_id       TEXT,
    source_url              TEXT NOT NULL,
    source_pdf_s3_uri       TEXT,
    ocr_s3_uri              TEXT,
    ocr_job_id              TEXT,
    ocr_confidence          REAL,
    ocr_page_count          INTEGER,
    sha256                  TEXT NOT NULL,
    fetched_at              TEXT NOT NULL,
    ingested_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    license                 TEXT NOT NULL DEFAULT 'public_domain_jp_gov'
                              CHECK (license IN (
                                'public_domain_jp_gov',
                                'cc_by_4.0',
                                'gov_standard',
                                'proprietary',
                                'unknown'
                              )),
    license_source          TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(municipality_code, program_name, source_url)
);

CREATE INDEX IF NOT EXISTS ix_am_munic_subsidy_pref
    ON am_municipality_subsidy(prefecture, municipality_code);

CREATE INDEX IF NOT EXISTS ix_am_munic_subsidy_deadline
    ON am_municipality_subsidy(deadline);

CREATE INDEX IF NOT EXISTS ix_am_munic_subsidy_amount_max
    ON am_municipality_subsidy(amount_yen_max);

CREATE INDEX IF NOT EXISTS ix_am_munic_subsidy_sha256
    ON am_municipality_subsidy(sha256);

CREATE INDEX IF NOT EXISTS ix_am_munic_subsidy_ingested
    ON am_municipality_subsidy(ingested_at);

-- ============================================================================
-- v_municipality_subsidy_by_prefecture — 47 prefecture x subsidy count / avg
-- ============================================================================

CREATE VIEW IF NOT EXISTS v_municipality_subsidy_by_prefecture AS
    SELECT
        prefecture,
        COUNT(*)                              AS subsidy_count,
        COUNT(DISTINCT municipality_code)     AS municipality_with_subsidy_count,
        ROUND(AVG(amount_yen_max), 0)         AS avg_amount_yen_max,
        MIN(amount_yen_max)                   AS min_amount_yen_max,
        MAX(amount_yen_max)                   AS max_amount_yen_max,
        SUM(CASE WHEN deadline IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_deadline,
        MAX(updated_at)                       AS latest_updated
      FROM am_municipality_subsidy
     GROUP BY prefecture
     ORDER BY prefecture;

-- ============================================================================
-- v_municipality_subsidy_by_jsic_major — 21 JSIC major code x availability
-- ============================================================================
-- target_jsic_majors is JSON array; rows that mention major 'F' will appear
-- exactly once under jsic_major='F'. NULL target_jsic_majors falls into the
-- '__any__' bucket (subsidy is open to all industries).

CREATE VIEW IF NOT EXISTS v_municipality_subsidy_by_jsic_major AS
    WITH expanded AS (
        SELECT
            subsidy_id,
            municipality_code,
            prefecture,
            amount_yen_max,
            CASE
                WHEN target_jsic_majors IS NULL OR TRIM(target_jsic_majors) IN ('', '[]')
                    THEN '__any__'
                ELSE TRIM(REPLACE(REPLACE(REPLACE(target_jsic_majors, '"', ''), '[', ''), ']', ''))
            END AS jsic_majors_str
          FROM am_municipality_subsidy
    )
    SELECT
        TRIM(j.value) AS jsic_major,
        COUNT(*) AS subsidy_count,
        COUNT(DISTINCT e.municipality_code) AS municipality_count,
        ROUND(AVG(e.amount_yen_max), 0) AS avg_amount_yen_max
      FROM expanded e,
           json_each('[' ||
                     CASE
                       WHEN e.jsic_majors_str = '__any__' THEN '"__any__"'
                       ELSE REPLACE('"' || REPLACE(e.jsic_majors_str, ',', '","') || '"', '"', '"')
                     END
                     || ']') j
     GROUP BY TRIM(j.value)
     ORDER BY subsidy_count DESC;

-- Note: schema_migrations bookkeeping is recorded by entrypoint.sh §4 /
-- scripts/migrate.py. Do NOT INSERT into schema_migrations here.
