-- target_db: autonomath
-- migration: 248_program_source_municipality_v2
-- generated_at: 2026-05-12
-- author: Wave 43.1.1 — 市町村 1,700+ subsidy ETL v2 拡張 (+5,000 programs)
-- idempotent: every CREATE uses IF NOT EXISTS; pure additive (no DML).
--
-- Purpose
-- -------
-- Wave 31 Axis 1a (wave24_191_municipality_subsidy.sql, target_db=jpintel)
-- shipped the 1st pass 47 都道府県 + 20 政令市 = 67 自治体 diff log. The v2
-- layer below extends to the full 1,700+ 市町村 cohort (中核市 / 特別区 /
-- 一般市町村) and records the bridge between each crawled page and the
-- `programs` registry it produces.
--
-- Distinction from wave24_191
-- ---------------------------
-- * wave24_191.municipality_subsidy  — raw page snapshot + diff hash log.
--   1 row per (muni_code, subsidy_url) page; jpintel.db side.
-- * 248.am_program_source_municipality_v2 — program-bridge join table.
--   1 row per (program_id, municipality_code, source_url); autonomath.db
--   side. Captures which programs were derived from which municipality
--   crawl, plus the grant_type taxonomy (補助金 / 助成金 / 融資 / その他).
--
-- target_db = autonomath
-- ----------------------
-- The v2 join sits in autonomath.db because the canonical `programs` table
-- (with unified_id, tier, primary_name) lives there. The bridge enables
-- the new REST surfaces `GET /v1/programs/by_municipality/{code}` and
-- `GET /v1/programs/by_prefecture/{code}` (with grant_type filter) without
-- a cross-db ATTACH.
--
-- entrypoint.sh §4 self-heal will pick up this migration via the
-- `autonomath_boot_manifest.txt` allowlist. Pure additive (CREATE TABLE
-- IF NOT EXISTS + CREATE INDEX IF NOT EXISTS) makes it boot-time safe.
--
-- LLM call: 0. Pure SQLite write. Cron is httpx + bs4 + sqlite3.
--
-- License posture
-- ---------------
-- 自治体公式サイトは §13 著作権法 上 政府著作物 — 編集 / 翻案 / 再配信 が
-- 原則自由。aggregator (noukaweb / hojyokin-portal / biz.stayway 等) は
-- 絶対禁止 (CLAUDE.md データ衛生規約)。本テーブルの source_url は
-- 1次資料 (city.*.lg.jp / pref.*.lg.jp / metro.tokyo.lg.jp 等) のみ。

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_program_source_municipality_v2 (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id          TEXT NOT NULL,
    municipality_code   TEXT NOT NULL,
    grant_type          TEXT NOT NULL CHECK (grant_type IN
                            ('補助金','助成金','融資','その他')),
    prefecture_code     TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    source_fetched_at   TEXT NOT NULL DEFAULT
                            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_verified       TEXT NOT NULL DEFAULT
                            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_msv2_muni_len   CHECK (length(municipality_code) = 5),
    CONSTRAINT ck_msv2_pref_len   CHECK (length(prefecture_code) = 2),
    UNIQUE(program_id, municipality_code, source_url)
);

-- Primary access: REST /v1/programs/by_municipality/{code}
CREATE INDEX IF NOT EXISTS idx_msv2_muni_grant
    ON am_program_source_municipality_v2(municipality_code, grant_type);

-- Secondary access: REST /v1/programs/by_prefecture/{code} + freshness sort
CREATE INDEX IF NOT EXISTS idx_msv2_pref_verified
    ON am_program_source_municipality_v2(prefecture_code, last_verified DESC);

-- Run log for cron observability (optional; ETL writes a single row per run).
CREATE TABLE IF NOT EXISTS am_program_source_municipality_v2_run_log (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL DEFAULT
                            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at         TEXT,
    municipalities_seen INTEGER NOT NULL DEFAULT 0,
    programs_inserted   INTEGER NOT NULL DEFAULT 0,
    programs_updated    INTEGER NOT NULL DEFAULT 0,
    aggregator_refused  INTEGER NOT NULL DEFAULT 0,
    fetch_errors        INTEGER NOT NULL DEFAULT 0,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_msv2_run_log_started
    ON am_program_source_municipality_v2_run_log(started_at DESC);

COMMIT;

-- schema_migrations bookkeeping is performed by scripts/migrate.py
-- (the entrypoint.sh §4 self-heal runner). Do NOT INSERT here.
