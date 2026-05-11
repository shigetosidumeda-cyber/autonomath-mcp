-- target_db: autonomath
-- migration: 252_law_jorei_pref
-- generated_at: 2026-05-12
-- author: Wave 43.1.5 — 都道府県条例 (prefectural ordinances) corpus, ~4,700 rows across 47 都道府県
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
-- boot_time: requires manifest approval to apply at boot
--
-- Purpose
-- -------
-- Capture each 都道府県's 公布済条例 corpus as a first-class table beside
-- am_law (which carries 国 level 法令 only). 都道府県条例 are governed
-- by 地方自治法 §14 and are out of scope for e-Gov; each prefecture
-- hosts its own 例規データベース (jorei.pref.{pref_code}.lg.jp or
-- equivalent). Conservatively budget ~100 ordinances per prefecture
-- (47 × 100 ≈ 4,700), with a long tail of 規則 / 訓令 / 告示 captured
-- as TBD.
--
-- Source discipline
-- -----------------
-- 一次資料 only — each prefecture's official 例規 site. Aggregators
-- (jorei.jp, jichi-souken.or.jp redistributions) are explicitly banned
-- in the matching ETL `fill_laws_jorei_47pref_2x.py`. RSS feeds, where
-- available (約 12 都道府県 publish 改正通知 RSS), are preferred over
-- full crawl for incremental delta.
--
-- Schema notes
-- ------------
-- * jorei_id          — surrogate INTEGER PK (autoincrement).
-- * canonical_id      — stable canonical id of the form
--                       "JOREI-{prefecture_code}-{slug}-{enacted_date}",
--                       used as the public reference key on REST.
-- * law_id            — OPTIONAL FK to am_law.canonical_id (nullable —
--                       used when 条例 is a 委任条例 derived from a 国法
--                       like 環境基本法 §15). Most rows are NULL.
-- * prefecture_code   — 2-char JIS X 0401 都道府県 code (01..47) — the
--                       leading 2 digits of the 5-digit local-gov code.
-- * jorei_number      — 公布番号 (e.g. "令和六年北海道条例第一号").
-- * enacted_date / last_revised — ISO-8601 date strings.
-- * body_text_excerpt — first ~4000 chars of 条例本文 (full body lands
--                       in `am_law_jorei_pref_fts` for FTS, not here).
-- * source_url        — canonical URL on the prefecture's 例規 site.
-- * license           — 都道府県 sites are 著作権法 §13 (条例 = 公文書
--                       かつ 著作物性無し) — re-distribution is OK; record
--                       as 'gov_public' by default.
--
-- Companion tables
-- ----------------
-- * am_law_jorei_pref_fts        — FTS5 trigram on body for search.
-- * am_law_jorei_pref_run_log    — weekly cron audit trail.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_law_jorei_pref (
    jorei_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id      TEXT NOT NULL UNIQUE,
    law_id            TEXT,                       -- optional am_law.canonical_id (委任条例)
    prefecture_code   TEXT NOT NULL,              -- '01'..'47'
    prefecture_name   TEXT NOT NULL,
    jorei_number      TEXT,                       -- 公布番号
    jorei_title       TEXT NOT NULL,
    jorei_kind        TEXT NOT NULL DEFAULT 'jorei',
    enacted_date      TEXT,                       -- ISO yyyy-mm-dd
    last_revised      TEXT,
    body_text_excerpt TEXT,                       -- first ~4000 chars
    body_url          TEXT,                       -- inline body anchor
    source_url        TEXT NOT NULL,              -- canonical prefecture page
    license           TEXT NOT NULL DEFAULT 'gov_public',
    fetched_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    confidence        REAL NOT NULL DEFAULT 1.0,
    CONSTRAINT ck_jorei_pref_code_len CHECK (length(prefecture_code) = 2),
    CONSTRAINT ck_jorei_pref_kind CHECK (jorei_kind IN (
        'jorei', 'kisoku', 'kunrei', 'kokuji', 'youkou'
    )),
    CONSTRAINT ck_jorei_pref_confidence CHECK (confidence BETWEEN 0.0 AND 1.0)
);

CREATE INDEX IF NOT EXISTS idx_jorei_pref_code
    ON am_law_jorei_pref(prefecture_code, enacted_date DESC);

CREATE INDEX IF NOT EXISTS idx_jorei_pref_law
    ON am_law_jorei_pref(law_id) WHERE law_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jorei_pref_kind
    ON am_law_jorei_pref(jorei_kind, prefecture_code);

CREATE INDEX IF NOT EXISTS idx_jorei_pref_fetched
    ON am_law_jorei_pref(fetched_at);

CREATE INDEX IF NOT EXISTS idx_jorei_pref_title
    ON am_law_jorei_pref(jorei_title);

-- FTS5 trigram (consistent with am_law full-text indexes elsewhere).
CREATE VIRTUAL TABLE IF NOT EXISTS am_law_jorei_pref_fts USING fts5(
    canonical_id UNINDEXED,
    prefecture_code UNINDEXED,
    jorei_title,
    body_text_excerpt,
    tokenize = "trigram"
);

-- Weekly cron audit log.
CREATE TABLE IF NOT EXISTS am_law_jorei_pref_run_log (
    run_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    pref_attempted     INTEGER NOT NULL DEFAULT 0,
    pref_ok            INTEGER NOT NULL DEFAULT 0,
    rows_upserted      INTEGER NOT NULL DEFAULT 0,
    rows_skipped       INTEGER NOT NULL DEFAULT 0,
    error_text         TEXT
);

CREATE INDEX IF NOT EXISTS idx_jorei_pref_run_log_started
    ON am_law_jorei_pref_run_log(started_at DESC);

-- Operator view: per-prefecture density snapshot.
DROP VIEW IF EXISTS v_law_jorei_pref_density;
CREATE VIEW v_law_jorei_pref_density AS
SELECT
    prefecture_code,
    prefecture_name,
    COUNT(*) AS row_count,
    MAX(enacted_date) AS most_recent_enacted,
    MAX(fetched_at) AS most_recent_fetch
FROM am_law_jorei_pref
GROUP BY prefecture_code, prefecture_name
ORDER BY prefecture_code ASC;

COMMIT;
