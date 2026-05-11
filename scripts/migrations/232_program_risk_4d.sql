-- target_db: autonomath
-- migration: 232_program_risk_4d
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2b — 4-axis program-risk precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- For every (program × 業法 fence × enforcement pattern × revocation
-- reason) cell where evidence exists, persist a 0-100 weighted risk score
-- + evidence_json so GET /v1/programs/{id}/risk returns O(1).
--
-- Weight: 0.5 * gyouhou_severity_0_100 + 0.3 * enforcement + 0.2 * tsutatsu.
-- 8 業法 enum mirrors `_business_law_detector` (税理士法 §52 etc).
--
-- Schema
-- ------
-- id                       PK
-- program_id               unified_id (soft ref jpintel.programs)
-- gyouhou_id               'none' or 1 of 8 enum
-- enforcement_pattern_id   surrogate per (kind, authority) tuple
-- revocation_reason_id     surrogate per nta_tsutatsu_index.code
-- risk_score_0_100         clamped [0,100]
-- evidence_json            {enforcement_ids, tsutatsu_codes, weights}
-- last_refreshed_at        ISO-8601 UTC

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

CREATE INDEX IF NOT EXISTS idx_program_risk_4d_program_score
    ON am_program_risk_4d(program_id, risk_score_0_100 DESC);
CREATE INDEX IF NOT EXISTS idx_program_risk_4d_gyouhou
    ON am_program_risk_4d(gyouhou_id, risk_score_0_100 DESC);
CREATE INDEX IF NOT EXISTS idx_program_risk_4d_refresh
    ON am_program_risk_4d(last_refreshed_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_program_risk_4d_tuple
    ON am_program_risk_4d(
        program_id,
        gyouhou_id,
        COALESCE(enforcement_pattern_id, -1),
        COALESCE(revocation_reason_id, -1)
    );

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
