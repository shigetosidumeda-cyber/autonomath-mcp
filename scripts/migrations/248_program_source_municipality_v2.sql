-- target_db: autonomath
-- migration: 248_program_source_municipality_v2
-- generated_at: 2026-05-12
-- author: Wave 43.1.1 - 市町村 1,700+ subsidy ETL v2 (+5,000 programs)
-- idempotent: every CREATE uses IF NOT EXISTS; pure additive (no DML).
--
-- target_db = autonomath: the v2 join sits in autonomath.db because the
-- canonical programs table lives there. Pure additive (CREATE TABLE/INDEX
-- IF NOT EXISTS) makes it boot-time safe via entrypoint.sh §4 self-heal.
--
-- LLM call: 0. Pure SQLite write. License posture: 自治体 = 政府著作物
-- §13 著作権法. Aggregator (noukaweb / hojyokin-portal / biz.stayway) banned.

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

CREATE INDEX IF NOT EXISTS idx_msv2_muni_grant
    ON am_program_source_municipality_v2(municipality_code, grant_type);

CREATE INDEX IF NOT EXISTS idx_msv2_pref_verified
    ON am_program_source_municipality_v2(prefecture_code, last_verified DESC);

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

-- schema_migrations bookkeeping is performed by scripts/migrate.py.
