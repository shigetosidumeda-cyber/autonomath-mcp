-- target_db: autonomath
-- migration: wave24_182_contributor_trust
-- generated_at: 2026-05-07
-- author: DEEP-33 Bayesian contributor trust score (CLV2-13 implementation)
-- idempotent: every CREATE uses IF NOT EXISTS; first-line target_db hint
--             routes this file to autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_33_contributor_trust_bayesian.md
--
-- DEEP-28 introduced `contribution_queue` for community first-source
-- contributions (税理士 / 公認会計士 / 司法書士 / 補助金 consultant /
-- anonymous walk-ins). DEEP-33 layers a Bayesian trust score on top
-- so that one contributor's reject history attenuates their effective
-- likelihood, and one verified contribution can spillover (partial)
-- to ~22K row-siblings in the same `am_amount_condition` cluster.
--
-- Field semantics
-- ---------------
-- id                       INTEGER PK AUTOINCREMENT
-- contributor_id           api_keys.id (authenticated path) OR
--                          salted SHA-256 hex of (IP+UA+nonce) for
--                          anonymous path. UNIQUE.
-- cohort                   CHECK enum:
--                            '税理士'
--                            '公認会計士'
--                            '司法書士'
--                            '補助金_consultant'
--                            'anonymous'
-- cumulative_contributions DEFAULT 0; total submissions count
-- cumulative_approved      DEFAULT 0; approved-status count
-- cumulative_rejected      DEFAULT 0; rejected-status count
-- latest_posterior_score   REAL CHECK (>=0.0 AND <=1.0); last computed
--                          posterior, cached so /v1/contribute/trust/{id}
--                          can return < 60ms even before recompute.
-- last_updated             TEXT (ISO 8601 UTC) of last recompute
-- temporal_decay_weight    e^(-λ × age_days), λ=0.005 (1-year half-life)
-- history_bonus            cumulative_approved boost, capped 0.15
--
-- Indexes:
--   * UNIQUE (contributor_id) — one row per contributor
--   * (cohort, latest_posterior_score DESC) — cohort leaderboard,
--     also drives §52-style trust transparency rollups.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- contributor_trust -- one row per (api_key OR anonymous_hash)
-- ============================================================================

CREATE TABLE IF NOT EXISTS contributor_trust (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    contributor_id           TEXT NOT NULL,
    cohort                   TEXT NOT NULL CHECK (cohort IN (
        '税理士',
        '公認会計士',
        '司法書士',
        '補助金_consultant',
        'anonymous'
    )),
    cumulative_contributions INTEGER NOT NULL DEFAULT 0
                             CHECK (cumulative_contributions >= 0),
    cumulative_approved      INTEGER NOT NULL DEFAULT 0
                             CHECK (cumulative_approved >= 0),
    cumulative_rejected      INTEGER NOT NULL DEFAULT 0
                             CHECK (cumulative_rejected >= 0),
    latest_posterior_score   REAL NOT NULL DEFAULT 0.0
                             CHECK (latest_posterior_score >= 0.0
                                    AND latest_posterior_score <= 1.0),
    last_updated             TEXT NOT NULL
                             DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    temporal_decay_weight    REAL NOT NULL DEFAULT 1.0
                             CHECK (temporal_decay_weight >= 0.0
                                    AND temporal_decay_weight <= 1.0),
    history_bonus            REAL NOT NULL DEFAULT 0.0
                             CHECK (history_bonus >= 0.0
                                    AND history_bonus <= 0.15)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_contributor_trust_uniq
    ON contributor_trust (contributor_id);

CREATE INDEX IF NOT EXISTS idx_contributor_trust_cohort_score
    ON contributor_trust (cohort, latest_posterior_score DESC);

-- ============================================================================
-- am_amount_condition.quality_flag CHECK relax companion
-- ============================================================================
-- DEEP-28 added 'community_verified'. DEEP-33 cluster spillover requires
-- 'community_partial_verified'. SQLite CHECK constraints cannot be ALTER'd
-- in place; the relax is best-effort: if `am_amount_condition` already
-- exists with the older CHECK, we register the additive flag in a
-- companion KV table so the application layer treats both forms as
-- equivalent. New deployments pick the relaxed CHECK directly.

CREATE TABLE IF NOT EXISTS contributor_trust_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO contributor_trust_meta (key, value) VALUES
    ('quality_flag.community_partial_verified.enabled', '1'),
    ('cohort.likelihood.税理士',                  '0.90'),
    ('cohort.likelihood.公認会計士',              '0.85'),
    ('cohort.likelihood.司法書士',                '0.85'),
    ('cohort.likelihood.補助金_consultant',       '0.75'),
    ('cohort.likelihood.anonymous',                '0.60'),
    ('verified_threshold',                         '0.95'),
    ('temporal_decay_lambda_per_day',              '0.005'),
    ('history_bonus_cap',                          '0.15'),
    ('reject_penalty_per_reject',                  '0.10'),
    ('reject_penalty_max',                         '0.30'),
    ('cluster_spillover_alpha',                    '0.30'),
    ('direct_verify_alpha',                        '1.00');

-- ============================================================================
-- View: cohort rollup (latest_posterior_score by cohort)
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_contributor_trust_cohort AS
SELECT cohort,
       COUNT(*) AS contributor_count,
       AVG(latest_posterior_score) AS avg_posterior,
       SUM(cumulative_contributions) AS total_contributions,
       SUM(cumulative_approved)      AS total_approved,
       SUM(cumulative_rejected)      AS total_rejected
  FROM contributor_trust
 GROUP BY cohort;

-- View: verified contributors only (posterior > 0.95)
CREATE VIEW IF NOT EXISTS v_contributor_trust_verified AS
SELECT id, contributor_id, cohort,
       cumulative_contributions, cumulative_approved,
       latest_posterior_score, history_bonus, last_updated
  FROM contributor_trust
 WHERE latest_posterior_score > 0.95;

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
