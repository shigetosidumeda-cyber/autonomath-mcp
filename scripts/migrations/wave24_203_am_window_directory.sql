-- target_db: autonomath
-- migration: wave24_203_am_window_directory
-- generated_at: 2026-05-17
-- author: Niche Moat Lane N4 — 窓口 / 申請先 lookup one-stop
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- 法人 + 制度 → どの役所に申請するか は実務で重要。jpcite に MCP call 1 本で
-- 取得できる状態を作る。これまで agent が houjin_bangou + program_id を渡しても
-- 「申請先は ○○ 役所」と即答できなかった。N4 lane はその死角を埋める。
--
-- 1st-pass scope
-- --------------
--   * 法務局 ~50 (全国法務局 + 地方法務局 + 支局/出張所 一部)
--   * 税務署 ~520 (国税庁 公開)
--   * 都道府県庁 47 + 関連担当課
--   * 市区町村役場 ~1,700 (市区町村税関連窓口)
--   * 商工会 / 商工会議所 ~1,500
--   * 公庫支店 152 (JFC 全店)
--   * 信金 / 信用組合 ~200 (信金中金 / 全信協)
-- 合計 ~4,200 - 4,500 件 (1st pass で 約 4,500)
--
-- target_db = autonomath
-- ----------------------
-- am_authority と同じ semantic 領域 (公的 institution master)。
-- am_region (region_code) と FK link で 法人本店 → 管轄 mapping を成立させる。
-- jpintel.db ではなく autonomath.db に置く理由:
--   * 既に am_authority / am_region が autonomath.db
--   * cross-domain lookup view (v_am_window_by_region) を同 DB 内で build 可
--   * entrypoint.sh §4 (autonomath self-heal) が target_db: autonomath を拾う
--
-- Idempotency contract
-- --------------------
--   * `CREATE TABLE IF NOT EXISTS` — 既存 row を保持したまま re-apply 可
--   * 全 index は `CREATE INDEX IF NOT EXISTS`
--   * VIEW も `CREATE VIEW IF NOT EXISTS`
--   * No DML — 行は scripts/etl/crawl_window_directory_2026_05_17.py が書く
--
-- LLM call: 0. Pure SQLite write. Crawl + ingest は asyncio + httpx + bs4.
--
-- License posture
-- ---------------
-- 国・自治体の窓口情報 (所在地・電話・URL) は政府著作物 §13 (著作権法) で
-- 編集・翻案・再配信 が原則自由。aggregator (mapfan / iタウンページ等) は
-- 絶対禁止 (CLAUDE.md データ衛生規約) — 1次資料 (法務省 / 国税庁 / pref / city
-- / 商工会議所連合会 / 日本政策金融公庫 / 信金中金) のみ。
--
-- Field semantics
-- ---------------
-- window_id                  TEXT PK — 'WIN-' + 11 hex (deterministic from URL)
-- jurisdiction_kind          TEXT enum:
--                              'legal_affairs_bureau'    (法務局・地方法務局)
--                              'tax_office'              (税務署)
--                              'prefecture'              (都道府県庁)
--                              'municipality'            (市区町村役場)
--                              'chamber_of_commerce'     (商工会議所)
--                              'commerce_society'        (商工会)
--                              'jfc_branch'              (日本政策金融公庫支店)
--                              'shinkin'                 (信用金庫)
--                              'credit_union'            (信用組合)
--                              'labour_bureau'           (労働局・労基署)
--                              'pension_office'          (年金事務所)
--                              'other'
-- name                       TEXT — 窓口名 (e.g. '東京法務局 新宿出張所')
-- postal_address             TEXT — 住所 (1次資料 raw)
-- jp_postcode                TEXT — 〒 ハイフン無 7 桁 (e.g. '1000013')
-- latitude_longitude         TEXT — 'lat,lon' (任意。 NULL 可)
-- tel                        TEXT — 電話番号 (raw 1次資料表記)
-- fax                        TEXT
-- email                      TEXT
-- url                        TEXT — official 1次資料 URL (必須)
-- opening_hours              TEXT — 開庁時間 free-text
-- jurisdiction_houjin_filter_regex
--                            TEXT — 管轄判定 regex over 法人本店住所
-- jurisdiction_region_code   TEXT — am_region(region_code) FK soft
-- parent_window_id           TEXT — 階層 (法務局本局 → 支局 など)
-- source_url                 TEXT NOT NULL — fetched 1次資料 URL
-- license                    TEXT NOT NULL DEFAULT 'public_domain_jp_gov'
-- retrieved_at               TEXT NOT NULL — ISO 8601 UTC
-- last_verified              TEXT — URL liveness last check
-- notes                      TEXT

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_window_directory — 国・自治体 窓口/申請先 lookup master
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_window_directory (
    window_id                        TEXT PRIMARY KEY,
    jurisdiction_kind                TEXT NOT NULL CHECK (jurisdiction_kind IN (
                                       'legal_affairs_bureau',
                                       'tax_office',
                                       'prefecture',
                                       'municipality',
                                       'chamber_of_commerce',
                                       'commerce_society',
                                       'jfc_branch',
                                       'shinkin',
                                       'credit_union',
                                       'labour_bureau',
                                       'pension_office',
                                       'other'
                                     )),
    name                             TEXT NOT NULL,
    postal_address                   TEXT,
    jp_postcode                      TEXT,
    latitude_longitude               TEXT,
    tel                              TEXT,
    fax                              TEXT,
    email                            TEXT,
    url                              TEXT,
    opening_hours                    TEXT,
    jurisdiction_houjin_filter_regex TEXT,
    jurisdiction_region_code         TEXT,
    parent_window_id                 TEXT,
    source_url                       TEXT NOT NULL,
    license                          TEXT NOT NULL DEFAULT 'public_domain_jp_gov'
                                       CHECK (license IN (
                                         'public_domain_jp_gov',
                                         'cc_by_4.0',
                                         'gov_standard',
                                         'proprietary',
                                         'unknown'
                                       )),
    retrieved_at                     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_verified                    TEXT,
    notes                            TEXT,
    UNIQUE(jurisdiction_kind, name, postal_address)
);

CREATE INDEX IF NOT EXISTS ix_am_window_kind_region
    ON am_window_directory(jurisdiction_kind, jurisdiction_region_code);

CREATE INDEX IF NOT EXISTS ix_am_window_kind
    ON am_window_directory(jurisdiction_kind);

CREATE INDEX IF NOT EXISTS ix_am_window_region
    ON am_window_directory(jurisdiction_region_code);

CREATE INDEX IF NOT EXISTS ix_am_window_postcode
    ON am_window_directory(jp_postcode);

CREATE INDEX IF NOT EXISTS ix_am_window_parent
    ON am_window_directory(parent_window_id);

-- Convenience views ----------------------------------------------------------

CREATE VIEW IF NOT EXISTS v_am_window_by_kind AS
    SELECT
        jurisdiction_kind,
        COUNT(*) AS window_count,
        MIN(retrieved_at) AS earliest_retrieved,
        MAX(retrieved_at) AS latest_retrieved
      FROM am_window_directory
     GROUP BY jurisdiction_kind;

CREATE VIEW IF NOT EXISTS v_am_window_by_region AS
    SELECT
        jurisdiction_region_code,
        jurisdiction_kind,
        COUNT(*) AS window_count
      FROM am_window_directory
     WHERE jurisdiction_region_code IS NOT NULL
     GROUP BY jurisdiction_region_code, jurisdiction_kind;
