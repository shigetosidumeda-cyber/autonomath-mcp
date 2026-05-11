-- target_db: autonomath
-- migration 215_cross_link_graph_v2
-- generated_at: 2026-05-11
-- author: Wave 15 F1 — cross-link graph hot path index expansion (jpcite v0.3.4)
--
-- ============================================================================
-- BACKGROUND
-- ============================================================================
--   Wave 15 F1 introduces `src/jpintel_mcp/api/graph.py` (REST surface
--   `GET /v1/graph/traverse/{entity_id}`) which executes a 4-hop
--   recursive-CTE walk over `am_relation` joined with `am_entities` +
--   `am_alias`. The existing graph_traverse MCP tool drives the SAME
--   query shape but already enjoys these indexes via Wave 21 mig 082:
--
--     - ix_am_relation_src_type_conf  (source_entity_id, relation_type, confidence DESC)
--     - ix_am_relation_origin         (origin)
--
--   F1 adds a REVERSE walk axis (find entities that cite *into* a given
--   entity) which the existing indexes don't cover — they're keyed on
--   source_entity_id, not target_entity_id. Without a matching index the
--   recursive CTE degenerates to a table scan of 378k rows per hop.
--
-- ============================================================================
-- WHAT THIS MIGRATION DOES
-- ============================================================================
--   1. Adds `ix_am_relation_tgt_type_conf` on
--        (target_entity_id, relation_type, confidence DESC)
--      so the REVERSE walk (`WHERE target_entity_id = ?`) has the same
--      logarithmic cost the forward walk gets from mig 082.
--
--   2. Adds `ix_am_relation_type_conf` on
--        (relation_type, confidence DESC)
--      to support `edge_types=` filters at the recursive root when the
--      caller wants "show me ALL cited-by relationships across the
--      corpus" (no seed entity) — a niche but cheap-to-index axis.
--
-- ============================================================================
-- IDEMPOTENCY
-- ============================================================================
--   * Every CREATE INDEX uses IF NOT EXISTS. Safe to re-apply on every
--     Fly boot via entrypoint.sh §4 (same pattern as mig 082 / 075).
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   Companion: 215_cross_link_graph_v2_rollback.sql drops both indexes.
--   No data side effects — these are pure perf indexes.
--
-- ============================================================================
-- COST
-- ============================================================================
--   Two B-tree indexes over the 378k-row am_relation table = ~12 MB
--   on-disk (8 bytes per row × 2 indexes × overhead). Build time on
--   the 9.4 GB autonomath.db is ~3-5 s — fits inside the Fly boot
--   grace window even on a cold start.

PRAGMA foreign_keys = ON;

-- 1. Reverse-walk hot path (target_entity_id-keyed).
CREATE INDEX IF NOT EXISTS ix_am_relation_tgt_type_conf
    ON am_relation(target_entity_id, relation_type, confidence DESC);

-- 2. Relation-type-only axis for corpus-wide edge-type filters.
CREATE INDEX IF NOT EXISTS ix_am_relation_type_conf
    ON am_relation(relation_type, confidence DESC);

-- Bookkeeping recorded by scripts/migrate.py.
