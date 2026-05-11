-- target_db: autonomath
-- migration: 232_program_risk_4d
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2b — 4-axis program-risk precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- For every (program × 業法 fence × enforcement pattern × revocation reason)
-- cell, persist a 0-100 risk score the GET /v1/programs/{id}/risk endpoint
-- can return in O(1). Inputs are existing tables:
--   * am_enforcement_detail (22,258 rows) — issuing_authority, kind, reason.
--   * nta_tsutatsu_index (3,221 rows) — 通達 reference → revocation reason
--     surface (税理士法/会計士法 boundary text excerpts).
--   * programs (11,601 rows) — primary metadata + tier + program_kind.
-- The 8 業法 enum mirrors the existing `_business_law_detector` surface
-- (税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1 / 弁護士法 §72 /
--  司法書士法 §3 / 社労士法 §27 / 弁理士法 §75 / 宅建業法 §47).
--
-- Why precompute (not a runtime aggregate)
-- ----------------------------------------
-- * 11,601 × 8 × 1,185 (distinct enforcement patterns) × N (revocation
--   reasons) per-call would be ~110M rows scanned per /risk lookup —
--   well past the 1s budget the customer-LLM round-trip expects.
-- * Weighted score depends on `am_enforcement_detail` cardinality —
--   re-evaluating live would also race against the nightly ETL backfill.
-- * Memory `feedback_no_quick_check_on_huge_sqlite` forbids full-scan
--   ops at runtime; precompute path is one daily job.
--
-- Schema
-- ------
-- * id                  — autoincrement PRIMARY KEY.
-- * program_id          — unified_id reference (programs.unified_id).
--                         No hard FK (programs is in jpintel.db; soft ref).
-- * gyouhou_id          — one of the 8 業法 enum (str), or 'none' when no
--                         sensitive boundary applies.
-- * enforcement_pattern_id — surrogate id grouping enforcement rows by
--                            (enforcement_kind, issuing_authority).
--                            NULL when no enforcement signal yet.
-- * revocation_reason_id — surrogate id from nta_tsutatsu_index code,
--                          NULL when no 通達 reference applies.
-- * risk_score_0_100    — weighted average (see cron impl for weights).
-- * evidence_json       — JSON object listing the underlying row ids:
--                         {"enforcement_ids": [...], "tsutatsu_codes": [...],
--                          "weights": {"gyouhou": 0.5, "enforcement": 0.3,
--                                      "tsutatsu": 0.2}}.
-- * last_refreshed_at   — ISO-8601 UTC.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_risk_4d (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id             TEXT NOT NULL,
    gyouhou_id             TEXT NOT NULL DEFAULT 'none',
    enforcement_pattern_id INTEGER,
    revocation_reason_id   INTEGER,
    risk_score_0_100       INTEGER NOT NULL DEFAULT 0,
    evidence_json          TEXT NOT NULL DEFAULT '{}',
    last_refreshed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT ck_risk_4d_gyouhou CHECK (gyouhou_id IN (
        'none',
        'zeirishi_52',
        'kaikei_47no2',
        'gyouseishoshi_1',
        'bengoshi_72',
        'shihoushoshi_3',
        'sharoushi_27',
        'benrishi_75',
        'takkengyou_47'
    )),
    CONSTRAINT ck_risk_4d_score CHECK (
        risk_score_0_100 >= 0 AND risk_score_0_100 <= 100
    )
);

-- Primary hot-path index: GET /v1/programs/{id}/risk returns top-1 by
-- score for the given program. Ordered DESC on score for fast tip-of-list.
CREATE INDEX IF NOT EXISTS idx_program_risk_4d_program_score
    ON am_program_risk_4d(program_id, risk_score_0_100 DESC);

-- Per-gyouhou histogram (operator dashboard: which 業法 fence trips most).
CREATE INDEX IF NOT EXISTS idx_program_risk_4d_gyouhou
    ON am_program_risk_4d(gyouhou_id, risk_score_0_100 DESC);

-- Staleness sweep.
CREATE INDEX IF NOT EXISTS idx_program_risk_4d_refresh
    ON am_program_risk_4d(last_refreshed_at);

-- Unique constraint on the 4-tuple — INSERT OR REPLACE in cron.
CREATE UNIQUE INDEX IF NOT EXISTS ux_program_risk_4d_tuple
    ON am_program_risk_4d(
        program_id,
        gyouhou_id,
        COALESCE(enforcement_pattern_id, -1),
        COALESCE(revocation_reason_id, -1)
    );

-- Operator view: top-N risky programs (across all gyouhou + patterns).
DROP VIEW IF EXISTS v_program_risk_4d_top;
CREATE VIEW v_program_risk_4d_top AS
SELECT
    program_id,
    MAX(risk_score_0_100) AS top_score,
    COUNT(*) AS scored_cells,
    GROUP_CONCAT(DISTINCT gyouhou_id) AS gyouhou_set
FROM am_program_risk_4d
GROUP BY program_id
ORDER BY top_score DESC;
