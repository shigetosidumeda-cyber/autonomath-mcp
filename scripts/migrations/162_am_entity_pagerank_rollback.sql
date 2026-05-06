-- target_db: autonomath
-- migration 162_am_entity_pagerank rollback
--
-- DOWN companion for 162_am_entity_pagerank.sql. Manual review only —
-- entrypoint.sh §4 explicitly excludes any filename containing
-- `_rollback` so this file never runs on boot.

DROP INDEX IF EXISTS ix_pagerank_rank;
DROP INDEX IF EXISTS ix_pagerank_score;
DROP TABLE IF EXISTS am_entity_pagerank;
