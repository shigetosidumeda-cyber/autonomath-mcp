-- target_db: autonomath
-- migration 067_dataset_versioning_autonomath (R8 — autonomath.db side)
--
-- Companion to 067_dataset_versioning.sql (jpintel.db side). Adds the
-- same valid_from / valid_until bitemporal columns + composite index to
-- the autonomath.db core EAV tables so the snapshot tool can pin
-- am_entities / am_entity_facts queries to a historical date.
--
-- Tables covered:
--   am_entities       — backfill from fetched_at (single timestamp column)
--   am_entity_facts   — backfill from observed_at if present, else
--                       fact_id-derived datetime('now') sentinel
--                       (writer must populate going forward)
--
-- Append-only updates (close prior row's valid_until + INSERT a new row)
-- are the canonical pattern; this migration is schema + index only.
--
-- DOWN: not provided — versioning columns persist for audit trail.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_entities
-- ============================================================================
ALTER TABLE am_entities ADD COLUMN valid_from TEXT;
ALTER TABLE am_entities ADD COLUMN valid_until TEXT;

-- Backfill: am_entities.fetched_at is the single ingestion timestamp on
-- this table (per the schema header in CLAUDE.md). When NULL, fall back
-- to a fixed sentinel matching the bulk-load completion date. The
-- migration runner is idempotent at the row-set level — re-applying the
-- UPDATE is a no-op since `valid_from IS NULL` shrinks to zero.
UPDATE am_entities
   SET valid_from = COALESCE(fetched_at, '2026-04-25T00:00:00Z')
 WHERE valid_from IS NULL;

CREATE INDEX IF NOT EXISTS ix_am_entities_valid
    ON am_entities(valid_from, valid_until);

-- ============================================================================
-- am_entity_facts
-- ============================================================================
ALTER TABLE am_entity_facts ADD COLUMN valid_from TEXT;
ALTER TABLE am_entity_facts ADD COLUMN valid_until TEXT;

-- am_entity_facts has no canonical fetched_at; backfill is a fixed
-- sentinel for the bulk-load completion date. New facts written after
-- this migration must populate valid_from at INSERT time (writer change
-- lands in the ingest CLIs, tracked in COORDINATION).
UPDATE am_entity_facts
   SET valid_from = '2026-04-25T00:00:00Z'
 WHERE valid_from IS NULL;

CREATE INDEX IF NOT EXISTS ix_am_entity_facts_valid
    ON am_entity_facts(valid_from, valid_until);

-- Bookkeeping recorded by scripts/migrate.py.
