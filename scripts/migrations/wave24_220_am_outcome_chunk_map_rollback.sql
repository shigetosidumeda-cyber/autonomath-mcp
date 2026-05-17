-- target_db: autonomath
-- rollback: wave24_220_am_outcome_chunk_map
-- generated_at: 2026-05-17
--
-- Rollback drops the two indexes first, then the table. Zero data loss
-- on the rest of the schema; the pre-mapped cache can be rebuilt from
-- scratch by re-running scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_am_outcome_chunk_map_chunk_id;
DROP INDEX IF EXISTS ix_am_outcome_chunk_map_outcome_id;
DROP TABLE IF EXISTS am_outcome_chunk_map;
