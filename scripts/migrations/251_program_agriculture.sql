-- target_db: autonomath
-- migration: 251_program_agriculture
-- generated_at: 2026-05-12
-- author: Wave 43.1.4 — MAFF 農水省 +3,000 programs (agri / fishery cohort)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_program_agriculture (
    program_agri_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id                TEXT,
    maff_id                   TEXT NOT NULL,
    agriculture_type          TEXT NOT NULL,
    crop_categories_json      TEXT,
    eligibility_target_types  TEXT,
    bureau_code               TEXT,
    title                     TEXT NOT NULL,
    deadline                  TEXT,
    amount_max_yen            INTEGER,
    source_url                TEXT NOT NULL,
    source_kind               TEXT NOT NULL DEFAULT 'maff',
    notes                     TEXT,
    refreshed_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_agri_type CHECK (
        agriculture_type IN ('耕種','畜産','林業','漁業','6次産業','一般')
    ),
    CONSTRAINT ck_agri_source_url CHECK (source_url LIKE 'https://%'),
    CONSTRAINT ck_agri_source_kind CHECK (
        source_kind IN ('maff','rinya','jfa','pref','other')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_program_agri_maff_id
    ON am_program_agriculture(maff_id, source_kind);
CREATE INDEX IF NOT EXISTS idx_program_agri_type
    ON am_program_agriculture(agriculture_type, refreshed_at DESC);
CREATE INDEX IF NOT EXISTS idx_program_agri_program_id
    ON am_program_agriculture(program_id) WHERE program_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_program_agri_bureau
    ON am_program_agriculture(bureau_code, refreshed_at DESC);
CREATE INDEX IF NOT EXISTS idx_program_agri_deadline
    ON am_program_agriculture(deadline) WHERE deadline IS NOT NULL;

CREATE TABLE IF NOT EXISTS am_program_agriculture_ingest_log (
    ingest_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    rows_seen      INTEGER NOT NULL DEFAULT 0,
    rows_upserted  INTEGER NOT NULL DEFAULT 0,
    rows_skipped   INTEGER NOT NULL DEFAULT 0,
    source_kind    TEXT,
    error_text     TEXT
);

CREATE INDEX IF NOT EXISTS idx_program_agri_ingest_log_started
    ON am_program_agriculture_ingest_log(started_at DESC);

DROP VIEW IF EXISTS v_program_agriculture_density;
CREATE VIEW v_program_agriculture_density AS
SELECT
    agriculture_type, bureau_code,
    COUNT(*) AS program_count,
    SUM(CASE WHEN deadline IS NOT NULL THEN 1 ELSE 0 END) AS dated_count,
    SUM(CASE WHEN amount_max_yen IS NOT NULL THEN 1 ELSE 0 END) AS amount_count,
    MAX(refreshed_at) AS last_refresh
FROM am_program_agriculture
GROUP BY agriculture_type, bureau_code
ORDER BY program_count DESC, agriculture_type ASC;

COMMIT;
