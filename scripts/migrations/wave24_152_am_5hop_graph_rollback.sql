-- target_db: autonomath
-- rollback for wave24_152_am_5hop_graph
DROP INDEX IF EXISTS ix_5hop_start_hop;
DROP INDEX IF EXISTS ix_5hop_end;
DROP INDEX IF EXISTS ix_5hop_start;
DROP TABLE IF EXISTS am_5hop_graph;
