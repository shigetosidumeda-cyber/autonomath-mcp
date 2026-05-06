-- target_db: jpintel
-- migration: wave24_191_municipality_subsidy
-- generated_at: 2026-05-07
-- author: DEEP-44 自治体 1,741 補助金 page weekly diff cron implementation
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_44_municipality_subsidy_weekly_diff.md
--
-- DEEP-44 lands the 1,741-自治体 補助金 page weekly diff layer that mirasapo
-- / jGrants do not cover (they only carry 国 + 都道府県 旗艦 補助金). This is
-- the 死角 that 補助金 consultant cohort (DEEP-19) hand-walks daily — by
-- automating it as a weekly diff cron, jpcite can occupy the bottom-of-funnel.
--
-- 1st pass scope
-- --------------
--   * 47 都道府県 + 20 政令市 = 67 自治体 (data/municipality_seed_urls.json)
--   * 中核市 60 / 特別区 23 / 一般市町村 1,591 (= 1,674 row) は後追加 path 残す
--     — operator manual seed expansion in subsequent waves once 67-row 1st
--     pass cron run is verified live.
--
-- target_db = jpintel
-- -------------------
-- 自治体 補助金 corpus は jpintel.db (~352 MB live) 側に置く。理由:
--   * core "programs" と同じ register entity (公的 補助制度) family
--   * 9.4 GB autonomath.db に対する RPO design (cold-keep) を温存
--   * `entrypoint.sh §3` の jpintel-target migrate.py loop が拾う
--
-- entrypoint.sh §4 の autonomath self-heal loop は `target_db: autonomath`
-- 行のみ拾うので、本ファイルは安全に jpintel 側にだけ apply される。
--
-- Idempotency contract
-- --------------------
--   * `CREATE TABLE IF NOT EXISTS` — 既存 row を保持したまま re-apply 可
--   * 全 index は `CREATE INDEX IF NOT EXISTS`
--   * No DML — 行は scripts/cron/ingest_municipality_subsidy_weekly.py が書く
--
-- LLM call: 0. Pure SQLite write. Cron は asyncio + httpx + bs4 + pdfplumber + sqlite3.
--
-- License posture
-- ---------------
-- 自治体公式サイトは §13 著作権法 上 政府著作物 — 編集 / 翻案 / 再配信 が
-- 原則自由。aggregator (noukaweb / hojyokin-portal / biz.stayway 等) は
-- 絶対禁止 (CLAUDE.md データ衛生規約)。本テーブルの subsidy_url は
-- 1次資料 (city.*.lg.jp / pref.*.lg.jp / metro.tokyo.lg.jp 等) のみ。
--
-- Field semantics
-- ---------------
-- id                INTEGER PRIMARY KEY AUTOINCREMENT — surrogate
-- pref              TEXT NOT NULL — 都道府県名 (e.g. '東京都', '北海道')
-- muni_code         TEXT NOT NULL — J-LIS 全国地方公共団体コード 6-digit
-- muni_name         TEXT NOT NULL — 自治体名 (e.g. '東京都', '札幌市')
-- muni_type         TEXT NOT NULL CHECK enum [prefecture/seirei/chukaku/special/regular]
-- subsidy_url       TEXT NOT NULL — 補助金 一覧 / 詳細 page URL (1次資料のみ)
-- subsidy_name      TEXT — 補助金名 (heuristic 抽出、 失敗時 NULL)
-- eligibility_text  TEXT — 対象者 free-text (raw fallback で全文格納可)
-- amount_text       TEXT — 補助額 free-text
-- deadline_text     TEXT — 締切 free-text
-- retrieved_at      TEXT NOT NULL — 取得時刻 ISO 8601
-- sha256            TEXT NOT NULL — diff 検出用 page contents hash
-- page_status       TEXT NOT NULL CHECK enum [active/404/redirect]
--                   (DEEP-44 spec の '410_gone' '5xx' 'timeout' 'cert_invalid'
--                    は 1st pass では 'active' / '404' / 'redirect' に集約。
--                    細分化は subsequent wave で migration 拡張予定。)

PRAGMA foreign_keys = ON;

-- ============================================================================
-- municipality_subsidy — 自治体 補助金 page diff log (1 row per page snapshot)
-- ============================================================================

CREATE TABLE IF NOT EXISTS municipality_subsidy (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pref              TEXT NOT NULL,
    muni_code         TEXT NOT NULL,
    muni_name         TEXT NOT NULL,
    muni_type         TEXT NOT NULL CHECK (muni_type IN
                          ('prefecture','seirei','chukaku','special','regular')),
    subsidy_url       TEXT NOT NULL,
    subsidy_name      TEXT,
    eligibility_text  TEXT,
    amount_text       TEXT,
    deadline_text     TEXT,
    retrieved_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    sha256            TEXT NOT NULL,
    page_status       TEXT NOT NULL CHECK (page_status IN
                          ('active','404','redirect')),
    UNIQUE(muni_code, subsidy_url)
);

-- Primary access pattern: pref + muni_name で frontend lookup
CREATE INDEX IF NOT EXISTS ix_ms_pref_muni
    ON municipality_subsidy(pref, muni_name);

-- diff detection: sha256 hash で前週との差分判定
CREATE INDEX IF NOT EXISTS ix_ms_sha256
    ON municipality_subsidy(sha256);

-- monitoring: page_status + retrieved_at で 404/redirect の継続日数を集計
CREATE INDEX IF NOT EXISTS ix_ms_status_retrieved
    ON municipality_subsidy(page_status, retrieved_at);

-- Bookkeeping is recorded by entrypoint.sh §3 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
