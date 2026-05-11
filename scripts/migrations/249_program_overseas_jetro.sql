-- target_db: autonomath
-- migration: 249_program_overseas_jetro
-- generated_at: 2026-05-12
-- author: Wave 43.1.2 — Overseas (JETRO / METI / JBIC / NEXI) cohort.
-- idempotent: every CREATE uses IF NOT EXISTS; no DML beyond seed-safe upsert.
--
-- Purpose
-- -------
-- Adds a structured "海外進出 / 対日直接投資 / 信用補完" surface keyed by
-- ISO 3166 country_code so that the foreign FDI cohort (memory:
-- cohort_revenue_model #4) can join programs.* with target_country +
-- program_type without a free-text scan of source_url every call.
--
-- The base programs table (jpintel.db) already stores domestic 補助金
-- on a single Japan-centric axis. This sister table on the autonomath
-- side captures the *cross-border* dimension (one program → 1..N
-- countries; one country → 1..N programs) plus the program_type fence
-- (JETRO海外進出支援 / METI / JBIC / NEXI) that consultants filter on.
--
-- Source discipline
-- -----------------
-- * JETRO 一次資料: https://www.jetro.go.jp/  (海外進出支援 / Invest Japan)
-- * METI 外国直接投資: https://www.meti.go.jp/policy/external_economy/
-- * JBIC: https://www.jbic.go.jp/  (信用補完・海外投資金融)
-- * NEXI: https://www.nexi.go.jp/  (貿易保険・信用補完)
--
-- Aggregator domains (noukaweb / hojyokin-portal / biz.stayway) are banned
-- per memory feedback_no_fake_data. source_url must be primary.
--
-- Schema notes
-- ------------
-- * country_code  — ISO 3166-1 alpha-2 (e.g. 'US', 'CN', 'TH', 'VN').
--   Length-2 CHECK keeps typos out (詐欺リスク回避, memory
--   feedback_bounded_text_to_select). 'XX' reserved for "global / 不問".
-- * jetro_id      — optional JETRO publication id when source is JETRO.
-- * program_type  — bounded enum (see CHECK below).
-- * source_url    — primary 一次資料 URL.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_program_overseas (
    overseas_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id      TEXT NOT NULL,
    country_code    TEXT NOT NULL,
    jetro_id        TEXT,
    program_type    TEXT NOT NULL,
    program_name    TEXT,
    source_url      TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_overseas_country_len CHECK (length(country_code) = 2),
    CONSTRAINT ck_overseas_program_type CHECK (
        program_type IN (
            'JETRO海外進出支援',
            'JETRO対日投資',
            'METI',
            'JBIC',
            'NEXI',
            'other'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_overseas_program
    ON am_program_overseas(program_id);

CREATE INDEX IF NOT EXISTS idx_overseas_country
    ON am_program_overseas(country_code, program_type);

CREATE INDEX IF NOT EXISTS idx_overseas_type
    ON am_program_overseas(program_type, fetched_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_overseas_edge
    ON am_program_overseas(program_id, country_code, program_type);

-- Weekly cron log surface
CREATE TABLE IF NOT EXISTS am_overseas_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    rows_inserted   INTEGER NOT NULL DEFAULT 0,
    rows_skipped    INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_overseas_run_log_started
    ON am_overseas_run_log(started_at DESC);

-- Operator view: country density (FDI cohort scoping)
DROP VIEW IF EXISTS v_program_overseas_country_density;
CREATE VIEW v_program_overseas_country_density AS
SELECT
    country_code,
    program_type,
    COUNT(*) AS programs_count,
    MAX(fetched_at) AS latest_fetched_at
FROM am_program_overseas
GROUP BY country_code, program_type
ORDER BY programs_count DESC, country_code ASC;

COMMIT;
