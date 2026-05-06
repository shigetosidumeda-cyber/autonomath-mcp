-- target_db: autonomath
-- migration 161 — am_enforcement_anomaly (per prefecture × JSIC major outlier flag)
--
-- Why this exists:
--   Surfaces (pref, industry) cells where 行政処分 incidence is statistically
--   abnormal vs the 47×22 grid mean. Used by the cohort #2/#3 (税理士/会計士)
--   compliance pillar and by enforcement-page anomaly badges. Pure SQL +
--   numpy z-score; NO LLM. anomaly_flag=1 iff z_score > 2.0.
--
-- Schema:
--   am_enforcement_anomaly
--     prefecture_code            TEXT NOT NULL  -- 5-digit am_region (01000..47000)
--     jsic_major                 TEXT NOT NULL  -- 'A'..'T' (taxonomy currently 20; up to 22 supported)
--     enforcement_count          INTEGER        -- aggregated cases for this cell
--     z_score                    REAL           -- (count - μ) / σ over all populated cells
--     anomaly_flag               INTEGER        -- 1 if z_score > 2.0
--     dominant_violation_kind    TEXT           -- top am_enforcement_detail.enforcement_kind for this cell
--     last_updated               TEXT DEFAULT (datetime('now'))
--     PRIMARY KEY (prefecture_code, jsic_major)
--
-- Idempotency:
--   CREATE * IF NOT EXISTS only; populator does INSERT OR REPLACE.
--
-- DOWN: companion 161_am_enforcement_anomaly_rollback.sql

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS am_enforcement_anomaly (
    prefecture_code         TEXT NOT NULL,
    jsic_major              TEXT NOT NULL,
    enforcement_count       INTEGER NOT NULL DEFAULT 0,
    z_score                 REAL,
    anomaly_flag            INTEGER NOT NULL DEFAULT 0,
    dominant_violation_kind TEXT,
    last_updated            TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (prefecture_code, jsic_major)
);

CREATE INDEX IF NOT EXISTS idx_aea_pref     ON am_enforcement_anomaly(prefecture_code);
CREATE INDEX IF NOT EXISTS idx_aea_jsic     ON am_enforcement_anomaly(jsic_major);
CREATE INDEX IF NOT EXISTS idx_aea_anomaly  ON am_enforcement_anomaly(anomaly_flag) WHERE anomaly_flag = 1;
CREATE INDEX IF NOT EXISTS idx_aea_z        ON am_enforcement_anomaly(z_score DESC);
