-- target_db: autonomath
-- migration wave24_130_am_case_study_similarity (MASTER_PLAN_v1 章
-- 10.2.5 — 採択事例間 類似度 事前計算)
--
-- Why this exists:
--   `find_similar_case_studies` (#101) returns N nearest case_study
--   neighbors per query case. We precompute the kNN top 5 per case
--   from cosine over case-text embeddings (intfloat/multilingual-e5-large)
--   so the read path is a single indexed lookup.
--
--   2,286 case_studies → 11,430 rows total (5 per case). Recompute
--   weekly Sun 04:00 JST, full rebuild.
--
-- Schema (canonical-ordering):
--   * case_a INTEGER NOT NULL  — joins to case_studies.case_id
--   * case_b INTEGER NOT NULL  — joins to case_studies.case_id
--   * similarity REAL NOT NULL — cosine, 0..1
--   * shared_factors_json TEXT — JSON list e.g. ["jsic_E","amount_band_300_500","prefecture_match"]
--   * rank_a INTEGER           — case_b's rank inside case_a's neighbors (1..N)
--   * rank_b INTEGER           — case_a's rank inside case_b's neighbors (1..N)
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * CHECK(case_a < case_b)   — canonical ordering, half the rows
--   * PRIMARY KEY (case_a, case_b)
--
--   The CHECK + PK lets `INSERT OR IGNORE` be the safe upsert; we
--   write each unordered pair exactly once. Both rank_a and rank_b
--   are stored so the read path doesn't need to flip the join based
--   on which case was queried.
--
-- Indexes:
--   * (case_a, similarity DESC) — top-N from a side.
--   * (case_b, similarity DESC) — top-N from b side.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR IGNORE under the canonical
--   ordering CHECK + PK gives full re-run safety.
--
-- DOWN:
--   See companion `wave24_130_am_case_study_similarity_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_case_study_similarity (
    case_a               INTEGER NOT NULL,
    case_b               INTEGER NOT NULL,
    similarity           REAL NOT NULL CHECK (similarity >= 0.0 AND similarity <= 1.0),
    shared_factors_json  TEXT,
    rank_a               INTEGER,
    rank_b               INTEGER,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (case_a < case_b),
    PRIMARY KEY (case_a, case_b)
);

CREATE INDEX IF NOT EXISTS idx_acss_a_sim
    ON am_case_study_similarity(case_a, similarity DESC);

CREATE INDEX IF NOT EXISTS idx_acss_b_sim
    ON am_case_study_similarity(case_b, similarity DESC);
