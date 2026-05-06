-- target_db: autonomath
-- migration wave24_129_am_enforcement_industry_risk (MASTER_PLAN_v1
-- 章 10.2.4 — enforcement × JSIC 業種リスク事前計算)
--
-- Why this exists:
--   `forecast_enforcement_risk` (#100, sensitive=YES) returns
--   "given JSIC × region, what is the横展開 (cross-industry) risk
--   of regulatory enforcement". The score is computed by
--   `scripts/etl/precompute_enforcement_industry_risk.py` from
--   `am_enforcement_detail` (22,258 rows, 6,455 with houjin_bangou)
--   joined against JSIC mapping and region rollups.
--
--   We materialize per (jsic_major, jsic_middle, region_code,
--   risk_category) so the read path is one indexed lookup.
--
-- Schema:
--   * jsic_major  TEXT NOT NULL  — 'A'..'T'
--   * jsic_middle TEXT           — 2 桁 or NULL for major-only rows
--   * region_code TEXT           — 5-digit JIS or 'JP-NATION' for nation-wide
--   * risk_category TEXT NOT NULL  — 'fine' | 'subsidy_exclude' | 'grant_refund'
--                                    | 'admin_order' | 'naming_publish'
--   * incident_count INTEGER NOT NULL DEFAULT 0
--   * total_amount_yen INTEGER             — sum of am_enforcement_detail.amount_yen
--   * percentile_in_industry REAL          — 0..1, this region vs other regions
--   * trend_3yr_json TEXT                  — {y2024:N, y2025:N, y2026:N}
--   * source_snapshot_id TEXT
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE(jsic_major, jsic_middle, region_code, risk_category)
--
-- Indexes:
--   * (jsic_major, region_code) — primary lookup pattern.
--   * (region_code, risk_category) — region-side rollup.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. UNIQUE for `INSERT OR REPLACE`.
--
-- DOWN:
--   See companion `wave24_129_am_enforcement_industry_risk_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_enforcement_industry_risk (
    risk_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    jsic_major              TEXT NOT NULL CHECK (jsic_major IN (
                                'A','B','C','D','E','F','G','H','I','J',
                                'K','L','M','N','O','P','Q','R','S','T'
                            )),
    jsic_middle             TEXT,
    region_code             TEXT,
    risk_category           TEXT NOT NULL CHECK (risk_category IN (
                                'fine','subsidy_exclude','grant_refund',
                                'admin_order','naming_publish'
                            )),
    incident_count          INTEGER NOT NULL DEFAULT 0,
    total_amount_yen        INTEGER,
    percentile_in_industry  REAL,
    trend_3yr_json          TEXT,
    source_snapshot_id      TEXT,
    computed_at             TEXT NOT NULL DEFAULT (datetime('now')),
    -- COALESCE the nullable columns to a literal sentinel so the
    -- composite UNIQUE works (SQLite treats NULL as distinct in
    -- UNIQUE without this canonicalization).
    UNIQUE (jsic_major, jsic_middle, region_code, risk_category)
);

CREATE INDEX IF NOT EXISTS idx_aeir_jsic_region
    ON am_enforcement_industry_risk(jsic_major, region_code);

CREATE INDEX IF NOT EXISTS idx_aeir_region_cat
    ON am_enforcement_industry_risk(region_code, risk_category);
