-- target_db: autonomath
-- migration 210_law_amendment_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: laws x am_amendment_snapshot. One row per (law_id, snapshot)
-- amendment event with `effective_from` (ISO date) + `diff_type`. Provides
-- a stable spine to walk law amendment history without re-scanning the
-- 14,596-row am_amendment_snapshot table by hash.
--
-- diff_type enum
-- --------------
--   - 'article_added'   : new article inserted
--   - 'article_removed' : article struck
--   - 'article_revised' : in-place text change
--   - 'article_renumbered' : same text, new article_no
--   - 'metadata_only'   : effective_from / version metadata only
--
-- FK note
-- -------
-- jpi_laws.unified_id (TEXT) is the canonical mirror key. amendment_id is
-- a free-form TEXT (typically am_amendment_snapshot.snapshot_id) and is
-- not FK'd to keep the spine append-only across snapshot rebuilds.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 210_law_amendment_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS law_amendment_refs (
    law_id          TEXT NOT NULL REFERENCES jpi_laws(unified_id),
    amendment_id    TEXT NOT NULL,
    effective_from  TEXT,
    diff_type       TEXT NOT NULL CHECK (diff_type IN (
                        'article_added',
                        'article_removed',
                        'article_revised',
                        'article_renumbered',
                        'metadata_only'
                    )),
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (law_id, amendment_id)
);

CREATE INDEX IF NOT EXISTS idx_law_amendment_refs_amendment
    ON law_amendment_refs(amendment_id);

CREATE INDEX IF NOT EXISTS idx_law_amendment_refs_effective
    ON law_amendment_refs(effective_from)
    WHERE effective_from IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_law_amendment_refs_diff_type
    ON law_amendment_refs(diff_type);

CREATE INDEX IF NOT EXISTS idx_law_amendment_refs_created_at
    ON law_amendment_refs(created_at);
