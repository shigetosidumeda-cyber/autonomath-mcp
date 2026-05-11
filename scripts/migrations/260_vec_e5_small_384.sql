-- target_db: autonomath
-- migration: 260_vec_e5_small_384
-- generated_at: 2026-05-12
-- author: Wave 43.2.1 — Dim A semantic 検索 (e5-small embed + cross-encoder reranker + hybrid search)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Wave 43.2.1 introduces a 384-dim sqlite-vec virtual table backing
-- `intfloat/multilingual-e5-small` (local sentence-transformers) for
-- the full 503,930+ am_entities corpus. Migration 147 covered the
-- legacy 1024-dim e5-large 7 tier suffix family; migration 166 covered
-- the canonical 3-corpus 1024-dim layer. Wave 43.2.1 builds a parallel
-- 384-dim layer that is (a) 2.67x smaller than e5-large and (b)
-- exposed to the new POST /v1/search/semantic hybrid + RRF + reranker
-- endpoint.
--
-- Sister cache layer: am_entities_vec_reranker_score persists the
-- cross-encoder (MS-MARCO-MiniLM-L-6-v2 local) score for top 50 → top
-- 10 reranker steps so subsequent identical (query × candidate) pairs
-- do not re-pay the cross-encoder inference cost.
--
-- Pre-condition: sqlite-vec extension load already wired in
-- src/jpintel_mcp/db/session.py:104 (runtime) and
-- tools/offline/batch_embedding_refresh.py (offline). NO new
-- extension load is introduced here.
--
-- NO LLM API import: this migration applies pure SQL only. The
-- sentence-transformers + cross-encoder local inference happens in
-- scripts/etl/build_e5_embeddings_v2.py (offline ETL) and in the
-- production REST handler (local CPU inference, no network).

PRAGMA foreign_keys = OFF;

BEGIN;

-- ---------------------------------------------------------------
-- 1. 384-dim sqlite-vec virtual table for e5-small embeddings.
-- ---------------------------------------------------------------
-- vec0 syntax is not compatible with `CREATE VIRTUAL TABLE IF NOT
-- EXISTS` on some sqlite-vec releases. The entrypoint.sh §4 boot
-- loop tolerates IF-NOT-EXISTS gracefully; on older releases the
-- runtime `ensure_vec_table_e5` helper in semantic_search_v2.py
-- re-issues the CREATE without IF NOT EXISTS inside a savepoint.
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_e5 USING vec0(
    entity_id INTEGER PRIMARY KEY,
    embedding float[384]
);

-- ---------------------------------------------------------------
-- 2. Cross-encoder reranker score cache.
-- ---------------------------------------------------------------
-- (query_hash, candidate_entity_id) → score in [-10, 10]. The score is
-- computed by MS-MARCO-MiniLM-L-6-v2 local inference (NO LLM API).
-- query_hash is SHA-256(query_lower_stripped) — stable across runs.
CREATE TABLE IF NOT EXISTS am_entities_vec_reranker_score (
    query_hash       TEXT    NOT NULL,
    entity_id_a      INTEGER NOT NULL,
    entity_id_b      INTEGER NOT NULL,
    score            REAL    NOT NULL CHECK (score >= -10.0 AND score <= 10.0),
    model_name       TEXT    NOT NULL DEFAULT 'cross-encoder/ms-marco-MiniLM-L-6-v2',
    computed_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (query_hash, entity_id_a, entity_id_b)
);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_reranker_score_entity_a
    ON am_entities_vec_reranker_score(entity_id_a, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_reranker_score_entity_b
    ON am_entities_vec_reranker_score(entity_id_b, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_reranker_score_computed
    ON am_entities_vec_reranker_score(computed_at DESC);

-- ---------------------------------------------------------------
-- 3. e5-small embed log table (sister of am_entities_vec_embed_log).
-- ---------------------------------------------------------------
-- Tracks which entities have been embedded with e5-small + when +
-- what text-hash. The batch driver writes here and uses text-hash
-- diff to decide whether to re-embed on incremental runs.
CREATE TABLE IF NOT EXISTS am_entities_vec_e5_embed_log (
    entity_id        INTEGER NOT NULL,
    canonical_id     TEXT,
    record_kind      TEXT,
    embed_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    embed_dim        INTEGER NOT NULL DEFAULT 384 CHECK (embed_dim = 384),
    model_name       TEXT    NOT NULL DEFAULT 'intfloat/multilingual-e5-small',
    model_version    TEXT,
    text_hash        TEXT,
    text_byte_len    INTEGER,
    PRIMARY KEY (entity_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_e5_embed_log_kind
    ON am_entities_vec_e5_embed_log(record_kind, embed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_e5_embed_log_at
    ON am_entities_vec_e5_embed_log(embed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_e5_embed_log_canonical
    ON am_entities_vec_e5_embed_log(canonical_id, embed_at DESC);

-- ---------------------------------------------------------------
-- 4. Refresh log (sister of am_entities_vec_refresh_log).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_entities_vec_e5_refresh_log (
    refresh_id           TEXT    PRIMARY KEY,
    mode                 TEXT    NOT NULL CHECK (mode IN ('full','incremental','resume')),
    started_at           TEXT    NOT NULL,
    finished_at          TEXT,
    entities_processed   INTEGER NOT NULL DEFAULT 0,
    entities_skipped     INTEGER NOT NULL DEFAULT 0,
    entities_failed      INTEGER NOT NULL DEFAULT 0,
    embed_dim            INTEGER NOT NULL DEFAULT 384,
    model_name           TEXT    NOT NULL DEFAULT 'intfloat/multilingual-e5-small',
    error_text           TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_e5_refresh_log_started
    ON am_entities_vec_e5_refresh_log(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_e5_refresh_log_mode
    ON am_entities_vec_e5_refresh_log(mode, started_at DESC);

COMMIT;
