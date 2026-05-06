-- target_db: autonomath
-- migration 155 — am_geo_industry_density (W19-5 supply-side scoring substrate)
--
-- Why this exists:
--   W19-5 ships 1,034 (47 prefecture × 22 JSIC major) static SEO pages.
--   Static page <-> live data integrity needs a per-cell density score so
--   the page can show "高機会" / "空白市場" badges and bias the cohort
--   recommendation engine (geo × industry pillar in cohort #8 industry packs).
--
--   The actual JSIC major taxonomy in am_industry_jsic has 20 codes
--   (A..T) — not 22 — so the populated matrix is 47 × 20 = 940 cells.
--   The schema is unconstrained on the JSIC side so a future taxonomy
--   widening to 22 (e.g. splitting B/T) re-populates without DDL.
--
-- Schema:
--   am_geo_industry_density
--     prefecture_code    TEXT NOT NULL  -- 5-digit am_region prefecture code (01000..47000)
--     jsic_major         TEXT NOT NULL  -- 'A'..'T'
--     program_count      INTEGER        -- jpi_programs(prefecture, jsic-derived)
--     program_tier_S     INTEGER
--     program_tier_A     INTEGER
--     verified_count     INTEGER        -- proxy: tier IN ('S','A') AND source_url IS NOT NULL
--     adoption_count     INTEGER        -- jpi_adoption_records(prefecture, industry_jsic_medium)
--     enforcement_count  INTEGER        -- jpi_enforcement_cases(prefecture, jsic-derived)
--     loan_count         INTEGER        -- jpi_loan_programs prefecture-bound subset
--     density_score      REAL           -- 0..1 z-normalized weighted composite
--     last_updated       TEXT DEFAULT (datetime('now'))
--     PRIMARY KEY (prefecture_code, jsic_major)
--
-- Idempotency:
--   CREATE * IF NOT EXISTS only; populate script does INSERT OR REPLACE.
--
-- DOWN: companion 155_am_geo_industry_density_rollback.sql

PRAGMA foreign_keys = OFF;

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

CREATE INDEX IF NOT EXISTS idx_agid_pref     ON am_geo_industry_density(prefecture_code);
CREATE INDEX IF NOT EXISTS idx_agid_jsic     ON am_geo_industry_density(jsic_major);
CREATE INDEX IF NOT EXISTS idx_agid_density  ON am_geo_industry_density(density_score DESC);
