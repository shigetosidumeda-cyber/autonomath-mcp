-- target_db: autonomath
-- migration: 247_industry_sector_175
-- generated_at: 2026-05-12
-- author: Wave 41 Axis 7c — JSIC 中分類 175-sector cohort (現 23 業種 → 175)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Extend the existing `am_industry_jsic` (37 大分類 + 一部 中分類) into a
-- full JSIC 175 中分類 cohort table so programs / adoption / enforcement
-- can be projected onto a finer-grained industry axis. 大分類 (e.g. 'D
-- 建設業') is too coarse for the cohort-revenue 8 cohorts — 中分類
-- (e.g. '060 総合工事業' / '061 職別工事業' / '062 設備工事業') unlocks
-- realistic program / case-study mappings.
--
-- Source discipline
-- -----------------
-- JSIC 中分類 list — 総務省統計局 公式
--   https://www.soumu.go.jp/toukei_toukatsu/index/seido/sangyo/02toukatsu01_03000023.html
-- Codes are 3-digit (e.g. '060' for 総合工事業). The first character of
-- the 大分類 is preserved as `major_code` (1 char A-T).
--
-- Schema notes
-- ------------
-- * jsic_code  — 3-digit JSIC 中分類 code (e.g. '060').
-- * major_code — 1-char JSIC 大分類 code (e.g. 'D' for 建設業).
-- * parent_major — name of the 大分類 (e.g. '建設業').
-- * name       — name of the 中分類 (e.g. '総合工事業').
-- * programs_count / programs_avg_amount — denormalized aggregates,
--   refreshed weekly by `scripts/cron/aggregate_industry_sector_175_weekly.py`.
-- * adoption_count — number of 採択事例 mapped to this 中分類.
--
-- NOT all 11,601 programs will map (some 制度 are sector-agnostic);
-- aggregator weights by available signals only.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_industry_jsic_175 (
    jsic_code             TEXT PRIMARY KEY,
    major_code            TEXT NOT NULL,
    parent_major          TEXT,
    name                  TEXT NOT NULL,
    programs_count        INTEGER NOT NULL DEFAULT 0,
    programs_avg_amount   INTEGER NOT NULL DEFAULT 0,
    adoption_count        INTEGER NOT NULL DEFAULT 0,
    enforcement_count     INTEGER NOT NULL DEFAULT 0,
    refreshed_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_jsic_175_code_len CHECK (length(jsic_code) = 3),
    CONSTRAINT ck_jsic_175_major_len CHECK (length(major_code) = 1)
);

CREATE INDEX IF NOT EXISTS idx_jsic_175_major
    ON am_industry_jsic_175(major_code, jsic_code);

CREATE INDEX IF NOT EXISTS idx_jsic_175_programs
    ON am_industry_jsic_175(programs_count DESC);

CREATE INDEX IF NOT EXISTS idx_jsic_175_adoption
    ON am_industry_jsic_175(adoption_count DESC);

CREATE INDEX IF NOT EXISTS idx_jsic_175_refreshed
    ON am_industry_jsic_175(refreshed_at);

-- Program → 中分類 mapping table (one program may map to multiple
-- sectors when its industry_tags carry multiple matches).
CREATE TABLE IF NOT EXISTS am_program_sector_175_map (
    map_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id      TEXT NOT NULL,
    jsic_code       TEXT NOT NULL,
    score           INTEGER NOT NULL DEFAULT 0,
    match_kind      TEXT,
    refreshed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_sector_175_map_score CHECK (score BETWEEN 0 AND 100),
    CONSTRAINT ck_sector_175_map_match_kind CHECK (
        match_kind IS NULL OR match_kind IN (
            'tag', 'jsic_major', 'keyword', 'industry_eligibility'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_sector_175_map_program
    ON am_program_sector_175_map(program_id, score DESC);

CREATE INDEX IF NOT EXISTS idx_sector_175_map_sector
    ON am_program_sector_175_map(jsic_code, score DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_sector_175_map_edge
    ON am_program_sector_175_map(program_id, jsic_code);

-- Weekly cron log
CREATE TABLE IF NOT EXISTS am_industry_sector_175_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    sectors_refreshed INTEGER NOT NULL DEFAULT 0,
    programs_mapped INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_industry_sector_175_run_log_started
    ON am_industry_sector_175_run_log(started_at DESC);

-- Operator view: top-density sectors (which JSIC 中分類 has the most
-- compatible programs).
DROP VIEW IF EXISTS v_industry_sector_175_density;
CREATE VIEW v_industry_sector_175_density AS
SELECT
    jsic_code,
    major_code,
    parent_major,
    name,
    programs_count,
    adoption_count,
    enforcement_count
FROM am_industry_jsic_175
WHERE programs_count > 0 OR adoption_count > 0
ORDER BY programs_count DESC, adoption_count DESC, jsic_code ASC;

COMMIT;
