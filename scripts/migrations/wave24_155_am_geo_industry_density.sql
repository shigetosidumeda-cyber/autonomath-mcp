-- target_db: autonomath
-- migration wave24_155_am_geo_industry_density
--
-- 47 prefecture × 22 JSIC major density matrix (1,034 cells).
-- Uses 20 standard JSIC majors (A..T) + 2 admin buckets:
--   * 'U' = unclassified / cross-industry
--   * 'V' = horizontal (all industries)
--
-- Columns mirror the user spec; the 0-row legacy shape already
-- shipped under wave24_104 with one extra column (loan_count) which
-- we keep for forward-compat. CREATE IF NOT EXISTS so this reapply
-- is a no-op when the legacy shape is present.
--
-- Population is performed by the companion populate script (run
-- from entrypoint or one-shot ETL); this file only owns the schema.
--
-- DOWN: scripts/migrations/wave24_155_am_geo_industry_density_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_geo_industry_density (
    prefecture_code     TEXT NOT NULL,
    jsic_major          TEXT NOT NULL,
    program_count       INTEGER NOT NULL DEFAULT 0,
    program_tier_S      INTEGER NOT NULL DEFAULT 0,
    program_tier_A      INTEGER NOT NULL DEFAULT 0,
    verified_count      INTEGER NOT NULL DEFAULT 0,
    adoption_count      INTEGER NOT NULL DEFAULT 0,
    enforcement_count   INTEGER NOT NULL DEFAULT 0,
    loan_count          INTEGER NOT NULL DEFAULT 0,
    density_score       REAL,
    last_updated        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (prefecture_code, jsic_major)
);

CREATE INDEX IF NOT EXISTS idx_agid_pref
    ON am_geo_industry_density(prefecture_code);

CREATE INDEX IF NOT EXISTS idx_agid_jsic
    ON am_geo_industry_density(jsic_major);

CREATE INDEX IF NOT EXISTS idx_agid_density
    ON am_geo_industry_density(density_score DESC);

-- Seed the 22 JSIC majors (20 standard + U / V admin buckets).
-- Idempotent: INSERT OR IGNORE so re-runs are safe.
INSERT OR IGNORE INTO am_industry_jsic (jsic_code, jsic_level, jsic_name_ja, jsic_name_en, parent_code, note)
VALUES
    ('U', 'major', '不明・未分類',           'Unclassified',           NULL, 'admin bucket for density matrix'),
    ('V', 'major', '横断（全業種対象）', 'Horizontal (all industries)', NULL, 'admin bucket for density matrix');
