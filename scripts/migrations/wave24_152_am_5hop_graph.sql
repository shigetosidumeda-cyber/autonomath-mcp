-- target_db: autonomath
-- migration wave24_152_am_5hop_graph
--   (Wave 24 §152 — pre-computed 5-hop graph traversal materialized
--    view over the heterogeneous KG so an agent can ask
--    "制度 X の根拠法 → その通達 → その通達に基づく裁決 → 関連判例"
--    in 1 RPC instead of 5+ recursive CTE walks.)
--
-- Why a separate mat-view (not just a CTE on top of v_am_relation_all)
-- -------------------------------------------------------------------
-- v_am_relation_all carries 378k rows across 15 relation_types. A naive
-- 5-deep recursive CTE blows up to O(N^5) cost for hub seeds (例:
-- IT2026 program 1,822 outdegree → ~10^13 candidate paths). Even with
-- the existing graph_traverse fan-out cap at depth=3, a 5-hop walk
-- requires either (a) per-call client-side cache, (b) per-seed
-- precompute. We choose (b): bake the walk for the top N seed entities
-- so the MCP tool is O(1) lookup at request time.
--
-- The mat-view also bridges three NON-am_relation evidence sources
-- (program_law_refs, nta_tsutatsu_index, nta_saiketsu) into a single
-- (start, end, hop, path, edge_kinds) tuple — without the mat-view the
-- agent has to know the schema of all four substrates AND join them
-- itself, which defeats the "1 RPC" zero-touch contract.
--
-- Schema
-- ------
-- * start_entity_id  — canonical_id of the seed (e.g. program: prefix
--                      from am_entities, law: prefix from
--                      nta_tsutatsu_index.law_canonical_id, etc.)
-- * hop              — 1..5, distance from start in canonical edges
-- * end_entity_id    — canonical_id of the destination at this hop
-- * path             — JSON array of intermediate canonical_ids
--                      (length == hop - 1; empty array '[]' at hop=1)
-- * edge_kinds       — JSON array of relation_type strings, one per
--                      hop traversed (length == hop). Includes
--                      'derived_keyword' for FTS-overlap edges where
--                      no direct foreign-key relation exists.
--
-- Idempotency
-- -----------
-- * CREATE TABLE IF NOT EXISTS  — re-apply on every Fly boot is no-op
-- * CREATE INDEX IF NOT EXISTS  — same
--
-- Population
-- ----------
-- Populated by scripts/etl/build_5hop_graph.py per Wave 24 §152 task.
-- Initial run: top 100 tier-S programs (sample). Full populate is a
-- separate wave (cost-bounded by the per-seed 5-hop fan-out budget).
--
-- Composability
-- -------------
-- The new MCP tool traverse_graph_5hop (mcp/autonomath_tools/
-- graph_5hop.py) reads exclusively from this table — pure SQL, no
-- recursive CTE at request time, p95 << 50 ms.

CREATE TABLE IF NOT EXISTS am_5hop_graph (
    start_entity_id  TEXT NOT NULL,
    hop              INTEGER NOT NULL CHECK (hop BETWEEN 1 AND 5),
    end_entity_id    TEXT NOT NULL,
    path             TEXT NOT NULL,
    edge_kinds       TEXT,
    PRIMARY KEY (start_entity_id, end_entity_id, hop)
);

CREATE INDEX IF NOT EXISTS ix_5hop_start
    ON am_5hop_graph(start_entity_id);

CREATE INDEX IF NOT EXISTS ix_5hop_end
    ON am_5hop_graph(end_entity_id);

CREATE INDEX IF NOT EXISTS ix_5hop_start_hop
    ON am_5hop_graph(start_entity_id, hop);
