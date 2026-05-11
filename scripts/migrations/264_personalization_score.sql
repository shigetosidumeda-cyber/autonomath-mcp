-- target_db: autonomath
-- migration: 264_personalization_score
-- generated_at: 2026-05-12
-- author: Wave 43.2.8 — Dim H personalization (client_profiles × industry pack × saved_search)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_personalization_score (
    score_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash        TEXT NOT NULL,
    client_id           INTEGER NOT NULL,
    program_id          TEXT NOT NULL,
    score               INTEGER NOT NULL DEFAULT 0,
    score_breakdown_json TEXT NOT NULL DEFAULT '{}',
    reasoning_json      TEXT NOT NULL DEFAULT '{}',
    industry_pack       TEXT,
    refreshed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (api_key_hash, client_id, program_id),
    CONSTRAINT ck_ps_score CHECK (score BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_pers_key_client_score
    ON am_personalization_score(api_key_hash, client_id, score DESC, refreshed_at DESC);

CREATE INDEX IF NOT EXISTS idx_pers_refresh
    ON am_personalization_score(api_key_hash, client_id, refreshed_at);

CREATE INDEX IF NOT EXISTS idx_pers_program
    ON am_personalization_score(program_id, score DESC);

CREATE TABLE IF NOT EXISTS am_personalization_refresh_log (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    profiles_scored     INTEGER NOT NULL DEFAULT 0,
    rows_upserted       INTEGER NOT NULL DEFAULT 0,
    rows_purged         INTEGER NOT NULL DEFAULT 0,
    errors_count        INTEGER NOT NULL DEFAULT 0,
    error_text          TEXT
);

CREATE INDEX IF NOT EXISTS idx_pers_refresh_log_started
    ON am_personalization_refresh_log(started_at DESC);

DROP VIEW IF EXISTS v_personalization_top10;
CREATE VIEW v_personalization_top10 AS
SELECT
    api_key_hash, client_id, program_id, score,
    industry_pack, score_breakdown_json, reasoning_json, refreshed_at
FROM am_personalization_score
WHERE score > 0
ORDER BY api_key_hash, client_id, score DESC, refreshed_at DESC;

COMMIT;
