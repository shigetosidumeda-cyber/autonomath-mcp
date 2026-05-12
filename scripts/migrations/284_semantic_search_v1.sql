-- target_db: autonomath
-- migration: 284_semantic_search_v1
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim A semantic_search legacy v1 storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the legacy v1 path of the Dim A semantic search
-- surface. Migration 260 introduced the canonical v2 (e5-small 384-dim
-- sqlite-vec + cross-encoder reranker). Wave 47 PR #144 landed the v1
-- REST wrap (legacy hash-fallback embedding + JSON top-k cache) but
-- the storage layer was left implicit; this migration provides the
-- two tables the REST wrap reads/writes against so the v1 path is
-- 100% disk-backed and survives boot.
--
-- Two tables (separate write-shapes)
-- ----------------------------------
--   * am_semantic_search_v1_cache: write-rare-read-many top-K result
--     cache, keyed by cache_id (sha256 of normalized query_text). One
--     row per pre-warmed query (the top 100 queries baked by
--     scripts/etl/build_semantic_search_v1_cache.py).
--
--   * am_semantic_search_v1_log: append-only per-search latency + hit
--     log. Used for cache hit-rate KPI (TTFP) and for AI Mention Share
--     funnel reconciliation. Never PII — query_hash only, raw text NOT
--     stored on the log path.
--
-- v1 vs v2 separation
-- -------------------
-- v2 (migration 260) is the CANONICAL on-line path. v1 (this migration)
-- is the legacy hash-fallback path retained for two reasons:
--   1. Boot-time fallback when sqlite-vec extension fails to load
--      (entrypoint.sh §4 currently degrades silently — Wave 47 wires
--      the v1 cache as the graceful read-only fallback).
--   2. Long-tail query warm-cache (top 100 queries baked offline) so
--      ¥3/req can still serve a useful hit even when the vec0 table is
--      cold or absent.
-- These tables NEVER overlap with migration 260's am_entities_vec_e5
-- or am_entities_vec_reranker_score — disjoint name space, disjoint
-- write paths. Migration 260 is NOT mutated by this migration.
--
-- LLM-0 discipline (feedback_no_operator_llm_api)
-- -----------------------------------------------
-- Zero columns imply LLM inference. embedding is BLOB of float32
-- packed bytes (struct.pack format) produced by local sentence-
-- transformers or hash-fallback — never an LLM API. top_k_results is
-- a JSON array of {entity_id, score} pairs, no completion text.

PRAGMA foreign_keys = OFF;

BEGIN;

-- ---------------------------------------------------------------
-- 1. v1 top-K result cache (write-rare).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_semantic_search_v1_cache (
    cache_id         TEXT    PRIMARY KEY,
    query_text       TEXT    NOT NULL,
    embedding        BLOB    NOT NULL,
    embedding_dim    INTEGER NOT NULL DEFAULT 384 CHECK (embedding_dim > 0),
    top_k_results    TEXT    NOT NULL,
    top_k            INTEGER NOT NULL DEFAULT 10 CHECK (top_k >= 1 AND top_k <= 100),
    model_name       TEXT    NOT NULL DEFAULT 'hash-fallback-e5-small-v1',
    cached_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (length(top_k_results) > 0)
);

CREATE INDEX IF NOT EXISTS idx_am_semantic_search_v1_cache_cached_at
    ON am_semantic_search_v1_cache (cached_at);

-- ---------------------------------------------------------------
-- 2. v1 per-search latency + hit log (append-only).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_semantic_search_v1_log (
    search_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash       TEXT    NOT NULL,
    latency_ms       INTEGER NOT NULL CHECK (latency_ms >= 0),
    hit_count        INTEGER NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    cache_hit        INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0, 1)),
    searched_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_am_semantic_search_v1_log_query_hash
    ON am_semantic_search_v1_log (query_hash);

CREATE INDEX IF NOT EXISTS idx_am_semantic_search_v1_log_searched_at
    ON am_semantic_search_v1_log (searched_at);

COMMIT;

PRAGMA foreign_keys = ON;
