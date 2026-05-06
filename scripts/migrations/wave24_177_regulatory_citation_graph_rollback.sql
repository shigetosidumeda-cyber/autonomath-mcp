-- target_db: autonomath
-- rollback for wave24_177_regulatory_citation_graph
--
-- DROP VIEWS first (they depend on both tables), then edges (FK references
-- nodes), then nodes. Indexes drop automatically.
--
-- WARNING: dropping reg_node/reg_edge erases the legal citation graph.
-- The companion ETL (scripts/etl/backfill_regulatory_citation_graph.py)
-- can rebuild reg_node from `am_law_article` + e-Gov dumps + NTA 通達
-- index, but the *edge* discovery is partially manual (high-confidence
-- ETL extracts ~70% of citations; the remaining 30% require text-mining
-- pass on bodies and a curator review queue). Re-creation cost: ~12 h
-- ETL + ~2 h curator review per 1k edges.

DROP VIEW IF EXISTS v_reg_program_dependencies;
DROP VIEW IF EXISTS v_reg_penalty_rollup;
DROP VIEW IF EXISTS v_reg_amendment_timeline;
DROP TABLE IF EXISTS reg_edge;
DROP TABLE IF EXISTS reg_node;
