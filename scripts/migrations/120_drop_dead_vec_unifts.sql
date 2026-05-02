-- target_db: autonomath
-- boot_time: manual
-- migration 120 — drop DEAD vec + unicode-FTS tables (perf audit 2026-04-30)
--
-- Why:
--   Per docs/_internal/performance_audit_2026-04-30.md, am_vec_* and
--   am_entities_fts_uni_* tables in autonomath.db consume ~1.25 GB +
--   external vec0 chunk pages (~660 MB) for ZERO production reads.
--
--   References surveyed (2026-04-30):
--     - src/jpintel_mcp/_archive/embedding_2026-04-25/   ← archived
--     - src/jpintel_mcp/_archive/reasoning_2026-04-25/   ← archived
--     - scripts/rebuild_am_entities_fts.py               ← one-shot, NOT cron
--     - scripts/populate_tier_b_vec.py                   ← one-shot, NOT cron
--     - 0 hits in src/jpintel_mcp/api/, src/jpintel_mcp/mcp/, scripts/cron/,
--       .github/workflows/, server.json, smithery.yaml.
--
--   The active FTS path uses `am_entities_fts` (trigram) which is HOT.
--   The unicode-FTS variant (`am_entities_fts_uni*`) was a parallel
--   experiment never wired into routes.
--
-- Recovery:
--   If a future feature needs vector search, regenerate via the existing
--   one-shot scripts (rebuild_am_entities_fts.py + populate_tier_b_vec.py)
--   or the migration that originally created these tables. The schema is
--   fully derivable from am_entities + am_entity_facts.
--
-- Idempotency:
--   `DROP TABLE IF EXISTS` × 30 — re-run on already-clean DB is a no-op.
--
-- Performance impact (after VACUUM, runs separately because VACUUM cannot
-- run inside a transaction):
--   - autonomath.db: 9.4 GB → ~7.5 GB (-20%)
--   - Fly volume: same proportional shrink
--   - SHA256 verify on boot: ~6 min → ~5 min (faster R2 download too)
--   - integrity_check: ~25 min → ~20 min
--
-- Rollback companion: 120_drop_dead_vec_unifts_rollback.sql does NOT exist
-- because re-creating these tables is via the original ETL scripts, not
-- a single SQL statement.

PRAGMA foreign_keys = OFF;

-- am_entities_fts_uni* (unicode61 FTS variant — parallel to trigram FTS, never wired)
DROP TABLE IF EXISTS am_entities_fts_uni;
DROP TABLE IF EXISTS am_entities_fts_uni_data;
DROP TABLE IF EXISTS am_entities_fts_uni_idx;
DROP TABLE IF EXISTS am_entities_fts_uni_content;
DROP TABLE IF EXISTS am_entities_fts_uni_docsize;
DROP TABLE IF EXISTS am_entities_fts_uni_config;

-- am_vec_rowid_map (shared rowid mapping for the vec families below)
DROP TABLE IF EXISTS am_vec_rowid_map;

-- am_vec_tier_a (sqlite-vec virtual + companion tables — top-level entity vectors)
DROP TABLE IF EXISTS am_vec_tier_a;
DROP TABLE IF EXISTS am_vec_tier_a_chunks;
DROP TABLE IF EXISTS am_vec_tier_a_info;
DROP TABLE IF EXISTS am_vec_tier_a_rowids;
DROP TABLE IF EXISTS am_vec_tier_a_vector_chunks00;

-- am_vec_tier_b_* (5 attribute-specific vector indexes: dealbreakers,
-- eligibility, exclusions, obligations, the parallel reasoning experiment)
DROP TABLE IF EXISTS am_vec_tier_b_dealbreakers;
DROP TABLE IF EXISTS am_vec_tier_b_dealbreakers_chunks;
DROP TABLE IF EXISTS am_vec_tier_b_dealbreakers_info;
DROP TABLE IF EXISTS am_vec_tier_b_dealbreakers_rowids;
DROP TABLE IF EXISTS am_vec_tier_b_dealbreakers_vector_chunks00;

DROP TABLE IF EXISTS am_vec_tier_b_eligibility;
DROP TABLE IF EXISTS am_vec_tier_b_eligibility_chunks;
DROP TABLE IF EXISTS am_vec_tier_b_eligibility_info;
DROP TABLE IF EXISTS am_vec_tier_b_eligibility_rowids;
DROP TABLE IF EXISTS am_vec_tier_b_eligibility_vector_chunks00;

DROP TABLE IF EXISTS am_vec_tier_b_exclusions;
DROP TABLE IF EXISTS am_vec_tier_b_exclusions_chunks;
DROP TABLE IF EXISTS am_vec_tier_b_exclusions_info;
DROP TABLE IF EXISTS am_vec_tier_b_exclusions_rowids;
DROP TABLE IF EXISTS am_vec_tier_b_exclusions_vector_chunks00;

DROP TABLE IF EXISTS am_vec_tier_b_obligations;
DROP TABLE IF EXISTS am_vec_tier_b_obligations_chunks;
DROP TABLE IF EXISTS am_vec_tier_b_obligations_info;
DROP TABLE IF EXISTS am_vec_tier_b_obligations_rowids;
DROP TABLE IF EXISTS am_vec_tier_b_obligations_vector_chunks00;

PRAGMA foreign_keys = ON;

-- VACUUM is run separately (cannot be inside a transaction).
-- See scripts/cron/post_drop_vacuum.py for the post-DROP rebuild step.
