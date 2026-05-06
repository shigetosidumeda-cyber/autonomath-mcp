-- target_db: autonomath
-- migration wave24_126_am_recommended_programs (MASTER_PLAN_v1 章 10.2.1 —
-- 法人 → 推奨制度 TOP 10 事前計算テーブル)
--
-- Why this exists:
--   `recommend_programs_for_houjin` (#97, billing=1, sensitive=YES)
--   must NOT call any LLM at request time (memory
--   `feedback_no_operator_llm_api`). The recommender's TOP 10
--   per-houjin output is computed offline by
--   `scripts/etl/precompute_recommended_programs.py` (subagent
--   batch) and stored here for SELECT-only retrieval.
--
--   Recompute cadence: weekly Sun 03:00 JST, full rebuild for the
--   100,000 cohort houjin.
--
-- Schema:
--   * houjin_bangou TEXT NOT NULL  — 13-digit 法人番号 (NTA canonical)
--   * program_unified_id TEXT NOT NULL  — joins to jpi_programs.unified_id
--   * rank INTEGER NOT NULL  — 1..N (typically 1..10)
--   * score REAL NOT NULL    — composite recommendation score 0..1
--   * reason_json TEXT       — JSON per-tool: {match_factors:[...], evidence:[...]}
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * source_snapshot_id TEXT  — corpus checksum at compute time, audit
--
--   PRIMARY KEY (houjin_bangou, program_unified_id) so the upsert
--   surface uses `INSERT OR REPLACE`. CHECK (rank > 0) keeps
--   pathological negatives out.
--
-- Indexes:
--   * (houjin_bangou, rank) for "top N for this houjin" hot path.
--   * (program_unified_id) for reverse lookup "which houjin was
--     this program recommended to".
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS, no
--   DML. Cron uses INSERT OR REPLACE for upserts.
--
-- DOWN:
--   See companion `wave24_126_am_recommended_programs_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_recommended_programs (
    houjin_bangou      TEXT NOT NULL,
    program_unified_id TEXT NOT NULL,
    rank               INTEGER NOT NULL CHECK (rank > 0),
    score              REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    reason_json        TEXT,
    computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    source_snapshot_id TEXT,
    PRIMARY KEY (houjin_bangou, program_unified_id)
);

-- "Top N for this houjin" — primary read pattern of #97.
CREATE INDEX IF NOT EXISTS idx_arp_houjin_rank
    ON am_recommended_programs(houjin_bangou, rank);

-- Reverse lookup: "which 法人 has this program in their TOP 10".
CREATE INDEX IF NOT EXISTS idx_arp_program
    ON am_recommended_programs(program_unified_id);
