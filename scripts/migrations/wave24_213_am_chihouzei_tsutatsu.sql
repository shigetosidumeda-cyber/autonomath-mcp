-- target_db: autonomath
-- migration: wave24_213_am_chihouzei_tsutatsu
-- generated_at: 2026-05-17
-- author: AA1-G1 — 地方税 個別通達 47 都道府県 expansion
-- idempotent: every CREATE uses IF NOT EXISTS; no DML in this DDL
--
-- Purpose
-- -------
-- The base `nta_tsutatsu_index` (migration 103) is keyed by national
-- 通達 (法基通 / 所基通 / 消基通 / 相基通). 地方税 (個人住民税 / 法人住民税
-- / 事業税 / 固定資産税 / 不動産取得税 / 自動車税 / 軽自動車税 etc.) is
-- governed by 47 都道府県 + 1,727 市区町村 individual ordinances and
-- prefectural 通達 — the national index does NOT cover these.
--
-- AA1-G1 backfill: ~6,000 prefectural 通達 + 個別取扱 across 47 都道府県
-- official 公開資料. Each row carries the prefecture code (JIS X 0401
-- 2-digit prefecture code), the tax type, and a primary source_url
-- (pref.*.lg.jp / metro.tokyo.lg.jp host allowlist).
--
-- Field semantics
-- ---------------
-- chihouzei_id        PK
-- prefecture_code     JIS X 0401 (01..47, 01=北海道 … 47=沖縄)
-- prefecture_name     '北海道' / '青森県' / ...
-- tax_kind            canonical enum
-- tsutatsu_no         通達番号 (e.g. '令和3年告示第123号')
-- title               通達 title
-- body_excerpt        first 1000 chars
-- effective_from      ISO date (parsed from 通達 header)
-- effective_to        ISO date if 廃止 / 改正 marker present
-- source_url          canonical pref.*.lg.jp URL (UNIQUE)
-- license             'gov_standard' (各自治体公開資料)
-- crawl_run_id        G1 manifest run id
-- ingested_at         ISO 8601 UTC
--
-- License posture
-- ---------------
-- 都道府県公開資料 = gov_standard. Aggregator hosts rejected by allowlist
-- at crawl time (pref.*.lg.jp / metro.tokyo.lg.jp / city.*.lg.jp only).
--
-- NO LLM. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_chihouzei_tsutatsu (
    chihouzei_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    prefecture_code   TEXT NOT NULL
                          CHECK (LENGTH(prefecture_code) = 2
                                 AND prefecture_code BETWEEN '01' AND '47'),
    prefecture_name   TEXT NOT NULL,
    tax_kind          TEXT NOT NULL
                          CHECK (tax_kind IN (
                            'kojin_juminzei',
                            'hojin_juminzei',
                            'jigyozei',
                            'kotei_shisanzei',
                            'fudosan_shutokuzei',
                            'jidoshazei',
                            'kei_jidoshazei',
                            'kenmin_zei',
                            'shimin_zei',
                            'tabako_zei',
                            'gorufujozei',
                            'kankyo_zei',
                            'sonota_chihouzei'
                          )),
    tsutatsu_no       TEXT,
    title             TEXT NOT NULL,
    body_excerpt      TEXT,
    effective_from    TEXT,
    effective_to      TEXT,
    source_url        TEXT NOT NULL UNIQUE,
    license           TEXT NOT NULL DEFAULT 'gov_standard'
                          CHECK (license IN ('gov_standard', 'public_domain_jp_gov')),
    crawl_run_id      TEXT NOT NULL DEFAULT 'etl_g1_nta_manifest_2026_05_17',
    ingested_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_am_chihouzei_pref_tax
    ON am_chihouzei_tsutatsu(prefecture_code, tax_kind);

CREATE INDEX IF NOT EXISTS ix_am_chihouzei_effective
    ON am_chihouzei_tsutatsu(effective_from DESC, effective_to);

CREATE INDEX IF NOT EXISTS ix_am_chihouzei_crawl_run
    ON am_chihouzei_tsutatsu(crawl_run_id, ingested_at DESC);

-- FTS5 over title + body_excerpt
CREATE VIRTUAL TABLE IF NOT EXISTS am_chihouzei_tsutatsu_fts USING fts5(
    title, body_excerpt,
    content='am_chihouzei_tsutatsu', content_rowid='chihouzei_id',
    tokenize="trigram"
);

CREATE TRIGGER IF NOT EXISTS am_chihouzei_tsutatsu_ai AFTER INSERT ON am_chihouzei_tsutatsu BEGIN
    INSERT INTO am_chihouzei_tsutatsu_fts(rowid, title, body_excerpt)
    VALUES (new.chihouzei_id, new.title, new.body_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS am_chihouzei_tsutatsu_ad AFTER DELETE ON am_chihouzei_tsutatsu BEGIN
    INSERT INTO am_chihouzei_tsutatsu_fts(am_chihouzei_tsutatsu_fts, rowid, title, body_excerpt)
    VALUES ('delete', old.chihouzei_id, old.title, old.body_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS am_chihouzei_tsutatsu_au AFTER UPDATE ON am_chihouzei_tsutatsu BEGIN
    INSERT INTO am_chihouzei_tsutatsu_fts(am_chihouzei_tsutatsu_fts, rowid, title, body_excerpt)
    VALUES ('delete', old.chihouzei_id, old.title, old.body_excerpt);
    INSERT INTO am_chihouzei_tsutatsu_fts(rowid, title, body_excerpt)
    VALUES (new.chihouzei_id, new.title, new.body_excerpt);
END;

CREATE VIEW IF NOT EXISTS v_am_chihouzei_coverage AS
    SELECT
        prefecture_code,
        prefecture_name,
        tax_kind,
        COUNT(*) AS row_count,
        MAX(ingested_at) AS latest_ingested
      FROM am_chihouzei_tsutatsu
     GROUP BY prefecture_code, tax_kind;
