-- target_db: autonomath
-- migration 206_entity_id_bridge_v3
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus bridge spine (jpcite v0.3.4)
--
-- Purpose
-- -------
-- 8-source canonical-id bridge for the cross-corpus join layer. Each row
-- records one (source, id_local) -> id_canonical mapping across the 8
-- corpus sources: programs / laws / cases / enforcement / loans / tax /
-- bids / invoice.
--
-- Why not 168 (entity_resolution_bridge_v2) nor 196 (entity_id_bridge)
-- -------------------------------------------------------------------
--   - 168 covers houjin-grade entity resolution with confidence scores +
--     cluster_id semantics.
--   - 196 covers the houjin/invoice/edinet/permit/procurement/law axis with
--     bridge_type enum and validity windows.
--   - This migration adds a third, lighter spine: a flat (source, id_local)
--     -> id_canonical lookup so the 8 cross-corpus join tables (207-214)
--     can resolve each side's id without re-walking the houjin/edinet/etc
--     axis. The 8-source enum is the source-of-truth for "which corpus
--     does this id belong to" and is referenced via CHECK only (no FK so
--     ATTACH-less mirror tables stay decoupled).
--
-- Idempotency
-- -----------
-- All CREATE TABLE / INDEX use IF NOT EXISTS. No seed data; entrypoint.sh
-- §4 self-heal loop applies once + records in schema_migrations.
--
-- DOWN
-- ----
-- Companion: 206_entity_id_bridge_v3_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity_id_bridge_v3 (
    id_local      TEXT NOT NULL,
    id_canonical  TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN (
                      'programs',
                      'laws',
                      'cases',
                      'enforcement',
                      'loans',
                      'tax',
                      'bids',
                      'invoice'
                  )),
    created_at    INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (source, id_local)
);

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_v3_canonical
    ON entity_id_bridge_v3(id_canonical, source);

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_v3_canonical_only
    ON entity_id_bridge_v3(id_canonical);

CREATE INDEX IF NOT EXISTS idx_entity_id_bridge_v3_created_at
    ON entity_id_bridge_v3(created_at);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
