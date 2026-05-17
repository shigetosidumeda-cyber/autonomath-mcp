-- target_db: autonomath
-- Niche Moat Lane N2 — 法人 × 制度 portfolio gap analysis (2026-05-17).
--
-- Stores per-(houjin × program) applicability score precomputed by
-- ``scripts/etl/compute_portfolio_2026_05_17.py``. The script emits one
-- row per (houjin_bangou, program_id) pair that survives the sparse
-- filter, with a 0-100 score decomposed across five axes
-- (industry / size / region / sector / target_form), and joins
-- ``jpi_adoption_records`` for ``applied_status`` so downstream MCP tools
-- can return "未申請 top 20" and "申請済" lists without an extra JOIN.
--
-- Idempotent (CREATE IF NOT EXISTS only); safe to re-run on every boot.

CREATE TABLE IF NOT EXISTS am_houjin_program_portfolio (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou        TEXT NOT NULL,
    program_id           TEXT NOT NULL,
    applicability_score  REAL NOT NULL,
    score_industry       REAL NOT NULL DEFAULT 0.0,
    score_size           REAL NOT NULL DEFAULT 0.0,
    score_region         REAL NOT NULL DEFAULT 0.0,
    score_sector         REAL NOT NULL DEFAULT 0.0,
    score_target_form    REAL NOT NULL DEFAULT 0.0,
    applied_status       TEXT NOT NULL DEFAULT 'unknown',
    applied_at           TEXT,
    deadline             TEXT,
    deadline_kind        TEXT,
    priority_rank        INTEGER,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    method               TEXT NOT NULL DEFAULT 'lane_n2_deterministic_v1',
    notes                TEXT
);

CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin
    ON am_houjin_program_portfolio(houjin_bangou, applicability_score DESC);

CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin_priority
    ON am_houjin_program_portfolio(houjin_bangou, priority_rank ASC);

CREATE INDEX IF NOT EXISTS ix_am_hpp_houjin_unapplied
    ON am_houjin_program_portfolio(houjin_bangou, applied_status, applicability_score DESC);

CREATE INDEX IF NOT EXISTS ix_am_hpp_program
    ON am_houjin_program_portfolio(program_id, applicability_score DESC);

CREATE INDEX IF NOT EXISTS ix_am_hpp_deadline
    ON am_houjin_program_portfolio(deadline ASC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_am_hpp_houjin_program_method
    ON am_houjin_program_portfolio(houjin_bangou, program_id, method);

CREATE VIEW IF NOT EXISTS v_am_houjin_gap_top AS
    SELECT
        houjin_bangou,
        program_id,
        applicability_score,
        score_industry,
        score_size,
        score_region,
        score_sector,
        score_target_form,
        applied_status,
        deadline,
        deadline_kind,
        priority_rank,
        computed_at
      FROM am_houjin_program_portfolio
     WHERE applied_status = 'unapplied'
       AND priority_rank IS NOT NULL
       AND priority_rank <= 20
     ORDER BY houjin_bangou, priority_rank;
