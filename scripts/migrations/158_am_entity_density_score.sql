-- target_db: autonomath
-- migration 158_am_entity_density_score
--
-- Knowledge-graph density score per `am_entities.canonical_id`.
--
-- Pre-aggregated per-entity rollup of how richly each canonical entity is
-- wired into the autonomath knowledge graph. The score combines six
-- z-normalized axes (verification / edge / fact / alias / adoption /
-- enforcement) into a single density_score; enforcement carries a
-- *negative* weight so that high-enforcement entities sink rather than
-- rise.
--
-- Axes (per canonical_id, NULLs counted as 0):
--   * verification_count -- distinct am_entity_source rows (independent
--                          source corroborations)
--   * edge_count         -- am_relation rows where the entity appears as
--                          either source_entity_id or target_entity_id
--   * fact_count         -- am_entity_facts rows (EAV facts)
--   * alias_count        -- am_alias rows where entity_table='am_entities'
--   * adoption_count     -- inbound am_relation edges originating from
--                          record_kind='adoption' entities
--   * enforcement_count  -- am_enforcement_detail rows linking to entity
--
-- density_score formula (computed in the companion populator, not here):
--   density_score =
--       z(verification_count) + z(edge_count) + z(fact_count)
--     + z(alias_count)        + z(adoption_count)
--     - z(enforcement_count)              -- NEGATIVE weight
--
-- density_rank: dense_rank over density_score DESC (1 = highest density).
--
-- Idempotent: CREATE * IF NOT EXISTS. Populator uses INSERT OR REPLACE
-- keyed on entity_id. Safe to re-apply on every Fly boot via
-- entrypoint.sh §4.
--
-- DOWN: see companion `158_am_entity_density_score_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_entity_density_score (
    entity_id           TEXT PRIMARY KEY,
    record_kind         TEXT,
    verification_count  INTEGER DEFAULT 0,
    edge_count          INTEGER DEFAULT 0,
    fact_count          INTEGER DEFAULT 0,
    alias_count         INTEGER DEFAULT 0,
    adoption_count      INTEGER DEFAULT 0,
    enforcement_count   INTEGER DEFAULT 0,
    density_score       REAL,
    density_rank        INTEGER,
    last_updated        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_density_score
    ON am_entity_density_score(density_score DESC);

CREATE INDEX IF NOT EXISTS ix_density_score_kind
    ON am_entity_density_score(record_kind, density_score DESC);

CREATE INDEX IF NOT EXISTS ix_density_score_rank
    ON am_entity_density_score(density_rank);
