-- AutonoMath embedding schema
-- ---------------------------------------------------------------------------
-- Applied by setup.py (or `python -m embedding.setup`) onto autonomath.db.
-- jpintel.db is read-only per user rule; we do NOT touch it.
--
-- sqlite-vec (>=0.1.6) must be loaded before these CREATE VIRTUAL TABLE run.
-- Dimension defaults to 384 (multilingual-e5-small).  If the model changes,
-- bump config.EMBED_DIM AND re-run schema.sql on a fresh DB.
-- ---------------------------------------------------------------------------

-- 1) Canonical entity + facts table (stub -- real schema lives in
--    /tmp/autonomath_infra_2026-04-24/schema/  but for this package we only
--    need the FK target to exist so vector rowids are joinable).
CREATE TABLE IF NOT EXISTS am_entities (
    canonical_id      TEXT PRIMARY KEY,
    topic_id          TEXT NOT NULL,
    primary_name      TEXT,
    authority_name    TEXT,
    prefecture        TEXT,
    tag_json          TEXT,      -- JSON array of tags for filtering
    active_from       TEXT,      -- ISO date
    active_to         TEXT,      -- ISO date or NULL
    source_url        TEXT,
    source_excerpt    TEXT,
    target_entity     TEXT,
    record_json       TEXT,      -- raw record as JSON
    content_hash      TEXT,      -- sha256 of embed input, for idempotency
    inserted_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_am_entities_topic    ON am_entities(topic_id);
CREATE INDEX IF NOT EXISTS idx_am_entities_region   ON am_entities(prefecture);
CREATE INDEX IF NOT EXISTS idx_am_entities_auth     ON am_entities(authority_name);
CREATE INDEX IF NOT EXISTS idx_am_entities_active   ON am_entities(active_from, active_to);

-- 2) Per-facet raw text (kept alongside vectors so we can re-embed without
--    reloading the source JSONL).
CREATE TABLE IF NOT EXISTS am_entity_facets (
    canonical_id  TEXT NOT NULL,
    facet         TEXT NOT NULL,   -- tier_a / tier_b_eligibility / ...
    text          TEXT NOT NULL,
    char_count    INTEGER,
    PRIMARY KEY (canonical_id, facet),
    FOREIGN KEY (canonical_id) REFERENCES am_entities(canonical_id)
);

-- 3) FTS5 BM25 mirror of Tier A text (for hybrid search).
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_fts USING fts5(
    canonical_id UNINDEXED,
    primary_name,
    tier_a_text,
    tokenize = 'trigram'
);

-- ---------------------------------------------------------------------------
-- sqlite-vec virtual tables.
-- vec0 requires dim known at CREATE time.  Parametrised via EMBED_DIM
-- template substitution in setup.py.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS am_vec_tier_a USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS am_vec_tier_b_eligibility USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS am_vec_tier_b_exclusions USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS am_vec_tier_b_dealbreakers USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS am_vec_tier_b_obligations USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);

-- 4) rowid <-> canonical_id map.  sqlite-vec vec0 tables only expose an
--    auto-increment rowid; to join back to am_entities we keep a separate
--    bridge so FK constraints stay clean.
CREATE TABLE IF NOT EXISTS am_vec_rowid_map (
    tier          TEXT NOT NULL,
    rowid         INTEGER NOT NULL,
    canonical_id  TEXT NOT NULL,
    PRIMARY KEY (tier, rowid),
    FOREIGN KEY (canonical_id) REFERENCES am_entities(canonical_id)
);

CREATE INDEX IF NOT EXISTS idx_am_vec_rowid_map_cid
    ON am_vec_rowid_map(canonical_id);

-- 5) Batch run ledger.
CREATE TABLE IF NOT EXISTS am_embed_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    model         TEXT NOT NULL,
    embed_dim     INTEGER NOT NULL,
    record_count  INTEGER,
    vector_count  INTEGER,
    notes         TEXT
);
