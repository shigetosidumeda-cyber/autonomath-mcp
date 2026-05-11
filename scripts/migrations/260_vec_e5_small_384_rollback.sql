-- target_db: autonomath
-- rollback: 260_vec_e5_small_384
-- generated_at: 2026-05-12

PRAGMA foreign_keys = OFF;

BEGIN;

DROP TABLE IF EXISTS am_entities_vec_e5;
DROP TABLE IF EXISTS am_entities_vec_reranker_score;
DROP TABLE IF EXISTS am_entities_vec_e5_embed_log;
DROP TABLE IF EXISTS am_entities_vec_e5_refresh_log;

COMMIT;
