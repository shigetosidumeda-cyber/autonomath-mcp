-- target_db: autonomath
-- migration: 239_am_knowledge_graph_vec_index
-- generated_at: 2026-05-12
-- author: Wave 34 Axis 4e — 503,930 entity sqlite-vec embed index expansion
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- 既存 am_entities_vec_S/C/J (program/case/court) を 全 12 record_kind に
-- 拡張する index 層。vec0 virtual table は本 migration では create せず、
-- embed_knowledge_graph_vec.py が runtime で都度 ensure する
-- (vec0 syntax と CREATE...IF NOT EXISTS の互換性回避)。

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS am_entities_vec_embed_log (
    canonical_id TEXT NOT NULL,
    record_kind TEXT NOT NULL,
    embed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    embed_dim INTEGER NOT NULL CHECK (embed_dim > 0),
    model_name TEXT NOT NULL,
    model_version TEXT,
    text_hash TEXT,
    PRIMARY KEY (canonical_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_embed_log_kind
    ON am_entities_vec_embed_log(record_kind, embed_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_embed_log_at
    ON am_entities_vec_embed_log(embed_at DESC);

CREATE TABLE IF NOT EXISTS am_entities_vec_refresh_log (
    refresh_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('full','incremental')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    entities_processed INTEGER NOT NULL DEFAULT 0,
    entities_skipped INTEGER NOT NULL DEFAULT 0,
    embed_dim INTEGER,
    model_name TEXT,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_refresh_log_started
    ON am_entities_vec_refresh_log(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_entities_vec_refresh_log_mode
    ON am_entities_vec_refresh_log(mode, started_at DESC);

COMMIT;
