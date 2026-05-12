-- target_db: autonomath
-- migration: 284_semantic_search_v1_rollback
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim A semantic_search legacy v1 storage layer (rollback)
-- idempotent: DROP IF EXISTS.

PRAGMA foreign_keys = OFF;

BEGIN;

DROP INDEX IF EXISTS idx_am_semantic_search_v1_log_searched_at;
DROP INDEX IF EXISTS idx_am_semantic_search_v1_log_query_hash;
DROP TABLE IF EXISTS am_semantic_search_v1_log;

DROP INDEX IF EXISTS idx_am_semantic_search_v1_cache_cached_at;
DROP TABLE IF EXISTS am_semantic_search_v1_cache;

COMMIT;

PRAGMA foreign_keys = ON;
