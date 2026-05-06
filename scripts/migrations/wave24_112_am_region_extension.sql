-- target_db: autonomath
-- migration wave24_112_am_region_extension (MASTER_PLAN_v1 章 10.1.c —
-- am_region 拡張 + 業種密度 KPI)
--
-- Why this exists:
--   `am_region` (1,966 rows, all 5-digit JIS X 0401/0402 codes)
--   today carries population_exact + household_count but lacks the
--   socio-economic columns that `get_industry_program_density` (#117)
--   needs to normalize "制度密度" against. We add:
--
--     * gdp_million_yen / business_count / business_count_as_of —
--       drive industry-density normalization
--     * climate_zone — surfaces in agri / GX programs (寒冷地 / 中間地)
--     * latitude / longitude — geo proximity for "近隣地域 program"
--     * land_area_km2 — secondary normalizer
--
--   We also create the dedicated lookup table
--   `am_region_program_density` so that the hot path query
--   "given (region_code, jsic_major) what is the program-per-capita
--   metric" doesn't have to recompute aggregates at request time.
--
-- Schema additions to am_region (ALTER):
--   * gdp_million_yen INTEGER         — most recent prefectural / municipal GDP
--   * gdp_as_of TEXT                  — ISO date of the GDP figure
--   * gdp_source_url TEXT             — primary citation
--   * business_count INTEGER          — 経済センサス 事業所数
--   * business_count_as_of TEXT       — ISO date
--   * climate_zone TEXT               — 'temperate'|'cool'|'cold'|'subtropical'
--   * latitude REAL                   — centroid
--   * longitude REAL                  — centroid
--   * land_area_km2 REAL              — 国土地理院
--
--   `am_region_program_density` table:
--     * region_code TEXT NOT NULL
--     * jsic_major TEXT NOT NULL                — 'A'..'T'
--     * program_count INTEGER NOT NULL
--     * programs_per_million_yen_gdp REAL
--     * programs_per_business REAL
--     * percentile_in_prefecture REAL           — 0..1
--     * computed_at TEXT NOT NULL
--     * source_snapshot_id TEXT
--     * UNIQUE(region_code, jsic_major)
--
--   The aggregation cron is `scripts/cron/recompute_region_density.py`.
--   `INSERT OR REPLACE` is the upsert surface, gated by the UNIQUE.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN raises "duplicate column name" on re-run;
--   entrypoint.sh §4 swallows that OperationalError when the message
--   is exclusively "duplicate column" (lines 420-428). Same pattern
--   used by 049/101/105/106/119.
--
--   CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
--
-- DOWN:
--   See companion `wave24_112_am_region_extension_rollback.sql`.

PRAGMA foreign_keys = ON;

-- am_region socio-economic columns. Each ALTER is an independent
-- statement so a single duplicate-column failure on partial re-apply
-- still lets the remaining ALTERs land.
ALTER TABLE am_region ADD COLUMN gdp_million_yen INTEGER;
ALTER TABLE am_region ADD COLUMN gdp_as_of TEXT;
ALTER TABLE am_region ADD COLUMN gdp_source_url TEXT;
ALTER TABLE am_region ADD COLUMN business_count INTEGER;
ALTER TABLE am_region ADD COLUMN business_count_as_of TEXT;
ALTER TABLE am_region ADD COLUMN climate_zone TEXT;
ALTER TABLE am_region ADD COLUMN latitude REAL;
ALTER TABLE am_region ADD COLUMN longitude REAL;
ALTER TABLE am_region ADD COLUMN land_area_km2 REAL;

-- Density rollup table. JSIC major is letters A-T per JIS standard.
-- Note: a fuller `am_region_program_density` companion is also
-- declared in wave24_139 for the #117 hot path; that file is the
-- "logical" home per MASTER_PLAN §10.2.14, but the table is created
-- here too so the column-extension migration can exercise it
-- standalone in tests. Both CREATE TABLE statements are
-- IF NOT EXISTS-guarded and use the same column shape, so apply
-- order is irrelevant.
CREATE TABLE IF NOT EXISTS am_region_program_density (
    density_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code                      TEXT NOT NULL,
    jsic_major                       TEXT NOT NULL,
    program_count                    INTEGER NOT NULL DEFAULT 0,
    programs_per_million_yen_gdp     REAL,
    programs_per_business            REAL,
    percentile_in_prefecture         REAL,
    computed_at                      TEXT NOT NULL DEFAULT (datetime('now')),
    source_snapshot_id               TEXT,
    UNIQUE (region_code, jsic_major)
);

CREATE INDEX IF NOT EXISTS idx_arpd_region
    ON am_region_program_density(region_code);

CREATE INDEX IF NOT EXISTS idx_arpd_jsic
    ON am_region_program_density(jsic_major);

-- Bookkeeping by entrypoint.sh §4.
