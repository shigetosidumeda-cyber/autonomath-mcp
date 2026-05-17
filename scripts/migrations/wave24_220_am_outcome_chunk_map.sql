-- target_db: autonomath
-- migration: wave24_220_am_outcome_chunk_map
-- generated_at: 2026-05-17
-- author: GG4 — Top-100 chunk pre-mapped to Wave 60-94 outcome catalog 432
-- idempotent: every CREATE uses IF NOT EXISTS; pure DDL, no DML.
--
-- Purpose
-- -------
-- Pre-mapped retrieval cache: for each of the 432 Wave 60-94 outcomes,
-- the top-100 chunks (FAISS retrieval + cross-encoder rerank, computed
-- offline by scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py)
-- are pinned to a flat 43,200-row table. The MCP tool
-- ``get_outcome_chunks`` reads from this table directly, skipping the
-- live 2-stage FAISS+rerank pipeline. Expected p95: 20 ms vs ~150 ms
-- live (~7-8x faster) at the same ¥3/req tier.
--
-- Idempotency contract
-- --------------------
--   * PRIMARY KEY (outcome_id, rank) — re-running the offline pre-mapper
--     for the same outcome converges on the same 100 rows via
--     INSERT OR REPLACE.
--   * All indexes are CREATE INDEX IF NOT EXISTS.
--   * mapped_at is the producer's ISO-8601 timestamp so freshness of
--     each row is independently auditable.
--
-- LLM call: 0. Producer = local FAISS (IVF+PQ nprobe=8) + OSS BERT
-- cross-encoder (jpcite-cross-encoder-v1). Reader = SQLite SELECT only.
--
-- License posture
-- ---------------
-- chunk_id references the live chunk corpus produced by upstream lane
-- M9; no hard FK constraint is declared because M9 may be staged on a
-- separate DB / hosting. Soft-link semantics preserved by an index on
-- chunk_id for reverse lookup. Compose-time and serve-time LLM calls
-- are both zero.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_outcome_chunk_map — 432 outcome × top-100 chunk pre-mapped retrieval cache
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_outcome_chunk_map (
    outcome_id          INTEGER NOT NULL,                       -- Wave 60-94 catalog id (1..432)
    rank                INTEGER NOT NULL                        -- 1..100 (1 = best)
                          CHECK (rank >= 1 AND rank <= 100),
    chunk_id            INTEGER NOT NULL,                       -- logical chunk id (M9 corpus)
    score               REAL NOT NULL                           -- rerank score, 0.0..1.0
                          CHECK (score >= 0.0 AND score <= 1.0),
    mapped_at           TEXT NOT NULL,                          -- ISO-8601 UTC, producer-stamped
    PRIMARY KEY (outcome_id, rank)
);

-- Forward lookup: get top-N for a given outcome (the hot path).
CREATE INDEX IF NOT EXISTS ix_am_outcome_chunk_map_outcome_id
    ON am_outcome_chunk_map(outcome_id);

-- Reverse lookup: which outcomes does a chunk participate in (admin / debug).
CREATE INDEX IF NOT EXISTS ix_am_outcome_chunk_map_chunk_id
    ON am_outcome_chunk_map(chunk_id);
