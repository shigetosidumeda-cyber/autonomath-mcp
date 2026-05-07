-- target_db: autonomath
-- migration wave24_110_am_entities_vec_v2 (MASTER_PLAN_v1 章 10.1.a — vector
-- 拡張 v2: 全 11,601 searchable program に embed)
--
-- Why this exists:
--   Migration 120 (drop_dead_vec_unifts) GC'd the 1.25 GB legacy
--   am_vec_tier_a / am_vec_tier_b_* sqlite-vec families that were
--   never wired into production routes. The Wave 24 hybrid search
--   path (BM25 + cosine) needs ONE clean, production-shaped vec
--   table covering all 11,601 searchable programs (not just tier S/A
--   like the previous experiment). This migration declares that
--   table.
--
--   Backing the table with sqlite-vec virtual table (vec0 family)
--   gives us native ANN over float[1024] vectors with no ATTACH /
--   external service. The rebuild ETL is
--   `scripts/etl/rebuild_am_entities_vec_v2.py` (subagent batch,
--   intfloat/multilingual-e5-large embedding).
--
-- Schema:
--   * `entity_id INTEGER PRIMARY KEY` — joins to am_entities.rowid
--     (the canonical entity rowid is the SQLite ROWID; see
--     `entity_id_map` view). Vec0 mandates an INTEGER PK.
--   * `embedding float[1024]` — multilingual-e5-large hidden size.
--     Stored as raw float32 little-endian blob managed by vec0.
--
--   The `dim=1024` choice matches the e5-large family (jpintel uses
--   the same model elsewhere — see `tools/offline/embedding/`).
--   Reducing dim later requires a re-embedding pass; raising dim
--   requires a new table (sqlite-vec dim is immutable post-CREATE).
--
-- Idempotency:
--   `CREATE VIRTUAL TABLE IF NOT EXISTS` — re-apply on a populated
--   DB is a no-op. The sqlite-vec extension MUST be loaded before
--   this migration runs; entrypoint.sh §3 loads it via
--   `sqlite3 -cmd '.load /usr/lib/sqlite-vec/vec0.so'`. If the
--   extension is absent at apply time, the CREATE fails with
--   `no such module: vec0` and the migration is left unrecorded so
--   the next boot retries after the operator installs the extension.
--
--   `am_vec_v2_metadata` is a thin sidecar that records when the
--   ETL last refreshed the vectors and how many rows it covered.
--   `INSERT OR IGNORE` makes the seed row idempotent.
--
-- DOWN:
--   See companion `wave24_110_am_entities_vec_v2_rollback.sql`.

PRAGMA foreign_keys = ON;

-- 1. The vec0 virtual table itself. dim=1024 is fixed per
--    intfloat/multilingual-e5-large.
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_v2 USING vec0(
    entity_id INTEGER PRIMARY KEY,
    embedding float[1024]
);

-- 2. ETL bookkeeping sidecar. The rebuild cron updates `last_full_rebuild_at`
--    and `row_count` post-batch so a `/health/deep` probe can surface vector
--    coverage without scanning the vec table.
CREATE TABLE IF NOT EXISTS am_entities_vec_v2_metadata (
    metadata_key       TEXT PRIMARY KEY,
    last_full_rebuild_at TEXT,
    last_delta_at      TEXT,
    row_count          INTEGER,
    embed_model        TEXT NOT NULL DEFAULT 'intfloat/multilingual-e5-large',
    embed_dim          INTEGER NOT NULL DEFAULT 1024,
    notes              TEXT
);

INSERT OR IGNORE INTO am_entities_vec_v2_metadata(metadata_key, embed_model, embed_dim)
VALUES ('singleton', 'intfloat/multilingual-e5-large', 1024);

-- Bookkeeping recorded by entrypoint.sh §4 into schema_migrations.
-- Do NOT INSERT here.
