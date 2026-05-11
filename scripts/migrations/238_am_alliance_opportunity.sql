-- target_db: autonomath
-- migration: 238_am_alliance_opportunity
-- generated_at: 2026-05-12
-- author: Wave 34 Axis 4d — weekly precomputed alliance opportunity per houjin
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- houjin × alliance_partner (top 10 候補 法人) を weekly で固定。
-- 既存 採択事例 2,286 + 共同申請 pattern + 業種 chain を join して
-- alliance opportunity score を 0-100 で算出。
--
-- score 構成 (合計 100):
--   * 0..40  co_adoption_history
--   * 0..25  industry_chain_match
--   * 0..20  size_balance
--   * 0..10  region_proximity
--   * 0..5   compat_with_programs

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS am_alliance_opportunity (
    houjin_bangou TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 10),
    partner_houjin_bangou TEXT NOT NULL,
    partner_primary_name TEXT,
    alliance_score_0_100 INTEGER NOT NULL CHECK (alliance_score_0_100 BETWEEN 0 AND 100),
    co_adoption_subscore INTEGER NOT NULL DEFAULT 0 CHECK (co_adoption_subscore BETWEEN 0 AND 40),
    industry_chain_subscore INTEGER NOT NULL DEFAULT 0 CHECK (industry_chain_subscore BETWEEN 0 AND 25),
    size_balance_subscore INTEGER NOT NULL DEFAULT 0 CHECK (size_balance_subscore BETWEEN 0 AND 20),
    region_proximity_subscore INTEGER NOT NULL DEFAULT 0 CHECK (region_proximity_subscore BETWEEN 0 AND 10),
    compat_with_programs_subscore INTEGER NOT NULL DEFAULT 0 CHECK (compat_with_programs_subscore BETWEEN 0 AND 5),
    co_adoption_count INTEGER NOT NULL DEFAULT 0,
    industry_chain_pair TEXT,
    region_a TEXT,
    region_b TEXT,
    reason_json TEXT,
    refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (houjin_bangou, rank),
    CHECK (houjin_bangou <> partner_houjin_bangou)
);

CREATE INDEX IF NOT EXISTS idx_am_alliance_opportunity_score
    ON am_alliance_opportunity(alliance_score_0_100 DESC, houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_am_alliance_opportunity_partner
    ON am_alliance_opportunity(partner_houjin_bangou, alliance_score_0_100 DESC);

CREATE INDEX IF NOT EXISTS idx_am_alliance_opportunity_refreshed
    ON am_alliance_opportunity(refreshed_at);

CREATE TABLE IF NOT EXISTS am_alliance_opportunity_refresh_log (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    houjin_count INTEGER NOT NULL DEFAULT 0,
    partner_pairs_written INTEGER NOT NULL DEFAULT 0,
    skipped_no_co_adoption INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_alliance_opportunity_refresh_log_started
    ON am_alliance_opportunity_refresh_log(started_at DESC);

COMMIT;
