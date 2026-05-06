-- target_db: autonomath
-- migration 162_am_entity_pagerank
--
-- PageRank centrality per `am_entities.canonical_id`.
--
-- W22-9 shipped a simple density_score = z-axis sum (verification + edge
-- + fact + alias + adoption - enforcement). That signal is local: it
-- tells you how many neighbors an entity has, not how *important* those
-- neighbors are. PageRank closes the gap. It propagates centrality
-- iteratively over the directed `am_relation` graph so an entity wired
-- to other high-centrality entities scores higher than an entity wired
-- to the same number of leaf entities.
--
-- Used by relevance ranking on the read path (one PRIMARY-KEY lookup
-- per entity), audit-pack curation, and customer-LLM search re-ranking.
-- Sits alongside `am_entity_density_score` (mig 158): density is the
-- raw axis rollup, pagerank is the graph-aware centrality.
--
-- Column semantics (per canonical_id):
--   * pagerank_score   -- networkx.pagerank(alpha=0.85) result; sums
--                        to 1.0 across the entire entity population.
--   * pagerank_rank    -- dense rank over pagerank_score DESC
--                        (1 = highest centrality).
--   * in_degree        -- raw inbound edge count from am_relation.
--   * out_degree       -- raw outbound edge count from am_relation.
--   * last_updated     -- datetime('now') stamp from populator.
--
-- Algorithm (computed in companion populator, not here):
--   1. Build directed graph from every am_relation row where
--      target_entity_id IS NOT NULL.
--   2. Add every am_entities.canonical_id as a node so isolated
--      entities still receive the baseline (1-alpha)/N score.
--   3. networkx.pagerank(graph, alpha=0.85) — power iteration, no LLM.
--
-- Idempotent: CREATE * IF NOT EXISTS. Populator wraps INSERT OR REPLACE
-- in a single transaction. Safe to re-apply on every Fly boot via
-- entrypoint.sh §4.
--
-- DOWN: see companion `162_am_entity_pagerank_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_entity_pagerank (
    entity_id       TEXT PRIMARY KEY,
    pagerank_score  REAL,
    pagerank_rank   INTEGER,
    in_degree       INTEGER DEFAULT 0,
    out_degree      INTEGER DEFAULT 0,
    last_updated    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_pagerank_score
    ON am_entity_pagerank(pagerank_score DESC);

CREATE INDEX IF NOT EXISTS ix_pagerank_rank
    ON am_entity_pagerank(pagerank_rank);
