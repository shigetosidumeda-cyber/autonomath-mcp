-- target_db: autonomath
-- migration wave24_131_am_houjin_360_snapshot (MASTER_PLAN_v1 章
-- 10.2.6 — 法人 × 月 360° スナップショット事前計算)
--
-- Why this exists:
--   `get_houjin_360_snapshot_history` (#102, sensitive=YES) and
--   `get_compliance_risk_score` (#113, sensitive=YES) need a frozen
--   monthly snapshot of every metric we expose for a houjin so that
--   the time-series surface is honest. Without this, every read
--   would be "current value" projected backwards — a hallucination
--   under §10.10 fact-check.
--
--   100,000 cohort houjin × 12 months ≈ 1.2 M rows × ~5 KB JSON
--   ≈ 6 GB / year (受容、master plan §10.x risk row).
--
-- Schema:
--   * houjin_bangou TEXT NOT NULL
--   * snapshot_month TEXT NOT NULL                  — YYYY-MM
--   * adoption_count INTEGER                        — 累積採択数
--   * adoption_total_man_yen REAL                   — 累積交付総額
--   * enforcement_count INTEGER                     — 累積行政処分件数
--   * enforcement_amount_yen INTEGER                — 累積罰金 / 課徴金
--   * invoice_registered INTEGER                    — 0/1, 適格事業者登録
--   * compliance_score REAL                         — 0..1 derived
--   * risk_score REAL                               — 0..1 derived
--   * subsidy_eligibility_count INTEGER             — 同月時点で適用可能な制度数
--   * tax_credit_potential_man_yen REAL             — 同月時点で見込まれる税額控除合計
--   * payload_json TEXT                             — JSON blob: full 360° snapshot
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE (houjin_bangou, snapshot_month)
--
-- Indexes:
--   * (houjin_bangou, snapshot_month DESC) — primary read pattern
--     for #102 history.
--   * (snapshot_month, risk_score DESC) — KPI roll-up "highest-risk
--     houjin in 2026-05".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, monthly cron uses INSERT OR REPLACE
--   under UNIQUE.
--
-- DOWN:
--   See companion `wave24_131_am_houjin_360_snapshot_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_houjin_360_snapshot (
    snapshot_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou                TEXT NOT NULL,
    snapshot_month               TEXT NOT NULL,
    adoption_count               INTEGER,
    adoption_total_man_yen       REAL,
    enforcement_count            INTEGER,
    enforcement_amount_yen       INTEGER,
    invoice_registered           INTEGER CHECK (invoice_registered IS NULL OR
                                                invoice_registered IN (0, 1)),
    compliance_score             REAL CHECK (compliance_score IS NULL OR
                                             (compliance_score >= 0.0 AND
                                              compliance_score <= 1.0)),
    risk_score                   REAL CHECK (risk_score IS NULL OR
                                             (risk_score >= 0.0 AND risk_score <= 1.0)),
    subsidy_eligibility_count    INTEGER,
    tax_credit_potential_man_yen REAL,
    payload_json                 TEXT,
    computed_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (houjin_bangou, snapshot_month)
);

CREATE INDEX IF NOT EXISTS idx_ah360s_houjin_month
    ON am_houjin_360_snapshot(houjin_bangou, snapshot_month DESC);

CREATE INDEX IF NOT EXISTS idx_ah360s_month_risk
    ON am_houjin_360_snapshot(snapshot_month, risk_score DESC)
    WHERE risk_score IS NOT NULL;
